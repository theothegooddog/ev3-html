"""Recursive-descent parser for the small JS subset.

AST nodes are plain tuples, tag first:

Statements:
  ("Program", [stmt, ...])
  ("VarDecl", kind, [(name, expr_or_None), ...])
  ("ExprStmt", expr)
  ("Block", [stmt, ...])
  ("If", cond, thenStmt, elseStmt_or_None)
  ("While", cond, body)
  ("For", initStmt_or_None, cond_or_None, updateExpr_or_None, body)
  ("ForOf", name, iterableExpr, body)
  ("FuncDecl", name, [param, ...], [stmt, ...])
  ("Return", expr_or_None)
  ("Break",)
  ("Continue",)

Expressions:
  ("Num", float) | ("Str", str) | ("Bool", bool) | ("Null",)
  ("Ident", name)
  ("Array", [expr, ...])
  ("Object", [(key_str, expr), ...])
  ("Func", [param, ...], [stmt, ...])
  ("Unary", op, expr)
  ("Update", op, targetExpr, is_prefix)
  ("Binary", op, left, right)
  ("Logical", op, left, right)
  ("Assign", op, targetExpr, valueExpr)
  ("Cond", test, cons, alt)
  ("Call", calleeExpr, [argExpr, ...])
  ("Member", objExpr, name)
  ("Index", objExpr, indexExpr)

Not supported (by design, to keep this a small hand-written subset):
classes/prototypes, `this`, generators/async, destructuring, template
literals, spread/rest, regex literals, try/catch, switch, for-in, var
hoisting/function-scoping quirks (var/let/const all behave like
block-scoped let here).
"""

from .lexer import tokenize, JSSyntaxError

