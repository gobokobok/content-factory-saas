"""Studio routes for an uploaded voiceover (P14b).

    POST  /studio/runs/{run_id}/voice/upload   store the audio, start transcription
    GET   /studio/runs/{run_id}/transcript     words, timing, audio URL, editability
    PATCH /studio/runs/{run_id}/transcript     timing-safe word edits (S2)

Transcription is a background job polled through the existing
GET /studio/runs/{run_id}/voice/status. The transcript is stored twice, deliberately:
as the run's `voice_alignment` artifact (words and timing — what the storyboard,
timeline, render and CapCut export already read) and as its `script` artifact with
`source: uploaded_vo` (so GET .../script returns it and nothing reads another place).
Routes are thin: validation and edit rules live in workers/voice_upload.py and
workers/transcript_edit.py.
"""

import logging
import time
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact, write_artifact
from cf_platform.core.config import PlatformSettings
from cf_platform.core.run_manager import RunNotFoundError, RunRepository
from cf_platform.core.schemas import LineageEnvelope, RunRecord, StageState, TraceEvent
from cf_platform.core.trace_repo import TraceEventRepository
from cf_platform.interfaces.dependencies import (
    PLATFORM_USER_ID,
    get_artifact_storage,
    get_effective_platform_settings,
    get_run_repository,
    get_trace_event_repository,
)
from cf_platform.interfaces.routes._helpers import DISCARDED_STORYBOARD_MARKER
from cf_platform.interfaces.routes._helpers import latest_artifact_key as _latest_artifact_key
from cf_platform.workers.script_packager import ScriptArtifact
from cf_platform.workers.transcript_edit import (
    TranscriptEditError,
    WordEdit,
    apply_word_edits,
    describe_edits,
    edits_from_text,
    transcript_text,
)
from cf_platform.workers.voice_production import VoiceAlignmentArtifact
from cf_platform.workers.voice_upload import (
    DEFAULT_LANGUAGE,
    UPLOADED_ALIGNMENT_METHOD,
    UPLOADED_SCRIPT_SOURCE,
    VOICE_UPLOAD_REGISTRATION,
    VoiceUploadError,
    build_voice_upload_worker,
    content_type_for,
    language_warning,
    validate_voice_upload,
)

_logger = logging.getLogger(__name__)

router = APIRouter()

UPLOADED_VOICE_SOURCE = "uploaded"


def _job_key(run_id: str) -> str:
    """Storage key of the run's voice job record (shared with generated voice)."""
    return f"runs/{run_id}/voice/current_job.json"


def run_language(run: RunRecord | None) -> str:
    """The run's language (ISO 639-1); English for a run created before the language seed."""
    return str((run.inputs.get("language") if run else None) or DEFAULT_LANGUAGE)


async def _require_uploaded_run(run_id: str, runs: RunRepository) -> RunRecord:
    """Return the run, or raise 409 unless it was created with the 'Upload voiceover' entry mode."""
    try:
        run = await runs.get(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=409, detail="This run was not created with an uploaded voiceover.") from None
    if run.inputs.get("voice_source") != UPLOADED_VOICE_SOURCE:
        raise HTTPException(status_code=409, detail="This run was not created with an uploaded voiceover.")
    return run


async def _write_transcript_artifacts(
    storage: ArtifactStorage, run_id: str, alignment: VoiceAlignmentArtifact, worker: str
) -> None:
    """Write the voice_alignment artifact and the script artifact derived from its words."""
    lineage = LineageEnvelope(
        run_id=run_id,
        worker=worker,
        worker_version=VOICE_UPLOAD_REGISTRATION.worker_version,
        prompt_version=VOICE_UPLOAD_REGISTRATION.prompt_version,
        model=VOICE_UPLOAD_REGISTRATION.model,
        created_at=datetime.now(),
    )
    await write_artifact(
        storage, alignment, name="voice_alignment", stage="voice",
        run_id=run_id, user_id=PLATFORM_USER_ID, lineage=lineage,
    )
    text = transcript_text(alignment.word_timestamps)
    script = ScriptArtifact(
        idea_title="", niche=None, script=text, word_count=len(alignment.word_timestamps),
        status="ok", generated_at=datetime.now(), source=UPLOADED_SCRIPT_SOURCE,
    )
    await write_artifact(
        storage, script, name="script", stage="script",
        run_id=run_id, user_id=PLATFORM_USER_ID, lineage=lineage,
    )


