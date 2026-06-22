"""Tests for the named ingestion constructors: from_cli / from_env / from_yaml."""

import kwconf


class Cfg(kwconf.Config):
    __default__ = {
        'num': kwconf.Value(0, type=int),
        'name': kwconf.Value('x'),
    }


def test_from_cli():
    cfg = Cfg.from_cli(argv=['--num=4', '--name', 'foo'])
    assert cfg['num'] == 4 and cfg['name'] == 'foo'


def test_from_cli_no_argv_uses_defaults():
    cfg = Cfg.from_cli(argv=False)
    assert cfg['num'] == 0 and cfg['name'] == 'x'


def test_from_env_parses_string_values(monkeypatch):
    monkeypatch.setenv('MYAPP_NUM', '7')
    monkeypatch.setenv('MYAPP_NAME', 'hello')
    monkeypatch.setenv('OTHER_NUM', 'ignored')
    cfg = Cfg.from_env(prefix='MYAPP_')
    assert cfg['num'] == 7  # coerced via the field's int parser
    assert cfg['name'] == 'hello'


def test_from_env_kwargs_override(monkeypatch):
    monkeypatch.setenv('MYAPP_NUM', '7')
    cfg = Cfg.from_env(prefix='MYAPP_', num=99)
    assert cfg['num'] == 99  # real Python value, passed through


def test_from_yaml(tmp_path):
    import pytest

    pytest.importorskip('yaml')
    import yaml

    p = tmp_path / 'cfg.yaml'
    p.write_text(yaml.safe_dump({'num': 5, 'name': 'fromfile'}))
    cfg = Cfg.from_yaml(str(p))
    assert cfg['num'] == 5 and cfg['name'] == 'fromfile'


def test_from_yaml_respects_file_typing(tmp_path):
    import pytest

    pytest.importorskip('yaml')
    p = tmp_path / 'cfg.yaml'
    # A quoted scalar stays a string -- the file format's own typing wins.
    p.write_text('name: "123"\n')
    cfg = Cfg.from_yaml(str(p))
    assert cfg['name'] == '123'


def test_from_cli_union_field_is_auto_gated():
    """CLI parsing of a union-annotated field now honors the union (consistent
    with Config.coerce), instead of using only the first runtime type."""

    class C(kwconf.Config):
        x: 'str | int | None' = None

    assert C.from_cli(argv=['--x=123'])['x'] == 123
    assert type(C.from_cli(argv=['--x=123'])['x']) is int
    assert C.from_cli(argv=['--x=foo'])['x'] == 'foo'


def test_from_cli_str_annotation_pins_string():
    class C(kwconf.Config):
        name: str = 'd'

    assert C.from_cli(argv=['--name=123'])['name'] == '123'


def test_from_cli_nargs_coerces_elements():
    """nargs fields coerce each token as the container's element type."""

    class C(kwconf.Config):
        nums: 'list[int]' = kwconf.Value(None, nargs='+')

    assert C.from_cli(argv=['--nums', '1', '2', '3'])['nums'] == [1, 2, 3]


def test_from_cli_nargs_bare_list_keeps_strings():
    class C(kwconf.Config):
        words: list = kwconf.Value(None, nargs='+')

    assert C.from_cli(argv=['--words', 'a', 'b'])['words'] == ['a', 'b']
