Modal CLIs
==========

:class:`kwconf.ModalCLI` groups several smaller ``Config`` CLIs into one
subcommand-based program. Each command owns its config class and ``main``
method.

Basic modal
-----------

.. code-block:: python

    import kwconf


    class Train(kwconf.Config):
        epochs = kwconf.Value(1, help='number of epochs')
        dry_run = kwconf.Flag(False, help='only print what would run')

        @classmethod
        def main(cls, argv=None, **kwargs):
            cfg = cls.cli(argv=argv, data=kwargs)
            print(f'train epochs={cfg.epochs} dry_run={cfg.dry_run}')
            return 0


    class Eval(kwconf.Config):
        dataset = kwconf.Value('demo', help='dataset name')

        @classmethod
        def main(cls, argv=None, **kwargs):
            cfg = cls.cli(argv=argv, data=kwargs)
            print(f'eval dataset={cfg.dataset}')
            return 0


    class App(kwconf.ModalCLI):
        __version__ = '1.0.0'
        train = kwconf.ModalValue(Train, alias=['fit-model'])
        eval = Eval


    App.main(argv=['fit-model', '--epochs=3', '--dry-run'])

Declarative registration
------------------------

Commands can be class attributes, registered imperatively with
``@modal.register``, or wrapped in :class:`kwconf.ModalValue` when you want
aliases, command-name overrides, or group metadata. The command name defaults to
the attribute name (or the class name under ``@modal.register``); to override it
prefer ``ModalValue(..., command=...)``. A ``__command__`` class attribute also
works but is rarely needed.

.. code-block:: python

    class App(kwconf.ModalCLI):
        train = kwconf.ModalValue(Train, alias=['fit-model'])
        score = kwconf.ModalValue(Eval, command='score', alias=['evaluate'])

Nested modals
-------------

A modal can contain another modal:

.. code-block:: python

    class Tools(kwconf.ModalCLI):
        score = kwconf.ModalValue(Eval, command='score')


    class App(kwconf.ModalCLI):
        tools = Tools


    App.main(argv=['tools', 'score', '--dataset=coco'])

Explicit child arguments
------------------------

Modal dispatch forwards only child arguments that were present in argv. This
lets command ``main`` methods merge repo defaults, config files, and explicit
CLI values without treating schema defaults as user input.

Help and version behavior
-------------------------

``--help`` is available at every modal level, and ``--version`` reports the
version for the modal currently being addressed. Unknown command errors print
usage for the deepest parser that could be resolved.
