# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
"""
Tests for ``Value(type='yaml')``.

YAML-typed fields parse string inputs via ``yaml.safe_load``. The same
behavior applies whether the string came from argv, a config file, or
a kwarg in the constructor -- consistent with how other typed Values
already coerce strings.
"""
import typing

import pytest


def _require_yaml():
    try:
        import yaml  # NOQA
    except ImportError:
        pytest.skip('requires yaml')


def test_yaml_type_parses_list_from_kwargs():
    _require_yaml()
    import kwconf

    class C(kwconf.Config):
        items: typing.Any = kwconf.Value(None, type="yaml")

    cfg = C(items='[1, 2, 3]')
    assert cfg['items'] == [1, 2, 3]


def test_yaml_type_parses_list_from_cli():
    _require_yaml()
    import kwconf

    class C(kwconf.Config):
        items: typing.Any = kwconf.Value(None, type="yaml")

    cfg = C.cli(argv=['--items=[1,2,3]'])
    assert cfg['items'] == [1, 2, 3]


def test_yaml_type_parses_dict_from_cli():
    _require_yaml()
    import kwconf

    class C(kwconf.Config):
        opts: typing.Any = kwconf.Value(None, type="yaml")

    cfg = C.cli(argv=['--opts={a: 1, b: 2}'])
    assert cfg['opts'] == {'a': 1, 'b': 2}


def test_yaml_type_parses_scalars():
    _require_yaml()
    import kwconf

    class C(kwconf.Config):
        x: typing.Any = kwconf.Value(None, type="yaml")

    assert C(x='1')['x'] == 1
    assert C(x='true')['x'] is True
    assert C(x='null')['x'] is None
    assert C(x='auto')['x'] == 'auto'


def test_yaml_type_passthrough_non_string():
    _require_yaml()
    import kwconf

    class C(kwconf.Config):
        x: typing.Any = kwconf.Value(None, type="yaml")

    cfg = C(x=[1, 2, 3])
    assert cfg['x'] == [1, 2, 3]
    cfg = C(x=42)
    assert cfg['x'] == 42


def test_yaml_type_unknown_named_raises():
    import kwconf

    with pytest.raises(TypeError, match='Unknown named Value type'):
        kwconf.Value(None, type='not-a-real-type')


def test_yaml_type_legacy_smartcast_string_still_rejected():
    import kwconf

    # The old smartcast aliases must continue to raise -- only registered
    # named types like 'yaml' are accepted as strings.
    with pytest.raises(TypeError, match='Unknown named Value type'):
        kwconf.Value(None, type='smartcast')
