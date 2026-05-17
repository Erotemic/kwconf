"""
Command-line surface area.

This example demonstrates the CLI conveniences kwconf keeps: positional
arguments, aliases, fuzzy hyphen names, booleans, counters, choices, and nargs.
"""

import _bootstrap  # noqa: F401
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
    summary = summarize(config)
    print(summary)
    return summary


def demo():
    config = ConvertConfig.cli(argv=[
        'raw.dat',
        'clean.dat',
        '-vvv',
        '-j', '4',
        '--dry-run',
        '--mode=safe',
        '--include', 'metadata', 'features',
    ])
    assert config.src == 'raw.dat'
    assert config.dst == 'clean.dat'
    assert config.verbose == 3
    assert config.workers == 4
    assert config.dry_run is True
    assert config.include == ['metadata', 'features']

    # Fuzzy hyphens mean `dry_run` can be spelled `--dry-run`.
    config2 = ConvertConfig.cli(argv=['a', 'b', '--no-dry-run'])
    assert config2.dry_run is False
    print('02_cli_surface: ok')


if __name__ == '__main__':
    main()
