def test_explicit_type_beats_legacy_smartcast():
    import kwconf as kw

    class MyConfig(kw.Config):
        text: str = ''
        legacy = kw.Value(0, type='smartcast:legacy')

    cfg = MyConfig.cli(argv='--text=1,2,3 --legacy=1,2,3')
    assert cfg.text == '1,2,3'
    assert cfg.legacy == [1, 2, 3]


def test_isflag_respects_explicit_type():
    import kwconf as kw

    class MyConfig(kw.Config):
        param1 = kw.Value(0, type=str, isflag=True)
        param2 = kw.Value(0, type='smartcast:legacy', isflag=True)

    cfg = dict(MyConfig.cli(argv='--param1=1,2,3 --param2=1,2,3'))
    assert cfg == {
        'param1': '1,2,3',
        'param2': [1, 2, 3],
    }
