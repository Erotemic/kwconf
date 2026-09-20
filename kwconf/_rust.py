"""Experimental lazy bridge to the optional ``_kwconf_rust`` accelerator.

The normal kwconf import path does not import this module, and this module does
not import the extension until an accelerated CLI parse is requested.  The
first experiment deliberately targets the common flat-Config argv path rather
than attempting to replace argparse's help/error machinery.

The accelerator is conservative: if a schema or argv shape falls outside the
implemented fast path it returns ``None`` and kwconf runs its existing argparse
path.  This keeps the experiment useful for real applications without making
partial Rust semantics authoritative.
"""

from __future__ import annotations

from kwconf._typing_runtime import Any
from kwconf.util.util_misc import NoParam
from kwconf.value import _resolve_alias

# These values are part of the tiny private FFI between this module and
# rust/kwconf_accel.  Keep them boring integers so PyO3 conversion is cheap.
_KIND_VALUE = 0
_KIND_FLAG = 1
_KIND_COUNTER = 2
_KIND_OPTIONAL = 3

_OP_VALUE = 0
_OP_FLAG_BARE = 1
_OP_FLAG_VALUE = 2
_OP_COUNTER_BARE = 3
_OP_COUNTER_VALUE = 4
_OP_OPTIONAL_BARE = 5

_BACKEND_PROTOCOL_NAME = 'kwconf-cli-core'
_BACKEND_PROTOCOL_VERSION = 3

_EXTENSION: Any = None
_EXTENSION_TRIED = False
_EXTENSION_ERROR: str | None = None
_CACHE_GENERATION = 0
_CACHED_SCHEMA_COUNT = 0
_UNSUPPORTED_SCHEMA_COUNT = 0
_SCHEMA_CACHE_ATTR = '_kwconf_rust_compiled_schema'
_UNSUPPORTED_CACHE_ATTR = '_kwconf_rust_unsupported_schema'


class UnsupportedSchema(RuntimeError):
    """Raised by explicit compilation when a Config cannot use the fast path."""


class _CompiledConfig:
    """Small immutable-by-convention FFI record without dataclasses startup."""

    __slots__ = ('parser', 'keys', 'templates', 'mutex_groups', 'required_keys')
    parser: Any
    keys: tuple[str, ...]
    templates: tuple[Any, ...]
    mutex_groups: tuple[tuple[str, ...], ...]
    required_keys: tuple[str, ...]

    def __init__(self, *, parser, keys, templates, mutex_groups, required_keys):
        self.parser = parser
        self.keys = keys
        self.templates = templates
        self.mutex_groups = mutex_groups
        self.required_keys = required_keys


class FastParseResult:
    """Minimal parse result consumed by :meth:`Config._read_argv`."""

    __slots__ = ('values', 'explicit_keys', 'unknown_args')
    values: dict[str, Any]
    explicit_keys: frozenset[str]
    unknown_args: tuple[str, ...]

    def __init__(self, *, values, explicit_keys, unknown_args):
        self.values = values
        self.explicit_keys = explicit_keys
        self.unknown_args = unknown_args


def _load_extension(*, required: bool) -> Any:
    """Load and protocol-check the optional accelerator once per process.

    The binary is intentionally a separate distribution so kwconf can remain
    pure Python when no wheel exists for a platform.  A protocol check is
    therefore mandatory: an older accelerator may remain installed while the
    Python package is upgraded independently.  ``auto`` treats an incompatible
    wheel exactly like a missing wheel; explicit ``rust`` mode reports the
    incompatibility instead of attempting an unsafe FFI call.
    """
    global _EXTENSION, _EXTENSION_TRIED, _EXTENSION_ERROR
    if not _EXTENSION_TRIED:
        _EXTENSION_TRIED = True
        try:
            candidate = __import__('_kwconf_rust')
        except ImportError as ex:
            _EXTENSION = None
            _EXTENSION_ERROR = f'extension import failed: {ex}'
        else:
            try:
                name, version = candidate.backend_info()
            except Exception as ex:
                _EXTENSION = None
                _EXTENSION_ERROR = (
                    'extension does not expose a usable backend_info(): '
                    f'{type(ex).__name__}: {ex}'
                )
            else:
                expected = (_BACKEND_PROTOCOL_NAME, _BACKEND_PROTOCOL_VERSION)
                actual = (name, version)
                if actual != expected:
                    _EXTENSION = None
                    _EXTENSION_ERROR = (
                        'extension protocol mismatch: '
                        f'expected {expected!r}, got {actual!r}'
                    )
                else:
                    _EXTENSION = candidate
                    _EXTENSION_ERROR = None
    if _EXTENSION is None and required:
        detail = f' ({_EXTENSION_ERROR})' if _EXTENSION_ERROR else ''
        raise ImportError(
            'The kwconf Rust CLI backend is unavailable or incompatible'
            f'{detail}. Build/install a matching accelerator with: '
            'python dev/rust_backend/build_backend.py --release'
        )
    return _EXTENSION


