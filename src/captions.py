"""ASS subtitle file generator for on-screen text and voiceover captions."""

from src.models import StoryboardScene

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
    "Style: VoiceCaption,Poppins,92,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
    "1,0,0,0,100,100,0,0,1,8,1,2,10,10,250,1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)


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


def _chunk_text(text: str, chunk_size: int = 5) -> list[str]:
    """Split text into chunks of chunk_size words. Last chunk may be smaller."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunks.append(" ".join(words[i : i + chunk_size]))
    return chunks


def build_captions_ass(scenes: list[StoryboardScene]) -> str:
    """
    Generate an ASS subtitle file for voiceover captions.

    Each scene's voiceover_line is split into 5-word chunks; scene duration is
    divided equally across chunks so each chunk is displayed for the same slice
    of time. Timing is derived by accumulating duration_s values in order.
    Text is displayed as-is (natural sentence case, no quote stripping).
    Scenes with an empty voiceover_line produce no Dialogue event.
    Style: Open Sans Regular, 64pt, white+black outline, bottom of screen, MarginV=288.
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
                f"VoiceCaption,,0,0,0,,{chunk}"
            )

    if events:
        return _CAPTIONS_ASS_HEADER + "\n".join(events) + "\n"
    return _CAPTIONS_ASS_HEADER
