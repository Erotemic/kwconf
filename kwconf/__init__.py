"""
kwconf
======

`kwconf` is an experimental successor to `scriptconfig` that keeps the
high-value CLI and config-file features while moving toward a simpler typed
configuration model.

Preferred usage:

.. code:: python

    import kwconf as kw


    class MyConfig(kw.Config):
        x: int = 1
        y: str = 'foo'
        tags: list[str] = kw.Value(default_factory=list)


    config = MyConfig.cli(argv=['--x=3'])
    assert config.x == 3

`Value(...)` remains the place for CLI metadata such as help text, aliases,
choices, flags, and positional behavior.
"""

__autogen__ = """
Ignore:
    mkinit ~/code/kwconf/kwconf/__init__.py --nomods --relative --diff
    mkinit ~/code/kwconf/kwconf/__init__.py --nomods --relative -w
"""

__version__ = '0.9.2'

__submodules__ = {
    'modal': None,
    'config': None,
    'value': None,
    'cli': None,
    'dataconfig': None,
    'annotations': None,
}

from typing import Any, Callable, Optional, Sequence, TypeVar, Union, cast

import ubelt as ub

from . import diagnostics  # NOQA
from .modal import (ModalCLI, ModalValue)
from .config import (Config, define,)
from .value import _Value as ValueClass, _Flag as FlagClass
from .dataconfig import (dataconf,)
from .subconfig import (SubConfig,)

_T = TypeVar('_T')

# Sentinel meaning "no default was supplied". Typed ``Any`` so that a field with
# no positional default (``Value(required=True)`` / ``Value(default_factory=...)``)
# lets the field type be inferred from the *annotation* rather than the sentinel.
_NODEFAULT: Any = ub.NoParam


# The runtime field-metadata wrappers live in ``kwconf.value`` as the classes
# ``_Value`` / ``_Flag``. The PUBLIC ``kwconf.Value`` / ``kwconf.Flag`` are thin
# factory *functions* that construct one of those classes but are typed to return
# the field's value type ``T`` (the attrs ``field()`` pattern), so that
# ``x: int = Value(None)`` is a static type error and ``cfg.x`` reads as ``int``.
# Internals isinstance/construct against ``kwconf.value._Value`` (also exposed as
# ``kwconf.ValueClass``); these public callables are what users import.
def Value(
    default: _T = _NODEFAULT,
    type: Any = None,
    help: Optional[str] = None,
    choices: Optional[Sequence[Any]] = None,
    position: Optional[int] = None,
    isflag: Union[bool, str] = False,
    nargs: Optional[Any] = None,
    alias: Optional[Sequence[str]] = None,
    required: bool = False,
    short_alias: Optional[Sequence[str]] = None,
    group: Optional[str] = None,
    mutex_group: Optional[str] = None,
    tags: Optional[Any] = None,
    *,
    default_factory: Optional[Callable[[], Any]] = None,
    parser: Any = None,
    validate: Optional[Union[bool, str]] = None,
) -> _T:
    """
    Declare a config field, attaching CLI / parsing metadata to a default value.

    Returns a :class:`kwconf.value._Value` wrapper at runtime, but is *typed* as
    the field's value type ``T`` so that the default is checked against the field
    annotation (``x: int = Value(None)`` is a static error) and ``cfg.x`` reads
    as ``int``. Use a bare attribute (``x: int = 5``) when you need no metadata.

    Args:
        default (T):
            The default value. Omit it for a required field (``required=True``)
            or when using ``default_factory``. A *string* default is parsed at
            the text boundary, never on plain Python assignment.

        type (type | str | Callable | None):
            DEPRECATED alias for ``coerce`` (kept for back-compat); mutually
            exclusive with it. Also sets the argparse ``type``.

        help (str | None):
            CLI help text for this option.

        choices (Sequence | None):
            Restrict accepted CLI values to this set (argparse ``choices``).

        position (int | None):
            If set, allow this field as a positional CLI argument at this index
            (1-based). Fields sharing a position conflict.

        isflag (bool | str):
            If True, parse as a boolean flag; ``'counter'`` for a count flag.
            Prefer :func:`Flag` for boolean flags.

        nargs (int | str | None):
            argparse ``nargs`` (e.g. ``'+'``, ``'*'``, ``'?'``, or an int). For
            container fields each token is coerced as the element type.

        alias (Sequence[str] | None):
            Additional long option names (each prefixed with ``--``).

        required (bool):
            If True, the CLI requires this option. Mutually exclusive with a
            supplied default.

        short_alias (Sequence[str] | None):
            Short option names (each prefixed with ``-``), e.g. ``['n']``.

        group (str | None):
            Display-only: group options with the same value in CLI help.

        mutex_group (str | None):
            Mark options that are mutually exclusive on the command line.

        tags (Any):
            Free-form metadata for external program use.

        default_factory (Callable[[], Any] | None):
            Zero-argument callable producing the default; mutually exclusive with
            ``default``. Use for mutable defaults (e.g. ``default_factory=list``).

        parser (Callable | str | None):
            How to parse a *string* input into a value (the text-boundary
            parser): a callable ``str -> value`` or a registry key such as
            ``'auto'`` (annotation-gated, the default), ``'yaml'``, or ``'csv'``.
            See :mod:`kwconf.coerce`. Preferred over ``type``.

        validate (bool | str | None):
            Opt into post-coerce annotation validation. ``None`` inherits the
            class ``__validate__``; ``'warn'`` warns; ``'error'`` / ``True``
            raises; ``False`` disables.

    Returns:
        T: typed as the field value type (a ``_Value`` wrapper at runtime).

    Example:
        >>> import kwconf
        >>> class Cfg(kwconf.Config):
        >>>     epochs: int = kwconf.Value(10, help='number of epochs')
        >>>     name: str | None = kwconf.Value(None, alias=['n'])
        >>> assert Cfg(epochs=3)['epochs'] == 3
    """
    # Runtime returns a _Value wrapper; the signature lies (-> _T) so the
    # default is checked against the field annotation. cast keeps the checker
    # happy about the wrapper-vs-T mismatch (the attrs field() pattern).
    return cast(_T, ValueClass(
        default, type=type, help=help, choices=choices, position=position,
        isflag=isflag, nargs=nargs, alias=alias, required=required,
        short_alias=short_alias, group=group, mutex_group=mutex_group,
        tags=tags, default_factory=default_factory, parser=parser,
        validate=validate,
    ))


def Flag(
    default: bool = False,
    help: Optional[str] = None,
    *,
    alias: Optional[Sequence[str]] = None,
    short_alias: Optional[Sequence[str]] = None,
    group: Optional[str] = None,
    mutex_group: Optional[str] = None,
    required: bool = False,
    position: Optional[int] = None,
    tags: Optional[Any] = None,
    parser: Any = None,
    validate: Optional[Union[bool, str]] = None,
) -> bool:
    """
    Declare a boolean flag field: like :func:`Value` but with flag semantics
    (supports both ``--flag`` and ``--flag=value`` on the CLI). Typed to return
    ``bool``. See :func:`Value` for the shared keyword arguments.
    """
    return cast(bool, FlagClass(
        default, help=help, alias=alias, short_alias=short_alias, group=group,
        mutex_group=mutex_group, required=required, position=position,
        tags=tags, parser=parser, validate=validate,
    ))

__all__ = ['Config', 'Value', 'Flag',
           'dataconf', 'define', 'ModalCLI', 'ModalValue', 'SubConfig']
