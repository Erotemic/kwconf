Coercion and CLI Contract
=========================

``kwconf`` keeps the useful command-line behavior from ``scriptconfig`` while
removing the most surprising implicit conversions.  The important rule is that
untyped strings only infer scalar values by default.  A value such as
``"a,b,c"`` stays a string unless the schema explicitly asks for sequence or
structured parsing.

Value coercion
--------------

``Value.coerce`` is the field-level coercion hook.  It applies a small,
predictable policy:

1. named parsers such as ``type='yaml'`` run their registered parser;
2. explicit runtime types or callables are used when supplied;
3. untyped strings infer only scalar values: ``int``, ``float``, ``complex``,
   ``bool``, or ``None``;
4. non-string values are returned unchanged unless an explicit type asks for a
   cast.

.. code-block:: python

    import kwconf as kw

    assert kw.Value(None).coerce('1') == 1
    assert kw.Value(None).coerce('true') is True
    assert kw.Value(None).coerce('None') is None
    assert kw.Value(None).coerce('a,b,c') == 'a,b,c'

Structured parsing is explicit:

.. code-block:: python

    assert kw.Value(None, type=list).coerce('1,2,3') == [1, 2, 3]
    assert kw.Value(None, type='yaml').coerce('[1, 2, 3]') == [1, 2, 3]

Annotations can enrich metadata.  For example, ``Literal`` annotations become
choices, and runtime validation can use annotations when ``__validate__`` is
enabled.

.. code-block:: python

    import typing

    class C(kw.Config):
        mode: typing.Literal['fast', 'safe'] = 'fast'

    assert list(C.__default__['mode'].parsekw['choices']) == ['fast', 'safe']

Useful CLI behavior
-------------------

``kwconf`` intentionally keeps the ergonomic pieces that made ``scriptconfig``
useful:

* long and short options;
* long aliases and fuzzy underscore-to-hyphen variants;
* flexible booleans, including ``--flag``, ``--flag=false``, and
  ``--no-flag``;
* counters such as ``-vvv`` and ``--verbose=3``;
* ``nargs`` for explicit list input;
* positional arguments;
* display groups and mutually exclusive groups;
* opt-in special options: ``--config``, ``--dump``, and ``--dumps``.

.. code-block:: python

    class RunConfig(kw.Config):
        __fuzzy_hyphens__ = 1
        workers: int = 0
        verbose = kw.Value(0, short_alias=['v'], isflag='counter')
        dry_run = kw.Flag(False, alias=['dryrun'])
        tags: list[str] = kw.Value(default_factory=list, nargs='+')

    cfg = RunConfig.cli(argv=['--workers=4', '-vvv', '--dry-run', '--tags', 'a', 'b'])
    assert cfg.workers == 4
    assert cfg.verbose == 3
    assert cfg.dry_run is True
    assert cfg.tags == ['a', 'b']

Special options are off by default.  Opt in per call or at the class level:

.. code-block:: python

    class Dumpable(kw.Config):
        __special_options__ = True
        x: int = 1

    # Prints YAML and exits.
    Dumpable.cli(argv=['--x=2', '--dumps'])

Compatibility note
------------------

The module :mod:`kwconf.smartcast` remains as a small internal and legacy import
location.  New code should use ``Value.coerce`` and explicit ``Value(type=...)``
settings rather than importing ``smartcast`` directly.
