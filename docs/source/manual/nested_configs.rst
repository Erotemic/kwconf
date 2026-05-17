Nested Configs
==============

Nested configs are declared explicitly with :class:`kwconf.SubConfig`.  A
``SubConfig`` wraps a :class:`kwconf.Config` class or instance and lets files
and CLIs update nested values without hiding the tree shape.

Basic nesting
-------------

.. code-block:: python

    import kwconf as kw

    class Dataset(kw.Config):
        path: str = 'demo'
        augment: bool = False

    class Adam(kw.Config):
        lr: float = 0.001
        beta1: float = 0.9

    class Train(kw.Config):
        dataset = kw.SubConfig(Dataset)
        optim = kw.SubConfig(Adam)
        epochs: int = 10

    cfg = Train.cli(argv=['--dataset.path=data/images', '--optim.lr=0.01'])
    assert cfg.dataset.path == 'data/images'
    assert cfg.optim.lr == 0.01

Selector choices
----------------

A nested field can expose a registry of allowed implementations.  Users can
select a choice with ``--field=<choice>`` or ``--field.__class__=<choice>`` and
then override leaves below that selected class.

.. code-block:: python

    class SGD(kw.Config):
        lr: float = 0.01
        momentum: float = 0.9

    class Train(kw.Config):
        optim = kw.SubConfig(Adam, choices={'adam': Adam, 'sgd': SGD})

    cfg = Train.cli(argv=['--optim=sgd', '--optim.momentum=0.7'])
    assert isinstance(cfg.optim, SGD)
    assert cfg.optim.momentum == 0.7

YAML roundtrip
--------------

Nested YAML uses normal dictionaries.  ``__class__`` records selector choices
when a field is realized as a non-default class.

.. code-block:: yaml

    optim:
      __class__: sgd
      lr: 0.2
      momentum: 0.7
    epochs: 5

The same file can be loaded with the opt-in special ``--config`` option:

.. code-block:: python

    cfg = Train.cli(
        argv=['--config', 'train.yaml', '--optim.lr=0.05'],
        special_options=True,
        allow_subconfig_overrides=True,
    )

Precedence is predictable: class defaults, then ``data`` / config file values,
then explicit CLI overrides.

Import safety
-------------

``SubConfig`` supports dynamic class-path selection only when ``allow_import``
is enabled.  Prefer explicit ``choices`` for stable CLIs and disable imports in
contexts where config files or argv are not trusted.

Help output
-----------

The parser is variant-aware.  If the user selects ``--optim=sgd`` before
``--help``, the help output includes ``optim.momentum`` and omits Adam-only
fields such as ``optim.beta1``.
