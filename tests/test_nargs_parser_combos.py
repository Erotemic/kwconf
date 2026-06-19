# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
"""
TENTATIVE tests for combining ``nargs`` with ``parser='csv'``/``'yaml'``.

These capture the exploration around "weird cases" so the design discussion is
not lost. Status:

* Plain asserts  -> behavior we consider decided / already working.
* ``xfail(strict=True)`` -> the agreed-but-NOT-yet-implemented design. They fail
  today because ``nargs`` currently *silently ignores* the field ``parser`` (each
  token just goes through ``auto``). When the design lands they will XPASS and
  strict-mode will flag them, prompting removal of the marker.

The intended design (see the design chat):

* A parser has a *kind*. ``csv`` is **list-producing**; ``yaml``/``auto`` are
  **value-producing**. Decisions are driven by the parser kind, NOT the
  annotation (no nesting/depth-matching).
* ``nargs`` + list-producing parser  -> parse each token, **concat** into one
  flat list (this is the scriptconfig dual-form: ``--k a,b,c`` == ``--k a b c``).
* ``nargs`` + value-producing parser -> parse each token, **collect** into a
  list (``nargs`` always wraps; so a single structured yaml token nests one
  level and a ``list|dict`` field's dict branch is unreachable under nargs).
* For a rich/polymorphic ``list|dict`` value, use ``yaml`` WITHOUT ``nargs``.

If we decide to drop this niche, delete this file -- no harm done.
"""
import shlex

import pytest

import kwconf

_PENDING = (
    "pending nargs+parser design: parser is currently ignored under nargs "
    "(concat rule for csv / collect rule for yaml not implemented)"
)


def _cli(cls, cmd):
    return cls.cli(argv=shlex.split(cmd))['key']


# --------------------------------------------------------------------------
# csv + nargs : the dual-form (concat rule)
# --------------------------------------------------------------------------
class CsvInt(kwconf.Config):
    __validate__ = False  # isolate parser/nargs behavior from validation
    key: list[int] = kwconf.Value(default_factory=list, parser='csv', nargs='*')


class CsvStr(kwconf.Config):
    __validate__ = False
    key: list[str] = kwconf.Value(default_factory=list, parser='csv', nargs='*')


def test_csv_nargs_empty():
    # Decided/working: no tokens -> empty list.
    assert _cli(CsvInt, '--key') == []


def test_csv_nargs_space_form_works_today():
    # Already works (auto-per-token happens to match the target for plain ints).
    assert _cli(CsvInt, '--key 1 2 3') == [1, 2, 3]


@pytest.mark.xfail(strict=True, reason=_PENDING)
def test_csv_nargs_comma_form():
    # `=`-supplied single comma token should split + concat.
    assert _cli(CsvInt, '--key=1,2,3') == [1, 2, 3]


@pytest.mark.xfail(strict=True, reason=_PENDING)
def test_csv_nargs_mixed_form():
    # comma AND space tokens flatten into one list.
    assert _cli(CsvInt, '--key 1,2 3') == [1, 2, 3]


@pytest.mark.xfail(strict=True, reason=_PENDING)
def test_csv_nargs_dual_form_equivalence():
    # The headline scriptconfig nicety: both spellings agree.
    assert _cli(CsvInt, '--key 1 2 3') == _cli(CsvInt, '--key=1,2,3') == [1, 2, 3]


@pytest.mark.xfail(strict=True, reason=_PENDING)
def test_csv_nargs_element_gating():
    # list[str] keeps each element a string (annotation-aware csv per token).
    assert _cli(CsvStr, '--key 1,2 3o') == ['1', '2', '3o']


# --------------------------------------------------------------------------
# yaml + nargs : collect rule (value-producing; nargs always wraps in a list)
# --------------------------------------------------------------------------
class YamlNargs(kwconf.Config):
    __validate__ = False
    key = kwconf.Value(None, parser='yaml', nargs='+')


def test_yaml_nargs_scalar_tokens_work_today():
    # Scalar tokens collect into a list (auto and yaml agree here).
    assert _cli(YamlNargs, '--key 1 2 3') == [1, 2, 3]


@pytest.mark.xfail(strict=True, reason=_PENDING)
def test_yaml_nargs_collects_structured_tokens():
    pytest.importorskip('yaml')
    assert _cli(YamlNargs, "--key '[1,2,3]' '[4,5,6]'") == [[1, 2, 3], [4, 5, 6]]


@pytest.mark.xfail(strict=True, reason=_PENDING)
def test_yaml_nargs_collects_dict_tokens():
    pytest.importorskip('yaml')
    assert _cli(YamlNargs, "--key '{a: 1}' '{b: 2}'") == [{'a': 1}, {'b': 2}]


@pytest.mark.xfail(strict=True, reason=_PENDING)
def test_yaml_nargs_single_structured_token_nests():
    # nargs wraps: a single yaml-list token becomes a 1-element list-of-lists.
    pytest.importorskip('yaml')
    assert _cli(YamlNargs, "--key '[1,2,3]'") == [[1, 2, 3]]


# --------------------------------------------------------------------------
# yaml WITHOUT nargs : the right way to get a polymorphic list|dict (works now)
# --------------------------------------------------------------------------
class YamlPoly(kwconf.Config):
    key: list | dict | int = kwconf.Value(None, parser='yaml')


def test_yaml_no_nargs_list():
    pytest.importorskip('yaml')
    assert _cli(YamlPoly, "--key=[1,2,3]") == [1, 2, 3]


def test_yaml_no_nargs_dict():
    pytest.importorskip('yaml')
    assert _cli(YamlPoly, "--key='{a: 1}'") == {'a': 1}


def test_yaml_no_nargs_scalar():
    pytest.importorskip('yaml')
    assert _cli(YamlPoly, "--key=5") == 5
