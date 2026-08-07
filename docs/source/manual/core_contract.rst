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

Constructor calls use Python-like binding rules. Positional values bind in
field declaration order; extra positional values and any field supplied more
than once (including through an alias) raise ``TypeError`` instead of silently
discarding or replacing input.

Field names and operation names
-------------------------------

Mapping access is the authoritative field protocol. Attribute access is a
convenience and may overlap with the public ``Config`` API. A declared field
such as ``load``, ``validate``, or ``cli`` wins on an instance, while the
operation remains available on the class when applicable and through its
private counterpart:

.. code-block:: python

    class C(kwconf.Config):
        load: str = 'record'
        cli: str = 'worker'


    cfg = C()
    assert cfg.load == 'record'
    assert cfg['cli'] == 'worker'

    C.cli(argv=False)       # classmethod remains available
    cfg._load({'load': 'x'})  # guaranteed non-shadowable operation

Every public ``Config`` operation has a matching underscore-prefixed alias.
Kwconf itself uses those aliases internally so a field cannot redirect an
internal method call.

The dictionary-like methods ``clear``, ``copy``, ``get``, ``items``, ``keys``,
``pop``, ``popitem``, ``update``, and ``values`` are different: they remain
method-first on instances to preserve the mapping protocol. Those spellings are
still valid field keys and are always available through item access:

.. code-block:: python

    class C(kwconf.Config):
        keys: str = 'payload'


    cfg = C()
    assert cfg['keys'] == 'payload'
    assert set(cfg.keys()) == {'keys'}

Declared fields and transient attributes
----------------------------------------

The class declaration is the configuration contract. Only declared fields
participate in mapping access, validation, CLI generation, serialization, and
deserialization.

An undeclared attribute attached to an instance is ordinary transient Python
state:

.. code-block:: python

    cfg = TrainConfig()
    cfg.runtime_cache = object()

    assert cfg.runtime_cache is not None
    assert 'runtime_cache' not in cfg
    assert 'runtime_cache' not in cfg.asdict()

This is intentional. ``kwconf`` does not reject the assignment or warn during
serialization. Use a declared field when a value must persist or round-trip.
Private names are not required for temporary state, although they can still be
useful by convention.

``__allow_newattr__ = True`` is a separate, experimental escape hatch. It
promotes unknown item or attribute assignments into ``_data``, so they become
mapping keys and may be emitted by serializers. Dynamic keys have no declared
default, annotation, parser, help text, CLI option, or SubConfig metadata, and
the current API does not promise symmetric deserialization of them. Do not use
this flag for persisted configuration yet.

A possible future direction is to formalize this opt-in as a dynamic-field
mode: unknown loaded keys would round-trip symmetrically, while remaining
outside schema-generated CLI and static validation unless explicit metadata is
provided. That direction is intentionally separate from ordinary attached
attributes, which remain transient object state.

State ownership
---------------

The class schema, instance reset baseline, and current values are separate:

``Class.__default__``
    Schema templates. These carry ``Value`` / ``SubConfig`` metadata and are
    never mutated or materialized by normal instance operations.

``cfg._default``
    An instance-owned clone of the schema plus that instance's reset defaults.
    Constructor values and ``default=`` overrides update this layer without
    changing the class.

``cfg._data``
    Current raw values and realized nested Config objects. Mutable values are
    independent from the reset baseline, so changing current state cannot
    corrupt a later reset or another instance.

These are internal attributes, but the ownership rule is a compatibility
invariant. Public code should use mapping/attribute access and ``load`` rather
than editing them directly.

Input and parser ownership
--------------------------

Mapping objects, files, streams, and inline YAML/JSON share one ingestion
boundary. Flat configs and nested ``SubConfig`` trees therefore agree on source
classification, path errors, empty documents, and mapping-type requirements.

Parser construction also has one canonical route for field ordering, aliases,
flags, coercion, groups, and special options. ``port_to_argparse`` consumes the
same argument specification as the live parser rather than maintaining a
second interpretation of ``Value`` metadata.

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

Runtime validation has two deliberately different cost tiers.

Value validation checks user-supplied values against annotations after
parsing. Its class default is ``'warn'``. Tune it per class or per field:

.. code-block:: python

    class C(kwconf.Config):
        __validate__ = 'error'  # 'warn' | 'error'/True | False
        count: int | None = None

Validation runs on constructor values, data/file values, assignment, parsed
argv values, and parsed env values. Field defaults are accepted as declared.
Unsupported annotation forms are skipped.

``Config.cli`` and ``Config.load`` also accept a per-ingestion ``validate=``
override. It has highest precedence for values ingested by that call, ahead of
field and class policy:

.. code-block:: python

    C.cli(data=payload, argv=False, validate=False)
    C.cli(data=payload, argv=False, validate='warn')
    C.cli(data=payload, argv=False, validate='error')

``None`` is the default. It preserves field/class value validation and avoids
an additional structural traversal. Explicit ``'warn'`` or ``'error'`` enables
structural source checks; ``True`` is an alias for ``'error'``. A class with
``__validate__ = 'error'`` also enables strict structural checks by default.
The class default ``'warn'`` intentionally remains value-only so ordinary CLI
startup stays lean.

Structural validation currently detects contradictory SubConfig selector
spellings within one source, such as both ``inner`` and
``inner.__class__``. Warning mode reports the ambiguity and continues with
safe deterministic precedence; error mode raises
``ConfigValidationError`` before mutation. Overrides from separate sources are
not conflicts: later argv may intentionally override earlier ``data=`` or a
config file.

Safety does not depend on enabling the diagnostic scan. On the lean path an
explicit ``path.__class__`` selector wins over scalar ``path`` sugar, and raw
selector text is never stored in place of a declared SubConfig.

``Config.validate()`` is a separate, side-effect-free static schema gate for
tests/CI. It is not called implicitly by class construction or CLI startup.
Parser-enforced constraints such as ``Literal`` choices also remain hard
errors regardless of runtime validation mode.

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
use a tri-state policy: the call-level ``allow_import`` value is the default,
``SubConfig(..., allow_import=None)`` inherits it, and a field-level True or
False explicitly overrides it. Importable selectors use
``module.qualname.Class`` or ``module:qualname.Class`` syntax.

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
