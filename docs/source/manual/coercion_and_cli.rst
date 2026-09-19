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

CLI spelling invariants
-----------------------

Kwconf delegates parsing to :mod:`argparse`, but it intentionally adds a small
set of CLI spelling rules. These rules are part of kwconf's public contract,
not accidental consequences of a particular ``argparse.Action``.

1. **Every CLI key can be assigned explicitly.** A boolean flag is not limited
   to presence/absence. All of these are meaningful kwconf spellings::

       --flag
       --flag=false
       --flag false

   This is intentional. An explicit command line can show that a setting was
   considered and disabled instead of making the setting disappear from the
   command merely because its value is false.

2. **Options may have a bare form.** *Bare* is the kwconf term for an option
   occurrence with no explicit value. ``Flag(False)`` has a built-in bare
   meaning of true. A counter's bare meaning is increment. For an ordinary
   value, define the bare result explicitly with ``bare=``::

       class C(kwconf.Config):
           patch = kwconf.Value(None, bare='auto', short_alias=['p'])

   The resulting forms are::

       --patch              # -> 'auto' (bare)
       --patch=archive.tar  # -> 'archive.tar' (explicit)
       --patch archive.tar  # -> 'archive.tar' (explicit)
       -p                   # -> 'auto' (bare)
       -p=archive.tar       # -> 'archive.tar' (explicit)
       -p archive.tar       # -> 'archive.tar' (explicit)

   ``bare=...`` is the semantic kwconf API over argparse's lower-level
   ``nargs='?'`` / ``const=...`` mechanism and implies ``nargs='?'``.

3. **A bare-capable option may consume the following token.** Therefore
   ``--flag input.txt`` assigns ``input.txt`` to ``flag`` rather than assuming
   that it is positional. Use the standard end-of-options separator when the
   option should stay bare::

       prog --flag -- input.txt
       prog -p -- .

4. **Bare-capable short aliases cluster and never use undelimited attached
   values.** With ``-f`` and ``-v`` registered as bare-capable aliases::

       -fv       # -> -f -v
       -vvf      # -> -v -v -f
       -f=false  # explicit assignment
       -f false  # explicit assignment

   ``-ffalse`` does *not* mean ``-f false``. This avoids the intrinsic ambiguity
   between an attached optional value and a short-option cluster. Use ``=`` or
   a separate token for an explicit value.

5. **Ordinary required-value short options retain argparse syntax.** If ``-k``
   is an ordinary value-taking option, ``-k value``, ``-k=value``, and the
   traditional ``-kVALUE`` spelling remain accepted. Kwconf does not need to
   promote the compact spelling in documentation or generated examples. A
   required-value option can terminate a cluster, so ``-vkfoo`` is interpreted
   as ``-v -kfoo`` when ``-v`` is bare-capable and ``-k`` takes a value.

6. **``--`` ends option interpretation.** This is the standard escape hatch
   whenever an otherwise ambiguous token must be positional.

7. **Kwconf lexical conveniences are configurable.** Hyphen/underscore long
   option matching is controlled by ``__fuzzy_hyphens__``. Bare-capable short
   clustering is controlled by ``__short_alias_clusters__``. Set either to
   ``False`` to move that part of the grammar closer to raw argparse behavior.
   Parser construction also has corresponding per-call controls::

       parser = cfg.argparse(
           fuzzy_hyphens=False,
           short_alias_clusters=False,
       )

The short-cluster rule is deliberately lexical and narrow. Kwconf normalizes a
compact token before handing it to argparse; it does not replace argparse's
cross-token parsing, conversion, ``nargs``, positional, subparser, or error
machinery.

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

Value validation checks user-supplied values against annotations after
parsing. The class default is ``'warn'``. Set ``__validate__ = 'error'`` for a
strict application or ``False`` to disable value checks.

.. code-block:: python

    class C(kwconf.Config):
        __validate__ = 'error'
        count: int = 0


    C.cli(argv=['--count=3'])

For a per-invocation policy, pass ``validate=`` to :meth:`Config.cli` or
:meth:`Config.load`:

.. code-block:: python

    C.cli(argv=False, data=payload, validate=False)    # lean path
    C.cli(argv=False, data=payload, validate='warn')   # diagnose and continue
    C.cli(argv=False, data=payload, validate='error')  # diagnose and raise

The distinction is intentional. The default ``validate=None`` preserves the
existing class/field annotation policy but does not perform an additional
structural scan of each input source. Explicit ``'warn'`` or ``'error'`` also
checks structural ambiguities such as providing both ``inner`` and
``inner.__class__`` for the same SubConfig. ``__validate__ = 'error'`` opts a
class into those strict structural checks without repeating the argument at
each call. The baseline loader remains safe without the scan: the explicit
``.__class__`` selector wins and a SubConfig node is never replaced by raw
selector text.

This runtime policy is separate from ``MyConfig.validate()``, the opt-in static
schema check intended for tests and CI.

See :doc:`core_contract` for the full validation contract.
