"""
Modal CLIs: one application, multiple subcommands -- with fuzzy hyphens.

A ModalCLI routes the first positional command to a Config-backed command (or to
a nested submodal). Each command still gets normal Config.cli parsing, and each
command prints resolved config fields as ``name : type = value`` rows.

This example focuses on **fuzzy hyphens**: spelling names with hyphens or
underscores interchangeably. This is **on by default** -- you do not set
anything to get it. It works at every level:

* root command names         ``run_train``   <-> ``run-train``
* root command aliases       ``fit_model``   <-> ``fit-model``
* submodal command names     ``data_tools``  <-> ``data-tools``
* nested command names       ``export_data`` <-> ``export-data``
* leaf option flags          ``--out_dir``   <-> ``--out-dir``

Fuzziness is **per-object**: each ModalCLI / Config decides how *it* behaves,
never how its children behave. Set ``__fuzzy_hyphens__ = False`` to opt out.
``LegacyTools`` opts out for its own command names, and ``StrictReport`` opts out
for its own option flags -- both stay strict even though the root modal that
reaches them is fuzzy.

Run the script with no arguments to execute a self-check that proves every level
above resolves identically under underscores and hyphens.

DEMO:
    Commands::

        # Prove fuzzy hyphens across modal + submodal levels (asserts equivalence):
        python examples/05_modal_cli.py

        # Normal dispatch, hyphenated spellings of underscore names:
        python examples/05_modal_cli.py run-train --max-epochs=3 --dry-run
        python examples/05_modal_cli.py fit-model --max_epochs=2
        python examples/05_modal_cli.py data-tools export-data --out-dir=build/exports
"""

import shlex

import _bootstrap  # noqa: F401
from _bootstrap import (
    _styled_line,
    print_resolved_config,
    print_rule,
    rich_print,
)

import kwconf as kw


# Fuzzy hyphens are on by default, so none of these set __fuzzy_hyphens__.


class Train(kw.Config):
    max_epochs: int = kw.Value(1, help='number of epochs')
    dry_run = kw.Flag(False, help='only print what would run')

    @classmethod
    def main(cls, argv=None, **kwargs):
        config = cls.cli(argv=argv, data=kwargs)
        print_resolved_config(config)
        return config


class Predict(kw.Config):
    batch_size: int = kw.Value(1, help='inference batch size')

    @classmethod
    def main(cls, argv=None, **kwargs):
        config = cls.cli(argv=argv, data=kwargs)
        print_resolved_config(config)
        return config


class ExportData(kw.Config):
    out_dir: str = kw.Value('build/exports', help='destination directory')
    include_meta = kw.Flag(False, help='also export metadata sidecars')

    @classmethod
    def main(cls, argv=None, **kwargs):
        config = cls.cli(argv=argv, data=kwargs)
        print_resolved_config(config)
        return config


class CleanCache(kw.Config):
    older_than: int = kw.Value(7, help='delete cache entries older than N days')

    @classmethod
    def main(cls, argv=None, **kwargs):
        config = cls.cli(argv=argv, data=kwargs)
        print_resolved_config(config)
        return config


class PurgeLogs(kw.Config):
    older_than: int = kw.Value(30, help='delete logs older than N days')

    @classmethod
    def main(cls, argv=None, **kwargs):
        config = cls.cli(argv=argv, data=kwargs)
        print_resolved_config(config)
        return config


class StrictReport(kw.Config):
    """A leaf config that opts *out* of fuzzy hyphens for its own flags."""

    __fuzzy_hyphens__ = False

    out_dir: str = kw.Value('build/reports', help='destination directory')

    @classmethod
    def main(cls, argv=None, **kwargs):
        config = cls.cli(argv=argv, data=kwargs)
        print_resolved_config(config)
        return config


class DataTools(kw.ModalCLI):
    """Nested utility commands (a submodal). Fuzzy by default."""

    export_data = ExportData
    clean_cache = CleanCache


class LegacyTools(kw.ModalCLI):
    """A submodal that opts *out* of fuzzy hyphens for its own commands."""

    __fuzzy_hyphens__ = False

    purge_logs = PurgeLogs


class App(kw.ModalCLI):
    """Small modal example application. Fuzzy by default."""

    __version__ = '1.0.0'

    run_train = kw.ModalValue(Train, alias=['fit_model'])
    predict = kw.ModalValue(Predict, alias=['score_model'])
    data_tools = DataTools
    legacy_tools = LegacyTools
    report = StrictReport


# Each row is (label, canonical underscore argv, equivalent fuzzy argv). Both
# spellings must dispatch to the same command and resolve to the same config.
EQUIVALENT_INVOCATIONS = [
    (
        'root command name',
        ['run_train', '--max_epochs=3'],
        ['run-train', '--max_epochs=3'],
    ),
    (
        'root command alias',
        ['fit_model', '--max_epochs=3'],
        ['fit-model', '--max_epochs=3'],
    ),
    (
        'leaf option flag',
        ['run_train', '--max_epochs=3'],
        ['run_train', '--max-epochs=3'],
    ),
    (
        'predict alias + hyphen flag',
        ['score_model', '--batch_size=8'],
        ['score-model', '--batch-size=8'],
    ),
    (
        'submodal command name',
        ['data_tools', 'export_data', '--out_dir=/tmp/out'],
        ['data-tools', 'export_data', '--out_dir=/tmp/out'],
    ),
    (
        'nested (submodal) command name',
        ['data_tools', 'export_data', '--out_dir=/tmp/out'],
        ['data_tools', 'export-data', '--out_dir=/tmp/out'],
    ),
    (
        'every level hyphenated at once',
        ['data_tools', 'export_data', '--out_dir=/tmp/out', '--include_meta'],
        ['data-tools', 'export-data', '--out-dir=/tmp/out', '--include-meta'],
    ),
]

