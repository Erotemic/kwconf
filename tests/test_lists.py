def test_typed_list_cli_with_nargs():
    import kwconf as kw

    class ExampleConfig(kw.Config):
        tags: list = kw.Value(default_factory=list, nargs='*', type=list)

    cfg = ExampleConfig.cli(argv=['--tags', 'spam', 'eggs'])
    assert cfg.tags == ['spam', 'eggs']


def test_legacy_comma_split_is_opt_in():
    import kwconf as kw

    class ExampleConfig(kw.Config):
        legacy_items = kw.Value([], type='smartcast:legacy')
        plain_text: str = ''

    cfg = ExampleConfig.cli(argv=['--legacy_items=spam,eggs', '--plain_text=spam,eggs'])
    assert cfg.legacy_items == ['spam', 'eggs']
    assert cfg.plain_text == 'spam,eggs'
