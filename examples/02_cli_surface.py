"""
Command-line surface area.

This example demonstrates the CLI conveniences kwconf keeps: positional
arguments, aliases, fuzzy hyphen names, booleans, counters, choices, and nargs.
The script prints the resolved config and the concrete Python types produced by
CLI coercion.

DEMO:
    Command::

        python examples/02_cli_surface.py raw.dat clean.dat -vvv -j 4 --dry-run --mode=safe --include metadata features

    Expected output::

        RESOLVED CONFIG:
        src: raw.dat
        dst: clean.dat
        workers: 4
        mode: safe
        include:
        - metadata
        - features
        verbose: 3
        dry_run: true
        RESOLVED TYPES:
        __class__: ConvertConfig
        src: str
        dst: str
        workers: int
        mode: str
        include:
          list_of: str
        verbose: int
        dry_run: bool
        SUMMARY:
        {'src': 'raw.dat', 'dst': 'clean.dat', 'workers': 4, 'mode': 'safe', 'include': ['metadata', 'features'], 'verbose': 3, 'dry_run': True}
"""

import _bootstrap  # noqa: F401
from _bootstrap import print_resolved_config
import kwconf as kw


class ConvertConfig(kw.Config):
    __description__ = 'Convert one input file into one output file.'
    __fuzzy_hyphens__ = True

    src: str = kw.Value('input.txt', position=1, help='input file')
    dst: str = kw.Value('output.txt', position=2, help='output file')
    workers: int = kw.Value(1, short_alias=['j'], help='worker count')
    mode: str = kw.Value('fast', choices=['fast', 'safe'], help='conversion mode')
    include: list = kw.Value(default_factory=list, nargs='*', help='named sections')
    verbose = kw.Value(0, short_alias=['v'], isflag='counter', help='verbosity')
    dry_run = kw.Flag(False, alias=['dryrun'], help='do not write outputs')


def summarize(config):
    return {
        'src': config.src,
        'dst': config.dst,
        'workers': config.workers,
        'mode': config.mode,
        'include': list(config.include),
        'verbose': config.verbose,
        'dry_run': config.dry_run,
    }


def main(argv=None):
    config = ConvertConfig.cli(argv=argv)
    print_resolved_config(config)
    summary = summarize(config)
    print('SUMMARY:')
    print(summary)
    return config


if __name__ == '__main__':
    main()