async def _record_trace(trace_events: TraceEventRepository, event: TraceEvent) -> None:
    """Best-effort TraceEvent write — observability must never fail the operator's action."""
    try:
        await trace_events.record(event)
    except Exception:
        _logger.warning("trace_events.record failed for run %s", event.run_id, exc_info=True)


async def _run_transcription_background(
    run_id: str,
    job_id: str,
    state: StageState,
    worker: Any,
    storage: ArtifactStorage,
    trace_events: TraceEventRepository,
    cost_per_min_usd: float,
    low_confidence: float,
) -> None:
    """Background task: transcribe, write the artifacts, update voice/current_job.json.

    A transcript that looks like it is in another language than the run's still
    completes; the job record carries a `language_warning` for Studio to show.
    """
    t0 = time.monotonic()
    try:
        output = await worker(state)
        alignment = output.artifact
        if not isinstance(alignment, VoiceAlignmentArtifact):
            raise RuntimeError(f"Voice upload worker returned unexpected type: {type(alignment)}")
        await _write_transcript_artifacts(storage, run_id, alignment, "voice_upload")
        warning = language_warning(
            alignment.word_timestamps, state.inputs.get("language") or DEFAULT_LANGUAGE, low_confidence
        )
        await storage.put_json(_job_key(run_id), {
            "job_id": job_id,
            "status": "complete",
            "alignment_method": alignment.alignment_method,
            "total_duration_s": alignment.total_duration_s,
            "word_count": len(alignment.word_timestamps),
            "language_warning": warning,
        })
        await _record_trace(trace_events, TraceEvent(
            run_id=run_id, worker="voice_upload", source="deepgram", op="transcribe",
            latency_ms=int((time.monotonic() - t0) * 1000),
            cost_usd=round(alignment.total_duration_s / 60 * cost_per_min_usd, 6),
            status="ok",
            meta={
                "duration_s": alignment.total_duration_s, "word_count": len(alignment.word_timestamps),
                "language": state.inputs.get("language"), "language_warning": warning,
            },
        ))
    except Exception as exc:
        # VoiceUploadError carries an operator-readable message; anything else is a bug
        # the log needs the traceback for.
        if isinstance(exc, VoiceUploadError):
            _logger.warning("Voice upload job failed for run %s: %s", run_id, exc)
        else:
            _logger.exception("Voice upload job crashed for run %s", run_id)
        message = str(exc) if isinstance(exc, VoiceUploadError) else f"Transcription failed: {exc}"
        try:
            await storage.put_json(_job_key(run_id), {"job_id": job_id, "status": "error", "error": message})
        except Exception:
            _logger.exception("Could not record the voice job error for run %s", run_id)
        await _record_trace(trace_events, TraceEvent(
            run_id=run_id, worker="voice_upload", source="deepgram", op="transcribe",
            latency_ms=int((time.monotonic() - t0) * 1000), status="error", meta={"error": message[:300]},
        ))


async def _current_alignment(storage: ArtifactStorage, run_id: str) -> VoiceAlignmentArtifact | None:
    """Return the latest voice_alignment of the run, or None when there is none."""
    key = await _latest_artifact_key(storage, run_id, "voice", "voice_alignment")
    if not key:
        return None
    _, body = await read_artifact(storage, key)
    return VoiceAlignmentArtifact.model_validate(body)


