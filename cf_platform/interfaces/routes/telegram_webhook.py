"""Telegram trigger interface — POST /telegram/webhook (D049).

Each Telegram command hands off to a `_run_*_and_reply` background task so the
webhook can return {"ok": True} within Telegram's 60-second timeout while the
LLM graph (25s-10min) runs and then pushes the reply via TelegramClient.
"""

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel

from cf_platform.blocks.idea_to_script import build_idea_to_script_graph
from cf_platform.blocks.niche_to_ideas import build_niche_to_ideas_graph
from cf_platform.core.artifact_manager import ArtifactRepository, ArtifactStorage, read_artifact
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.execution_engine import run_graph
from cf_platform.core.run_manager import RunRepository, create_run, transition_run
from cf_platform.core.schemas import IdeaToScriptState, NicheToIdeasState, PipelineState, SourceAdapter, StageState
from cf_platform.core.trace_repo import TraceEventRepository
from cf_platform.core.worker_registry import ExecutionRepository, WorkerRegistry
from cf_platform.interfaces.dependencies import (
    PLATFORM_USER_ID,
    get_artifact_repository,
    get_artifact_storage,
    get_discovery_adapters,
    get_execution_repository,
    get_graph_checkpointer,
    get_run_repository,
    get_trace_event_repository,
    get_worker_registry,
)
from cf_platform.interfaces.telegram import (
    TelegramClient,
    format_ideas_running,
    format_ideas_usage,
    format_pick_running,
    format_produce_reply,
    format_produce_running,
    format_produce_usage,
    format_ranked_ideas,
    format_run_running,
    format_run_usage,
    format_script_reply,
    format_script_running,
    format_script_usage,
    format_testvoice_reply,
    format_testvoice_running,
    format_unrecognized_command,
    is_chat_allowed,
    parse_ideas_command,
    parse_pick_command,
    parse_produce_args,
    parse_produce_command,
    parse_run_args,
    parse_run_command,
    parse_script_command,
    parse_script_duration_args,
    parse_testvoice_command,
)
from cf_platform.orchestrator.full_pipeline import build_full_pipeline_graph
from cf_platform.workers.opportunity_scorer import TopicScore  # noqa: F401
from cf_platform.workers.script_packager import ScriptArtifact
from cf_platform.workers.topic_selector import RankedIdeasArtifact
from cf_platform.workers.voice_production import build_voice_production_worker
from cf_platform.workers.youtube_metadata import YoutubeMetadataArtifact

_logger = logging.getLogger(__name__)

router = APIRouter()

_VIDEO_URL_EXPIRY = 86400  # 24 hours
_TESTVOICE_MP3_URL_EXPIRY = 3600  # 1 hour


class TelegramChat(BaseModel):
    """Minimal Telegram `chat` object — only the `id` is needed to reply (D049)."""

    id: int


class TelegramMessage(BaseModel):
    """Minimal Telegram `message` object — chat + optional text (D049)."""

    chat: TelegramChat
    text: str | None = None


class TelegramUpdate(BaseModel):
    """Minimal Telegram `Update` object — only the `message` field is consumed (D049)."""

    message: TelegramMessage | None = None


