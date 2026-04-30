"""
Tests for optional annotation-based validation on DataConfig.

Validation is opt-in via ``__validate__ = 'error' | 'warn'`` on the class
or ``Value(..., validate=...)`` per field. Annotations consulted include
plain types, ``Literal[...]``, unions, and parameterized collections.
"""
import typing

import pytest


def test_validation_off_by_default():
    import kwconf

    class D(kwconf.DataConfig):
        mode: typing.Literal['fast', 'slow'] = 'fast'

    # mode is a choice on argparse but constructor doesn't enforce
    # without ``__validate__``. ``'wrong'`` is silently accepted.
    cfg = D(mode='wrong')
    assert cfg['mode'] == 'wrong'


def test_class_level_error_validation_literal():
    import kwconf

    class C(kwconf.DataConfig):
        __validate__ = 'error'
        mode: typing.Literal['fast', 'slow'] = 'fast'

    assert C(mode='fast')['mode'] == 'fast'
    with pytest.raises(TypeError, match='does not match annotation'):
        C(mode='wrong')


def test_class_level_warn_validation_literal():
    import kwconf

    class C(kwconf.DataConfig):
        __validate__ = 'warn'
        mode: typing.Literal['fast', 'slow'] = 'fast'

    with pytest.warns(UserWarning, match='does not match annotation'):
        cfg = C(mode='wrong')
    assert cfg['mode'] == 'wrong'


def test_per_field_validate_overrides_class():
    import kwconf

    class C(kwconf.DataConfig):
        __validate__ = 'error'
        mode: typing.Literal['fast', 'slow'] = kwconf.Value(
            'fast', validate=False)

    # Class would error, but field opts out.
    cfg = C(mode='whatever')
    assert cfg['mode'] == 'whatever'


def test_validation_union_int_or_none():
    import kwconf

    class C(kwconf.DataConfig):
        __validate__ = 'error'
        x: typing.Optional[int] = None

    assert C(x=None)['x'] is None
    assert C(x=5)['x'] == 5
    assert C(x='5')['x'] == 5  # coerced via type=int from annotation
    with pytest.raises(TypeError):
        C(x=[1, 2])  # not int, not None


def test_validation_yaml_typed_with_literal():
    pytest.importorskip('yaml')
    import kwconf

    class C(kwconf.DataConfig):
        __validate__ = 'error'
        flag: typing.Literal[1, 0, True, 'auto', None] = kwconf.Value(
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
        C(flag='foobar')


def test_validation_list_of_int():
    import kwconf

    class C(kwconf.DataConfig):
        __validate__ = 'error'
        items: list[int] = kwconf.Value(default_factory=list)

    assert C(items=[1, 2, 3])['items'] == [1, 2, 3]
    with pytest.raises(TypeError):
        C(items=[1, 'two', 3])


def test_validation_skipped_without_annotation():
    import kwconf

    class C(kwconf.DataConfig):
        __validate__ = 'error'
        x = kwconf.Value(None)  # no annotation

    # No annotation, no validation, no error.
    assert C(x='whatever')['x'] == 'whatever'


def test_validation_runs_on_setitem():
    import kwconf

    class C(kwconf.DataConfig):
        __validate__ = 'error'
        mode: typing.Literal['a', 'b'] = 'a'

    cfg = C()
    cfg['mode'] = 'b'
    with pytest.raises(TypeError):
        cfg['mode'] = 'c'
