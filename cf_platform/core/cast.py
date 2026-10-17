"""One character throughout a video (P-PROJ1 follow-up, D113).

By default the animation storyboard worker decides who appears: it may invent two
or three characters for one script. A run can instead be set to follow **one
protagonist** — a project asset, or a description typed for the run. The rule is
given to the model, and then **enforced in code**, because a prompt alone can be
ignored and a regenerated storyboard would otherwise bring the second character
back: every other character entry is dropped from the bible, and the scenes that
showed one show the protagonist instead.
"""

from dataclasses import dataclass
from typing import Any

from cf_platform.core.project_assets import list_assets, slug
from src.models import ContinuityEntry, Storyboard

CAST_MODES = ("free", "single", "listed")
# The most characters a run may list (mirrors src.models.MAX_RUN_CHARACTERS).
MAX_LISTED_CHARACTERS = 6
PROTAGONIST_ID = "protagonist"
MAX_PROTAGONIST_CHARS = 2400


@dataclass(frozen=True)
class CastRule:
    """The one character a run follows."""

    entry_id: str
    name: str
    description: str
    asset_id: str | None = None

    def as_input(self) -> dict[str, Any]:
        """The rule as a plain dict, for a worker's `state.inputs`."""
        return {"id": self.entry_id, "name": self.name, "description": self.description, "asset_id": self.asset_id}

    @classmethod
    def from_input(cls, raw: dict[str, Any] | None) -> "CastRule | None":
        """Rebuild a rule from `as_input()`; None for nothing usable."""
        if not isinstance(raw, dict) or not str(raw.get("description") or "").strip():
            return None
        return cls(
            entry_id=str(raw.get("id") or PROTAGONIST_ID),
            name=str(raw.get("name") or "the protagonist"),
            description=str(raw["description"]).strip(),
            asset_id=raw.get("asset_id") or None,
        )


def resolve_cast(settings: dict[str, Any], project_config: dict[str, Any] | None) -> CastRule | None:
    """The run's cast rule from its settings.json, or None when it is left to the director.

    A chosen project asset wins; a deleted one falls back to the typed description.
    "single" with neither is no rule (the page says so) — it never invents a person.
    """
    if settings.get("cast_mode") != "single":
        return None
    asset_id = str(settings.get("protagonist_asset_id") or "").strip()
    if asset_id:
        for asset in list_assets(project_config):
            if asset["id"] == asset_id:
                return CastRule(asset["id"], str(asset.get("name") or asset["id"]), asset["description"], asset["id"])
    text = str(settings.get("protagonist_text") or "").strip()[:MAX_PROTAGONIST_CHARS]
    return CastRule(PROTAGONIST_ID, "the protagonist", text) if text else None


def prompt_block(rule: CastRule | None) -> str:
    """The storyboard worker's message section for the rule; '' without one."""
    if rule is None:
        return ""
    return (
        "CAST RULE — this video follows ONE person from start to finish. The protagonist is "
        f'id "{rule.entry_id}" ({rule.name}): {rule.description}\n'
        "Put exactly this character in `continuity` (kind \"character\", this id; its description is fixed "
        "and added in code) and show them in every scene that shows a person. Do NOT create any other "
        "character entry. Other people may appear only as unidentifiable background — far-off crowds, "
        "silhouettes, hands — never as a depicted character. When the narration names someone else, show "
        "that through objects, places, documents or the protagonist's reaction, not as a second person."
    )


