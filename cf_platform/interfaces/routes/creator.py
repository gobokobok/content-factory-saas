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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cf_platform.core import limits
from cf_platform.core.artifact_manager import ArtifactStorage
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.moderation import moderate_many
from cf_platform.core.projects import CREATOR_CONFIG_FLAG, Project, ProjectRepository, create_project
from cf_platform.core.run_manager import RunRepository, create_run
from cf_platform.core.run_visuals import settings_key
from cf_platform.core.shortlist import build_idea_context
from cf_platform.interfaces.dependencies import (
    current_tenant_id,
    get_artifact_storage,
    get_project_repository,
    get_run_repository,
)
from cf_platform.interfaces.routes.projects import STUDIO_BLOCK, ProjectRunResponse, _run_response
from src.models import MAX_RUN_CHARACTERS, RunCharacter, VideoSettings

router = APIRouter()

_RUN_NAME_MAX_CHARS = 120
# The voices a run may choose, in the order the page lists them; the first is the default.
# Male first: it is the deployment's own voice (GEMINI_TTS_VOICE) unless one is set.
CREATOR_VOICES = (("male", "Male"), ("female", "Female"))


class CreatorRunRequest(BaseModel):
    """Request body for POST /platform/creator/runs."""

    title: str = Field(min_length=1, max_length=300)
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    language: str = Field(default="en", pattern=r"^[a-z]{2}$")
    # The look every image of the video shares; empty leaves the animated default.
    master_style: str = Field(default="", max_length=2000)
    # The only people the director may show. Empty: the director invents the cast.
    characters: list[RunCharacter] = Field(default_factory=list, max_length=MAX_RUN_CHARACTERS)


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
    """The settings.json a new Creator run starts with: animated, AI images, captions off."""
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
    return {
        "project_id": project.project_id,
        "project_name": project.name,
        "script_max_words": settings.CREATOR_SCRIPT_MAX_WORDS,
        "max_characters": MAX_RUN_CHARACTERS,
        "voices": [{"id": voice_id, "label": label} for voice_id, label in CREATOR_VOICES],
    }


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
