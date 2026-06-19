# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
"""
The small helpers in kwconf.util were vendored from ubelt when ubelt became an
optional dependency. These tests assert they stay byte-compatible with ubelt
(which remains a test dependency), so future edits cannot silently drift.
"""
import pytest

from kwconf.util.util_text import codeblock, paragraph, indent
from kwconf.util.util_misc import iterable, NoParam
from kwconf.util.util_repr import NiceRepr

ub = pytest.importorskip('ubelt')


TEXT_CASES = [
    "\n    a\n        b\n    c\n    ",
    "x",
    "\nfoo\nbar\n",
    "    only indented\n    lines\n",
    "\n\n  a\n\n  b\n\n",
    "single line no newline",
]


@pytest.mark.parametrize('text', TEXT_CASES)
def test_codeblock_matches_ubelt(text):
    assert codeblock(text) == ub.codeblock(text)


@pytest.mark.parametrize('text', ['  a\n  b   c\n', 'x', '', '   ', 'a\tb\nc'])
def test_paragraph_matches_ubelt(text):
    assert paragraph(text) == ub.paragraph(text)


@pytest.mark.parametrize('text', ['a\nb\n\nc', 'a\nb', '', 'single'])
@pytest.mark.parametrize('prefix', ['  ', '    ', '> '])
def test_indent_matches_ubelt(text, prefix):
    assert indent(text, prefix) == ub.indent(text, prefix)


def test_indent_default_prefix_matches_ubelt():
    assert indent('a\nb') == ub.indent('a\nb')


@pytest.mark.parametrize('obj', [[1], 'ab', 3, {1: 2}, (1, 2), None, set()])
def test_iterable_matches_ubelt(obj):
    assert iterable(obj) == ub.iterable(obj)
    assert iterable(obj, strok=True) == ub.iterable(obj, strok=True)


def test_noparam_behaves_like_ubelt():
    assert repr(NoParam) == repr(ub.NoParam) == 'NoParam'
    assert bool(NoParam) is False
    # Singleton + copy/deepcopy stability (identity must be preserved).
    import copy
    assert NoParam is copy.copy(NoParam)
    assert NoParam is copy.deepcopy(NoParam)
    from kwconf.util.util_misc import _NoParamType
    assert _NoParamType() is NoParam


def test_nicerepr_format_matches_ubelt():
    # Same class name on both sides so only the mixin behavior differs.
    def make(base):
        return type('Widget', (base,), {'__nice__': lambda self: 'hello'})

    mine = make(NiceRepr)()
    theirs = make(ub.NiceRepr)()
    assert str(mine) == str(theirs) == '<Widget(hello)>'
    # repr differs only by the object address; compare structure.
    assert repr(mine).startswith('<Widget(hello) at 0x')
    assert repr(theirs).startswith('<Widget(hello) at 0x')
