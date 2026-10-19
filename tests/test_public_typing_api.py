"""Public API runtime and typing contracts for downstream consumers."""

import pytest

import kwconf
from kwconf.config import Config, validate_schema


def test_static_schema_entrypoint_with_validate_field():
    class Options(kwconf.Config):
        validate: bool = False
        count: int = 1

    # These assignments are also static-type regression cases: callers should
    # not need a cast to use the schema validator or the typed CLI result.
    kwconf.validate_schema(Options)
    validate_schema(Options)
    options: Options = Options.cli(argv=False)
    assert options.validate is False
    assert options.count == 1


def test_static_schema_entrypoint_preserves_overrides():
    events = []

    class Override(kwconf.Config):
        @classmethod
        def validate(cls) -> None:
            events.append(cls)

    kwconf.validate_schema(Override)
    assert events == [Override]


def test_static_schema_entrypoint_rejects_alias_collisions():
    class Bad(kwconf.Config):
        a: int = kwconf.Value(1, alias='b')
        b: int = 2

    with pytest.raises(ValueError, match='collision'):
        kwconf.validate_schema(Bad)


def test_static_schema_entrypoint_rejects_unrelated_values():
    from typing import Any

    wrong_type: Any = object
    wrong_instance: Any = kwconf.Config()
    with pytest.raises(TypeError, match='Config subclass'):
        kwconf.validate_schema(wrong_type)
    with pytest.raises(TypeError, match='Config subclass'):
        kwconf.validate_schema(wrong_instance)


def test_subclass_returning_factories():
    class Options(Config):
        count: int = 2

    validate_schema(Options)
    original: Options = Options(count=5)
    via_cli: Options = Options.cli(argv=False)
    via_from_cli: Options = Options.from_cli(argv=False)
    via_coerce: Options = Options.coerce(count='3')
    via_env: Options = Options.from_env(prefix='KWCONF_TEST_NOT_SET_')
    assert isinstance(original, Options)
    assert type(via_cli) is Options
    assert type(via_from_cli) is Options
    assert type(via_coerce) is Options
    assert type(via_env) is Options
    assert via_coerce.count == 3

