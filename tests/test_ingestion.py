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
    assert cfg['num'] == 7          # coerced via the field's int parser
    assert cfg['name'] == 'hello'


def test_from_env_kwargs_override(monkeypatch):
    monkeypatch.setenv('MYAPP_NUM', '7')
    cfg = Cfg.from_env(prefix='MYAPP_', num=99)
    assert cfg['num'] == 99         # real Python value, passed through


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
