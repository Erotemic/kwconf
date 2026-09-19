import pytest

import kwconf


def test_value_bare_long_and_short_forms():
    class PatchConfig(kwconf.Config):
        patch = kwconf.Value(None, bare='auto', short_alias=['p'])
        repo = kwconf.Value(None, position=1)

    assert PatchConfig.cli(argv=[]).patch is None
    assert PatchConfig.cli(argv=['--patch']).patch == 'auto'
    assert PatchConfig.cli(argv=['--patch=base.tar']).patch == 'base.tar'
    assert PatchConfig.cli(argv=['--patch', 'base.tar']).patch == 'base.tar'
    assert PatchConfig.cli(argv=['-p']).patch == 'auto'
    assert PatchConfig.cli(argv=['-p=base.tar']).patch == 'base.tar'
    assert PatchConfig.cli(argv=['-p', 'base.tar']).patch == 'base.tar'

    # A kwconf key may consume a following token as its explicit value. Use
    # the standard ``--`` separator when the option is intended to stay bare
    # and the following token is positional.
    cfg = PatchConfig.cli(argv=['-p', '--', '.'])
    assert cfg.patch == 'auto'
    assert cfg.repo == '.'

    cfg = PatchConfig.cli(argv=['-p', '.'])
    assert cfg.patch == '.'
    assert cfg.repo is None


def test_bare_can_be_falsy_and_implies_optional_value_grammar():
    class BareConfig(kwconf.Config):
        none_value = kwconf.Value('default', bare=None)
        false_value = kwconf.Value('default', bare=False)
        zero_value = kwconf.Value('default', bare=0)

    parser = BareConfig().argparse()
    by_dest = {action.dest: action for action in parser._actions}
    assert by_dest['none_value'].nargs == '?'
    assert by_dest['none_value'].const is None
    assert by_dest['false_value'].nargs == '?'
    assert by_dest['false_value'].const is False
    assert by_dest['zero_value'].nargs == '?'
    assert by_dest['zero_value'].const == 0

    cfg = BareConfig.cli(
        argv=['--none_value', '--false_value', '--zero_value']
    )
    assert cfg.none_value is None
    assert cfg.false_value is False
    assert cfg.zero_value == 0


def test_bare_rejects_conflicting_field_modes():
    with pytest.raises(ValueError, match='non-flag values'):
        kwconf.Value(False, bare=True, isflag=True)
    with pytest.raises(ValueError, match="implies nargs='\\?'"):
        kwconf.Value(None, bare='auto', nargs='+')


def test_bare_short_alias_clusters_and_required_value_tail():
    class ClusterConfig(kwconf.Config):
        patch = kwconf.Value(None, bare='auto', short_alias=['p'])
        verbose = kwconf.Value(0, isflag='counter', short_alias=['v'])
        force = kwconf.Flag(False, short_alias=['f'])
        debug = kwconf.Flag(False, short_alias=['d'])
        key = kwconf.Value(None, short_alias=['k'])

    cases = {
        ('-pv',): dict(patch='auto', verbose=1),
        ('-vp',): dict(patch='auto', verbose=1),
        ('-vvp',): dict(patch='auto', verbose=2),
        ('-vfd',): dict(verbose=1, force=True, debug=True),
        ('-vvv',): dict(verbose=3),
        ('-vvv=5',): dict(verbose=5),
        ('-vf=false',): dict(verbose=1, force=False),
        ('-vkfoo',): dict(verbose=1, key='foo'),
        ('-vk=foo',): dict(verbose=1, key='foo'),
        ('-kfoo',): dict(key='foo'),
    }
    for argv, expected in cases.items():
        cfg = ClusterConfig.cli(argv=list(argv))
        for key, want in expected.items():
            assert getattr(cfg, key) == want, (argv, cfg.asdict())


def test_bare_short_alias_never_uses_undelimited_attached_value():
    class ClusterConfig(kwconf.Config):
        force = kwconf.Flag(False, short_alias=['f'])
        verbose = kwconf.Value(0, isflag='counter', short_alias=['v'])
        patch = kwconf.Value(None, bare='auto', short_alias=['p'])

    parser = ClusterConfig().argparse()

    # These used to fall through to argparse's nargs='?' interpretation. In
    # kwconf's default grammar they are invalid compact clusters, not attached
    # explicit values. parse_known_args must preserve the original token.
    for token in ['-ffalse', '-v3', '-parchive.tar']:
        ns, unknown = parser.parse_known_args([token])
        assert unknown == [token]
        assert ns.force is False
        assert ns.verbose == 0
        assert ns.patch is None

    # Explicit values remain available with a delimiter or separate token.
    assert ClusterConfig.cli(argv=['-f=false']).force is False
    assert ClusterConfig.cli(argv=['-f', 'false']).force is False
    assert ClusterConfig.cli(argv=['-v=3']).verbose == 3
    assert ClusterConfig.cli(argv=['-v', '3']).verbose == 3
    assert ClusterConfig.cli(argv=['-p=archive.tar']).patch == 'archive.tar'
    assert ClusterConfig.cli(argv=['-p', 'archive.tar']).patch == 'archive.tar'


def test_short_alias_cluster_extension_can_be_disabled():
    class StrictArgparseConfig(kwconf.Config):
        __short_alias_clusters__ = False
        force = kwconf.Flag(False, short_alias=['f'])
        verbose = kwconf.Value(0, isflag='counter', short_alias=['v'])
        patch = kwconf.Value(None, bare='auto', short_alias=['p'])

    # With the kwconf lexical extension disabled, compact tokens are delegated
    # to argparse's native nargs='?' interpretation.
    cfg = StrictArgparseConfig.cli(argv=['-fv'])
    assert cfg.force == 'v'
    assert cfg.verbose == 0

    cfg = StrictArgparseConfig.cli(argv=['-pbase.tar'])
    assert cfg.patch == 'base.tar'

    # The same opt-out is available per parser construction.
    parser = StrictArgparseConfig().argparse(short_alias_clusters=True)
    # A class-level opt-out cannot be re-enabled by a parent / per-call opt-in,
    # mirroring fuzzy_hyphens subtree semantics.
    ns = parser.parse_args(['-fv'])
    assert ns.force == 'v'

    class DefaultConfig(kwconf.Config):
        force = kwconf.Flag(False, short_alias=['f'])
        verbose = kwconf.Value(0, isflag='counter', short_alias=['v'])

    parser = DefaultConfig().argparse(short_alias_clusters=False)
    ns = parser.parse_args(['-fv'])
    assert ns.force == 'v'
    assert ns.verbose == 0


def test_bare_metadata_roundtrips_to_config_source():
    class BareConfig(kwconf.Config):
        patch = kwconf.Value(None, bare='auto', short_alias=['p'])

    text = BareConfig().port_to_config()
    assert "bare='auto'" in text


def test_argparse_optional_value_ports_to_bare():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--patch', nargs='?', const='auto', default=None)

    text = kwconf.Config.port_from_argparse(parser)
    assert "bare='auto'" in text
    assert "nargs='?'" not in text

    DynamicConfig = kwconf.Config.cls_from_argparse(parser)
    field = DynamicConfig.__default__['patch']
    assert field.bare == 'auto'
    assert field.parsekw.get('nargs') is None