async def _run_ideas_and_reply(
    chat_id: int,
    niche: str,
    settings: PlatformSettings,
    adapters: list,
    storage: ArtifactStorage,
    registry: WorkerRegistry,
    runs: RunRepository,
    executions: ExecutionRepository,
    artifacts: ArtifactRepository,
    trace_events: TraceEventRepository,
    checkpointer: BaseCheckpointSaver,
) -> None:
    """Run the full niche→ideas block in the background and push the reply to Telegram.

    Separated from the webhook handler so the handler can return {"ok": True} immediately —
    Telegram's webhook has a 60-second response timeout; LLM graph runs take 25–55 s and
    would trigger retries and duplicate runs if awaited inline.
    """
    client = TelegramClient(settings.TELEGRAM_BOT_TOKEN)
    try:
        run = await create_run(PLATFORM_USER_ID, "niche_to_ideas", {"niche": niche}, runs)
        run = await transition_run(run.run_id, "running", runs)

        graph = build_niche_to_ideas_graph(
            storage=storage,
            registry=registry,
            executions=executions,
            artifact_repo=artifacts,
            adapters=adapters,
            trace_repo=trace_events,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
            checkpointer=checkpointer,
        )
        state = NicheToIdeasState(
            run_id=run.run_id, user_id=PLATFORM_USER_ID, inputs={"niche": niche}
        )
        result = await run_graph(graph, state, thread_id=run.run_id)
        await transition_run(run.run_id, "complete", runs)

        ranked_key = result.artifacts["ranked_ideas"]
        _, body_dict = await read_artifact(storage, ranked_key)
        ranked_artifact = RankedIdeasArtifact.model_validate(body_dict)
        reply = format_ranked_ideas(niche, run.run_id, ranked_key, ranked_artifact)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("_run_ideas_and_reply failed for niche=%r chat_id=%s: %s", niche, chat_id, exc)
        short = str(exc)[:200]
        reply = f"Error running /ideas: {type(exc).__name__}: {short}"

    try:
        await client.send_message(chat_id, reply)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("TelegramClient.send_message failed for chat_id=%s: %s", chat_id, exc)


async def _run_script_and_reply(
    chat_id: int,
    idea_title: str,
    settings: PlatformSettings,
    storage: ArtifactStorage,
    registry: WorkerRegistry,
    runs: RunRepository,
    executions: ExecutionRepository,
    artifacts: ArtifactRepository,
    checkpointer: BaseCheckpointSaver,
    target_duration_seconds: int = 60,
) -> None:
    """Run the full idea→script block in the background and push the script to Telegram.

    Separated from the webhook handler so the handler can return {"ok": True} immediately —
    Telegram's 60-second response timeout is too short for a multi-iteration LLM graph.
    `target_duration_seconds` is parsed from the `/script ... --duration <n>` flag (P6-S5).
    """
    client = TelegramClient(settings.TELEGRAM_BOT_TOKEN)
    try:
        run_inputs: dict[str, Any] = {"idea_title": idea_title}
        run = await create_run(PLATFORM_USER_ID, "idea_to_script", run_inputs, runs)
        run = await transition_run(run.run_id, "running", runs)

        graph = build_idea_to_script_graph(
            storage=storage,
            registry=registry,
            executions=executions,
            artifact_repo=artifacts,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
            checkpointer=checkpointer,
        )
        state = IdeaToScriptState(
            run_id=run.run_id,
            user_id=PLATFORM_USER_ID,
            inputs=run_inputs,
            target_duration_seconds=target_duration_seconds,
        )
        result = await run_graph(graph, state, thread_id=run.run_id)
        await transition_run(run.run_id, "complete", runs)

        script_key = result.artifacts["script"]
        _, body_dict = await read_artifact(storage, script_key)
        script_artifact = ScriptArtifact.model_validate(body_dict)
        reply = format_script_reply(script_artifact)
    except Exception as exc:  # noqa: BLE001
        _logger.exception(
            "_run_script_and_reply failed for idea_title=%r chat_id=%s: %s",
            idea_title,
            chat_id,
            exc,
        )
        short = str(exc)[:200]
        reply = f"Error running /script: {type(exc).__name__}: {short}"

    try:
        await client.send_message(chat_id, reply)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("TelegramClient.send_message failed for chat_id=%s: %s", chat_id, exc)


