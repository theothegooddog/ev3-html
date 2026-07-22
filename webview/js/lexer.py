"""Tokenizer for the small JS subset. No `re` dependency.

Character classification is done with plain `in`-membership checks against
fixed digit/letter strings rather than str.isdigit()/isalpha()/isalnum() --
pybricks-MicroPython's str type doesn't implement all three (isalnum is
missing at least), so this avoids relying on any of them.
"""

_DIGITS = "0123456789"
_LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _is_digit(c):
    return c in _DIGITS


def _is_letter(c):
    return c in _LETTERS


def _is_ident_char(c):
    return c in _LETTERS or c in _DIGITS or c == "_" or c == "$"


KEYWORDS = set([
    "var", "let", "const", "function", "return", "if", "else", "while",
    "for", "of", "true", "false", "null", "undefined", "break", "continue",
    "typeof",
])

# Longest-match-first.
_PUNCT3 = ["===", "!=="]
_PUNCT2 = ["=>", "==", "!=", "<=", ">=", "&&", "||", "++", "--",
           "+=", "-=", "*=", "/=", "%="]
_PUNCT1 = list("+-*/%=<>!(){}[],;.:?")


class Token:
    __slots__ = ("type", "value")

    def __init__(self, type_, value):
        self.type = type_
        self.value = value

    def __repr__(self):
        return "Token(%s, %r)" % (self.type, self.value)


class JSSyntaxError(Exception):
    pass


def tokenize(src):
    tokens = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]

        if c in " \t\r\n":
            i += 1
            continue

        if c == "/" and i + 1 < n and src[i + 1] == "/":
            end = src.find("\n", i)
            i = end if end != -1 else n
            continue

        if c == "/" and i + 1 < n and src[i + 1] == "*":
            end = src.find("*/", i + 2)
            i = end + 2 if end != -1 else n
            continue

        if _is_digit(c) or (c == "." and i + 1 < n and _is_digit(src[i + 1])):
            start = i
            seen_dot = False
            while i < n and (_is_digit(src[i]) or (src[i] == "." and not seen_dot)):
                if src[i] == ".":
                    seen_dot = True
                i += 1
            tokens.append(Token("num", float(src[start:i])))
            continue

        if c in ("'", '"'):
            quote = c
            i += 1
            start = i
            out = []
            while i < n and src[i] != quote:
                if src[i] == "\\" and i + 1 < n:
                    esc = src[i + 1]
                    out.append({"n": "\n", "t": "\t", "\\": "\\", "'": "'", '"': '"'}.get(esc, esc))
                    i += 2
                else:
                    out.append(src[i])
                    i += 1
            i += 1  # closing quote
            tokens.append(Token("str", "".join(out)))
            continue

        if _is_letter(c) or c == "_" or c == "$":
            start = i
            while i < n and _is_ident_char(src[i]):
                i += 1
            word = src[start:i]
            if word in KEYWORDS:
                tokens.append(Token("keyword", word))
            else:
                tokens.append(Token("ident", word))
            continue

        matched = False
        for p in _PUNCT3:
            if src[i:i + 3] == p:
                tokens.append(Token("punct", p))
                i += 3
                matched = True
                break
        if matched:
            continue
        for p in _PUNCT2:
            if src[i:i + 2] == p:
                tokens.append(Token("punct", p))
                i += 2
                matched = True
                break
        if matched:
            continue
        if c in _PUNCT1:
            tokens.append(Token("punct", c))
            i += 1
            continue

        raise JSSyntaxError("Unexpected character %r at offset %d" % (c, i))

    tokens.append(Token("eof", None))
    return tokens
