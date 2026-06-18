"""Tests for the additive ``kwconf.coerce`` module (the 'auto' parser)."""
from typing import Any, Optional, Union

import pytest

from kwconf.coerce import auto, coerce, register_parser, CannotCoerce


def _is(value: Any, expect_type: type) -> bool:
    return type(value) is expect_type


class TestAutoFullInference:
    def test_scalars(self):
        assert auto('True', Any) is True
        assert auto('False', Any) is False
        assert auto('None', Any) is None
        assert _is(auto('123', Any), int) and auto('123') == 123
        assert _is(auto('1.5', Any), float) and auto('1.5') == 1.5

    def test_strings_stay_strings(self):
        assert auto('foo123', Any) == 'foo123'

    def test_no_comma_splitting(self):
        # The headline departure from scriptconfig.
        assert auto('1,2,3', Any) == '1,2,3'

    def test_non_string_passthrough(self):
        assert auto(123, Any) == 123
        assert auto([1, 2], Any) == [1, 2]


class TestAutoAnnotationGated:
    def test_str_annotation_pins_to_string(self):
        assert auto('123', str) == '123'
        assert auto('None', str) == 'None'
        assert auto('True', str) == 'True'

    def test_union_lets_ints_through_keeps_other_strings(self):
        U = Union[str, int, None]
        assert _is(auto('123', U), int) and auto('123', U) == 123
        assert auto('foo', U) == 'foo'
        assert auto('None', U) is None

    def test_optional_int(self):
        assert auto('123', Optional[int]) == 123
        assert auto('None', Optional[int]) is None

    def test_literal_infers_member_type(self):
        from typing import Literal
        assert auto('a', Literal['a', 'b']) == 'a'
        assert auto('2', Literal[1, 2, 3]) == 2


class TestAutoFallback:
    def test_warn_and_fallback_when_str_not_allowed(self):
        with pytest.warns(UserWarning, match='could not parse'):
            got = auto('foo', Optional[int])
        assert got == 'foo'

    def test_container_annotation_warns_and_falls_back(self):
        with pytest.warns(UserWarning, match="parser='csv'"):
            got = auto('1,2,3', list[int])
        assert got == '1,2,3'


class TestAutoBoolIntInterplay:
    def test_int_beats_bool_for_one(self):
        assert _is(auto('1', Union[int, bool]), int)
        assert auto('1', Union[int, bool]) == 1

    def test_bool_claims_one_when_no_int(self):
        assert auto('1', Union[bool, None]) is True
        assert auto('0', Union[bool, None]) is False

    def test_bool_always_claims_true_false(self):
        assert auto('true', Union[bool, None]) is True
        assert auto('false', Union[bool, None]) is False

    def test_strict_bool_rejects_arbitrary_ints(self):
        # "123" must NOT become True; bool is strict (0/1/true/false only).
        with pytest.warns(UserWarning, match='could not parse'):
            got = auto('123', Union[bool, None])
        assert got == '123'

    def test_true_with_only_int_falls_back(self):
        with pytest.warns(UserWarning, match='could not parse'):
            got = auto('true', Optional[int])
        assert got == 'true'


class TestCoerceDispatch:
    def test_default_auto(self):
        assert coerce('123') == 123

    def test_non_string_passthrough(self):
        assert coerce(123) == 123
        obj = object()
        assert coerce(obj) is obj

    def test_callable_spec(self):
        assert coerce('123', spec=str) == '123'
        assert coerce('5', spec=int) == 5

    def test_csv(self):
        assert coerce('1,2,3', spec='csv') == [1, 2, 3]
        assert coerce('a,b', spec='csv') == ['a', 'b']

    def test_yaml(self):
        pytest.importorskip('yaml')
        assert coerce('[1, 2, 3]', spec='yaml') == [1, 2, 3]
        assert coerce('true', spec='yaml') is True

    def test_auto_consults_annotation(self):
        assert coerce('123', annotation=str, spec='auto') == '123'

    def test_unknown_spec_raises(self):
        with pytest.raises(TypeError, match='unknown coerce spec'):
            coerce('x', spec='nope')

    def test_register_parser(self):
        register_parser('shout', lambda s: s.upper())
        assert coerce('hi', spec='shout') == 'HI'


def test_cannot_coerce_is_exported():
    assert issubclass(CannotCoerce, Exception)


class TestValueCoerceKwarg:
    """The new Value(parser=...) kwarg routes string coercion through
    kwconf.coerce; omitting it preserves the legacy type=/smartcast path."""

    def test_legacy_path_unchanged_when_coerce_unset(self):
        from kwconf import Value
        v = Value(None, type=float)
        v.update('3.3')
        assert v.value == 3.3

    def test_coerce_callable(self):
        from kwconf import Value
        v = Value(None, parser=str)
        v.update('123')
        assert v.value == '123'   # explicit str escape hatch keeps the string

    def test_coerce_csv(self):
        from kwconf import Value
        v = Value(None, parser='csv')
        v.update('1,2,3')
        assert v.value == [1, 2, 3]

    def test_coerce_auto_gated_by_annotation(self):
        from kwconf import Value
        v = Value(None, parser='auto')
        v._annotation = str           # mimic a `: str` class annotation
        v.update('123')
        assert v.value == '123'
        v2 = Value(None, parser='auto')
        v2.update('123')              # no annotation -> full inference
        assert v2.value == 123

    def test_non_string_passthrough(self):
        from kwconf import Value
        v = Value(None, parser='csv')
        v.update([1, 2])              # already a list; not re-parsed
        assert v.value == [1, 2]


class TestConfigCoerceConstructor:
    def test_coerce_constructor_parses_strings(self):
        import kwconf

        class MyConfig(kwconf.Config):
            __default__ = {'num': kwconf.Value(0, type=int)}

        assert MyConfig.coerce(num='42')['num'] == 42

    def test_coerce_constructor_passes_through_real_values(self):
        import kwconf

        class MyConfig(kwconf.Config):
            __default__ = {'num': kwconf.Value(0, type=int)}

        assert MyConfig.coerce(num=7)['num'] == 7


def test_coerce_and_type_are_mutually_exclusive():
    import pytest
    from kwconf import Value
    with pytest.raises(ValueError, match='either .parser.* or the deprecated'):
        Value(None, type=int, parser='auto')


class TestAutoIsDefaultParser:
    """With neither type= nor coerce= set, coercion uses the annotation-gated
    'auto' parser (the new default), for both bare and Value-wrapped fields."""

    def test_union_field_bare_and_wrapped_agree(self):
        import kwconf

        class Bare(kwconf.Config):
            x: Union[str, int, None] = None

        class Wrapped(kwconf.Config):
            x: Union[str, int, None] = kwconf.Value(None)

        for C in (Bare, Wrapped):
            assert C.coerce(x='123')['x'] == 123      # int member of the union
            assert C.coerce(x='foo')['x'] == 'foo'    # str catch-all
            assert C.coerce(x='None')['x'] is None

    def test_str_annotation_pins_to_string(self):
        import kwconf

        class C(kwconf.Config):
            x: str = 'd'

        assert C.coerce(x='123')['x'] == '123'

    def test_explicit_deprecated_type_uses_legacy_path(self):
        import kwconf
        v = kwconf.Value(None, type=int)
        v.update('5')
        assert v.value == 5
