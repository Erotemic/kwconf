"""
Argparse Extensions
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from gettext import gettext as _
from typing import (
    TYPE_CHECKING,
    Any,
    Iterable,
    List,
    Sequence,
    Tuple,
    cast,
)

_FALSY: set[str] = {'0', 'false', 'f', 'no', ''}
KWCONF_NORICH: bool = os.environ.get('KWCONF_NORICH', '').lower() not in _FALSY


def _infer_scalar(text: Any) -> Any:
    """
    Best-effort standalone scalar inference for flag-or-keyval actions.

    Kept self-contained on purpose: ``argparse_ext`` must not import from the
    rest of ``kwconf`` so it stays a small, portable layer (a parser built from
    it can run without kwconf). It is only used as the fallback when no
    argparse ``type`` is set; kwconf injects richer coercion via ``type=``.

    Tries int, float, complex, then ``true``/``false`` and ``none``/``null``,
    otherwise returns the original string.
    """
    if not isinstance(text, str):
        return text
    for caster in (int, float, complex):
        try:
            return caster(text)
        except (ValueError, TypeError):
            pass
    low = text.strip().lower()
    if low == 'true':
        return True
    if low == 'false':
        return False
    if low in {'none', 'null'}:
        return None
    return text


__docstubs__ = """
import argparse

