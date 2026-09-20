"""Fast static shell completion for the optional Rust backend.

The public kwconf completion contract remains argcomplete-compatible.  This
module only claims completion requests that can be answered from static schema
metadata (option spellings, primitive choices, and modal command names) and
whose shell prefix can be tokenized without shell expansion.  Anything richer
falls back to the real argcomplete integration unchanged.
"""

from __future__ import annotations

import os
import sys

from kwconf._typing_runtime import Any


def _active_argcomplete(autocomplete: bool | str) -> bool:
    return bool(autocomplete) and '_ARGCOMPLETE' in os.environ


def _native_protocol_safe() -> bool:
    """Return whether the active argcomplete wire protocol is simple enough.

    Bash candidate-only completion is the native performance target. Other
    shell adapters and descriptive protocols remain byte-for-byte owned by
    argcomplete until their post-processing rules are covered explicitly.
    """
    ifs = os.environ.get('_ARGCOMPLETE_IFS', '\013')
    dfs = os.environ.get('_ARGCOMPLETE_DFS')
    if len(ifs) != 1 or (dfs and len(dfs) != 1):
        return False
    shell = os.environ.get('_ARGCOMPLETE_SHELL')
    if shell not in {None, '', 'bash'}:
        return False
    if dfs:
        return False
    return True


def _simple_completion_context() -> tuple[list[str], str] | None:
    """Return ``(argv_before_current, prefix)`` for a simple argcomplete line.

    Quotes, escapes, command substitutions, and non-default word-break syntax
    deliberately return ``None``.  Argcomplete remains the authority for those
    cases.  The fast path covers ordinary option / choice / subcommand TAB
    completion without importing argparse or argcomplete.
    """
    try:
        line = os.environ['COMP_LINE']
        point = int(os.environ['COMP_POINT'])
        start = int(os.environ.get('_ARGCOMPLETE', '1')) - 1
    except (KeyError, ValueError):
        return None
    if point < 0 or point > len(line):
        return None
    text = line[:point]
    # Keep this grammar intentionally conservative.  Shell quoting is where
    # argcomplete earns its complexity; do not create a second shell parser.
    if any(ch in text for ch in "'\"\\`$(){}[];|&<>\n\r\t"):
        return None
    words = text.split(' ')
    if start < 0 or start >= max(len(words), 1):
        return None
    words = words[start:]
    # Argcomplete keeps the invoked program/module as comp_words[0] and feeds
    # only comp_words[1:] to argparse.  The Rust completion index consumes
    # argv rather than a process command, so drop that same leading token.
    compact = [word for word in words if word]
    if compact:
        compact = compact[1:]
    if text.endswith(' '):
        prefix = ''
        argv_before = compact
    else:
        if not compact:
            return [], ''
        prefix = compact[-1]
        argv_before = compact[:-1]
    return argv_before, prefix


def _write_argcomplete_result(
    completions: list[tuple[str, str]],
    *,
    output_stream=None,
) -> None:
    """Write completions using argcomplete's fd/env protocol."""
    ifs = os.environ.get('_ARGCOMPLETE_IFS', '\013')
    dfs = os.environ.get('_ARGCOMPLETE_DFS')
    if len(ifs) != 1 or (dfs and len(dfs) != 1):
        raise ValueError('invalid argcomplete IFS/DFS environment')

    values: list[str] = []
    shell = os.environ.get('_ARGCOMPLETE_SHELL')
    for candidate, description in completions:
        if shell == 'zsh':
            values.append(f'{candidate}:{description}')
        elif dfs:
            values.append(dfs.join((candidate, description.replace(ifs, ' '))))
        else:
            values.append(candidate)

    close_stream = False
    if output_stream is None:
        filename = os.environ.get('_ARGCOMPLETE_STDOUT_FILENAME')
        if filename:
            output_stream = open(filename, 'w')
            close_stream = True
        else:
            # Match argcomplete's standard shell protocol.  dup() avoids
            # closing the shell-owned descriptor when the Python file object
            # is collected.
            output_stream = os.fdopen(os.dup(8), 'w')
            close_stream = True
    try:
        output_stream.write(ifs.join(values))
        output_stream.flush()
    finally:
        if close_stream:
            output_stream.close()


