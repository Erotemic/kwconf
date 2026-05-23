"""
MWE: modal dispatch should preserve omitted-vs-explicit option semantics.

This example captures a real bug found while adding repo-local defaults to
``git-well archive_source``. The subcommand wanted to read a Git config value
such as ``git-well.archive-source.depth=0`` and use it as a default. Direct
invocation worked, but modal invocation did not because the modal dispatcher
called the subcommand with every resolved value already present in ``kwargs``.

DEMO:
    Command::

        python examples/08_modal_default_precedence_mwe.py

    Fixed output should show modal and direct invocation agreeing::

        DIRECT INVOCATION
        subcommand argv=['--verbose']
        subcommand kwargs={}
        repo defaults={'depth': '0'}
        resolved depth=0
        MODAL INVOCATION
        subcommand argv=False
        subcommand kwargs={'verbose': True}
        repo defaults={'depth': '0'}
        resolved depth=0

    Historical buggy behavior::

        The modal invocation used to forward
        ``kwargs={'depth': 'full', 'verbose': True}``, causing
        ``resolved depth=full`` even though ``--depth`` was omitted.

PROMPT FOR THE KWCONF AGENT:
    Please use this file as a regression target while designing modal dispatch
    semantics. The important invariant is that a subcommand must be able to
    distinguish:

    - values explicitly supplied by the caller, e.g. ``--depth=full``;
    - values supplied by modal dispatch because the parent parser resolved the
      subcommand schema;
    - values omitted by the user and therefore still eligible to be filled by a
      later default source, such as repo-local Git config.

    In scriptconfig / current kwconf modal behavior, the modal path calls the
    subcommand as if all schema defaults were explicit kwargs:
    ``kwargs={'depth': 'full', 'verbose': True}``. That prevents a later call
    such as ``ArchiveSource.cli(data=kwargs, default={'depth': '0'})`` from
    honoring the repo-local default. A more natural behavior would preserve
    omitted values as omitted, or otherwise provide provenance metadata so
    downstream code can apply lower-priority defaults before final resolution.
"""

import _bootstrap  # noqa: F401
import kwconf as kw


REPO_LOCAL_DEFAULTS = {
    # Simulates: git config --local git-well.archive-source.depth 0
    'depth': '0',
}


class ArchiveSource(kw.Config):
    """
    Small stand-in for git-well archive_source.
    """

    __command__ = 'archive_source'

    depth = kw.Value(
        'full',
        help='history depth: full, positive integer, or 0 for source-only',
    )
    verbose = kw.Flag(False, help='print progress')

    @classmethod
    def main(cls, argv=None, **kwargs):
        print(f'subcommand argv={argv!r}')
        print(f'subcommand kwargs={kwargs!r}')
        print(f'repo defaults={REPO_LOCAL_DEFAULTS!r}')
        config = cls.cli(
            argv=argv,
            data=kwargs,
            default=REPO_LOCAL_DEFAULTS,
        )
        print(f'resolved depth={config.depth}')
        return config


class App(kw.ModalCLI):
    """
    Modal app that exposes the archive_source subcommand.
    """

    archive_source = ArchiveSource


def main():
    print('DIRECT INVOCATION')
    direct = ArchiveSource.main(argv=['--verbose'])
    print('MODAL INVOCATION')
    modal = App.main(argv=['archive_source', '--verbose'])

    if direct.depth != '0':
        raise AssertionError('direct invocation should honor repo defaults')
    if modal.depth != '0':
        raise AssertionError(
            'modal dispatch made omitted defaults look explicit, so the '
            'repo-local depth default could not apply'
        )


if __name__ == '__main__':
    main()