_RawDescriptionHelpFormatter = argparse.RawDescriptionHelpFormatter
_ArgumentDefaultsHelpFormatter = argparse.ArgumentDefaultsHelpFormatter
"""

if TYPE_CHECKING:
    # The rich variants are drop-in replacements for these, so let the type
    # checkers reason about the stdlib formatters as real base classes rather
    # than about a variable that holds one of two classes.
    _RawDescriptionHelpFormatter = argparse.RawDescriptionHelpFormatter
    _ArgumentDefaultsHelpFormatter = argparse.ArgumentDefaultsHelpFormatter
else:
    try:
        if KWCONF_NORICH:
            raise ImportError
        import rich_argparse
    except ImportError:
        _RawDescriptionHelpFormatter = argparse.RawDescriptionHelpFormatter
        _ArgumentDefaultsHelpFormatter = argparse.ArgumentDefaultsHelpFormatter
    else:
        _RawDescriptionHelpFormatter = (
            rich_argparse.RawDescriptionRichHelpFormatter
        )
        _ArgumentDefaultsHelpFormatter = (
            rich_argparse.ArgumentDefaultsRichHelpFormatter
        )


_EXPLICIT_KEYS_ATTR = '__kwconf_explicit_keys__'


def mark_explicit(
    parser: argparse.ArgumentParser,
    namespace: argparse.Namespace,
    dest: str,
) -> None:
    """Record one explicit destination for the current parse.

    Extended parsers keep parse-local provenance on the parser that owns the
    action, which preserves child-command provenance without leaking a marker
    into the returned namespace.  The namespace marker remains as a fallback
    for kwconf actions installed on a plain ``argparse.ArgumentParser``.
    """
    parser_explicit = getattr(parser, '_kwconf_last_explicit_keys', None)
    if parser_explicit is None or isinstance(parser_explicit, frozenset):
        parser_explicit = set()
        setattr(parser, '_kwconf_last_explicit_keys', parser_explicit)
    parser_explicit.add(dest)

    explicit = getattr(namespace, _EXPLICIT_KEYS_ATTR, None)
    if explicit is None:
        explicit = set()
        setattr(namespace, _EXPLICIT_KEYS_ATTR, explicit)
    explicit.add(dest)


@dataclass(frozen=True)
class ParseResult:
    """
    Result of parsing command-line arguments with provenance metadata.

    ``namespace`` contains argparse's resolved values, including parser
    defaults. ``explicit_keys`` contains only canonical destinations that were
    supplied by the user for the selected parser. This lets kwconf keep
    resolved values separate from user intent.
    """

    namespace: argparse.Namespace
    unknown_args: List[str]
    parser: argparse.ArgumentParser
    selected_parser: argparse.ArgumentParser
    explicit_keys: frozenset[str]

    @property
    def values(self) -> dict[str, Any]:
        return vars(self.namespace)

    @property
    def explicit_values(self) -> dict[str, Any]:
        values = self.values
        return {key: values[key] for key in self.explicit_keys if key in values}


def parse_known_result(
    parser: argparse.ArgumentParser,
    args: Sequence[str] | None = None,
    namespace: argparse.Namespace | None = None,
) -> ParseResult:
    """
    Parse arguments and return resolved values plus provenance metadata.

    This works with any ``argparse.ArgumentParser``. Kwconf actions record
    provenance for the parser that owns each action, while a namespace marker
    provides compatibility for plain argparse parsers. Both are replaced or
    removed per parse, so parser reuse cannot leak explicit keys between
    invocations.
    """
    if args is None:
        args = sys.argv[1:]
    else:
        args = [os.fspath(a) if isinstance(a, os.PathLike) else a for a in args]
    _reset_parser_provenance(parser)
    # Bind the result to its own name: reusing ``namespace`` would widen it to
    # ``Namespace | None`` for the rest of the function.
    if namespace is None:
        parsed, unknown_args = parser.parse_known_args(args=args)
    else:
        parsed, unknown_args = parser.parse_known_args(
            args=args,
            namespace=namespace,
        )
    deepest = getattr(parser, '_deepest_subparser_for_argv', None)
    if deepest is None:
        selected_parser = parser
    else:
        selected_parser = deepest(args) or parser
    namespace_explicit = getattr(parsed, _EXPLICIT_KEYS_ATTR, None)
    if namespace_explicit is not None:
        # Plain argparse parsers do not expose a public way to recover the
        # selected child parser. Kwconf actions therefore leave a parse-local
        # namespace marker that correctly aggregates root and child actions.
        explicit_keys = frozenset(namespace_explicit)
    else:
        parser_explicit = getattr(
            selected_parser, '_kwconf_last_explicit_keys', None
        )
        explicit_keys = frozenset(parser_explicit or ())
    if hasattr(parsed, _EXPLICIT_KEYS_ATTR):
        delattr(parsed, _EXPLICIT_KEYS_ATTR)
    return ParseResult(
        namespace=parsed,
        unknown_args=unknown_args,
        parser=parser,
        selected_parser=selected_parser,
        explicit_keys=explicit_keys,
    )


def _reset_parser_provenance(parser: argparse.ArgumentParser) -> None:
    """Clear parse-local explicit-key state across a parser tree.

    Kwconf actions can be installed on either :class:`ExtendedArgumentParser`
    or a plain :class:`argparse.ArgumentParser`. Reset at this shared boundary
    so parser reuse has identical semantics in both cases, including selected
    subparsers.
    """
    stack = [parser]
    seen = set()
    while stack:
        current = stack.pop()
        current_id = id(current)
        if current_id in seen:
            continue
        seen.add(current_id)
        setattr(current, '_kwconf_last_explicit_keys', set())
        for action in getattr(current, '_actions', ()):
            choices = getattr(action, 'choices', None)
            if not isinstance(choices, dict):
                continue
            stack.extend(
                choice
                for choice in choices.values()
                if isinstance(choice, argparse.ArgumentParser)
            )


def parse_result(
    parser: argparse.ArgumentParser,
    args: Sequence[str] | None = None,
    namespace: argparse.Namespace | None = None,
) -> ParseResult:
    """
    Strict parse that returns resolved values plus provenance metadata.
    """
    result = parse_known_result(parser, args=args, namespace=namespace)
    if result.unknown_args:
        msg = 'unrecognized arguments: %s' % ' '.join(result.unknown_args)
        if getattr(parser, 'exit_on_error', True):
            result.selected_parser.error(msg)
        else:
            from argparse import ArgumentError

            raise ArgumentError(None, msg)
    return result


def _option_consumes_separate_value(
    parser: argparse.ArgumentParser, token: str
) -> bool:
    """
    Whether ``token`` names an option on ``parser`` that consumes a following
    separate-token value (e.g. ``--opt val``). Returns False for flags,
    ``--opt=val`` forms (the value is in the same token), unknown options, and
    the end-of-options separator. Used to skip past options when locating the
    positional subcommand token.
    """
    if '=' in token:
        return False
    for action in parser._actions:
        if token in action.option_strings:
            # nargs 0 (store_true / count / our flag actions) takes no value;
            # nargs='?' can appear alone; everything else expects a value.
            if action.nargs == 0 or action.nargs == '?':
                return False
            return True
    return False


class BooleanFlagOrKeyValAction(argparse.Action):
    """
    An action that allows you to specify a boolean via a flag as per usual
    or a key/value pair.

    This helps allow for a flexible specification of boolean values:

    .. code::

        --flag        > {'flag': True}
        --flag=1      > {'flag': True}
        --flag True   > {'flag': True}
        --flag True   > {'flag': True}
        --flag False  > {'flag': False}
        --flag 0      > {'flag': False}
        --no-flag     > {'flag': False}
        --no-flag=0   > {'flag': True}
        --no-flag=1   > {'flag': False}

    Example:
        >>> from kwconf.argparse_ext import *  # NOQA
        >>> import argparse
        >>> parser = argparse.ArgumentParser()
        >>> parser.add_argument('-f', '--flag', action=BooleanFlagOrKeyValAction)
        >>> print(parser.format_usage())
        >>> print(parser.format_help())
        >>> import shlex
        >>> # Map the CLI arg string to what value we would expect to get
        >>> variants = {
        >>>     # Case1: you either specify the flag, or you don't
        >>>     '': None,
        >>>     '--flag': True,
        >>>     '--no-flag': False,
        >>>     # Case1: You specify the flag as a key/value pair
        >>>     '--flag=0': False,
        >>>     '--flag=1': True,
        >>>     '--flag True': True,
        >>>     '--flag False': False,
        >>>     # Case1: You specify the negated flag as a key/value pair
        >>>     # (you probably shouldn't do this)
        >>>     '--no-flag 0': True,
        >>>     '--no-flag 1': False,
        >>>     '--no-flag=True': False,
        >>>     '--no-flag=False': True,
        >>> }
        >>> for args, want in variants.items():
        >>>     args = shlex.split(args)
        >>>     ns = parser.parse_known_args(args=args)[0].__dict__
        >>>     print(f'args={args} -> {ns}')
        >>>     assert ns['flag'] == want
    """

    def __init__(
        self,
        option_strings: Sequence[str],
        dest: str,
        default: Any = None,
        required: bool = False,
        help: str | None = None,
        type: type | None = None,
    ) -> None:

        _option_strings: list[str] = []
        for option_string in option_strings:
            _option_strings.append(option_string)
            if option_string.startswith('--'):
                option_string = '--no-' + option_string[2:]
                _option_strings.append(option_string)
        if (
            help is not None
            and default is not None
            and default is not argparse.SUPPRESS
        ):
            help += ' (default: %(default)s)'

        actionkw: dict[str, Any] = dict(
            option_strings=_option_strings,
            dest=dest,
            default=default,
            type=type,
            choices=None,
            required=required,
            help=help,
            metavar=None,
        )
        # Either the zero arg flag form or the 1 arg key/value form.
        actionkw['nargs'] = '?'

        # not sure if type is supported here. Hacking it in to fix
        # interaction of smartcast and isflag
        # self._hacked_in_type = type

        # Hack because of the Store Base for configargparse support
        argparse.Action.__init__(self, **actionkw)
        # super().__init__(**actionkw)

    def format_usage(self) -> str:
        # I thought this was used in formatting the help, but it seems like
        # we dont have much control over that here.
        if self.default is False:
            # If the default is false, don't show the negative variants
            _option_strings: list[str] = []
            for option_string in self.option_strings:
                if not option_string.startswith('--no'):
                    _option_strings.append(option_string)
        else:
            _option_strings = list(self.option_strings)
        return ' | '.join(_option_strings)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        """
        Args:
            parser (argparse.ArgumentParser): Parser instance.

            namespace (argparse.Namespace): Namespace to update.

            values (Any): Parsed value or `None` for bare flags.

            option_string (str | None):
                The option used (e.g. '--flag', '--no-flag').  This should
                always be a string in normal usage, but could be None
                in a positional argument. This lets us know if we are
                setting the value of the "negative" option or not. If
                not specified, we always assume the "positive" version.
        """
        key_is_negative: bool = False
        if option_string is None:
            raise TypeError(
                'Cannot use a BooleanFlagOrKeyValAction as a positional argument'
            )
        if option_string in self.option_strings:
            # Was the positive or negated key given?
            key_is_negative = option_string.startswith('--no-')
        else:
            raise TypeError(
                'Cannot use a BooleanFlagOrKeyValAction as a positional argument'
            )

        # Was there a value or was the flag specified by itself?
        if values is None:
            # Case where no value is given (treat as a flag)
            value: bool = not key_is_negative
        else:
            # Case where no value is given, parse it and use it.
            # Allow for non-boolean values (i.e. auto) to be passed
            if self.type is None:
                value = _infer_scalar(values)
            else:
                value = values
            if key_is_negative:
                value = not value
        setattr(namespace, self.dest, value)
        mark_explicit(parser, namespace, self.dest)


class CounterOrKeyValAction(BooleanFlagOrKeyValAction):
    """
    Extends :BooleanFlagOrKeyValAction: and will increment the value
    based on the number of times the flag is specified.

    Example:
        >>> from kwconf.argparse_ext import *  # NOQA
        >>> import argparse
        >>> parser = argparse.ArgumentParser()
        >>> parser.add_argument('-f', '--flag', action=CounterOrKeyValAction)
        >>> print(parser.format_usage())
        >>> print(parser.format_help())
        >>> import shlex
        >>> # Map the CLI arg string to what value we would expect to get
        >>> variants = {
        >>>     # Case1: you either specify the flag, or you don't
        >>>     '': None,
        >>>     '--flag': True,
        >>>     '--no-flag': False,
        >>>     # Case1: You specify the flag as a key/value pair
        >>>     '--flag=0': False,
        >>>     '--flag=1': True,
        >>>     '--flag True': True,
        >>>     '--flag False': False,
        >>>     # Case1: You specify the negated flag as a key/value pair
        >>>     # (you probably shouldn't do this)
        >>>     '--no-flag 0': True,
        >>>     '--no-flag 1': False,
        >>>     '--no-flag=True': False,
        >>>     '--no-flag=False': True,
        >>>     # Multiple flag specification cases
        >>>     '--flag --flag --flag': 3,
        >>>     # Short names can be combined with = (this is standard argparse behavior)
        >>>     '-f=5': 5,
        >>>     # Grouped short options should also count
        >>>     '-fff': 3,
        >>>     # Grouping with an explicit value overrides
        >>>     '-fff=5': 5,
        >>>     # An explicit set overwrites previous increments
        >>>     '--flag --flag --flag --flag=0': 0,
        >>>     # An increments modify previous explicit settings
        >>>     '--flag=3 --flag --flag --flag': 6,
        >>> }
        >>> for args, want in variants.items():
        >>>     args = shlex.split(args)
        >>>     ns = parser.parse_known_args(args=args)[0].__dict__
        >>>     print(f'args={args} -> {ns}')
        >>>     assert ns['flag'] == want
    """

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        if option_string is None:
            raise TypeError(
                'Cannot use a CounterFlagOrKeyValAction as a positional argument'
            )
        if option_string in self.option_strings:
            # Was the positive or negated key given?
            key_default: bool = not option_string.startswith('--no-')

        # ---------- handling for grouped short options ------------
        # Argparse allows ``-v=123`` just like ``--verbose=123``; when we
        # use ``nargs='?'`` this means ``-vvv`` is parsed as option ``-v``
        # with value ``'vv'``.  The code below detects that situation and
        # normalizes it into either (a) a pure increment or (b) an explicit
        # value.  We avoid doing any smartcasting here and instead modify
        # ``values`` so that the original logic later in the method will
        # handle casting/boolean inversion as usual.
        #
        # This only applies to a genuine short option (``-v``); for a long
        # option (``--flag``) the value is never a short-option concatenation,
        # and stripping the option's first letter would corrupt real values
        # (``--flag=false`` -> ``'alse'``).
        is_short_option = (
            len(option_string) == 2
            and option_string[0] == '-'
            and option_string[1] != '-'
        )
        if values is not None and isinstance(values, str) and is_short_option:
            short: str = option_string[1]
            rep: int = 0
            rest: str = values
            while rest and rest[0] == short:
                rep += 1
                rest = rest[1:]
            if rep > 0:
                # Grouping detected: ``-v`` + rep extra occurrences
                if not rest:
                    # ``-vvv`` with no explicit value: let the normal
                    # "no values" branch compute the increment by
                    # pretending ``values`` was None, but we must apply
                    # all of the increments at once.
                    prev_value = getattr(namespace, self.dest)
                    if prev_value is None:
                        prev_value = 0
                    setattr(namespace, self.dest, prev_value + rep + 1)
                    mark_explicit(parser, namespace, self.dest)
                    return
                # For explicit value forms we strip leading '=' if present
                if rest.startswith('='):
                    values = rest[1:]
                else:
                    values = rest
                # fall through to normal handling below with updated values
        # ---------------------------------------------------------------

        # Was there a value or was the flag specified by itself?
        if values is None:
            # For the no k/v case, allow incrementing of the value
            prev_value = getattr(namespace, self.dest)
            if prev_value is None:
                prev_value = 0
            value: int = prev_value + key_default
        else:
            # Allow for non-boolean values (i.e. auto) to be passed
            value = _infer_scalar(values)
            if not key_default:
                value = not value

        setattr(namespace, self.dest, value)
        mark_explicit(parser, namespace, self.dest)


class RawDescriptionDefaultsHelpFormatter(
    _RawDescriptionHelpFormatter,
    _ArgumentDefaultsHelpFormatter,
):
    group_name_formatter: type = str  # revert rich-argparse title change

    # Set these classvars to prevent rich_argparase from interpreting user data
    # as rich markup, and could lead to things like lists not being rendered.
    help_markup: bool = False
    text_markup: bool = False

    def _concise_option_strings(self, action):
        # When working with fuzzy hyphens only show one variant of each
        # possibility.
        display_option_strings: list[str] = []
        _seen: set[str] = set()
        for s in action.option_strings:
            _norm = s.replace('_', '-')
            if _norm not in _seen:
                _seen.add(_norm)
                display_option_strings.append(s)
        return display_option_strings

    def _format_action_invocation(self, action: argparse.Action) -> str:
        """
        Custom mixin to reduce clutter from accepting fuzzy hyphens
        """
        if not action.option_strings:
            default = self._get_default_metavar_for_positional(action)
            (metavar,) = self._metavar_formatter(action, default)(1)
            return metavar

        else:
            parts: list[str] = []

            SCFG_MODIFICATIONS: bool = True
            if SCFG_MODIFICATIONS:
                display_option_strings = self._concise_option_strings(action)
            else:
                display_option_strings = action.option_strings

            # if the Optional doesn't take a value, format is:
            #    -s, --long
            if action.nargs == 0:
                parts.extend(display_option_strings)

            # if the Optional takes a value, format is:
            #    -s ARGS, --long ARGS
            else:
                default = self._get_default_metavar_for_optional(action)
                args_string = self._format_args(action, default)
                for option_string in display_option_strings:
                    if SCFG_MODIFICATIONS:
                        if option_string.startswith('--no-'):
                            if (
                                isinstance(action.default, int)
                                and action.default == 0
                            ):
                                # Dont bother telling the user they can turn
                                # something off when that is the default.
                                continue
                            parts.append('%s' % (option_string,))
                        else:
                            parts.append('%s %s' % (option_string, args_string))
                    else:
                        parts.append('%s %s' % (option_string, args_string))
            return ', '.join(parts)

    def _rich_format_action_invocation(self, action: argparse.Action):
        """
        Mirrors _format_action_invocation but for rich-argparse
        """
        from rich.text import Text

        if not action.option_strings:
            return Text().append(
                self._format_action_invocation(action), style='argparse.args'
            )
        else:
            parts: list[Text] = []
            SCFG_MODIFICATIONS: bool = True
            if SCFG_MODIFICATIONS:
                display_option_strings = self._concise_option_strings(action)
            else:
                display_option_strings = action.option_strings

            # if the Optional doesn't take a value, format is:
            #    -s, --long
            if action.nargs == 0:
                parts.extend(
                    [Text(o, 'argparse.args') for o in display_option_strings]
                )

            # if the Optional takes a value, format is:
            #    -s ARGS, --long ARGS
            else:
                default = self._get_default_metavar_for_optional(action)
                args_string = self._format_args(action, default)
                for option_string in display_option_strings:
                    if option_string.startswith('--no-'):
                        if (
                            isinstance(action.default, int)
                            and action.default == 0
                        ):
                            # Dont bother telling the user they can turn
                            # something off when that is the default.
                            continue
                        part = Text(option_string, 'argparse.args')
                    else:
                        part = Text(' ').join(
                            [
                                Text(option_string, 'argparse.args'),
                                Text(args_string, 'argparse.metavar'),
                            ]
                        )
                    parts.append(part)
            return Text(', ').join(parts)


@lru_cache(maxsize=None)
def _stdlib_consumes_separator_before_subcommand() -> bool:
    """
    Whether the running argparse consumes an end-of-options separator that
    appears immediately before a subcommand.

    CPython learned to drop that ``--`` in 3.13 (and in later 3.12 patch
    releases); older supported interpreters hand it to the subparsers action
    as the command name, which fails with an "invalid choice" error.  Probing
    the real behavior keeps the backport in :class:`CompatArgumentParser`
    inert wherever the stdlib already does the right thing.
    """
    probe = argparse.ArgumentParser(
        prog='probe', add_help=False, exit_on_error=False
    )
    probe.add_subparsers().add_parser('cmd')
    try:
        probe.parse_known_args(['--', 'cmd'])
    except (argparse.ArgumentError, SystemExit):
        return False
    return True


class CompatArgumentParser(argparse.ArgumentParser):
    """Levels argparse behavior across the supported Python versions.

    Kwconf requires Python 3.10+, where ``exit_on_error`` is public, so the
    old vendored ``parse_known_args`` implementation is intentionally gone.
    What remains are two stdlib behaviors that only newer interpreters have,
    backported here so a kwconf parser answers the same way everywhere:

    * ``--`` immediately before a subcommand is consumed by argparse rather
      than passed to the subparsers action as the command name.
    * ``parse_args`` raises :class:`argparse.ArgumentError` for unrecognized
      arguments when ``exit_on_error`` is False, rather than exiting.
    """

    def parse_args(  # type: ignore[override]
        self,
        args: Iterable[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> argparse.Namespace:
        # Mirrors argparse's own parse_args, but honors exit_on_error for
        # unrecognized arguments the way newer interpreters do.
        parsed, extras = self.parse_known_args(args, namespace)
        assert parsed is not None
        if extras:
            msg = _('unrecognized arguments: %s') % ' '.join(extras)
            if self.exit_on_error:
                self.error(msg)
            else:
                raise argparse.ArgumentError(None, msg)
        return parsed

    def _get_values(
        self, action: argparse.Action, arg_strings: List[str]
    ) -> Any:
        # By the time argparse resolves values it has already decided which
        # tokens belong to the subcommand, so this is the one place where the
        # separator can be dropped without second-guessing that match.
        if (
            action.nargs == argparse.PARSER
            and arg_strings[:1] == ['--']
            and not _stdlib_consumes_separator_before_subcommand()
        ):
            arg_strings = arg_strings[1:]
        return super()._get_values(action, arg_strings)  # type: ignore


def _normalize_fuzzy_option_tokens(
    parser: argparse.ArgumentParser, args: Sequence[str]
) -> list[str]:
    """Normalize exact long-option underscore/hyphen variants.

    This is a narrow preprocessing layer around public ``parse_known_args``.
    It replaces the previous version-pinned copies of argparse's private
    ``_parse_optional`` / ``_get_option_tuples`` implementations.  The sole
    remaining private read is isolated to argparse's option registry because
    the stdlib does not expose a public option-enumeration API.
    """
    if not getattr(parser, '_kwconf_fuzzy_hyphens', True):
        return list(args)

    option_actions = getattr(parser, '_option_string_actions', {})
    normalized_to_options: dict[str, list[str]] | None = None

    result: list[str] = []
    after_separator = False
    for token in args:
        if after_separator:
            result.append(token)
            continue
        if token == '--':
            after_separator = True
            result.append(token)
            continue
        if not token.startswith('--'):
            result.append(token)
            continue

        option, sep, value = token.partition('=')
        if option in option_actions:
            result.append(token)
            continue
        if normalized_to_options is None:
            normalized_to_options = {}
            for known_option in option_actions:
                if known_option.startswith('--'):
                    normalized_to_options.setdefault(
                        known_option.replace('-', '_'), []
                    ).append(known_option)
        candidates = normalized_to_options.get(option.replace('-', '_'), [])
        if len(candidates) == 1:
            replacement = candidates[0]
            result.append(replacement + (sep + value if sep else ''))
        else:
            # Leave unknown or ambiguous spellings to argparse's normal error
            # and abbreviation handling.
            result.append(token)
    return result


class ExtendedArgumentParser(CompatArgumentParser):
    """
    Extends the compatible argument parser to add minor new features.
    Namely: allowing options in argv to interchangeably use "_" or "-".

    CommandLine:
        xdoctest -m kwconf.argparse_ext ExtendedArgumentParser

    Example:
        >>> # Demonstrate how the default ArgumentParser does not interchange
        >>> # underscores and dashes, but kwconf can.
        >>> # xdoctest: +REQUIRES(module:ubelt)
        >>> import argparse
        >>> import ubelt as ub
        >>> #parser = argparse.ArgumentParser(exit_on_error=False)
        >>> parser = CompatArgumentParser(exit_on_error=False)  # for 3.9-
        >>> parser.add_argument('--my_option1', default='default')
        >>> parser.add_argument('--my-option2', default='default')
        >>> #
        >>> # In vanilla argparse you have to use the option exactly
        >>> res1 = parser.parse_args(args=['--my_option1=foo-bar_baz']).__dict__
        >>> res2 = parser.parse_args(args=['--my-option2=foo-bar_baz']).__dict__
        >>> print(f'res1 = {ub.urepr(res1, nl=1)}')
        >>> print(f'res2 = {ub.urepr(res2, nl=1)}')
        >>> assert (res1 == {'my_option1': 'foo-bar_baz', 'my_option2': 'default'})
        >>> assert (res2 == {'my_option1': 'default', 'my_option2': 'foo-bar_baz'})
        >>> # You cannot swap "_" and "-" in argument names.
        >>> # (exit_on_error=False surfaces the usage error as an exception
        >>> # instead of a SystemExit)
        >>> import pytest
        >>> with pytest.raises(argparse.ArgumentError):
        >>>     parser.parse_args(args=['--my_option2=foo-bar_baz'])
        >>> with pytest.raises(argparse.ArgumentError):
        >>>     parser.parse_args(args=['--my-option1=foo-bar_baz'])
        >>> #
        >>> # With the ExtendedArgumentParser you can freely interchange underscores
        >>> # and dashes when specifying argv.
        >>> parser = ExtendedArgumentParser(exit_on_error=False)
        >>> parser.add_argument('--my_option1', default='default')
        >>> parser.add_argument('--my-option2', default='default')
        >>> # Original cases work
        >>> res3 = parser.parse_args(args=['--my_option1=foo-bar_baz']).__dict__
        >>> res4 = parser.parse_args(args=['--my-option2=foo-bar_baz']).__dict__
        >>> print(f'res3 = {ub.urepr(res3, nl=1)}')
        >>> print(f'res4 = {ub.urepr(res4, nl=1)}')
        >>> # Swapped "_" and "-" in the option name now works too
        >>> res5 = parser.parse_args(args=['--my-option1=foo-bar_baz']).__dict__
        >>> res6 = parser.parse_args(args=['--my_option2=foo-bar_baz']).__dict__
        >>> print(f'res5 = {ub.urepr(res5, nl=1)}')
        >>> print(f'res6 = {ub.urepr(res6, nl=1)}')
        >>> assert res3 == {'my_option1': 'foo-bar_baz', 'my_option2': 'default'}
        >>> assert res4 == {'my_option1': 'default', 'my_option2': 'foo-bar_baz'}
        >>> assert res5 == {'my_option1': 'foo-bar_baz', 'my_option2': 'default'}
        >>> assert res6 == {'my_option1': 'default', 'my_option2': 'foo-bar_baz'}

    Example:
        >>> # xdoctest: +REQUIRES(module:ubelt)
        >>> import argparse
        >>> import ubelt as ub
        >>> parser = ExtendedArgumentParser()
        >>> parser.add_argument('--my_option1', default='default')
        >>> parser.add_argument('--my-option2', default='default')
        >>> # General test cases
        >>> cases = [
        >>>     dict(args=['--my-option1', 'foo-bar_baz'], expected={'my_option1': 'foo-bar_baz', 'my_option2': 'default'}),
        >>>     dict(args=['--my_option1', 'foo-bar_baz'], expected={'my_option1': 'foo-bar_baz', 'my_option2': 'default'}),
        >>>     dict(args=['--my_option2', 'foo-bar_baz'], expected={'my_option1': 'default', 'my_option2': 'foo-bar_baz'}),
        >>>     dict(args=['--my-option2', 'foo-bar_baz'], expected={'my_option1': 'default', 'my_option2': 'foo-bar_baz'}),
        >>>     dict(args=['--my-option1=foo-bar_baz'], expected={'my_option1': 'foo-bar_baz', 'my_option2': 'default'}),
        >>>     dict(args=['--my_option1=foo-bar_baz'], expected={'my_option1': 'foo-bar_baz', 'my_option2': 'default'}),
        >>>     dict(args=['--my_option2=foo-bar_baz'], expected={'my_option1': 'default', 'my_option2': 'foo-bar_baz'}),
        >>>     dict(args=['--my-option2=foo-bar_baz'], expected={'my_option1': 'default', 'my_option2': 'foo-bar_baz'}),
        >>> ]
        >>> for case in cases:
        >>>     print(f'case = {ub.urepr(case, nl=1)}')
        >>>     result = parser.parse_args(args=case['args'])
        >>>     print(f'result = {ub.urepr(result, nl=1)}')
        >>>     assert result.__dict__ == case['expected']
    """

    def parse_known_args(  # type: ignore[override]
        self,
        args: Iterable[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> Tuple[argparse.Namespace, List[str]]:
        if args is None:
            args = sys.argv[1:]
        normalized = _normalize_fuzzy_option_tokens(self, list(args))
        # Replace, rather than accumulate, provenance on every parse.  Actions
        # owned by this parser populate the set; child parsers maintain their
        # own set so modal dispatch can read only the selected command's keys.
        setattr(self, '_kwconf_last_explicit_keys', set())
        parsed, unknown = super().parse_known_args(
            normalized, namespace=namespace
        )
        assert parsed is not None
        setattr(
            self,
            '_kwconf_last_explicit_keys',
            frozenset(getattr(self, '_kwconf_last_explicit_keys')),
        )
        if hasattr(parsed, _EXPLICIT_KEYS_ATTR):
            delattr(parsed, _EXPLICIT_KEYS_ATTR)
        return parsed, unknown

    def parse_known_result(
        self,
        args: Sequence[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> ParseResult:
        """
        Parse arguments and return resolved values plus provenance metadata.
        """
        return parse_known_result(self, args=args, namespace=namespace)

    def parse_result(
        self,
        args: Sequence[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> ParseResult:
        """
        Strict parse that returns resolved values plus provenance metadata.
        """
        return parse_result(self, args=args, namespace=namespace)

    # Public parse that applies the "print leaf help on error" policy.
    # (The ignore is for argparse's overloaded signature, which binds the
    # return type to the namespace the caller passes in.)
    def parse_args(  # type: ignore[override]
        self,
        args: Iterable[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> argparse.Namespace:
        # Materialize the tokens: they are walked a second time below to find
        # the subcommand whose usage should be shown.
        argv = sys.argv[1:] if args is None else list(args)
        # If the caller wants default behavior, defer entirely to argparse.
        if not self.exit_on_error:
            return super().parse_args(argv, namespace=namespace)

        # Otherwise, intercept errors to help for the appropriate submodal
        self.exit_on_error = False
        try:
            return super().parse_args(argv, namespace=namespace)
        except argparse.ArgumentError as ex:
            deepest = self._deepest_subparser_for_argv(argv)
            if deepest is None:
                deepest = self
            # deepest.print_usage()
            # str(ex) keeps the "argument --name:" prefix; ex.message drops
            # it, leaving the user guessing which option failed.
            deepest.error(str(ex))
        finally:
            # Restore the flag so a reused parser keeps the exit-on-error
            # policy on later parses (error() raising SystemExit included).
            self.exit_on_error = True
        # This code is unreachable because error() raises SystemExit
        return super().parse_args(argv, namespace=namespace)

    # Helper: find deepest subparser matched by tokens.
    def _deepest_subparser_for_argv(
        self, tokens: Sequence[str] | None = None
    ) -> argparse.ArgumentParser | None:
        if tokens is None:
            tokens = sys.argv[1:]
        parser: argparse.ArgumentParser = self
        i: int = 0
        deepest: argparse.ArgumentParser | None = None
        while True:
            sub_action: argparse._SubParsersAction | None = None
            for act in parser._actions:
                if isinstance(act, argparse._SubParsersAction):
                    sub_action = act
                    break
            if sub_action is None:
                break
            # Skip this parser's own options (and any separate-token values)
            # to reach the positional command token. Without this a leading
            # ``--opt`` before the command would break the walk and collapse
            # provenance to the root parser -- dropping every user-supplied
            # subcommand value.
            saw_separator = False
            while i < len(tokens):
                tok = tokens[i]
                if tok == '--':
                    saw_separator = True
                    i += 1
                    break
                if tok.startswith('-') and tok != '-':
                    i += 1
                    if _option_consumes_separate_value(parser, tok):
                        i += 1
                    continue
                break
            if (
                not saw_separator
                and i < len(tokens)
                and tokens[i].startswith('-')
            ):
                break
            if i < len(tokens) and tokens[i] in sub_action.choices:
                # A subparsers action maps every choice to a parser; argparse
                # types the mapping loosely because Action.choices is generic.
                parser = cast(
                    argparse.ArgumentParser, sub_action.choices[tokens[i]]
                )
                deepest = parser
                i += 1
            else:
                break
        return deepest
