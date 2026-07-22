"""Bridges the JS interpreter to webview's DOM (html_parser.Node tree) and
to EV3 hardware events. This is a small, purpose-built API — not a real
browser DOM — scoped to what's useful for scripting a page on a 178x128
LCD with 5 buttons:

  document.getElementById(id) / querySelector(sel) / querySelectorAll(sel)
  element.textContent (get/set), .id, .tagName, .children
  element.getAttribute(name) / setAttribute(name, value)
  element.style.color / .backgroundColor / .display / .fontWeight /
          .fontStyle / .textAlign / .border / .width / .height /
          .margin / .padding   (get/set; camelCase -> kebab-case)
  element.classList.add/remove/toggle/contains
  console.log(...)
  Math.floor/ceil/round/abs/max/min/sqrt/random/PI
  EV3.onButton("left"|"right"|"up"|"down"|"center", fn)  -- see note below
  EV3.onTick(fn)             -- called every ~100ms main-loop iteration
  EV3.after(ticks, fn)       -- one-shot delayed call

Note: Up/Down/Center are reserved by main.py for page scrolling and exit,
so EV3.onButton only ever fires for "left"/"right" in practice — see
main.py and the README for the reasoning.

Any DOM/style/class mutation calls back into a `mark_dirty` callback so
the caller (webview.js.runtime.Runtime) knows to re-run layout + redraw.
"""

from .. import html_parser
from .. import css_parser
from .. import style as style_mod
from .interpreter import HostObject, JSError, to_js_string


_STYLE_PROPS = {
    "color": "color",
    "backgroundColor": "background-color",
    "display": "display",
    "fontWeight": "font-weight",
    "fontStyle": "font-style",
    "textAlign": "text-align",
    "border": "border",
    "width": "width",
    "height": "height",
    "margin": "margin",
    "padding": "padding",
}


class StyleProxy(HostObject):
    def __init__(self, element):
        self._element = element

    def _decls(self):
        return css_parser.parse_inline(self._element.node.attrs.get("style", "") or "")

    def get(self, name):
        prop = _STYLE_PROPS.get(name)
        if prop is None:
            return None
        return self._decls().get(prop)

    def set(self, name, value):
        prop = _STYLE_PROPS.get(name)
        if prop is None:
            raise JSError("unknown style property '%s'" % name)
        decls = self._decls()
        decls[prop] = to_js_string(value)
        self._element.node.attrs["style"] = "; ".join("%s: %s" % kv for kv in decls.items())
        self._element.mark_dirty()


class ClassListProxy(HostObject):
    def __init__(self, element):
        self._element = element

    def _classes(self):
        return (self._element.node.attrs.get("class", "") or "").split()

    def _write(self, classes):
        self._element.node.attrs["class"] = " ".join(classes)
        self._element.mark_dirty()

    def get(self, name):
        if name == "add":
            def _add(args):
                classes = self._classes()
                for c in args:
                    if c not in classes:
                        classes.append(c)
                self._write(classes)
            return _add
        if name == "remove":
            def _remove(args):
                self._write([c for c in self._classes() if c not in args])
            return _remove
        if name == "toggle":
            def _toggle(args):
                classes = self._classes()
                c = args[0]
                if c in classes:
                    classes.remove(c)
                    self._write(classes)
                    return False
                classes.append(c)
                self._write(classes)
                return True
            return _toggle
        if name == "contains":
            return lambda args: args[0] in self._classes()
        raise JSError("unknown classList method '%s'" % name)


class Element(HostObject):
    def __init__(self, node, mark_dirty_fn):
        self.node = node
        self._mark_dirty = mark_dirty_fn

    def mark_dirty(self):
        self._mark_dirty()

    def get(self, name):
        if name in ("textContent", "innerText"):
            return _text_content(self.node)
        if name == "style":
            return StyleProxy(self)
        if name == "classList":
            return ClassListProxy(self)
        if name == "id":
            return self.node.attrs.get("id", "")
        if name == "tagName":
            return (self.node.tag or "").upper()
        if name == "children":
            return [Element(c, self._mark_dirty) for c in self.node.children if c.tag]
        if name == "getAttribute":
            return lambda args: self.node.attrs.get(args[0])
        if name == "setAttribute":
            def _set(args):
                self.node.attrs[args[0]] = to_js_string(args[1])
                self.mark_dirty()
            return _set
        raise JSError("unknown element property '%s'" % name)

    def set(self, name, value):
        if name in ("textContent", "innerText"):
            self.node.children = [html_parser.Node(text=to_js_string(value))]
            self.mark_dirty()
            return
        raise JSError("cannot set element property '%s'" % name)


def _text_content(node):
    parts = []

    def walk(n):
        if n.text is not None:
            parts.append(n.text)
        for c in n.children:
            walk(c)

    walk(node)
    return " ".join(p.strip() for p in parts if p.strip())


class Document(HostObject):
    def __init__(self, dom_root, mark_dirty_fn):
        self._root = dom_root
        self._mark_dirty = mark_dirty_fn

    def get(self, name):
        if name == "getElementById":
            def _get(args):
                target_id = args[0]
                for node in html_parser.iter_nodes(self._root):
                    if node.tag and node.attrs.get("id") == target_id:
                        return Element(node, self._mark_dirty)
                return None
            return _get
        if name == "querySelector":
            def _qs(args):
                sel = args[0]
                for node in html_parser.iter_nodes(self._root):
                    if node.tag and style_mod.matches(node, sel):
                        return Element(node, self._mark_dirty)
                return None
            return _qs
        if name == "querySelectorAll":
            def _qsa(args):
                sel = args[0]
                return [Element(node, self._mark_dirty)
                        for node in html_parser.iter_nodes(self._root)
                        if node.tag and style_mod.matches(node, sel)]
            return _qsa
        raise JSError("unknown document property '%s'" % name)


class EV3Api(HostObject):
    def __init__(self, runtime):
        self._runtime = runtime

    def get(self, name):
        if name == "onButton":
            def _on(args):
                self._runtime.button_handlers.setdefault(args[0], []).append(args[1])
            return _on
        if name == "onTick":
            return lambda args: self._runtime.tick_handlers.append(args[0])
        if name == "after":
            def _after(args):
                from .interpreter import to_number
                self._runtime.delayed.append([int(to_number(args[0])), args[1]])
            return _after
        raise JSError("unknown EV3 property '%s'" % name)