def extension_available() -> bool:
    """Return whether the optional extension can be imported."""
    return _load_extension(required=False) is not None


def clear_cache() -> None:
    """Invalidate compiled schema caches without retaining Config classes.

    Cache records live on the Config classes themselves. Advancing a generation
    invalidates every record in O(1) while allowing dynamically-created classes
    to be garbage-collected normally.
    """
    global _CACHE_GENERATION, _CACHED_SCHEMA_COUNT, _UNSUPPORTED_SCHEMA_COUNT
    _CACHE_GENERATION += 1
    _CACHED_SCHEMA_COUNT = 0
    _UNSUPPORTED_SCHEMA_COUNT = 0


def _class_cache_get(cls: type, attr: str) -> Any:
    item = cls.__dict__.get(attr)
    if item is None:
        return None
    generation, value = item
    if generation != _CACHE_GENERATION:
        return None
    return value


def _class_cache_set(cls: type, attr: str, value: Any) -> None:
    setattr(cls, attr, (_CACHE_GENERATION, value))


_SAFE_CALLABLE_PARSERS = frozenset({str, int, float, complex, bool})
_SAFE_NAMED_PARSERS = frozenset({'auto', 'yaml', 'csv'})
_SAFE_CHOICE_TYPES = (type(None), bool, int, float, complex, str, bytes)
_SHELL_COMPLETION_SPECIAL = frozenset("\\();<>|&!`$*?[]{} \t\n\r\"':")


def _field_is_accelerator_safe(template: Any, key: str) -> None:
    """Reject Python callbacks whose effects cannot safely be replayed.

    A fast-path miss deliberately re-runs the argv through argparse so argparse
    remains authoritative for diagnostics.  Calling an arbitrary user parser
    before that decision would make a fallback invoke it twice.  Only builtin
    scalar callables and kwconf's own named parsers are therefore admitted.
    Flags/counters do not route explicit values through ``Value.coerce`` and
    are exempt from this check.
    """
    if not template.isflag:
        parser_spec = getattr(template, '_parser_spec', None)
        if parser_spec is not None:
            if callable(parser_spec):
                if parser_spec not in _SAFE_CALLABLE_PARSERS:
                    raise UnsupportedSchema(
                        f'custom parser callable for {key!r} requires argparse'
                    )
            elif (
                not isinstance(parser_spec, str)
                or parser_spec not in _SAFE_NAMED_PARSERS
            ):
                raise UnsupportedSchema(
                    f'custom named parser {parser_spec!r} for {key!r} '
                    'requires argparse'
                )
        elif getattr(template, '_user_gave_type', False):
            type_parser = template.type
            if type_parser not in _SAFE_CALLABLE_PARSERS:
                raise UnsupportedSchema(
                    f'custom type callable for {key!r} requires argparse'
                )

        choices = template.parsekw.get('choices')
        if choices is not None:
            try:
                choices_are_atomic = all(
                    isinstance(choice, _SAFE_CHOICE_TYPES) for choice in choices
                )
            except TypeError:
                choices_are_atomic = False
            if not choices_are_atomic:
                # ``value in choices`` can execute arbitrary ``__eq__`` code.
                # Keep that comparison on the one-shot argparse path so a
                # later fallback cannot repeat user-visible side effects.
                raise UnsupportedSchema(
                    f'non-primitive choices for {key!r} require argparse'
                )


