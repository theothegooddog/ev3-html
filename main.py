#!/usr/bin/env pybricks-micropython
"""Renders index.html + style.css (+ any <script>) to the EV3 LCD.

Up/Down scroll, Center exits. Left/Right are reserved for page scripts —
see EV3.onButton() in webview/js/dom_bridge.py and the README.
"""

from pybricks.hubs import EV3Brick
from pybricks.parameters import Button
from pybricks.tools import wait

from webview import html_parser, css_parser, layout, render
from webview.js.runtime import Runtime

ev3 = EV3Brick()

SCREEN_WIDTH = 178
SCREEN_HEIGHT = 128
SCROLL_STEP = 10

# Up/Down/Center are reserved by this viewer for scroll/exit; only these
# are ever forwarded to EV3.onButton() in page scripts.
_SCRIPT_BUTTONS = ((Button.LEFT, "left"), (Button.RIGHT, "right"))


def _read(path):
    with open(path) as f:
        return f.read()


def _read_optional(path):
    try:
        return _read(path)
    except OSError:
        return ""


def parse_page(html_path, css_path):
    dom = html_parser.parse(_read(html_path))

    css_text = _read_optional(css_path)
    script_sources = []
    for node in html_parser.iter_nodes(dom):
        if node.tag == "style":
            for child in node.children:
                if child.text:
                    css_text += "\n" + child.text
        elif node.tag == "script":
            src = node.attrs.get("src")
            if src:
                script_sources.append(_read_optional(src))
            else:
                for child in node.children:
                    if child.text:
                        script_sources.append(child.text)

    rules = css_parser.parse(css_text)
    return dom, rules, script_sources


def main():
    dom, rules, script_sources = parse_page("index.html", "style.css")
    runtime = Runtime(dom)
    for source in script_sources:
        runtime.run_source(source)

    screen = render.EV3ScreenAdapter(ev3.screen)
    commands, total_height = layout.layout(dom, rules, SCREEN_WIDTH)

    scroll = 0
    dirty = True

    while True:
        if dirty:
            max_scroll = max(0, total_height - SCREEN_HEIGHT + 4)
            scroll = min(scroll, max_scroll)
            visible = []
            for cmd in commands:
                y0, y1 = render.command_y_range(cmd)
                if y1 >= scroll and y0 <= scroll + SCREEN_HEIGHT:
                    visible.append(render.shift_command(cmd, -scroll))
            render.render(screen, visible)
            dirty = False

        pressed = ev3.buttons.pressed()
        if Button.CENTER in pressed:
            break

        max_scroll = max(0, total_height - SCREEN_HEIGHT + 4)
        if Button.UP in pressed and scroll > 0:
            scroll = max(0, scroll - SCROLL_STEP)
            dirty = True
        elif Button.DOWN in pressed and scroll < max_scroll:
            scroll = min(max_scroll, scroll + SCROLL_STEP)
            dirty = True

        script_pressed = [name for btn, name in _SCRIPT_BUTTONS if btn in pressed]
        if runtime.tick(script_pressed):
            commands, total_height = layout.layout(dom, rules, SCREEN_WIDTH)
            dirty = True

        wait(100)


main()
