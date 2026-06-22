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