def _is_realized_config_node(value: Any) -> bool:
    """Cheap internal Config check that does not import the nested stack."""
    return (
        hasattr(value, '_data')
        and hasattr(value, '_default')
        and hasattr(value, '_argument_key_order')
    )


def _flatten_schema_items(config: Any) -> list[tuple[str, Any]]:
    """Return canonical dotted leaves without importing ``subconfig``.

    The instance has already materialized its SubConfig tree.  Walking that
    tree directly keeps the successful nested Rust path independent of
    ``kwconf.subconfig`` (and therefore independent of its argparse machinery).
    Dynamic selector requests are still declined later because selector option
    spellings are intentionally absent from the parse schema.
    """
    if not getattr(config, '_has_subconfigs', False):
        return [(key, config._default[key]) for key in config._argument_key_order()]

    flattened: list[tuple[str, Any]] = []

    def visit(node: Any, prefix: tuple[str, ...]) -> None:
        for key in node._argument_key_order():
            value = node._data.get(key)
            path = prefix + (key,)
            if _is_realized_config_node(value):
                visit(value, path)
            else:
                template = node._default[key]
                flattened.append(('.'.join(path), template))

    visit(config, ())
    return flattened


def _schema_description(
    config: Any,
) -> tuple[list[tuple[str, list[str], int]], _CompiledConfig]:
    """Build the Python side of a flat or realized nested CLI schema.

    Dynamic SubConfig selector options are intentionally *not* included.  A
    selector token therefore makes the Rust parser decline and the canonical
    multipass Python path remains authoritative.  Fixed realized leaf options
    such as ``--optimizer.lr`` can still use the fast path.
    """
    specs: list[tuple[str, list[str], int]] = []
    templates: list[Any] = []
    mutex_lut: dict[str, list[str]] = {}
    required_keys: list[str] = []
    fuzzy_hyphens = bool(getattr(config, '__fuzzy_hyphens__', 1))
    if not getattr(config, '__short_alias_clusters__', True):
        raise UnsupportedSchema(
            '__short_alias_clusters__ = False is not accelerated yet'
        )

    for key, template in _flatten_schema_items(config):
        _field_is_accelerator_safe(template, key)
        if template.position is not None:
            raise UnsupportedSchema('positional arguments are not accelerated yet')

        nargs = template.parsekw.get('nargs')
        if template.isflag == 'counter':
            kind = _KIND_COUNTER
        elif template.isflag:
            kind = _KIND_FLAG
        elif template.bare is not NoParam or nargs == '?':
            kind = _KIND_OPTIONAL
        else:
            kind = _KIND_VALUE

        if not template.isflag and kind != _KIND_OPTIONAL and nargs is not None:
            raise UnsupportedSchema(
                f'nargs={nargs!r} for {key!r} is not accelerated yet'
            )
        if kind == _KIND_OPTIONAL and nargs not in {None, '?'}:
            raise UnsupportedSchema(
                f'nargs={nargs!r} for {key!r} is not accelerated yet'
            )

        option_strings = _resolve_alias(key, template, fuzzy_hyphens)
        specs.append((key, option_strings, kind))
        templates.append(template)
        if template.required:
            required_keys.append(key)
        if template.mutex_group is not None:
            # Nested groups are scoped by their owning config node. Prefix the
            # group id with the dotted parent path so identical local group
            # names in two subconfigs do not conflict.
            parent = key.rpartition('.')[0]
            group_id = f'{parent}:{template.mutex_group}'
            mutex_lut.setdefault(group_id, []).append(key)

    placeholder = _CompiledConfig(
        parser=None,
        keys=tuple(spec[0] for spec in specs),
        templates=tuple(templates),
        mutex_groups=tuple(tuple(v) for v in mutex_lut.values()),
        required_keys=tuple(required_keys),
    )
    return specs, placeholder


