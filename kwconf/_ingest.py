"""Shared input-boundary normalization for kwconf.

This module deliberately knows nothing about Config internals.  Both flat and
nested configuration loading use these helpers so path/string/stream and argv
semantics cannot drift between the two code paths.
"""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import Mapping
from typing import IO, Any, cast

from kwconf.util.util_fileio import looks_like_config_path, open_text_input
from kwconf.util.util_yaml import import_yaml


def coerce_mapping_source(data: Any, mode: str | None = None) -> dict[str, Any]:
    """Normalize a mapping, Config-like object, file, path, or inline text.

    Mapping inputs are copied because callers normalize aliases and may discard
    unknown keys.  Config-like inputs use ``asdict`` when available so nested
    Config values become ordinary mappings rather than leaking live objects.
    """
    if data is None:
        return {}
    if hasattr(data, 'asdict') and callable(data.asdict):
        parsed = data.asdict()
        return _validate_mapping_payload(parsed, data)
    if isinstance(data, Mapping):
        return dict(data)
    if isinstance(data, (str, os.PathLike)) or hasattr(data, 'readable'):
        if isinstance(data, str) and not os.path.exists(data):
            if looks_like_config_path(data):
                raise FileNotFoundError(f'config file does not exist: {data!r}')
            try:
                parsed = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                import io

                yaml = import_yaml('YAML parsing')
                parsed = yaml.load(io.StringIO(data), Loader=yaml.SafeLoader)
            return _validate_mapping_payload(parsed, data)

        if mode is None:
            if isinstance(data, (str, os.PathLike)) and os.fspath(
                data
            ).lower().endswith('.json'):
                mode = 'json'
            else:
                mode = 'yaml'
        with open_text_input(
            cast(str | os.PathLike | IO[Any], data), 'r'
        ) as file:
            if mode == 'yaml':
                yaml = import_yaml('YAML file loading')
                parsed = yaml.load(file, Loader=yaml.SafeLoader)
            elif mode == 'json':
                parsed = json.load(file)
            else:
                raise KeyError(mode)
        return _validate_mapping_payload(parsed, data)
    raise TypeError(f'Expected path, mapping, or Config; got {type(data)!r}')


def _validate_mapping_payload(parsed: Any, source: Any) -> dict[str, Any]:
    """Require a mapping payload; an empty document means no updates."""
    if parsed is None:
        return {}
    if isinstance(parsed, Mapping):
        return dict(parsed)
    raise TypeError(
        f'config source {source!r} did not parse to a mapping '
        f'(got {type(parsed).__name__})'
    )


def coerce_argv(argv: Any, *, expand_vars: bool = False) -> list[str]:
    """Normalize supported argv forms to a fresh list of strings."""
    if argv is False or argv is None:
        return []
    if argv is True:
        import sys

        return list(sys.argv[1:])
    if isinstance(argv, str):
        text = os.path.expandvars(argv) if expand_vars else argv
        return shlex.split(text)
    try:
        return [
            os.fspath(item) if isinstance(item, os.PathLike) else item
            for item in argv
        ]
    except TypeError as ex:
        raise TypeError(f'Unsupported argv={argv!r}') from ex
