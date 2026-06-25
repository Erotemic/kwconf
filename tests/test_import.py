def test_import():
    import kwconf

    assert hasattr(kwconf, 'Config')
    assert not hasattr(kwconf, 'DataConfig')


def test_dataconfig_module_does_not_reexport_dataconfig():
    import kwconf.dataconfig as dataconfig

    assert hasattr(dataconfig, 'Config')
    assert not hasattr(dataconfig, 'DataConfig')
