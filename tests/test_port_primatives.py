"""Tests for port_to_argparse(kwconf_primatives=True): the 1-to-1 emission that
uses argparse_ext + our coerce (depends on kwconf), vs the lightweight default."""

import kwconf


class C(kwconf.Config):
    x: 'str | int | None' = None
    verbose: bool = kwconf.Value(False, isflag=True)


def test_primatives_emits_kwconf_imports_and_roundtrips():
    text = C().port_to_argparse(kwconf_primatives=True)
    assert 'from kwconf import argparse_ext' in text
    assert 'from kwconf import coerce as _kwconf_coerce' in text
    assert 'argparse_ext.BooleanFlagOrKeyValAction' in text
    assert '_kwconf_coerce.auto' in text
    ns = {}
    exec(text, ns, ns)
    parser = ns['parser']
    # union-aware, matching the live kwconf CLI
    assert vars(parser.parse_args(['--x=123']))['x'] == 123
    assert vars(parser.parse_args(['--x=foo']))['x'] == 'foo'
    assert vars(parser.parse_args(['--verbose']))['verbose'] is True


def test_lightweight_default_has_no_kwconf_dependency():
    text = C().port_to_argparse()
    assert 'from kwconf' not in text
    assert 'argparse_ext' not in text
    ns = {}
    exec(text, ns, ns)  # must run standalone (pure argparse)
    assert 'parser' in ns
