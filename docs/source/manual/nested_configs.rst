Nested Configs
==============

Nested configs are declared explicitly with :class:`kwconf.SubConfig`. A
``SubConfig`` wraps a :class:`kwconf.Config` class or instance and lets files
and CLIs update nested values while keeping the tree shape visible.

Basic nesting
-------------

.. code-block:: python

    import kwconf


    class Dataset(kwconf.Config):
        path = 'demo'
        augment = False


    class Adam(kwconf.Config):
        lr = 0.001
        beta1 = 0.9


    class Train(kwconf.Config):
        dataset = kwconf.SubConfig(Dataset)
        optim = kwconf.SubConfig(Adam)
        epochs = 10


    cfg = Train.cli(argv=['--dataset.path=data/images', '--optim.lr=0.01'])
    assert cfg.dataset.path == 'data/images'
    assert cfg.optim.lr == 0.01

Selector choices
----------------

A nested field can expose a registry of allowed implementations. Users can
select a choice with ``--field=<choice>`` or ``--field.__class__=<choice>`` and
then override leaves below that selected class.

.. code-block:: python

    class SGD(kwconf.Config):
        lr = 0.01
        momentum = 0.9


    class Train(kwconf.Config):
        optim = kwconf.SubConfig(Adam, choices={'adam': Adam, 'sgd': SGD})


    cfg = Train.cli(argv=['--optim=sgd', '--optim.momentum=0.7'])
    assert isinstance(cfg.optim, SGD)
    assert cfg.optim.momentum == 0.7

YAML round trip
---------------

Nested YAML uses normal dictionaries. ``__class__`` records selector choices
when a field is realized as a non-default class.

.. code-block:: yaml

    optim:
      __class__: sgd
      lr: 0.2
      momentum: 0.7
    epochs: 5

Load the file with the opt-in special ``--config`` option:

.. code-block:: python

    cfg = Train.cli(
        argv=['--config', 'train.yaml', '--optim.lr=0.05'],
        special_options=True,
        allow_subconfig_overrides=True,
    )

Precedence is: class defaults, then ``data`` / config file values, then
explicit CLI overrides. See :doc:`core_contract`.

Import safety
-------------

``SubConfig`` supports dynamic class-path selection when ``allow_import`` is
enabled. Prefer explicit ``choices`` for stable CLIs and disable imports when
config files or argv come from untrusted sources.

Help output
-----------

The parser is variant-aware. If the user selects ``--optim=sgd`` before
``--help``, the help output includes ``optim.momentum`` and omits Adam-only
fields such as ``optim.beta1``.
