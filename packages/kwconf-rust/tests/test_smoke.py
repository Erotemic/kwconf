def test_accelerator_import_and_protocol():
    import _kwconf_rust
    import kwconf

    name, version = _kwconf_rust.backend_info()
    assert name
    assert version
    assert kwconf._rust.extension_available()
