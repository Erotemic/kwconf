def test_typed_list_cli_with_nargs():
    import kwconf as kw

    class ExampleConfig(kw.Config):
        tags: list = kw.Value(default_factory=list, nargs='*', type=list)

    cfg = ExampleConfig.cli(argv=['--tags', 'spam', 'eggs'])
    assert cfg.tags == ['spam', 'eggs']


def test_comma_strings_stay_strings():
    """
    kwconf intentionally drops scriptconfig's auto comma-splitting. A
    plain string field with a comma in its CLI value remains a single
    string regardless of where the comma appears.
    """
    import kwconf as kw

    class ExampleConfig(kw.Config):
        plain_text: str = ''
        untyped = kw.Value('default')

    cfg = ExampleConfig.cli(argv=['--plain_text=spam,eggs', '--untyped=foo,bar'])
    assert cfg.plain_text == 'spam,eggs'
    assert cfg.untyped == 'foo,bar'
