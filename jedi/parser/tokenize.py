# -*- coding: utf-8 -*-
"""
This tokenizer has been copied from the ``tokenize.py`` standard library
tokenizer. The reason was simple: The standard library tokenizer fails
if the indentation is not right. The fast parser of jedi however requires
"wrong" indentation.

Basically this is a stripped down version of the standard library module, so
you can read the documentation there. Additionally we included some speed and
memory optimizations here.
"""
from __future__ import absolute_import

import string
import re
from io import StringIO
from token import (tok_name, N_TOKENS, ENDMARKER, STRING, NUMBER, NAME, OP,
                   ERRORTOKEN, NEWLINE, INDENT, DEDENT)

from jedi._compatibility import u

cookie_re = re.compile("coding[:=]\s*([-\w.]+)")


# From here on we have custom stuff (everything before was originally Python
# internal code).
FLOWS = ['if', 'else', 'elif', 'while', 'with', 'try', 'except', 'finally']


namechars = string.ascii_letters + '_'


COMMENT = N_TOKENS
tok_name[COMMENT] = 'COMMENT'


class Token(object):
    """
    The token object is an efficient representation of the structure
    (type, token, (start_pos_line, start_pos_col, prefix)). It has indexer
    methods that maintain compatibility to existing code that expects the above
    structure.

    >>> repr(Token(1, "test", (1, 1, '')))
    "<Token: ('NAME', 'test', (1, 1, ''))>"
    >>> Token(1, 'bar', (3, 4, '')).__getstate__()
    (1, 'bar', 3, 4, '')
    >>> a = Token(0, 'baz', (0, 0, ''))
    >>> a.__setstate__((1, 'foo', 3, 4, ''))
    >>> a
    <Token: ('NAME', 'foo', (3, 4, ''))>
    >>> a.start_pos
    (3, 4)
    >>> a.value
    'foo'
    >>> a._start_pos_col
    4
    >>> Token(1, u("😷"), (1 ,1, '')).value + "p" == u("😷p")
    True
    """
    __slots__ = ("type", "value", "_start_pos_line", "_start_pos_col",
                 "prefix")

    def __init__(self, type, value, start_pos, prefix=''):
        self.type = type
        self.value = value
        self._start_pos_line = start_pos[0]
        self._start_pos_col = start_pos[1]
        self.prefix = prefix

    def __repr__(self):
        typ = tok_name[self.type]
        content = typ, self.value,\
            (self._start_pos_line, self._start_pos_col, self.prefix)
        return "<%s: %s>" % (type(self).__name__, content)

    @property
    def start_pos(self):
        return self._start_pos_line, self._start_pos_col

    @property
    def end_pos(self):
        """Returns end position respecting multiline tokens."""
        end_pos_line = self._start_pos_line
        lines = self.value.split('\n')
        if self.value.endswith('\n'):
            lines = lines[:-1]
            lines[-1] += '\n'
        end_pos_line += len(lines) - 1
        end_pos_col = self._start_pos_col
        # Check for multiline token
        if self._start_pos_line == end_pos_line:
            end_pos_col += len(lines[-1])
        else:
            end_pos_col = len(lines[-1])
        return (end_pos_line, end_pos_col)

    # Make cache footprint smaller for faster unpickling
    def __getstate__(self):
        return (self.type, self.value,
                self._start_pos_line, self._start_pos_col,
                self.prefix)

    # TODO DELETE this is not needed anymore, I guess. It should not get pickled.
    def __setstate__(self, state):
        self.type = state[0]
        self.value = state[1]
        self._start_pos_line = state[2]
        self._start_pos_col = state[3]
        self.prefix = state[4]


def group(*choices):
    return '(' + '|'.join(choices) + ')'


def maybe(*choices):
    return group(*choices) + '?'


# Note: we use unicode matching for names ("\w") but ascii matching for
# number literals.
whitespace = r'[ \f\t]*'
comment = r'#[^\r\n]*'
name = r'\w+'

