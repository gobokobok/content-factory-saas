"""Creator routes — the simplified flow's own entry points (Sprint P-LITE, D114, D117).

    GET  /creator/config    the project the Creator pages keep runs in, the voices, the script limit
    POST /creator/runs      create an animated run with its format, language, style and characters

The Creator pages (`/create`) reuse the Studio routes for everything a run does
after it exists; these two routes are what the simplified New run needs and the
Studio does not have. Until every user has a hidden personal project (P-AUTH), the
Creator keeps its runs in one fixed project, created the first time it is asked for.

Nothing here restricts what a signed-in user may call: the Creator pages are
simpler, not gated. Server-side limits by tier are LITE-S6, after P-AUTH.
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from cf_platform.core import limits
from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.moderation import moderate_many
from cf_platform.core.project_assets import (
    ProjectAssetError,
    ProjectAssetNotFoundError,
    add_asset,
    list_assets,
    remove_asset,
    update_asset,
)
from cf_platform.core.projects import CREATOR_CONFIG_FLAG, Project, ProjectRepository, create_project, update_project
from cf_platform.core.run_manager import RunNotFoundError, RunRepository, archive_run, create_run
from cf_platform.core.run_visuals import settings_key
from cf_platform.core.shortlist import build_idea_context
from cf_platform.interfaces.dependencies import (
    current_tenant_id,
    current_user,
    get_artifact_storage,
    get_effective_platform_settings,
    get_project_repository,
    get_run_repository,
)
from cf_platform.interfaces.guards import require_project
from cf_platform.interfaces.routes._helpers import latest_artifact_key
from cf_platform.interfaces.routes.projects import STUDIO_BLOCK, ProjectRunResponse, _run_response
from src.models import MAX_RUN_CHARACTERS, RunCharacter, VideoSettings

router = APIRouter()

_RUN_NAME_MAX_CHARS = 120
# The narrator voices a run may choose: Gemini TTS voice names with a short description.
# The deployment's own voice (GEMINI_TTS_VOICE) is listed first and is the default.
CREATOR_VOICES = (
    ("Puck", "Puck · male, upbeat"),
    ("Charon", "Charon · male, informative"),
    ("Orus", "Orus · male, firm"),
    ("Fenrir", "Fenrir · male, excitable"),
    ("Kore", "Kore · female, firm"),
    ("Aoede", "Aoede · female, breezy"),
    ("Leda", "Leda · female, youthful"),
    ("Sulafat", "Sulafat · female, warm"),
)


def creator_voice_choices(settings: PlatformSettings) -> tuple[list[dict[str, str]], str, dict[str, str]]:
    """(voices, default voice id, legacy aliases) for the Voice step, from the deployment's settings."""
    named = dict(CREATOR_VOICES)
    default = (getattr(settings, "GEMINI_TTS_VOICE", "") or "").strip()
    voices = [{"id": vid, "label": label} for vid, label in CREATOR_VOICES]
    if default and default not in named:
        voices.insert(0, {"id": default, "label": f"{default} · default"})
    default_id = default or voices[0]["id"]
    male = (getattr(settings, "CREATOR_VOICE_MALE", "") or "").strip() or default_id
    female = (getattr(settings, "CREATOR_VOICE_FEMALE", "") or "").strip() or default_id
    return voices, default_id, {"male": male, "female": female}


class CreatorRunRequest(BaseModel):
    """Request body for POST /platform/creator/runs."""

    title: str = Field(min_length=1, max_length=300)
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    language: str = Field(default="en", pattern=r"^[a-z]{2}$")
    # The look every image of the video shares; empty leaves the animated default.
    master_style: str = Field(default="", max_length=4000)
    # The only people the director may show. Empty: the director invents the cast.
    characters: list[RunCharacter] = Field(default_factory=list, max_length=MAX_RUN_CHARACTERS)
    # Super only (P-CORE): a realistic video made from stock footage, and a project of the
    # caller's own to keep it in. Basic accounts always get an animated video in their hidden project.
    look: Literal["animated", "realistic"] = "animated"
    project_id: str | None = Field(default=None, max_length=128)


async def creator_project(projects: ProjectRepository, name: str) -> Project:
    """The project the Creator pages keep their runs in, created on first use.

    Found by the flag in its config, so renaming it in the Studio does not make a
    second one. `name` is only used when the project has to be created.
    """
    for project in await projects.list_projects(current_tenant_id(), include_archived=False):
        if (project.config or {}).get(CREATOR_CONFIG_FLAG):
            return project
    return await create_project(current_tenant_id(), name, projects, config={CREATOR_CONFIG_FLAG: True})


