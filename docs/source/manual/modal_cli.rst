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
aliases, command-name overrides, or group metadata.

Modal command declarations follow normal class inheritance. A subclass keeps
commands declared by its parent through class attributes, ``__subconfigs__``,
or class-level ``register()``. Rebinding an attribute in the subclass replaces
the inherited command bound to that attribute; rebinding it to a non-command
value intentionally hides that command. Registering a new command on the
subclass does not modify the parent's command list.

Only :class:`kwconf.Config` and :class:`kwconf.ModalCLI` subclasses are
discovered implicitly from public class attributes. Other class-valued helpers
remain ordinary attributes. A compatible custom command type can still be
added deliberately with :class:`kwconf.ModalValue`, ``__subconfigs__``, or
``register()``.

The class-level ``__subconfigs__`` table is declarative and reusable. Each
``ModalCLI`` instance copies that metadata before parser construction adds live
Config instances, parser keyword arguments, or dispatch callables. Building a
parser for one modal therefore does not mutate the class declaration or alter
a sibling modal instance. Dictionaries passed through ``sub_clis=`` are copied
under the same rule; callers retain ownership of their input mappings.

The command name follows this precedence (high to low):

#. ``ModalValue(command=...)`` -- explicit at the binding site.
#. the command's ``__command__`` class attribute.
#. the attribute name the command is bound to (``train = Train`` -> ``train``).
#. the class name.

You usually do not need ``__command__``: when it is absent the attribute name is
used (and the class name for ``__subconfigs__`` lists / argument-less
``@modal.register``). Its main use is giving nested classes a clean command name
-- a nested ``class Train`` would otherwise become the command ``Train``, so set
``__command__ = 'train'`` to override it.

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

If no leaf command is selected, kwconf prints usage for that same deepest
parser and raises :class:`kwconf.modal.NoCommandError`. The exception keeps an
integer process status in ``code`` and exposes the diagnostic text and parser as
``message`` and ``parser`` for programmatic callers. A modal without an explicit
``__prog__`` uses its class name for deterministic root usage.