async def _run_pipeline_and_reply(
    chat_id: int,
    display_label: str,
    settings: PlatformSettings,
    adapters: list,
    storage: ArtifactStorage,
    registry: WorkerRegistry,
    runs: RunRepository,
    executions: ExecutionRepository,
    artifacts: ArtifactRepository,
    trace_events: TraceEventRepository,
    checkpointer: BaseCheckpointSaver,
    niche: str = "",
    idea_title: str | None = None,
    target_duration_seconds: int = 60,
    format_track: str = "portrait",
    command_name: str = "pipeline",
) -> None:
    """Run the full pipeline in the background and push a video URL reply to Telegram.

    Separated from webhook handlers so they can return {"ok": True} immediately —
    full pipeline runs take 5–10 minutes (LLM calls + ffmpeg render).

    `display_label` is shown in the Telegram reply (niche for /run, idea title for /produce
    and /pick). `niche` and `idea_title` are passed to PipelineState; when `idea_title` is
    set the orchestrator skips niche_to_ideas (P7-S1). `format_track` selects portrait
    (1080×1920, default) or landscape (1920×1080) output. `command_name` is used only in
    error messages for operator clarity.
    """
    client = TelegramClient(settings.TELEGRAM_BOT_TOKEN)
    try:
        run_inputs: dict[str, Any] = {}
        if niche:
            run_inputs["niche"] = niche
        if idea_title:
            run_inputs["idea_title"] = idea_title

        run = await create_run(PLATFORM_USER_ID, "full_pipeline", run_inputs, runs)
        run = await transition_run(run.run_id, "running", runs)

        graph = build_full_pipeline_graph(
            storage=storage,
            registry=registry,
            executions=executions,
            artifact_repo=artifacts,
            adapters=adapters,
            trace_repo=trace_events,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
            checkpointer=checkpointer,
            gemini_api_key=settings.GEMINI_API_KEY,
            gemini_tts_voice=settings.GEMINI_TTS_VOICE,
            deepgram_api_key=settings.DEEPGRAM_API_KEY,
            pexels_api_key=settings.PEXELS_API_KEY,
            pixabay_api_key=settings.PIXABAY_API_KEY,
            color_grade_preset=settings.COLOR_GRADE_PRESET,
            blur_fill_enabled=settings.BLUR_FILL_ENABLED,
            ffmpeg_timeout_seconds=settings.FFMPEG_TIMEOUT_SECONDS,
        )
        state = PipelineState(
            run_id=run.run_id,
            user_id=PLATFORM_USER_ID,
            inputs=run_inputs,
            target_duration_seconds=target_duration_seconds,
            idea_title=idea_title,
            format_track=format_track,
        )
        result = await run_graph(graph, state, thread_id=run.run_id)
        await transition_run(run.run_id, "complete", runs)

        video_r2_key: str = result.artifacts["video"]
        video_url = await storage.generate_presigned_url(video_r2_key, expires_in=_VIDEO_URL_EXPIRY)

        # Read youtube_metadata artifact when present; absent or failed → reply without it.
        metadata: YoutubeMetadataArtifact | None = None
        meta_key = result.artifacts.get("youtube_metadata")
        if meta_key:
            try:
                _, meta_body = await read_artifact(storage, meta_key)
                metadata = YoutubeMetadataArtifact.model_validate(meta_body)
            except Exception as meta_exc:  # noqa: BLE001
                _logger.warning(
                    "_run_pipeline_and_reply: could not read youtube_metadata for run_id=%s: %s",
                    run.run_id,
                    meta_exc,
                )

        # Read footage_summary side-car written by the legacy adapter (P8-S5).
        # Written to R2 as runs/{run_id}/footage_summary.json; absent in tests and
        # non-acquisition environments — graceful fallback to None (no coverage line).
        footage_summary: dict | None = None
        try:
            footage_summary = await storage.get_json(f"runs/{run.run_id}/footage_summary.json")
        except Exception:  # noqa: BLE001
            pass

        reply = format_produce_reply(display_label, run.run_id, video_url, metadata, footage_summary)
    except Exception as exc:  # noqa: BLE001
        _logger.exception(
            "_run_pipeline_and_reply failed for label=%r chat_id=%s: %s", display_label, chat_id, exc
        )
        short = str(exc)[:200]
        reply = f"Error running /{command_name}: {type(exc).__name__}: {short}"

    try:
        await client.send_message(chat_id, reply)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("TelegramClient.send_message failed for chat_id=%s: %s", chat_id, exc)