async def _discard_storyboard(storage: ArtifactStorage, run_id: str, storyboard_key: str) -> None:
    """Invalidate the run's storyboard and acquired assets, as a storyboard re-run does.

    The storyboard artifact is immutable, so it is marked discarded (readers then
    treat it as absent until a newer version is generated) and the asset manifest
    is emptied so Studio shows no acquired assets.
    """
    await storage.put_json(
        DISCARDED_STORYBOARD_MARKER.format(run_id=run_id),
        {"key": storyboard_key, "discarded_at": datetime.now().isoformat()},
    )
    manifest_key = await _latest_artifact_key(storage, run_id, "acquisition", "asset_manifest")
    if manifest_key:
        # Keep the artifact envelope so GET .../manifest still reads it (as an empty manifest).
        data = await storage.get_json(manifest_key)
        manifest = dict((data.get("body") or {}).get("manifest") or {})
        manifest["entries"] = []
        data["body"] = {**(data.get("body") or {}), "manifest": manifest}
        await storage.put_json(manifest_key, data)


@router.post("/studio/runs/{run_id}/voice/upload", status_code=202)
async def studio_upload_voice(
    run_id: str,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    confirm_discard: bool = False,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_effective_platform_settings),
    runs: RunRepository = Depends(get_run_repository),
    trace_events: TraceEventRepository = Depends(get_trace_event_repository),
):
    """Store an uploaded voiceover and start its Deepgram transcription (202).

    Validates extension, MIME type, size and file header (422). Uploading again on a
    run that already has a transcript or storyboard answers 409 with what would be
    discarded; repeating with confirm_discard=true discards the storyboard and the
    acquired assets and starts over. Poll GET .../voice/status for the result.
    """
    t0 = time.monotonic()
    run = await _require_uploaded_run(run_id, runs)
    data = await file.read()
    try:
        ext = validate_voice_upload(file.filename, file.content_type, data, settings.VOICE_UPLOAD_MAX_MB * 1024 * 1024)
    except VoiceUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        job = await storage.get_json(_job_key(run_id))
    except Exception:
        job = None
    if job and job.get("status") == "running":
        raise HTTPException(status_code=409, detail="A voiceover is already being transcribed — wait for it to finish.")

    storyboard_key = await _latest_artifact_key(storage, run_id, "storyboard", "verified_storyboard")
    has_transcript = await _latest_artifact_key(storage, run_id, "voice", "voice_alignment") is not None
    if (storyboard_key or has_transcript) and not confirm_discard:
        discards = ["the current transcript and any corrections you made to it"]
        if storyboard_key:
            discards += ["the storyboard", "the acquired assets and scene edits that came with it"]
        return JSONResponse(status_code=409, content={
            "detail": "This run already has a voiceover. Uploading a new one discards: " + "; ".join(discards) + ".",
            "needs_confirmation": True,
            "discards": discards,
        })
    if storyboard_key:
        await _discard_storyboard(storage, run_id, storyboard_key)

    audio_key = f"runs/{run_id}/voiceover/uploaded{ext}"
    await storage.put_bytes(audio_key, data, content_type_for(ext))
    worker = build_voice_upload_worker(
        storage,
        settings.DEEPGRAM_API_KEY,
        min_s=settings.VOICE_UPLOAD_MIN_S,
        max_s=settings.VOICE_UPLOAD_MAX_S,
    )
    language = run_language(run)
    state = StageState(
        run_id=run_id, user_id=PLATFORM_USER_ID,
        inputs={"audio_r2_key": audio_key, "language": language}, artifacts={},
    )
    job_id = str(uuid.uuid4())
    await storage.put_json(_job_key(run_id), {"job_id": job_id, "status": "running"})
    background_tasks.add_task(
        _run_transcription_background, run_id, job_id, state, worker, storage, trace_events,
        settings.DEEPGRAM_COST_PER_MIN_USD, settings.VOICE_LOW_CONFIDENCE,
    )
    await _record_trace(trace_events, TraceEvent(
        run_id=run_id, worker="voice_upload", source="operator", op="voice_upload",
        latency_ms=int((time.monotonic() - t0) * 1000), status="ok",
        meta={
            "filename": file.filename, "size_bytes": len(data), "language": language,
            "replaced": bool(storyboard_key or has_transcript),
        },
    ))
    return {"status": "accepted", "run_id": run_id}


def _transcript_response(alignment: VoiceAlignmentArtifact) -> list[dict]:
    """The words as the editor shows them: index, text and timing in milliseconds."""
    return [
        {"i": i, "word": w.word, "start_ms": w.start_ms, "end_ms": w.end_ms}
        for i, w in enumerate(alignment.word_timestamps)
    ]


