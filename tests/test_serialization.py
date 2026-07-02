"""
Tests for Config serialization: __json__, dump/dumps.
"""

import pytest

import kwconf


def test_json_serializes_all_keys():
    """
    An item with a __json__ method must be converted in place; it must not
    truncate the rest of the config.
    """
    pytest.importorskip('ubelt')

    class Custom:
        def __json__(self):
            return {'inner': 1}

    class MyConfig(kwconf.Config):
        x = kwconf.Value(1)
        y = kwconf.Value(None)
        z = kwconf.Value('s')

    cfg = MyConfig()
    cfg['y'] = Custom()
    result = cfg.__json__()
    assert result == {'x': 1, 'y': {'inner': 1}, 'z': 's'}
