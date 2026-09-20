"""Conservative Rust-backed success path for static ModalCLI command trees."""

from __future__ import annotations

import os
import sys

from kwconf._typing_runtime import Any

NOT_HANDLED = object()


def _has_named_parameter(func: Any, name: str) -> bool:
    """Check a normal Python callable without importing inspect.

    Modal Config.main methods are ordinary Python functions/classmethods in the
    common path.  Fall back to inspect only for exotic callables without a
    code object so compatibility is preserved without paying inspect's import
    cost on every accelerated modal invocation.
    """
    target = getattr(func, '__func__', func)
    code = getattr(target, '__code__', None)
    if code is not None:
        count = code.co_argcount + code.co_kwonlyargcount
        return name in code.co_varnames[:count]

    import inspect

    return name in inspect.signature(func).parameters


def _normalize_modal_argv(argv):
    if isinstance(argv, (int, bool)):
        return list(sys.argv[1:]) if argv else []
    if argv is None:
        return list(sys.argv[1:])
    if isinstance(argv, (list, tuple)):
        return list(argv)
    return list(argv)


def try_modal_main(
    modal: Any,
    argv,
    *,
    strict: bool,
    autocomplete: bool | str,
):
    """Return a ModalCLI result, or ``NOT_HANDLED`` for canonical fallback.

    Only successful static command routing is claimed. Diagnostics, versions,
    help, opaque commands, parser-policy inheritance mismatches, and extension
    absence all remain owned by the existing argparse implementation.
    """
    backend = os.environ.get(
        'KWCONF_CLI_BACKEND', getattr(modal, '__cli_backend__', 'auto')
    ).lower()
    if backend == 'python':
        return NOT_HANDLED
    if backend not in {'auto', 'rust'}:
        return NOT_HANDLED
    if autocomplete is True or '_ARGCOMPLETE' in os.environ:
        return NOT_HANDLED

    args = _normalize_modal_argv(argv)
    if not args:
        return NOT_HANDLED

    try:
        from kwconf import _completion, _rust

        if backend == 'auto' and not _rust.extension_available():
            return NOT_HANDLED
        option_specs, command_specs, leaf_by_path = _completion._modal_static_model(
            modal
        )
        # Reuse the same compact Rust command index as completion. Options are
        # not needed for routing; leaf Config.cli() owns the remaining argv.
        index = _rust.make_completion_index([], command_specs)
        routed = index.route(args)
    except Exception:
        if backend == 'rust':
            # Explicit rust still delegates unsupported modal shapes; it means
            # "accelerate when semantics are covered", not "replace canonical
            # argparse diagnostics with partial Rust errors".
            return NOT_HANDLED
        return NOT_HANDLED
    if routed is None:
        return NOT_HANDLED
    path, consumed = routed
    leaf_info = leaf_by_path.get(tuple(path))
    if leaf_info is None:
        return NOT_HANDLED

    metadata = leaf_info['metadata']
    leaf = metadata['subconfig']
    # Modal argparse construction propagates ancestor policy to a leaf. Config
    # .cli() has no override parameter for those parser policies, so only claim
    # the route when its normal class policy is equivalent.
    if bool(getattr(leaf, '__fuzzy_hyphens__', 1)) != bool(
        leaf_info['effective_fuzzy']
    ):
        return NOT_HANDLED
    if bool(getattr(leaf, '__short_alias_clusters__', True)) != bool(
        leaf_info['effective_short_clusters']
    ):
        return NOT_HANDLED
    leaf_cls = type(leaf)
    if getattr(leaf_cls, '__cli_backend__', 'auto') == 'python':
        return NOT_HANDLED

    remaining = args[consumed:]
    # Prove that the leaf's direct Rust path will accept the argv before any
    # user-visible parse lifecycle begins. If this probe declines, let the
    # canonical modal parser run exactly once.
    try:
        probe = leaf_cls(_dont_call_post_init=True)
        native_probe = _rust.try_parse_config(
            probe,
            remaining,
            strict=strict,
            required_extension=(backend == 'rust'),
        )
    except Exception:
        return NOT_HANDLED
    if native_probe is None:
        return NOT_HANDLED

    parsed = leaf_cls.cli(
        argv=remaining,
        strict=strict,
        autocomplete=False,
        special_options=False,
    )

    explicit = getattr(parsed, '_explicit_argv_keys', frozenset())
    explicit_kw = {key: parsed[key] for key in explicit if key in parsed}
    sub_main = metadata['main_func']
    control_kw = {'argv': False} if _has_named_parameter(sub_main, 'argv') else {}
    ret = sub_main(**control_kw, **explicit_kw)
    return 0 if ret is None else ret