@router.get("/studio/runs/{run_id}/transcript")
async def studio_get_transcript(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    runs: RunRepository = Depends(get_run_repository),
) -> dict:
    """Return the transcript words, the audio URL and whether the words can still be edited.

    Before the transcript exists, answers with an empty word list and the state of
    the transcription job (so a reloaded Studio resumes polling); 404 when the run
    has neither a transcript nor a job.
    """
    try:
        job = await storage.get_json(_job_key(run_id))
    except Exception:
        job = None
    alignment = await _current_alignment(storage, run_id)
    try:
        language = run_language(await runs.get(run_id))
    except RunNotFoundError:
        language = DEFAULT_LANGUAGE
    if alignment is None:
        if not job:
            raise HTTPException(status_code=404, detail="No transcript for this run yet.")
        return {"words": [], "job_status": job.get("status"), "job_error": job.get("error"), "language": language}
    audio_url: str | None = None
    if alignment.mp3_r2_key:
        try:
            audio_url = await storage.generate_presigned_url(alignment.mp3_r2_key, expires_in=3600)
        except Exception:
            audio_url = None
    storyboard_exists = await _latest_artifact_key(storage, run_id, "storyboard", "verified_storyboard") is not None
    return {
        "job_status": (job or {}).get("status"),
        "job_error": (job or {}).get("error"),
        "language": language,
        "language_warning": (job or {}).get("language_warning"),
        "words": _transcript_response(alignment),
        "text": transcript_text(alignment.word_timestamps),
        "audio_url": audio_url,
        "total_duration_s": alignment.total_duration_s,
        "alignment_method": alignment.alignment_method,
        "storyboard_exists": storyboard_exists,
        "editable": alignment.alignment_method == UPLOADED_ALIGNMENT_METHOD and not storyboard_exists,
    }


class LanguageRequest(BaseModel):
    """Request body for PUT /studio/runs/{run_id}/language."""

    language: str = Field(pattern=r"^[a-z]{2}$")


class VoiceSourceBody(BaseModel):
    """Request body for PUT /studio/runs/{run_id}/voice-source."""

    voice_source: Literal["generated", "uploaded"]
    confirm_discard: bool = False


@router.put("/studio/runs/{run_id}/voice-source")
async def studio_put_voice_source(
    run_id: str,
    body: VoiceSourceBody,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    runs: RunRepository = Depends(get_run_repository),
):
    """Choose where the run's voice comes from: a generated voice, or the operator's uploaded recording.

    Every run follows one pipeline; the Script step picks the source. Choosing
    "uploaded" only unlocks the upload. Choosing "generated" on a run that already has
    an uploaded recording replaces it: the word timings change, so the storyboard and
    its acquired assets are discarded (the recording itself stays in storage and in
    the Audio library). That answers 409 with what would be discarded until the
    request repeats with confirm_discard=true. Setting the source the run already has
    changes nothing.
    """
    try:
        run = await runs.get(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}") from None
    current = UPLOADED_VOICE_SOURCE if run.inputs.get("voice_source") == UPLOADED_VOICE_SOURCE else "generated"
    if body.voice_source == current:
        return {"voice_source": current, "changed": False, "discarded": []}

    discarded: list[str] = []
    if body.voice_source == "generated":
        storyboard_key = await _latest_artifact_key(storage, run_id, "storyboard", "verified_storyboard")
        alignment = await _current_alignment(storage, run_id)
        uploaded_voice = alignment is not None and alignment.alignment_method == UPLOADED_ALIGNMENT_METHOD
        if uploaded_voice:
            discarded.append("your uploaded voiceover is replaced by a generated voice (the recording stays in the library)")
        if storyboard_key:
            discarded += ["the storyboard", "the acquired assets and scene edits that came with it"]
        if discarded and not body.confirm_discard:
            return JSONResponse(status_code=409, content={
                "detail": "Switching to a generated voice: " + "; ".join(discarded) + ".",
                "needs_confirmation": True,
                "discards": discarded,
            })
        if storyboard_key:
            await _discard_storyboard(storage, run_id, storyboard_key)
    await runs.save(run.model_copy(update={"inputs": {**run.inputs, "voice_source": body.voice_source}}))
    return {"voice_source": body.voice_source, "changed": True, "discarded": discarded}


