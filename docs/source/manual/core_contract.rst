Core Contract
=============

``kwconf`` is a typed, dataclass-like configuration and CLI library for small
scripts and larger applications. It keeps the useful scriptconfig workflow and
makes parsing choices explicit.

Stable public objects
---------------------

``Config``
    The public configuration base class. Define schemas with class variables
    and optional ``Value`` wrappers. Construct with keyword arguments,
    ``.load(...)``, or ``.cli(argv=...)``.

``Value`` / ``Flag``
    Attach field metadata: help text, aliases, choices, flags, counters,
    ``nargs``, positional order, groups, mutex groups, ``parser=``, default
    factories, and validation policy.

``SubConfig``
    Declare nested configuration trees, dotted CLI overrides, and selector
    choices for variant nodes.

``ModalCLI`` / ``ModalValue``
    Build subcommand CLIs from ``Config`` classes, including aliases and nested
    modal dispatch.

``dataconf`` / ``define``
    Lightweight helpers for programmatic or migration-heavy definitions.

Schema definition
-----------------

Start with class attributes. Type annotations are optional.

.. code-block:: python

    import kwconf


    class TrainConfig(kwconf.Config):
        lr = 1e-3
        mode = kwconf.Value('fast', choices=['fast', 'safe'])
        tags = kwconf.Value(default_factory=list, nargs='+')

Raw defaults are normalized to ``Value`` metadata internally. Use ``Value``
when a field needs metadata or a ``default_factory``.

Add annotations when you want static checks, editor help, parser selection, or
validation:

.. code-block:: python

    class TypedTrainConfig(kwconf.Config):
        lr: float = 1e-3
        mode: str = kwconf.Value('fast', choices=['fast', 'safe'])
        tags: list[str] = kwconf.Value(default_factory=list, nargs='+')

``__default__`` remains available for migration and dynamic construction.
Prefer class attributes for new code.

CLI contract
------------

All command-line parsing uses ``argv``:

.. code-block:: python

    cfg = TrainConfig.cli(argv=['--lr=0.01', '--mode=safe'])

Accepted ``argv`` values are:

* ``True`` or ``None``: parse ``sys.argv``.
* ``False``: skip CLI parsing.
* ``list[str]``: parse that list.
* ``str``: split with ``shlex`` and parse the result.

Special options are opt-in. ``--config``, ``--dump``, and ``--dumps`` are
reserved only when ``special_options=True`` is passed or the class sets
``__special_options__ = True``.

Precedence
----------

Configuration values resolve in this order:

1. class defaults;
2. runtime default overrides;
3. mapping or file data;
4. explicit argv values.

Every input path maps into the same field model.

Coercion contract
-----------------

Coercion runs for string-only sources: ``sys.argv`` tokens and ``os.environ``
values. Python kwargs, assignment, defaults, and typed YAML/JSON values are
used as Python values.

* ``parser=`` selects the parser for a field.
* ``auto`` is the default scalar parser.
* ``csv`` reads comma-separated lists.
* ``yaml`` reads YAML-shaped strings.
* ``nargs`` reads space-separated CLI lists.

See :doc:`coercion_and_cli` for parser details.

Validation contract
-------------------

Runtime validation checks user-supplied values against annotations after
parsing. The default policy is ``'warn'``. Tune it per class or per field:

.. code-block:: python

    class C(kwconf.Config):
        __validate__ = 'error'  # 'warn' | 'error'/True | False
        count: int | None = None

Validation runs on constructor values, data/file values, assignment, parsed
argv values, and parsed env values. Field defaults are accepted as declared.
Unsupported annotation forms are skipped.

Nested configs
--------------

Nested config values are declared with ``SubConfig`` and updated with dotted
keys:

.. code-block:: python

    class Inner(kwconf.Config):
        depth = 1


    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(Inner)


    cfg = Outer.cli(argv=['--inner.depth=3'])
    assert cfg.inner.depth == 3

Variant nodes use ``choices`` for explicit selectors. Dynamic import selectors
are controlled by ``allow_import``.

Modal CLIs
----------

``ModalCLI`` collects ``Config`` or ``ModalCLI`` class attributes and exposes
them as subcommands. Use ``ModalValue`` for aliases or grouping metadata.

Migration boundary
------------------

Review :doc:`migration_from_scriptconfig` when porting scriptconfig code. The
most common changes are the import name, the single ``Config`` base class,
``parser=`` instead of ``type=``, ``argv=`` instead of old ``cmdline=`` examples,
opt-in special options, and explicit list parsing.
