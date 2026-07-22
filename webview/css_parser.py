"""A tiny CSS parser: selectors (tag, .class, #id, descendant combinator)
plus a flat declaration block. No `re` dependency, works under MicroPython.
"""


class Rule:
    __slots__ = ("selector", "decls", "specificity", "order")

    def __init__(self, selector, decls, order):
        self.selector = selector
        self.decls = decls
        self.specificity = _specificity(selector)
        self.order = order


def _specificity(selector):
    ids = classes = tags = 0
    for part in selector.split():
        j, n = 0, len(part)
        while j < n:
            ch = part[j]
            if ch == "#":
                ids += 1
                j += 1
                while j < n and part[j] not in ".#":
                    j += 1
            elif ch == ".":
                classes += 1
                j += 1
                while j < n and part[j] not in ".#":
                    j += 1
            else:
                start = j
                while j < n and part[j] not in ".#":
                    j += 1
                name = part[start:j]
                if name and name != "*":
                    tags += 1
    return (ids, classes, tags)


def _strip_comments(s):
    out = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "/" and i + 1 < n and s[i + 1] == "*":
            end = s.find("*/", i + 2)
            i = end + 2 if end != -1 else n
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _parse_decls(body):
    decls = {}
    for part in body.split(";"):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        k = k.strip().lower()
        v = v.strip()
        if k:
            decls[k] = v
    return decls


def parse(css_text):
    """Parse a stylesheet string into a list of Rule objects."""
    css_text = _strip_comments(css_text)
    rules = []
    i, n = 0, len(css_text)
    order = 0
    while i < n:
        brace = css_text.find("{", i)
        if brace == -1:
            break
        selector_text = css_text[i:brace].strip()
        end = css_text.find("}", brace)
        if end == -1:
            break
        decls = _parse_decls(css_text[brace + 1:end])
        if selector_text:
            for sel in selector_text.split(","):
                sel = sel.strip()
                if sel:
                    rules.append(Rule(sel, decls, order))
                    order += 1
        i = end + 1
    return rules


def parse_inline(style_attr):
    """Parse the contents of a `style="..."` attribute into a decl dict."""
    return _parse_decls(style_attr)
