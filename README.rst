kwconf
======

|Pypi| |PypiDownloads| |ReadTheDocs| |GithubActions| |Codecov| |GitlabCIPipeline| |GitlabCICoverage|

``kwconf`` defines small configuration objects that work from Python kwargs,
command line arguments, environment variables, and JSON/YAML files. It is the
successor to `scriptconfig <https://pypi.org/project/scriptconfig>`_, with the
same small-script ergonomics and a clearer parser model.

+-----------------+-----------------------------------------+
| Read the Docs   | http://kwconf.readthedocs.io/en/latest/ |
+-----------------+-----------------------------------------+
| Github          | https://github.com/Erotemic/kwconf      |
+-----------------+-----------------------------------------+
| Pypi            | https://pypi.org/project/kwconf         |
+-----------------+-----------------------------------------+

Features
--------

* Define config once, then read it from kwargs, argv, env, or files.
* Use the object like a dataclass, dict, or argparse namespace.
* Start with plain defaults. Add ``Value`` for help text, aliases, choices,
  flags, positions, ``nargs``, default factories, or a custom parser.
* Coerce only string-only sources: ``sys.argv`` tokens and ``os.environ``
  values. Python values are used as Python values.
* Use the default parsers: ``auto`` for scalars, ``csv`` for comma lists, and
  ``yaml`` for YAML-shaped values.
* Build argparse-backed CLIs, modal subcommands, nested config trees, dotted
  overrides, and YAML/JSON load/dump.
* Ship with ``py.typed`` and zero required runtime dependencies.

Installation
------------

.. code-block:: bash

    pip install kwconf

    # optional extras
    pip install kwconf[yaml]    # YAML config load/dump and parser='yaml'
    pip install kwconf[ubelt]   # rich repr, Config.__json__, port_to_argparse

Quickstart
----------

Start with plain class attributes. Type annotations are optional.

.. code-block:: python

    import kwconf


    class DemoConfig(kwconf.Config):
        count = 1
        mode = kwconf.Value('fast', choices=['fast', 'safe'])
        tags = kwconf.Value(default_factory=list, nargs='+')


    cfg = DemoConfig.cli(argv=['--count=3', '--mode=safe', '--tags', 'a', 'b'])
    assert cfg.count == 3
    assert cfg['mode'] == 'safe'
    assert cfg.tags == ['a', 'b']

The same class works from Python, files, env, or argv:

.. code-block:: python

    cfg = DemoConfig(count=2)
    cfg = DemoConfig().load({'count': 2})
    cfg = DemoConfig.cli(data={'count': 2}, argv=False)
    cfg = DemoConfig.cli(argv='--count=2 --mode=safe')
    cfg = DemoConfig.from_env(prefix='DEMO_')
    cfg = DemoConfig.from_yaml('demo.yaml')

Parser basics
-------------

A parser tells a field how to read a CLI/env string.

.. code-block:: python

    import kwconf


    class ParserConfig(kwconf.Config):
        scalar = kwconf.Value(None)                         # parser='auto'
        nums = kwconf.Value(default_factory=list, parser='csv')
        payload = kwconf.Value(None, parser='yaml')


    cfg = ParserConfig.cli(argv=[
        '--scalar=3',
        '--nums=1,2,3',
        '--payload={enabled: true, size: 4}',
    ])
    assert cfg.scalar == 3
    assert cfg.nums == [1, 2, 3]
    assert cfg.payload == {'enabled': True, 'size': 4}

``auto`` reads scalar strings such as ``3``, ``true``, and ``null``.
``csv`` splits commas and applies ``auto`` to each part. ``yaml`` uses
``yaml.safe_load`` for lists, dicts, and scalars; install ``kwconf[yaml]`` for
that parser. See the `coercion manual
<http://kwconf.readthedocs.io/en/latest/manual/coercion_and_cli.html>`_ for
the detailed parser contract.

Growing a script
----------------

``kwconf`` is designed for scripts that start as a dictionary and grow into a
CLI with minimal churn.

.. code-block:: python

    import kwconf


    class MyConfig(kwconf.Config):
        simple_option1 = 1
        simple_option2 = 2


    def main(argv=None, **kwargs):
        config = MyConfig.cli(argv=argv, data=kwargs)
        return run_algorithm(config)


    def run_algorithm(config):
        # Existing dict-style code can keep using config['simple_option1'].
        ...

Add metadata where the CLI needs it:

.. code-block:: python

    class MyConfig(kwconf.Config):
        simple_option1 = kwconf.Value(1, help='first simple option')
        simple_option2 = kwconf.Value(2, help='second simple option')

Typed path
----------

Annotations improve static checks, editor help, parser selection, and runtime
validation.

.. code-block:: python

    class TrainConfig(kwconf.Config):
        lr: float = 1e-3
        mode: str = kwconf.Value('fast', choices=['fast', 'safe'])
        tags: list[str] = kwconf.Value(default_factory=list, nargs='+')


    cfg = TrainConfig.cli(argv=['--lr=0.01', '--tags', 'cat', 'dog'])
    assert cfg.lr == 0.01
    assert cfg.tags == ['cat', 'dog']

Runnable examples
-----------------

The checked-in examples live in ``examples/``. Run commands from the repo root:

