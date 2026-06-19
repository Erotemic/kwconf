# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
"""
Tests for annotation-driven Value enrichment on Config.

These cover the cases where kwconf reads runtime information from a class
variable's type annotation and uses it to populate Value metadata.
"""
import typing

import pytest

import kwconf as kw


def test_literal_string_populates_choices_and_type():
    class C(kw.Config):
        mode: typing.Literal['fast', 'slow', 'auto'] = 'auto'

    template = C.__default__['mode']
    assert template.value == 'auto'
    assert template.type is str
    assert list(template.parsekw['choices']) == ['fast', 'slow', 'auto']

    cfg = C.cli(argv=['--mode=fast'])
    assert cfg.mode == 'fast'

    with pytest.raises(SystemExit):
        C.cli(argv=['--mode=garbage'])


def test_literal_int_populates_choices_and_type():
    class C(kw.Config):
        level: typing.Literal[1, 2, 3] = 1

    template = C.__default__['level']
    assert template.value == 1
    assert template.type is int
    assert list(template.parsekw['choices']) == [1, 2, 3]

    cfg = C.cli(argv=['--level=3'])
    assert cfg.level == 3


def test_literal_via_optional_still_populates_choices():
    class C(kw.Config):
        mode: typing.Optional[typing.Literal['x', 'y']] = None

    template = C.__default__['mode']
    assert list(template.parsekw['choices']) == ['x', 'y']
    # Underlying type is still inferred from the Literal members.
    assert template.type is str


def test_user_choices_win_over_literal():
    class C(kw.Config):
        mode: typing.Literal['a', 'b', 'c'] = kw.Value('a', choices=['a', 'b'])  # ty: ignore[invalid-assignment]

    template = C.__default__['mode']
    # user-provided choices should not be overridden by the Literal.
    assert list(template.parsekw['choices']) == ['a', 'b']


def test_literal_mixed_types_skips_type_inference():
    """Heterogeneous Literal members can't be coerced to one runtime type."""
    class C(kw.Config):
        thing: typing.Literal['x', 1] = 'x'

    template = C.__default__['thing']
    assert list(template.parsekw['choices']) == ['x', 1]
    # No single type can be inferred -- leave Value.type alone.
    assert template.type is None



def test_future_annotations_populate_choices_and_type():
    """Stringified annotations should be resolved during class creation."""
    ns = {}
    exec(
        """
from __future__ import annotations
import typing
import kwconf as kw

class C(kw.Config):
    mode: typing.Literal['fast', 'slow', 'auto'] = 'auto'
    nums: list[int] = kw.Value(default_factory=list)
""",
        ns,
    )
    C = ns['C']
    mode_template = C.__default__['mode']
    assert mode_template.type is str
    assert list(mode_template.parsekw['choices']) == ['fast', 'slow', 'auto']
    nums_template = C.__default__['nums']
    assert nums_template.type is list
    assert getattr(nums_template, '_annotation', None) == list[int]
