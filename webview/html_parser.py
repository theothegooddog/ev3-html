"""A tiny, tolerant HTML parser.

Builds a DOM-like tree of Node objects out of a small, hand-rolled tokenizer.
No dependency on the `re`/`html.parser` modules so it runs unmodified under
EV3 MicroPython (pybricks-micropython) as well as desktop CPython.
"""

VOID_TAGS = set([
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
    "vr",  # custom: vertical rule, not real HTML — see webview/style.py
])

RAW_TEXT_TAGS = set(["script", "style"])

_ENTITIES = {
    "amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " ",
}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "text", "style", "_ol_count")

    def __init__(self, tag=None, attrs=None, text=None):
        self.tag = tag
        self.attrs = attrs if attrs is not None else {}
        self.children = []
        self.parent = None
        self.text = text
        self.style = None
        self._ol_count = 0

    def append(self, child):
        child.parent = self
        self.children.append(child)

    def get(self, name, default=None):
        return self.attrs.get(name, default)

    def __repr__(self):
        if self.tag is None:
            return "Text(%r)" % (self.text,)
        return "<%s %r>" % (self.tag, self.attrs)


def _decode_entities(s):
    if "&" not in s:
        return s
    out = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "&":
            end = s.find(";", i)
            if end != -1 and end - i <= 10:
                name = s[i + 1:end]
                if name in _ENTITIES:
                    out.append(_ENTITIES[name])
                    i = end + 1
                    continue
                if name.startswith("#"):
                    try:
                        code = int(name[2:], 16) if name[1:2] in ("x", "X") else int(name[1:])
                        out.append(chr(code))
                        i = end + 1
                        continue
                    except ValueError:
                        pass
            out.append(c)
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _parse_attrs(s):
    attrs = {}
    i, n = 0, len(s)
    while i < n:
        while i < n and s[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        start = i
        while i < n and s[i] not in " \t\r\n=":
            i += 1
        name = s[start:i].lower()
        if not name or name == "/":
            i += 1
            continue
        while i < n and s[i] in " \t\r\n":
            i += 1
        value = ""
        if i < n and s[i] == "=":
            i += 1
            while i < n and s[i] in " \t\r\n":
                i += 1
            if i < n and s[i] in ("'", '"'):
                quote = s[i]
                i += 1
                start = i
                while i < n and s[i] != quote:
                    i += 1
                value = s[start:i]
                i += 1
            else:
                start = i
                while i < n and s[i] not in " \t\r\n":
                    i += 1
                value = s[start:i]
        attrs[name] = _decode_entities(value)
    return attrs


def parse(html):
    """Parse an HTML document/fragment string into a tree rooted at a `#root` Node."""
    root = Node(tag="#root")
    stack = [root]
    i, n = 0, len(html)

    while i < n:
        lt = html.find("<", i)
        if lt == -1:
            text = html[i:]
            if text.strip():
                stack[-1].append(Node(text=_decode_entities(text)))
            break

        if lt > i:
            text = html[i:lt]
            if text.strip():
                stack[-1].append(Node(text=_decode_entities(text)))

        if html[lt:lt + 4] == "<!--":
            end = html.find("-->", lt + 4)
            i = end + 3 if end != -1 else n
            continue

        if html[lt:lt + 2] == "<!" or html[lt:lt + 2] == "<?":
            end = html.find(">", lt)
            i = end + 1 if end != -1 else n
            continue

        gt = html.find(">", lt)
        if gt == -1:
            break
        inner = html[lt + 1:gt]
        i = gt + 1

        if inner.startswith("/"):
            tagname = inner[1:].strip().lower()
            for depth in range(len(stack) - 1, 0, -1):
                if stack[depth].tag == tagname:
                    del stack[depth:]
                    break
            continue

        self_close = inner.endswith("/")
        if self_close:
            inner = inner[:-1]

        sp = 0
        while sp < len(inner) and inner[sp] not in " \t\r\n":
            sp += 1
        tagname = inner[:sp].lower()
        if not tagname:
            continue
        attrs = _parse_attrs(inner[sp:])
        node = Node(tag=tagname, attrs=attrs)
        stack[-1].append(node)

        if tagname in RAW_TEXT_TAGS and not self_close:
            close_tag = "</" + tagname
            end = html.lower().find(close_tag, i)
            raw = html[i:end] if end != -1 else html[i:]
            if raw.strip():
                node.append(Node(text=raw))
            if end != -1:
                gt2 = html.find(">", end)
                i = gt2 + 1 if gt2 != -1 else n
            else:
                i = n
            continue

        if not self_close and tagname not in VOID_TAGS:
            stack.append(node)

    return root


def iter_nodes(node):
    """Depth-first iterator over a node and all its descendants."""
    yield node
    for child in node.children:
        for sub in iter_nodes(child):
            yield sub