def completion_selector_spellings(config: Any) -> tuple[str, ...]:
    """Return canonical selector options for realized nested SubConfigs.

    Selector *names* are static, but selector values can change the realized
    leaf schema.  The completion layer can therefore advertise these option
    names natively and still delegate any cursor state after a selector was
    consumed to canonical argcomplete.
    """
    if not getattr(config, '_has_subconfigs', False):
        return ()

    spellings: list[str] = []

    def visit(node: Any, prefix: tuple[str, ...]) -> None:
        subconfig_meta = getattr(node, '_subconfig_meta', {})
        for key in node._argument_key_order():
            value = node._data.get(key)
            path = prefix + (key,)
            if key in subconfig_meta:
                dotted = '.'.join(path)
                spellings.extend((f'--{dotted}', f'--{dotted}.__class__'))
            if _is_realized_config_node(value):
                visit(value, path)

    visit(config, ())
    return tuple(spellings)


def completion_specs_for_config(
    config: Any,
    *,
    special_options: bool = False,
    fuzzy_hyphens: int | bool | None = None,
) -> list[tuple[list[str], list[str], bool, list[str], str]]:
    """Return Rust-completion option records for a realized Config tree."""
    specs = []
    own_fuzzy = bool(getattr(config, '__fuzzy_hyphens__', 1))
    fuzzy_hyphens = own_fuzzy if (fuzzy_hyphens is None or fuzzy_hyphens) else False
    for key, template in _flatten_schema_items(config):
        if template.position is not None:
            # Static positional completion needs filesystem/custom completers;
            # leave the entire active request to argcomplete instead.
            raise UnsupportedSchema('positional completion requires argcomplete')
        option_strings = list(_resolve_alias(key, template, fuzzy_hyphens))
        if any(
            any(ch in _SHELL_COMPLETION_SPECIAL for ch in spelling)
            for spelling in option_strings
        ):
            raise UnsupportedSchema(
                f'shell-sensitive option spelling for {key!r} requires argcomplete'
            )
        if template.mutex_group is not None:
            # Argcomplete suppresses actions that conflict with an option
            # already seen. Keep that stateful rule canonical until the Rust
            # index carries the same mutex graph.
            raise UnsupportedSchema(
                f'mutex completion for {key!r} requires argcomplete'
            )
        if template.isflag:
            # kwconf's flag/counter argparse actions synthesize --no-* spellings.
            # Include those in the static index as well.
            for spelling in list(option_strings):
                if spelling.startswith('--'):
                    negative = '--no-' + spelling[2:]
                    if negative not in option_strings:
                        option_strings.append(negative)
        choices = template.parsekw.get('choices')
        choice_text = []
        if choices is not None:
            try:
                if not all(isinstance(c, _SAFE_CHOICE_TYPES) for c in choices):
                    raise UnsupportedSchema(
                        f'non-primitive completion choices for {key!r}'
                    )
                choice_text = [str(c) for c in choices]
                # Our native completion path intentionally handles only the
                # simple, unquoted shell grammar.  Argcomplete performs shell
                # escaping / COMP_WORDBREAKS handling for richer candidates;
                # delegate those rather than producing subtly different text.
                if any(
                    any(ch in _SHELL_COMPLETION_SPECIAL for ch in text)
                    for text in choice_text
                ):
                    raise UnsupportedSchema(
                        f'shell-sensitive completion choices for {key!r} require argcomplete'
                    )
            except TypeError as ex:
                raise UnsupportedSchema(
                    f'non-iterable completion choices for {key!r}'
                ) from ex
        # Boolean/counter actions use nargs='?' for explicit key/value input,
        # but argcomplete does not treat the bare flag as a required value
        # position. Scalar/bare Value actions do.
        takes_value = not bool(template.isflag)
        help_text = template.parsekw.get('help') or ''
        if help_text == '==SUPPRESS==':
            continue
        specs.append(([], option_strings, takes_value, choice_text, str(help_text)))

    # Selector option names are static even though their values may rebuild the
    # realized nested tree.  Expose the names in the fast index, but deliberately
    # leave their choices empty: CoreCompletionIndex returns None for the value
    # position, which hands filesystem/import/custom semantics to argcomplete.
    # Once a selector has been consumed, the Python completion shim also
    # delegates the rest of that request because the static leaf index may no
    # longer describe the selected class.
    for selector in completion_selector_spellings(config):
        specs.append(
            (
                [],
                [selector],
                True,
                [],
                'SubConfig implementation selector',
            )
        )

    specs.append(([], ['-h', '--help'], False, [], 'show this help message and exit'))
    if special_options:
        specs.extend(
            [
                ([], ['--config'], True, [], 'load an on-disk configuration file'),
                ([], ['--dump'], True, [], 'dump this config to disk'),
                ([], ['--dumps'], False, [], 'dump this config to stdout'),
            ]
        )
    return specs


