
def test_config_aliases():
    import kwconf
    import pytest
    # import ubelt as ub

    __common_default__ = {
        'opt1': kwconf.Value(None, alias=['option1']),
        'opt2': kwconf.Value(None, alias=['option2', 'old_name']),
    }

    class Config1(kwconf.Config):
        __default__ = __common_default__

    with pytest.warns(Warning):
        class Config2(kwconf.Config):
            default = __common_default__

    class Config3(kwconf.DataConfig):
        __default__ = __common_default__

    config1 = Config1()
    config2 = Config2()
    config3 = Config3()

    config_instances = [config1, config2, config3]

    for config in config_instances:
        assert config['opt1'] == config['option1'] and config['opt1'] is None
        config['opt1'] = 2
        assert config['opt1'] == config['option1'] == 2
