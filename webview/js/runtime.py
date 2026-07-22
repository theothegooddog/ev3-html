"""Owns one JS interpreter instance for a page: sets up the global
environment (document/console/Math/EV3), runs <script> sources once at
page-load, and dispatches button/tick events afterwards.

Hardware-independent: EV3 button state is passed in as plain strings by
the caller (main.py maps pybricks Button enum values to names), so this
whole package — including this module — is desktop-testable.
"""

from . import interpreter as interp
from . import dom_bridge


class Runtime:
    def __init__(self, dom_root):
        self.dom_root = dom_root
        self.button_handlers = {}
        self.tick_handlers = []
        self.delayed = []
        self._dirty = True
        self._prev_buttons = set()

        self.interp = interp.Interpreter()
        env = self.interp.global_env
        env.declare("document", dom_bridge.Document(dom_root, self.mark_dirty))
        env.declare("EV3", dom_bridge.EV3Api(self))

    def mark_dirty(self):
        self._dirty = True

    def consume_dirty(self):
        dirty = self._dirty
        self._dirty = False
        return dirty

    def run_source(self, source):
        from .parser import parse
        self.interp.run(parse(source))

    def tick(self, pressed_names=()):
        for handler in list(self.tick_handlers):
            self.interp.call_function(handler, [])

        still_pending = []
        for entry in self.delayed:
            entry[0] -= 1
            if entry[0] <= 0:
                self.interp.call_function(entry[1], [])
            else:
                still_pending.append(entry)
        self.delayed = still_pending

        pressed = set(pressed_names)
        newly_pressed = pressed - self._prev_buttons
        self._prev_buttons = pressed
        for name in newly_pressed:
            for handler in self.button_handlers.get(name, []):
                self.interp.call_function(handler, [])

        return self.consume_dirty()
