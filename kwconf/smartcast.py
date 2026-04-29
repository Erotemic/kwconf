from __future__ import annotations

from typing import Any, Callable, Optional

__all__ = ['smartcast']

NoneType = type(None)


def smartcast(item: Any,
              astype: Any = None,
              strict: bool = False) -> Any:
    r"""
    Convert a string into a standard python type.

    In many cases this is a simple alternative to `eval`. However, the syntax
    rules used here are more permissive and forgiving.

    When ``astype`` is None, the inferred candidates are int, float, complex,
    bool, and None, in that order. Sequences (list, tuple, set) are NOT
    inferred -- pass an explicit ``astype`` to opt into sequence parsing.
    This is a deliberate departure from scriptconfig: a value like
    ``"a,b,c"`` stays the literal string instead of becoming a list.

    Args:
        item (str | Any):
            data to be coerced. Non-strings are returned as-is when
            ``astype`` is None.

        astype (type | None):
            if None, infer the best scalar type. If ``eval`` (or ``'eval'``),
            evaluate the literal. Otherwise, cast to this type.
            Defaults to None.

        strict (bool):
            if True raises a TypeError when no inference candidate succeeds.
            Default to False.

    Returns:
        Any: the coerced item.

    Raises:
        TypeError: when ``strict`` is True and inference fails.

    Example:
        >>> # Simple cases
        >>> print(repr(smartcast('?')))
        >>> print(repr(smartcast('1')))
        >>> print(repr(smartcast('1,2,3')))
        >>> print(repr(smartcast('abc')))
        '?'
        1
        '1,2,3'
        'abc'

    Example:
        >>> from kwconf.smartcast import *
        >>> assert smartcast('?') == '?'
        >>> assert smartcast('1') == 1
        >>> assert smartcast('1.0') == 1.0
        >>> assert smartcast('1.2') == 1.2
        >>> assert smartcast('True') is True
        >>> assert smartcast('false') is False
        >>> assert smartcast('None') is None
        >>> assert smartcast('1', str) == '1'
        >>> assert smartcast('1', eval) == 1
        >>> assert smartcast('1', bool) is True
        >>> assert smartcast('[1,2]', eval) == [1, 2]
        >>> assert smartcast('a,b') == 'a,b'
        >>> assert smartcast('a,b', list) == ['a', 'b']

    Example:
        >>> def check_typed_value(item, want, astype=None):
        >>>     got = smartcast(item, astype)
        >>>     assert got == want and isinstance(got, type(want)), (
        >>>         'Cast {!r} to {!r}, but got {!r}'.format(item, want, got))
        >>> check_typed_value('?', '?')
        >>> check_typed_value('1', 1)
        >>> check_typed_value('1.0', 1.0)
        >>> check_typed_value('1.2', 1.2)
        >>> check_typed_value('True', True)
        >>> check_typed_value('None', None)
        >>> check_typed_value('1', 1, int)
        >>> check_typed_value('1', True, bool)
        >>> check_typed_value('1', 1.0, float)
        >>> check_typed_value(1, 1.0, float)
        >>> check_typed_value(1.0, 1.0)
        >>> check_typed_value([1.0], (1.0,), 'tuple')
    """
    if callable(astype):
        if getattr(astype, '__name__', '') in {'smartcast', '_smart_type'}:
            astype = None

    if isinstance(item, str):
        if astype is None:
            # Try each candidate scalar type in turn until one succeeds.
            # NOTE: lists / tuples / sets are NOT inferred. kwconf
            # intentionally drops scriptconfig's auto comma-splitting; pass
            # an explicit ``astype`` to opt into sequence parsing.
            for candidate in [int, float, complex, bool, NoneType]:
                try:
                    return _as_smart_type(item, candidate)
                except (TypeError, ValueError):
                    pass

            if strict:
                raise TypeError('Could not smartcast item={!r}'.format(item))
            else:
                return item
        else:
            return _as_smart_type(item, astype)
    else:
        # Note this is not a common case, the input is typically a string
        # Might want to rethink behavior in this case.
        if astype is None:
            return item
        else:
            if astype == eval:
                return item
            elif isinstance(astype, str):
                cast_map: dict[str, Callable[[Any], Any]] = {
                    'eval': _identity,
                    'int': int,
                    'bool': bool,
                    'float': float,
                    'complex': complex,
                    'str': str,
                    'tuple': tuple,
                    'list': list,
                    'set': set,
                    'frozenset': frozenset,
                }
                try:
                    return cast_map[astype](item)
                except KeyError as exc:
                    raise KeyError('unknown string astype={!r}'.format(astype)) from exc
            else:
                return astype(item)


