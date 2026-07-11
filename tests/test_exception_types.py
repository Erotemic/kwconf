import argparse

import pytest

import kwconf
from kwconf.argparse_ext import (
    BooleanFlagOrKeyValAction,
    CounterOrKeyValAction,
)


def test_unknown_mapping_key_raises_keyerror():
    class Demo(kwconf.Config):
        value = 1

    cfg = Demo()
    with pytest.raises(KeyError, match='Cannot add keys'):
        cfg['unknown'] = 2


def test_boolean_flag_action_rejects_positional_use_with_typeerror():
    parser = argparse.ArgumentParser()
    parser.add_argument('flag', action=BooleanFlagOrKeyValAction)
    with pytest.raises(TypeError, match='positional argument'):
        parser.parse_args(['true'])


def test_counter_action_rejects_positional_use_with_typeerror():
    parser = argparse.ArgumentParser()
    parser.add_argument('count', action=CounterOrKeyValAction)
    with pytest.raises(TypeError, match='positional argument'):
        parser.parse_args(['1'])


def test_removed_orig_export_style_raises_notimplementederror():
    cfg = kwconf.Config.demo()
    with pytest.raises(NotImplementedError, match="style='orig'"):
        cfg.port_to_config(style='orig')
