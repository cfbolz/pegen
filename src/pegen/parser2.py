# rpython code (python2!)
import argparse
import sys
import time
import traceback
from abc import abstractmethod

from pegen.tokenizer2 import Mark, Tokenizer, exact_token_types

from pypy.interpreter.pyparser import pytokenizer as tokenize, pytoken

globals().update(pytoken.python_tokens)


def logger(method):
    """For non-memoized functions that we want to be logged.

    (In practice this is only non-leader left-recursive functions.)
    """
    method_name = method.__name__

    def logger_wrapper(self, *args):
        if not self._verbose:
            return method(self, *args)
        argsr = ",".join(repr(arg) for arg in args)
        fill = "  " * self._level
        print "{fill}{method_name}({argsr}) .... (looking at {self.showpeek()})"
        self._level += 1
        tree = method(self, *args)
        self._level -= 1
        print "{fill}... {method_name}({argsr}) --> {tree!s:.200}"
        return tree

    logger_wrapper.__wrapped__ = method  # type: ignore
    return logger_wrapper


def memoize(method):
    """Memoize a symbol method."""
    method_name = method.__name__

    def memoize_wrapper(self, *args):
        mark = self._mark()
        key = mark, method_name, args
        # Fast path: cache hit, and not verbose.
        if key in self._cache and not self._verbose:
            tree, endmark = self._cache[key]
            self._reset(endmark)
            return tree
        # Slow path: no cache hit, or verbose.
        verbose = self._verbose
        argsr = ",".join(repr(arg) for arg in args)
        fill = "  " * self._level
        if key not in self._cache:
            if verbose:
                print "{fill}{method_name}({argsr}) ... (looking at {self.showpeek()})"
            self._level += 1
            tree = method(self, *args)
            self._level -= 1
            if verbose:
                print "{fill}... {method_name}({argsr}) -> {tree!s:.200}"
            endmark = self._mark()
            self._cache[key] = tree, endmark
        else:
            tree, endmark = self._cache[key]
            if verbose:
                print "{fill}{method_name}({argsr}) -> {tree!s:.200}"
            self._reset(endmark)
        return tree

    memoize_wrapper.__wrapped__ = method  # type: ignore
    return memoize_wrapper


def memoize_left_rec(method):
    """Memoize a left-recursive symbol method."""
    method_name = method.__name__

    def memoize_left_rec_wrapper(self):
        mark = self._mark()
        key = mark, method_name, ()
        # Fast path: cache hit, and not verbose.
        if key in self._cache and not self._verbose:
            tree, endmark = self._cache[key]
            self._reset(endmark)
            return tree
        # Slow path: no cache hit, or verbose.
        verbose = self._verbose
        fill = "  " * self._level
        if key not in self._cache:
            if verbose:
                print "{fill}{method_name} ... (looking at {self.showpeek()})"
            self._level += 1

            # For left-recursive rules we manipulate the cache and
            # loop until the rule shows no progress, then pick the
            # previous result.  For an explanation why this works, see
            # https://github.com/PhilippeSigaud/Pegged/wiki/Left-Recursion
            # (But we use the memoization cache instead of a static
            # variable; perhaps this is similar to a paper by Warth et al.
            # (http://web.cs.ucla.edu/~todd/research/pub.php?id=pepm08).

            # Prime the cache with a failure.
            self._cache[key] = None, mark
            lastresult, lastmark = None, mark
            depth = 0
            if verbose:
                print "{fill}Recursive {method_name} at {mark} depth {depth}"

            while True:
                self._reset(mark)
                self.in_recursive_rule += 1
                try:
                    result = method(self)
                finally:
                    self.in_recursive_rule -= 1
                endmark = self._mark()
                depth += 1
                if verbose:
                    print "{fill}Recursive {method_name} at {mark} depth {depth}: {result!s:.200} to {endmark}"
                if not result:
                    if verbose:
                        print "{fill}Fail with {lastresult!s:.200} to {lastmark}"
                    break
                if endmark <= lastmark:
                    if verbose:
                        print "{fill}Bailing with {lastresult!s:.200} to {lastmark}"
                    break
                self._cache[key] = lastresult, lastmark = result, endmark

            self._reset(lastmark)
            tree = lastresult

            self._level -= 1
            if verbose:
                print "{fill}{method_name}() -> {tree!s:.200} [cached]"
            if tree:
                endmark = self._mark()
            else:
                endmark = mark
                self._reset(endmark)
            self._cache[key] = tree, endmark
        else:
            tree, endmark = self._cache[key]
            if verbose:
                print "{fill}{method_name}() -> {tree!s:.200} [fresh]"
            if tree:
                self._reset(endmark)
        return tree

    memoize_left_rec_wrapper.__wrapped__ = method  # type: ignore
    return memoize_left_rec_wrapper


