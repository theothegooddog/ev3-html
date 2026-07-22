"""Selector matching + cascade: turns (DOM node, CSS rules, parent style)
into a computed style dict. Deliberately small: this targets a 178x128
monochrome LCD, not a real browser box model.
"""

from . import css_parser
from . import fonts

INHERITED = ("color", "font-weight", "font-style", "text-align", "font-size")

DEFAULT_STYLE = {
    "display": "inline",
    "color": "black",
    "background-color": "white",
    "font-weight": "normal",
    "font-style": "normal",
    "text-align": "left",
    "font-size": fonts.BASE_FONT_SIZE,
    "margin-top": 0, "margin-right": 0, "margin-bottom": 0, "margin-left": 0,
    "padding-top": 0, "padding-right": 0, "padding-bottom": 0, "padding-left": 0,
    "border": False,
    "width": None,
    "height": None,
}

# Minimal user-agent stylesheet: just enough to make plain HTML look sane.
UA_STYLESHEET = {
    "#root": {"display": "block"},
    "html": {"display": "block"},
    "body": {"display": "block"},
    "div": {"display": "block"},
    "p": {"display": "block", "margin": "3px 0"},
    "h1": {"display": "block", "font-weight": "bold", "margin": "5px 0", "font-size": "xx-large"},
    "h2": {"display": "block", "font-weight": "bold", "margin": "4px 0", "font-size": "x-large"},
    "h3": {"display": "block", "font-weight": "bold", "margin": "4px 0", "font-size": "large"},
    "h4": {"display": "block", "font-weight": "bold", "margin": "3px 0", "font-size": "medium"},
    "h5": {"display": "block", "font-weight": "bold", "margin": "3px 0", "font-size": "small"},
    "h6": {"display": "block", "font-weight": "bold", "margin": "3px 0", "font-size": "x-small"},
    "ul": {"display": "block", "margin": "3px 0", "padding-left": "8px"},
    "ol": {"display": "block", "margin": "3px 0", "padding-left": "8px"},
    "li": {"display": "block"},
    "hr": {"display": "block", "margin": "3px 0"},
    "vr": {"display": "inline"},
    "br": {"display": "inline"},
    "span": {"display": "inline"},
    "a": {"display": "inline"},
    "b": {"display": "inline", "font-weight": "bold"},
    "strong": {"display": "inline", "font-weight": "bold"},
    "i": {"display": "inline", "font-style": "italic"},
    "em": {"display": "inline", "font-style": "italic"},
    "img": {"display": "inline"},
    "head": {"display": "none"},
    "title": {"display": "none"},
    "style": {"display": "none"},
    "script": {"display": "none"},
    "meta": {"display": "none"},
    "link": {"display": "none"},
}

_BOX_PROPS = (
    "margin-top", "margin-right", "margin-bottom", "margin-left",
    "padding-top", "padding-right", "padding-bottom", "padding-left",
)

_LIGHT_COLORS = set([
    "white", "#fff", "#ffffff", "transparent", "silver",
    "lightgray", "lightgrey", "#eee", "#eeeeee", "#ccc", "#cccccc",
])


def to_mono(color):
    """Map an arbitrary CSS color keyword to 'black' or 'white' for the 1-bit screen."""
    c = (color or "").strip().lower()
    return "white" if c in _LIGHT_COLORS else "black"


def _px(v, default=0):
    if v is None:
        return default
    v = v.strip()
    if v.endswith("px"):
        v = v[:-2]
    try:
        return int(float(v))
    except ValueError:
        return default


def _expand_box(prefix, value, out):
    vals = [_px(p) for p in value.split()]
    if not vals:
        return
    if len(vals) == 1:
        t = r = b = l = vals[0]
    elif len(vals) == 2:
        t = b = vals[0]
        r = l = vals[1]
    elif len(vals) == 3:
        t = vals[0]
        r = l = vals[1]
        b = vals[2]
    else:
        t, r, b, l = vals[0], vals[1], vals[2], vals[3]
    out[prefix + "-top"] = t
    out[prefix + "-right"] = r
    out[prefix + "-bottom"] = b
    out[prefix + "-left"] = l


def _matches_simple(node, part):
    if part == "*":
        return True
    i, n = 0, len(part)
    tag = ""
    while i < n and part[i] not in ".#":
        tag += part[i]
        i += 1
    if tag and tag != "*" and node.tag != tag:
        return False
    classes = (node.attrs.get("class", "") or "").split()
    node_id = node.attrs.get("id", "")
    while i < n:
        if part[i] == "#":
            i += 1
            start = i
            while i < n and part[i] not in ".#":
                i += 1
            if part[start:i] != node_id:
                return False
        elif part[i] == ".":
            i += 1
            start = i
            while i < n and part[i] not in ".#":
                i += 1
            if part[start:i] not in classes:
                return False
    return True


def matches(node, selector):
    """Descendant-combinator selector matching (e.g. 'div p', '.card h2')."""
    parts = selector.split()
    if not parts or node.tag is None:
        return False
    if not _matches_simple(node, parts[-1]):
        return False
    ancestor = node.parent
    for part in reversed(parts[:-1]):
        found = False
        while ancestor is not None:
            if _matches_simple(ancestor, part):
                found = True
                ancestor = ancestor.parent
                break
            ancestor = ancestor.parent
        if not found:
            return False
    return True


def compute(node, rules, parent_style):
    """Compute the cascaded style for `node` given its parent's computed style."""
    style = {}
    if parent_style:
        for k in INHERITED:
            style[k] = parent_style[k]
    for k, v in DEFAULT_STYLE.items():
        if k not in style:
            style[k] = v

    decls = {}
    ua = UA_STYLESHEET.get(node.tag)
    if ua:
        decls.update(ua)

    matched = [r for r in rules if matches(node, r.selector)]
    matched.sort(key=lambda r: (r.specificity, r.order))
    for r in matched:
        decls.update(r.decls)

    inline = node.attrs.get("style") if node.tag else None
    if inline:
        decls.update(css_parser.parse_inline(inline))

    for k, v in decls.items():
        if k == "margin":
            _expand_box("margin", v, style)
        elif k == "padding":
            _expand_box("padding", v, style)
        elif k in _BOX_PROPS:
            style[k] = _px(v)
        elif k == "width":
            style["width"] = None if v == "auto" else _px(v, None)
        elif k == "height":
            style["height"] = None if v == "auto" else _px(v, None)
        elif k == "border":
            style["border"] = "none" not in v.lower()
        elif k == "font-size":
            style["font-size"] = fonts.resolve_font_size(_parse_font_size(v))
        elif k in ("display", "font-weight", "font-style", "text-align"):
            style[k] = v.lower()
        elif k in ("color", "background-color"):
            style[k] = v
    return style


def _parse_font_size(v):
    """'16px' -> 16.0, '16' -> 16.0, 'large' -> 'large' (resolved by
    fonts.resolve_font_size's keyword table), anything unparseable -> None
    (falls back to fonts.BASE_FONT_SIZE)."""
    vv = v.strip()
    text = vv[:-2] if vv.endswith("px") else vv
    try:
        return float(text)
    except ValueError:
        return vv
