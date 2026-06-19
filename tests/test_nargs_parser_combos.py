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

The intended design (REVISED -- uniform, no special cases):

* ``nargs`` applies the field's parser to EACH token and **collects** the results
  into a list. That's the whole rule -- we just stop forcing ``auto`` per token
  and use the real parser; argparse already collects into a list. No concat, no
  flatten, no parser-kind distinction, no annotation depth-matching.
* Consequences (uniform across every parser -- result depth = parser-output
  depth + 1 for the nargs wrapper):
    - ``parser='yaml'``, ``--key '[1,2,3]' '[4,5,6]'`` -> ``[[1,2,3],[4,5,6]]``
    - ``parser='csv'``,  ``--key=1,2,3``               -> ``[[1,2,3]]``
    - ``parser='csv'``,  ``--key 1 2 3``               -> ``[[1],[2],[3]]``
  So ``csv + nargs`` is *defined but not useful*: use csv (commas) OR nargs
  (spaces), not both.
* The scriptconfig dual-form (``--k a,b,c`` == ``--k a b c``) is intentionally
  DROPPED -- it required a concat special-case and was ambiguous for structured
  tokens (``--k [1,2,3] [4,5,6]`` -> flatten or group?). For a flat list use
  csv or nargs; for a polymorphic ``list|dict`` use yaml WITHOUT nargs.

If we decide to drop this niche, delete this file -- no harm done.
"""
import shlex

import pytest

import kwconf

_PENDING = (
    "pending nargs+parser fix: nargs currently ignores the field parser and "
    "runs auto per token; target is parser-per-token + collect"
)


def _cli(cls, cmd):
    return cls.cli(argv=shlex.split(cmd))['key']


# --------------------------------------------------------------------------
# csv + nargs : uniform collect (defined but not a useful combo)
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


@pytest.mark.xfail(strict=True, reason=_PENDING)
def test_csv_nargs_comma_token_wraps():
    # The least-surprising case: one `=`-supplied comma token csv's to a list,
    # which nargs wraps -> list-of-one-list.
    assert _cli(CsvInt, '--key=1,2,3') == [[1, 2, 3]]


@pytest.mark.xfail(strict=True, reason=_PENDING)
def test_csv_nargs_space_tokens_wrap_each():
    # Uniform rule: each token csv'd then collected (so this combo nests and is
    # not useful -- documented on purpose).
    assert _cli(CsvInt, '--key 1 2 3') == [[1], [2], [3]]


@pytest.mark.xfail(strict=True, reason=_PENDING)
def test_csv_nargs_mixed_tokens():
    assert _cli(CsvInt, '--key 1,2 3') == [[1, 2], [3]]


@pytest.mark.xfail(strict=True, reason=_PENDING)
def test_csv_nargs_element_gating():
    # csv is annotation-aware per token: list[str] keeps strings.
    assert _cli(CsvStr, '--key 1,2 3o') == [['1', '2'], ['3o']]


# --------------------------------------------------------------------------
# yaml + nargs : same uniform collect rule
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
def test_yaml_nargs_single_structured_token_wraps():
    # nargs always wraps: a single yaml-list token becomes a 1-element list.
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
