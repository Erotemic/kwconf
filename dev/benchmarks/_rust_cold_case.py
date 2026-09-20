#!/usr/bin/env python3
"""One-shot process workload for rust_cli_runtime.py; not a standalone bench."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_DPATH = Path(__file__).resolve().parents[2]
if str(REPO_DPATH) not in sys.path:
    sys.path.insert(0, str(REPO_DPATH))


def main() -> None:
    method = sys.argv[1]
    size = int(sys.argv[2])
    argv_size = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    if not 0 <= argv_size <= size:
        raise SystemExit(f'argv_size must satisfy 0 <= argv_size <= {size}')
    argv = [f'--option_{idx}=value{idx}' for idx in range(argv_size)]
    typed = method.endswith('_typed')
    base_method = method.removesuffix('_typed')
    if base_method == 'argparse':
        import argparse

        parser = argparse.ArgumentParser(add_help=False)
        for idx in range(size):
            parser.add_argument(
                f'--option_{idx}',
                f'--option-{idx}',
                dest=f'option_{idx}',
                default='' if typed else None,
                type=str,
            )
        result = parser.parse_args(argv)
        if argv_size:
            assert result.option_0 == 'value0'
        return

    import kwconf

    backend = {
        'kwconf_python': 'python',
        'kwconf_rust': 'rust',
        'kwconf_auto': 'auto',
    }[base_method]
    if typed:
        names = [f'option_{idx}' for idx in range(size)]
        namespace = {
            '__annotations__': {name: str for name in names},
            '__cli_backend__': backend,
        }
        namespace.update({name: '' for name in names})
    else:
        namespace = {
            '__default__': {
                f'option_{idx}': kwconf.Value(None, parser=str)
                for idx in range(size)
            },
            '__cli_backend__': backend,
        }
    cls = type(
        f'ColdConfig{size}',
        (kwconf.Config,),
        namespace,
    )
    result = cls.cli(
        argv=argv,
        autocomplete=False,
        special_options=False,
    )
    if argv_size:
        assert result['option_0'] == 'value0'


if __name__ == '__main__':
    main()
