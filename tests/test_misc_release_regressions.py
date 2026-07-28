"""Regression coverage for the release-readiness follow-up fixes."""

import json
import typing

import pytest

import kwconf
from kwconf.annotations import value_matches_annotation


def test_coerce_uses_canonical_parser_for_aliases():
    class C(kwconf.Config):
        num = kwconf.Value(0, type=int, alias=['n'])

    cfg = C.coerce(n='42')
    assert cfg.num == 42
    assert isinstance(cfg.num, int)


def test_validate_rejects_short_alias_collisions():
    class C(kwconf.Config):
        left = kwconf.Value(0, short_alias=['x'])
        right = kwconf.Value(0, short_alias=['x'])

    with pytest.raises(ValueError, match="short option '-x'.*left.*right"):
        C.validate()


def test_inline_json_mode_does_not_fall_back_to_yaml():
    pytest.importorskip('yaml')

    class C(kwconf.Config):
        value = 0

    with pytest.raises(json.JSONDecodeError):
        C().load(data='value: 3', mode='json', argv=False)
    cfg = C()
    cfg.load(data='value: 3', mode='yaml', argv=False)
    assert cfg.value == 3


def test_missing_pathlike_raises_file_not_found(tmp_path):
    class C(kwconf.Config):
        value = 0

    missing = tmp_path / 'missing.json'
    with pytest.raises(FileNotFoundError, match='config file does not exist'):
        C.cli(data=missing, argv=False)


def test_literal_validation_distinguishes_bool_from_int():
    assert value_matches_annotation(1, typing.Literal[1])
    assert not value_matches_annotation(True, typing.Literal[1])
    assert value_matches_annotation(True, typing.Literal[True])
    assert not value_matches_annotation(1, typing.Literal[True])


def test_classvar_is_not_a_config_field():
    class C(kwconf.Config):
        label: typing.ClassVar[str] = 'class-only'
        value: int = 1

    cfg = C()
    assert C.label == 'class-only'
    assert cfg.asdict() == {'value': 1}
    assert 'label' not in C.__default__

    @kwconf.dataconf
    class D:
        label: typing.ClassVar[str] = 'class-only'
        value: int = 1

    dcfg = D()
    assert D.label == 'class-only'
    assert dcfg.asdict() == {'value': 1}
    assert 'label' not in D.__default__


def test_json_output_rejects_non_json_values_and_handles_mixed_keys():
    pytest.importorskip('ubelt')

    class C(kwconf.Config):
        payload = None

    cfg = C(payload={1: 'one', 'two': 2})
    result = cfg.__json__()
    json.dumps(result)
    assert result == {'payload': {1: 'one', 'two': 2}}

    cfg.payload = 1 + 2j
    with pytest.raises(TypeError, match='Unknown JSON serialization'):
        cfg.__json__()

    cfg.payload = {(1, 2): 'tuple key'}
    with pytest.raises(TypeError):
        cfg.__json__()


def test_dataconf_documentation_examples_are_preserved():
    import importlib

    module = importlib.import_module('kwconf.dataconfig')
    doc = module.dataconf.__doc__ or ''
    assert 'class ExampleConfig2' in doc
    assert 'class PathologicalConfig' in doc
    assert 'FIXME: xdoctest problem' in doc
    assert hasattr(module, '__example__')
