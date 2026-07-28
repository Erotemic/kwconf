"""
Helpers for nested configuration nodes built from Config objects.

The :class:`SubConfig` wrapper marks a nested :class:`Config` (or subclass)
and optionally exposes a registry of valid choices or a permissive import
mechanism for dynamically specified class paths.

The rest of this module contains utilities that :class:`Config` uses to
realize nested configuration trees from defaults, files, kwargs, and staged
CLI parsing.

Example:
    >>> import kwconf
    >>> class Inner(kwconf.Config):
    ...     depth = 1
    >>> class Outer(kwconf.Config):
    ...     inner = kwconf.SubConfig(Inner, choices={'inner': Inner})
    >>> cfg = Outer.cli(argv=['--inner.depth=3'])
    >>> assert cfg.inner.depth == 3
    >>> cfg2 = Outer.cli(argv=['--inner=inner', '--inner.depth=4'])
    >>> assert isinstance(cfg2.inner, Inner) and cfg2.inner.depth == 4
"""

from __future__ import annotations

import argparse
import inspect
import typing
import warnings
from collections.abc import Mapping
from typing import Any, cast

from kwconf.config import Config, ConfigValidationError
from kwconf.value import _Value as Value

# ``SubConfig`` is the supported public surface of this module. The remaining
# functions implement Config's nested-loading and staged-parser machinery and
# may change without compatibility guarantees. They remain explicitly
# importable for kwconf internals, but wildcard imports intentionally expose
# only the declaration type.
__all__ = ['SubConfig']

_SELECTOR_SUFFIX = '.__class__'
_MISSING = object()

if typing.TYPE_CHECKING:
    from types import FrameType


def get_stack_frame(stacklevel: int = 0) -> FrameType:
    """
    Gets the current stack frame or any of its ancestors dynamically.

    Args:
        stacklevel (int): stacklevel=0 means the frame you called this
            function in. stacklevel=1 is the parent frame.

    Returns:
        FrameType: frame_cur

    Example:
        >>> from kwconf.subconfig import get_stack_frame
        >>> frame_cur = get_stack_frame(stacklevel=0)
        >>> print('frame_cur = %r' % (frame_cur,))
        >>> assert frame_cur.f_globals['frame_cur'] is frame_cur
    """
    frame_cur: FrameType | None = inspect.currentframe()
    # Use stacklevel+1 to always skip the frame of this function.
    for ix in range(stacklevel + 1):
        frame_next: FrameType | None = frame_cur.f_back  # type: ignore
        if frame_next is None:  # nocover
            raise AssertionError(f'Frame level {ix} is root')
        frame_cur = frame_next
    assert frame_cur is not None
    return frame_cur


def resolve_localns(
    localns: typing.MutableMapping | None, stacklevel: int | None
) -> typing.MutableMapping | None:
    """
    Resolve the namespace for selector evaluation, if needed.

    Args:
        localns (dict | None): namespace to use when resolving class names.
        stacklevel (int | None): stack offset for caller introspection.

    Returns:
        dict | None: resolved namespace.

    Example:
        >>> ns = resolve_localns({'demo_value': 5}, stacklevel=None)
        >>> assert ns['demo_value'] == 5
    """
    if localns is None and stacklevel is not None:
        frame = get_stack_frame(stacklevel=stacklevel + 2)
        localns = dict(frame.f_globals)
        localns.update(frame.f_locals)
    return localns


class _ForbiddenSelectorAction(argparse.Action):
    """
    argparse action that errors when subconfig selectors are disallowed.
    """

    def __init__(self, option_strings, dest, **kwargs):
        self._message = kwargs.pop('_message', None)
        super().__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        message = self._message or (
            'SubConfig selection overrides require allow_subconfig_overrides=True'
        )
        parser.error(message)


def add_forbidden_selector_args(parser, cfg):
    """
    Add selector options that always error when used.

    Example:
        >>> import argparse
        >>> import kwconf
        >>> class Inner(kwconf.Config):
        ...     __default__ = {'x': 1}
        >>> class Outer(kwconf.Config):
        ...     __default__ = {'inner': kwconf.SubConfig(Inner)}
        >>> parser = argparse.ArgumentParser()
        >>> add_forbidden_selector_args(parser, Outer())
        >>> assert '--inner' in parser._option_string_actions
    """
    message = (
        'SubConfig selection overrides require allow_subconfig_overrides=True'
    )
    for path in find_subconfig_paths(cfg):
        for opt in (f'--{path}', f'--{path}.__class__'):
            parser.add_argument(
                opt,
                action=_ForbiddenSelectorAction,
                help=argparse.SUPPRESS,
                _message=message,
            )