async def _run_pick_and_reply(
    chat_id: int,
    original_run_id: str,
    idea_number: int,
    settings: PlatformSettings,
    adapters: list,
    storage: ArtifactStorage,
    registry: WorkerRegistry,
    runs: RunRepository,
    executions: ExecutionRepository,
    artifacts: ArtifactRepository,
    trace_events: TraceEventRepository,
    checkpointer: BaseCheckpointSaver,
    target_duration_seconds: int = 60,
    format_track: str = "portrait",
) -> None:
    """Read the ranked_ideas artifact from original_run_id, extract idea N, and produce a video.

    Validates that idea_number is in range for the artifact, sends an ack, then calls
    _run_pipeline_and_reply with idea_title set so niche_to_ideas is skipped (P7-S1).
    Niche is read from the ranked_ideas artifact for prompt context downstream.
    """
    client = TelegramClient(settings.TELEGRAM_BOT_TOKEN)
    try:
        artifact_records = await artifacts.list_for_run(original_run_id)
        ranked_records = [a for a in artifact_records if a.name == "ranked_ideas"]
        if not ranked_records:
            await client.send_message(chat_id, f"No ideas found for run {original_run_id}. Run /ideas first.")
            return
        ranked_r2_key = max(ranked_records, key=lambda a: a.version).r2_key
        _, ranked_body = await read_artifact(storage, ranked_r2_key)
        ranked_artifact = RankedIdeasArtifact.model_validate(ranked_body)

        all_ideas = [ranked_artifact.selected] + list(ranked_artifact.alternatives)
        if idea_number > len(all_ideas):
            await client.send_message(chat_id, f"Idea {idea_number} not found — run {original_run_id} only has {len(all_ideas)} ideas.")
            return

        chosen = all_ideas[idea_number - 1]
        niche: str = ranked_artifact.niche

        await client.send_message(chat_id, format_pick_running(original_run_id, chosen.title))
    except Exception as exc:  # noqa: BLE001
        _logger.exception("_run_pick_and_reply failed for run_id=%r idea_number=%s chat_id=%s: %s", original_run_id, idea_number, chat_id, exc)
        short = str(exc)[:200]
        try:
            await client.send_message(chat_id, f"Error running /pick: {type(exc).__name__}: {short}")
        except Exception:  # noqa: BLE001
            pass
        return

    await _run_pipeline_and_reply(
        chat_id=chat_id,
        display_label=chosen.title,
        settings=settings,
        adapters=adapters,
        storage=storage,
        registry=registry,
        runs=runs,
        executions=executions,
        artifacts=artifacts,
        trace_events=trace_events,
        checkpointer=checkpointer,
        niche=niche,
        idea_title=chosen.title,
        target_duration_seconds=target_duration_seconds,
        format_track=format_track,
        command_name="pick",
    )


