"""Where a run is in the pipeline — derived from what it has produced (P-UX build).

Every run follows the same five steps: Script → Voice → Storyboard → Video → Metadata.
A step is done when its artifact (or, for Video, the final file) exists. A run from an
uploaded voiceover writes the script and the voice together, so both read as done.
Progress is derived, never stored, so it can not drift from the run's files.
"""

from collections.abc import Iterable

PIPELINE: tuple[str, ...] = ("script", "voice", "storyboard", "render", "metadata")

# Artifact (stage, name) that marks each step except the video as done.
_STEP_ARTIFACTS: dict[str, tuple[str, str]] = {
    "script": ("script", "script"),
    "voice": ("voice", "voice_alignment"),
    "storyboard": ("storyboard", "verified_storyboard"),
    "metadata": ("metadata", "youtube_metadata"),
}


def progress_from_artifacts(artifacts: Iterable[tuple[str, str]], has_video: bool) -> tuple[int, str | None]:
    """Return (steps_done, current_step) for a run.

    `artifacts` are (stage, name) pairs the run has produced; `has_video` says a final
    video exists. steps_done counts the leading steps that are done — a later step
    that exists without an earlier one does not count. current_step is the first step
    not done, or None when all five are.
    """
    present = set(artifacts)
    done = 0
    for step in PIPELINE:
        finished = has_video if step == "render" else _STEP_ARTIFACTS[step] in present
        if not finished:
            return done, step
        done += 1
    return done, None


async def collect_run_progress(run_id: str, artifact_repo, storage) -> tuple[int, str | None, bool]:
    """Read a run's artifacts and files and return (steps_done, current_step, has_video).

    Never raises: a storage or database error reads as "nothing produced yet", so one
    unreadable run cannot break a project's run list.
    """
    try:
        records = await artifact_repo.list_for_run(run_id)
        pairs = [(a.stage, a.name) for a in records]
    except Exception:
        pairs = []
    try:
        has_video = bool(await storage.list_keys(f"runs/{run_id}/output/"))
    except Exception:
        has_video = False
    done, current = progress_from_artifacts(pairs, has_video)
    return done, current, has_video
