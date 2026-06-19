Quickstart
==========

Start with plain class attributes. Add ``Value`` only when a field needs CLI
metadata or a default factory.

.. code-block:: python

    import kwconf


    class DemoConfig(kwconf.Config):
        count = 1
        mode = kwconf.Value('fast', choices=['fast', 'safe'])
        tags = kwconf.Value(default_factory=list, nargs='+')


    cfg = DemoConfig.cli(argv=['--count=3', '--mode=safe', '--tags', 'a', 'b'])
    assert cfg.count == 3
    assert cfg.mode == 'safe'
    assert cfg.tags == ['a', 'b']

``Config`` instances support attribute access and dict-style access, so they
fit code that already expects a small config dictionary.

Loading data
------------

``load`` accepts dictionaries, JSON/YAML paths, JSON/YAML strings, and optional
CLI overrides:

.. code-block:: python

    cfg = DemoConfig(count=2)
    cfg = DemoConfig().load({'count': 2})
    cfg = DemoConfig.cli(data={'count': 2}, argv=['--mode=fast'])
    cfg = DemoConfig.from_env(prefix='DEMO_')
    cfg = DemoConfig.from_yaml('demo.yaml')

Precedence is: class defaults, runtime default overrides, data/file values,
then explicit argv values. See :doc:`../manual/core_contract`.

Parsers
-------

A parser reads a CLI/env string for one field.

.. code-block:: python

    import kwconf


    class ParserConfig(kwconf.Config):
        scalar = kwconf.Value(None)                         # parser='auto'
        nums = kwconf.Value(default_factory=list, parser='csv')
        payload = kwconf.Value(None, parser='yaml')


    cfg = ParserConfig.cli(argv=[
        '--scalar=3',
        '--nums=1,2,3',
        '--payload={enabled: true, size: 4}',
    ])
    assert cfg.scalar == 3
    assert cfg.nums == [1, 2, 3]
    assert cfg.payload == {'enabled': True, 'size': 4}

Use ``auto`` for scalar values, ``csv`` for comma-separated lists, and ``yaml``
for YAML-shaped values. Install ``kwconf[yaml]`` for YAML support. Use
``nargs`` for space-separated CLI lists. See :doc:`../manual/coercion_and_cli`.

Typing path
-----------

Annotations are optional. Add them when you want better static checks, editor
help, parser selection, or validation.

.. code-block:: python

    class TrainConfig(kwconf.Config):
        lr: float = 1e-3
        mode: str = kwconf.Value('fast', choices=['fast', 'safe'])
        tags: list[str] = kwconf.Value(default_factory=list, nargs='+')


    cfg = TrainConfig.cli(argv=['--lr=0.01', '--tags', 'cat', 'dog'])
    assert cfg.lr == 0.01
    assert cfg.tags == ['cat', 'dog']

Nested configs
--------------

.. code-block:: python

    class Train(kwconf.Config):
        lr = 1e-3


    class Experiment(kwconf.Config):
        train = kwconf.SubConfig(Train)


    cfg = Experiment.cli(argv=['--train.lr=0.01'])
    assert cfg.train.lr == 0.01

See :doc:`../manual/nested_configs` for selector choices and YAML round trips.

Subcommands
-----------

.. code-block:: python

    class Foo(kwconf.Config):
        __command__ = 'foo'

        @classmethod
        def main(cls, argv=None, **kwargs):
            print(cls.cli(argv=argv, data=kwargs))


    class App(kwconf.ModalCLI):
        foo = Foo


    App.main(argv=['foo'])

See :doc:`../manual/modal_cli` for aliases, nested modals, help, and version
behavior.

Next steps
----------

Run checked-in examples from the repo root:

.. code-block:: bash

    python examples/01_minimal_config.py --help
    python examples/03_config_files.py --config examples/data/report.yaml --limit=3 --format=json
    python examples/run_all.py

Use :doc:`../manual/migration_from_scriptconfig` when porting scriptconfig code
or asking an LLM for migration help. The migration guide calls out old
``cmdline`` examples, parser changes, and scriptconfig footguns.
