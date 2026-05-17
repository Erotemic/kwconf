Modal CLIs
==========

:class:`kwconf.ModalCLI` groups several smaller ``DataConfig`` CLIs into one
subcommand-based program.  Each command owns its own config class and ``main``
method.

Basic modal
-----------

.. code-block:: python

    import kwconf as kw

    class Train(kw.DataConfig):
        __command__ = 'train'
        epochs: int = kw.Value(1, help='number of epochs')
        dry_run = kw.Flag(False, help='only print what would run')

        @classmethod
        def main(cls, argv=None, **kwargs):
            cfg = cls.cli(argv=argv, data=kwargs)
            print(f'train epochs={cfg.epochs} dry_run={cfg.dry_run}')
            return 0

    class Eval(kw.DataConfig):
        __command__ = 'eval'
        dataset: str = kw.Value('demo', help='dataset name')

        @classmethod
        def main(cls, argv=None, **kwargs):
            cfg = cls.cli(argv=argv, data=kwargs)
            print(f'eval dataset={cfg.dataset}')
            return 0

    class App(kw.ModalCLI):
        __version__ = '1.0.0'
        train = kw.ModalValue(Train, alias=['fit-model'])
        eval = Eval

    App.main(argv=['fit-model', '--epochs=3', '--dry-run'])

Declarative registration
------------------------

Commands can be class attributes, registered imperatively with
``@modal.register``, or wrapped in :class:`kwconf.ModalValue` when you want
aliases, command-name overrides, or group metadata.

.. code-block:: python

    class App(kw.ModalCLI):
        train = kw.ModalValue(Train, alias=['fit-model'])
        score = kw.ModalValue(Eval, command='score', alias=['evaluate'])

Nested modals
-------------

A modal can contain another modal:

.. code-block:: python

    class Tools(kw.ModalCLI):
        __command__ = 'tools'
        score = kw.ModalValue(Eval, command='score')

    class App(kw.ModalCLI):
        tools = Tools

    App.main(argv=['tools', 'score', '--dataset=coco'])

Help and version behavior
-------------------------

``--help`` is available at every modal level, and ``--version`` reports the
version for the modal currently being addressed.  Unknown command errors print
usage for the deepest parser that could be resolved, which makes nested modal
mistakes easier to diagnose.
