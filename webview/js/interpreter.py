"""Tree-walking evaluator for the parser's AST.

Value mapping (deliberately simplified vs. real JS):
  number            -> Python float
  string            -> Python str
  boolean           -> Python bool
  null / undefined  -> Python None (not distinguished — a documented
                       simplification; most scripts don't care)
  array             -> Python list
  plain object      -> Python dict (string keys)
  JS function       -> JSFunction
  host function     -> any Python callable(args_list) -> value
  host object       -> HostObject subclass (document, console, Math, EV3,
                       Element, etc.) with custom get()/set()

`==`/`!=` are NOT coerced to `===`/`!==`'s counterparts — no coercion:
they compare like Python `==`. Numbers still coerce for arithmetic
(`"3" + 1` numeric-adds if both sides "look like" the intended op; see
`apply_binary`). Comparison/arithmetic edge cases won't always match a
real JS engine bit-for-bit — this targets "scripts behave the way you'd
expect", not full ECMAScript spec compliance.
"""

try:
    import math as _math
except ImportError:
    _math = None

# float("inf")/float("nan") need string-parsing support in float() that
# some MicroPython builds don't implement (same issue as str.isalnum() --
# see lexer.py). Deriving these via plain arithmetic sidesteps that.
INF = 1e308 * 10
NEG_INF = -INF
NAN = INF - INF


class JSError(Exception):
    pass


class _ReturnSignal(Exception):
    def __init__(self, value):
        self.value = value


class _BreakSignal(Exception):
    pass


class _ContinueSignal(Exception):
    pass


class HostObject:
    """Base for objects implemented in Python but reachable from JS
    (document, console, Math, EV3, DOM Elements, style/classList proxies)."""

    def get(self, name):
        raise JSError("no such property '%s'" % name)

    def set(self, name, value):
        raise JSError("cannot set property '%s'" % name)


class JSFunction:
    __slots__ = ("params", "body", "closure", "name")

    def __init__(self, params, body, closure, name=None):
        self.params = params
        self.body = body
        self.closure = closure
        self.name = name


class Environment:
    __slots__ = ("vars", "parent")

    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def declare(self, name, value):
        self.vars[name] = value

    def get(self, name):
        env = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        raise JSError("%s is not defined" % name)

    def assign(self, name, value):
        env = self
        while env is not None:
            if name in env.vars:
                env.vars[name] = value
                return
            env = env.parent
        raise JSError("%s is not defined (assign before declare?)" % name)


# -- value helpers ----------------------------------------------------

def is_truthy(v):
    if v is None or v is False:
        return False
    if v is True:
        return True
    if isinstance(v, float):
        return v == v and v != 0  # excludes NaN and 0
    if isinstance(v, str):
        return len(v) > 0
    return True


def to_number(v):
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, float):
        return v
    if v is None:
        return 0.0
    if isinstance(v, str):
        try:
            return float(v.strip()) if v.strip() else 0.0
        except ValueError:
            return NAN
    return NAN


def to_js_string(v):
    if v is None:
        return "undefined"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return str(v)
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return ",".join(to_js_string(x) for x in v)
    if isinstance(v, dict):
        return "[object Object]"
    if isinstance(v, JSFunction):
        return "function %s() { ... }" % (v.name or "")
    if isinstance(v, HostObject):
        return "[object]"
    if callable(v):
        return "function () { [native code] }"
    return str(v)


def js_typeof(v):
    if v is None:
        return "undefined"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, JSFunction) or callable(v):
        return "function"
    return "object"


def apply_binary(op, l, r):
    if op == "+":
        if isinstance(l, str) or isinstance(r, str):
            return to_js_string(l) + to_js_string(r)
        return to_number(l) + to_number(r)
    if op == "-":
        return to_number(l) - to_number(r)
    if op == "*":
        return to_number(l) * to_number(r)
    if op == "/":
        rn = to_number(r)
        if rn == 0:
            ln = to_number(l)
            return INF if ln > 0 else (NEG_INF if ln < 0 else NAN)
        return to_number(l) / rn
    if op == "%":
        rn = to_number(r)
        if rn == 0:
            return NAN
        ln = to_number(l)
        return ln - rn * float(int(ln / rn))
    if op == "==":
        return l == r
    if op == "!=":
        return l != r
    if op == "<":
        return _compare(l, r) < 0
    if op == ">":
        return _compare(l, r) > 0
    if op == "<=":
        return _compare(l, r) <= 0
    if op == ">=":
        return _compare(l, r) >= 0
    raise JSError("Unknown binary operator %r" % op)


