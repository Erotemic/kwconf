"""
Modal CLIs: one application, multiple subcommands.

A ModalCLI routes the first positional command to a Config-backed command. Each
command still gets normal Config.cli parsing, and each command prints resolved
config fields as ``name : type = value`` rows.

DEMO:
    Command::

        python examples/05_modal_cli.py fit --epochs=3 --dry-run
"""

import _bootstrap  # noqa: F401
from _bootstrap import print_resolved_config

import kwconf as kw


class Train(kw.Config):
    __command__ = 'train'
    epochs: int = kw.Value(1, help='number of epochs')
    dry_run = kw.Flag(False, help='only print what would run')

    @classmethod
    def main(cls, argv=None, **kwargs):
        config = cls.cli(argv=argv, data=kwargs)
        print_resolved_config(config)
        message = f'train epochs={config.epochs} dry_run={config.dry_run}'
        print('COMMAND RESULT:')
        print(message)
        return config


class Evaluate(kw.Config):
    __command__ = 'eval'
    dataset: str = kw.Value('demo', help='dataset name')

    @classmethod
    def main(cls, argv=None, **kwargs):
        config = cls.cli(argv=argv, data=kwargs)
        print_resolved_config(config)
        message = f'eval dataset={config.dataset}'
        print('COMMAND RESULT:')
        print(message)
        return config


class Tools(kw.ModalCLI):
    """Nested utility commands."""

    score = kw.ModalValue(Evaluate, command='score', alias=['evaluate'])


class App(kw.ModalCLI):
    """Small modal example application."""

    __version__ = '1.0.0'

    train = kw.ModalValue(Train, alias=['fit'])
    eval = Evaluate
    tools = Tools


def main(argv=None):
    return App.main(argv=argv)


if __name__ == '__main__':
    main()
