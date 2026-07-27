# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
import os
import typing

import ubelt as ub

import kwconf


def mark_requires_yaml():
    try:
        import yaml  # NOQA
    except ImportError:
        import pytest

        pytest.skip('requires yaml')


def test_json_dump():
    import json

    dpath = ub.Path.appdir('kwconf', 'tests', 'test_file_config').ensuredir()

    class MyConfig(kwconf.Config):
        option1: typing.Any = 'a'
        option2: str = 'b'
        option3: str = 'c'

    config = MyConfig(option1=2, option2='foobar')
    fpath = dpath / 'test_dump_config.json'
    with open(fpath, 'w') as file:
        config.dump(file, mode='json')
    recon = json.loads(fpath.read_text())
    assert recon == dict(config)


def test_yaml_dump():
    mark_requires_yaml()
    dpath = ub.Path.appdir('kwconf', 'tests', 'test_file_config').ensuredir()

    class MyConfig(kwconf.Config):
        option1: typing.Any = 'a'
        option2: str = 'b'
        option3: str = 'c'

    config = MyConfig(option1=2, option2='foobar')
    fpath = dpath / 'test_dump_config.yaml'
    with open(fpath, 'w') as file:
        config.dump(file, mode='yaml')
    print(fpath.read_text())
    assert fpath.read_text() == 'option1: 2\noption2: foobar\noption3: c\n'


def test_yaml_load():
    mark_requires_yaml()
    dpath = ub.Path.appdir('kwconf', 'tests', 'test_file_config').ensuredir()

    class MyConfig(kwconf.Config):
        option1: typing.Any = 'a'
        option2: str = 'b'
        option3: str = 'c'

    config = MyConfig(option1=3, option2='baz')
    fpath = dpath / 'test_load_config.yaml'
    with open(fpath, 'w') as file:
        config.dump(file, mode='yaml')

    config2 = MyConfig()
    # Test works with string
    config2.load(data=os.fspath(fpath))
    assert dict(config2) == dict(config)

    config2 = MyConfig()
    # Test works with pathlib
    config2.load(data=fpath)
    assert dict(config2) == dict(config)


def test_json_load():
    dpath = ub.Path.appdir('kwconf', 'tests', 'test_file_config').ensuredir()

    class MyConfig(kwconf.Config):
        option1: typing.Any = 'a'
        option2: str = 'b'
        option3: str = 'c'

    config = MyConfig(option1=3, option2='baz')
    fpath = dpath / 'test_load_config.json'
    with open(fpath, 'w') as file:
        config.dump(file, mode='json')

    config2 = MyConfig()
    # Test works with string
    config2.load(data=os.fspath(fpath))
    assert dict(config2) == dict(config)

    config2 = MyConfig()
    # Test works with pathlib
    config2.load(data=fpath)
    assert dict(config2) == dict(config)


def test_load_from_open_file_object():
    # load() accepts an already-open readable file object; the loader must NOT
    # close a caller-supplied stream (open_text_input only closes paths it
    # opened itself). This branch was previously untested.
    dpath = ub.Path.appdir('kwconf', 'tests', 'test_file_config').ensuredir()

    class MyConfig(kwconf.Config):
        option1: typing.Any = 'a'
        option2: str = 'b'

    config = MyConfig(option1=3, option2='baz')
    fpath = dpath / 'test_load_fileobj.json'
    with open(fpath, 'w') as file:
        config.dump(file, mode='json')

    config2 = MyConfig()
    with open(fpath, 'r') as file:
        config2.load(data=file, mode='json')
        # The caller still owns the stream and it remains open.
        assert not file.closed
    assert dict(config2) == dict(config)


def test_open_text_input_rejects_bad_input():
    import pytest

    from kwconf.util.util_fileio import open_text_input

    with pytest.raises(ValueError):
        with open_text_input('/this/path/does/not/exist.yaml', 'r'):
            pass
    with pytest.raises(TypeError):
        with open_text_input(12345, 'r'):  # not a path or readable file
            pass


def test_config_dumps_load_cli():
    mark_requires_yaml()
    dpath = ub.Path.appdir('kwconf', 'tests', 'test_file_config').ensuredir()

    class MyConfig(kwconf.Config):
        option1: typing.Any = 'a'
        option2: str = 'b'
        option3: str = 'c'

    fpath = dpath / 'test_dump_load_config.json'
    fpath.delete()
    assert not fpath.exists()
    config = MyConfig(option1=3, option2='baz')
    try:
        MyConfig.cli(
            argv=['--option1=dumped', '--dump', os.fspath(fpath)],
            special_options=True,
        )
    except SystemExit:
        assert fpath.exists()

    config = MyConfig.cli(
        argv=['--config', os.fspath(fpath)], special_options=True
    )
    assert config['option1'] == 'dumped'


def test_config_load_from_json_text():
    """
    Check that the config can load from raw text on the command line
    """

    class MyConfig(kwconf.Config):
        option1: typing.Any = 'a'
        option2: str = 'b'
        option3: str = 'c'

    config = MyConfig(option1=3, option2='baz')
    config2 = MyConfig.cli(
        argv=['--config', config.dumps(mode='json')], special_options=True
    )
    assert dict(config2) == dict(config)


def test_config_load_from_yaml_text():
    """
    Check that the config can load from raw text on the command line
    """
    mark_requires_yaml()

    class MyConfig(kwconf.Config):
        option1: typing.Any = 'a'
        option2: str = 'b'
        option3: str = 'c'

    config = MyConfig(option1=3, option2='baz')
    config2 = MyConfig.cli(
        argv=['--config', config.dumps(mode='yaml')], special_options=True
    )
    assert dict(config2) == dict(config)


def test_missing_config_path_raises_file_not_found():
    """A mistyped config path must raise FileNotFoundError, not be parsed as
    inline YAML content."""
    import pytest

    class C(kwconf.Config):
        a = kwconf.Value(0)

    for bad in ['no_such_file.yaml', os.path.join('missing', 'cfg.json')]:
        with pytest.raises(FileNotFoundError):
            C.cli(data=bad, argv=False)


def test_inline_json_values_can_look_like_paths():
    import pytest

    class C(kwconf.Config):
        path = ''

    cfg = C.cli(data='{"path": "foo/bar"}', argv=False)
    assert cfg.path == 'foo/bar'

    with pytest.raises(TypeError):
        C.cli(data='["foo/bar"]', argv=False)


def test_inline_yaml_values_can_look_like_paths():
    mark_requires_yaml()

    class C(kwconf.Config):
        path = ''
        url = ''
        name = ''

    cfg = C.cli(
        data='path: foo/bar\nurl: https://example.com/api\nname: config.json',
        argv=False,
    )
    assert cfg.asdict() == {
        'path': 'foo/bar',
        'url': 'https://example.com/api',
        'name': 'config.json',
    }


def test_empty_config_file_is_no_overrides(tmp_path):
    mark_requires_yaml()

    class C(kwconf.Config):
        a = kwconf.Value(7)

    fpath = tmp_path / 'empty.yaml'
    fpath.write_text('')
    cfg = C.cli(data=str(fpath), argv=False)
    assert cfg['a'] == 7


def test_non_mapping_config_payload_raises(tmp_path):
    mark_requires_yaml()
    import pytest

    class C(kwconf.Config):
        a = kwconf.Value(0)

    fpath = tmp_path / 'scalar.yaml'
    fpath.write_text('just a bare string\n')
    with pytest.raises(TypeError, match='did not parse to a mapping'):
        C.cli(data=str(fpath), argv=False)
