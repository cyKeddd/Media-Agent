"""Line-at-a-time ASS subtitle writer for Pivot.6 AI-generated content.

Replaces the karaoke-style ass_writer.py for Pivot.6. The old writer
animated per-word; this one displays one full line at a time — simpler,
more readable on a 16s Short with fast TTS narration.

Input: [{word, start, end}] from Whisper forced-alignment on the TTS mp3.
Output: ASS file content with one Dialogue event per display line.

Layout (same anchors as karaoke writer):
  1080x1920 canvas, pos(540,1500), an5 (middle-center).
  fad(FADE_MS,0) + a slight scale-in transform on line entry.
  Max 28 chars/line, broken at word boundaries.

Typography restyle (Issue 68): Impact -> Arial Black. Arial Black is
confirmed present on the render box via the Windows font registry
(HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts ->
"Arial Black (TrueType)" = ariblk.ttf) so libass resolves the family by
name without a silent fallback. The salient token per line (first
numeric token, else the longest non-stopword) is rendered in
ACCENT_COLOR; everything else stays PRIMARY_COLOR. A line with no
emphasis candidate renders with no colour-override tags at all.
"""

from __future__ import annotations

from pathlib import Path

PLAY_RES_X = 1080
PLAY_RES_Y = 1920
ANCHOR_X = 540
ANCHOR_Y = 1500
FONT_NAME = "Arial Black"
FONT_SIZE = 100
PRIMARY_COLOR = "&H00FFFFFF"
OUTLINE_COLOR = "&H00000000"
OUTLINE_PX = 6
MAX_CHARS = 28
FADE_MS = 60
SCALE_START_PCT = 80

# Inline override-tag colours (BBGGRR, no alpha byte -- distinct format
# from the AABBGGRR style-line colours above).
ACCENT_COLOR = "&H00D1FF&"
PRIMARY_COLOR_TAG = "&HFFFFFF&"

# Words too common to ever be the emphasised token, even if they happen
# to be the longest word on a short line.
_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "of", "to", "in", "on",
    "for", "and", "or", "but", "at", "it", "its", "that", "this", "with",
    "as", "by", "be", "from", "has", "have", "had", "will", "just", "not",
    "so", "if", "than", "then", "you", "your", "we", "our", "they", "them",
}

ASS_HEADER = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    f"PlayResX: {PLAY_RES_X}\n"
    f"PlayResY: {PLAY_RES_Y}\n"
    "ScaledBorderAndShadow: yes\n"
    "\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
    "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    f"Style: Subtitle,{FONT_NAME},{FONT_SIZE},{PRIMARY_COLOR},&H000000FF,{OUTLINE_COLOR},&H00000000,"
    f"-1,0,0,0,100,100,0,0,1,{OUTLINE_PX},0,5,30,30,0,1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)


def _escape(text: str) -> str:
    """Escape ASS dialogue metacharacters: \\, {, }."""
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "\\{").replace("}", "\\}")
    text = text.replace("\n", " ").replace("\r", " ")
    return text


def _pick_accent_word(words: list[str]) -> str | None:
    """Pick the salient token in a line for accent-colour emphasis.

    Preference: first token containing a digit (stats/specs read as
    numerically salient), else the longest non-stopword token. Returns
    None when no candidate qualifies -- the line then renders entirely
    in the primary colour.
    """
    for w in words:
        if any(c.isdigit() for c in w):
            return w

    candidates = [
        w for w in words
        if len(w) > 2 and w.strip(".,!?;:'\"").lower() not in _STOPWORDS
    ]
    if not candidates:
        return None
    return max(candidates, key=len)


def _style_line_text(text: str) -> str:
    """Escape and accent-colour a wrapped line's text for the Text field.

    Wraps the single salient token (see _pick_accent_word) in
    ACCENT_COLOR override tags, resetting to PRIMARY_COLOR_TAG right
    after it. Escaping is applied per-word so the override tags can
    never straddle an escaped `{`/`}`/`\\` from the narration text.
    """
    words = text.split(" ")
    accent_word = _pick_accent_word(words)
    if accent_word is None:
        return _escape(text)

    accent_idx = words.index(accent_word)
    styled: list[str] = []
    for i, w in enumerate(words):
        esc = _escape(w)
        if i == accent_idx:
            styled.append(f"{{\\c{ACCENT_COLOR}}}{esc}{{\\c{PRIMARY_COLOR_TAG}}}")
        else:
            styled.append(esc)
    return " ".join(styled)


def _format_time(seconds: float) -> str:
    """ASS time format: H:MM:SS.cc (centiseconds)."""
    if seconds < 0:
        seconds = 0.0
    cs_total = int(round(seconds * 100))
    cs = cs_total % 100
    s_total = cs_total // 100
    s = s_total % 60
    m = (s_total // 60) % 60
    h = s_total // 3600
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def wrap_words_to_lines(
    word_timings: list[dict],
    max_chars: int = MAX_CHARS,
) -> list[tuple[float, float, str]]:
    """Group word timings into display lines of <= max_chars chars.

    Returns list of (start_s, end_s, line_text). Words that would push
    a line over max_chars start a new line. A single word exceeding
    max_chars still gets its own line (no truncation).
    """
    if not word_timings:
        return []

    lines: list[tuple[float, float, str]] = []
    current_words: list[str] = []
    line_start: float = word_timings[0]["start"]
    line_end: float = word_timings[0]["end"]

    for w in word_timings:
        word = w["word"].strip()
        if not word:
            continue

        candidate = " ".join(current_words + [word]) if current_words else word

        if current_words and len(candidate) > max_chars:
            # Flush current line and start fresh.
            lines.append((line_start, line_end, " ".join(current_words)))
            current_words = [word]
            line_start = w["start"]
            line_end = w["end"]
        else:
            current_words.append(word)
            if not current_words[:-1]:  # first word sets line_start
                line_start = w["start"]
            line_end = w["end"]

    if current_words:
        lines.append((line_start, line_end, " ".join(current_words)))

    return lines


def render_line_ass(
    word_timings: list[dict],
    *,
    max_chars: int = MAX_CHARS,
    fade_ms: int = FADE_MS,
) -> str:
    """Build full .ass content for line-at-a-time subtitles.

    Empty input -> header only (valid no-op ASS file).
    """
    lines = wrap_words_to_lines(word_timings, max_chars=max_chars)
    if not lines:
        return ASS_HEADER

    events: list[str] = []
    pos_tag = f"{{\\an5\\pos({ANCHOR_X},{ANCHOR_Y})}}"
    entry_tag = (
        f"{{\\fad({fade_ms},0)\\fscx{SCALE_START_PCT}\\fscy{SCALE_START_PCT}"
        f"\\t(0,{fade_ms},\\fscx100\\fscy100)}}"
    )

    for start_s, end_s, text in lines:
        styled = _style_line_text(text)
        text_field = f"{pos_tag}{entry_tag}{styled}"
        events.append(
            f"Dialogue: 0,{_format_time(start_s)},{_format_time(end_s)},"
            f"Subtitle,,0,0,0,,{text_field}"
        )

    return ASS_HEADER + "\n".join(events) + "\n"


def write_line_ass_file(path: Path | str, word_timings: list[dict], **kwargs) -> None:
    """Write ASS file to disk (UTF-8). kwargs forwarded to render_line_ass."""
    content = render_line_ass(word_timings, **kwargs)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