async def _run_testvoice_and_reply(
    chat_id: int,
    run_id: str,
    settings: PlatformSettings,
    storage: ArtifactStorage,
    artifacts: ArtifactRepository,
) -> None:
    """Read the script artifact for run_id, generate voice, and reply with a presigned MP3 URL.

    Calls voice_production_worker directly (not through the full graph) so the
    operator can test voice in isolation without re-running the whole pipeline.
    Reads the latest 'script' artifact for the run from the artifact repository,
    then invokes build_voice_production_worker with GEMINI_API_KEY + GEMINI_TTS_VOICE
    from settings.  Returns a presigned URL with a 1-hour expiry.

    Fault isolation: if no script artifact is found, or TTS fails, sends an error
    reply rather than crashing silently.
    """
    client = TelegramClient(settings.TELEGRAM_BOT_TOKEN)
    try:
        # Look up the latest 'script' artifact for this run.
        artifact_records = await artifacts.list_for_run(run_id)
        script_records = [a for a in artifact_records if a.name == "script"]
        if not script_records:
            await client.send_message(chat_id, f"No script artifact found for run {run_id}. Run /produce first.")
            return
        # Take the highest version.
        script_r2_key = max(script_records, key=lambda a: a.version).r2_key

        voice_worker = build_voice_production_worker(
            storage,
            gemini_api_key=settings.GEMINI_API_KEY,
            gemini_tts_voice=settings.GEMINI_TTS_VOICE,
            deepgram_api_key=settings.DEEPGRAM_API_KEY,
        )
        state = StageState(
            run_id=run_id,
            user_id=PLATFORM_USER_ID,
            inputs={},
            artifacts={"script": script_r2_key},
        )
        result = await voice_worker(state)
        mp3_r2_key: str = result.artifact.mp3_r2_key  # type: ignore[union-attr]
        if not mp3_r2_key:
            await client.send_message(chat_id, f"Voice generated with proportional fallback (no TTS key). No MP3 to download for run {run_id}.")
            return
        mp3_url = await storage.generate_presigned_url(mp3_r2_key, expires_in=_TESTVOICE_MP3_URL_EXPIRY)
        reply = format_testvoice_reply(run_id, mp3_url)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("_run_testvoice_and_reply failed for run_id=%r chat_id=%s: %s", run_id, chat_id, exc)
        short = str(exc)[:200]
        reply = f"Error running /testvoice: {type(exc).__name__}: {short}"

    try:
        await client.send_message(chat_id, reply)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("TelegramClient.send_message failed for chat_id=%s: %s", chat_id, exc)


