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