class SubConfig(Value):
    """
    Wrapper used to declare nested :class:`Config` nodes.

    Args:
        default (Type[Config] | Config): a Config subclass or instance.
        choices (dict | None): optional registry mapping selector keys to
            Config subclasses.
        allow_import (bool | None): per-field dynamic-import policy. ``None``
            inherits the call-level ``allow_import`` switch; True or False
            explicitly enables or disables imports for this field.

    Example:
        >>> import kwconf
        >>> class Inner(kwconf.Config):
        ...     __default__ = {'x': 1}
        >>> meta = SubConfig(Inner)
        >>> inst = meta.instantiate()
        >>> assert isinstance(inst, Inner)
    """

    def __init__(
        self,
        default: Any,
        *,
        choices: Mapping[str, type] | None = None,
        allow_import: bool | None = None,
        help: str | None = None,
    ) -> None:
        default_inst: Any
        if inspect.isclass(default):
            if not issubclass(default, Config):
                raise TypeError(
                    'SubConfig default must be a Config subclass or instance'
                )
            default_inst = default
        elif isinstance(default, Config):
            default_inst = default
        else:
            raise TypeError(
                'SubConfig default must be a Config subclass or instance'
            )

        super().__init__(default=default_inst, help=help)
        self.allow_import = allow_import
        self.choices = dict(choices) if choices is not None else None
        if self.choices is not None:
            for key, cls in self.choices.items():
                if not inspect.isclass(cls) or not issubclass(cls, Config):
                    raise TypeError(
                        f'SubConfig choices must map to Config subclasses. {key!r} -> {cls!r}'
                    )

    def __nice__(self):
        default_cls = (
            self.value if inspect.isclass(self.value) else self.value.__class__
        )
        return f'{default_cls.__name__}'

    def clone_default(self, *, context='SubConfig default'):
        """Copy selector metadata while retaining the baseline recipe/template."""
        new = cast(SubConfig, self.copy())
        new.choices = dict(self.choices) if self.choices is not None else None
        # Config classes are constructors; Config instances are baseline
        # templates cloned by instantiate(). Neither should be deep-copied as
        # ordinary Value payload here.
        new._value = self.value
        return new

    def instantiate(self, *, _dont_call_post_init=False):
        """
        Return a fresh instance of the wrapped config.
        """
        if inspect.isclass(self.value):
            # __init__ validated that a class value is a Config subclass.
            subconfig_cls = cast(type[Config], self.value)
            instance = subconfig_cls(_dont_call_post_init=_dont_call_post_init)
        else:
            # An instance declaration is a reset-baseline template, not a
            # request to deepcopy its live runtime objects. Config-aware cloning
            # preserves concrete defaults while re-invoking factory recipes.
            instance = self.value._clone_from_baseline(
                _dont_call_post_init=_dont_call_post_init
            )
        return instance


def wrap_subconfig_defaults(cfg, _dont_call_post_init=False):
    """Compatibility wrapper for indexing and realizing SubConfig fields.

    Class normalization owns schema conversion.  This helper no longer rewrites
    ``cfg._default``; it only refreshes the instance index and ensures current
    runtime values are realized Config objects.
    """
    cfg._index_subconfigs()
    ensure_subconfigs_instantiated(
        cfg, _dont_call_post_init=_dont_call_post_init
    )


def ensure_subconfigs_instantiated(cfg, _dont_call_post_init=False):
    """Ensure every indexed SubConfig has a realized runtime instance."""
    cfg._index_subconfigs()
    for key, meta in cfg._subconfig_meta.items():
        if not isinstance(cfg._data.get(key), Config):
            cfg._data[key] = meta.instantiate(
                _dont_call_post_init=_dont_call_post_init
            )


def coerce_argv(cmdline: Any) -> tuple[list[str], bool]:
    """Normalize cmdline inputs into an argv list and help flag."""
    from kwconf._ingest import coerce_argv as _coerce_argv

    argv = _coerce_argv(cmdline)
    return argv, any(arg in {'-h', '--help'} for arg in argv)


def scan_config_path(argv: list[str]) -> str | None:
    """Extract ``--config`` using argparse's own option semantics."""
    parser = argparse.ArgumentParser(
        add_help=False, allow_abbrev=False, exit_on_error=False
    )
    parser.add_argument('--config')
    try:
        namespace, _unknown = parser.parse_known_args(argv)
    except argparse.ArgumentError as ex:
        raise ValueError(str(ex)) from ex
    return typing.cast(str | None, namespace.config)


def coerce_data_updates(data, mode=None, cfg=None):
    """Convert a shared mapping source into config-aware dotted updates."""
    from kwconf._ingest import coerce_mapping_source

    user_config = coerce_mapping_source(data, mode=mode)
    return dict(_flatten_nested(user_config, cfg=cfg))


