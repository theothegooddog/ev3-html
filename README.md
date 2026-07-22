# EV3 MicroPython HTML/CSS/JS renderer

Parses a small HTML document, CSS stylesheet, and JavaScript into a live
page rendered on the LEGO EV3's 178x128 monochrome LCD, using
[pybricks](https://pybricks.com/)' `EV3Brick().screen`. Up/Down scrolls,
Center exits, Left/Right are available to page scripts (see below).

## Layout

```
index.html, style.css      -- the page you're viewing
main.py                    -- on-brick entry point (reads the files above,
                              runs scripts, renders to ev3.screen, handles
                              scrolling + button dispatch)
webview/
  html_parser.py           -- hand-rolled HTML tokenizer -> DOM tree
  css_parser.py             -- hand-rolled CSS tokenizer -> selector/decl rules
  style.py                  -- selector matching + cascade -> computed style
  layout.py                 -- DOM + styles -> block/inline layout -> draw commands
  fonts.py                  -- font metrics + word wrapping
  render.py                 -- draw commands -> screen calls (pybricks or mock)
  js/
    lexer.py                -- JS tokenizer
    parser.py                -- recursive-descent parser -> AST (tuples)
    interpreter.py            -- tree-walking evaluator + value/coercion rules
    dom_bridge.py              -- document/Element/style/classList/EV3 host objects
    runtime.py                  -- wires interpreter + bridge, dispatches button/tick events
tests/
  mock_screen.py             -- Pillow-backed stand-in for ev3.screen (desktop only)
  preview.py                  -- renders index.html/style.css(+js) to tests/preview.png
  test_js.py                   -- unit tests for the JS lexer/parser/interpreter/bridge
```

Nothing outside `main.py` and `tests/` imports pybricks directly except
`render.EV3ScreenAdapter`, so the parser/style/layout/JS stack is plain,
portable Python with no `re`/stdlib-heavy dependencies — it runs unmodified
under both pybricks-MicroPython (on the brick) and desktop CPython (for
`tests/preview.py` and `tests/test_js.py`).

## Running

- **On the brick**: open this folder in VS Code with the LEGO EV3
  MicroPython extension and use "Download and Run" as usual — `main.py` is
  the entry point already wired up in `.vscode/launch.json`.
- **On your desktop, without hardware**: `python3 tests/preview.py` renders
  the current `index.html`/`style.css` (running any `<script>` once, as at
  page-load) to `tests/preview.png` (requires `pip install pillow`).
  `python3 tests/test_js.py` runs the JS interpreter's unit tests. Useful
  for iterating on markup/CSS/JS before deploying.

## JavaScript

`<script>` tags (inline or `src="file.js"`) run once at page load against
a small, hand-written JS interpreter — not a real JS engine, a deliberately
scoped subset. Supported: `var`/`let`/`const`, `if`/`else`, `while`, `for`,
`for...of` (over arrays), functions/closures, arrow functions, arrays,
object literals, `typeof`, and the usual operators. **Not** supported (by
design): classes/prototypes, `this`, generators/async, try/catch, switch,
destructuring, template literals, regex.

The page-specific API, all implemented in `webview/js/dom_bridge.py`:

- `document.getElementById(id)` / `.querySelector(sel)` / `.querySelectorAll(sel)`
- `element.textContent` (get/set), `.id`, `.tagName`, `.children`,
  `.getAttribute()`/`.setAttribute()`
- `element.style.color` / `.backgroundColor` / `.display` / `.fontWeight` /
  `.fontStyle` / `.textAlign` / `.border` / `.width` / `.height` /
  `.margin` / `.padding` (get/set, camelCase like the real DOM)
- `element.classList.add()` / `.remove()` / `.toggle()` / `.contains()`
- `console.log(...)`, `Math.floor/ceil/round/abs/max/min/sqrt/random/PI`
- `EV3.onButton("left" | "right", fn)` — edge-triggered (fires once per
  press, not once per 100ms poll)
- `EV3.onTick(fn)` — called every ~100ms main-loop iteration
- `EV3.after(ticks, fn)` — one-shot delayed call, `ticks` × ~100ms

**Up/Down/Center are reserved** by the viewer itself for page scrolling and
exit, so `EV3.onButton` only ever fires for `"left"`/`"right"` — a single
device with 5 buttons doesn't have enough input surface to give scripts
free rein over all of them without losing basic page navigation. Any DOM
mutation (`textContent`, `style`, `classList`, `setAttribute`) triggers a
re-layout + redraw on the next tick.

See `index.html`'s counter for a working example.

## What's supported

- Tags: `html`, `head`/`title`/`style`/`script` (skipped from rendering),
  `body`, `div`, `p`, `h1`-`h6`, `span`, `a`, `b`/`strong`, `i`/`em`, `br`,
  `hr`, `ul`/`ol`/`li`, `img` (rendered as an `[alt text]` placeholder — no
  image decoding), and `vr` — a custom element, **not real HTML**: a
  vertical-rule divider mirroring `<hr>`, for toolbar-style layouts
  (`<h3>Title</h3> <vr> <p>status</p>`) since HTML has no built-in
  equivalent. It's inline (flows within text, sized to its line's height),
  not a full-height column divider.
