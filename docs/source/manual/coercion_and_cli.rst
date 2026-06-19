Coercion and CLI Contract
=========================

``kwconf`` keeps scriptconfig's useful CLI behavior but drops its surprising
conversions. The core rule: untyped strings infer **scalars only**. ``"a,b,c"``
stays a string unless the schema explicitly asks for sequence or structured
parsing.

The coercion boundary
---------------------

Coercion happens only at the **text boundary** (argv, env). The **Python
boundary** -- constructor, assignment, a field's own default -- is *trusted*:
values pass through verbatim, no parsing, no runtime type failure.

.. code-block:: python

    import kwconf as kw

    class C(kw.Config):
        x: int = kw.Value('512')        # WYSIWYG: the default stays '512'

    assert C()['x'] == '512'            # Python boundary trusts
    assert C.cli(argv=['--x=512'])['x'] == 512   # text boundary parses

To run the text-boundary path from Python (handy in tests), use
``Config.coerce(**kwargs)`` or the ``from_cli`` / ``from_env`` / ``from_yaml``
adapters. Plain ``MyConfig(x=...)`` stays the trusted, non-coercing path.

Value coercion
--------------

``Value.coerce`` is the field-level text-boundary hook:

1. an explicit ``parser=`` (named or callable) runs that parser;
2. otherwise the default ``'auto'`` infers a scalar from a string -- ``None``,
   ``int``, ``float``, ``complex``, ``bool``, ``str`` (fixed precedence,
   intersected with the annotation);
3. non-string values pass through unchanged.

.. code-block:: python

    assert kw.Value(None).coerce('1') == 1
    assert kw.Value(None).coerce('true') is True
    assert kw.Value(None).coerce('a,b,c') == 'a,b,c'          # NOT split
    assert kw.Value(None, parser='csv').coerce('1,2,3') == [1, 2, 3]
    assert kw.Value(None, parser='yaml').coerce('[1, 2, 3]') == [1, 2, 3]

.. note::

   ``parser=`` is canonical; ``type=`` is a deprecated alias (mutually
   exclusive). Don't use ``parser=list`` to build a list -- ``list('1,2,3')``
   splits into characters. Use ``parser='csv'``, ``parser='yaml'``, or
   ``nargs``.

Parsers: annotation-aware vs unaware
------------------------------------

``'auto'`` (default, aware)
    Scalar inference steered by the annotation; ``str`` is the final catch-all.
    No match and ``str`` disallowed -> silent fallback (the validation layer
    reports the mismatch once -- see :doc:`core_contract`).

``'csv'`` (aware)
    ``'auto'`` mapped over the comma-split, gated by the *element* annotation, so
    ``list[str]`` keeps strings:

    .. code-block:: python

        class C(kw.Config):
            tags: list[str] = kw.Value(default_factory=list, parser='csv')

        assert C.cli(argv=['--tags', '1,2,3o'])['tags'] == ['1', '2', '3o']

``'yaml'`` (unaware)
    ``yaml.safe_load``; produces its own typed structure. Best for polymorphic
    ``list | dict | scalar`` fields:

    .. code-block:: python

        class C(kw.Config):
            data: list | dict | int = kw.Value(None, parser='yaml')

        assert C.cli(argv=['--data=[1,2,3]'])['data'] == [1, 2, 3]
        assert C.cli(argv=["--data={a: 1}"])['data'] == {'a': 1}

Register custom parsers and opt into awareness explicitly; unaware parsers keep
the single-argument ``str -> value`` contract:

.. code-block:: python

    from kwconf.coerce import register_parser, element_annotation, auto

    def head_csv(token, annotation):                  # aware: gets annotation
        elem = element_annotation(annotation)
        return [auto(p, elem) for p in token.split(',')][:1]

    register_parser('head_csv', head_csv, annotation_aware=True)

``nargs`` with a parser
-----------------------

Uniform rule, no special cases: the parser is applied to **each token** and the
results **collect** into a list (no concat). Result depth = parser-output depth
+ 1 for the wrapper:

.. code-block:: python

    class C(kw.Config):
        key: list[int] = kw.Value(default_factory=list, parser='csv', nargs='*')

    assert C.cli(argv=['--key=1,2,3'])['key'] == [[1, 2, 3]]
    assert C.cli(argv=['--key', '1,2', '3'])['key'] == [[1, 2], [3]]

So ``csv + nargs`` is defined but rarely useful: use commas **or** spaces, not
both. The old dual-form (``--k a,b,c`` == ``--k a b c``) is intentionally
dropped -- it needed a concat special case and was ambiguous for structured
tokens.

Annotations also feed metadata -- e.g. ``Literal`` becomes choices:

.. code-block:: python

    import typing

    class C(kw.Config):
        mode: typing.Literal['fast', 'safe'] = 'fast'

    assert list(C.__default__['mode'].parsekw['choices']) == ['fast', 'safe']

Useful CLI behavior
-------------------

``kwconf`` keeps the ergonomic scriptconfig pieces:

* long/short options, long aliases, fuzzy underscore-to-hyphen variants;
* flexible booleans (``--flag``, ``--flag=false``, ``--no-flag``);
* counters (``-vvv``, ``--verbose=3``);
* ``nargs``, positionals, display groups, mutex groups;
* opt-in special options: ``--config``, ``--dump``, ``--dumps``.

.. code-block:: python

    class RunConfig(kw.Config):
        __fuzzy_hyphens__ = 1
        workers: int = 0
        verbose = kw.Value(0, short_alias=['v'], isflag='counter')
        dry_run = kw.Flag(False, alias=['dryrun'])
        tags: list[str] = kw.Value(default_factory=list, nargs='+')

    cfg = RunConfig.cli(argv=['--workers=4', '-vvv', '--dry-run', '--tags', 'a', 'b'])
    assert (cfg.workers, cfg.verbose, cfg.dry_run, cfg.tags) == (4, 3, True, ['a', 'b'])

Special options are off by default; opt in per call or with
``__special_options__ = True`` on the class:

.. code-block:: python

    class Dumpable(kw.Config):
        __special_options__ = True
        x: int = 1

    Dumpable.cli(argv=['--x=2', '--dumps'])     # prints YAML and exits