def _flatten_nested(mapping, cfg=None):
    """
    Flatten a nested mapping into dotted key/value pairs.

    When ``cfg`` is given, descend into a nested mapping only if its dotted
    path is a SubConfig node in ``cfg``. A nested mapping that lands on a
    plain (non-subconfig) leaf field -- including an empty dict -- is yielded
    whole, so dict-valued fields are neither shredded into dotted keys nor
    silently dropped. Without ``cfg`` every nested mapping is flattened (the
    original structure-blind behavior).

    Example:
        >>> list(_flatten_nested({'a': {'b': 1}, 'c': 2}))
        [('a.b', 1), ('c', 2)]
        >>> # Without cfg an empty mapping cannot be told from a node, so it
        >>> # keeps the original structure-blind behavior (dropped).
        >>> list(_flatten_nested({'a': {}}))
        []
    """
    if not isinstance(mapping, Mapping):
        raise TypeError('Expected mapping')
    stack: list[tuple[Any, tuple[str, ...]]] = [(iter(mapping.items()), ())]
    while stack:
        iterator, prefix = stack[-1]
        try:
            k, v = next(iterator)
        except StopIteration:
            stack.pop()
            continue
        next_prefix = prefix + (str(k),)
        is_subconfig = cfg is not None and _path_is_subconfig(
            cfg, list(next_prefix)
        )
        if isinstance(v, Mapping):
            if cfg is not None and not is_subconfig:
                # Leaf dict-valued field: assign the mapping whole (an empty
                # dict included) rather than shredding it into dotted keys.
                yield '.'.join(next_prefix), v  # type: ignore
            elif len(v) > 0:
                # Structural descent through a subconfig boundary (or the
                # original structure-blind behavior when cfg is None).
                stack.append((iter(v.items()), next_prefix))  # type: ignore
            # An empty mapping on a subconfig path carries no update: skip it.
        else:
            yield '.'.join(next_prefix), v  # type: ignore


def _iter_flat_update_sources(mapping, cfg=None):
    """Yield flattened updates together with their original spelling path.

    This is intentionally separate from :func:`_flatten_nested`: it is used
    only by opt-in structural validation, so normal loading does not allocate
    provenance records or perform a second traversal.
    """
    if not isinstance(mapping, Mapping):
        raise TypeError('Expected mapping')
    stack: list[tuple[Any, tuple[str, ...]]] = [(iter(mapping.items()), ())]
    while stack:
        iterator, prefix = stack[-1]
        try:
            k, v = next(iterator)
        except StopIteration:
            stack.pop()
            continue
        next_prefix = prefix + (str(k),)
        flat_key = '.'.join(next_prefix)
        is_subconfig = cfg is not None and _path_is_subconfig(
            cfg, flat_key.split('.')
        )
        if isinstance(v, Mapping):
            if cfg is not None and not is_subconfig:
                yield flat_key, v, next_prefix
            elif len(v) > 0:
                stack.append((iter(v.items()), next_prefix))
        else:
            yield flat_key, v, next_prefix


def _find_selector_update_conflicts(cfg, updates):
    """Find duplicate semantic SubConfig selector declarations."""
    # path -> [(spelling parts, value), ...]
    _Records = dict[str, list[tuple[tuple[str, ...], Any]]]
    explicit: _Records = {}
    direct: _Records = {}
    for flat_key, value, source_parts in _iter_flat_update_sources(
        updates, cfg=cfg
    ):
        record = (source_parts, value)
        if flat_key.endswith('.__class__'):
            path = flat_key[: -len('.__class__')]
            explicit.setdefault(path, []).append(record)
        else:
            direct.setdefault(flat_key, []).append(record)

    issues = []
    for path, records in explicit.items():
        records = [*records, *direct.get(path, [])]
        if len(records) > 1:
            rendered = []
            for source_parts, value in records:
                source = ' -> '.join(repr(part) for part in source_parts)
                rendered.append(f'{source}={value!r}')
            issues.append(
                f'Conflicting SubConfig selector updates for {path!r}: '
                + ', '.join(rendered)
            )
    return issues


def _report_structural_validation(mode, issues):
    """Warn or raise for opt-in structural validation issues."""
    if not issues:
        return
    message = '\n'.join(issues)
    if mode == 'warn':
        warnings.warn(message, UserWarning, stacklevel=4)
    else:
        raise ConfigValidationError(message)


def _selector_bootstrap_parser(cfg):
    """Build the tiny argparse parser used to realize the current tree."""
    parser = argparse.ArgumentParser(
        add_help=False, allow_abbrev=False, exit_on_error=False
    )
    for path in find_subconfig_paths(cfg):
        parser.add_argument(
            f'--{path}',
            f'--{path}.__class__',
            dest=path,
            default=argparse.SUPPRESS,
        )
    return parser


def _path_is_subconfig(cfg, parts):
    """
    Determine if a dotted path refers to a SubConfig node.

    Example:
        >>> import kwconf
        >>> class Inner(kwconf.Config):
        ...     __default__ = {'x': 1}
        >>> class Outer(kwconf.Config):
        ...     __default__ = {'inner': kwconf.SubConfig(Inner)}
        >>> cfg = Outer(_dont_call_post_init=True)
        >>> wrap_subconfig_defaults(cfg, _dont_call_post_init=True)
        >>> _path_is_subconfig(cfg, ['inner'])
        True
    """
    node = cfg
    for idx, part in enumerate(parts):
        if part == '__class__':
            return False
        if not isinstance(node, Config):
            return False
        if part in getattr(node, '_subconfig_meta', {}):
            if idx == len(parts) - 1:
                return True
            child = node._data.get(part)
            if isinstance(child, Config):
                node = child
            else:
                return False
        elif part in node._data and isinstance(node._data[part], Config):
            node = node._data[part]
        else:
            return False
    return False


