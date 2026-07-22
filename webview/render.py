"""Turns layout draw-commands into actual screen calls.

`render()` is display-agnostic: it only needs an object with clear() /
draw_text() / draw_line() / draw_box() methods that accept string colors
("black"/"white") and draw_text() accepting a `size` (px-equivalent font
size). EV3ScreenAdapter wraps the real pybricks `ev3.screen`;
tests/mock_screen.py provides a desktop stand-in for previewing without
hardware.
"""

from . import fonts


class EV3ScreenAdapter:
    """Adapts pybricks' `EV3Brick().screen` to the string-color interface
    used by `render()`.

    Font-size support uses pybricks' `Font`/`Screen.set_font()` — this is
    the one part of this adapter I can't verify against real hardware, so
    every step is wrapped defensively: if `Font`/`set_font` don't exist, or
    a given size fails to construct, text just renders at whatever the
    screen's current/default font is instead of crashing the program.
    """

    def __init__(self, ev3_screen):
        from pybricks.parameters import Color
        self._screen = ev3_screen
        self._Color = Color
        self._font_cache = {}
        self._current_font_size = None
        try:
            from pybricks.media.ev3dev import Font
            self._Font = Font
        except ImportError:
            self._Font = None

    def _c(self, color):
        return self._Color.BLACK if color == "black" else self._Color.WHITE

    def _use_font_size(self, size):
        if self._Font is None or size is None:
            return
        key = int(round(size))
        if key == self._current_font_size:
            return
        if key not in self._font_cache:
            try:
                self._font_cache[key] = self._Font(size=key)
            except Exception:
                self._font_cache[key] = None
        font = self._font_cache[key]
        if font is None:
            return
        try:
            self._screen.set_font(font)
            self._current_font_size = key
        except Exception:
            pass

    def clear(self):
        self._screen.clear()
        self._current_font_size = None

    def draw_text(self, x, y, text, color="black", size=None):
        self._use_font_size(size)
        self._screen.draw_text(x, y, text, text_color=self._c(color))

    def draw_line(self, x1, y1, x2, y2, color="black"):
        self._screen.draw_line(x1, y1, x2, y2, color=self._c(color))

    def draw_box(self, x1, y1, x2, y2, fill=False, color="black"):
        self._screen.draw_box(x1, y1, x2, y2, fill=fill, color=self._c(color))


def render(screen, commands):
    """Draw a list of layout commands onto `screen` (clears it first)."""
    screen.clear()
    for cmd in commands:
        kind = cmd[0]
        if kind == "text":
            _, x, y, text, color, bold, size = cmd
            screen.draw_text(x, y, text, color=color, size=size)
            if bold:
                screen.draw_text(x + 1, y, text, color=color, size=size)
        elif kind == "line":
            _, x1, y1, x2, y2, color = cmd
            screen.draw_line(x1, y1, x2, y2, color=color)
        elif kind == "box":
            _, x1, y1, x2, y2, fill, color = cmd
            screen.draw_box(x1, y1, x2, y2, fill=fill, color=color)


def command_y_range(cmd):
    """Vertical extent of a command, for scrolling/clipping."""
    kind = cmd[0]
    if kind == "text":
        y = cmd[2]
        size = cmd[6] if len(cmd) > 6 else fonts.BASE_FONT_SIZE
        return y, y + fonts.line_height_for(size)
    if kind == "line":
        return cmd[2], cmd[4]
    if kind == "box":
        return cmd[2], cmd[4]
    return 0, 0


def shift_command(cmd, dy):
    """Return a copy of `cmd` shifted vertically by `dy`."""
    kind = cmd[0]
    if kind == "text":
        _, x, y, text, color, bold, size = cmd
        return (kind, x, y + dy, text, color, bold, size)
    if kind == "line":
        _, x1, y1, x2, y2, color = cmd
        return (kind, x1, y1 + dy, x2, y2 + dy, color)
    if kind == "box":
        _, x1, y1, x2, y2, fill, color = cmd
        return (kind, x1, y1 + dy, x2, y2 + dy, fill, color)
    return cmd
