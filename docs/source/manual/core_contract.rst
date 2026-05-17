Core Contract
=============

``kwconf`` is intentionally **not** a drop-in compatibility layer for
``scriptconfig``.  It is a typed, explicit, dataclass-like configuration and
CLI library that keeps the useful scriptconfig ergonomics while removing the
implicit behavior that made large CLIs surprising.

Stable public objects
---------------------

The stable public surface is intentionally small:

``DataConfig``
    The only public configuration base class.  Define schemas with typed class
    variables and optional ``Value`` wrappers.  Construct with keyword
    arguments, ``.load(...)``, or ``.cli(argv=...)``.

``Value`` / ``Flag``
    Attach CLI metadata to a field: help text, aliases, choices, flags,
    counters, ``nargs``, positional order, groups, mutex groups, explicit
    coercion, and validation policy.

``SubConfig``
    Declare nested configuration trees, including dotted CLI overrides and
    selector choices for variant nodes.

``ModalCLI`` / ``ModalValue``
    Build subcommand CLIs from ``DataConfig`` classes, including aliases and
    nested modal dispatch.

``dataconf`` / ``define``
    Lightweight helpers for defining config classes programmatically.

Schema definition contract
--------------------------

Prefer typed class variables:

.. code-block:: python

    import kwconf as kw


    class TrainConfig(kw.DataConfig):
        lr: float = 1e-3
        mode: str = kw.Value('fast', choices=['fast', 'safe'])
        tags: list[str] = kw.Value(default_factory=list, nargs='+')

Raw defaults are normalized to ``Value`` metadata internally.  Use ``Value``
when the field needs CLI metadata or a ``default_factory``.

``__default__`` remains supported for migration and dynamic construction, but
new code should prefer typed class variables.

CLI contract
------------

All command-line parsing flows through ``argv``:

.. code-block:: python

    cfg = TrainConfig.cli(argv=['--lr=0.01', '--mode=safe'])

Accepted ``argv`` values are:

* ``True`` or ``None``: parse ``sys.argv``.
* ``False``: skip CLI parsing.
* ``list[str]``: parse that list.
* ``str``: split with ``shlex`` and parse the result.

Special options are opt-in.  ``--config``, ``--dump``, and ``--dumps`` are not
reserved unless ``special_options=True`` is passed or the class sets
``__special_options__ = True``.

Coercion contract
-----------------

Coercion is explicit and schema-driven:

* untyped strings only infer scalar values;
* comma-separated strings stay strings unless the schema explicitly asks for a
  sequence;
* ``type=int`` / ``type=float`` / ``type=callable`` calls that coercer;
* ``type='yaml'`` is the named structured parser;
* annotations such as ``list[int]`` and ``Literal['a', 'b']`` enrich coercion,
  choices, and optional validation.

This means ``--items=a,b,c`` does not silently become ``['a', 'b', 'c']``.  Use
``nargs='+'``, ``type=list``, ``type='yaml'``, or explicit ``__post_init__``
logic depending on the desired user interface.

Validation contract
-------------------

Runtime validation is off by default.  Opt in with:

.. code-block:: python

    class C(kw.DataConfig):
        __validate__ = 'error'  # or 'warn'
        count: int | None = None

Validation runs after coercion.  Unknown or unsupported annotation forms are
under-validated instead of causing class creation or assignment to fail.

Nested-config contract
----------------------

Nested config values are declared with ``SubConfig`` and updated with dotted
keys:

.. code-block:: python

    class Inner(kw.DataConfig):
        depth: int = 1

    class Outer(kw.DataConfig):
        inner = kw.SubConfig(Inner)

    cfg = Outer.cli(argv=['--inner.depth=3'])

Variant nodes use ``choices`` for explicit selectors.  Dynamic imports are
controlled by the ``allow_import`` policy and should be disabled when untrusted
input controls selectors.

Modal contract
--------------

``ModalCLI`` collects class attributes that are ``DataConfig`` or ``ModalCLI``
subclasses and exposes them as subcommands.  Use ``ModalValue`` when a command
needs aliases or grouping metadata.

Removed scriptconfig behavior
-----------------------------

The following APIs and behaviors are deliberately not part of kwconf:

* ``scriptconfig.Config`` / ``kwconf.Config``.
* ``cmdline=``.
* non-dunder lifecycle aliases: ``default``, ``normalize``, ``description``,
  ``epilog``, and ``prog``.
* implicit comma-splitting.
* ``Path`` / ``PathList`` helper classes.
* magic ``type='smartcast'``, ``type='smartcast:v1'``, or
  ``type='smartcast:legacy'`` aliases.

Migration checks should remain a documentation/review concern rather than a
runtime CLI feature.