def enforce_single_cast(storyboard: Storyboard, rule: CastRule | None) -> Storyboard:
    """Make the storyboard follow the rule whatever the model returned.

    The protagonist's entry is created or overwritten with the rule's text; every
    other character entry is removed; a scene that showed a removed character shows
    the protagonist (once, in the same place). Props and settings are untouched.
    """
    if rule is None:
        return storyboard
    removed = {e.id for e in storyboard.continuity if e.kind == "character" and e.id != rule.entry_id}
    entry = ContinuityEntry(
        id=rule.entry_id, kind="character", name=rule.name, description=rule.description,
        project_asset_id=rule.asset_id,
    )
    continuity, placed = [], False
    for existing in storyboard.continuity:
        if existing.id in removed:
            continue
        if existing.id == rule.entry_id:
            continuity.append(entry)
            placed = True
        else:
            continuity.append(existing)
    if not placed:
        continuity.insert(0, entry)

    scenes = []
    for scene in storyboard.scenes:
        entities: list[str] = []
        for entity_id in scene.entities or []:
            mapped = rule.entry_id if entity_id in removed else entity_id
            if mapped not in entities:
                entities.append(mapped)
        scenes.append(scene.model_copy(update={"entities": entities}) if entities != (scene.entities or []) else scene)
    return storyboard.model_copy(update={"continuity": continuity, "scenes": scenes})


# ── Listed characters (D117) ─────────────────────────────────────────────────
# The Creator flow asks for the characters when the run is created. They are the
# only characters the director may use: the same idea as the single-cast rule,
# for several people.


def resolve_listed_cast(settings: dict[str, Any]) -> list[CastRule]:
    """The run's listed characters as rules, in the order given; [] unless cast_mode is "listed".

    Each character's id is the slug of its name (its position when the name has no
    slug), so a re-created storyboard gives the same person the same id. Unnamed,
    undescribed and duplicate entries are skipped.
    """
    if settings.get("cast_mode") != "listed":
        return []
    rules: list[CastRule] = []
    seen: set[str] = set()
    for index, raw in enumerate(settings.get("characters") or []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        description = str(raw.get("description") or "").strip()[:MAX_PROTAGONIST_CHARS]
        # A name with no Latin letters or digits (e.g. Cyrillic) has no slug: number it instead.
        entry_id = slug(name) or f"character_{index + 1}"
        if not name or not description or entry_id in seen:
            continue
        seen.add(entry_id)
        rules.append(CastRule(entry_id, name, description))
        if len(rules) >= MAX_LISTED_CHARACTERS:
            break
    return rules


def listed_prompt_block(rules: list[CastRule]) -> str:
    """The storyboard worker's message section for a listed cast; '' without one."""
    if not rules:
        return ""
    if len(rules) == 1:
        return prompt_block(rules[0])
    people = "\n".join(f'- id "{r.entry_id}" ({r.name}): {r.description}' for r in rules)
    return (
        "CAST RULE — the people of this video are fixed. These are the ONLY characters:\n"
        f"{people}\n"
        "Put exactly these in `continuity` (kind \"character\", these ids; their descriptions are fixed "
        "and added in code) and use them wherever a scene shows a person. Do NOT create any other "
        "character entry. Anyone else may appear only as unidentifiable background — far-off crowds, "
        "silhouettes, hands — never as a depicted character. A scene does not need a person: when the "
        "narration is about someone who is not listed, show it through objects, places or documents."
    )


def enforce_listed_cast(storyboard: Storyboard, rules: list[CastRule]) -> Storyboard:
    """Make the storyboard use only the listed characters, whatever the model returned.

    One listed character behaves as the single-cast rule (a scene that showed an invented
    person shows the listed one). With several, there is no telling which listed person an
    invented one stood for, so the invented character is removed from the bible and from
    its scenes. Every listed character is in the bible with its given description, used or
    not; props and settings are untouched.
    """
    if not rules:
        return storyboard
    if len(rules) == 1:
        return enforce_single_cast(storyboard, rules[0])
    listed = {rule.entry_id: rule for rule in rules}
    removed = {e.id for e in storyboard.continuity if e.kind == "character" and e.id not in listed}
    entries = [
        ContinuityEntry(id=rule.entry_id, kind="character", name=rule.name, description=rule.description)
        for rule in rules
    ]
    others = [e for e in storyboard.continuity if e.id not in listed and e.id not in removed]
    scenes = []
    for scene in storyboard.scenes:
        entities = [entity_id for entity_id in scene.entities or [] if entity_id not in removed]
        scenes.append(scene.model_copy(update={"entities": entities}) if entities != (scene.entities or []) else scene)
    return storyboard.model_copy(update={"continuity": [*entries, *others], "scenes": scenes})