hex_number = r'0[xX][0-9a-fA-F]+'
bin_number = r'0[bB][01]+'
oct_number = r'0[oO][0-7]+'
dec_number = r'(?:0+|[1-9][0-9]*)'
int_number = group(hex_number, bin_number, oct_number, dec_number)
exponent = r'[eE][-+]?[0-9]+'
point_float = group(r'[0-9]+\.[0-9]*', r'\.[0-9]+') + maybe(exponent)
Expfloat = r'[0-9]+' + exponent
float_number = group(point_float, Expfloat)
imag_number = group(r'[0-9]+[jJ]', float_number + r'[jJ]')
number = group(imag_number, float_number, int_number)

# Tail end of ' string.
single = r"[^'\\]*(?:\\.[^'\\]*)*'"
# Tail end of " string.
double = r'[^"\\]*(?:\\.[^"\\]*)*"'
# Tail end of ''' string.
single3 = r"[^'\\]*(?:(?:\\.|'(?!''))[^'\\]*)*'''"
# Tail end of """ string.
double3 = r'[^"\\]*(?:(?:\\.|"(?!""))[^"\\]*)*"""'
triple = group("[bB]?[rR]?'''", '[bB]?[rR]?"""')
# Single-line ' or " string.

# Because of leftmost-then-longest match semantics, be sure to put the
# longest operators first (e.g., if = came before ==, == would get
# recognized as two instances of =).
operator = group(r"\*\*=?", r">>=?", r"<<=?", r"!=",
                 r"//=?", r"->",
                 r"[+\-*/%&|^=<>]=?",
                 r"~")

bracket = '[][(){}]'
special = group(r'\r?\n', r'\.\.\.', r'[:;.,@]')
funny = group(operator, bracket, special)

# First (or only) line of ' or " string.
cont_str = group(r"[bBuU]?[rR]?'[^\n'\\]*(?:\\.[^\n'\\]*)*" +
                 group("'", r'\\\r?\n'),
                 r'[bBuU]?[rR]?"[^\n"\\]*(?:\\.[^\n"\\]*)*' +
                 group('"', r'\\\r?\n'))
pseudo_extras = group(r'\\\r?\n', comment, triple)
pseudo_token = group(whitespace) + \
    group(pseudo_extras, number, funny, cont_str, name)


def _compile(expr):
    return re.compile(expr, re.UNICODE)


pseudoprog, single3prog, double3prog = map(
    _compile, (pseudo_token, single3, double3))

endprogs = {"'": _compile(single), '"': _compile(double),
            "'''": single3prog, '"""': double3prog,
            "r'''": single3prog, 'r"""': double3prog,
            "b'''": single3prog, 'b"""': double3prog,
            "u'''": single3prog, 'u"""': double3prog,
            "br'''": single3prog, 'br"""': double3prog,
            "R'''": single3prog, 'R"""': double3prog,
            "B'''": single3prog, 'B"""': double3prog,
            "U'''": single3prog, 'U"""': double3prog,
            "bR'''": single3prog, 'bR"""': double3prog,
            "Br'''": single3prog, 'Br"""': double3prog,
            "BR'''": single3prog, 'BR"""': double3prog,
            'r': None, 'R': None, 'b': None, 'B': None}

triple_quoted = {}
for t in ("'''", '"""',
          "r'''", 'r"""', "R'''", 'R"""',
          "b'''", 'b"""', "B'''", 'B"""',
          "u'''", 'u"""', "U'''", 'U"""',
          "br'''", 'br"""', "Br'''", 'Br"""',
          "bR'''", 'bR"""', "BR'''", 'BR"""'):
    triple_quoted[t] = t
single_quoted = {}
for t in ("'", '"',
          "r'", 'r"', "R'", 'R"',
          "b'", 'b"', "B'", 'B"',
          "u'", 'u""', "U'", 'U"',
          "br'", 'br"', "Br'", 'Br"',
          "bR'", 'bR"', "BR'", 'BR"'):
    single_quoted[t] = t

del _compile

tabsize = 8

ALWAYS_BREAK_TOKEN = (';', 'import', 'from', 'class', 'def', 'try', 'except',
                      'finally', 'while', 'return')


