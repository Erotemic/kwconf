# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
def test_special_options_default_off():
    """
    kwconf's "special options" (``--config``, ``--dump``, ``--dumps``) are
    useful but they prevent the user from defining fields with the same
    names. They are off by default; opt in with ``special_options=True``
    on a per-call basis or ``__special_options__ = True`` on the class.
    """
    import kwconf
    import pytest

    class MyConfig(kwconf.DataConfig):
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


def test_special_options_class_attribute_opt_in():
    """The ``__special_options__`` class attribute opts the class in."""
    import kwconf
    import pytest

    class MyConfig(kwconf.DataConfig):
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
