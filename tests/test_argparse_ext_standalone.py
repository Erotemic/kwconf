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
