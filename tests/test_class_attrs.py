# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
"""
Test that class attributes are correctly initialized.
"""


def test_class_inst_default_attr():
    """
    kwconf.Config should now support the same declarative class-variable style
    as Config.
    """
    import kwconf

    class Config1(kwconf.Config):
        option1: tuple = kwconf.Value((1, 2, 3), tuple, alias='a')
        option2: str = 'bar'
        option3 = None

    class Config2(kwconf.Config):
        __default__ = {
            'option1': kwconf.Value((1, 2, 3), tuple, alias='a'),
            'option2': 'bar',
            'option3': None,
        }

    class Config3(kwconf.Config):
        option1: tuple = kwconf.Value((1, 2, 3), tuple, alias='a')
        option2: str = 'bar'
        option3 = None

    config1 = Config1()
    config2 = Config2()
    config3 = Config3()

    a = config1.to_dict()
    b = config2.to_dict()
    c = config3.to_dict()
    assert a == b == c

    config_instances = [config1, config2, config3]

    import ubelt as ub

    for config in config_instances:
        defaults = ub.udict(
            {
                'self._default': config._default,
                'self.__default__': config.__default__,
                'cls.__default__': config.__class__.__default__,
            }
        )
        default_ids = defaults.map_values(id)
        print('default_ids = {}'.format(ub.urepr(default_ids, nl=1, align=':')))
        assert default_ids['self._default'] != default_ids['self.__default__']


def test_class_inst_post_init_attr():
    """
    The __post_init__ method runs after construction.
    """
    import kwconf
    import ubelt as ub

    test_state = ub.ddict(lambda: 0)

    common_default = {
        'opt1': kwconf.Value(None, alias=['option1']),
        'opt2': kwconf.Value(None, alias=['option2', 'old_name']),
    }

    class Config1(kwconf.Config):
        __default__ = common_default

        def __post_init__(self):
            test_state[self.__class__.__name__ + '.__post_init__'] += 1
            self['opt1'] = 'post-initialized'

    class Config2(kwconf.Config):
        __default__ = common_default

        def __post_init__(self):
            test_state[self.__class__.__name__ + '.__post_init__'] += 1
            self['opt1'] = 'post-initialized'

    instances = {cls.__name__: cls() for cls in [Config1, Config2]}
    assert len(instances) == len(test_state) == 2
    assert all(v == 1 for v in test_state.values())
    assert instances['Config1']['opt1'] == 'post-initialized'
    assert instances['Config2']['opt1'] == 'post-initialized'
