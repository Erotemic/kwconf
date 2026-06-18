# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
"""
Tests for the private argv-provenance snapshot ``_explicit_argv_keys``.

This records the canonical (possibly dotted) destinations that were explicitly
supplied on the command line for the most recent parse. It is intentionally
argv-scoped: it is *not* a general "was this key set by any source" flag.
"""
import copy
import kwconf


class Flat(kwconf.Config):
    __default__ = {'a': 10, 'b': 20}


class Inner(kwconf.Config):
    __default__ = {'x': 1, 'y': 2}


class Outer(kwconf.Config):
    __default__ = {'a': 10, 'inner': kwconf.SubConfig(Inner)}


def test_empty_when_not_from_cli():
    # Pure data/programmatic construction never touches argv.
    cfg = Flat()
    assert cfg._explicit_argv_keys == frozenset()
    cfg = Flat(a=99)
    assert cfg['a'] == 99
    assert cfg._explicit_argv_keys == frozenset()


def test_records_only_explicit_keys():
    cfg = Flat.cli(argv=['--a=99'])
    assert cfg['a'] == 99
    # b was left at its default and must not appear.
    assert cfg._explicit_argv_keys == frozenset({'a'})


def test_default_valued_explicit_key_is_recorded():
    # Even when the user supplies a value equal to the default, the key counts
    # as explicit -- this is the case that cannot be recovered by comparing
    # values.
    cfg = Flat.cli(argv=['--a=10'])
    assert cfg['a'] == 10
    assert 'a' in cfg._explicit_argv_keys


def test_subconfig_dotted_key_distribution():
    cfg = Outer.cli(argv=['--a=99', '--inner.x=5'])
    assert cfg._explicit_argv_keys == frozenset({'a', 'inner.x'})
    # The child carries the prefix-stripped key.
    child = cfg._data['inner']
    assert child._explicit_argv_keys == frozenset({'x'})


def test_subconfig_class_swap_lands_on_final_instance():
    class Fast(kwconf.Config):
        __default__ = {'speed': 100}

    class Slow(kwconf.Config):
        __default__ = {'speed': 1}

    class App(kwconf.Config):
        __default__ = {
            'engine': kwconf.SubConfig(Fast, choices={'fast': Fast, 'slow': Slow})
        }

    cfg = App.cli(argv=['--engine.__class__=slow', '--engine.speed=7'])
    assert isinstance(cfg['engine'], Slow)
    assert cfg['engine']['speed'] == 7
    # Provenance must land on the surviving (swapped-in) instance.
    child = cfg._data['engine']
    assert cfg['engine'] is child
    assert child._explicit_argv_keys == frozenset({'__class__', 'speed'})
    assert cfg._explicit_argv_keys == frozenset({'engine.__class__', 'engine.speed'})


def test_deepcopy_carries_provenance():
    cfg = Outer.cli(argv=['--a=99', '--inner.x=5'])
    dup = copy.deepcopy(cfg)
    assert dup._explicit_argv_keys == frozenset({'a', 'inner.x'})
    assert dup._data['inner']._explicit_argv_keys == frozenset({'x'})


def test_shallow_copy_carries_provenance():
    cfg = Outer.cli(argv=['--a=99', '--inner.x=5'])
    dup = copy.copy(cfg)
    assert dup._explicit_argv_keys == frozenset({'a', 'inner.x'})


def test_dump_excludes_provenance():
    cfg = Flat.cli(argv=['--a=99'])
    text = cfg.dumps()
    assert '_explicit_argv_keys' not in text


def test_setitem_does_not_populate_provenance():
    # Post-construction mutation must not retroactively rewrite argv history.
    cfg = Flat.cli(argv=['--a=99'])
    cfg['b'] = 123
    assert cfg._explicit_argv_keys == frozenset({'a'})
