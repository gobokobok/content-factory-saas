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
from src.ffmpeg_builder import (
    assign_words_to_scenes,
    build_ffmpeg_script,
    compute_scene_durations_from_alignment,
    redistribute_scene_durations,
)
from src.manifest import build_manifest
from src.models import AssetManifest, Storyboard, VideoSettings, WordTimestamp as SrcWordTimestamp
from src.pexels import PexelsClient
from src.pixabay_client import PixabayClient
from src.renderer import render_run
from src.wikimedia_client import WikimediaClient
from src.storyboard import generate_storyboard
from src.storage import R2Client

# ── Platform imports (D047 one-directional: src/ never imports cf_platform/) ──
from cf_platform.workers.voice_production import VoiceAlignmentArtifact

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
        *,
        voice_alignment: Optional[VoiceAlignmentArtifact] = None,
    ) -> VideoResult:
        """Run the full legacy render pipeline and return the video result.

        voice_alignment: when provided by voice_production_worker, TTS is skipped
        (MP3 already at runs/{run_id}/voiceover/generated.mp3) and word timestamps
        are used for scene-timing and caption sync.
        """
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
        *,
        voice_alignment: Optional[VoiceAlignmentArtifact] = None,
    ) -> VideoResult:
        """Chain legacy steps and return the R2 key for the finished video.

        Each step emits a TraceEvent.  On any step failure, returns a VideoResult
        with status='failed' and the error message from that step.

        When voice_alignment is provided (from voice_production_worker), TTS is
        skipped and word timestamps are used for storyboard timing and captions.
        Without voice_alignment, TTS is attempted if ElevenLabs credentials exist.
        """
        s = self._settings
        storage = self._make_storage()

        # ── 0. Bootstrap legacy run prefix in R2 ─────────────────────────
        storage.create_run_folder(run_id, project_name="platform-run")
        storage.upload_text(f"runs/{run_id}/script.txt", script)

        # ── 1. TTS — always handled by voice_production_worker (P6-S7) ───
        # voice_production_worker runs before this adapter and uploads
        # runs/{run_id}/voiceover/generated.mp3; render_run picks it up
        # automatically.  When voice_alignment is None (no worker ran),
        # the render continues without a voiceover (silent video).
        if voice_alignment is None:
            logger.info("No voice_alignment for run %s — rendering without voiceover", run_id)

        # ── 1b. Convert platform timestamps to src timestamps ─────────────
        src_timestamps: Optional[list[SrcWordTimestamp]] = None
        if voice_alignment and voice_alignment.word_timestamps:
            src_timestamps = [
                SrcWordTimestamp(
                    word=wt.word,
                    start_ms=wt.start_ms,
                    end_ms=wt.end_ms,
                    confidence=wt.confidence,
                )
                for wt in voice_alignment.word_timestamps
            ]

        # ── 2. Storyboard ─────────────────────────────────────────────────
        t0 = time.monotonic()
        try:
            storyboard, validation = await generate_storyboard(script, s, src_timestamps)
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
            pixabay = PixabayClient(api_key=s.PIXABAY_API_KEY) if s.PIXABAY_API_KEY else None
            wikimedia = WikimediaClient()
            summary = await run_acquisition(
                run_id,
                manifest,
                pexels,
                pixabay,
                storage,
                wikimedia=wikimedia,
                batch_size=s.ACQUISITION_BATCH_SIZE,
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
            scene_words = assign_words_to_scenes(storyboard_obj.scenes, src_timestamps) if src_timestamps else None

            # Correct scene durations to match actual VO length so visuals don't
            # freeze before audio ends.  Mirrors the logic in routes/ffmpeg_script.py.
            if src_timestamps and voice_alignment and voice_alignment.alignment_method == "deepgram_nova2":
                # Derive per-scene duration from real word timestamps.
                adjusted = compute_scene_durations_from_alignment(storyboard_obj.scenes, scene_words)
                storyboard_obj = storyboard_obj.model_copy(update={"scenes": adjusted})
            elif voice_alignment and voice_alignment.total_duration_s > 0:
                # Proportional fallback: stretch all scenes to cover the full VO.
                adjusted = redistribute_scene_durations(storyboard_obj.scenes, voice_alignment.total_duration_s)
                storyboard_obj = storyboard_obj.model_copy(update={"scenes": adjusted})

            ffmpeg_script = build_ffmpeg_script(
                run_id, storyboard_obj, manifest, scene_words, video_settings=VideoSettings(aspect_ratio="16:9")
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
