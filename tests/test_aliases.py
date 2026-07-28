def test_config_aliases():
    import kwconf

    __common_default__ = {
        'opt1': kwconf.Value(None, alias=['option1']),
        'opt2': kwconf.Value(None, alias=['option2', 'old_name']),
    }

    class Config1(kwconf.Config):
        __default__ = __common_default__

    class Config3(kwconf.Config):
        __default__ = __common_default__

    config1 = Config1()
    config3 = Config3()

    config_instances = [config1, config3]

    for config in config_instances:
        assert config['opt1'] == config['option1'] and config['opt1'] is None
        config['opt1'] = 2
        assert config['opt1'] == config['option1'] == 2


def test_config_fuzzy_hyphens_default_on():
    """By default a Config accepts both "_" and "-" spellings on the CLI."""
    import kwconf

    class Default(kwconf.Config):
        out_dir = kwconf.Value('x')

    assert Default.cli(argv=['--out_dir=A']).out_dir == 'A'
    assert Default.cli(argv=['--out-dir=A']).out_dir == 'A'


def test_config_fuzzy_hyphens_optout():
    """``__fuzzy_hyphens__ = False`` disables "_"/"-" interchange on input.

    Regression test: previously the hyphen variant was still accepted on the
    input side even when the config opted out (it only stopped advertising the
    variant in ``--help``).
    """
    import pytest

    import kwconf

    class Strict(kwconf.Config):
        __fuzzy_hyphens__ = False
        out_dir = kwconf.Value('x')

    # The canonical underscore spelling still works.
    assert Strict.cli(argv=['--out_dir=A']).out_dir == 'A'
    # The hyphen spelling is now rejected rather than silently accepted.
    with pytest.raises(SystemExit):
        Strict.cli(argv=['--out-dir=A'], strict=True)


def test_config_schema_validation_is_opt_in(monkeypatch):
    import importlib

    import pytest

    import kwconf

    config_module = importlib.import_module('kwconf.config')

    def fail_if_called(*args, **kwargs):
        raise RuntimeError('schema validation ran')

    monkeypatch.setattr(
        config_module, '_validate_class_aliases', fail_if_called
    )

    class GoodConfig(kwconf.Config):
        value = 1

    # Neither class construction nor normal config / CLI construction performs
    # a schema scan. Projects opt into it explicitly in tests or CI.
    assert GoodConfig().value == 1
    assert GoodConfig.cli(argv=False).value == 1
    with pytest.raises(RuntimeError, match='schema validation ran'):
        GoodConfig.validate()


def test_config_validate_accepts_unambiguous_aliases():
    import kwconf

    class GoodConfig(kwconf.Config):
        output_path = kwconf.Value('out.txt', alias=['output'])
        workers = kwconf.Value(1, alias=['jobs'])

    assert GoodConfig.validate() is None


def test_alias_collision_with_canonical_field_rejected_by_validate():
    import pytest

    import kwconf

    class BadConfig(kwconf.Config):
        opt1 = kwconf.Value(1, alias=['opt2'])
        opt2 = kwconf.Value(2)

    with pytest.raises(ValueError, match="spelling 'opt2'.*'opt1'.*'opt2'"):
        BadConfig.validate()


def test_duplicate_alias_across_fields_rejected_by_validate():
    import pytest

    import kwconf

    class BadConfig(kwconf.Config):
        opt1 = kwconf.Value(1, alias=['shared'])
        opt2 = kwconf.Value(2, alias=['shared'])

    with pytest.raises(ValueError, match="spelling 'shared'.*'opt1'.*'opt2'"):
        BadConfig.validate()


def test_fuzzy_alias_collision_rejected_by_validate():
    import pytest

    import kwconf

    class BadConfig(kwconf.Config):
        __default__ = {
            'output_dir': kwconf.Value('a'),
            'other': kwconf.Value('b', alias=['output-dir']),
        }

    with pytest.raises(ValueError, match="spelling 'output-dir'"):
        BadConfig.validate()


def test_fuzzy_alias_collision_allowed_when_disabled():
    import kwconf

    class StrictConfig(kwconf.Config):
        __fuzzy_hyphens__ = False
        __default__ = {
            'output_dir': kwconf.Value('a'),
            'other': kwconf.Value('b', alias=['output-dir']),
        }

    assert StrictConfig.validate() is None
    config = StrictConfig(output_dir='canonical', **{'output-dir': 'alias'})
    assert config.output_dir == 'canonical'
    assert config.other == 'alias'


def test_inherited_alias_collision_rejected_by_validate():
    import pytest

    import kwconf

    class BaseConfig(kwconf.Config):
        original = kwconf.Value(1, alias=['future_name'])

    class BadSubclass(BaseConfig):
        future_name = kwconf.Value(2)

    with pytest.raises(ValueError, match="spelling 'future_name'"):
        BadSubclass.validate()
