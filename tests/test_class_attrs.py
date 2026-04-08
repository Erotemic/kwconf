"""
Test that class attributes are correctly initialized.
"""


def test_class_inst_default_attr():
    """
    kwconf.DataConfig should now support the same declarative class-variable style
    as DataConfig.
    """
    import kwconf

    class Config1(kwconf.DataConfig):
        option1: tuple = kwconf.Value((1, 2, 3), tuple, alias='a')
        option2: str = 'bar'
        option3 = None

    class Config2(kwconf.DataConfig):
        __default__ = {
            'option1': kwconf.Value((1, 2, 3), tuple, alias='a'),
            'option2': 'bar',
            'option3': None,
        }

    class DataConfig3(kwconf.DataConfig):
        option1: tuple = kwconf.Value((1, 2, 3), tuple, alias='a')
        option2: str = 'bar'
        option3 = None

    config1 = Config1()
    config2 = Config2()
    config3 = DataConfig3()

    a = config1.to_dict()
    b = config2.to_dict()
    c = config3.to_dict()
    assert a == b == c

    config_instances = [config1, config2, config3]

    import ubelt as ub
    for config in config_instances:
        defaults = ub.udict({
            'self._default': config._default,
            'self.__default__': config.__default__,
            'cls.__default__': config.__class__.__default__,
        })
        default_ids = defaults.map_values(id)
        print('default_ids = {}'.format(ub.urepr(default_ids, nl=1, align=':')))
        assert default_ids['self._default'] != default_ids['self.__default__']


def test_class_inst_normalize_attr():
    """
    The normalize and __post_init__ methods should function equivalently
    """
    import kwconf
    import ubelt as ub
    import pytest

    test_state = ub.ddict(lambda: 0)

    config_classes = []

    common_default = {
        'opt1': kwconf.Value(None, alias=['option1']),
        'opt2': kwconf.Value(None, alias=['option2', 'old_name']),
    }

    with pytest.warns(Warning):
        @config_classes.append
        class Config1A(kwconf.DataConfig):
            __default__ = common_default
            def normalize(self):
                test_state[self.__class__.__name__ + '.normalize'] += 1
                self['opt1'] = 'normalized'

    @config_classes.append
    class Config1B(kwconf.DataConfig):
        __default__ = common_default
        def __post_init__(self):
            test_state[self.__class__.__name__ + '.__post_init__'] += 1
            self['opt1'] = 'post-initialized'

    @config_classes.append
    class Config1C(kwconf.DataConfig):
        __default__ = common_default

        def __post_init__(self):
            test_state[self.__class__.__name__ + '.__post_init__'] += 1
            self['opt1'] = 'post-initialized'

        def normalize(self):
            test_state[self.__class__.__name__ + '.normalize'] += 1
            self['opt1'] = 'normalized'

    with pytest.warns(Warning):
        @config_classes.append
        class DataConfig2A(kwconf.DataConfig):
            __default__ = common_default
            def normalize(self):
                test_state[self.__class__.__name__ + '.normalize'] += 1
                self['opt1'] = 'normalized'

    @config_classes.append
    class DataConfig2B(kwconf.DataConfig):
        __default__ = common_default
        def __post_init__(self):
            test_state[self.__class__.__name__ + '.__post_init__'] += 1
            self['opt1'] = 'post-initialized'

    @config_classes.append
    class DataConfig2C(kwconf.DataConfig):
        __default__ = common_default

        def __post_init__(self):
            test_state[self.__class__.__name__ + '.__post_init__'] += 1
            self['opt1'] = 'post-initialized'

        def normalize(self):
            test_state[self.__class__.__name__ + '.normalize'] += 1
            self['opt1'] = 'normalized'

    instances = {}
    for cls in config_classes:
        instances[cls.__name__] = cls()

    assert len(instances) == len(test_state) == 6
    assert all(v == 1 for v in test_state.values()), (
        'Only normalize or __post_init__ should be called, depending on '
        'which one is defined.'
    )

    # post-init should be used over normalize when available
    assert instances['Config1A']['opt1'] == 'normalized'
    assert instances['Config1B']['opt1'] == 'post-initialized'
    assert instances['Config1C']['opt1'] == 'post-initialized'
    assert instances['DataConfig2A']['opt1'] == 'normalized'
    assert instances['DataConfig2B']['opt1'] == 'post-initialized'
    assert instances['DataConfig2C']['opt1'] == 'post-initialized'