class Parser:
    """Parsing base class."""

    # KEYWORDS: ClassVar[Tuple[str, ...]]

    # SOFT_KEYWORDS: ClassVar[Tuple[str, ...]]

    def __init__(self, tokenizer, verbose=False):
        self._tokenizer = tokenizer
        self._verbose = verbose
        self._level = 0
        self._cache = {}
        # Integer tracking wether we are in a left recursive rule or not. Can be useful
        # for error reporting.
        self.in_recursive_rule = 0
        # Pass through common tokenizer methods.
        self._mark = self._tokenizer.mark
        self._reset = self._tokenizer.reset

    def start(self):
        pass

    def showpeek(self):
        tok = self._tokenizer.peek()
        return "{tok.start[0]}.{tok.start[1]}: {token.tok_name[tok.token_type]}:{tok.value!r}"

    @memoize
    def name(self):
        tok = self._tokenizer.peek()
        if tok.token_type == NAME and tok.value not in self.KEYWORDS:
            return self._tokenizer.getnext()
        return None

    @memoize
    def number(self):
        tok = self._tokenizer.peek()
        if tok.token_type == NUMBER:
            return self._tokenizer.getnext()
        return None

    @memoize
    def string(self):
        tok = self._tokenizer.peek()
        if tok.token_type == STRING:
            return self._tokenizer.getnext()
        return None

    @memoize
    def op(self):
        tok = self._tokenizer.peek()
        if tok.token_type == OP:
            return self._tokenizer.getnext()
        return None

    @memoize
    def type_comment(self):
        tok = self._tokenizer.peek()
        if tok.token_type == TYPE_COMMENT:
            return self._tokenizer.getnext()
        return None

    @memoize
    def soft_keyword(self):
        tok = self._tokenizer.peek()
        if tok.token_type == NAME and tok.value in self.SOFT_KEYWORDS:
            return self._tokenizer.getnext()
        return None

    @memoize
    def expect(self, type):
        tok = self._tokenizer.peek()
        if tok.value == type:
            return self._tokenizer.getnext()
        if type in exact_token_types:
            if tok.token_type == exact_token_types[type]:
                return self._tokenizer.getnext()
        if type in pytoken.python_tokens:
            if tok.token_type == pytoken.python_tokens[type]:
                return self._tokenizer.getnext()
        if tok.token_type == OP and tok.value == type:
            return self._tokenizer.getnext()
        return None

    def expect_forced(self, res, expectation):
        if res is None:
            raise self.make_syntax_error("expected {expectation}")
        return res

    def positive_lookahead(self, func, *args):
        mark = self._mark()
        ok = func(*args)
        self._reset(mark)
        return ok

    def negative_lookahead(self, func, *args):
        mark = self._mark()
        ok = func(*args)
        self._reset(mark)
        return not ok

    def make_syntax_error(self, message, filename):
        tok = self._tokenizer.diagnose()
        return SyntaxError(message, (filename, tok.start[0], 1 + tok.start[1], tok.line))


def simple_parser_main(parser_class):
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Print timing stats; repeat for more debug output",
    )
    argparser.add_argument(
        "-q", "--quiet", action="store_true", help="Don't print the parsed program"
    )
    argparser.add_argument("filename", help="Input file ('-' to use stdin)")

    args = argparser.parse_args()
    verbose = args.verbose
    verbose_tokenizer = verbose >= 3
    verbose_parser = verbose == 2 or verbose >= 4

    t0 = time.time()

    filename = args.filename
    if filename == "" or filename == "-":
        filename = "<stdin>"
        file = sys.stdin
    else:
        file = open(args.filename)
    try:
        tokengen = tokenize.generate_tokens(file.readlines(), 0)
        tokenizer = Tokenizer(tokengen, verbose=verbose_tokenizer)
        parser = parser_class(tokenizer, verbose=verbose_parser)
        try:
            tree = parser.start()
        except Exception:
            import pdb;pdb.xpm()
            raise
        try:
            if file.isatty():
                endpos = 0
            else:
                endpos = file.tell()
        except IOError:
            endpos = 0
    finally:
        if file is not sys.stdin:
            file.close()

    t1 = time.time()

    if not tree:
        err = parser.make_syntax_error(filename)
        traceback.print_exception(err.__class__, err, None)
        sys.exit(1)

    if not args.quiet:
        print tree

    if verbose:
        dt = t1 - t0
        diag = tokenizer.diagnose()
        nlines = diag.end[0]
        if diag.type == ENDMARKER:
            nlines -= 1
        print "Total time: {dt:.3f} sec; {nlines} lines"
        if endpos:
            print " ({endpos} bytes)"
        if dt:
            print "; {nlines / dt:.0f} lines/sec"
        else:
            print
        print "Caches sizes:"
        print "  token array : {len(tokenizer._tokens):10}"
        print "        cache : {len(parser._cache):10}"
        ## print_memstats()