def _compare(l, r):
    if isinstance(l, str) and isinstance(r, str):
        return -1 if l < r else (1 if l > r else 0)
    ln, rn = to_number(l), to_number(r)
    return -1 if ln < rn else (1 if ln > rn else 0)


class Interpreter:
    def __init__(self, global_env=None):
        self.global_env = global_env if global_env is not None else Environment()
        self.global_env.declare("console", Console())
        self.global_env.declare("Math", MathApi())

    def run(self, program_ast):
        self.exec_stmts(program_ast[1], self.global_env)

    # -- statements -----------------------------------------------------
    def exec_stmts(self, stmts, env):
        for s in stmts:
            self.exec_stmt(s, env)

    def exec_stmt(self, node, env):
        kind = node[0]

        if kind == "ExprStmt":
            self.eval_expr(node[1], env)
        elif kind == "VarDecl":
            for name, expr in node[2]:
                val = self.eval_expr(expr, env) if expr is not None else None
                env.declare(name, val)
        elif kind == "Block":
            self.exec_stmts(node[1], Environment(env))
        elif kind == "If":
            _, cond, then_s, else_s = node
            if is_truthy(self.eval_expr(cond, env)):
                self.exec_stmt(then_s, env)
            elif else_s is not None:
                self.exec_stmt(else_s, env)
        elif kind == "While":
            _, cond, body = node
            while is_truthy(self.eval_expr(cond, env)):
                try:
                    self.exec_stmt(body, env)
                except _BreakSignal:
                    break
                except _ContinueSignal:
                    continue
        elif kind == "For":
            self._exec_for(node, env)
        elif kind == "ForOf":
            self._exec_for_of(node, env)
        elif kind == "FuncDecl":
            _, name, params, body = node
            env.declare(name, JSFunction(params, body, env, name))
        elif kind == "Return":
            raise _ReturnSignal(self.eval_expr(node[1], env) if node[1] is not None else None)
        elif kind == "Break":
            raise _BreakSignal()
        elif kind == "Continue":
            raise _ContinueSignal()
        else:
            raise JSError("Unknown statement %r" % (kind,))

    def _exec_for(self, node, env):
        _, init, cond, update, body = node
        for_env = Environment(env)
        if init is not None:
            self.exec_stmt(init, for_env)
        while cond is None or is_truthy(self.eval_expr(cond, for_env)):
            try:
                self.exec_stmt(body, for_env)
            except _BreakSignal:
                break
            except _ContinueSignal:
                pass
            if update is not None:
                self.eval_expr(update, for_env)

    def _exec_for_of(self, node, env):
        _, name, iterable_expr, body = node
        iterable = self.eval_expr(iterable_expr, env)
        for item in list(iterable):
            loop_env = Environment(env)
            loop_env.declare(name, item)
            try:
                self.exec_stmt(body, loop_env)
            except _BreakSignal:
                break
            except _ContinueSignal:
                continue

    # -- expressions ------------------------------------------------------
    def eval_expr(self, node, env):
        kind = node[0]

        if kind == "Num" or kind == "Str" or kind == "Bool":
            return node[1]
        if kind == "Null":
            return None
        if kind == "Ident":
            return env.get(node[1])
        if kind == "Array":
            return [self.eval_expr(e, env) for e in node[1]]
        if kind == "Object":
            return {k: self.eval_expr(v, env) for k, v in node[1]}
        if kind == "Func":
            return JSFunction(node[1], node[2], env, None)
        if kind == "Unary":
            return self._eval_unary(node, env)
        if kind == "Update":
            return self._eval_update(node, env)
        if kind == "Binary":
            _, op, l, r = node
            return apply_binary(op, self.eval_expr(l, env), self.eval_expr(r, env))
        if kind == "Logical":
            _, op, l, r = node
            lv = self.eval_expr(l, env)
            if op == "&&":
                return self.eval_expr(r, env) if is_truthy(lv) else lv
            return lv if is_truthy(lv) else self.eval_expr(r, env)
        if kind == "Cond":
            _, test, cons, alt = node
            return self.eval_expr(cons, env) if is_truthy(self.eval_expr(test, env)) else self.eval_expr(alt, env)
        if kind == "Assign":
            return self._eval_assign(node, env)
        if kind == "Call":
            _, callee, args = node
            fn = self.eval_expr(callee, env)
            argvals = [self.eval_expr(a, env) for a in args]
            return self.call_function(fn, argvals)
        if kind == "Member":
            _, objexpr, name = node
            return self.get_member(self.eval_expr(objexpr, env), name)
        if kind == "Index":
            _, objexpr, iexpr = node
            obj = self.eval_expr(objexpr, env)
            idx = self.eval_expr(iexpr, env)
            return self.get_index(obj, idx)

        raise JSError("Unknown expression %r" % (kind,))

    def _eval_unary(self, node, env):
        _, op, expr = node
        val = self.eval_expr(expr, env)
        if op == "-":
            return -to_number(val)
        if op == "+":
            return to_number(val)
        if op == "!":
            return not is_truthy(val)
        if op == "typeof":
            return js_typeof(val)
        raise JSError("Unknown unary operator %r" % op)

    def _eval_update(self, node, env):
        _, op, target, prefix = node
        old = to_number(self._get_ref(target, env))
        new = old + 1 if op == "++" else old - 1
        self._set_ref(target, new, env)
        return new if prefix else old

    def _eval_assign(self, node, env):
        _, op, target, vexpr = node
        val = self.eval_expr(vexpr, env)
        if op != "=":
            cur = self._get_ref(target, env)
            val = apply_binary(op[:-1], cur, val)
        self._set_ref(target, val, env)
        return val

    def _get_ref(self, target, env):
        if target[0] == "Ident":
            return env.get(target[1])
        if target[0] == "Member":
            return self.get_member(self.eval_expr(target[1], env), target[2])
        if target[0] == "Index":
            obj = self.eval_expr(target[1], env)
            return self.get_index(obj, self.eval_expr(target[2], env))
        raise JSError("Invalid assignment target")

    def _set_ref(self, target, value, env):
        if target[0] == "Ident":
            env.assign(target[1], value)
        elif target[0] == "Member":
            self.set_member(self.eval_expr(target[1], env), target[2], value)
        elif target[0] == "Index":
            obj = self.eval_expr(target[1], env)
            self.set_index(obj, self.eval_expr(target[2], env), value)
        else:
            raise JSError("Invalid assignment target")

    # -- calling ------------------------------------------------------------
    def call_function(self, fn, argvals):
        if isinstance(fn, JSFunction):
            call_env = Environment(fn.closure)
            for i, pname in enumerate(fn.params):
                call_env.declare(pname, argvals[i] if i < len(argvals) else None)
            try:
                self.exec_stmts(fn.body, call_env)
            except _ReturnSignal as r:
                return r.value
            return None
        if callable(fn):
            return fn(argvals)
        raise JSError("value is not callable")

    # -- member/index access --------------------------------------------
    def get_member(self, obj, name):
        if isinstance(obj, HostObject):
            return obj.get(name)
        if isinstance(obj, dict):
            return obj.get(name)
        if isinstance(obj, list):
            return self._get_array_member(obj, name)
        if isinstance(obj, str):
            return self._get_string_member(obj, name)
        if obj is None:
            raise JSError("Cannot read properties of undefined (reading '%s')" % name)
        raise JSError("Cannot read property '%s'" % name)

    def set_member(self, obj, name, value):
        if isinstance(obj, HostObject):
            obj.set(name, value)
            return
        if isinstance(obj, dict):
            obj[name] = value
            return
        raise JSError("Cannot set property '%s'" % name)

    def get_index(self, obj, idx):
        if isinstance(obj, list):
            i = int(to_number(idx))
            return obj[i] if 0 <= i < len(obj) else None
        if isinstance(obj, dict):
            return obj.get(to_js_string(idx))
        if isinstance(obj, str):
            i = int(to_number(idx))
            return obj[i] if 0 <= i < len(obj) else None
        raise JSError("Cannot read index")

    def set_index(self, obj, idx, value):
        if isinstance(obj, list):
            i = int(to_number(idx))
            if i == len(obj):
                obj.append(value)
            elif 0 <= i < len(obj):
                obj[i] = value
            elif i > len(obj):
                obj.extend([None] * (i - len(obj)))
                obj.append(value)
            return
        if isinstance(obj, dict):
            obj[to_js_string(idx)] = value
            return
        raise JSError("Cannot set index")

    def _get_string_member(self, s, name):
        if name == "length":
            return float(len(s))
        if name == "toUpperCase":
            return lambda args: s.upper()
        if name == "toLowerCase":
            return lambda args: s.lower()
        if name == "trim":
            return lambda args: s.strip()
        if name == "split":
            return lambda args: s.split(args[0]) if args else [s]
        if name == "indexOf":
            return lambda args: float(s.find(args[0]))
        if name == "includes":
            return lambda args: args[0] in s
        if name == "charAt":
            return lambda args: (s[int(to_number(args[0]))] if args and 0 <= int(to_number(args[0])) < len(s) else "")
        if name == "slice":
            return lambda args: _string_slice(s, args)
        raise JSError("Unknown string property '%s'" % name)

    def _get_array_member(self, arr, name):
        if name == "length":
            return float(len(arr))
        if name == "push":
            def _push(args):
                arr.extend(args)
                return float(len(arr))
            return _push
        if name == "pop":
            return lambda args: (arr.pop() if arr else None)
        if name == "shift":
            return lambda args: (arr.pop(0) if arr else None)
        if name == "join":
            return lambda args: (args[0] if args else ",").join(to_js_string(x) for x in arr)
        if name == "indexOf":
            def _indexOf(args):
                target = args[0] if args else None
                for i, v in enumerate(arr):
                    if v == target:
                        return float(i)
                return -1.0
            return _indexOf
        if name == "includes":
            return lambda args: (args[0] if args else None) in arr
        if name == "reverse":
            def _reverse(args):
                arr.reverse()
                return arr
            return _reverse
        if name in ("forEach", "map", "filter", "find"):
            def _iter(args, _name=name):
                fn = args[0]
                out = []
                for i, v in enumerate(arr):
                    r = self.call_function(fn, [v, float(i)])
                    if _name == "map":
                        out.append(r)
                    elif _name == "filter" and is_truthy(r):
                        out.append(v)
                    elif _name == "find" and is_truthy(r):
                        return v
                if _name == "forEach":
                    return None
                if _name == "find":
                    return None
                return out
            return _iter
        raise JSError("Unknown array property '%s'" % name)


