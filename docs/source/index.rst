:gitlab_url: https://gitlab.kitware.com/computer-vision/kwconf

:github_url: None

kwconf documentation
====================

``kwconf`` defines configuration objects that work from Python kwargs,
``sys.argv``, ``os.environ``, and JSON/YAML files. It is the successor to
``scriptconfig`` and keeps the small-script workflow: start with defaults, add
metadata where the CLI needs it, and keep the config usable as an object or a
mapping.

Basic demo
----------

.. code-block:: python

    import kwconf


    class DemoConfig(kwconf.Config):
        count = 1
        mode = kwconf.Value('fast', choices=['fast', 'safe'])
        tags = kwconf.Value(default_factory=list, nargs='+')


    cfg = DemoConfig.cli(argv=['--count=3', '--mode=safe', '--tags', 'a', 'b'])
    assert cfg.count == 3
    assert cfg['mode'] == 'safe'
    assert cfg.tags == ['a', 'b']

Parser demo
-----------

.. code-block:: python

    class ParserConfig(kwconf.Config):
        scalar = kwconf.Value(None)                         # parser='auto'
        nums = kwconf.Value(default_factory=list, parser='csv')
        payload = kwconf.Value(None, parser='yaml')


    cfg = ParserConfig.cli(argv=[
        '--scalar=3',
        '--nums=1,2,3',
        '--payload=[a, b, c]',
    ])
    assert cfg.scalar == 3
    assert cfg.nums == [1, 2, 3]
    assert cfg.payload == ['a', 'b', 'c']

``auto`` reads scalar CLI/env strings, ``csv`` reads comma lists, and ``yaml``
reads YAML-shaped values. See :doc:`manual/coercion_and_cli` for details.

.. toctree::
   :caption: Tutorial
   :maxdepth: 2

   tutorial/quickstart

.. toctree::
   :caption: Manual
   :maxdepth: 2

   manual/core_contract
   manual/coercion_and_cli
   manual/nested_configs
   manual/modal_cli
   manual/migration_from_scriptconfig
   manual/ADRs

.. toctree::
   :caption: API reference
   :maxdepth: 5

   auto/modules


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
