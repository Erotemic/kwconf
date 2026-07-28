import argparse

import pytest

import kwconf
from kwconf.subconfig import expand_multipass_parser, wrap_subconfig_defaults


class Adam(kwconf.Config):
    lr = 0.001


class SGD(kwconf.Config):
    momentum = 0.9


class Train(kwconf.Config):
    optim = kwconf.SubConfig(Adam, choices={'adam': Adam, 'sgd': SGD})


def _fresh_train():
    cfg = Train(_dont_call_post_init=True)
    wrap_subconfig_defaults(cfg, _dont_call_post_init=True)
    return cfg


def test_expand_multipass_preserves_parser_identity_and_custom_options():
    cfg = _fresh_train()
    parser = argparse.ArgumentParser(prog='custom')
    parser.add_argument('--sentinel')

    result, argv = expand_multipass_parser(
        cfg,
        parser,
        argv=['--sentinel=kept', '--optim=sgd', '--optim.momentum=0.7'],
        allow_subconfig_overrides=True,
    )

    assert result is parser
    assert argv == [
        '--sentinel=kept',
        '--optim=sgd',
        '--optim.momentum=0.7',
    ]
    namespace = parser.parse_args(argv)
    assert namespace.sentinel == 'kept'
    assert namespace.optim == 'sgd'
    assert namespace.__dict__['optim.momentum'] == 0.7


def test_expand_multipass_preserves_parser_on_static_path():
    cfg = _fresh_train()
    parser = argparse.ArgumentParser(prog='custom')
    parser.add_argument('--sentinel')

    result, argv = expand_multipass_parser(
        cfg,
        parser,
        argv=['--sentinel=kept', '--optim.lr=0.2'],
        allow_subconfig_overrides=False,
    )

    assert result is parser
    namespace = parser.parse_args(argv)
    assert namespace.sentinel == 'kept'
    assert namespace.__dict__['optim.lr'] == 0.2
    with pytest.raises(SystemExit):
        parser.parse_args(['--optim=sgd'])


def test_cli_multipass_still_realizes_selected_variant():
    cfg = Train.cli(
        argv=['--optim=sgd', '--optim.momentum=0.7'],
        allow_subconfig_overrides=True,
    )
    assert isinstance(cfg.optim, SGD)
    assert cfg.optim.momentum == 0.7