def creator_run_settings(body: CreatorRunRequest) -> dict[str, Any]:
    """The settings.json a new Creator run starts with: animated with AI images, or realistic with stock; captions off."""
    if body.look == "realistic":
        return VideoSettings(
            aspect_ratio=body.aspect_ratio, visual_mode="stock", look="realistic", subtitles="none"
        ).model_dump()
    return VideoSettings(
        aspect_ratio=body.aspect_ratio,
        visual_mode="ai_animation",
        look="animated",
        master_style=body.master_style,
        subtitles="none",
        cast_mode="listed" if body.characters else "free",
        characters=body.characters,
    ).model_dump()


@router.get("/creator/config")
async def creator_config(
    projects: ProjectRepository = Depends(get_project_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict[str, Any]:
    """What the Creator pages need before they can list or create runs."""
    project = await creator_project(projects, settings.CREATOR_PROJECT_NAME)
    principal = current_user()
    # The page's word limit is the Creator's; a Super account works at the server's cap (the
    # owner's tenant has none), so a generated three-minute script still fits (P-CORE S5).
    if not principal.is_super:
        script_max = settings.CREATOR_SCRIPT_MAX_WORDS
    elif principal.is_owner:
        script_max = 20000
    else:
        script_max = int(getattr(settings, "CAP_SCRIPT_WORDS", 1200))
    voices, default_voice, voice_aliases = creator_voice_choices(settings)
    return {
        "project_id": project.project_id,
        "project_name": project.name,
        "script_max_words": script_max,
        "max_characters": MAX_RUN_CHARACTERS,
        "voices": voices,
        "default_voice": default_voice,
        "voice_aliases": voice_aliases,
        # P-CORE: what the Super screens need to know without another round trip.
        "sfx_enabled": bool(getattr(settings, "SFX_ENABLED", False)),
    }


@router.delete("/creator/runs/{run_id}", status_code=204)
async def delete_creator_run(run_id: str, runs: RunRepository = Depends(get_run_repository)) -> Response:
    """Delete one of the caller's videos: it leaves every list and library. The row is kept (archived)."""
    try:
        await runs.get(run_id, tenant_id=current_tenant_id())
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}") from None
    await archive_run(run_id, runs)
    return Response(status_code=204)


@router.post("/creator/runs", response_model=ProjectRunResponse, status_code=201)
async def create_creator_run(
    body: CreatorRunRequest,
    projects: ProjectRepository = Depends(get_project_repository),
    runs: RunRepository = Depends(get_run_repository),
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> ProjectRunResponse:
    """Create an animated run in the Creator's project and store its settings.

    The run's format, style and characters are written to settings.json before the
    run is returned, so the first step the user takes already sees them. A blank
    title is a 422.
    """
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Say what the video is about.")
    # P-AUTH S8 / S9: bounds and moderation are the server's, whatever the page does.
    await limits.enforce_runs_per_day(runs, settings)
    limits.check_style(body.master_style, settings)
    for character in body.characters:
        limits.check_character(character.description, f"The description of {character.name}", settings)
    await moderate_many(
        [title, body.master_style, *[f"{c.name}. {c.description}" for c in body.characters]], "creator_run"
    )
    principal = current_user()
    if (body.look == "realistic" or body.project_id) and not principal.is_super:
        raise HTTPException(status_code=403, detail="This needs a Super account.")
    if body.project_id:
        await require_project(body.project_id, projects, principal)
        project = await projects.get(body.project_id)
    else:
        project = await creator_project(projects, settings.CREATOR_PROJECT_NAME)
    context = build_idea_context([])
    context["idea_title"] = title
    run = await create_run(
        current_tenant_id(),
        STUDIO_BLOCK,
        {
            "item_ids": [],
            "voice_source": "generated",
            "language": body.language,
            "aspect_ratio": body.aspect_ratio,
            **context,
        },
        runs,
        project_id=project.project_id,
        name=title[:_RUN_NAME_MAX_CHARS],
    )
    await storage.put_json(settings_key(run.run_id), creator_run_settings(body))
    return _run_response(run)


# ── The AI assets library (P-CORE UX pass) ────────────────────────────────────
# Every character, place and object of the account: saved from a storyboard or added by hand.
# Kept in the config of the tenant's own Creator project, so it needs no new table and is
# isolated per tenant like everything else; Basic and Super use the same routes.


class LibraryAssetRequest(BaseModel):
    """Body for POST /creator/assets."""

    kind: str = "character"
    name: str
    description: str


class LibraryAssetPatch(BaseModel):
    """Body for PATCH /creator/assets/{asset_id}; only the fields given change."""

    kind: str | None = None
    name: str | None = None
    description: str | None = None


class LibraryAssetFromRun(BaseModel):
    """Body for POST /creator/assets/from-run."""

    run_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$", max_length=120)
    entry_id: str


async def _library_project(projects: ProjectRepository, settings: PlatformSettings) -> Project:
    """The project whose config holds this tenant's AI assets."""
    return await creator_project(projects, settings.CREATOR_PROJECT_NAME)


@router.get("/creator/assets")
async def list_library_assets(
    projects: ProjectRepository = Depends(get_project_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict[str, Any]:
    """The account's characters, places and objects."""
    project = await _library_project(projects, settings)
    return {"kind": "assets", "items": list_assets(project.config)}


@router.post("/creator/assets", status_code=201)
async def add_library_asset(
    body: LibraryAssetRequest,
    projects: ProjectRepository = Depends(get_project_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict[str, Any]:
    """Add a character, place or object by hand."""
    limits.check_character(body.description, f"The description of {body.name}", settings)
    await moderate_many([f"{body.name}. {body.description}"], "library_asset")
    project = await _library_project(projects, settings)
    try:
        config, asset = add_asset(project.config, kind=body.kind, name=body.name, description=body.description)
    except ProjectAssetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await update_project(project.project_id, projects, config=config)
    return asset


@router.patch("/creator/assets/{asset_id}")
async def patch_library_asset(
    asset_id: str,
    body: LibraryAssetPatch,
    projects: ProjectRepository = Depends(get_project_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict[str, Any]:
    """Edit an asset. Videos already made keep the copy they were made with."""
    if body.description is not None:
        limits.check_character(body.description, f"The description of {body.name or 'the asset'}", settings)
    await moderate_many([f"{body.name or ''}. {body.description or ''}"], "library_asset")
    project = await _library_project(projects, settings)
    try:
        config, asset = update_asset(
            project.config, asset_id, kind=body.kind, name=body.name, description=body.description
        )
    except ProjectAssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProjectAssetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await update_project(project.project_id, projects, config=config)
    return asset


@router.delete("/creator/assets/{asset_id}", status_code=204)
async def delete_library_asset(
    asset_id: str,
    projects: ProjectRepository = Depends(get_project_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> Response:
    """Remove an asset."""
    project = await _library_project(projects, settings)
    try:
        config = remove_asset(project.config, asset_id)
    except ProjectAssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await update_project(project.project_id, projects, config=config)
    return Response(status_code=204)


@router.post("/creator/assets/from-run", status_code=201)
async def library_asset_from_run(
    body: LibraryAssetFromRun,
    projects: ProjectRepository = Depends(get_project_repository),
    runs: RunRepository = Depends(get_run_repository),
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict[str, Any]:
    """Copy a storyboard's character, place or object into the library (the run must be the caller's)."""
    try:
        run = await runs.get(body.run_id, tenant_id=current_tenant_id())
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run not found: {body.run_id}") from None
    key = await latest_artifact_key(storage, run.run_id, "storyboard", "verified_storyboard")
    if not key:
        raise HTTPException(status_code=404, detail="That video has no storyboard yet.")
    _, artifact = await read_artifact(storage, key)
    bible = ((artifact.get("storyboard") or {}).get("continuity")) or []
    entry = next((e for e in bible if isinstance(e, dict) and e.get("id") == body.entry_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No entry {body.entry_id!r} in that storyboard.")
    project = await _library_project(projects, settings)
    try:
        config, asset = add_asset(
            project.config,
            kind=str(entry.get("kind") or "prop"),
            name=str(entry.get("name") or entry.get("id") or ""),
            description=str(entry.get("description") or ""),
            source_run_id=run.run_id,
        )
    except ProjectAssetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await update_project(project.project_id, projects, config=config)
    return asset


# ── Voice samples ─────────────────────────────────────────────────────────────


@router.get("/creator/voice-samples/{voice}")
async def creator_voice_sample(
    voice: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_effective_platform_settings),
) -> dict[str, str]:
    """A short recording of one listed voice, made once and kept: {"url": …}.

    Only the voices the Voice step lists can be sampled. The first request for a voice
    makes the recording with the deployment's Gemini key; later requests (from any
    account) get the stored file.
    """
    from cf_platform.workers.voice_production import _tts_generate

    voices, _, _ = creator_voice_choices(settings)
    if voice not in {v["id"] for v in voices}:
        raise HTTPException(status_code=404, detail="Unknown voice.")
    key = f"voice-samples/{voice}.wav"
    try:
        return {"url": await _stored_sample_url(storage, key)}
    except Exception:
        pass
    if not getattr(settings, "GEMINI_API_KEY", ""):
        raise HTTPException(status_code=503, detail="Voice samples are not available: the voice service is not configured.")
    text = f"Hi, I'm {voice}. This is how I would narrate your video."
    try:
        wav = await _tts_generate(text, settings.GEMINI_API_KEY, voice)
    except Exception as exc:  # the provider's message may carry a key; show a plain one
        raise HTTPException(status_code=502, detail="The voice service could not make a sample. Try again.") from exc
    await storage.put_bytes(key, wav, "audio/wav")
    return {"url": await storage.generate_presigned_url(key, expires_in=3600)}


async def _stored_sample_url(storage: ArtifactStorage, key: str) -> str:
    """The presigned URL of a stored sample; raises when it has not been made yet."""
    if key not in await storage.list_keys(key):
        raise LookupError(key)
    return await storage.generate_presigned_url(key, expires_in=3600)