@router.put("/studio/runs/{run_id}/language")
async def studio_put_language(
    run_id: str,
    body: LanguageRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    runs: RunRepository = Depends(get_run_repository),
) -> dict:
    """Set the run's language (ISO 639-1) — also how the operator answers a language warning.

    Changing it does not re-transcribe: an uploaded run has to upload the voiceover
    again (`transcript_stale` says so). Setting the language the run already has
    just confirms it. Either way the pending warning is marked acknowledged.
    """
    try:
        run = await runs.get(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}") from None
    changed = body.language != run_language(run)
    if changed:
        await runs.save(run.model_copy(update={"inputs": {**run.inputs, "language": body.language}}))
    try:
        job = await storage.get_json(_job_key(run_id))
    except Exception:
        job = None
    stale = False
    if job and job.get("language_warning"):
        job["language_warning"] = {**job["language_warning"], "acknowledged": True}
        await storage.put_json(_job_key(run_id), job)
        stale = changed
    return {"language": body.language, "changed": changed, "transcript_stale": stale}


class TranscriptPatchRequest(BaseModel):
    """Either explicit word `edits`, or corrected `text` to map onto the words; dry_run only checks."""

    edits: list[WordEdit] | None = None
    text: str | None = None
    dry_run: bool = False


@router.patch("/studio/runs/{run_id}/transcript")
async def studio_patch_transcript(
    run_id: str,
    body: TranscriptPatchRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    runs: RunRepository = Depends(get_run_repository),
    trace_events: TraceEventRepository = Depends(get_trace_event_repository),
) -> dict:
    """Apply timing-safe word edits to the uploaded transcript (S2).

    422 with the reason when the edit would delete a spoken word, add an unspoken
    one, or cannot be mapped; 409 once a storyboard exists (re-upload the voiceover
    to start over — that discards the storyboard). Valid edits write a new
    voice_alignment version and regenerate the script from the words; the audio
    is untouched. With dry_run nothing is written.
    """
    await _require_uploaded_run(run_id, runs)
    if (body.edits is None) == (body.text is None):
        raise HTTPException(status_code=422, detail="Send either 'edits' or 'text'.")
    if await _latest_artifact_key(storage, run_id, "storyboard", "verified_storyboard"):
        raise HTTPException(
            status_code=409,
            detail=(
                "The storyboard already exists, so the words are locked. To change the transcript, "
                "upload the voiceover again — that discards the storyboard, the acquired assets and scene edits."
            ),
        )
    try:
        job = await storage.get_json(_job_key(run_id))
    except Exception:
        job = None
    if job and job.get("status") == "running":
        raise HTTPException(status_code=409, detail="The voiceover is still being transcribed.")
    alignment = await _current_alignment(storage, run_id)
    if alignment is None or alignment.alignment_method != UPLOADED_ALIGNMENT_METHOD:
        raise HTTPException(status_code=409, detail="This run has no uploaded transcript to edit.")

    words = alignment.word_timestamps
    try:
        edits = body.edits if body.edits is not None else edits_from_text(words, body.text or "")
        changes = describe_edits(words, edits)
        new_words = apply_word_edits(words, edits)
    except TranscriptEditError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not body.dry_run:
        updated = alignment.model_copy(update={"word_timestamps": new_words})
        await _write_transcript_artifacts(storage, run_id, updated, "transcript_edit")
        await _record_trace(trace_events, TraceEvent(
            run_id=run_id, worker="transcript_edit", source="operator", op="transcript_edit",
            latency_ms=0, status="ok", meta={"changes": changes, "word_count": len(new_words)},
        ))
    return {
        "applied": not body.dry_run,
        "changes": changes,
        "word_count": len(new_words),
        "words": [{"i": i, "word": w.word, "start_ms": w.start_ms, "end_ms": w.end_ms} for i, w in enumerate(new_words)],
        "text": transcript_text(new_words),
    }