def _as_smart_type(item: Any, astype: Any) -> Any:
    """
    casts item to type, and tries to be clever when item is a string, otherwise
    it simply calls `astype(item)`.

    Args:
        item (str): represents some data of another type.
        astype (type | str): type to attempt to cast to

    Returns:
        object:

    Example:
        >>> assert _as_smart_type('1', int) == 1
        >>> assert _as_smart_type('1', str) == '1'
        >>> assert _as_smart_type('1', bool) is True
        >>> assert _as_smart_type('0', bool) is False
        >>> assert _as_smart_type('1', float) == 1.0
        >>> assert _as_smart_type('1', list) == [1]
        >>> assert _as_smart_type('(1,3)', 'eval') == (1, 3)
        >>> assert _as_smart_type('(1,3)', eval) == (1, 3)
        >>> assert _as_smart_type('1::3', slice) == slice(1, None, 3)
    """
    if not isinstance(item, str):
        raise TypeError('item must be a string')

    if astype is NoneType:
        return _smartcast_none(item)
    elif astype is bool:
        return _smartcast_bool(item)
    elif astype is slice:
        return _smartcast_slice(item)
    elif astype in [int, float, complex]:
        return astype(item)
    elif astype is str:
        return item
    elif astype is eval:
        import ast
        return ast.literal_eval(item)
    elif astype in [list, tuple, set, frozenset]:
        # TODO:
        # use parse_nestings to smartcast complex lists/tuples/sets
        return _smartcast_simple_sequence(item, astype)
    elif isinstance(astype, str):
        # allow types to be given as strings
        astype = {
            'bool': bool,
            'int': int,
            'float': float,
            'complex': complex,
            'str': str,
            'eval': eval,
            'none': NoneType,
        }[astype.lower()]
        return _as_smart_type(item, astype)
    raise NotImplementedError('Unknown smart astype=%r' % (astype,))


def _smartcast_slice(item: str) -> slice:
    args: list[Optional[int]] = [int(p) if p else None for p in item.split(':')]
    return slice(*args)


def _smartcast_none(item):
    """
    Casts a string to None.
    """
    if item.lower() == 'none':
        return None
    else:
        raise TypeError('string does not represent none')


def _smartcast_bool(item):
    """
    Casts a string to a boolean.
    Setting strict=False allows '0' and '1' to be used as a bool
    """
    lower = item.lower()
    if lower == 'true':
        return True
    elif lower == 'false':
        return False
    else:
        try:
            return bool(int(item))
        except TypeError:
            pass
        raise TypeError('item does not represent boolean')


def _smartcast_simple_sequence(item: str, astype: Any = list) -> Any:
    """
    Casts only the simplest strings to a sequence. Cannot handle any nesting.

    Example:
        >>> assert _smartcast_simple_sequence('1') == [1]
        >>> assert _smartcast_simple_sequence('[1]') == [1]
        >>> assert _smartcast_simple_sequence('[[1]]') == ['[1]']
        >>> item = "[1,2,3,]"
        >>> _smartcast_simple_sequence(item)
    """
    nesters = {list: '[]', tuple: '()', set: '{}', frozenset: '{}'}
    nester = nesters.pop(astype)
    item = item.strip()
    if item.startswith(nester[0]) and item.endswith(nester[1]):
        item = item[1:-1]
    elif any(item.startswith(nester[0]) and item.endswith(nester[1])
             for nester in nesters.values()):
        raise ValueError('wrong nester')
    parts = [p.strip() for p in item.split(',')]
    parts = [p for p in parts if p]
    return astype(smartcast(p) for p in parts)


def _identity(arg: Any) -> Any:
    """ identity function """
    return arg


if __name__ == '__main__':
    """
    CommandLine:
        python ~/code/kwconf/kwconf/smartcast.py
    """
    import xdoctest
    xdoctest.doctest_module(__file__)