def make_completion_index(option_specs, command_specs=()):
    """Construct the backend's reusable static completion index."""
    extension = _load_extension(required=True)
    return extension.CompletionIndex(list(option_specs), list(command_specs))


def compile_completion_index(config: Any, *, special_options: bool = False):
    """Compile static Config completion metadata without constructing argparse."""
    return make_completion_index(
        completion_specs_for_config(config, special_options=special_options),
        [],
    )

def compile_config(config: Any, *, cache: bool = True) -> _CompiledConfig:
    """Compile a flat Config schema into the Rust token parser.

    This function is intentionally public only inside ``kwconf._rust`` so the
    benchmark can distinguish schema-build cost from parser-reuse cost.
    """
    global _CACHED_SCHEMA_COUNT, _UNSUPPORTED_SCHEMA_COUNT
    cls = type(config)
    # Scalar default overrides preserve CLI metadata, but update_defaults() may
    # also receive a full Value with different aliases/parser metadata. Such an
    # instance must compile from its own schema instead of reusing the class
    # cache.
    cache = (
        cache
        and not getattr(config, '_rust_schema_mutated', False)
        and not getattr(config, '_has_subconfigs', False)
    )
    if cache:
        cached = _class_cache_get(cls, _SCHEMA_CACHE_ATTR)
        if cached is not None:
            return cached
        reason = _class_cache_get(cls, _UNSUPPORTED_CACHE_ATTR)
        if reason is not None:
            raise UnsupportedSchema(reason)

    try:
        specs, metadata = _schema_description(config)
    except UnsupportedSchema as ex:
        if cache:
            _class_cache_set(cls, _UNSUPPORTED_CACHE_ATTR, str(ex))
            _UNSUPPORTED_SCHEMA_COUNT += 1
        raise

    extension = _load_extension(required=True)
    try:
        parser = extension.FlatParser(specs)
    except (TypeError, ValueError) as ex:
        # Let the normal argparse path remain authoritative for schema conflict
        # diagnostics.  Cache only the fact that this class was unsuitable.
        reason = f'Rust schema construction refused this config: {ex}'
        if cache:
            _class_cache_set(cls, _UNSUPPORTED_CACHE_ATTR, reason)
            _UNSUPPORTED_SCHEMA_COUNT += 1
        raise UnsupportedSchema(reason) from ex

    compiled = _CompiledConfig(
        parser=parser,
        keys=metadata.keys,
        templates=metadata.templates,
        mutex_groups=metadata.mutex_groups,
        required_keys=metadata.required_keys,
    )
    if cache:
        _class_cache_set(cls, _SCHEMA_CACHE_ATTR, compiled)
        _CACHED_SCHEMA_COUNT += 1
    return compiled


def _infer_scalar(text: Any) -> Any:
    # Import lazily so the bridge does not duplicate kwconf's flag-value
    # coercion contract.  This is intentionally the exact existing helper.
    from kwconf.argparse_ext import _infer_scalar as infer

    return infer(text)


def _dotted_current_value(config: Any, key: str) -> Any:
    node = config
    parts = key.split('.')
    for part in parts[:-1]:
        node = node._data[part]
    return node._data[parts[-1]]