def extract_selector_overrides(
    cfg, argv, allow_import=True, localns=None, stacklevel=None
):
    """Realize selector options through iterative argparse bootstrap passes.

    Kwconf orchestrates the passes, but argparse owns token interpretation in
    every pass.  Each pass recognizes only selectors exposed by the currently
    realized tree; applying those selectors may reveal another nested level.
    """
    if stacklevel is not None:
        localns = resolve_localns(localns, stacklevel)
    working = list(argv)
    collected: dict[str, Any] = {}
    while True:
        parser = _selector_bootstrap_parser(cfg)
        try:
            namespace, remaining = parser.parse_known_args(working)
        except argparse.ArgumentError as ex:
            raise ValueError(str(ex)) from ex
        selectors = vars(namespace)
        if not selectors:
            return collected, remaining
        if len(remaining) >= len(working):  # nocover - argparse invariant
            raise RuntimeError('Selector parsing made no progress')
        collected.update(selectors)
        apply_dot_updates(
            cfg,
            selectors,
            allow_import=allow_import,
            localns=localns,
            stacklevel=None,
        )
        working = remaining


def _ensure_parent_node(cfg, parts):
    """
    Traverse a dotted path and return the parent node.

    Example:
        >>> import kwconf
        >>> class Inner(kwconf.Config):
        ...     __default__ = {'x': 1}
        >>> class Outer(kwconf.Config):
        ...     __default__ = {'inner': kwconf.SubConfig(Inner)}
        >>> cfg = Outer(_dont_call_post_init=True)
        >>> wrap_subconfig_defaults(cfg, _dont_call_post_init=True)
        >>> parent = _ensure_parent_node(cfg, ['inner'])
        >>> assert isinstance(parent, Inner)
    """
    node = cfg
    for part in parts:
        if not isinstance(node, Config):
            raise KeyError('.'.join(parts))
        if part in getattr(node, '_subconfig_meta', {}):
            child = node._data.get(part)
            if not isinstance(child, Config):
                child = node._subconfig_meta[part].instantiate(
                    _dont_call_post_init=True
                )
                node._data[part] = child
            node = child
        elif part in node._data and isinstance(node._data[part], Config):
            node = node._data[part]
        else:
            raise KeyError('.'.join(parts))
    return node


def _resolve_class_spec(meta: SubConfig, spec, allow_import, localns=None):
    """
    Resolve a selector spec into a Config subclass.

    Precedence:
        1. SubConfig registry choices (if provided)
        2. Local namespace class names (bare identifiers)
        3. Importable module paths (if allow_import), using
           ``module.qualname.Class``.

    Example:
        >>> import kwconf
        >>> class Inner(kwconf.Config):
        ...     __default__ = {'x': 1}
        >>> meta = SubConfig(Inner, choices={'inner': Inner})
        >>> assert _resolve_class_spec(meta, 'inner', True) is Inner
    """
    if meta.choices and spec in meta.choices:
        return meta.choices[spec]
    if inspect.isclass(spec) and issubclass(spec, Config):
        return spec
    if isinstance(spec, str):
        if localns is not None and spec.isidentifier():
            candidate = localns.get(spec)
            if inspect.isclass(candidate) and issubclass(candidate, Config):
                return candidate
        import_allowed = (
            allow_import if meta.allow_import is None else meta.allow_import
        )
        if not import_allowed:
            raise ValueError(
                f'Importing {spec!r} not allowed for this SubConfig'
            )
        cls = _import_selector_object(spec)
        if not inspect.isclass(cls) or not issubclass(cls, Config):
            raise TypeError(f'Specified object {cls!r} is not a Config class')
        return cls
    raise ValueError(f'Unknown selector spec {spec!r}')


def _import_selector_object(spec: str):
    """Import ``module:qualname`` or ``module.qualname`` selector syntax."""
    import importlib

    if ':' in spec:
        modname, qualname = spec.split(':', 1)
        if not modname or not qualname:
            raise ValueError(f'Cannot interpret class spec {spec!r}')
        module = importlib.import_module(modname)
    else:
        parts = spec.split('.')
        if len(parts) < 2:
            raise ValueError(f'Cannot interpret class spec {spec!r}')
        module = None
        qualname_parts = None
        for split_idx in range(len(parts) - 1, 0, -1):
            candidate = '.'.join(parts[:split_idx])
            try:
                module = importlib.import_module(candidate)
            except ModuleNotFoundError as ex:
                missing = ex.name or ''
                if missing == candidate or candidate.startswith(missing + '.'):
                    continue
                raise
            qualname_parts = parts[split_idx:]
            modname = candidate
            break
        if module is None or qualname_parts is None:
            raise ValueError(f'Cannot import class spec {spec!r}')
        qualname = '.'.join(qualname_parts)

    obj = module
    for attr in qualname.split('.'):
        if not hasattr(obj, attr):
            raise ValueError(
                f'Object {modname!r} has no attribute path {qualname!r}'
            )
        obj = getattr(obj, attr)
    return obj


