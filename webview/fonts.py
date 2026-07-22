"""Approximate metrics for the EV3 screen's default bitmap font.

pybricks' `Screen.draw_text` uses a fixed-width font whose exact pixel size
isn't queryable from MicroPython, and it doesn't match the font used by
tests/preview.py's desktop mock — so these numbers can only really be
verified on real hardware. Run calibrate.py on the brick (see its
docstring) to find exact values for your firmware, then update
BASE_CHAR_WIDTH/BASE_LINE_HEIGHT below. Until then these are a
conservative placeholder, deliberately erring toward "too much space"
rather than overlapping text.

BASE_FONT_SIZE is the nominal CSS font-size (in px-equivalent units) that
BASE_CHAR_WIDTH/BASE_LINE_HEIGHT were calibrated at ("normal" text).
Other font-size values scale both proportionally — see char_width_for()/
line_height_for(). This is a rough approximation (real fonts don't scale
glyph width and line height perfectly linearly), fine for a 178x128
1-bit display, not for typographic precision.
"""

BASE_FONT_SIZE = 10.0
BASE_CHAR_WIDTH = 14
BASE_LINE_HEIGHT = 20
SPACE_WIDTH = BASE_CHAR_WIDTH

# Width reserved for an inline <vr> (vertical rule) "word" in the text flow.
VR_WIDTH = 8

FONT_SIZE_KEYWORDS = {
    "xx-small": 6.0, "x-small": 8.0, "small": 9.0, "medium": 10.0,
    "large": 13.0, "x-large": 16.0, "xx-large": 20.0,
}


def resolve_font_size(value):
    """value: a px number, a CSS keyword string, or None -> px-equivalent
    float. Unrecognized keywords/None fall back to BASE_FONT_SIZE."""
    if value is None:
        return BASE_FONT_SIZE
    if isinstance(value, (int, float)):
        return float(value)
    return FONT_SIZE_KEYWORDS.get(value, BASE_FONT_SIZE)


def char_width_for(font_size):
    scale = font_size / BASE_FONT_SIZE
    return max(3, int(BASE_CHAR_WIDTH * scale))


def line_height_for(font_size):
    scale = font_size / BASE_FONT_SIZE
    return max(6, int(BASE_LINE_HEIGHT * scale))


class Word:
    __slots__ = ("text", "color", "bold", "font_size", "is_vr")

    def __init__(self, text, color, bold, font_size=BASE_FONT_SIZE, is_vr=False):
        self.text = text
        self.color = color
        self.bold = bold
        self.font_size = font_size
        self.is_vr = is_vr


def text_width(text, font_size=BASE_FONT_SIZE):
    return len(text) * char_width_for(font_size)


def word_width(word):
    if word.is_vr:
        return VR_WIDTH
    return text_width(word.text, word.font_size)


def line_width(words):
    if not words:
        return 0
    w = sum(word_width(word) for word in words)
    w += SPACE_WIDTH * (len(words) - 1)
    return w


def line_height_of(words):
    """A line's height is the tallest non-<vr> word on it (<vr> stretches
    to fill whatever height the line ends up with); falls back to
    BASE_FONT_SIZE's line height for a line that's only a <vr>."""
    sizes = [w.font_size for w in words if not w.is_vr]
    if not sizes:
        return line_height_for(BASE_FONT_SIZE)
    return max(line_height_for(s) for s in sizes)


def wrap_words(words, max_width):
    """Greedy word wrap. `words` may contain `None` sentinels for forced
    breaks (<br>). Returns a list of lines, each a list of Word."""
    lines = []
    current = []
    cur_w = 0
    for word in words:
        if word is None:
            lines.append(current)
            current = []
            cur_w = 0
            continue
        w = word_width(word)
        add_w = w if not current else w + SPACE_WIDTH
        if current and cur_w + add_w > max_width:
            lines.append(current)
            current = [word]
            cur_w = w
        else:
            current.append(word)
            cur_w += add_w
    if current or not lines:
        lines.append(current)
    return lines