def _string_slice(s, args):
    start = int(to_number(args[0])) if len(args) > 0 else 0
    end = int(to_number(args[1])) if len(args) > 1 else len(s)
    return s[start:end]


class Console(HostObject):
    def get(self, name):
        if name == "log":
            return lambda args: print(" ".join(to_js_string(a) for a in args))
        raise JSError("unknown console property '%s'" % name)


class MathApi(HostObject):
    def get(self, name):
        if name == "PI":
            return _math.pi if _math else 3.14159265
        if name == "floor":
            return lambda args: float(_ipart_floor(to_number(args[0])))
        if name == "ceil":
            return lambda args: float(_ipart_ceil(to_number(args[0])))
        if name == "round":
            return lambda args: float(_ipart_floor(to_number(args[0]) + 0.5))
        if name == "abs":
            return lambda args: abs(to_number(args[0]))
        if name == "max":
            return lambda args: max([to_number(a) for a in args]) if args else NEG_INF
        if name == "min":
            return lambda args: min([to_number(a) for a in args]) if args else INF
        if name == "sqrt":
            return lambda args: (_math.sqrt(to_number(args[0])) if _math else to_number(args[0]) ** 0.5)
        if name == "random":
            return lambda args: _random_float()
        raise JSError("unknown Math property '%s'" % name)


def _ipart_floor(x):
    i = int(x)
    return i if x >= 0 or i == x else i - 1


def _ipart_ceil(x):
    i = int(x)
    return i if x <= 0 or i == x else i + 1


try:
    import urandom as _random_mod
except ImportError:
    try:
        import random as _random_mod
    except ImportError:
        _random_mod = None


def _random_float():
    if _random_mod is not None and hasattr(_random_mod, "random"):
        return _random_mod.random()
    return 0.5