def _apply_selectors_fixpoint(cfg, selectors, allow_import=True, localns=None):
    """
    Apply selector overrides until a fixed point is reached.

    Example:
        >>> import kwconf
        >>> class Adam(kwconf.Config):
        ...     __default__ = {'lr': 1e-3}
        >>> class Sgd(kwconf.Config):
        ...     __default__ = {'momentum': 0.9}
        >>> class Train(kwconf.Config):
        ...     __default__ = {'optim': kwconf.SubConfig(Adam, choices={'adam': Adam, 'sgd': Sgd})}
        >>> cfg = Train(_dont_call_post_init=True)
        >>> wrap_subconfig_defaults(cfg, _dont_call_post_init=True)
        >>> _apply_selectors_fixpoint(cfg, {'optim': 'sgd'})
        >>> assert isinstance(cfg['optim'], Sgd)
    """
    remaining = dict(selectors)
    while remaining:
        applied_paths = []
        for path, spec in list(remaining.items()):
            parts = tuple(p for p in path.split('.') if p)
            if not parts:
                raise ValueError('Empty selector path')
            parent_parts, leaf = parts[:-1], parts[-1]
            try:
                parent = _ensure_parent_node(cfg, parent_parts)
            except KeyError:
                continue
            if not isinstance(parent, Config):
                continue
            meta = getattr(parent, '_subconfig_meta', {}).get(leaf, None)
            if meta is None:
                continue
            cls = _resolve_class_spec(meta, spec, allow_import, localns=localns)
            current = parent._data.get(leaf)
            if current.__class__ is not cls:
                parent._data[leaf] = cls(_dont_call_post_init=True)
            applied_paths.append(path)
        if not applied_paths:
            break
        for path in applied_paths:
            remaining.pop(path)
    if remaining:
        raise KeyError(f'Could not resolve selectors for: {sorted(remaining)}')


def apply_dot_updates(
    cfg,
    updates,
    *,
    allow_import=True,
    localns=None,
    stacklevel=None,
    validation_mode=None,
    structural_validation=False,
    provided_keys=None,
    _path_prefix=(),
):
    """
    Apply dotted-path updates and selectors to a nested Config.

    Example:
        >>> import kwconf
        >>> class Inner(kwconf.Config):
        ...     __default__ = {'x': 1}
        >>> class Outer(kwconf.Config):
        ...     __default__ = {'inner': kwconf.SubConfig(Inner)}
        >>> cfg = Outer(_dont_call_post_init=True)
        >>> wrap_subconfig_defaults(cfg, _dont_call_post_init=True)
        >>> apply_dot_updates(cfg, {'inner.x': 5})
        >>> assert cfg['inner']['x'] == 5
    """
    if not updates:
        return cfg

    if stacklevel is not None:
        localns = resolve_localns(localns, stacklevel)

    if structural_validation:
        issues = _find_selector_update_conflicts(cfg, updates)
        _report_structural_validation(structural_validation, issues)

    flat_updates = {}
    if isinstance(updates, Mapping):
        for k, v in _flatten_nested(updates, cfg=cfg):
            flat_updates[k] = v
    else:
        raise TypeError('updates must be a mapping')

    selectors = {}
    leaf_updates = {}
    for key, value in flat_updates.items():
        if key.endswith(_SELECTOR_SUFFIX):
            selectors[key[: -len(_SELECTOR_SUFFIX)]] = value
        else:
            leaf_updates[key] = value

    _apply_selectors_fixpoint(
        cfg, selectors, allow_import=allow_import, localns=localns
    )

    # Scalar values assigned directly to a SubConfig path are selector sugar.
    # Apply them to a fixed point because selecting a parent implementation may
    # reveal additional nested SubConfig paths. Mapping values are deferred:
    # they represent nested updates, not selector tokens.
    while True:
        sugar = {}
        for key, value in list(leaf_updates.items()):
            if isinstance(value, Mapping):
                continue
            parts = key.split('.')
            try:
                parent = _ensure_parent_node(cfg, parts[:-1])
            except KeyError:
                continue
            if parts[-1] in getattr(parent, '_subconfig_meta', {}):
                leaf_updates.pop(key)
                if key not in selectors:
                    sugar[key] = value
        if not sugar:
            break
        _apply_selectors_fixpoint(
            cfg, sugar, allow_import=allow_import, localns=localns
        )

    canonical_sources: dict[str, str] = {}
    for key, value in leaf_updates.items():
        parts = key.split('.')
        parent = _ensure_parent_node(cfg, parts[:-1])
        raw_leaf = parts[-1]
        leaf = raw_leaf
        if leaf == '__class__':
            raise KeyError(
                'The name "__class__" is reserved for selector metadata'
            )
        if leaf not in parent._data:
            leaf = parent._normalize_alias_key(leaf)
        if leaf not in parent._data:
            raise KeyError(f'Unknown configuration key: {key}')

        canonical_key = '.'.join(parts[:-1] + [leaf])
        prior = canonical_sources.get(canonical_key)
        if prior is not None and prior != key:
            raise TypeError(
                f'Multiple input keys {prior!r} and {key!r} target '
                f'configuration field {canonical_key!r}'
            )
        canonical_sources[canonical_key] = key

        if leaf in getattr(parent, '_subconfig_meta', {}):
            if not isinstance(value, Mapping):  # nocover - consumed as sugar
                raise TypeError(
                    f'SubConfig update for {key!r} must be a selector or mapping'
                )
            nested_updates = value
            nested_selector = value.get('__class__', _MISSING)
            if key not in selectors and nested_selector is not _MISSING:
                # This mapping was deferred because an earlier parent selector
                # had not exposed the SubConfig path yet. Realize its own
                # selector now, at the parent boundary, before applying child
                # fields.
                _apply_selectors_fixpoint(
                    cfg,
                    {key: nested_selector},
                    allow_import=allow_import,
                    localns=localns,
                )
            if nested_selector is not _MISSING:
                # A dotted selector at this source boundary wins over the
                # mapping spelling. In either case, the selector has already
                # been applied and must not be treated as a child field.
                nested_updates = {
                    nested_key: nested_value
                    for nested_key, nested_value in value.items()
                    if nested_key != '__class__'
                }
            child = parent._data[leaf]
            apply_dot_updates(
                child,
                nested_updates,
                allow_import=allow_import,
                localns=localns,
                stacklevel=None,
                validation_mode=validation_mode,
                structural_validation=structural_validation,
                provided_keys=provided_keys,
                _path_prefix=_path_prefix + tuple(parts[:-1]) + (leaf,),
            )
        else:
            parent._setitem(leaf, value, validation_mode=validation_mode)
            if provided_keys is not None:
                provided_keys.add(
                    '.'.join(_path_prefix + tuple(parts[:-1]) + (leaf,))
                )
    return cfg


