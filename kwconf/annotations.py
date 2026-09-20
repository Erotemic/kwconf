"""
Annotation helpers for :mod:`kwconf`.

``kwconf`` uses class annotations at metaclass-construction time to enrich
``Value`` metadata, derive CLI choices from ``Literal`` annotations, and run
optional validation after coercion. Keeping that logic here makes the policy
explicit and keeps ``config.py`` focused on config-object lifecycle behavior.

The helpers are intentionally best-effort: unresolved forward references and
annotation forms that kwconf does not understand are preserved or treated as
unknown instead of causing class creation to fail.

Performance note:
    :mod:`typing` is intentionally not imported when this module loads. The
    overwhelmingly common CLI annotations (``int``, ``str``, ``list[str]``,
    ``X | None``) can be inspected through builtin/runtime metadata. Typing is
    imported only when an annotation explicitly needs its compatibility names.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping

__all__ = [
    'annotation_eval_context',
    'resolve_annotation',
    'resolve_annotations',
    'get_class_namespace_annotations',
    'is_classvar_annotation',
    'runtime_type_from_annotation',
    'choices_from_annotation',
    'value_matches_annotation',
    'format_annotation',
]

NoneType = type(None)
_UNION_TYPE = type(int | str)


def _typing_if_loaded():
    """Return :mod:`typing` without importing it."""
    return sys.modules.get('typing')


def _typing_module():
    """Return :mod:`typing`, importing it only when a feature needs it."""
    module = _typing_if_loaded()
    if module is None:
        import typing

        module = typing
    return module


def _origin(annotation):
    """Fast ``typing.get_origin`` equivalent for the forms kwconf needs."""
    if isinstance(annotation, _UNION_TYPE):
        return _UNION_TYPE
    # Ordinary classes dominate kwconf schemas and can never have a typing
    # origin. Short-circuit before consulting an already-imported ``typing``
    # module; ``typing.get_origin(str)`` is surprisingly visible when hundreds
    # of fields are normalized at class construction time.
    if isinstance(annotation, type):
        return None
    typing_mod = _typing_if_loaded()
    if typing_mod is not None:
        return typing_mod.get_origin(annotation)
    return getattr(annotation, '__origin__', None)


def _args(annotation):
    """Fast ``typing.get_args`` equivalent without forcing a typing import."""
    if isinstance(annotation, type):
        return ()
    typing_mod = _typing_if_loaded()
    if typing_mod is not None:
        return typing_mod.get_args(annotation)
    return getattr(annotation, '__args__', ())


def _is_any(annotation):
    typing_mod = _typing_if_loaded()
    return typing_mod is not None and annotation is typing_mod.Any


def _is_literal_origin(origin):
    if origin is None:
        return False
    typing_mod = _typing_if_loaded()
    return typing_mod is not None and origin is typing_mod.Literal


def _is_union_origin(origin):
    if origin is _UNION_TYPE:
        return True
    if origin is None:
        return False
    typing_mod = _typing_if_loaded()
    return typing_mod is not None and origin is typing_mod.Union


def is_classvar_annotation(annotation):
    """Return True for ``typing.ClassVar[...]`` without importing typing."""
    if annotation is None:
        return False
    origin = _origin(annotation)
    typing_mod = _typing_if_loaded()
    return typing_mod is not None and origin is typing_mod.ClassVar


def _base_eval_context(namespace=None):
    namespace = namespace or {}
    module_globals = {}
    module_name = namespace.get('__module__')
    if isinstance(module_name, str):
        module = sys.modules.get(module_name)
        if module is not None:
            module_globals.update(getattr(module, '__dict__', {}))
    return module_globals, dict(namespace)


def annotation_eval_context(namespace=None):
    """Build globals / locals useful for resolving class annotations.

    Calling this compatibility helper explicitly provides the historical
    ``typing``, ``Any``, and ``Union`` convenience names. The hot metaclass path
    first attempts annotation evaluation without them so simple schemas do not
    import :mod:`typing`.

    Examples:
        >>> import typing
        >>> g, l = annotation_eval_context({
        ...     '__module__': __name__,
        ...     'LocalAlias': int,
        ... })
        >>> assert g['typing'] is typing
        >>> assert g['Any'] is typing.Any and g['Union'] is typing.Union
        >>> assert l['LocalAlias'] is int

        Missing or non-string ``__module__`` values are tolerated.

        >>> g, l = annotation_eval_context({'__module__': 42})
        >>> assert g['typing'] is typing and l['__module__'] == 42
    """
    module_globals, localns = _base_eval_context(namespace)
    typing_mod = _typing_module()
    module_globals.setdefault('typing', typing_mod)
    module_globals.setdefault('Any', typing_mod.Any)
    module_globals.setdefault('Union', typing_mod.Union)
    return module_globals, localns


def resolve_annotation(annotation, namespace=None):
    """Best-effort conversion of deferred/string annotations into values.

    Examples:
        >>> import typing
        >>> assert resolve_annotation('int') is int
        >>> assert resolve_annotation('typing.Optional[str]') == typing.Optional[str]
        >>> resolve_annotation('MissingName')
        'MissingName'
        >>> assert resolve_annotation(float) is float
        >>> assert resolve_annotation('Alias', {'Alias': bytes}) is bytes
    """
    if isinstance(annotation, str):
        globalns, localns = _base_eval_context(namespace)
        try:
            return eval(annotation, globalns, localns)
        except NameError:
            # Preserve kwconf's historical convenience resolution for strings
            # such as ``typing.Optional[int]`` and bare ``Any`` / ``Union``.
            globalns, localns = annotation_eval_context(namespace)
            try:
                return eval(annotation, globalns, localns)
            except Exception:
                return annotation
        except Exception:
            return annotation
    if hasattr(annotation, '__forward_arg__') and hasattr(
        annotation, 'evaluate'
    ):
        globalns, localns = annotation_eval_context(namespace)
        try:
            return annotation.evaluate(globals=globalns, locals=localns)
        except Exception:
            return annotation
    return annotation


def resolve_annotations(annotations: Mapping, namespace=None):
    """Resolve all annotations in a class namespace as far as possible."""
    return {
        key: resolve_annotation(annotation, namespace)
        for key, annotation in annotations.items()
    }


def get_class_namespace_annotations(namespace: Mapping):
    """Return class-body annotations during metaclass construction.

    On Python <= 3.13 this usually comes from ``__annotations__``. On Python
    3.14+, non-future annotations may instead be available through the
    compiler-generated ``__annotate__`` function. Use ``annotationlib`` when it
    exists, matching Python's documented metaclass recipe.
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
            annotate, annotationlib.Format.FORWARDREF
        )
    except Exception:
        try:
            annotations = annotationlib.call_annotate_function(
                annotate, annotationlib.Format.STRING
            )
        except Exception:
            return {}
    return resolve_annotations(annotations, namespace)