def _complete_with_index(index: Any, context) -> list[tuple[str, str]] | None:
    if context is None:
        return None
    argv_before, prefix = context
    # Preserve canonical argcomplete behavior for cursor states whose output
    # depends on shell word-break processing rather than only schema metadata.
    # In particular, bash treats '=' as a completion word break and argparse
    # stops interpreting options after a standalone '--'.  Let argcomplete own
    # those positions byte-for-byte instead of growing a second shell parser.
    if '=' in prefix or '--' in argv_before:
        return None
    try:
        complete_values = getattr(index, 'complete_values', None)
        if complete_values is not None:
            values = complete_values(argv_before, prefix)
            result = None if values is None else [(value, '') for value in values]
        else:
            result = index.complete(argv_before, prefix)
    except Exception:
        return None
    if result is None:
        # The index recognized that this cursor position requires a dynamic
        # completer (filesystem, Python callback, or richer argcomplete state).
        return None
    return [(str(candidate), str(help_text or '')) for candidate, help_text in result]


def _argcomplete_quote_simple(
    completions: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Match argcomplete's simple unquoted completion post-processing.

    ``_simple_completion_context`` rejects shell quoting / word-break syntax,
    so the only canonical transformation left on this path is argcomplete's
    default unique-match trailing space.  Continuation characters deliberately
    suppress it.  Complex candidate text is rejected while compiling the
    static index and therefore remains owned by real argcomplete.
    """
    if len(completions) != 1:
        return completions
    if os.environ.get('_ARGCOMPLETE_SUPPRESS_SPACE') == '1':
        return completions
    candidate, description = completions[0]
    if candidate and candidate[-1] not in '=/:':
        candidate += ' '
    return [(candidate, description)]


def _finish_native_completion(
    completions: list[tuple[str, str]] | None,
    *,
    output_stream=None,
    exit_method=None,
) -> bool:
    if completions is None:
        return False
    completions = _argcomplete_quote_simple(completions)
    _write_argcomplete_result(completions, output_stream=output_stream)
    if exit_method is None:
        exit_method = os._exit
    exit_method(0)
    return True  # pragma: no cover - ordinary exit methods do not return


def try_config_argcomplete(
    config: Any,
    *,
    autocomplete: bool | str = 'auto',
    special_options: bool = False,
    output_stream=None,
    exit_method=None,
) -> bool:
    """Answer a static Config completion request with Rust when safe.

    Returns False when argcomplete should receive the canonical argparse parser.
    """
    if not _active_argcomplete(autocomplete):
        return False
    # Descriptive completion protocols ask argparse's formatter to expand help
    # (including default-value text and formatter-specific styling). Preserve
    # byte parity by delegating those richer display modes to argcomplete; the
    # native path targets the ordinary candidate-only TAB protocol.
    if not _native_protocol_safe():
        return False
    backend = os.environ.get(
        'KWCONF_CLI_BACKEND', getattr(config, '__cli_backend__', 'auto')
    ).lower()
    if backend == 'python':
        return False
    if backend not in {'auto', 'rust'}:
        return False
    context = _simple_completion_context()
    if context is None:
        return False
    try:
        from kwconf import _rust

        argv_before, _prefix = context
        selectors = set(_rust.completion_selector_spellings(config))
        # A selector changes the realized nested schema.  We can complete the
        # selector option name itself natively, but after any selector token has
        # appeared the canonical multipass/argcomplete path must rebuild the
        # selected tree before offering leaf completions.
        if selectors and any(
            token in selectors
            or any(token.startswith(spelling + '=') for spelling in selectors)
            for token in argv_before
        ):
            return False

        index = _rust.compile_completion_index(
            config,
            special_options=special_options,
        )
    except Exception:
        return False
    completions = _complete_with_index(index, context)
    return _finish_native_completion(
        completions,
        output_stream=output_stream,
        exit_method=exit_method,
    )


def _modal_route_model(modal: Any):
    """Build only the static metadata needed to route a ModalCLI invocation.

    Unlike :func:`_modal_static_model`, this deliberately does *not* compile
    every leaf Config's option schema.  Routing only needs the command tree.
    ``_update_metadata`` is still used so command/alias/main semantics and the
    parser-stage Config materialization remain identical to the canonical
    ModalCLI path, but parser/help metadata stays lazy.
    """
    from kwconf import _rust

    option_specs = []
    command_specs = []
    leaf_by_path = {}

    def fuzzy_names(name, aliases, enabled):
        names = [name] + list(aliases or [])
        if enabled:
            for item in list(names):
                fuzzy = item.replace('_', '-')
                if fuzzy not in names:
                    names.append(fuzzy)
        shell_special = set("\\();<>|&!`$*?[]{} \t\n\r\"':")
        if any(any(ch in shell_special for ch in item) for item in names):
            raise _rust.UnsupportedSchema(
                'shell-sensitive modal command spelling requires argcomplete'
            )
        return names[0], [item for item in names[1:] if item != names[0]]

    def walk(
        current,
        path: tuple[str, ...],
        inherited_fuzzy=None,
        inherited_short_clusters=None,
    ):
        own_fuzzy = bool(getattr(current, '__fuzzy_hyphens__', 1))
        fuzzy = own_fuzzy if (inherited_fuzzy is None or inherited_fuzzy) else False
        own_short = bool(getattr(current, '__short_alias_clusters__', True))
        short_clusters = (
            own_short
            if inherited_short_clusters is None or inherited_short_clusters
            else False
        )
        if getattr(current, 'version', None) is not None:
            option_specs.append(
                (list(path), ['--version'], False, [], 'show version number and exit')
            )
        option_specs.append(
            (list(path), ['-h', '--help'], False, [], 'show this help message and exit')
        )
        for metadata in current._subconfig_metadata:
            current._update_metadata(metadata, with_parserkw=False)
            if metadata.get('is_opaque'):
                raise _rust.UnsupportedSchema(
                    'opaque modal command requires canonical argcomplete/argparse'
                )
            command, aliases = fuzzy_names(
                metadata['command'], metadata.get('alias') or [], fuzzy
            )
            # Bash candidate-only completion and routing do not consume help
            # descriptions. Keep the shared Rust command index compact here;
            # descriptive shell protocols delegate to argcomplete before this
            # model is built.
            command_specs.append((list(path), command, aliases, ''))
            next_path = path + (command,)
            if metadata.get('is_modal'):
                walk(
                    metadata['subconfig'],
                    next_path,
                    inherited_fuzzy=fuzzy,
                    inherited_short_clusters=short_clusters,
                )
            else:
                child = metadata['subconfig']
                child_own_fuzzy = bool(getattr(child, '__fuzzy_hyphens__', 1))
                child_effective_fuzzy = child_own_fuzzy if fuzzy else False
                child_own_short = bool(
                    getattr(child, '__short_alias_clusters__', True)
                )
                child_effective_short = child_own_short if short_clusters else False
                leaf_by_path[next_path] = {
                    'metadata': metadata,
                    'effective_fuzzy': child_effective_fuzzy,
                    'effective_short_clusters': child_effective_short,
                }

    walk(modal, ())
    return option_specs, command_specs, leaf_by_path


def _modal_static_model(modal: Any):
    """Build the complete static modal model for compatibility/debugging.

    The hot routing and ordinary command-name completion paths use the lighter
    :func:`_modal_route_model`. This full model remains available for callers
    that need every leaf option at once.
    """
    from kwconf import _rust

    option_specs, command_specs, leaf_by_path = _modal_route_model(modal)
    for path, leaf_info in leaf_by_path.items():
        child = leaf_info['metadata']['subconfig']
        # A Modal leaf with SubConfig selectors can change its own option
        # grammar after the command has already been routed. The complete model
        # cannot represent all selector-dependent grammars simultaneously.
        if _rust.completion_selector_spellings(child):
            raise _rust.UnsupportedSchema(
                'modal leaf with SubConfig selectors requires canonical argcomplete'
            )
        child_options = _rust.completion_specs_for_config(
            child,
            special_options=False,
            fuzzy_hyphens=leaf_info['effective_fuzzy'],
        )
        for _, spellings, takes_value, choices, field_help in child_options:
            option_specs.append(
                (list(path), spellings, takes_value, choices, field_help)
            )
        option_specs.append(
            (
                list(path),
                ['-h', '--help'],
                False,
                [],
                'show this help message and exit',
            )
        )
    return option_specs, command_specs, leaf_by_path


def _modal_completion_specs(modal: Any):
    option_specs, command_specs, _ = _modal_static_model(modal)
    return option_specs, command_specs


def _route_modal_context(command_specs, argv_before):
    """Resolve completed command tokens to a canonical modal path in Python.

    This only guides which *single* leaf option schema must be compiled for
    completion. Rust still owns the actual candidate matching/output.
    """
    choices = {}
    for path, command, aliases, _help in command_specs:
        table = choices.setdefault(tuple(path), {})
        table[command] = command
        for alias in aliases:
            table[alias] = command

    path = ()
    consumed = 0
    for token in argv_before:
        if token.startswith('-'):
            break
        canonical = choices.get(path, {}).get(token)
        if canonical is None:
            break
        path = path + (canonical,)
        consumed += 1
    return path, consumed


def _modal_completion_specs_for_context(modal: Any, context):
    """Build modal completion metadata, compiling at most one leaf schema."""
    from kwconf import _rust

    option_specs, command_specs, leaf_by_path = _modal_route_model(modal)
    argv_before, _prefix = context
    path, consumed = _route_modal_context(command_specs, argv_before)
    leaf_info = leaf_by_path.get(path)
    if leaf_info is None:
        return option_specs, command_specs

    child = leaf_info['metadata']['subconfig']
    leaf_argv = argv_before[consumed:]
    selectors = set(_rust.completion_selector_spellings(child))
    if selectors and any(
        token in selectors
        or any(token.startswith(spelling + '=') for spelling in selectors)
        for token in leaf_argv
    ):
        return None

    child_options = _rust.completion_specs_for_config(
        child,
        special_options=False,
        fuzzy_hyphens=leaf_info['effective_fuzzy'],
    )
    for _, spellings, takes_value, choices, field_help in child_options:
        option_specs.append(
            (list(path), spellings, takes_value, choices, field_help)
        )
    option_specs.append(
        (
            list(path),
            ['-h', '--help'],
            False,
            [],
            'show this help message and exit',
        )
    )
    return option_specs, command_specs


def try_modal_argcomplete(
    modal: Any,
    *,
    autocomplete: bool | str = 'auto',
    output_stream=None,
    exit_method=None,
) -> bool:
    """Fast static completion for ModalCLI command trees."""
    if not _active_argcomplete(autocomplete):
        return False
    # Descriptive completion protocols ask argparse's formatter to expand help
    # (including default-value text and formatter-specific styling). Preserve
    # byte parity by delegating those richer display modes to argcomplete; the
    # native path targets the ordinary candidate-only TAB protocol.
    if not _native_protocol_safe():
        return False
    backend = os.environ.get(
        'KWCONF_CLI_BACKEND', getattr(modal, '__cli_backend__', 'auto')
    ).lower()
    if backend == 'python':
        return False
    if backend not in {'auto', 'rust'}:
        return False
    context = _simple_completion_context()
    if context is None:
        return False
    try:
        from kwconf import _rust

        specs = _modal_completion_specs_for_context(modal, context)
        if specs is None:
            return False
        option_specs, command_specs = specs
        index = _rust.make_completion_index(option_specs, command_specs)
    except Exception:
        return False
    completions = _complete_with_index(index, context)
    return _finish_native_completion(
        completions,
        output_stream=output_stream,
        exit_method=exit_method,
    )


def debug_completion_context() -> dict[str, Any]:
    """Return completion protocol diagnostics for evidence bundles."""
    return {
        'active': '_ARGCOMPLETE' in os.environ,
        'context': _simple_completion_context(),
        'shell': os.environ.get('_ARGCOMPLETE_SHELL'),
        'ifs': os.environ.get('_ARGCOMPLETE_IFS', '\013'),
        'dfs': os.environ.get('_ARGCOMPLETE_DFS'),
        'python': sys.executable,
    }