def has_selector_overrides(cfg, updates):
    """
    Determine if updates contain selector overrides for SubConfig nodes.

    Example:
        >>> import kwconf
        >>> class Inner(kwconf.Config):
        ...     __default__ = {'x': 1}
        >>> class Outer(kwconf.Config):
        ...     __default__ = {'inner': kwconf.SubConfig(Inner)}
        >>> cfg = Outer(_dont_call_post_init=True)
        >>> wrap_subconfig_defaults(cfg, _dont_call_post_init=True)
        >>> assert has_selector_overrides(cfg, {'inner.__class__': 'inner'})
    """
    if not updates:
        return False
    if isinstance(updates, Mapping):
        flat_updates = dict(_flatten_nested(updates, cfg=cfg))
    else:
        return False
    subconfig_paths = set(find_subconfig_paths(cfg))
    for key in flat_updates:
        if key.endswith(_SELECTOR_SUFFIX):
            selector_path = key[: -len(_SELECTOR_SUFFIX)]
            if selector_path in subconfig_paths:
                return True
        if key in subconfig_paths:
            return True
    return False


def flatten_defaults(cfg, prefix=(), include_class_options=False):
    """
    Flatten config defaults into dotted keys.

    Example:
        >>> import kwconf
        >>> class Inner(kwconf.Config):
        ...     __default__ = {'x': 1}
        >>> class Outer(kwconf.Config):
        ...     __default__ = {'inner': kwconf.SubConfig(Inner)}
        >>> cfg = Outer(_dont_call_post_init=True)
        >>> wrap_subconfig_defaults(cfg, _dont_call_post_init=True)
        >>> flat = flatten_defaults(cfg)
        >>> assert 'inner.x' in flat
    """
    flat = {}
    for key, value in cfg._data.items():
        if key in getattr(cfg, '_subconfig_meta', {}):
            if include_class_options:
                selector_key = '.'.join(prefix + (key,))
                class_key = '.'.join(prefix + (key, '__class__'))
                flat[selector_key] = Value(
                    None, help=f'{key} implementation selector'
                )
                flat[class_key] = Value(
                    None, help=f'{key} implementation selector'
                )
            if isinstance(value, Config):
                flat.update(
                    flatten_defaults(
                        value, prefix + (key,), include_class_options
                    )
                )
        elif isinstance(value, Config):
            flat.update(
                flatten_defaults(value, prefix + (key,), include_class_options)
            )
        else:
            meta = cfg._default.get(key)
            leaf_key = '.'.join(prefix + (key,))
            if isinstance(meta, Value):
                flat[leaf_key] = meta
            else:
                flat[leaf_key] = value
    return flat