def runtime_type_from_annotation(annotation):
    """Infer the runtime type useful for CLI coercion from an annotation."""
    if annotation is None or isinstance(annotation, str):
        return None
    # ``typing.Any`` is itself an instance of ``type`` on supported CPython
    # versions, so it must be recognized before the ordinary-class shortcut.
    if _is_any(annotation):
        return None
    # Plain classes are by far the most common schema annotation and need no
    # typing machinery at all.
    if isinstance(annotation, type):
        return annotation
    origin = _origin(annotation)
    if _is_literal_origin(origin):
        choice_types = {type(arg) for arg in _args(annotation)}
        if len(choice_types) == 1:
            (only_type,) = choice_types
            return only_type
        return None
    if _is_union_origin(origin):
        for arg in _args(annotation):
            if arg is NoneType:
                continue
            runtime_type = runtime_type_from_annotation(arg)
            if runtime_type is not None:
                return runtime_type
        return None
    if origin is not None:
        return origin if isinstance(origin, type) else None
    return None


def choices_from_annotation(annotation):
    """Return choices implied by ``Literal`` annotations and unions."""
    if annotation is None or isinstance(annotation, (str, type)):
        return None
    origin = _origin(annotation)
    if _is_literal_origin(origin):
        return _args(annotation)
    if _is_union_origin(origin):
        combined = []
        for arg in _args(annotation):
            if arg is NoneType:
                continue
            choices = choices_from_annotation(arg)
            if choices is None:
                return None
            combined.extend(choice for choice in choices if choice not in combined)
        if combined:
            return tuple(combined)
    return None


def value_matches_annotation(value, annotation):
    """Return True if ``value`` is consistent with ``annotation``.

    Unknown forms intentionally pass validation so kwconf under-validates
    rather than rejecting a valid value it cannot reason about.
    """
    if annotation is None or _is_any(annotation) or isinstance(annotation, str):
        return True
    if annotation is NoneType:
        return value is None
    origin = _origin(annotation)
    if _is_literal_origin(origin):
        return any(
            type(value) is type(candidate) and value == candidate
            for candidate in _args(annotation)
        )
    if _is_union_origin(origin):
        return any(
            value_matches_annotation(value, arg) for arg in _args(annotation)
        )
    if origin in {list, set, frozenset}:
        if not isinstance(value, origin):
            return False
        args = _args(annotation)
        elem_t = args[0] if args else None
        return all(value_matches_annotation(item, elem_t) for item in value)
    if origin is tuple:
        if not isinstance(value, tuple):
            return False
        args = _args(annotation)
        if len(args) == 2 and args[1] is Ellipsis:
            return all(value_matches_annotation(item, args[0]) for item in value)
        if len(args) != len(value):
            return False
        return all(
            value_matches_annotation(item, item_type)
            for item, item_type in zip(value, args)
        )
    if origin is dict:
        if not isinstance(value, dict):
            return False
        args = _args(annotation) or (None, None)
        key_t, value_t = args
        return all(
            value_matches_annotation(key, key_t)
            and value_matches_annotation(item, value_t)
            for key, item in value.items()
        )
    if origin is not None:
        try:
            return isinstance(value, origin)
        except TypeError:
            return True
    if isinstance(annotation, type):
        # PEP 484 numeric tower.
        if annotation is float and isinstance(value, int):
            return True
        if annotation is complex and isinstance(value, (int, float)):
            return True
        return isinstance(value, annotation)
    return True


def format_annotation(annotation):
    """Return a compact display string for diagnostics."""
    if annotation is NoneType or annotation is None:
        return 'None'
    if annotation is Ellipsis:
        return '...'
    origin = _origin(annotation)
    if origin is None and isinstance(annotation, type):
        return annotation.__name__
    if _is_union_origin(origin):
        return ' | '.join(format_annotation(arg) for arg in _args(annotation))
    if origin is not None:
        args = _args(annotation)
        origin_name = getattr(origin, '__name__', str(origin))
        if _is_literal_origin(origin):
            origin_name = 'Literal'
        if args:
            inner = ', '.join(format_annotation(arg) for arg in args)
            return f'{origin_name}[{inner}]'
        return origin_name
    if hasattr(annotation, '__name__'):
        return annotation.__name__
    return str(annotation)
