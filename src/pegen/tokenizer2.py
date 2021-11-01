import token
import tokenize

from pypy.interpreter.pyparser.pytoken import python_opmap as exact_token_types

Mark = int


def shorttok(tok):
    return "%-25.25s" % ("%s.%s: %s:%r" % (tok.lineno, tok.column, token.tok_name[tok.token_type], tok.value))


class Tokenizer:
    """Caching wrapper for the tokenize module.

    This is pretty tied to Python's syntax.
    """

    def __init__(self, tokengen, path="", verbose=False):
        self._tokengen = iter(tokengen)
        self._tokens = []
        self._index = 0
        self._verbose = verbose
        self._lines = {}
        self._path = path
        if verbose:
            self.report(False, False)

    def getnext(self):
        """Return the next token and updates the index."""
        cached = not self._index == len(self._tokens)
        tok = self.peek()
        self._index += 1
        if self._verbose:
            self.report(cached, False)
        return tok

    def peek(self):
        """Return the next token *without* updating the index."""
        while self._index == len(self._tokens):
            tok = next(self._tokengen)
            if tok.token_type in (tokenize.NL, tokenize.COMMENT):
                continue
            if tok.token_type == token.ERRORTOKEN and tok.value.isspace():
                continue
            if (
                tok.token_type == token.NEWLINE
                and self._tokens
                and self._tokens[-1].token_type == token.NEWLINE
            ):
                continue
            self._tokens.append(tok)
            if not self._path:
                self._lines[tok.lineno] = tok.line
        return self._tokens[self._index]

    def diagnose(self):
        if not self._tokens:
            self.getnext()
        return self._tokens[-1]

    def get_last_non_whitespace_token(self):
        for tok in reversed(self._tokens[: self._index]):
            if tok.token_type != tokenize.ENDMARKER and (
                tok.token_type < tokenize.NEWLINE or tok.token_type > tokenize.DEDENT
            ):
                break
        return tok

    def get_lines(self, line_numbers):
        """Retrieve source lines corresponding to line numbers."""
        if self._lines:
            lines = self._lines
        else:
            n = len(line_numbers)
            lines = {}
            count = 0
            seen = 0
            with open(self._path) as f:
                for l in f:
                    count += 1
                    if count in line_numbers:
                        seen += 1
                        lines[count] = l
                        if seen == n:
                            break

        return [lines[n] for n in line_numbers]

    def mark(self):
        return self._index

    def reset(self, index):
        if index == self._index:
            return
        assert 0 <= index <= len(self._tokens), (index, len(self._tokens))
        old_index = self._index
        self._index = index
        if self._verbose:
            self.report(True, index < old_index)

    def report(self, cached, back):
        if back:
            fill = "-" * self._index + "-"
        elif cached:
            fill = "-" * self._index + ">"
        else:
            fill = "-" * self._index + "*"
        if self._index == 0:
            print("{fill} (Bof)")
        else:
            tok = self._tokens[self._index - 1]
            print("{fill} {shorttok(tok)}")