def flat_config_from_tree(cfg, include_class_options=False):
    """
    Build a temporary Config instance to parse realized leaf arguments.

    Example:
        >>> import kwconf
        >>> class Inner(kwconf.Config):
        ...     __default__ = {'x': 1}
        >>> class Outer(kwconf.Config):
        ...     __default__ = {'inner': kwconf.SubConfig(Inner)}
        >>> cfg = Outer(_dont_call_post_init=True)
        >>> wrap_subconfig_defaults(cfg, _dont_call_post_init=True)
        >>> flat = flat_config_from_tree(cfg)
        >>> assert 'inner.x' in flat.__default__
    """
    defaults = flatten_defaults(
        cfg, include_class_options=include_class_options
    )
    name = f'_Flat_{cfg.__class__.__name__}'
    FlatCls = type(name, (Config,), {'__default__': defaults})
    return FlatCls(_dont_call_post_init=True)


def expand_multipass_parser(
    cfg,
    parser,
    argv=None,
    special_options=True,
    allow_import=True,
    allow_subconfig_overrides=True,
    pending_updates=None,
    localns=None,
    stacklevel=None,
    validation_mode=None,
    structural_validation=False,
    provided_keys=None,
):
    """
    Expand an argparse parser for configs with nested SubConfig nodes.

    This staged parse realizes selector overrides first, then extends the
    supplied parser with arguments for the realized tree so the full argv can
    be parsed in a single pass with the standard logic in ``_read_argv``.
    Existing caller-defined arguments and parser identity are preserved.

    Example:
        >>> import argparse
        >>> import kwconf
        >>> class Inner(kwconf.Config):
        ...     __default__ = {'x': 1}
        >>> class Outer(kwconf.Config):
        ...     __default__ = {'inner': kwconf.SubConfig(Inner)}
        >>> cfg = Outer(_dont_call_post_init=True)
        >>> wrap_subconfig_defaults(cfg, _dont_call_post_init=True)
        >>> parser = argparse.ArgumentParser()
        >>> parser.add_argument('--sentinel')
        >>> original = parser
        >>> parser, argv = expand_multipass_parser(cfg, parser, argv=['--inner.x=2'])
        >>> assert parser is original
        >>> assert '--sentinel' in parser._option_string_actions
        >>> assert '--inner.x' in parser._option_string_actions
    """
    argv_list, _ = coerce_argv(True if argv is None else argv)

    # Apply lower-precedence mapping data before a --config file. This mirrors
    # the public load order: defaults < data= < --config < explicit argv.
    if pending_updates is not None:
        cfg_updates = pending_updates
        if not allow_subconfig_overrides and has_selector_overrides(
            cfg, cfg_updates
        ):
            raise ValueError(
                'SubConfig selection overrides require allow_subconfig_overrides=True'
            )
        apply_dot_updates(
            cfg,
            cfg_updates,
            allow_import=allow_import,
            localns=localns,
            stacklevel=stacklevel,
            validation_mode=validation_mode,
            structural_validation=structural_validation,
            provided_keys=provided_keys,
        )

    if special_options:
        config_fpath = scan_config_path(argv_list)
        if config_fpath is not None:
            from kwconf._ingest import coerce_mapping_source

            # Preserve the source mapping until apply_dot_updates so structural
            # validation can compare nested and dotted spellings before either
            # one is flattened away.
            cfg_updates = coerce_mapping_source(config_fpath)
            if not allow_subconfig_overrides and has_selector_overrides(
                cfg, cfg_updates
            ):
                raise ValueError(
                    'SubConfig selection overrides require allow_subconfig_overrides=True'
                )
            apply_dot_updates(
                cfg,
                cfg_updates,
                allow_import=allow_import,
                localns=localns,
                stacklevel=stacklevel,
                validation_mode=validation_mode,
                structural_validation=structural_validation,
                provided_keys=provided_keys,
            )

    if allow_subconfig_overrides:
        extract_selector_overrides(
            cfg,
            argv_list,
            allow_import=allow_import,
            localns=localns,
            stacklevel=stacklevel,
        )
        flat_helper = flat_config_from_tree(cfg, include_class_options=True)
        flat_helper.argparse(parser=parser, special_options=special_options)
    else:
        # Static parse path: disallow selector overrides and fail early.
        flat_helper = flat_config_from_tree(cfg, include_class_options=False)
        flat_helper.argparse(parser=parser, special_options=special_options)
        add_forbidden_selector_args(parser, cfg)
    return parser, argv_list


def finalize_post_init(cfg):
    """
    Run __post_init__ once on a nested config tree.

    Example:
        >>> import kwconf
        >>> class Inner(kwconf.Config):
        ...     __default__ = {'x': 1}
        >>> class Outer(kwconf.Config):
        ...     __default__ = {'inner': kwconf.SubConfig(Inner)}
        >>> cfg = Outer(_dont_call_post_init=True)
        >>> wrap_subconfig_defaults(cfg, _dont_call_post_init=True)
        >>> finalize_post_init(cfg)
    """
    if not isinstance(cfg, Config):
        return
    if not getattr(cfg, '_kwconf_post_init_done', False):
        cfg.__post_init__()
        cfg._kwconf_post_init_done = True
    for value in cfg._data.values():
        if isinstance(value, Config):
            finalize_post_init(value)


