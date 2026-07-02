"""
Tests for Config serialization: __json__, dump/dumps.
"""

import pytest

import kwconf


def test_dump_does_not_mutate_global_yaml_state():
    """
    dump()/dumps() must not register representers on the shared
    yaml.SafeDumper: that would change unrelated yaml.safe_dump calls in the
    same process.
    """
    yaml = pytest.importorskip('yaml')

    class MyConfig(kwconf.Config):
        b = 2
        a = 1

    before = dict(yaml.SafeDumper.yaml_representers)
    text = MyConfig().dumps(mode='yaml')
    after = dict(yaml.SafeDumper.yaml_representers)

    # Output preserves declaration order (the point of the representer).
    assert text.index('b:') < text.index('a:')
    # ... but the global SafeDumper registry is untouched.
    assert before == after


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
