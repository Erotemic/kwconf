The kwconf Module
=================

|Pypi| |PypiDownloads| |ReadTheDocs| |GithubActions| |Codecov| |GitlabCIPipeline| |GitlabCICoverage|

``kwconf`` provides typed, dependency-free configuration objects that parse
**consistently** from Python keyword arguments, the command line, the
environment, and config files. It is a successor to
`scriptconfig <https://pypi.org/project/scriptconfig>`_, keeping the useful
ergonomics while dropping the footguns (most notably, comma-strings no longer
silently split into lists).

+-----------------+-----------------------------------------+
| Read the Docs   | http://kwconf.readthedocs.io/en/latest/ |
+-----------------+-----------------------------------------+
| Github          | https://github.com/Erotemic/kwconf      |
+-----------------+-----------------------------------------+
| Pypi            | https://pypi.org/project/kwconf         |
+-----------------+-----------------------------------------+


Features
--------

* **One model, many inputs.** CLI, kwargs, env, and files map onto the same
  field model.
* **Trust at the Python boundary, parse at the text boundary.** ``Config(x='1')``
  keeps ``'1'``; ``--x=1`` parses it. Defaults are WYSIWYG.
* **Progressive typing.** Stays simple untyped; add annotations to harden.
  ``Value`` / ``Flag`` are typed so ``x: int = Value(None)`` is a *static* error
  on ty, mypy, and pyright. Ships ``py.typed``.
* **Zero required dependencies.** YAML and the ubelt-backed niceties are optional
  extras.
* Modal subcommand CLIs, nested configs with dotted overrides, argparse
  round-tripping, and YAML/JSON load/dump.


Installation
------------

.. code-block:: bash

    pip install kwconf

    # optional extras
    pip install kwconf[yaml]    # YAML config load/dump and parser='yaml'
    pip install kwconf[ubelt]   # rich repr, Config.__json__, port_to_argparse


Quickstart
----------

.. code-block:: python

    import kwconf as kw

    class DemoConfig(kw.Config):
        count: int = 1
        mode: str = kw.Value('fast', choices=['fast', 'safe'])
        tags: list[str] = kw.Value(default_factory=list, nargs='+')

    cfg = DemoConfig.cli(argv=['--count=3', '--mode=safe', '--tags', 'a', 'b'])
    assert cfg.count == 3
    assert cfg.mode == 'safe'
    assert cfg.tags == ['a', 'b']

See the `documentation <http://kwconf.readthedocs.io/en/latest/>`_ for the
coercion model, nested configs, modal CLIs, and a scriptconfig migration guide.


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
