from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

import kwconf


def _import_generated(text, tmp_path, module_name='generated_pydantic_port'):
    path = tmp_path / f'{module_name}.py'
    path.write_text(text)
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def test_port_to_pydantic_basic_source():
    class Demo(kwconf.Config):
        src = kwconf.Value(None, required=True, position=1, help='input path')
        count: int = kwconf.Value(
            3,
            alias=['num'],
            tags=['perf_param'],
            help='number of workers',
        )
        mode: str = kwconf.Value('fast', choices=['fast', 'slow'])

    text = Demo().port_to_pydantic()

    assert 'from pydantic import AliasChoices, BaseModel, Field' in text
    assert 'class Demo(BaseModel):' in text
    assert 'src: typing.Any = Field(' in text
    assert "description='input path'" in text
    assert "validation_alias=AliasChoices('count', 'num')" in text
    assert "json_schema_extra={'kwconf_tags': ['perf_param']}" in text
    assert 'choices=' in text
    assert 'REVIEW(kwconf-port)' in text
    compile(text, '<generated-pydantic-port>', 'exec')


def test_port_to_pydantic_executes_when_pydantic_available(tmp_path):
    pytest.importorskip('pydantic')

    class Child(kwconf.Config):
        depth: int = 1

    class Demo(kwconf.Config):
        src: str = kwconf.Value('', required=True)
        count: int = kwconf.Value(3, alias=['num'], tags=['perf_param'])
        child = kwconf.SubConfig(Child)

    text = Demo().port_to_pydantic()
    module = _import_generated(text, tmp_path)
    model = module.Demo(src='input.txt', num='4')

    assert model.src == 'input.txt'
    assert model.count == 4
    assert model.child.depth == 1
    schema = module.Demo.model_json_schema()
    assert schema['properties']['count']['kwconf_tags'] == ['perf_param']


def test_port_to_pydantic_uses_public_pathlib_annotation(tmp_path):
    pytest.importorskip('pydantic')

    class Demo(kwconf.Config):
        path: pathlib.Path = pathlib.Path('demo.txt')

    text = Demo().port_to_pydantic()
    assert 'pathlib._' not in text
    assert "path: pathlib.Path = pathlib.Path('demo.txt')" in text
    module = _import_generated(text, tmp_path, 'generated_path_port')
    assert module.Demo(path='other.txt').path == pathlib.Path('other.txt')


def test_port_to_pydantic_default_factory(tmp_path):
    pytest.importorskip('pydantic')

    class Demo(kwconf.Config):
        items: list[str] = kwconf.Value(default_factory=list)

    text = Demo().port_to_pydantic()
    assert 'default_factory=list' in text
    module = _import_generated(text, tmp_path, 'generated_factory_port')
    first = module.Demo()
    second = module.Demo()
    assert first.items == []
    assert first.items is not second.items


def test_port_to_pydantic_subconfig_review_notes():
    class ChildA(kwconf.Config):
        x: int = 1

    class ChildB(kwconf.Config):
        y: int = 2

    class Parent(kwconf.Config):
        child = kwconf.SubConfig(
            ChildA,
            choices={'a': ChildA, 'b': ChildB},
            allow_import=False,
        )

    text = Parent().port_to_pydantic()
    assert 'class ChildA(BaseModel):' in text
    assert 'class Parent(BaseModel):' in text
    assert 'child: ChildA = Field(default_factory=ChildA)' in text
    assert 'SubConfig choices/selectors were not translated' in text
    assert 'allow_import=False' in text


def test_port_to_pydantic_marks_cli_semantics_for_review():
    class Demo(kwconf.Config):
        values = kwconf.Value(
            [],
            parser='csv',
            nargs='+',
            short_alias=['v'],
            group='inputs',
        )
        verbose = kwconf.Value(0, isflag='counter')

    text = Demo().port_to_pydantic()
    assert "parser='csv'" in text
    assert "nargs='+'" in text
    assert "short_alias=['v']" in text
    assert "group='inputs'" in text
    assert "isflag='counter'" in text


def test_port_to_pydantic_does_not_require_pydantic_to_generate(monkeypatch):
    real_import = __import__

    def guarded_import(name, *args, **kwargs):
        if name == 'pydantic' or name.startswith('pydantic.'):
            raise AssertionError('kwconf imported pydantic while generating source')
        return real_import(name, *args, **kwargs)

    class Demo(kwconf.Config):
        x: int = 1

    monkeypatch.setattr('builtins.__import__', guarded_import)
    text = Demo().port_to_pydantic()
    assert 'from pydantic import BaseModel, Field' in text
