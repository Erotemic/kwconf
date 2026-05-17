"""
Modal CLIs: one application, multiple subcommands.
"""

import _bootstrap  # noqa: F401
import kwconf as kw


class Train(kw.Config):
    __command__ = 'train'
    epochs: int = kw.Value(1, help='number of epochs')
    dry_run = kw.Flag(False, help='only print what would run')

    @classmethod
    def main(cls, argv=None, **kwargs):
        config = cls.cli(argv=argv, data=kwargs)
        message = f'train epochs={config.epochs} dry_run={config.dry_run}'
        print(message)
        return message


class Evaluate(kw.Config):
    __command__ = 'eval'
    dataset: str = kw.Value('demo', help='dataset name')

    @classmethod
    def main(cls, argv=None, **kwargs):
        config = cls.cli(argv=argv, data=kwargs)
        message = f'eval dataset={config.dataset}'
        print(message)
        return message


class Tools(kw.ModalCLI):
    """Nested utility commands."""

    score = kw.ModalValue(Evaluate, command='score', alias=['evaluate'])


class App(kw.ModalCLI):
    """Small modal demo application."""

    __version__ = '1.0.0'

    train = kw.ModalValue(Train, alias=['fit'])
    eval = Evaluate
    tools = Tools


def main(argv=None):
    return App.main(argv=argv)


def demo():
    assert App.main(argv=['fit', '--epochs=3', '--dry-run']) == 'train epochs=3 dry_run=True'
    assert App.main(argv=['eval', '--dataset=coco']) == 'eval dataset=coco'
    assert App.main(argv=['tools', 'evaluate', '--dataset=demo']) == 'eval dataset=demo'
    print('05_modal_cli: ok')


if __name__ == '__main__':
    main()