.. code-block:: bash

    python examples/01_minimal_config.py --help
    python examples/01_minimal_config.py --width=128 --height=96 --method=lanczos --dst=thumb.png --tags demo small --dry-run
    python examples/03_config_files.py --config examples/data/report.yaml --limit=3 --format=json
    python examples/run_all.py

Use ``examples/README.md`` as the map. Each example focuses on one surface:
basic configs, CLI flags, files, nested configs, modals, large app structure,
and migration helpers.

Scriptconfig migration
----------------------

Use the migration guide when porting existing code or prompting an LLM that
already knows scriptconfig.

* ``import scriptconfig as scfg`` -> ``import kwconf``.
* ``scfg.Config`` / ``scfg.DataConfig`` -> ``kwconf.Config``.
* ``type=`` -> ``parser=`` for new code.
* ``cmdline=`` -> ``argv=``. Recent scriptconfig already supports ``argv``;
  older examples often emphasize ``cmdline``.
* ``--config`` / ``--dump`` / ``--dumps`` are opt-in via
  ``special_options=True`` or ``__special_options__ = True``.
* Comma-separated CLI strings stay strings. Use ``nargs='+'``,
  ``parser='csv'``, or ``parser='yaml'`` for structured text input.

See the `migration guide
<http://kwconf.readthedocs.io/en/latest/manual/migration_from_scriptconfig.html>`_
for the checklist, footguns, and exact replacements.

Next steps
----------

Read the `documentation <http://kwconf.readthedocs.io/en/latest/>`_ for the
core contract, parser model, nested configs, modal CLIs, and migration notes.
The ``examples/`` directory contains runnable scripts for the main patterns.


Related Work
------------

``kwconf`` sits at the intersection of argument parsing, settings management,
and typed data models. Like its predecessor `scriptconfig
<https://pypi.org/project/scriptconfig/>`_, it builds on the standard library
`argparse <https://docs.python.org/3/library/argparse.html>`_, but adds flags
that double as key/value pairs, defaults drawn from kwargs / env / files, and
the ability to call a CLI as a plain Python function.

Closely related / complementary
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* `jsonargparse <https://jsonargparse.readthedocs.io/>`_ -- argparse plus config
  files and class / dataclass / pydantic signatures (and the engine behind
  Lightning's CLI). Its nested-configuration support is complementary to
  ``kwconf`` and a natural integration target.
* `configargparse <https://pypi.org/project/ConfigArgParse/>`_ -- augments
  argparse with config-file and env-var defaults, but is more limited and does
  not handle the "call the CLI as a Python function" use case well.

Typed classes to CLIs
~~~~~~~~~~~~~~~~~~~~~~~

Like ``kwconf``, these derive a parser from a class of typed fields (most via
:pep:`681` ``dataclass_transform``):

* `pydantic <https://pypi.org/project/pydantic/>`_ /
  `pydantic-settings <https://pypi.org/project/pydantic-settings/>`_ --
  validated data models and layered settings (env, dotenv, secrets).
* `pydantic-cli <https://pypi.org/project/pydantic-cli/>`_ -- an argparse CLI
  built from a pydantic model.
* `simple-parsing <https://pypi.org/project/simple-parsing/>`_ -- adds
  dataclasses to ``argparse``.
* `tyro <https://github.com/brentyi/tyro>`_ -- typed CLIs from dataclasses,
  functions, and unions.
* `typer <https://typer.tiangolo.com/>`_ -- ``click``-based CLIs from type hints.

CLI frameworks
~~~~~~~~~~~~~~~

* `click <https://pypi.org/project/click/>`_ -- composable decorator-based CLIs.
* `fire <https://pypi.org/project/fire/>`_ -- generates a CLI from arbitrary
  Python objects.

Hierarchical configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* `Hydra <https://hydra.cc/>`_ / `OmegaConf
  <https://omegaconf.readthedocs.io/>`_ -- composable, hierarchical YAML
  configuration with command-line overrides.

Standard-library building blocks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* `dataclasses <https://docs.python.org/3/library/dataclasses.html>`_ and
  `attrs <https://pypi.org/project/attrs/>`_ -- the field-with-default class
  pattern (formalized by :pep:`681`) that ``kwconf``'s static typing surface
  mirrors.


.. |Pypi| image:: https://img.shields.io/pypi/v/kwconf.svg
    :target: https://pypi.python.org/pypi/kwconf

.. |PypiDownloads| image:: https://img.shields.io/pypi/dm/kwconf.svg
    :target: https://pypistats.org/packages/kwconf

.. |ReadTheDocs| image:: https://readthedocs.org/projects/kwconf/badge/?version=latest
    :target: http://kwconf.readthedocs.io/en/latest/

.. |GithubActions| image:: https://github.com/Erotemic/kwconf/actions/workflows/tests.yml/badge.svg
    :target: https://github.com/Erotemic/kwconf/actions?query=branch%3Amain

.. |Codecov| image:: https://codecov.io/github/Erotemic/kwconf/badge.svg?branch=main&service=github
    :target: https://codecov.io/github/Erotemic/kwconf?branch=main

.. |GitlabCIPipeline| image:: https://gitlab.kitware.com/Erotemic/kwconf/badges/main/pipeline.svg
    :target: https://gitlab.kitware.com/Erotemic/kwconf/-/jobs

.. |GitlabCICoverage| image:: https://gitlab.kitware.com/Erotemic/kwconf/badges/main/coverage.svg
    :target: https://gitlab.kitware.com/Erotemic/kwconf/commits/main