# Each row is (label, argv, expect_ok). These probe that fuzziness is owned by
# each object: the fuzzy root reaches every command by either spelling, but a
# strict submodal / config does not accept hyphenated spellings of its own
# command names / option flags.
PER_OBJECT_CHECKS = [
    (
        'root is fuzzy: reaches strict submodal by hyphen name',
        ['legacy-tools', 'purge_logs'],
        True,
    ),
    (
        'fuzzy submodal advertises its hyphen command',
        ['data-tools', 'export-data', '--out_dir=/tmp/o'],
        True,
    ),
    (
        'strict submodal rejects its hyphen command',
        ['legacy_tools', 'purge-logs'],
        False,
    ),
    (
        'strict submodal accepts its underscore command',
        ['legacy_tools', 'purge_logs'],
        True,
    ),
    (
        'strict config rejects its hyphen flag',
        ['report', '--out-dir=/tmp/r'],
        False,
    ),
    (
        'strict config accepts its underscore flag',
        ['report', '--out_dir=/tmp/r'],
        True,
    ),
]


def _run_quiet(argv):
    """Dispatch through ``App``, swallowing the command's own output.

    Returns the resolved Config on success, or ``1`` (the ``_noexit`` error
    code the modal returns) when parsing fails.
    """
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        return App.main(argv=argv, _noexit=True)


def _proof_line(passed, label, left, right, sep='  ==  '):
    tag, style = ('[PASS]', 'bold green') if passed else ('[FAIL]', 'bold red')
    _styled_line(
        [
            (f'{tag} ', style),
            (f'{label:<46}', 'bold cyan'),
            (left, 'yellow'),
            (sep, 'white'),
            (right, 'magenta'),
        ]
    )


def demonstrate_data_tools_equivalence():
    """Show plainly that ``data-tools`` and ``data_tools`` are one command."""
    print_rule("Hyphens == underscores: 'data-tools' IS 'data_tools'")
    underscored = [
        'data_tools',
        'export_data',
        '--out_dir=/tmp/x',
        '--include_meta',
    ]
    hyphenated = [
        'data-tools',
        'export-data',
        '--out-dir=/tmp/x',
        '--include-meta',
    ]
    cfg_a = _run_quiet(underscored)
    cfg_b = _run_quiet(hyphenated)
    assert isinstance(cfg_a, kw.Config) and isinstance(cfg_b, kw.Config)
    rich_print('  underscores:  ' + shlex.join(underscored), 'yellow')
    rich_print('  hyphens:      ' + shlex.join(hyphenated), 'magenta')
    rich_print('  both select the SAME command and resolve to:', 'white')
    resolved = (
        f'{type(cfg_a).__name__}('
        f'out_dir={cfg_a.out_dir!r}, include_meta={cfg_a.include_meta!r})'
    )
    rich_print('    ' + resolved, 'bold cyan')
    assert cfg_a.asdict() == cfg_b.asdict()
    rich_print(
        '  => identical result; hyphens and underscores are interchangeable.',
        'bold green',
    )


def prove_fuzzy_hyphens():
    """Prove fuzzy hyphens resolve identically at every modal level."""
    demonstrate_data_tools_equivalence()
    print_rule('PROVE: equivalent spellings resolve identically')
    for label, canonical, variant in EQUIVALENT_INVOCATIONS:
        base = _run_quiet(canonical)
        other = _run_quiet(variant)
        passed = (
            isinstance(base, kw.Config)
            and isinstance(other, kw.Config)
            and type(base) is type(other)
            and base.asdict() == other.asdict()
        )
        _proof_line(passed, label, shlex.join(canonical), shlex.join(variant))
        assert passed, f'fuzzy mismatch for {label!r}: {canonical} != {variant}'

    print_rule('PROVE: fuzziness is per-object (children are not coerced)')
    for label, argv, expect_ok in PER_OBJECT_CHECKS:
        ret = _run_quiet(argv)
        got_ok = isinstance(ret, kw.Config)
        passed = got_ok == expect_ok
        verdict = 'accepted' if got_ok else 'rejected'
        _proof_line(passed, label, shlex.join(argv), verdict, sep='  ->  ')
        assert passed, (
            f'{label!r}: expected {"accepted" if expect_ok else "rejected"}, '
            f'got {verdict} for {argv}'
        )

    print('ALL FUZZY-HYPHEN CHECKS PASSED')


def main(argv=None):
    import sys

    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        # No command given: run the self-proving fuzzy-hyphen demonstration.
        return prove_fuzzy_hyphens()
    return App.main(argv=argv)


if __name__ == '__main__':
    main()
