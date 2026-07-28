"""Make examples import the in-tree kwconf package when run from a checkout."""

import json
import os
import sys
from pathlib import Path

try:
    import yaml
except Exception:  # pragma: no cover - only used for friendly example output
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _rich_console():
    """Return a Rich console when Rich is installed, otherwise ``None``."""
    try:
        from rich.console import Console
    except Exception:  # pragma: no cover - rich is optional for examples
        return None

    force_color = os.environ.get('KWCONF_FORCE_COLOR')
    force_terminal = None
    color_system = 'auto'
    no_color = None
    if force_color is not None:
        force_terminal = force_color.lower() not in {'0', 'false', 'no', 'off'}
        if force_terminal:
            color_system = 'standard'
            no_color = False
    return Console(
        force_terminal=force_terminal,
        color_system=color_system,
        no_color=no_color,
        highlight=False,
    )


def _wants_color():
    """Return true when the fallback printer should emit ANSI color."""
    force_color = os.environ.get('KWCONF_FORCE_COLOR')
    if force_color is not None:
        return force_color.lower() not in {'0', 'false', 'no', 'off'}
    return sys.stdout.isatty()


def _ansi(message, style):
    """Apply a small subset of Rich-like styles for fallback output."""
    if style is None or not _wants_color():
        return message
    color_codes = {
        'cyan': '36',
        'green': '32',
        'magenta': '35',
        'white': '37',
        'yellow': '33',
    }
    codes = []
    if 'bold' in style:
        codes.append('1')
    for name, code in color_codes.items():
        if name in style:
            codes.append(code)
            break
    if not codes:
        return message
    return f'\033[{";".join(codes)}m{message}\033[0m'


def _styled_line(parts):
    """Print styled line parts with Rich when available, ANSI otherwise."""
    console = _rich_console()
    if console is None:
        print(''.join(_ansi(text, style) for text, style in parts))
    else:
        from rich.text import Text

        line = Text()
        for text, style in parts:
            line.append(text, style=style)
        console.print(line)


def rich_print(message='', style=None):
    """Print ``message`` with Rich styles when available."""
    console = _rich_console()
    if console is None:
        print(_ansi(message, style))
    else:
        console.print(message, style=style)


def print_rule(title, style='bold cyan'):
    """Print a section title that is colored in capable terminals."""
    console = _rich_console()
    if console is None:
        print(_ansi(title, style))
        print(_ansi('-' * len(title), style))
    else:
        console.rule(title, style=style)


def _type_name(value):
    """Return a compact type description for a resolved config value."""
    import kwconf as kw

    if isinstance(value, kw.Config):
        data = value.asdict()
        summary = {'__class__': value.__class__.__name__}
        for key in data:
            summary[key] = _type_name(getattr(value, key))
        return summary
    if isinstance(value, dict):
        return {key: _type_name(val) for key, val in value.items()}
    if isinstance(value, list):
        if not value:
            return 'list'
        child_types = sorted(
            {json.dumps(_type_name(item), sort_keys=True) for item in value}
        )
        if len(child_types) == 1:
            child = json.loads(child_types[0])
        else:
            child = [json.loads(item) for item in child_types]
        return {'list_of': child}
    if isinstance(value, tuple):
        if not value:
            return 'tuple'
        child_types = [_type_name(item) for item in value]
        return {'tuple_of': child_types}
    return type(value).__name__


def _dump_text(data):
    """Dump example data in a stable, human-readable form."""
    if yaml is not None:
        return yaml.safe_dump(data, sort_keys=False).rstrip()
    return json.dumps(data, indent=2, sort_keys=False)


def _value_text(value):
    """Return a compact value representation for one config field."""
    import kwconf as kw

    if isinstance(value, kw.Config):
        return value.__class__.__name__
    return repr(value)


def _field_type_name(value):
    """Return a compact one-line type description for one config field."""
    import kwconf as kw

    if isinstance(value, kw.Config):
        return value.__class__.__name__
    if isinstance(value, list):
        if not value:
            return 'list'
        child_types = sorted({type(item).__name__ for item in value})
        if len(child_types) == 1:
            return f'list[{child_types[0]}]'
        return 'list[' + ' | '.join(child_types) + ']'
    if isinstance(value, tuple):
        if not value:
            return 'tuple'
        child_types = ', '.join(type(item).__name__ for item in value)
        return f'tuple[{child_types}]'
    if isinstance(value, dict):
        return 'dict'
    return type(value).__name__


def _iter_config_fields(config, prefix=''):
    """Yield resolved config fields as ``(name, value)`` pairs."""
    import kwconf as kw

    for key in config.asdict():
        value = getattr(config, key)
        name = f'{prefix}.{key}' if prefix else key
        if isinstance(value, kw.Config):
            yield name, value
            yield from _iter_config_fields(value, prefix=name)
        else:
            yield name, value


def print_resolved_config(config, label='RESOLVED CONFIG', explicit_only=False):
    """
    Print resolved config fields as name/type/value triples.

    Args:
        config (kwconf.Config): the config to print.
        label (str): heading printed above the fields.
        explicit_only (bool):
            if True, only show fields that were explicitly provided on the
            command line (as tracked by ``config._explicit_argv_keys``),
            rather than every resolved field including defaults.
    """
    rich_print(f'{label}:', style='bold green')
    explicit_keys = getattr(config, '_explicit_argv_keys', frozenset())
    for name, value in _iter_config_fields(config):
        if explicit_only and name not in explicit_keys:
            continue
        _styled_line(
            [
                (name, 'bold cyan'),
                (' : ', 'white'),
                (_field_type_name(value), 'bold magenta'),
                (' = ', 'white'),
                (_value_text(value), 'yellow'),
            ]
        )
    return config
