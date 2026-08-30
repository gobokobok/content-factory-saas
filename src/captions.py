"""ASS subtitle file generator for on-screen text and voiceover captions."""

import re

from src.models import StoryboardScene, WordTimestamp

# ── Number-to-words for caption display (D073) ────────────────────────────────
#
# Deepgram's smart_format strips "$"/"," from word tokens (see D045 rev /
# cf_platform/workers/voice_production.py), so a spoken "$100,000" arrives as
# the bare token "100000" — a long digit run with no thousands separator reads
# as near-impossible to parse at a glance in a Shorts caption. Below spells
# such tokens out ("one hundred thousand") for DISPLAY ONLY: it is applied to
# the text joined into each Dialogue line, never to WordTimestamp.word itself,
# so scene-alignment / gap-filling matching against the verbatim script is
# unaffected.

_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
    "eighteen", "nineteen",
]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_SCALES = [(1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand")]

_TRAILING_PUNCT_RE = re.compile(r"([.,!?;:]+)$")
_NUMERIC_CORE_RE = re.compile(r"^(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?$")


def _int_to_words(n: int) -> str:
    """Convert a non-negative integer to English words (supports up to billions)."""
    if n < 0:
        return "minus " + _int_to_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, rem = divmod(n, 10)
        return _TENS[tens] + (f"-{_ONES[rem]}" if rem else "")
    if n < 1000:
        hundreds, rem = divmod(n, 100)
        return f"{_ONES[hundreds]} hundred" + (f" {_int_to_words(rem)}" if rem else "")
    for scale_val, scale_name in _SCALES:
        if n >= scale_val:
            hi, rem = divmod(n, scale_val)
            return f"{_int_to_words(hi)} {scale_name}" + (f" {_int_to_words(rem)}" if rem else "")
    return str(n)  # unreachable for n < 1e12, kept as a safe fallback


def _spell_out_token(token: str) -> str:
    """Return the spoken-word form of a single numeric caption token.

    Handles an optional leading '$' (-> trailing "dollars"), an optional
    trailing '%' (-> trailing "percent"), comma thousands-separators, decimals
    ("3.5" -> "three point five"), and preserves trailing sentence punctuation
    (e.g. "100000." -> "one hundred thousand."). Returns the token unchanged
    if it is not (once currency/percent/punctuation are stripped) a plain
    number — words like "1st" or mixed alphanumerics are left untouched.
    """
    if not token:
        return token
    core = token
    is_currency = core.startswith("$")
    if is_currency:
        core = core[1:]
    trailing = ""
    m = _TRAILING_PUNCT_RE.search(core)
    if m:
        trailing = m.group(1)
        core = core[: m.start()]
    is_percent = core.endswith("%")
    if is_percent:
        core = core[:-1]
    match = _NUMERIC_CORE_RE.match(core)
    if not match:
        return token
    int_part, dec_part = match.groups()
    words = _int_to_words(int(int_part.replace(",", "")))
    if dec_part:
        digit_words = " ".join(_ONES[int(d)] for d in dec_part[1:])
        words += f" point {digit_words}"
    if is_percent:
        words += " percent"
    if is_currency:
        words += " dollars"
    return words + trailing


def spell_out_numbers(text: str) -> str:
    """Convert every purely-numeric word in text to its spoken form.

    e.g. "up to 100000" -> "up to one hundred thousand"; "$15,000" ->
    "fifteen thousand dollars"; "90%" -> "ninety percent". Non-numeric words
    are left untouched. Caption display only — never applied to word-timing
    or alignment data (see module docstring above).
    """
    return " ".join(_spell_out_token(tok) for tok in text.split())

_ASS_HEADER = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "PlayResX: 1080\n"
    "PlayResY: 1920\n"
    "\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
    " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline,"
    " Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    "Style: Default,Open Sans,56,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
    "-1,0,0,0,100,100,0,0,1,3,0,5,10,10,0,1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)


# 9:16 Shorts caption styles (D070, D071, D072). PlayResY=1920 -> MarginV=576
# is 30% up from the bottom edge. Line-to-line spacing when a chunk wraps to 2
# lines is controlled by TitilliumWeb-SemiBold.ttf's own tightened vertical
# metrics (~30% tighter than the font's stock line-height), not by an ASS
# style field — ASS/libass has no native line-spacing property (D071).
_CAPTIONS_ASS_HEADER = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "PlayResX: 1080\n"
    "PlayResY: 1920\n"
    "\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
    " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline,"
    " Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    "Style: VoiceCaption,Titillium Web SemiBold,80,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
    "0,0,0,0,100,100,0,0,1,3,1,2,110,110,576,1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)

# Punch style (D082) — ONE WORD AT A TIME, uppercase. A single word owns the whole
# frame, so the size goes up from 80 to 130 and the outline from 3 to 4 to hold up
# against bright footage. MarginV matches _CAPTIONS_ASS_HEADER so the caption band
# sits in the same place whichever preset is chosen. Only used at 9:16.
_CAPTIONS_ASS_HEADER_PUNCH = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "PlayResX: 1080\n"
    "PlayResY: 1920\n"
    "\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
    " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline,"
    " Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    "Style: VoiceCaption,Titillium Web SemiBold,130,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
    "0,0,0,0,100,100,0,0,1,4,1,2,60,60,576,1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)

# Classic subtitle style — smaller, clean, traditional appearance. Kept at its
# original (lower, closer-to-edge) vertical position; only font/size/margin
# follow the TikTok style's D070/D071/D072 changes.
_CAPTIONS_ASS_HEADER_CLASSIC = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "PlayResX: 1080\n"
    "PlayResY: 1920\n"
    "\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
    " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline,"
    " Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    "Style: VoiceCaption,Titillium Web SemiBold,56,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
    "0,0,0,0,100,100,0,0,1,2,1,2,110,110,180,1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)

# Pre-D070 styles, unchanged. Used for every aspect ratio other than 9:16 so
# landscape/other-format renders are never affected by the Shorts-only caption
# styling requested in D070/D071 (see D071).
_CAPTIONS_ASS_HEADER_LEGACY = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "PlayResX: 1080\n"
    "PlayResY: 1920\n"
    "\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
    " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline,"
    " Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    "Style: VoiceCaption,Poppins,147,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
    "1,0,0,0,100,100,0,0,1,8,1,2,10,10,350,1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)

_CAPTIONS_ASS_HEADER_CLASSIC_LEGACY = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "PlayResX: 1080\n"
    "PlayResY: 1920\n"
    "\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
    " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline,"
    " Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    "Style: VoiceCaption,Poppins,102,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
    "0,0,0,0,100,100,0,0,1,3,1,2,10,10,180,1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)


def _captions_header(
    subtitle_style: str,
    aspect_ratio: str = "9:16",
    caption_style: str = "standard",
) -> str:
    """Return the ASS header for the given subtitle style ('TikTok' or 'Classic').

    aspect_ratio gates the D070/D071 Shorts-only restyle: any value other than
    '9:16' returns the original pre-D070 Poppins headers untouched, so
    landscape/other-format renders are never affected by Shorts caption tuning.

    caption_style="punch" (D082) selects the one-word-at-a-time header. It is a
    9:16-only preset — landscape keeps the legacy headers, matching how the D070
    restyle is scoped.
    """
    if aspect_ratio != "9:16":
        return _CAPTIONS_ASS_HEADER_CLASSIC_LEGACY if subtitle_style == "Classic" else _CAPTIONS_ASS_HEADER_LEGACY
    if caption_style == "punch":
        return _CAPTIONS_ASS_HEADER_PUNCH
    if subtitle_style == "Classic":
        return _CAPTIONS_ASS_HEADER_CLASSIC
    return _CAPTIONS_ASS_HEADER


def format_ass_time(seconds: float) -> str:
    """Convert seconds to ASS time format H:MM:SS.cc (centiseconds, 0–99)."""
    cs = round(seconds * 100)
    h = cs // 360000
    cs %= 360000
    m = cs // 6000
    cs %= 6000
    s = cs // 100
    cs %= 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _clean_on_screen_text(text: str) -> str:
    """Strip surrounding quotes and whitespace, then uppercase."""
    stripped = text.strip().strip('"“”').strip()
    return stripped.upper()


def build_ass(scenes: list[StoryboardScene]) -> str:
    """
    Generate a complete ASS subtitle file string from storyboard scenes.

    Scene timing is derived by accumulating duration_s values in order.
    Scenes with on_screen_text=None produce no Dialogue event.
    Text is uppercased per YouTube Shorts style.
    """
    events: list[str] = []
    offset = 0.0
    for scene in scenes:
        start = offset
        end = offset + scene.duration_s
        if scene.on_screen_text is not None:
            text = _clean_on_screen_text(scene.on_screen_text)
            events.append(
                f"Dialogue: 0,{format_ass_time(start)},{format_ass_time(end)},"
                f"Default,,0,0,0,,{text}"
            )
        offset = end

    if events:
        return _ASS_HEADER + "\n".join(events) + "\n"
    return _ASS_HEADER


def build_word_synced_captions_ass(
    scene_words: list[list[WordTimestamp]],
    chunk_size: int = 5,
    subtitle_style: str = "TikTok",
    aspect_ratio: str = "9:16",
) -> str:
    """
    Build ASS captions with word-level sync from Deepgram timestamps.

    scene_words is a list of per-scene word lists (from assign_words_to_scenes).
    Chunks are formed within each scene independently — they never cross scene
    boundaries.  For each word in a chunk one Dialogue event is emitted spanning
    that word's start_ms → end_ms.  The active word is highlighted in yellow via
    an ASS inline colour override; surrounding words remain white.  Purely
    numeric tokens (e.g. "100000") are spelled out ("one hundred thousand")
    for display only — see spell_out_numbers (D073).
    subtitle_style selects 'TikTok' (default, 80pt Titillium Web SemiBold) or
    'Classic' (56pt).  aspect_ratio restricts the D070/D071/D072 Shorts styling to
    '9:16' — any other value falls back to the original Poppins styling
    unchanged (see _captions_header).
    """
    events: list[str] = []

    for words in scene_words:
        if not words:
            continue
        chunks = [words[i : i + chunk_size] for i in range(0, len(words), chunk_size)]
        for j, chunk in enumerate(chunks):
            next_chunk = chunks[j + 1] if j + 1 < len(chunks) else None
            # Display text only (D073) — spell out numeric tokens for
            # readability. word_ts.word itself is untouched below, since it
            # still drives start_ms/end_ms timing.
            chunk_texts = [spell_out_numbers(w.word) for w in chunk]
            for i, word_ts in enumerate(chunk):
                before = chunk_texts[:i]
                active = "{\\c&H0000FFFF&}" + spell_out_numbers(word_ts.word) + "{\\c&H00FFFFFF&}"
                after = chunk_texts[i + 1 :]
                text = " ".join(before + [active] + after)
                start_s = word_ts.start_ms / 1000.0
                # Extend event to next word's start so the chunk stays on screen
                # with no gap between words.  Last word of a chunk ends at its own
                # end_ms; last word of a non-final chunk extends to the next chunk.
                if i + 1 < len(chunk):
                    end_s = chunk[i + 1].start_ms / 1000.0
                elif next_chunk:
                    end_s = next_chunk[0].start_ms / 1000.0
                else:
                    end_s = word_ts.end_ms / 1000.0
                events.append(
                    f"Dialogue: 0,{format_ass_time(start_s)},{format_ass_time(end_s)},"
                    f"VoiceCaption,,0,0,0,,{text}"
                )

    header = _captions_header(subtitle_style, aspect_ratio)
    if events:
        return header + "\n".join(events) + "\n"
    return header


def _chunk_text(text: str, chunk_size: int = 5) -> list[str]:
    """Split text into chunks of chunk_size words. Last chunk may be smaller."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunks.append(" ".join(words[i : i + chunk_size]))
    return chunks


def build_captions_ass(
    scenes: list[StoryboardScene],
    subtitle_style: str = "TikTok",
    aspect_ratio: str = "9:16",
) -> str:
    """
    Generate an ASS subtitle file for voiceover captions.

    Each scene's voiceover_line is split into 5-word chunks; scene duration is
    divided equally across chunks so each chunk is displayed for the same slice
    of time. Timing is derived by accumulating duration_s values in order.
    Text is displayed as-is (natural sentence case, no quote stripping), except
    purely numeric tokens are spelled out for display (see spell_out_numbers,
    D073).
    Scenes with an empty voiceover_line produce no Dialogue event.
    subtitle_style selects 'TikTok' (default, 80pt Titillium Web SemiBold) or
    'Classic' (56pt).  aspect_ratio restricts the D070/D071/D072 Shorts styling to
    '9:16' — any other value falls back to the original Poppins styling
    unchanged (see _captions_header).
    """
    events: list[str] = []
    offset = 0.0
    for scene in scenes:
        scene_start = offset
        offset += scene.duration_s
        line = scene.voiceover_line.strip()
        if not line:
            continue
        chunks = _chunk_text(line)
        n = len(chunks)
        chunk_duration = scene.duration_s / n
        for i, chunk in enumerate(chunks):
            start = scene_start + i * chunk_duration
            end = scene_start + (i + 1) * chunk_duration
            events.append(
                f"Dialogue: 0,{format_ass_time(start)},{format_ass_time(end)},"
                f"VoiceCaption,,0,0,0,,{spell_out_numbers(chunk)}"
            )

    header = _captions_header(subtitle_style, aspect_ratio)
    if events:
        return header + "\n".join(events) + "\n"
    return header
