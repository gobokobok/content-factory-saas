"""Curated SFX library manifest — single source of truth (D076).

One entry per curated sound effect. Consumed by:
  - cf_platform.workers.storyboard_worker — builds the SFX vocabulary block
    substituted into the storyboard-generation system prompt (and the reviewer
    prompt), so the AI only ever suggests a key from this list, or "silence".
  - cf_platform.workers.render_worker — lists which curated keys actually have
    a backing file in R2 (sfx-library/{key}.mp3), for the Studio picker and for
    copying the right files into a run before render.
  - scripts/seed_sfx_library.py — the Freesound search query used to seed each
    key's audio file into R2, once, offline.

Adding a new curated sound: append an entry here, re-run
scripts/seed_sfx_library.py (optionally with --key <new_key>), and the new
option becomes available to the AI, the reviewer, and the Studio dropdown
automatically — no other file needs to change.
"""

from pydantic import BaseModel


class SfxLibraryEntry(BaseModel):
    """One curated SFX option."""

    key: str
    display_name: str
    prompt_hint: str
    search_query: str


SFX_LIBRARY: list[SfxLibraryEntry] = [
    # The operator-chosen set (2026-10-04). Source files and licences: assets/sfx_source/SOURCES.md.
    # search_query is unused for these (hand-picked, not Freesound-seeded); the field stays required.
    SfxLibraryEntry(
        key="whoosh",
        display_name="Whoosh",
        prompt_hint="scene is a topic or section transition",
        search_query="",
    ),
    SfxLibraryEntry(
        key="impact",
        display_name="Impact / boom",
        prompt_hint="emphasis moment on a shocking or dramatic stat",
        search_query="",
    ),
    SfxLibraryEntry(
        key="cash_register",
        display_name="Cash register",
        prompt_hint="scene mentions a dollar amount, price, or cost",
        search_query="",
    ),
    SfxLibraryEntry(
        key="error",
        display_name="Error / buzzer",
        prompt_hint="scene highlights a mistake, misconception, or wrongdoing",
        search_query="",
    ),
    SfxLibraryEntry(
        key="typing",
        display_name="Typing",
        prompt_hint="scene is about searching, looking something up, researching, or writing",
        search_query="",
    ),
]


def sfx_vocab_prompt_line() -> str:
    """Render the manifest as the SFX field-rule block for the generation prompt.

    One bullet per curated key (key + when to use it) plus a closing bullet for
    "silence", which should be the majority pick.
    """
    lines = [f'- "{e.key}" — {e.prompt_hint}' for e in SFX_LIBRARY]
    lines.append('- "silence" — no sfx fits; this should be the MAJORITY of scenes, do not force one')
    return "\n".join(lines)


def sfx_vocab_reviewer_line() -> str:
    """Render the manifest as a compact key list for the reviewer prompt."""
    keys = " | ".join(f'"{e.key}"' for e in SFX_LIBRARY)
    return f'{keys} | "silence"'
