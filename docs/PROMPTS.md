# AI Prompts — Content Factory

## Storyboard Generator — v0.4
**Used in:** E1-S3 (Step 2b — Script to Storyboard)
**Input:** Plain-text voiceover script
**Output:** `storyboard.json`

### Changelog
| Version | Date | Change |
|---------|------|--------|
| v0.1 | — | Initial prompt |
| v0.2 | — | Added SFX rules |
| v0.3 | — | Added fallback query logic |
| v0.4 | — | Duration from VO word count; comma-list = hard_cut; SFX never null |

### Key rules (v0.4)
- **Duration** is derived from voiceover word count, not clip type ceiling
- **Comma-separated lists** in VO text = one `hard_cut` scene per list item
- **Clip types:** `hard_cut` / `still_with_motion` / `animated`
- **Visual query hierarchy:** PRIMARY (STK) → FALLBACK (STK) → AI_GENERATE
- **SFX** is never null — assign a relevant ambient sound to every scene
- **bg_music** field in global settings specifies music mood/style

### Full system prompt (v0.4)

```
[PASTE FULL v0.4 PROMPT TEXT HERE]

Operator: replace this placeholder with the complete v0.4 system prompt before
running E1-S3. The prompt defines the storyboard.json output schema and all
generation rules.
```

### Expected output schema (`storyboard.json`)

```json
{
  "global": {
    "title": "string",
    "total_duration_seconds": "number",
    "bg_music": "string (mood/style descriptor)",
    "voice_style": "string"
  },
  "scenes": [
    {
      "scene_id": "integer",
      "clip_type": "hard_cut | still_with_motion | animated",
      "duration_seconds": "number",
      "voiceover": "string",
      "visual_description": "string",
      "primary_stock_query": "string",
      "fallback_stock_query": "string",
      "ai_generate_prompt": "string",
      "sfx": "string (never null)"
    }
  ]
}
```

---

## Future prompts
_Add entries here as new AI prompt components are introduced._
