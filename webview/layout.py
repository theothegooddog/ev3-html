"""Block/inline layout engine.

Walks a styled DOM tree and produces a flat list of draw commands:
  ("text", x, y, text, color, bold, font_size)
  ("line", x1, y1, x2, y2, color)          -- also used for <vr>, x1==x2
  ("box",  x1, y1, x2, y2, fill, color)

Block-level elements (div/p/h1..h6/ul/li/...) stack vertically with
margins/padding. A container whose children are all inline (span/b/i/a/text)
is flowed as wrapped, aligned text lines. When inline/text content sits
next to block siblings (e.g. recovered malformed markup), it's flowed as
its own anonymous line-box between the surrounding block children, the way
browsers handle stray inline content.

<vr> (vertical rule -- not real HTML, mirrors <hr>) is an inline element:
it's flowed as a fixed-width "word" in the text stream and rendered as a
vertical line spanning its line's height, for toolbar-style dividers
(e.g. "Title | status") that HTML/CSS has no built-in element for.
"""

from . import style as style_mod
from .fonts import (
    Word, wrap_words, word_width, line_width, line_height_of,
    BASE_FONT_SIZE, SPACE_WIDTH, VR_WIDTH,
)


def _is_block(node, rules, parent_style):
    if node.tag is None:
        return False
    node.style = style_mod.compute(node, rules, parent_style)
    return node.style.get("display") == "block"


def _collect_inline(nodes, rules, parent_style, words):
    """Recursively gather Word entries (and None break-sentinels) for a run
    of sibling nodes (mix of text nodes and inline elements)."""
    for child in nodes:
        if child.tag is None:
            text = child.text or ""
            color = style_mod.to_mono(parent_style.get("color"))
            bold = parent_style.get("font-weight") == "bold"
            size = parent_style.get("font-size", BASE_FONT_SIZE)
            for w in text.split():
                words.append(Word(w, color, bold, size))
            continue

        child.style = style_mod.compute(child, rules, parent_style)
        if child.style.get("display") == "none":
            continue

        if child.tag == "br":
            words.append(None)
            continue

        if child.tag == "vr":
            color = style_mod.to_mono(child.style.get("color"))
            words.append(Word("", color, False, child.style.get("font-size", BASE_FONT_SIZE), is_vr=True))
            continue

        if child.tag == "img":
            alt = child.attrs.get("alt", "img")
            color = style_mod.to_mono(child.style.get("color"))
            words.append(Word("[%s]" % alt, color, False, child.style.get("font-size", BASE_FONT_SIZE)))
            continue

        _collect_inline(child.children, rules, child.style, words)


def _flow_words(words, computed, x, width, y):
    commands = []
    if not words:
        return commands, y

    widths = [word_width(w) for w in words if w is not None]
    min_width = max(widths) if widths else VR_WIDTH
    lines = wrap_words(words, max(width, min_width))
    align = computed.get("text-align", "left")
    for line in lines:
        if not line:
            y += line_height_of([])
            continue
        line_h = line_height_of(line)
        lw = line_width(line)
        if align == "center":
            lx = x + max(0, (width - lw) // 2)
        elif align == "right":
            lx = x + max(0, width - lw)
        else:
            lx = x
        cx = lx
        for word in line:
            if word.is_vr:
                vx = cx + VR_WIDTH // 2
                commands.append(("line", vx, y, vx, y + line_h, word.color))
            else:
                commands.append(("text", cx, y, word.text, word.color, word.bold, word.font_size))
            cx += word_width(word) + SPACE_WIDTH
        y += line_h
    return commands, y


def _list_prefix(node, computed):
    if node.tag != "li":
        return None
    parent_tag = node.parent.tag if node.parent else None
    if parent_tag == "ol":
        node.parent._ol_count += 1
        return "%d." % node.parent._ol_count
    return "-"


def _render_inline_block(node, rules, computed, x, width, y):
    words = []
    prefix = _list_prefix(node, computed)
    if prefix:
        words.append(Word(prefix, style_mod.to_mono(computed.get("color")), False,
                           computed.get("font-size", BASE_FONT_SIZE)))
    _collect_inline(node.children, rules, computed, words)
    return _flow_words(words, computed, x, width, y)


class _Cursor:
    __slots__ = ("y",)

    def __init__(self, y):
        self.y = y


def _layout_block(node, rules, computed, x, width, cursor, commands):
    st = computed
    cursor.y += st["margin-top"]
    box_x = x + st["margin-left"]
    box_w = st["width"] if st["width"] is not None else (width - st["margin-left"] - st["margin-right"])
    content_x = box_x + st["padding-left"]
    content_w = box_w - st["padding-left"] - st["padding-right"]
    box_top = cursor.y
    cursor.y += st["padding-top"]

    if node.tag == "hr":
        color = style_mod.to_mono(st.get("color"))
        commands.append(("line", content_x, cursor.y, content_x + content_w, cursor.y, color))
        cursor.y += 2
    else:
        block_children = [
            c for c in node.children
            if c.tag is not None and _is_block(c, rules, st)
        ]
        has_block_child = len(block_children) > 0

        if has_block_child:
            run = []

            def flush_run():
                if not run:
                    return
                words = []
                _collect_inline(run, rules, st, words)
                run_cmds, new_y = _flow_words(words, st, content_x, content_w, cursor.y)
                commands.extend(run_cmds)
                cursor.y = new_y
                del run[:]

            for c in node.children:
                if c.tag is None:
                    run.append(c)
                    continue
                if c.style is None:
                    c.style = style_mod.compute(c, rules, st)
                if c.style.get("display") == "none":
                    continue
                if c.style.get("display") == "block":
                    flush_run()
                    _layout_block(c, rules, c.style, content_x, content_w, cursor, commands)
                else:
                    run.append(c)
            flush_run()
        else:
            inline_cmds, new_y = _render_inline_block(node, rules, st, content_x, content_w, cursor.y)
            commands.extend(inline_cmds)
            cursor.y = new_y

    if st.get("border"):
        color = style_mod.to_mono(st.get("color"))
        commands.append(("box", box_x, box_top, box_x + box_w, cursor.y + st["padding-bottom"], False, color))

    cursor.y += st["padding-bottom"]
    cursor.y += st["margin-bottom"]


def layout(root, rules, screen_width, content_x=2, top=2):
    """Lay out `root` (as produced by html_parser.parse) and return
    (commands, total_height)."""
    content_width = screen_width - content_x * 2
    root.style = style_mod.compute(root, rules, None)
    root.style["display"] = "block"
    cursor = _Cursor(top)
    commands = []
    _layout_block(root, rules, root.style, content_x, content_width, cursor, commands)
    return commands, cursor.y
