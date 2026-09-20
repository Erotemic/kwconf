"""Lazy integration with :func:`ubelt.urepr`.

The integration is intentionally *not* allowed to import ubelt while kwconf's
core classes are loading.  Importing all of ubelt is much more expensive than
loading Config/Value themselves and made every short-lived CLI pay for an
optional pretty-printing feature.

If ubelt was imported first, registration happens immediately and behaves as it
historically did.  If ubelt is imported after kwconf, the first ``ub.urepr``
call on a Config self-registers through the compatibility hook below.  Direct
``repr(config)`` keeps the normal NiceRepr spelling.
"""

from __future__ import annotations

import sys

_REGISTERED = False
_REGISTERING = False


def _register_ubelt_repr_extensions() -> bool:
    """Register kwconf's formatter, importing ubelt only on explicit demand.

    Returns:
        bool: True if a formatter is registered after this call.
    """
    global _REGISTERED, _REGISTERING
    if _REGISTERED:
        return True
    if _REGISTERING:
        return False

    try:
        import ubelt as ub
    except ImportError:
        return False

    _REGISTERING = True
    try:
        try:
            extensions = ub.util_repr._REPR_EXTENSIONS  # type: ignore[attr-defined]
        except AttributeError:
            extensions = ub.util_format._FORMATTER_EXTENSIONS  # type: ignore[attr-defined]

        # Register against the real base class, not the string ``"Config"``.
        # Ubelt's typename registry is global and a string registration would
        # accidentally capture unrelated third-party classes with that name.
        import kwconf

        @extensions.register(kwconf.Config)
        def _format_config_type(data, **kwargs):
            return _format_config(data, ub, **kwargs)

        _REGISTERED = True
    finally:
        _REGISTERING = False
    return _REGISTERED


def _format_config(data, ub, **kwargs):
    name = data.__class__.__name__
    body = ub.urepr(data._to_dict(), **kwargs)
    if isinstance(data, sys.modules['kwconf'].Config):
        return f'{name}(**{body})'
    return f'{name}({body})'


def _register_if_ubelt_loaded() -> bool:
    """Register without causing an ubelt import on the cold path."""
    if _REGISTERED:
        return True
    if 'ubelt' not in sys.modules:
        return False
    return _register_ubelt_repr_extensions()


def _late_urepr_fallback(data):
    """Preserve ``ub.urepr(Config)`` when ubelt is imported after kwconf.

    Ubelt checks its extension registry before falling back to ``repr(data)``.
    If kwconf was imported first, there was intentionally no reason to import
    ubelt just to populate that registry.  When this function is reached from
    ubelt's fallback formatter, ubelt is now definitely loaded, so registration
    is cheap.  Re-entering ``urepr`` with the original formatting kwargs gives
    the first call the same result as eager registration did.

    This compatibility shim is deliberately narrow: ordinary ``repr(config)``
    never looks like an ubelt call and therefore keeps NiceRepr behavior.
    """
    if _REGISTERED or 'ubelt' not in sys.modules:
        return None
    try:
        frame = sys._getframe(2)
    except (AttributeError, ValueError):  # pragma: nocover
        return None
    module_name = frame.f_globals.get('__name__')
    if module_name not in {'ubelt.util_repr', 'ubelt.util_format'}:
        return None
    if frame.f_code.co_name != '_format_object':
        return None
    if not _register_ubelt_repr_extensions():
        return None
    ub = sys.modules.get('ubelt')
    if ub is None:  # pragma: nocover
        return None
    kwargs = frame.f_locals.get('kwargs', {})
    return ub.urepr(data, **dict(kwargs))
