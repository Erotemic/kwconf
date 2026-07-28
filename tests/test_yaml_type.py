# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
"""
Tests for ``Value(type='yaml')``.

YAML-typed fields parse string inputs via ``yaml.safe_load`` at the text
boundary: argv, or the explicit ``Config.coerce(...)`` constructor. The plain
``Config(...)`` constructor trusts the user and does NOT coerce -- strings are
kept verbatim (see dev/planning/design.md §4).
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
        items: typing.Any = kwconf.Value(None, type='yaml')

    # Plain constructor keeps the raw string (text boundary not crossed).
    assert C(items='[1, 2, 3]')['items'] == '[1, 2, 3]'
    # coerce() parses it via the yaml parser.
    assert C.coerce(items='[1, 2, 3]')['items'] == [1, 2, 3]


def test_yaml_type_parses_list_from_cli():
    _require_yaml()
    import kwconf

    class C(kwconf.Config):
        items: typing.Any = kwconf.Value(None, type='yaml')

    cfg = C.cli(argv=['--items=[1,2,3]'])
    assert cfg['items'] == [1, 2, 3]


def test_yaml_type_parses_dict_from_cli():
    _require_yaml()
    import kwconf

    class C(kwconf.Config):
        opts: typing.Any = kwconf.Value(None, type='yaml')

    cfg = C.cli(argv=['--opts={a: 1, b: 2}'])
    assert cfg['opts'] == {'a': 1, 'b': 2}


def test_yaml_type_parses_scalars():
    _require_yaml()
    import kwconf

    class C(kwconf.Config):
        x: typing.Any = kwconf.Value(None, type='yaml')

    # The plain constructor trusts the user: strings are kept verbatim.
    assert C(x='1')['x'] == '1'
    assert C(x='true')['x'] == 'true'
    assert C(x='null')['x'] == 'null'
    assert C(x='auto')['x'] == 'auto'
    # coerce() parses string inputs through the field's yaml parser.
    assert C.coerce(x='1')['x'] == 1
    assert C.coerce(x='true')['x'] is True
    assert C.coerce(x='null')['x'] is None
    assert C.coerce(x='auto')['x'] == 'auto'


def test_yaml_type_passthrough_non_string():
    _require_yaml()
    import kwconf

    class C(kwconf.Config):
        x: typing.Any = kwconf.Value(None, type='yaml')

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