- Tolerant parsing: mismatched/unclosed tags, comments, `<!DOCTYPE>`,
  HTML entities (named + numeric/hex).
- CSS: tag/`.class`/`#id` selectors with descendant combinators (`div p`),
  comma-separated selector lists, normal cascade/specificity rules, inline
  `style="..."` attributes, and `<style>` blocks in `<head>` (merged with
  the external stylesheet).
- Properties: `display` (`block`/`inline`/`none`), `color`,
  `background-color`, `font-weight: bold`, `font-style: italic` (tracked but
  not visually distinguished — see below), `text-align`, `margin`/`padding`
  (shorthand + longhand, px only), `width`/`height` (px only), `border`
  (on/off box outline only), `font-size` — keywords (`xx-small` through
  `xx-large`) or px numbers, inherited like real CSS. `h1`-`h6` now default
  to distinct sizes (`h1` largest down to `h6` smallest) the way a browser's
  UA stylesheet does.

## Known limitations

- **Monochrome**: the LCD is 1-bit, so every CSS color collapses to black or
  a small set of recognized "light" keywords maps to white — there's no
  actual color rendering.
- **No italics**: pybricks' default screen font has no italic variant, so
  `font-style: italic` is parsed but rendered as normal text. Bold is faked
  by drawing text twice, offset by 1px.
- **Font metrics are estimated** (`webview/fonts.py`): pybricks doesn't
  expose glyph metrics to MicroPython, so `BASE_CHAR_WIDTH`/
  `BASE_LINE_HEIGHT` are best-guess constants for "normal" (`font-size:
  medium`) text, and other sizes scale proportionally from those two. If
  text looks cramped or too sparse on real hardware, tune those two
  numbers. Actually changing rendered text *size* on the brick (not just
  layout math) goes through pybricks' `Font`/`Screen.set_font()` in
  `render.EV3ScreenAdapter` — an API I can't verify without hardware, so
  it's wrapped defensively: if it doesn't work as expected, text still
  renders (just always at the screen's default size) rather than crashing.
  Report back what you see and I'll adjust.
- **No percentage/em units, no flex/grid/position** — only `px` and
  keyword values are understood; anything else falls back to a sane
  default rather than erroring.
- Mixed inline+block siblings from malformed markup are flowed as a single
  anonymous text run rather than fully reconstructing correct block
  boundaries — good enough to avoid ever silently dropping content, not a
  full HTML5 tree-construction algorithm.
- **JS `null`/`undefined` are unified** into Python's `None` — scripts that
  rely on `x === undefined` vs `x === null` distinguishing won't see a
  difference. `==`/`!=` are plain equality (no JS-style type coercion);
  `+`/`-`/`*`/`/`/`%`/comparisons do coerce operands to number/string as
  usual. No `this` binding for JS-defined functions/methods, no
  classes/prototypes, no exceptions (`try`/`catch`) — a thrown `JSError`
  from a bad script currently just stops that script's execution.