@router.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(
    update: TelegramUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    settings: PlatformSettings = Depends(get_platform_settings),
    adapters: list[tuple[str, SourceAdapter]] = Depends(get_discovery_adapters),
    storage: ArtifactStorage = Depends(get_artifact_storage),
    registry: WorkerRegistry = Depends(get_worker_registry),
    runs: RunRepository = Depends(get_run_repository),
    executions: ExecutionRepository = Depends(get_execution_repository),
    artifacts: ArtifactRepository = Depends(get_artifact_repository),
    trace_events: TraceEventRepository = Depends(get_trace_event_repository),
    checkpointer: BaseCheckpointSaver = Depends(get_graph_checkpointer),
) -> dict:
    """Validate Telegram's secret token, parse trigger commands, and reply via a formatter (D049).

    `/ideas <niche>` schedules the full niche→ideas block as a FastAPI BackgroundTask so
    the webhook returns {"ok": True} immediately — well within Telegram's 60 s timeout.
    The graph result is pushed to chat via `TelegramClient.send_message` when done.

    TELEGRAM_ALLOWED_CHAT_IDS (temporary single-operator allowlist ahead of S19):
    updates from chats not on the list are acked with no reply sent.
    """
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not settings.TELEGRAM_WEBHOOK_SECRET or secret != settings.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret token")

    if update.message is None or update.message.text is None:
        return {"ok": True}

    if not is_chat_allowed(update.message.chat.id, settings.TELEGRAM_ALLOWED_CHAT_IDS):
        return {"ok": True}

    chat_id = update.message.chat.id
    client = TelegramClient(settings.TELEGRAM_BOT_TOKEN)

    run_args = parse_run_command(update.message.text)
    produce_args = parse_produce_command(update.message.text)
    pick_result = parse_pick_command(update.message.text)
    niche = parse_ideas_command(update.message.text)
    idea_title = parse_script_command(update.message.text)
    testvoice_run_id = parse_testvoice_command(update.message.text)

    if run_args is not None:
        if not run_args:
            await client.send_message(chat_id, format_run_usage())
        else:
            parsed_niche, duration, run_format = parse_run_args(run_args)
            if not parsed_niche:
                await client.send_message(chat_id, format_run_usage())
            else:
                await client.send_message(chat_id, format_run_running(parsed_niche))
                background_tasks.add_task(
                    _run_pipeline_and_reply,
                    chat_id=chat_id,
                    display_label=parsed_niche,
                    settings=settings,
                    adapters=adapters,
                    storage=storage,
                    registry=registry,
                    runs=runs,
                    executions=executions,
                    artifacts=artifacts,
                    trace_events=trace_events,
                    checkpointer=checkpointer,
                    niche=parsed_niche,
                    target_duration_seconds=duration,
                    format_track=run_format,
                    command_name="run",
                )
    elif produce_args is not None:
        if not produce_args:
            await client.send_message(chat_id, format_produce_usage())
        else:
            parsed_title, duration, produce_format = parse_produce_args(produce_args)
            if not parsed_title:
                await client.send_message(chat_id, format_produce_usage())
            else:
                await client.send_message(chat_id, format_produce_running(parsed_title))
                background_tasks.add_task(
                    _run_pipeline_and_reply,
                    chat_id=chat_id,
                    display_label=parsed_title,
                    settings=settings,
                    adapters=adapters,
                    storage=storage,
                    registry=registry,
                    runs=runs,
                    executions=executions,
                    artifacts=artifacts,
                    trace_events=trace_events,
                    checkpointer=checkpointer,
                    idea_title=parsed_title,
                    target_duration_seconds=duration,
                    format_track=produce_format,
                    command_name="produce",
                )
    elif pick_result is not None:
        original_run_id, idea_number, pick_duration, pick_format = pick_result
        background_tasks.add_task(
            _run_pick_and_reply,
            chat_id=chat_id,
            original_run_id=original_run_id,
            idea_number=idea_number,
            settings=settings,
            adapters=adapters,
            storage=storage,
            registry=registry,
            runs=runs,
            executions=executions,
            artifacts=artifacts,
            trace_events=trace_events,
            checkpointer=checkpointer,
            target_duration_seconds=pick_duration,
            format_track=pick_format,
        )
    elif niche is not None:
        if not niche:
            await client.send_message(chat_id, format_ideas_usage())
        else:
            await client.send_message(chat_id, format_ideas_running(niche))
            background_tasks.add_task(
                _run_ideas_and_reply,
                chat_id=chat_id,
                niche=niche,
                settings=settings,
                adapters=adapters,
                storage=storage,
                registry=registry,
                runs=runs,
                executions=executions,
                artifacts=artifacts,
                trace_events=trace_events,
                checkpointer=checkpointer,
            )
    elif idea_title is not None:
        if not idea_title:
            await client.send_message(chat_id, format_script_usage())
        else:
            parsed_title, duration = parse_script_duration_args(idea_title)
            await client.send_message(chat_id, format_script_running(parsed_title))
            background_tasks.add_task(
                _run_script_and_reply,
                chat_id=chat_id,
                idea_title=parsed_title,
                settings=settings,
                storage=storage,
                registry=registry,
                runs=runs,
                executions=executions,
                artifacts=artifacts,
                checkpointer=checkpointer,
                target_duration_seconds=duration,
            )
    elif testvoice_run_id is not None:
        if not testvoice_run_id:
            await client.send_message(chat_id, "Usage: /testvoice <run_id> — e.g. /testvoice abc-123")
        else:
            await client.send_message(chat_id, format_testvoice_running(testvoice_run_id))
            background_tasks.add_task(
                _run_testvoice_and_reply,
                chat_id=chat_id,
                run_id=testvoice_run_id,
                settings=settings,
                storage=storage,
                artifacts=artifacts,
            )
    else:
        await client.send_message(chat_id, format_unrecognized_command(update.message.text))

    return {"ok": True}
