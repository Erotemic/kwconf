Coercion and CLI Contract
=========================

``kwconf`` parses strings from string-only sources: ``sys.argv`` tokens and
``os.environ`` values. Python kwargs, assignment, defaults, and typed YAML/JSON
values are used as Python values.

The user-facing rule
--------------------

.. code-block:: python

    import kwconf


    class C(kwconf.Config):
        x = kwconf.Value('512')


    assert C()['x'] == '512'
    assert C.cli(argv=['--x=512'])['x'] == 512

``Config.coerce(**kwargs)`` and ``from_cli`` / ``from_env`` adapters opt into
the same string parsing path from Python. ``from_yaml`` loads YAML/JSON values
with the types supplied by the file format.

What a parser does
------------------

A parser tells one field how to read a CLI/env string. Set it with
``Value(..., parser=...)``. The parser can be a named parser or a callable.

.. code-block:: python

    import kwconf


    assert kwconf.Value(None).coerce('1') == 1
    assert kwconf.Value(None).coerce('true') is True
    assert kwconf.Value(None).coerce('a,b,c') == 'a,b,c'
    assert kwconf.Value(None, parser='csv').coerce('1,2,3') == [1, 2, 3]
    assert kwconf.Value(None, parser='yaml').coerce('[1, 2, 3]') == [1, 2, 3]

``parser=`` is the canonical spelling. ``type=`` is a deprecated alias for
migration.

Default parsers
---------------

``auto``
    The default parser. It reads one scalar from one string: ``None``, ``int``,
    ``float``, ``complex``, ``bool``, or ``str``. With an annotation, it uses
    the compatible scalar choices. Comma strings remain strings.

``csv``
    Splits on commas and applies ``auto`` to each item. Use it for compact
    list-valued CLI/env fields.

``yaml``
    Runs ``yaml.safe_load`` on the string. Use it for values that may be a
    list, dict, scalar, or nested structure. Install ``kwconf[yaml]`` for YAML
    support.

.. code-block:: python

    class C(kwconf.Config):
        scalar = kwconf.Value(None)                         # auto
        nums = kwconf.Value(default_factory=list, parser='csv')
        data = kwconf.Value(None, parser='yaml')


    cfg = C.cli(argv=['--scalar=3', '--nums=1,2,3', '--data={a: 1}'])
    assert cfg.scalar == 3
    assert cfg.nums == [1, 2, 3]
    assert cfg.data == {'a': 1}

Annotations can refine parser output:

.. code-block:: python

    class C(kwconf.Config):
        tags: list[str] = kwconf.Value(default_factory=list, parser='csv')
        nums: list[int] = kwconf.Value(default_factory=list, parser='csv')


    assert C.cli(argv=['--tags=1,2'])['tags'] == ['1', '2']
    assert C.cli(argv=['--nums=1,2'])['nums'] == [1, 2]

List input
----------

Use ``nargs`` for space-separated CLI lists:

.. code-block:: python

    class C(kwconf.Config):
        tags = kwconf.Value(default_factory=list, nargs='+')


    cfg = C.cli(argv=['--tags', 'cat', 'dog'])
    assert cfg.tags == ['cat', 'dog']

Use ``parser='csv'`` for comma-separated strings:

.. code-block:: python

    class C(kwconf.Config):
        tags = kwconf.Value(default_factory=list, parser='csv')


    cfg = C.cli(argv=['--tags=cat,dog'])
    assert cfg.tags == ['cat', 'dog']

Use ``parser='yaml'`` for nested text:

.. code-block:: python

    class C(kwconf.Config):
        payload = kwconf.Value(None, parser='yaml')


    cfg = C.cli(argv=['--payload={names: [cat, dog], enabled: true}'])
    assert cfg.payload == {'names': ['cat', 'dog'], 'enabled': True}

Custom parsers
--------------

Register a named parser when the same string format appears in several fields.
A normal parser accepts one string and returns one Python value.

.. code-block:: python

    import pathlib
    import kwconf
    from kwconf.coerce import register_parser


    def path_list(text):
        return [pathlib.Path(p).expanduser() for p in text.split(':') if p]


    register_parser('path_list', path_list)


    class C(kwconf.Config):
        inputs = kwconf.Value(default_factory=list, parser='path_list')

For parsers that should consult the field annotation, register with
``annotation_aware=True`` and accept ``(text, annotation)``.

Validation
----------

Validation checks user-supplied values against annotations after parsing. The
default policy is ``'warn'``. Set ``__validate__ = 'error'`` for stricter CLIs
or ``False`` to disable validation.

.. code-block:: python

    class C(kwconf.Config):
        __validate__ = 'error'
        count: int = 0


    C.cli(argv=['--count=3'])

See :doc:`core_contract` for the full validation contract.
