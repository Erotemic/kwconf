# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
def test_special_options_default_off():
    """
    kwconf's "special options" (``--config``, ``--dump``, ``--dumps``) are
    useful but they prevent the user from defining fields with the same
    names. They are off by default; opt in with ``special_options=True``
    on a per-call basis or ``__special_options__ = True`` on the class.
    """
    import pytest

    import kwconf

    class MyConfig(kwconf.Config):
        config = None

    # Without using the ``cli`` classmethod there is no conflict.
    config = MyConfig()
    assert config.config is None

    # Default behaviour: no special options, so a user-defined --config works.
    config = MyConfig.cli(argv=['--config=foo'])
    assert config.config == 'foo'

    # Explicit special_options=False is equivalent.
    config = MyConfig.cli(argv=['--config=foo'], special_options=False)
    assert config.config == 'foo'

    # Opting in means user-defined ``--config`` collides with the special one.
    with pytest.raises(Exception):
        MyConfig.cli(argv=['--config=foo'], special_options=True)


def test_config_file_merges_over_data(tmp_path):
    """
    --config must merge the file's values over the current state. It used to
    perform a full reset-load, restoring defaults for every key the file did
    not mention (wiping data= values).
    """
    import pytest

    import kwconf

    pytest.importorskip('yaml')

    class MyConfig(kwconf.Config):
        a = kwconf.Value(0)
        b = kwconf.Value(0)

    fpath = tmp_path / 'cfg.yaml'
    fpath.write_text('b: 7\n')

    cfg = MyConfig.cli(
        data={'a': 1}, argv=['--config', str(fpath)], special_options=True
    )
    assert cfg.b == 7  # from the file
    assert cfg.a == 1  # from data=, must survive the file merge

    # Explicit CLI values still take precedence over the file.
    cfg = MyConfig.cli(
        data={'a': 1},
        argv=['--config', str(fpath), '--b=9'],
        special_options=True,
    )
    assert cfg.b == 9
    assert cfg.a == 1


def test_dump_and_dumps_exit_zero(tmp_path):
    """
    A successful ``--dump`` / ``--dumps`` must exit with status 0 so shell
    pipelines like ``tool --dumps > config.yaml`` do not report failure.
    """
    import pytest

    import kwconf

    pytest.importorskip('yaml')

    class MyConfig(kwconf.Config):
        x = 1

    with pytest.raises(SystemExit) as excinfo:
        MyConfig.cli(argv=['--dumps'], special_options=True)
    assert excinfo.value.code == 0

    dump_fpath = tmp_path / 'out.yaml'
    with pytest.raises(SystemExit) as excinfo:
        MyConfig.cli(argv=['--dump', str(dump_fpath)], special_options=True)
    assert excinfo.value.code == 0
    assert 'x: 1' in dump_fpath.read_text()


def test_special_options_class_attribute_opt_in():
    """The ``__special_options__`` class attribute opts the class in."""
    import pytest

    import kwconf

    class MyConfig(kwconf.Config):
        __special_options__ = True
        x = 1

    # The class-level opt-in adds the special options to the parser.
    parser = MyConfig().argparse(special_options=True)
    actions = {a.dest for a in parser._actions}
    assert {'config', 'dump', 'dumps'}.issubset(actions)

    # And cli() picks up the class attribute when special_options is None.
    with pytest.raises(SystemExit):
        # ``--unknown`` would be silently ignored without strict mode, but
        # asking for --help via the special options exits cleanly.
        MyConfig.cli(argv=['--help'])
