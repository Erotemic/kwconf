"""
Annotation helpers for :mod:`kwconf`.

``kwconf`` uses class annotations at metaclass-construction time to enrich
``Value`` metadata, derive CLI choices from ``Literal`` annotations, and run
optional validation after coercion.  Keeping that logic here makes the policy
explicit and keeps ``config.py`` focused on config-object lifecycle behavior.

The helpers are intentionally best-effort: unresolved forward references and
annotation forms that kwconf does not understand are preserved or treated as
unknown instead of causing class creation to fail.
"""
from __future__ import annotations

import sys
import types
import typing
from collections.abc import Mapping
from typing import Any, Dict, Union, cast

__all__ = [
    'annotation_eval_context',
    'resolve_annotation',
    'resolve_annotations',
    'get_class_namespace_annotations',
    'runtime_type_from_annotation',
    'choices_from_annotation',
    'value_matches_annotation',
    'format_annotation',
]

NoneType = type(None)


def annotation_eval_context(
    namespace: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build globals / locals useful for resolving class annotations.

    Examples:
        >>> g, l = annotation_eval_context({
        ...     '__module__': __name__,
        ...     'LocalAlias': int,
        ... })
        >>> g['typing'] is typing and g['Any'] is Any and g['Union'] is Union
        True
        >>> l['LocalAlias'] is int
        True

        Missing or non-string ``__module__`` values are tolerated.

        >>> g, l = annotation_eval_context({'__module__': 42})
        >>> g['typing'] is typing and l['__module__'] == 42
        True
    """
    namespace = namespace or {}
    module_globals: Dict[str, Any] = {}
    module_name = namespace.get('__module__')
    if isinstance(module_name, str):
        module = sys.modules.get(module_name)
        if module is not None:
            module_globals.update(getattr(module, '__dict__', {}))
    module_globals.setdefault('typing', typing)
    module_globals.setdefault('Any', Any)
    module_globals.setdefault('Union', Union)
    localns = dict(namespace)
    return module_globals, localns


def resolve_annotation(
    annotation: Any,
    namespace: Mapping[str, Any] | None = None,
) -> Any:
    """
    Best-effort conversion of deferred / string annotations into values.

    Python 3.14 stores class-body annotations behind ``__annotate__`` by
    default, while ``from __future__ import annotations`` stores them as
    strings.  kwconf needs real ``typing`` objects in its metaclass so it can
    populate ``Value.type``, argparse ``choices``, and validation metadata.

    Examples:
        >>> resolve_annotation('int') is int
        True
        >>> resolve_annotation('typing.Optional[str]')
        typing.Optional[str]
        >>> resolve_annotation('MissingName')
        'MissingName'
        >>> resolve_annotation(float) is float
        True

        Local names from the class namespace are available while resolving.

        >>> resolve_annotation('Alias', {'Alias': bytes}) is bytes
        True
    """
    if isinstance(annotation, str):
        globalns, localns = annotation_eval_context(namespace)
        try:
            return eval(annotation, globalns, localns)
        except Exception:
            return annotation
    if hasattr(annotation, '__forward_arg__') and hasattr(annotation, 'evaluate'):
        globalns, localns = annotation_eval_context(namespace)
        try:
            return annotation.evaluate(globals=globalns, locals=localns)
        except Exception:
            return annotation
    return annotation


def resolve_annotations(
    annotations: Mapping[str, Any],
    namespace: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve all annotations in a class namespace as far as possible.

    Examples:
        >>> resolved = resolve_annotations({
        ...     'name': 'str',
        ...     'count': 'typing.Optional[int]',
        ...     'unknown': 'NotImported',
        ... })
        >>> resolved['name'] is str
        True
        >>> resolved['count']
        typing.Optional[int]
        >>> resolved['unknown']
        'NotImported'
    """
    return {
        key: resolve_annotation(annotation, namespace)
        for key, annotation in annotations.items()
    }


def get_class_namespace_annotations(namespace: Mapping[str, Any]) -> dict[str, Any]:
    """
    Return class-body annotations during metaclass construction.

    On Python <= 3.13 this usually comes from ``__annotations__``.  On Python
    3.14+, non-future annotations may instead be available through the
    compiler-generated ``__annotate__`` function.  Use ``annotationlib`` when it
    exists, matching Python's documented metaclass recipe for deferred
    annotations.

    Examples:
        >>> ns = {
        ...     '__module__': __name__,
        ...     '__annotations__': {'x': 'int', 'y': 'Missing'},
        ... }
        >>> get_class_namespace_annotations(ns) == {'x': int, 'y': 'Missing'}
        True
        >>> get_class_namespace_annotations({})
        {}
    """
    annotations = namespace.get('__annotations__', None)
    if annotations:
        return resolve_annotations(annotations, namespace)

    try:
        import annotationlib  # type: ignore[import-not-found]
    except Exception:
        return {}

    annotate = annotationlib.get_annotate_from_class_namespace(namespace)
    if annotate is None:
        return {}
    try:
        annotations = annotationlib.call_annotate_function(
            annotate, annotationlib.Format.FORWARDREF)
    except Exception:
        try:
            annotations = annotationlib.call_annotate_function(
                annotate, annotationlib.Format.STRING)
        except Exception:
            return {}
    return resolve_annotations(annotations, namespace)


def runtime_type_from_annotation(annotation: Any) -> type | None:
    """
    Infer the runtime type useful for argparse coercion from an annotation.

    Examples:
        >>> runtime_type_from_annotation(int) is int
        True
        >>> runtime_type_from_annotation(typing.Literal['debug', 'info']) is str
        True
        >>> runtime_type_from_annotation(typing.Literal[1, 'two']) is None
        True
        >>> runtime_type_from_annotation(int | None) is int
        True
        >>> runtime_type_from_annotation(list[int]) is list
        True
        >>> runtime_type_from_annotation(typing.Any) is None
        True
        >>> runtime_type_from_annotation('ForwardRef') is None
        True
    """
    if annotation is None or annotation is Any or isinstance(annotation, str):
        return None
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        # ``Literal['a', 'b']`` -> infer the type of the choices.
        choice_types = {type(arg) for arg in typing.get_args(annotation)}
        if len(choice_types) == 1:
            (only_type,) = choice_types
            return only_type
        return None
    if origin in {Union, types.UnionType}:
        args = [arg for arg in typing.get_args(annotation) if arg is not NoneType]
        for arg in args:
            runtime_type = runtime_type_from_annotation(arg)
            if runtime_type is not None:
                return runtime_type
        return None
    if origin is not None:
        return cast(type | None, origin)
    if isinstance(annotation, type):
        return annotation
    return None


def choices_from_annotation(annotation: Any) -> tuple | None:
    """
    Return choices implied by ``Literal`` annotations, including Optional wrappers.

    Examples:
        >>> choices_from_annotation(typing.Literal['small', 'large'])
        ('small', 'large')
        >>> choices_from_annotation(typing.Optional[typing.Literal[1, 2]])
        (1, 2)
        >>> choices_from_annotation(str) is None
        True
        >>> choices_from_annotation('ForwardRef') is None
        True
    """
    if annotation is None or isinstance(annotation, str):
        return None
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return typing.get_args(annotation)
    if origin in {Union, types.UnionType}:
        for arg in typing.get_args(annotation):
            if arg is NoneType:
                continue
            ch = choices_from_annotation(arg)
            if ch is not None:
                return ch
    return None


def value_matches_annotation(value: Any, annotation: Any) -> bool:
    """
    Return True if ``value`` is consistent with ``annotation``.

    Supports plain runtime types (int, str, bool, None), ``Literal[...]``,
    unions (``X | Y``, ``Optional[X]``, ``Union[...]``), and parameterized
    collections (``list[T]``, ``tuple[T, ...]``, ``dict[K, V]``, ``set[T]``)
    with a one-level element-type check. Annotations the helper cannot reason
    about return True so kwconf under-validates rather than misvalidates.

    Examples:
        >>> value_matches_annotation(3, int)
        True
        >>> value_matches_annotation('3', int)
        False
        >>> value_matches_annotation(None, NoneType)
        True
        >>> value_matches_annotation('red', typing.Literal['red', 'blue'])
        True
        >>> value_matches_annotation('green', typing.Literal['red', 'blue'])
        False
        >>> value_matches_annotation(None, int | None)
        True
        >>> value_matches_annotation([1, 2], list[int])
        True
        >>> value_matches_annotation([1, '2'], list[int])
        False
        >>> value_matches_annotation({1, 2}, set[int])
        True
        >>> value_matches_annotation((1, 2, 3), tuple[int, ...])
        True
        >>> value_matches_annotation((1, 'x'), tuple[int, str])
        True
        >>> value_matches_annotation((1, 2), tuple[int, str])
        False
        >>> value_matches_annotation({'x': 1}, dict[str, int])
        True
        >>> value_matches_annotation({'x': '1'}, dict[str, int])
        False

        Unknown annotation forms intentionally pass validation.

        >>> value_matches_annotation(object(), 'UnresolvedForwardRef')
        True
    """
    if annotation is None or annotation is Any or isinstance(annotation, str):
        return True
    if annotation is NoneType:
        return value is None
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return value in typing.get_args(annotation)
    if origin in {Union, types.UnionType}:
        return any(
            value_matches_annotation(value, arg)
            for arg in typing.get_args(annotation)
        )
    if origin in {list, set, frozenset}:
        if not isinstance(value, origin):
            return False
        (elem_t,) = typing.get_args(annotation) or (Any,)
        return all(value_matches_annotation(v, elem_t) for v in value)
    if origin is tuple:
        if not isinstance(value, tuple):
            return False
        args = typing.get_args(annotation)
        if len(args) == 2 and args[1] is Ellipsis:
            return all(value_matches_annotation(v, args[0]) for v in value)
        if len(args) != len(value):
            return False
        return all(value_matches_annotation(v, t) for v, t in zip(value, args))
    if origin is dict:
        if not isinstance(value, dict):
            return False
        args = typing.get_args(annotation) or (Any, Any)
        kt, vt = args
        return all(
            value_matches_annotation(k, kt) and value_matches_annotation(v, vt)
            for k, v in value.items()
        )
    if origin is not None:
        # Some other parameterized generic; check the origin only.
        try:
            return isinstance(value, origin)
        except TypeError:
            return True
    if isinstance(annotation, type):
        return isinstance(value, annotation)
    return True


def format_annotation(annotation: Any) -> str:
    """Return a compact display string for diagnostics.

    Examples:
        >>> format_annotation(int)
        'int'
        >>> class Custom:
        ...     pass
        >>> format_annotation(Custom)
        'Custom'
        >>> format_annotation('ForwardRef')
        'ForwardRef'
    """
    if hasattr(annotation, '__name__'):
        return cast(str, annotation.__name__)
    return str(annotation)
