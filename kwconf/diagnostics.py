"""
Global state initialized at import time.
Used for hidden arguments and diagnostic developer features.
"""
import os


def _boolean_environ(key: str) -> bool:
    """
    Args:
        key (str)

    Returns:
        bool
    """
    value: str = os.environ.get(key, '').lower()
    TRUTHY_ENVIRONS: set[str] = {'true', 'on', 'yes', '1'}
    return value in TRUTHY_ENVIRONS


DEBUG = _boolean_environ('KWCONF_DEBUG')

DEBUG_CONFIG = DEBUG or _boolean_environ('KWCONF_DEBUG_CONFIG')
DEBUG_DATA_CONFIG = DEBUG or _boolean_environ('KWCONF_DEBUG_DATA_CONFIG')
DEBUG_META_CONFIG = DEBUG or _boolean_environ('KWCONF_DEBUG_META_CONFIG')
DEBUG_META_DATA_CONFIG = DEBUG or _boolean_environ('KWCONF_DEBUG_META_DATA_CONFIG')
DEBUG_MODAL = DEBUG or _boolean_environ('KWCONF_DEBUG_MODAL')


if DEBUG:
    print("KWCONF INITIALIZED WITH GENERAL DIAGNOSTIC DEBUGGING")
