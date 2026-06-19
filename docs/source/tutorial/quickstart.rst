Quickstart
==========

Define a config by subclassing ``Config``:

.. code-block:: python

    import kwconf as kw


    class DemoConfig(kw.Config):
        count: int = 1
        mode: str = kw.Value('fast', choices=['fast', 'safe'])
        tags: list[str] = kw.Value(default_factory=list, nargs='+')


    cfg = DemoConfig.cli(argv=['--count=3', '--mode=safe', '--tags', 'a', 'b'])
    assert cfg.count == 3
    assert cfg.mode == 'safe'
    assert cfg.tags == ['a', 'b']

Use ``Value`` only when a field needs CLI metadata.  Raw typed class variables
are enough for simple values.

Loading data
------------

``load`` accepts dictionaries, JSON/YAML paths, JSON/YAML strings, and optional
CLI overrides:

.. code-block:: python

    cfg = DemoConfig().load({'count': 2})
    cfg = DemoConfig.cli(data={'count': 2}, argv=['--mode=fast'])

Nested configs
--------------

.. code-block:: python

    class Train(kw.Config):
        lr: float = 1e-3

    class Experiment(kw.Config):
        train = kw.SubConfig(Train)

    cfg = Experiment.cli(argv=['--train.lr=0.01'])
    assert cfg.train.lr == 0.01

Subcommands
-----------

.. code-block:: python

    class Foo(kw.Config):
        __command__ = 'foo'
        @classmethod
        def main(cls, argv=1, **kwargs):
            print(cls.cli(argv=argv, data=kwargs))

    class App(kw.ModalCLI):
        foo = Foo

    App.main(argv=['foo'])

Next steps
----------

Read the manual chapters for coercion, nested configs, and modal CLIs. If you
are moving code from scriptconfig, use the migration guide as a review
checklist rather than relying on a runtime compatibility layer.
