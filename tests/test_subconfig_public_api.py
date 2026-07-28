from typing import Any

import kwconf.subconfig as subconfig_mod


def test_subconfig_module_public_surface():
    assert subconfig_mod.__all__ == ['SubConfig']

    namespace: dict[str, Any] = {}
    exec('from kwconf.subconfig import *', namespace)
    exported = {key for key in namespace if not key.startswith('_')}
    assert exported == {'SubConfig'}


def test_internal_helpers_remain_explicitly_importable():
    # ``__all__`` defines the supported wildcard/public surface; it does not
    # prevent kwconf internals or advanced callers from using explicit imports.
    from kwconf.subconfig import apply_dot_updates, expand_multipass_parser

    assert callable(apply_dot_updates)
    assert callable(expand_multipass_parser)