def _class_identifier(cls):
    """
    Return a module-qualified class identifier.

    Example:
        >>> import kwconf
        >>> assert _class_identifier(kwconf.Config).endswith('.Config')
    """
    qualname = cls.__qualname__
    if '<locals>' in qualname:
        # Local classes are not importable by qualname. Preserve the historical
        # best-effort spelling; stable round trips should use explicit choices.
        qualname = cls.__name__
    return f'{cls.__module__}.{qualname}'


def find_subconfig_paths(cfg):
    """
    Yield dotted paths to SubConfig nodes in the realized tree.

    Example:
        >>> import kwconf
        >>> class Inner(kwconf.Config):
        ...     __default__ = {'x': 1}
        >>> class Outer(kwconf.Config):
        ...     __default__ = {'inner': kwconf.SubConfig(Inner)}
        >>> cfg = Outer(_dont_call_post_init=True)
        >>> wrap_subconfig_defaults(cfg, _dont_call_post_init=True)
        >>> assert 'inner' in find_subconfig_paths(cfg)
    """
    paths: list[str] = []
    stack: list[tuple[list[str], Config]] = [([], cfg)]
    while stack:
        prefix, node = stack.pop()
        for key, value in node._data.items():
            next_prefix = prefix + [key]
            if key in getattr(node, '_subconfig_meta', {}):
                paths.append('.'.join(next_prefix))
            if isinstance(value, Config):
                stack.append((next_prefix, value))
    return paths


def _distribute_keys(cfg, keys, attr_name):
    """Distribute canonical dotted keys across a realized Config tree."""
    keys = frozenset(keys)
    setattr(cfg, attr_name, keys)
    child_keys: dict[str, set[str]] = {}
    for key in keys:
        head, sep, tail = key.partition('.')
        if not sep or not tail:
            continue
        child = cfg._data.get(head)
        if isinstance(child, Config):
            child_keys.setdefault(head, set()).add(tail)
    for head, child in cfg._data.items():
        if isinstance(child, Config):
            _distribute_keys(child, child_keys.get(head, set()), attr_name)


def distribute_explicit_argv_keys(cfg, keys):
    """
    Record argv-explicit provenance across a realized config tree.

    ``keys`` is the set of canonical (possibly dotted) destinations that were
    explicitly supplied on argv for ``cfg``. The full set is stored on
    ``cfg._explicit_argv_keys``; dotted keys are additionally distributed to
    the matching SubConfig children with their leading segment stripped,
    recursing into the realized tree so each node carries the keys relevant to
    it (e.g. the parent records ``inner.x`` while ``inner`` records ``x``).

    Example:
        >>> import kwconf
        >>> class Inner(kwconf.Config):
        ...     __default__ = {'x': 1}
        >>> class Outer(kwconf.Config):
        ...     __default__ = {'inner': kwconf.SubConfig(Inner)}
        >>> cfg = Outer(_dont_call_post_init=True)
        >>> wrap_subconfig_defaults(cfg, _dont_call_post_init=True)
        >>> distribute_explicit_argv_keys(cfg, {'inner.x'})
        >>> assert cfg._explicit_argv_keys == frozenset({'inner.x'})
        >>> assert cfg._data['inner']._explicit_argv_keys == frozenset({'x'})
    """
    _distribute_keys(cfg, keys, '_explicit_argv_keys')


def distribute_provided_keys(cfg, keys):
    """Record all fields supplied by the current load across the tree."""
    _distribute_keys(cfg, keys, '_provided_keys')


def config_to_nested_dict(cfg, include_class=True):
    """
    Convert a realized config tree to a nested dictionary.

    Example:
        >>> import kwconf
        >>> class Inner(kwconf.Config):
        ...     __default__ = {'x': 1}
        >>> class Outer(kwconf.Config):
        ...     __default__ = {'inner': kwconf.SubConfig(Inner)}
        >>> cfg = Outer(_dont_call_post_init=True)
        >>> wrap_subconfig_defaults(cfg, _dont_call_post_init=True)
        >>> data = config_to_nested_dict(cfg)
        >>> assert 'inner' in data
    """

    def unwrap(val):
        if isinstance(val, Value):
            return val.value
        return val

    result = {}
    meta_map = getattr(cfg, '_subconfig_meta', {})
    for key, value in cfg._data.items():
        meta = meta_map.get(key)
        if isinstance(value, Config):
            child = config_to_nested_dict(value, include_class=include_class)
            selector = None
            if meta is not None and meta.choices:
                selected_cls = type(value)
                for name, cls in meta.choices.items():
                    if selected_cls is cls:
                        selector = name
                        break
            if selector is None:
                selector = _class_identifier(value.__class__)
            # Always record the selected implementation for SubConfig nodes.
            if meta is not None or include_class:
                child['__class__'] = selector
            result[key] = child
        else:
            result[key] = unwrap(value)
    return result
