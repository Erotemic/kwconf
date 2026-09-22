"""Side-by-side argparse and kwconf implementations of the same CLI.

This is intentionally a normal-sized production-style command rather than a
synthetic hundreds-of-options stress test.  The two implementations expose the
same options and return the same ordinary ``dict`` shape.

Usage::

    python examples/09_argparse_comparison.py argparse --input images --workers 8
    python examples/09_argparse_comparison.py kwconf   --input images --workers 8

For an easy-to-see warm parsing comparison, repeat parsing in one process::

    python examples/09_argparse_comparison.py argparse --_repeat=20000 --_quiet
    python examples/09_argparse_comparison.py kwconf   --_repeat=20000 --_quiet

The control options prefixed with ``_`` are for the benchmark harness and are
removed before either CLI implementation sees argv.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any


SAMPLE_ARGV = [
    '--input',
    'images',
    '--output',
    'prepared',
    '--workers',
    '8',
    '--batch-size',
    '32',
    '--format',
    'webp',
    '--quality',
    '90',
    '--recursive',
    '--verify',
    '-vv',
]

_KWCONF_CONFIG = None


# REPORT_SNIPPET_ARGPARSE_START
def _get_argparse_parser():
    import argparse

    parser = argparse.ArgumentParser(
        description='Prepare a dataset for training.'
    )
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', default='prepared')
    parser.add_argument('--pattern', default='*.jpg')
    parser.add_argument(
        '--format', choices=['jpg', 'png', 'webp'], default='webp'
    )
    parser.add_argument('--quality', type=int, default=90)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--batch-size', type=int, default=32)
    parser.add_argument('--chunk-size', type=int, default=256)
    parser.add_argument('--width', type=int, default=1024)
    parser.add_argument('--height', type=int, default=1024)
    parser.add_argument(
        '--interpolation',
        choices=['nearest', 'linear', 'cubic'],
        default='linear',
    )
    parser.add_argument('--compression-level', type=int, default=6)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--timeout', type=float, default=30.0)
    parser.add_argument('--retries', type=int, default=2)
    parser.add_argument('--cache-dir', default='.cache/prepare')
    parser.add_argument('--manifest', default='manifest.json')
    parser.add_argument(
        '--hash-algorithm', choices=['sha1', 'sha256'], default='sha256'
    )
    parser.add_argument('--recursive', action='store_true')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--follow-symlinks', action='store_true')
    parser.add_argument('-v', '--verbose', action='count', default=0)
    return parser


# REPORT_SNIPPET_ARGPARSE_END


# REPORT_SNIPPET_KWCONF_START
def _get_kwconf_config():
    import kwconf

    class PrepareConfig(kwconf.Config):
        """Prepare a dataset for training."""

        input: str = kwconf.Value(None, required=True)
        output: str = 'prepared'
        pattern: str = '*.jpg'
        format: str = kwconf.Value('webp', choices=['jpg', 'png', 'webp'])
        quality: int = 90
        workers: int = 4
        batch_size: int = 32
        chunk_size: int = 256
        width: int = 1024
        height: int = 1024
        interpolation: str = kwconf.Value(
            'linear', choices=['nearest', 'linear', 'cubic']
        )
        compression_level: int = 6
        seed: int = 0
        timeout: float = 30.0
        retries: int = 2
        cache_dir: str = '.cache/prepare'
        manifest: str = 'manifest.json'
        hash_algorithm: str = kwconf.Value('sha256', choices=['sha1', 'sha256'])
        recursive = kwconf.Flag(False)
        verify = kwconf.Flag(False)
        overwrite = kwconf.Flag(False)
        dry_run = kwconf.Flag(False)
        follow_symlinks = kwconf.Flag(False)
        verbose: int = kwconf.Value(0, isflag='counter', short_alias='v')

    return PrepareConfig


# REPORT_SNIPPET_KWCONF_END


def parse_argparse(argv: list[str]) -> dict[str, Any]:
    # This is the conventional short-CLI shape: build the parser in main and
    # parse once.  Repeated benchmark calls therefore include argparse schema
    # construction, while the declarative kwconf class remains module state.
    return vars(_get_argparse_parser().parse_args(argv))


def parse_kwconf(argv: list[str]) -> dict[str, Any]:
    global _KWCONF_CONFIG
    if _KWCONF_CONFIG is None:
        _KWCONF_CONFIG = _get_kwconf_config()
    config = _KWCONF_CONFIG.cli(
        argv=argv, autocomplete=False, special_options=False
    )
    return config.to_dict()


def _pop_control_args(argv: list[str]) -> tuple[list[str], int, bool, bool]:
    repeat = 1
    quiet = False
    emit_json = False
    clean = []
    for arg in argv:
        if arg.startswith('--_repeat='):
            repeat = int(arg.split('=', 1)[1])
        elif arg == '--_quiet':
            quiet = True
        elif arg == '--_json':
            emit_json = True
        else:
            clean.append(arg)
    return clean, repeat, quiet, emit_json


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in {'argparse', 'kwconf'}:
        print(
            'usage: 09_argparse_comparison.py {argparse|kwconf} [options]',
            file=sys.stderr,
        )
        return 2
    backend = argv.pop(0)
    argv, repeat, quiet, emit_json = _pop_control_args(argv)
    if not argv:
        argv = list(SAMPLE_ARGV)

    parse = parse_argparse if backend == 'argparse' else parse_kwconf
    # A normal/default invocation parses exactly once.  Only repeated-throughput
    # mode warms one-time imports / kwconf schema compilation before timing the
    # requested loop count.  argparse intentionally retains its conventional
    # build-then-parse shape on every repeated call.
    if repeat > 1:
        result = parse(argv)
    else:
        result = None
    start = time.perf_counter_ns()
    for _ in range(repeat):
        result = parse(argv)
    elapsed_ns = time.perf_counter_ns() - start
    if result is None:
        # Preserve the historical repeat=0 control behavior without changing
        # the ordinary cold path, which always has repeat=1.
        result = parse(argv)

    if emit_json:
        print(
            json.dumps(
                {
                    'backend': backend,
                    'repeat': repeat,
                    'elapsed_ns': elapsed_ns,
                    'per_parse_ns': elapsed_ns / repeat,
                    'result': result,
                },
                sort_keys=True,
            )
        )
    elif not quiet:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
