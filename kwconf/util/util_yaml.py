"""
Lazy import of the optional PyYAML dependency.

YAML file/string load, ``dump``/``dumps`` in yaml mode (the default), and the
``'yaml'`` parser all require PyYAML. It is an optional dependency, so import it
through here to get a consistent, actionable error when it is missing.
"""
from __future__ import annotations

from typing import Any


def import_yaml(feature: str = 'YAML support') -> Any:
    """
    Import ``yaml``, raising an actionable error if PyYAML is not installed.
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            f'{feature} requires the optional PyYAML dependency. '
            f'Install it with `pip install kwconf[yaml]`.'
        ) from exc
    return yaml
