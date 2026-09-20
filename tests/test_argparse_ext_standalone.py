"""
Guardrail: ``kwconf.argparse_ext`` must stay a small, portable layer that does
NOT import from the rest of kwconf. This keeps it usable standalone (a parser
ported to pure argparse can rely on argparse_ext without dragging in kwconf).
"""

import ast
import pathlib

import kwconf.argparse_ext


def test_argparse_ext_does_not_import_kwconf():
    src = pathlib.Path(kwconf.argparse_ext.__file__).read_text()
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ''
            # node.level > 0 is a relative import (from . / from .. ...)
            if (
                node.level > 0
                or module == 'kwconf'
                or module.startswith('kwconf.')
            ):
                dots = '.' * node.level
                offenders.append(f'from {dots}{module} import ...')
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == 'kwconf' or alias.name.startswith('kwconf.'):
                    offenders.append(f'import {alias.name}')
    assert not offenders, (
        'kwconf.argparse_ext must not import kwconf; found: ' + repr(offenders)
    )


def test_deepest_subparser_skips_leading_options():
    """
    Provenance must survive a root-level option (or ``--``) appearing before
    the subcommand token; otherwise the walk collapses to the root parser and
    drops the subcommand's explicit keys.
    """
    from kwconf.argparse_ext import ExtendedArgumentParser, parse_known_result

    parser = ExtendedArgumentParser(prog='app')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--level')
    sub = parser.add_subparsers()
    child = sub.add_parser('run')
    child.add_argument('--opt')

    # selected_parser drives provenance (explicit_keys reads its
    # _explicitly_given); the walk must reach the child in every case.

    # Bare subcommand: baseline.
    assert (
        parse_known_result(parser, args=['run', '--opt=1']).selected_parser
        is child
    )
    # Store-true option before the command.
    assert (
        parse_known_result(
            parser, args=['--verbose', 'run', '--opt=1']
        ).selected_parser
        is child
    )
    # Value option (separate token) before the command.
    assert (
        parse_known_result(
            parser, args=['--level', 'hi', 'run', '--opt=1']
        ).selected_parser
        is child
    )
    # End-of-options separator before the command.
    assert (
        parse_known_result(
            parser, args=['--', 'run', '--opt=1']
        ).selected_parser
        is child
    )


def test_separator_before_subcommand_is_consumed():
    """
    ``--`` in front of a subcommand belongs to the parser, not to the
    subparsers action. CPython only learned this in 3.13 (and late 3.12 patch
    releases), so kwconf backports it to keep every supported version honest.
    """
    from kwconf.argparse_ext import ExtendedArgumentParser

    parser = ExtendedArgumentParser(prog='app')
    sub = parser.add_subparsers(dest='command')
    child = sub.add_parser('run')
    child.add_argument('--opt')

    ns = parser.parse_args(['--', 'run', '--opt=1'])
    assert vars(ns) == {'command': 'run', 'opt': '1'}

    # The separator is only stripped once: it still shields later tokens that
    # the subcommand itself wants to read positionally.
    child.add_argument('rest', nargs='*')
    ns = parser.parse_args(['--', 'run', '--', '--opt=1'])
    assert ns.opt is None
    assert ns.rest == ['--opt=1']


def test_unrecognized_arguments_respect_exit_on_error():
    """
    With ``exit_on_error=False`` an unrecognized argument must surface as an
    ``ArgumentError`` rather than a ``SystemExit`` (stdlib behavior from 3.13
    onward, backported for older versions).
    """
    import argparse

    import pytest

    from kwconf.argparse_ext import (
        CompatArgumentParser,
        ExtendedArgumentParser,
    )

    for cls in (CompatArgumentParser, ExtendedArgumentParser):
        parser = cls(prog='app', exit_on_error=False)
        parser.add_argument('--known')
        with pytest.raises(argparse.ArgumentError) as ctx:
            parser.parse_args(['--unknown=1'])
        assert 'unrecognized arguments: --unknown=1' in str(ctx.value)

    # The default policy still exits.
    parser = ExtendedArgumentParser(prog='app')
    parser.add_argument('--known')
    with pytest.raises(SystemExit):
        parser.parse_args(['--unknown=1'])


def test_fuzzy_hyphens_independent_of_allow_abbrev():
    """
    Underscore/hyphen interchange (fuzzy hyphens) is an exact-normalized
    match and must work regardless of allow_abbrev; only prefix abbreviation
    is gated by allow_abbrev.
    """
    from kwconf.argparse_ext import ExtendedArgumentParser

    for allow_abbrev in (True, False):
        parser = ExtendedArgumentParser(allow_abbrev=allow_abbrev)
        parser.add_argument('--my-option', default='d')
        ns = parser.parse_known_args(['--my_option=hello'])[0]
        assert ns.my_option == 'hello', (allow_abbrev, ns)

    # Abbreviation, by contrast, follows allow_abbrev.
    parser = ExtendedArgumentParser(allow_abbrev=False)
    parser.add_argument('--my-option', default='d')
    _, unknown = parser.parse_known_args(['--my=x'])
    assert '--my=x' in unknown


def test_short_optional_value_clusters_are_lexically_normalized():
    """The parser, not the action, owns kwconf's compact short grammar."""
    from kwconf.argparse_ext import ExtendedArgumentParser

    parser = ExtendedArgumentParser(exit_on_error=False)
    parser.add_argument('-f', nargs='?', const='bare-f')
    parser.add_argument('-v', nargs='?', const='bare-v')
    parser.add_argument('-k')

    ns, unknown = parser.parse_known_args(['-fv'])
    assert vars(ns) == {'f': 'bare-f', 'v': 'bare-v', 'k': None}
    assert unknown == []

    ns, unknown = parser.parse_known_args(['-vkfoo'])
    assert vars(ns) == {'f': None, 'v': 'bare-v', 'k': 'foo'}
    assert unknown == []

    # A bare-capable short alias cannot fall back to -fVALUE when the suffix
    # is not a valid cluster.
    ns, unknown = parser.parse_known_args(['-f3'])
    assert ns.f is None
    assert unknown == ['-f3']

    parser._kwconf_short_alias_clusters = False
    ns, unknown = parser.parse_known_args(['-fv'])
    assert ns.f == 'v'
    assert ns.v is None
    assert unknown == []


def test_fuzzy_option_index_is_reused_and_invalidated_by_schema_growth():
    """Fuzzy spelling lookup should be cached across parses, but stay fresh."""
    from kwconf import argparse_ext

    parser = argparse_ext.ExtendedArgumentParser(allow_abbrev=False)
    parser.add_argument('--alpha-beta')

    got = argparse_ext._normalize_fuzzy_option_tokens(
        parser, ['--alpha_beta=value']
    )
    assert got == ['--alpha-beta=value']
    first_cache = parser._kwconf_fuzzy_option_index

    got = argparse_ext._normalize_fuzzy_option_tokens(
        parser, ['--alpha_beta=other']
    )
    assert got == ['--alpha-beta=other']
    assert parser._kwconf_fuzzy_option_index is first_cache

    # Parser schemas are normally built before parsing, but argparse permits
    # later additions. The cache must notice those without requiring callers to
    # manually invalidate kwconf internals.
    parser.add_argument('--gamma-delta')
    got = argparse_ext._normalize_fuzzy_option_tokens(
        parser, ['--gamma_delta=value']
    )
    assert got == ['--gamma-delta=value']
    assert parser._kwconf_fuzzy_option_index is not first_cache
