"""Make examples import the in-tree kwconf package when run from a checkout."""

import json
import sys
from pathlib import Path

try:
    import yaml
except Exception:  # pragma: no cover - only used for friendly example output
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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
        child_types = sorted({json.dumps(_type_name(item), sort_keys=True) for item in value})
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


def print_resolved_config(config, label='RESOLVED CONFIG'):
    """Print resolved config values and the concrete Python types they became."""
    print(f'{label}:')
    text = config.dumps(mode='yaml').rstrip()
    print(text if text else '{}')
    print('RESOLVED TYPES:')
    print(_dump_text(_type_name(config)))
    return config
