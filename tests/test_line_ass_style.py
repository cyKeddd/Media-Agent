"""Tests for the Issue 68 subtitle/typography restyle in src/subtitles/line_ass.py.

Covers the new module constants (font/size/outline/accent), the
keyword accent-colour behaviour, the shortened fade + scale-in entry,
and the ASS-metacharacter escaping guard against style-block
corruption from narration text.
"""
from __future__ import annotations

from src.subtitles import line_ass
from src.subtitles.line_ass import render_line_ass, wrap_words_to_lines


def _w(word: str, start: float, end: float) -> dict:
    return {"word": word, "start": start, "end": end}


def _dialogue_lines(ass: str) -> list[str]:
    return [l for l in ass.splitlines() if l.startswith("Dialogue:")]


def _style_line(ass: str) -> str:
    lines = [l for l in ass.splitlines() if l.startswith("Style:")]
    assert len(lines) == 1
    return lines[0]


# ---------------------------------------------------------------------------
# Module constants drive the [V4+ Styles] line
# ---------------------------------------------------------------------------


def test_font_is_not_impact():
    assert line_ass.FONT_NAME != "Impact"


def test_style_line_uses_module_font_constant():
    ass = render_line_ass([_w("hi", 0.0, 0.5)])
    style = _style_line(ass)
    assert line_ass.FONT_NAME in style


def test_style_line_uses_module_size_constant():
    ass = render_line_ass([_w("hi", 0.0, 0.5)])
    style = _style_line(ass)
    fields = style.split(",")
    # Format: Name, Fontname, Fontsize, ...
    assert fields[2] == str(line_ass.FONT_SIZE)


def test_style_line_uses_module_outline_constant():
    ass = render_line_ass([_w("hi", 0.0, 0.5)])
    style = _style_line(ass)
    fields = style.split(",")
    # Format: ... BorderStyle, Outline, Shadow, ...
    outline_idx = style.split("Format: ")[0]  # noop, keep field-index approach below
    # Fields (0-indexed): Name0 Font1 Size2 Primary3 Secondary4 Outline5 Back6
    # Bold7 Italic8 Underline9 StrikeOut10 ScaleX11 ScaleY12 Spacing13 Angle14
    # BorderStyle15 Outline16 Shadow17 Alignment18 ...
    assert fields[16] == str(line_ass.OUTLINE_PX)


# ---------------------------------------------------------------------------
# Safe-area anchor and wrap are unchanged
# ---------------------------------------------------------------------------


def test_pos_540_1500_unchanged():
    ass = render_line_ass([_w("hi", 0.0, 0.5)])
    dlines = _dialogue_lines(ass)
    assert r"\pos(540,1500)" in dlines[0]


def test_an5_unchanged():
    ass = render_line_ass([_w("hi", 0.0, 0.5)])
    dlines = _dialogue_lines(ass)
    assert r"\an5" in dlines[0]


def test_wrap_still_breaks_at_28_chars_word_boundary():
    sentence = "Scientists built an AI that edits its own code at runtime"
    word_list = sentence.split()
    words = [_w(w, float(i) * 0.3, float(i) * 0.3 + 0.25) for i, w in enumerate(word_list)]
    lines = wrap_words_to_lines(words)
    for _, _, text in lines:
        assert len(text) <= 28
    reconstructed = " ".join(text for _, _, text in lines)
    assert reconstructed == sentence


# ---------------------------------------------------------------------------
# Shorter fade + scale-in entry
# ---------------------------------------------------------------------------


def test_fade_is_shorter_than_old_100ms_default():
    assert line_ass.FADE_MS < 100
    ass = render_line_ass([_w("hi", 0.0, 0.5)])
    dlines = _dialogue_lines(ass)
    assert f"\\fad({line_ass.FADE_MS},0)" in dlines[0]


def test_line_entry_has_scale_in_transform():
    ass = render_line_ass([_w("hi", 0.0, 0.5)])
    dlines = _dialogue_lines(ass)
    # Starts below 100% scale and animates to 100% via \t.
    assert f"\\fscx{line_ass.SCALE_START_PCT}" in dlines[0]
    assert f"\\fscy{line_ass.SCALE_START_PCT}" in dlines[0]
    assert r"\t(0," in dlines[0]
    assert r"\fscx100\fscy100" in dlines[0]


