def test_import():
    import kwconf

    assert hasattr(kwconf, 'Config')
    assert not hasattr(kwconf, 'DataConfig')


def test_dataconfig_module_does_not_reexport_dataconfig():
    import kwconf.dataconfig as dataconfig

    assert hasattr(dataconfig, 'Config')
    assert not hasattr(dataconfig, 'DataConfig')


def test_public_api_exports():
    """__all__ names must exist, and the documented extension point
    register_parser must be reachable from the top level."""
    import kwconf

    for name in kwconf.__all__:
        assert hasattr(kwconf, name), name
    assert kwconf.register_parser is not None


def test_mkinit_submodules_spec_matches_reality():
    """
    The mkinit __submodules__ spec must reference real submodules and cover
    exactly the names hand-imported in __init__ (regenerating with mkinit -w
    must not change the public API).
    """
    import importlib

    import kwconf

    spec_names = set()
    for modname, names in kwconf.__submodules__.items():
        importlib.import_module(f'kwconf.{modname}')
        assert names is not None, (
            f'kwconf.{modname} must declare an explicit export list'
        )
        spec_names.update(names)
    assert spec_names == set(kwconf.__all__)
