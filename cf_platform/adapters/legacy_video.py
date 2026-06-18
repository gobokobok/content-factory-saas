"""Legacy video adapter — the ONLY cf_platform module that imports src/ (D047).

Bridges the platform orchestrator to the legacy Script→Video pipeline by chaining
the per-step domain functions from src/ in-process.  Emits TraceEvents per step;
never emits platform artifacts (D050, D057).

HTTP-swappable: `LegacyVideoAdapter` is a Protocol — replace
`InProcessLegacyVideoAdapter` with an HTTP client impl in the future with zero
caller changes (D047 §sequencing-watch-outs #4).
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Literal, Optional, Protocol

from pydantic import BaseModel

from cf_platform.core.schemas import TraceEvent
from cf_platform.core.trace_repo import TraceEventRepository

# ── src/ imports — ONLY this module may import from src/ (D047) ───────────────
from src.acquisition import MIN_ACQUIRED_FOR_COMPLETE, run_acquisition
from src.ffmpeg_builder import build_ffmpeg_script
from src.manifest import build_manifest
from src.models import AssetManifest, Storyboard, VideoSettings
from src.pexels import PexelsClient
from src.replicate_client import ReplicateClient
from src.renderer import render_run
from src.storyboard import generate_storyboard
from src.storage import R2Client
from src.tts import generate_tts

if TYPE_CHECKING:
    from src.config import Settings

logger = logging.getLogger(__name__)

_WORKER = "legacy_render"


class VideoResult(BaseModel):
    """Result returned by the legacy video adapter after a render attempt."""

    r2_key: str
    legacy_run_id: str
    status: Literal["complete", "failed"]
    error: Optional[str] = None


class LegacyVideoAdapter(Protocol):
    """Protocol for the legacy Script→Video adapter (D047).

    The in-process impl chains src/ domain functions directly.
    An HTTP-backed impl can be swapped in later with zero caller changes.
    """

    async def render(
        self,
        run_id: str,
        script: str,
        trace_repo: TraceEventRepository,
    ) -> VideoResult:
        """Run the full legacy render pipeline and return the video result."""
        ...


class InProcessLegacyVideoAdapter:
    """In-process impl of LegacyVideoAdapter.

    Chains six legacy steps: [TTS?] → storyboard → manifest → acquisition →
    ffmpeg-script → render.  Uses the platform run_id as the legacy R2 prefix
    so lineage is 1:1.  ElevenLabs TTS is attempted when credentials are present;
    skipped otherwise (video renders with storyboard-duration pacing, no audio).
    """

    def __init__(self, settings: Optional["Settings"] = None) -> None:
        """Load src.config.Settings lazily when not injected (supports test injection)."""
        if settings is None:
            from src.config import get_settings

            settings = get_settings()
        self._settings = settings

    def _make_storage(self) -> R2Client:
        """Construct an R2Client from the injected settings."""
        s = self._settings
        return R2Client(
            account_id=s.R2_ACCOUNT_ID,
            access_key_id=s.R2_ACCESS_KEY_ID,
            secret_access_key=s.R2_SECRET_ACCESS_KEY,
            bucket_name=s.R2_BUCKET_NAME,
        )

    async def _trace(
        self,
        trace_repo: TraceEventRepository,
        run_id: str,
        source: str,
        op: str,
        latency_ms: int,
        status: Literal["ok", "error"],
        meta: Optional[dict] = None,
    ) -> None:
        """Record one TraceEvent to the repo (non-fatal on failure)."""
        try:
            await trace_repo.record(
                TraceEvent(
                    run_id=run_id,
                    worker=_WORKER,
                    source=source,
                    op=op,
                    latency_ms=latency_ms,
                    status=status,
                    meta=meta or {},
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to record trace event %s/%s for run %s: %s", source, op, run_id, exc)

    async def render(
        self,
        run_id: str,
        script: str,
        trace_repo: TraceEventRepository,
    ) -> VideoResult:
        """Chain legacy steps and return the R2 key for the finished video.

        Each step emits a TraceEvent.  On any step failure, returns a VideoResult
        with status='failed' and the error message from that step.
        """
        s = self._settings
        storage = self._make_storage()

        # ── 0. Bootstrap legacy run prefix in R2 ─────────────────────────
        storage.create_run_folder(run_id, project_name="platform-run")
        storage.upload_text(f"runs/{run_id}/script.txt", script)

        # ── 1. TTS — optional; non-fatal on failure ───────────────────────
        if s.ELEVENLABS_API_KEY and s.ELEVENLABS_VOICE_ID:
            t0 = time.monotonic()
            try:
                mp3_bytes, _ = await generate_tts(
                    script,
                    api_key=s.ELEVENLABS_API_KEY,
                    voice_id=s.ELEVENLABS_VOICE_ID,
                )
                storage.upload_bytes(
                    f"runs/{run_id}/voiceover/generated.mp3",
                    mp3_bytes,
                    content_type="audio/mpeg",
                )
                await self._trace(
                    trace_repo, run_id, "tts", "generate",
                    int((time.monotonic() - t0) * 1000), "ok",
                )
            except Exception as exc:
                await self._trace(
                    trace_repo, run_id, "tts", "generate",
                    int((time.monotonic() - t0) * 1000), "error", {"error": str(exc)},
                )
                logger.warning(
                    "TTS failed for run %s — continuing without voiceover: %s", run_id, exc
                )

        # ── 2. Storyboard ─────────────────────────────────────────────────
        t0 = time.monotonic()
        try:
            storyboard, validation = await generate_storyboard(script, s, None)
            storyboard_data = storyboard.model_dump(by_alias=True, mode="json")
            storage.upload_json(f"runs/{run_id}/storyboard.json", storyboard_data)
            await self._trace(
                trace_repo, run_id, "storyboard", "generate",
                int((time.monotonic() - t0) * 1000), "ok",
                {"cost_usd": validation.cost_usd},
            )
        except Exception as exc:
            await self._trace(
                trace_repo, run_id, "storyboard", "generate",
                int((time.monotonic() - t0) * 1000), "error", {"error": str(exc)},
            )
            return VideoResult(
                r2_key="", legacy_run_id=run_id, status="failed",
                error=f"storyboard: {exc}",
            )

        # ── 3. Manifest ───────────────────────────────────────────────────
        t0 = time.monotonic()
        try:
            manifest = build_manifest(run_id, storyboard_data)
            storage.upload_json(
                f"runs/{run_id}/asset_manifest.json",
                manifest.model_dump(mode="json"),
            )
            await self._trace(
                trace_repo, run_id, "manifest", "build",
                int((time.monotonic() - t0) * 1000), "ok",
            )
        except Exception as exc:
            await self._trace(
                trace_repo, run_id, "manifest", "build",
                int((time.monotonic() - t0) * 1000), "error", {"error": str(exc)},
            )
            return VideoResult(
                r2_key="", legacy_run_id=run_id, status="failed",
                error=f"manifest: {exc}",
            )

        # ── 4. Asset acquisition ──────────────────────────────────────────
        t0 = time.monotonic()
        try:
            pexels = PexelsClient(api_key=s.PEXELS_API_KEY, per_page=s.PEXELS_PER_PAGE)
            replicate = ReplicateClient(
                api_token=s.REPLICATE_API_TOKEN,
                model=s.REPLICATE_FLUX_MODEL,
                poll_interval_seconds=s.REPLICATE_POLL_INTERVAL_SECONDS,
                max_poll_attempts=s.REPLICATE_MAX_POLL_ATTEMPTS,
            )
            summary = await run_acquisition(
                run_id,
                manifest,
                pexels,
                replicate,
                storage,
                pexels_only=s.ACQUISITION_PEXELS_ONLY,
            )
            if summary["acquired"] < MIN_ACQUIRED_FOR_COMPLETE:
                raise RuntimeError(
                    f"Too few assets acquired: {summary['acquired']} of {len(manifest.entries)}"
                )
            storage.upload_json(
                f"runs/{run_id}/asset_manifest.json",
                manifest.model_dump(mode="json"),
            )
            await self._trace(
                trace_repo, run_id, "acquisition", "acquire_assets",
                int((time.monotonic() - t0) * 1000), "ok", summary,
            )
        except Exception as exc:
            await self._trace(
                trace_repo, run_id, "acquisition", "acquire_assets",
                int((time.monotonic() - t0) * 1000), "error", {"error": str(exc)},
            )
            return VideoResult(
                r2_key="", legacy_run_id=run_id, status="failed",
                error=f"acquisition: {exc}",
            )

        # ── 5. FFmpeg script ──────────────────────────────────────────────
        t0 = time.monotonic()
        try:
            storyboard_obj = Storyboard.model_validate(storyboard_data)
            ffmpeg_script = build_ffmpeg_script(
                run_id, storyboard_obj, manifest, None, video_settings=VideoSettings()
            )
            storage.upload_text(
                f"runs/{run_id}/ffmpeg_script.sh",
                ffmpeg_script,
                content_type="text/x-shellscript",
            )
            await self._trace(
                trace_repo, run_id, "ffmpeg_script", "build",
                int((time.monotonic() - t0) * 1000), "ok",
            )
        except Exception as exc:
            await self._trace(
                trace_repo, run_id, "ffmpeg_script", "build",
                int((time.monotonic() - t0) * 1000), "error", {"error": str(exc)},
            )
            return VideoResult(
                r2_key="", legacy_run_id=run_id, status="failed",
                error=f"ffmpeg_script: {exc}",
            )

        # ── 6. Render ─────────────────────────────────────────────────────
        t0 = time.monotonic()
        try:
            total_duration_s = storyboard_data.get("summary", {}).get("total_duration_s", 0)
            total_frames = int(total_duration_s * 25)
            result = await asyncio.to_thread(
                render_run, run_id, manifest, storage, s.FFMPEG_TIMEOUT_SECONDS, total_frames
            )
            if result["status"] != "complete":
                raise RuntimeError(f"FFmpeg exit code {result.get('exit_code', -1)}")
            r2_key: str = result["output_key"]
            await self._trace(
                trace_repo, run_id, "render", "render",
                int((time.monotonic() - t0) * 1000), "ok", {"output_key": r2_key},
            )
        except Exception as exc:
            await self._trace(
                trace_repo, run_id, "render", "render",
                int((time.monotonic() - t0) * 1000), "error", {"error": str(exc)},
            )
            return VideoResult(
                r2_key="", legacy_run_id=run_id, status="failed",
                error=f"render: {exc}",
            )

        return VideoResult(r2_key=r2_key, legacy_run_id=run_id, status="complete")