# ---------------------------------------------------------------------------
# Keyword accent colour
# ---------------------------------------------------------------------------


def test_numeric_token_gets_accent_color():
    words = [_w("It", 0.0, 0.2), _w("has", 0.2, 0.4), _w("120GB", 0.4, 0.9)]
    ass = render_line_ass(words)
    dlines = _dialogue_lines(ass)
    assert line_ass.ACCENT_COLOR in dlines[0]
    assert "120GB" in dlines[0]


def test_only_the_salient_token_is_accented_rest_is_primary():
    words = [_w("Scientists", 0.0, 0.5), _w("built", 0.5, 0.9), _w("500", 0.9, 1.3)]
    ass = render_line_ass(words)
    dlines = _dialogue_lines(ass)
    line = dlines[0]
    # Exactly one accent-open and the tag pair brackets only the "500" token.
    assert line.count(line_ass.ACCENT_COLOR) == 1
    assert line.count(line_ass.PRIMARY_COLOR_TAG) == 1
    accent_start = line.index("\\c" + line_ass.ACCENT_COLOR)
    reset_idx = line.index("\\c" + line_ass.PRIMARY_COLOR_TAG)
    assert accent_start < reset_idx
    between = line[accent_start:reset_idx]
    assert "500" in between
    assert "Scientists" not in between
    assert "built" not in between


def test_line_with_no_emphasis_candidate_has_no_accent_tag_and_no_empty_override():
    # All stopwords / too-short tokens -> no candidate.
    words = [_w("it", 0.0, 0.2), _w("is", 0.2, 0.4), _w("the", 0.4, 0.6), _w("as", 0.6, 0.8)]
    ass = render_line_ass(words)
    dlines = _dialogue_lines(ass)
    line = dlines[0]
    assert line_ass.ACCENT_COLOR not in line
    assert line_ass.PRIMARY_COLOR_TAG not in line
    # No dangling/empty override braces from a would-be accent wrap.
    assert "{}" not in line
    assert r"{\c}" not in line


def test_no_emphasis_candidate_line_renders_without_crash_or_missing_text():
    words = [_w("it", 0.0, 0.2), _w("is", 0.2, 0.4), _w("the", 0.4, 0.6)]
    ass = render_line_ass(words)
    dlines = _dialogue_lines(ass)
    assert "it is the" in dlines[0]


# ---------------------------------------------------------------------------
# ASS metacharacter escaping still holds, including around the accent word
# ---------------------------------------------------------------------------


def test_escaping_holds_for_backslash_and_braces_in_narration():
    ass = render_line_ass([_w("data{leak}\\here", 0.0, 0.5)])
    assert "data{leak}\\here" not in ass
    assert r"data\{leak\}\\here" in ass


def test_narration_brace_cannot_corrupt_the_style_block():
    # A hostile "narration" word containing raw ASS override syntax must
    # not be able to inject an unescaped override tag into the event.
    ass = render_line_ass([_w("{\\pos(0,0)}", 0.0, 0.5)])
    dlines = _dialogue_lines(ass)
    line = dlines[0]
    # The narration's own braces/backslash are fully escaped -- the
    # literal payload survives only inside the escaped form, never as a
    # bare, unescaped override tag of its own.
    assert r"\{\\pos(0,0)\}" in line
    # The only functioning \pos override in the event is the module's
    # own safe-area anchor tag, still intact.
    assert r"\pos(540,1500)" in line
    assert line.count(r"\pos(540,1500)") == 1


def test_escaping_survives_when_the_escaped_word_is_also_the_accent_word():
    # The word containing "{" is also the longest/only candidate, so it
    # gets wrapped in accent tags. The escape must still hold.
    ass = render_line_ass([_w("wow{big}reveal", 0.0, 0.5), _w("ok", 0.5, 0.7)])
    dlines = _dialogue_lines(ass)
    line = dlines[0]
    assert "wow{big}reveal" not in line
    assert r"wow\{big\}reveal" in line