def source_tokens(source, line_offset=0):
    """Generate tokens from a the source code (string)."""
    source = source + '\n'  # end with \n, because the parser needs it
    readline = StringIO(source).readline
    return generate_tokens(readline, line_offset)


def generate_tokens(readline, line_offset=0):
    """
    The original stdlib Python version with minor modifications.
    Modified to not care about dedents.
    """
    paren_level = 0  # count parentheses
    indents = [0]
    lnum = line_offset
    numchars = '0123456789'
    contstr = ''
    contline = None
    new_line = False
    prefix = ''  # Should never be required, but here for safety
    while True:            # loop over lines in stream
        line = readline()  # readline returns empty when finished. See StringIO
        if not line:
            if contstr:
                yield Token(ERRORTOKEN, contstr, contstr_start, prefix)
            break

        lnum += 1
        pos, max = 0, len(line)

        if contstr:                                         # continued string
            endmatch = endprog.match(line)
            if endmatch:
                pos = endmatch.end(0)
                yield Token(STRING, contstr + line[:pos],
                            contstr_start, prefix)
                contstr = ''
                contline = None
            else:
                contstr = contstr + line
                contline = contline + line
                continue

        while pos < max:
            pseudomatch = pseudoprog.match(line, pos)
            if not pseudomatch:                             # scan for tokens
                txt = line[pos]
                if line[pos] in '"\'':
                    # If a literal starts but doesn't end the whole rest of the
                    # line is an error token.
                    txt = line[pos:]
                yield Token(ERRORTOKEN, txt, (lnum, pos))
                pos += 1
                continue

            prefix = pseudomatch.group(1)
            start, pos = pseudomatch.span(2)
            spos = (lnum, start)
            token, initial = line[start:pos], line[start]

            if new_line and initial not in '\r\n#':
                new_line = False
                if paren_level == 0:
                    if start > indents[-1]:
                        yield Token(INDENT, '', spos, '')
                        indents.append(start)
                    while start < indents[-1]:
                        yield Token(DEDENT, '', spos, '')
                        indents.pop()

            if (initial in numchars or                      # ordinary number
                    (initial == '.' and token != '.' and token != '...')):
                yield Token(NUMBER, token, spos, prefix)
            elif initial in '\r\n':
                if not new_line and paren_level == 0:
                    yield Token(NEWLINE, token, spos, prefix)
                new_line = True
            elif initial == '#':
                assert not token.endswith("\n")
                #yield Token(COMMENT, token, spos, prefix)
            elif token in triple_quoted:
                endprog = endprogs[token]
                endmatch = endprog.match(line, pos)
                if endmatch:                                # all on one line
                    pos = endmatch.end(0)
                    token = line[start:pos]
                    yield Token(STRING, token, spos, prefix)
                else:
                    contstr_start = (lnum, start)           # multiple lines
                    contstr = line[start:]
                    contline = line
                    break
            elif initial in single_quoted or \
                    token[:2] in single_quoted or \
                    token[:3] in single_quoted:
                if token[-1] == '\n':                       # continued string
                    contstr_start = lnum, start
                    endprog = (endprogs.get(initial) or endprogs.get(token[1])
                               or endprogs.get(token[2]))
                    contstr = line[start:]
                    contline = line
                    break
                else:                                       # ordinary string
                    yield Token(STRING, token, spos, prefix)
            elif initial in namechars:                      # ordinary name
                if token in ALWAYS_BREAK_TOKEN:
                    paren_level = 0
                    while True:
                        indent = indents.pop()
                        if indent > start:
                            yield Token(DEDENT, '', (lnum, 0), '')
                        else:
                            indents.append(indent)
                            break
                yield Token(NAME, token, spos, prefix)
            elif initial == '\\' and line[start:] == '\\\n':  # continued stmt
                continue
            else:
                if token in '([{':
                    paren_level += 1
                elif token in ')]}':
                    paren_level -= 1
                yield Token(OP, token, spos, prefix)

    for indent in indents[1:]:
        yield Token(DEDENT, '', (lnum, 0), '')
    yield Token(ENDMARKER, '', (lnum, 0), prefix)
