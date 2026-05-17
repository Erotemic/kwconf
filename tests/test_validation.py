# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
"""
Tests for optional annotation-based validation on Config.

Validation is opt-in via ``__validate__ = 'error' | 'warn'`` on the class
or ``Value(..., validate=...)`` per field. Annotations consulted include
plain types, ``Literal[...]``, unions, and parameterized collections.

Many tests in this file deliberately pass values that violate the field
annotations to exercise the runtime validator. Inline ``# ty: ignore``
comments suppress the corresponding static-analysis errors.
"""
import typing

import pytest


def test_validation_off_by_default():
    import kwconf

    class D(kwconf.Config):
        mode: typing.Literal['fast', 'slow'] = 'fast'

    # mode is a choice on argparse but constructor doesn't enforce
    # without ``__validate__``. ``'wrong'`` is silently accepted.
    cfg = D(mode='wrong')  # ty: ignore[invalid-argument-type]
    assert cfg['mode'] == 'wrong'


def test_class_level_error_validation_literal():
    import kwconf

    class C(kwconf.Config):
        __validate__ = 'error'
        mode: typing.Literal['fast', 'slow'] = 'fast'

    assert C(mode='fast')['mode'] == 'fast'
    with pytest.raises(TypeError, match='does not match annotation'):
        C(mode='wrong')  # ty: ignore[invalid-argument-type]


def test_class_level_warn_validation_literal():
    import kwconf

    class C(kwconf.Config):
        __validate__ = 'warn'
        mode: typing.Literal['fast', 'slow'] = 'fast'

    with pytest.warns(UserWarning, match='does not match annotation'):
        cfg = C(mode='wrong')  # ty: ignore[invalid-argument-type]
    assert cfg['mode'] == 'wrong'


def test_per_field_validate_overrides_class():
    import kwconf

    class C(kwconf.Config):
        __validate__ = 'error'
        mode: typing.Literal['fast', 'slow'] = kwconf.Value(  # ty: ignore[invalid-assignment]
            'fast', validate=False)

    # Class would error, but field opts out.
    cfg = C(mode='whatever')  # ty: ignore[invalid-argument-type]
    assert cfg['mode'] == 'whatever'


def test_validation_union_int_or_none():
    import kwconf

    class C(kwconf.Config):
        __validate__ = 'error'
        x: typing.Optional[int] = None

    assert C(x=None)['x'] is None
    assert C(x=5)['x'] == 5
    assert C(x='5')['x'] == 5  # ty: ignore[invalid-argument-type]
    with pytest.raises(TypeError):
        C(x=[1, 2])  # ty: ignore[invalid-argument-type]


def test_validation_yaml_typed_with_literal():
    pytest.importorskip('yaml')
    import kwconf

    class C(kwconf.Config):
        __validate__ = 'error'
        flag: typing.Literal[1, 0, True, 'auto', None] = kwconf.Value(  # ty: ignore[invalid-assignment]
            None, type='yaml')

    # yaml parses --flag=1 to int 1, which is in the Literal set
    assert C.cli(argv=['--flag=1'])['flag'] == 1
    assert C.cli(argv=['--flag=auto'])['flag'] == 'auto'
    assert C.cli(argv=['--flag=null'])['flag'] is None
    # 'foobar' is not in the set. CLI rejects via argparse choices first
    # (argparse runs before our validator), but constructor input goes
    # through validation directly.
    with pytest.raises(SystemExit):
        C.cli(argv=['--flag=foobar'])
    with pytest.raises(TypeError):
        C(flag='foobar')  # ty: ignore[invalid-argument-type]


def test_validation_list_of_int():
    import kwconf

    class C(kwconf.Config):
        __validate__ = 'error'
        nums: list[int] = kwconf.Value(default_factory=list)

    assert C(nums=[1, 2, 3])['nums'] == [1, 2, 3]
    with pytest.raises(TypeError):
        C(nums=[1, 'two', 3])  # ty: ignore[invalid-argument-type]


def test_validation_skipped_without_annotation():
    import kwconf

    class C(kwconf.Config):
        __validate__ = 'error'
        x = kwconf.Value(None)  # no annotation

    # No annotation, no validation, no error.
    assert C(x='whatever')['x'] == 'whatever'  # ty: ignore[unknown-argument]


def test_validation_runs_on_setitem():
    import kwconf

    class C(kwconf.Config):
        __validate__ = 'error'
        mode: typing.Literal['a', 'b'] = 'a'

    cfg = C()
    cfg['mode'] = 'b'
    with pytest.raises(TypeError):
        cfg['mode'] = 'c'