def _coerce_assignment(
    config: Any,
    key: str,
    template: Any,
    op: int,
    raw: Any,
    current: dict[str, Any],
) -> Any:
    if op == _OP_VALUE:
        return template.coerce(raw[0])
    if op == _OP_OPTIONAL_BARE:
        if template.bare is NoParam:
            return None
        return template.bare
    if op == _OP_FLAG_BARE:
        return not bool(raw[1])
    if op == _OP_FLAG_VALUE:
        value = _infer_scalar(raw[0])
        return (not value) if raw[1] else value
    if op == _OP_COUNTER_BARE:
        previous = current.get(key, _dotted_current_value(config, key))
        if previous is None:
            previous = 0
        return previous + (0 if raw[1] else 1)
    if op == _OP_COUNTER_VALUE:
        value = _infer_scalar(raw[0])
        return (not value) if raw[1] else value
    raise AssertionError(f'unknown Rust assignment op={op!r}')

def parse_compiled(
    config: Any,
    compiled: _CompiledConfig,
    argv: list[str],
    *,
    strict: bool,
) -> FastParseResult | None:
    """Run one compiled schema, returning ``None`` when argparse must decide."""
    assignments, unknown, fallback_reason = compiled.parser.parse(argv)
    if fallback_reason is not None:
        return None
    if strict and unknown:
        # Delegate user-facing error wording / usage selection to argparse.
        return None

    current: dict[str, Any] = {}
    explicit: set[str] = set()
    for field_index, op, raw in assignments:
        key = compiled.keys[field_index]
        template = compiled.templates[field_index]
        try:
            value = _coerce_assignment(
                config, key, template, op, raw, current
            )
        except Exception:
            # Coercion errors are part of the existing argparse-facing error
            # behavior. Re-run through that path rather than creating a second
            # set of diagnostics in this experiment.
            return None
        choices = template.parsekw.get('choices')
        if not template.isflag and choices is not None and value not in choices:
            return None
        current[key] = value
        explicit.add(key)
    for group in compiled.mutex_groups:
        if sum(key in explicit for key in group) > 1:
            return None
    if any(key not in explicit for key in compiled.required_keys):
        # Let argparse produce the canonical usage/error text. Successful
        # required-option parses still stay entirely on the Rust fast path.
        return None

    return FastParseResult(
        values=current,
        explicit_keys=frozenset(explicit),
        unknown_args=tuple(unknown),
    )


def try_compile_config(
    config: Any,
    *,
    required_extension: bool,
) -> _CompiledConfig | None:
    """Compile the accelerated schema, returning None for delegated shapes."""
    if _load_extension(required=required_extension) is None:
        return None
    try:
        return compile_config(config, cache=True)
    except UnsupportedSchema:
        return None


def try_parse_config(
    config: Any,
    argv: list[str],
    *,
    strict: bool,
    required_extension: bool,
) -> FastParseResult | None:
    """Try the Rust CLI fast path and conservatively fall back on miss."""
    if '--' in argv:
        # End-of-options handling interacts with positional / parse-known
        # behavior in argparse. Keep that compatibility surface authoritative
        # until the differential corpus proves the Rust grammar equivalent.
        return None

    compiled = try_compile_config(
        config, required_extension=required_extension
    )
    if compiled is None:
        return None
    return parse_compiled(config, compiled, argv, strict=strict)


def backend_status(config: Any | None = None) -> dict[str, Any]:
    """Return lightweight diagnostic information for experiments."""
    available = extension_available()
    info: dict[str, Any] = {
        'extension_available': available,
        'extension_error': _EXTENSION_ERROR,
        'protocol': (_BACKEND_PROTOCOL_NAME, _BACKEND_PROTOCOL_VERSION),
        'capabilities': (
            tuple(_EXTENSION.backend_capabilities())
            if available and hasattr(_EXTENSION, 'backend_capabilities')
            else ()
        ),
        'cached_schema_count': _CACHED_SCHEMA_COUNT,
        'unsupported_schema_count': _UNSUPPORTED_SCHEMA_COUNT,
    }
    if config is not None:
        cls = type(config)
        info['class_cached'] = (
            _class_cache_get(cls, _SCHEMA_CACHE_ATTR) is not None
        )
        info['class_unsupported_reason'] = _class_cache_get(
            cls, _UNSUPPORTED_CACHE_ATTR
        )
    return info
