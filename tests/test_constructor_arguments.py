import pytest

import kwconf


def test_reject_extra_positional_constructor_arguments():
    class DemoConfig(kwconf.Config):
        first = 1
        second = 2

    with pytest.raises(
        TypeError, match='accepts at most 2 positional arguments; got 3'
    ):
        DemoConfig(10, 20, 30)


def test_extra_positional_rejected_before_default_materialization():
    calls = []

    def make_value():
        calls.append('called')
        return []

    class DemoConfig(kwconf.Config):
        payload = kwconf.Value(default_factory=make_value)

    with pytest.raises(
        TypeError, match='accepts at most 1 positional argument; got 2'
    ):
        DemoConfig('first', 'extra')

    assert calls == []


def test_reject_positional_and_keyword_duplicate():
    class DemoConfig(kwconf.Config):
        first = 1
        second = 2

    with pytest.raises(TypeError, match="multiple values for argument 'first'"):
        DemoConfig(10, first=20)


def test_reject_positional_and_alias_duplicate():
    class DemoConfig(kwconf.Config):
        first = kwconf.Value(1, alias=['f'])
        second = 2

    with pytest.raises(TypeError, match="multiple values for argument 'first'"):
        DemoConfig(10, f=20)


def test_reject_canonical_and_alias_keyword_duplicate():
    class DemoConfig(kwconf.Config):
        first = kwconf.Value(1, alias=['f'])

    with pytest.raises(TypeError, match="multiple values for argument 'first'"):
        DemoConfig(first=10, f=20)


def test_canonical_keyword_fast_path_does_not_build_alias_map():
    class DemoConfig(kwconf.Config):
        first = kwconf.Value(1, alias=['f'])
        second = 2

    config = DemoConfig(first=10, second=20)
    assert config.asdict() == {'first': 10, 'second': 20}
    assert config._alias_map is None


def test_constructor_binding_remains_ordered_and_alias_aware():
    class DemoConfig(kwconf.Config):
        first = 1
        second = kwconf.Value(2, alias=['s'])
        third = 3

    config = DemoConfig(10, s=20, third=30)
    assert config.asdict() == {'first': 10, 'second': 20, 'third': 30}
