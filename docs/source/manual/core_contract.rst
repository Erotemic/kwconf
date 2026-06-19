Core Contract
=============

``kwconf`` is intentionally **not** a drop-in compatibility layer for
``scriptconfig``.  It is a typed, explicit, dataclass-like configuration and
CLI library that keeps the useful scriptconfig ergonomics while removing the
implicit behavior that made large CLIs surprising.

Stable public objects
---------------------

The stable public surface is intentionally small:

``Config``
    The only public configuration base class.  Define schemas with typed class
    variables and optional ``Value`` wrappers.  Construct with keyword
    arguments, ``.load(...)``, or ``.cli(argv=...)``.

``Value`` / ``Flag``
    Attach CLI metadata to a field: help text, aliases, choices, flags,
    counters, ``nargs``, positional order, groups, mutex groups, explicit
    coercion (``parser=``), and validation policy.  These are typed *factory
    functions* (annotated to return the field's value type, which is what gives
    you static default-vs-annotation checking).  To subclass the underlying
    runtime class, use ``ValueClass`` / ``FlagClass``.

``SubConfig``
    Declare nested configuration trees, including dotted CLI overrides and
    selector choices for variant nodes.

``ModalCLI`` / ``ModalValue``
    Build subcommand CLIs from ``Config`` classes, including aliases and
    nested modal dispatch.

``dataconf`` / ``define``
    Lightweight helpers for defining config classes programmatically.

Schema definition contract
--------------------------

Prefer typed class variables:

.. code-block:: python

    import kwconf as kw


    class TrainConfig(kw.Config):
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

Coercion happens only at the **text boundary** (argv / env). The **Python
boundary** (constructor, assignment, a field's own default) is trusted, so a
WYSIWYG ``kw.Value('512')`` stays the string ``'512'``.

* untyped strings infer scalars only; ``--items=a,b,c`` does **not** become a
  list;
* ``parser=`` (canonical; ``type=`` is a deprecated alias) selects a parser --
  a callable, or a named one: ``'auto'`` (default), ``'csv'``, ``'yaml'``;
* ``'auto'`` and ``'csv'`` are annotation-aware; ``'yaml'`` is not;
* annotations like ``list[int]`` and ``Literal['a', 'b']`` enrich coercion,
  choices, and validation.

For a list on the CLI use ``nargs='+'``, ``parser='csv'``, or ``parser='yaml'``.
See :doc:`coercion_and_cli` for the full parser model.

Validation contract
-------------------

Runtime validation defaults to ``'warn'``: a value that does not match the
field annotation is accepted (never raises) but emits a ``UserWarning``.  It is
the single place mismatches are reported, so the message is consistent across
``auto``/``csv``/``yaml``/custom parsers.  Tune it per class or per field:

.. code-block:: python

    class C(kw.Config):
        __validate__ = 'error'  # 'warn' (default) | 'error'/True | False
        count: int | None = None

Validation runs after coercion, on *user-supplied* values (constructor / data /
assignment / parsed argv-env) but **not** on a field's own trusted default.
Unknown or unsupported annotation forms are under-validated instead of causing
class creation or assignment to fail.  Opt a single field out with
``Value(..., validate=False)``.

Nested-config contract
----------------------

Nested config values are declared with ``SubConfig`` and updated with dotted
keys:

.. code-block:: python

    class Inner(kw.Config):
        depth: int = 1

    class Outer(kw.Config):
        inner = kw.SubConfig(Inner)

    cfg = Outer.cli(argv=['--inner.depth=3'])

Variant nodes use ``choices`` for explicit selectors.  Dynamic imports are
controlled by the ``allow_import`` policy and should be disabled when untrusted
input controls selectors.

Modal contract
--------------

``ModalCLI`` collects class attributes that are ``Config`` or ``ModalCLI``
subclasses and exposes them as subcommands.  Use ``ModalValue`` when a command
needs aliases or grouping metadata.

Removed scriptconfig behavior
-----------------------------

The following APIs and behaviors are deliberately not part of kwconf:

* ``kwconf.DataConfig`` and the old ``scriptconfig.Config(data=..., cmdline=...)`` constructor style.
* ``cmdline=``.
* non-dunder lifecycle aliases: ``default``, ``normalize``, ``description``,
  ``epilog``, and ``prog``.
* implicit comma-splitting.
* ``Path`` / ``PathList`` helper classes.
* magic ``type='smartcast'``, ``type='smartcast:v1'``, or
  ``type='smartcast:legacy'`` aliases.

Migration checks should remain a documentation/review concern rather than a
runtime CLI feature.