_ASSIGN_OPS = ("=", "+=", "-=", "*=", "/=", "%=")


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    # -- token helpers --------------------------------------------------
    def peek(self, offset=0):
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return self.tokens[-1]

    def next(self):
        tok = self.tokens[self.pos]
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return tok

    def check_punct(self, value):
        tok = self.peek()
        return tok.type == "punct" and tok.value == value

    def check_keyword(self, value):
        tok = self.peek()
        return tok.type == "keyword" and tok.value == value

    def match_punct(self, value):
        if self.check_punct(value):
            self.next()
            return True
        return False

    def match_keyword(self, value):
        if self.check_keyword(value):
            self.next()
            return True
        return False

    def expect_punct(self, value):
        if not self.match_punct(value):
            raise JSSyntaxError("Expected %r but got %r" % (value, self.peek()))

    def expect_ident(self):
        tok = self.peek()
        if tok.type != "ident":
            raise JSSyntaxError("Expected identifier but got %r" % (tok,))
        return self.next().value

    # -- entry point ------------------------------------------------------
    def parse_program(self):
        stmts = []
        while self.peek().type != "eof":
            stmts.append(self.parse_statement())
        return ("Program", stmts)

    # -- statements -------------------------------------------------------
    def parse_statement(self):
        if self.check_keyword("var") or self.check_keyword("let") or self.check_keyword("const"):
            stmt = self.parse_var_decl()
            self.match_punct(";")
            return stmt
        if self.check_keyword("function"):
            return self.parse_func_decl()
        if self.check_punct("{"):
            return self.parse_block()
        if self.check_keyword("if"):
            return self.parse_if()
        if self.check_keyword("while"):
            return self.parse_while()
        if self.check_keyword("for"):
            return self.parse_for()
        if self.check_keyword("return"):
            self.next()
            if self.check_punct(";") or self.check_punct("}"):
                self.match_punct(";")
                return ("Return", None)
            expr = self.parse_expression()
            self.match_punct(";")
            return ("Return", expr)
        if self.check_keyword("break"):
            self.next()
            self.match_punct(";")
            return ("Break",)
        if self.check_keyword("continue"):
            self.next()
            self.match_punct(";")
            return ("Continue",)
        if self.match_punct(";"):
            return ("Block", [])
        expr = self.parse_expression()
        self.match_punct(";")
        return ("ExprStmt", expr)

    def parse_var_decl(self):
        kind = self.next().value  # var/let/const
        decls = []
        while True:
            name = self.expect_ident()
            init = None
            if self.match_punct("="):
                init = self.parse_assignment()
            decls.append((name, init))
            if not self.match_punct(","):
                break
        return ("VarDecl", kind, decls)

    def parse_func_decl(self):
        self.next()  # 'function'
        name = self.expect_ident()
        params = self.parse_param_list()
        body = self.parse_block()
        return ("FuncDecl", name, params, body[1])

    def parse_param_list(self):
        self.expect_punct("(")
        params = []
        if not self.check_punct(")"):
            while True:
                params.append(self.expect_ident())
                if not self.match_punct(","):
                    break
        self.expect_punct(")")
        return params

    def parse_block(self):
        self.expect_punct("{")
        stmts = []
        while not self.check_punct("}") and self.peek().type != "eof":
            stmts.append(self.parse_statement())
        self.expect_punct("}")
        return ("Block", stmts)

    def parse_if(self):
        self.next()
        self.expect_punct("(")
        cond = self.parse_expression()
        self.expect_punct(")")
        then_s = self.parse_statement()
        else_s = None
        if self.match_keyword("else"):
            else_s = self.parse_statement()
        return ("If", cond, then_s, else_s)

    def parse_while(self):
        self.next()
        self.expect_punct("(")
        cond = self.parse_expression()
        self.expect_punct(")")
        body = self.parse_statement()
        return ("While", cond, body)

    def parse_for(self):
        self.next()
        self.expect_punct("(")

        if (self.check_keyword("var") or self.check_keyword("let") or self.check_keyword("const")) \
                and self.peek(1).type == "ident" and self.peek(2).type == "keyword" and self.peek(2).value == "of":
            self.next()  # kind
            name = self.expect_ident()
            self.next()  # 'of'
            iterable = self.parse_expression()
            self.expect_punct(")")
            body = self.parse_statement()
            return ("ForOf", name, iterable, body)

        init = None
        if not self.check_punct(";"):
            if self.check_keyword("var") or self.check_keyword("let") or self.check_keyword("const"):
                init = self.parse_var_decl()
            else:
                init = ("ExprStmt", self.parse_expression())
        self.expect_punct(";")

        cond = None
        if not self.check_punct(";"):
            cond = self.parse_expression()
        self.expect_punct(";")

        update = None
        if not self.check_punct(")"):
            update = self.parse_expression()
        self.expect_punct(")")

        body = self.parse_statement()
        return ("For", init, cond, update, body)

    # -- expressions (precedence climbing) --------------------------------
    def parse_expression(self):
        return self.parse_assignment()

    def parse_assignment(self):
        left = self.parse_conditional()
        tok = self.peek()
        if tok.type == "punct" and tok.value in _ASSIGN_OPS:
            op = self.next().value
            right = self.parse_assignment()
            return ("Assign", op, left, right)
        return left

    def parse_conditional(self):
        test = self.parse_or()
        if self.match_punct("?"):
            cons = self.parse_assignment()
            self.expect_punct(":")
            alt = self.parse_assignment()
            return ("Cond", test, cons, alt)
        return test

    def parse_or(self):
        left = self.parse_and()
        while self.match_punct("||"):
            right = self.parse_and()
            left = ("Logical", "||", left, right)
        return left

    def parse_and(self):
        left = self.parse_equality()
        while self.match_punct("&&"):
            right = self.parse_equality()
            left = ("Logical", "&&", left, right)
        return left

    def parse_equality(self):
        left = self.parse_relational()
        while True:
            tok = self.peek()
            if tok.type == "punct" and tok.value in ("==", "!=", "===", "!=="):
                op = self.next().value
                right = self.parse_relational()
                left = ("Binary", "==" if op == "===" else ("!=" if op == "!==" else op), left, right)
            else:
                break
        return left

    def parse_relational(self):
        left = self.parse_additive()
        while True:
            tok = self.peek()
            if tok.type == "punct" and tok.value in ("<", ">", "<=", ">="):
                op = self.next().value
                right = self.parse_additive()
                left = ("Binary", op, left, right)
            else:
                break
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while True:
            tok = self.peek()
            if tok.type == "punct" and tok.value in ("+", "-"):
                op = self.next().value
                right = self.parse_multiplicative()
                left = ("Binary", op, left, right)
            else:
                break
        return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while True:
            tok = self.peek()
            if tok.type == "punct" and tok.value in ("*", "/", "%"):
                op = self.next().value
                right = self.parse_unary()
                left = ("Binary", op, left, right)
            else:
                break
        return left

    def parse_unary(self):
        tok = self.peek()
        if tok.type == "punct" and tok.value in ("-", "+", "!"):
            op = self.next().value
            expr = self.parse_unary()
            return ("Unary", op, expr)
        if tok.type == "keyword" and tok.value == "typeof":
            self.next()
            expr = self.parse_unary()
            return ("Unary", "typeof", expr)
        if tok.type == "punct" and tok.value in ("++", "--"):
            op = self.next().value
            expr = self.parse_unary()
            return ("Update", op, expr, True)
        return self.parse_postfix()

    def parse_postfix(self):
        expr = self.parse_call_member()
        tok = self.peek()
        if tok.type == "punct" and tok.value in ("++", "--"):
            op = self.next().value
            return ("Update", op, expr, False)
        return expr

    def parse_call_member(self):
        expr = self.parse_primary()
        while True:
            if self.match_punct("."):
                name = self.expect_ident()
                expr = ("Member", expr, name)
            elif self.match_punct("["):
                idx = self.parse_expression()
                self.expect_punct("]")
                expr = ("Index", expr, idx)
            elif self.check_punct("("):
                args = self.parse_arg_list()
                expr = ("Call", expr, args)
            else:
                break
        return expr

    def parse_arg_list(self):
        self.expect_punct("(")
        args = []
        if not self.check_punct(")"):
            while True:
                args.append(self.parse_assignment())
                if not self.match_punct(","):
                    break
        self.expect_punct(")")
        return args

    def parse_primary(self):
        tok = self.peek()

        if tok.type == "num":
            self.next()
            return ("Num", tok.value)
        if tok.type == "str":
            self.next()
            return ("Str", tok.value)
        if tok.type == "keyword" and tok.value in ("true", "false"):
            self.next()
            return ("Bool", tok.value == "true")
        if tok.type == "keyword" and tok.value in ("null", "undefined"):
            self.next()
            return ("Null",)
        if tok.type == "keyword" and tok.value == "function":
            self.next()
            if self.peek().type == "ident":
                self.next()  # optional name, ignored (no named-expr recursion support)
            params = self.parse_param_list()
            body = self.parse_block()
            return ("Func", params, body[1])

        if tok.type == "ident" and self.peek(1).type == "punct" and self.peek(1).value == "=>":
            name = self.next().value
            self.next()  # '=>'
            return self.parse_arrow_body([name])

        if tok.type == "ident":
            self.next()
            return ("Ident", tok.value)

        if self.match_punct("("):
            save = self.pos
            params = self._try_parse_arrow_params()
            if params is not None:
                return self.parse_arrow_body(params)
            self.pos = save
            expr = self.parse_expression()
            self.expect_punct(")")
            return expr

        if self.match_punct("["):
            elems = []
            if not self.check_punct("]"):
                while True:
                    elems.append(self.parse_assignment())
                    if not self.match_punct(","):
                        break
            self.expect_punct("]")
            return ("Array", elems)

        if self.match_punct("{"):
            props = []
            if not self.check_punct("}"):
                while True:
                    key = self._parse_object_key()
                    if self.match_punct(":"):
                        value = self.parse_assignment()
                    else:
                        value = ("Ident", key)
                    props.append((key, value))
                    if not self.match_punct(","):
                        break
            self.expect_punct("}")
            return ("Object", props)

        raise JSSyntaxError("Unexpected token %r" % (tok,))

    def _parse_object_key(self):
        tok = self.peek()
        if tok.type == "str":
            self.next()
            return tok.value
        if tok.type in ("ident", "keyword"):
            self.next()
            return tok.value
        raise JSSyntaxError("Expected object key, got %r" % (tok,))

    def _try_parse_arrow_params(self):
        save = self.pos
        params = []
        if not self.check_punct(")"):
            while True:
                if self.peek().type != "ident":
                    self.pos = save
                    return None
                params.append(self.next().value)
                if self.match_punct(","):
                    continue
                break
        if not self.match_punct(")"):
            self.pos = save
            return None
        if not self.match_punct("=>"):
            self.pos = save
            return None
        return params

    def parse_arrow_body(self, params):
        if self.check_punct("{"):
            body = self.parse_block()
            return ("Func", params, body[1])
        expr = self.parse_assignment()
        return ("Func", params, [("Return", expr)])


def parse(source):
    return Parser(tokenize(source)).parse_program()
