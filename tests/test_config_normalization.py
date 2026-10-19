import pytest

import kwconf
from kwconf.value import _Value


def test_leaf_defaults_are_normalized():
    class LeafConfig(kwconf.Config):
        __default__ = {
            'alpha': 1,
            'beta': kwconf.Value(2),
        }

    # kwconf.Value is now a factory function; the runtime wrapper class is
    # kwconf.value._Value .
    assert isinstance(LeafConfig.__default__['alpha'], kwconf.value._Value)
    assert LeafConfig.__default__['alpha'].value == 1
    assert isinstance(LeafConfig.__default__['beta'], kwconf.value._Value)


def test_bool_defaults_become_flags():
    class BoolConfig(kwconf.Config):
        __default__: dict[str, object] = {
            'flag': False,
            'enabled': True,
        }

    # The metaclass replaces raw booleans with Value metadata.
    flag = BoolConfig.__default__['flag']
    enabled = BoolConfig.__default__['enabled']
    assert isinstance(flag, _Value) and flag.isflag is True
    assert isinstance(enabled, _Value) and enabled.isflag is True

    cfg = BoolConfig.cli(argv=['--flag'])
    assert cfg['flag'] is True

    cfg2 = BoolConfig.cli(argv=['--no-enabled'])
    assert cfg2['enabled'] is False


def test_subconfig_defaults_are_normalized():
    class Inner(kwconf.Config):
        __default__ = {'leaf': 1}

    class Outer(kwconf.Config):
        __default__ = {
            'inner_class': Inner,
            'inner_inst': Inner(),
            'inner_value': kwconf.Value(Inner, help='inner config'),
        }

    assert isinstance(Outer.__default__['inner_class'], kwconf.SubConfig)
    assert isinstance(Outer.__default__['inner_inst'], kwconf.SubConfig)
    assert isinstance(Outer.__default__['inner_value'], kwconf.SubConfig)
    assert Outer.__default__['inner_value'].help == 'inner config'


def test_selector_override_remains_available():
    class SGDConfig(kwconf.Config):
        lr = kwconf.Value(0.01, type=float)
        momentum = kwconf.Value(0.9, type=float)

    class AdamConfig(kwconf.Config):
        lr = kwconf.Value(0.001, type=float)
        beta1 = kwconf.Value(0.9, type=float)

    class TrainConfig(kwconf.Config):
        optim = kwconf.SubConfig(
            AdamConfig, choices={'adam': AdamConfig, 'sgd': SGDConfig}
        )
        epochs = kwconf.Value(10, type=int)

    cfg = TrainConfig.cli(
        argv=['--optim=sgd', '--optim.momentum=0.8'],
        allow_subconfig_overrides=True,
    )
    assert isinstance(cfg.optim, SGDConfig)
    assert cfg.optim.momentum == pytest.approx(0.8)
