from __future__ import annotations

import io

import pytest

import kwconf


def test_nested_schema_description_flattens_realized_subconfig():
    from kwconf import _rust

    class Inner(kwconf.Config):
        count: int = 1
        mode = kwconf.Value('a', choices=['a', 'b'])

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(Inner)
        top: str = ''

    specs, compiled = _rust._schema_description(Outer())
    keys = [item[0] for item in specs]
    assert keys == ['inner.count', 'inner.mode', 'top']
    assert compiled.keys == tuple(keys)
    completion = _rust.completion_specs_for_config(Outer())
    spellings = {spelling for _, names, *_ in completion for spelling in names}
    assert '--inner.count' in spellings
    assert '--inner.mode' in spellings


def test_static_completion_protocol_uses_argcomplete_output_contract(monkeypatch):
    from kwconf import _completion
    from kwconf import _rust

    class FakeIndex:
        def complete(self, argv_before, prefix):
            assert argv_before == []
            assert prefix == '--mo'
            return [('--mode', 'run mode')]

    class C(kwconf.Config):
        mode = kwconf.Value('a', choices=['a', 'b'], help='run mode')

    monkeypatch.setattr(_rust, 'compile_completion_index', lambda *a, **kw: FakeIndex())
    monkeypatch.setenv('_ARGCOMPLETE', '1')
    monkeypatch.setenv('COMP_LINE', 'prog --mo')
    monkeypatch.setenv('COMP_POINT', str(len('prog --mo')))
    stream = io.StringIO()

    with pytest.raises(SystemExit) as ex:
        _completion.try_config_argcomplete(
            C(),
            autocomplete='auto',
            output_stream=stream,
            exit_method=lambda code: (_ for _ in ()).throw(SystemExit(code)),
        )
    assert ex.value.code == 0
    assert stream.getvalue() == '--mode '  # argcomplete appends a space to a unique simple match


def test_complex_shell_completion_falls_back(monkeypatch):
    from kwconf import _completion

    class C(kwconf.Config):
        value: str = ''

    monkeypatch.setenv('_ARGCOMPLETE', '1')
    monkeypatch.setenv('COMP_LINE', "prog --value='sp")
    monkeypatch.setenv('COMP_POINT', str(len("prog --value='sp")))
    assert _completion.try_config_argcomplete(C(), autocomplete='auto') is False


def test_modal_static_completion_specs_cover_commands_and_leaf_options():
    from kwconf import _completion

    class Root(kwconf.ModalCLI):
        class Train(kwconf.Config):
            __command__ = 'train'
            __alias__ = ['fit']
            lr: float = kwconf.Value(0.1, help='learning rate')

            @classmethod
            def main(cls, argv=False, **kwargs):
                return 0

    modal = Root()
    options, commands = _completion._modal_completion_specs(modal)
    assert any(path == [] and name == 'train' for path, name, *_ in commands)
    assert any(
        path == ['train'] and '--lr' in spellings
        for path, spellings, *_ in options
    )


def test_nested_modal_static_model_tracks_canonical_paths_and_leaf_options():
    from kwconf import _completion

    class Root(kwconf.ModalCLI):
        class DataOps(kwconf.ModalCLI):
            __command__ = 'data_ops'

            class TrainModel(kwconf.Config):
                __command__ = 'train_model'
                epochs: int = 1

                @classmethod
                def main(cls, argv=False, **kwargs):
                    return 0

    options, commands, leaves = _completion._modal_static_model(Root())
    assert any(
        path == [] and name == 'data_ops' and 'data-ops' in aliases
        for path, name, aliases, _ in commands
    )
    assert any(
        path == ['data_ops']
        and name == 'train_model'
        and 'train-model' in aliases
        for path, name, aliases, _ in commands
    )
    assert ('data_ops', 'train_model') in leaves
    assert any(
        path == ['data_ops', 'train_model'] and '--epochs' in spellings
        for path, spellings, *_ in options
    )


def test_completion_context_matches_argcomplete_program_offset(monkeypatch):
    from kwconf import _completion

    monkeypatch.setenv('_ARGCOMPLETE', '1')
    monkeypatch.setenv('COMP_LINE', 'prog --mode b')
    monkeypatch.setenv('COMP_POINT', str(len('prog --mode b')))
    assert _completion._simple_completion_context() == (['--mode'], 'b')

    monkeypatch.setenv('_ARGCOMPLETE', '2')
    monkeypatch.setenv('COMP_LINE', 'python script.py --mode b')
    monkeypatch.setenv('COMP_POINT', str(len('python script.py --mode b')))
    assert _completion._simple_completion_context() == (['--mode'], 'b')


def test_static_completion_declines_dynamic_value(monkeypatch):
    from kwconf import _completion
    from kwconf import _rust

    class FakeIndex:
        def complete(self, argv_before, prefix):
            assert argv_before == ['--path']
            assert prefix == ''
            return None

    class C(kwconf.Config):
        path: str = ''

    monkeypatch.setattr(_rust, 'compile_completion_index', lambda *a, **kw: FakeIndex())
    monkeypatch.setenv('_ARGCOMPLETE', '1')
    monkeypatch.setenv('COMP_LINE', 'prog --path ')
    monkeypatch.setenv('COMP_POINT', str(len('prog --path ')))
    assert _completion.try_config_argcomplete(C(), autocomplete='auto') is False


def test_modal_static_model_fuzzy_aliases_and_opaque_fallback():
    from kwconf import _completion
    from kwconf import _rust

    class Root(kwconf.ModalCLI):
        class TrainModel(kwconf.Config):
            __command__ = 'train_model'

            @classmethod
            def main(cls, argv=False, **kwargs):
                return 0

    _, commands, leaves = _completion._modal_static_model(Root())
    row = next(row for row in commands if row[1] == 'train_model')
    assert 'train-model' in row[2]
    assert ('train_model',) in leaves

    modal = kwconf.ModalCLI()
    modal.register(command='external', main=lambda: 0)(None)
    with pytest.raises(_rust.UnsupportedSchema):
        _completion._modal_static_model(modal)


def test_nested_rust_schema_is_not_class_cached(monkeypatch):
    from kwconf import _rust

    class FakeFlatParser:
        def __init__(self, specs):
            self.specs = specs

    class FakeExtension:
        FlatParser = FakeFlatParser

    class Inner(kwconf.Config):
        value: int = 1

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(Inner)

    _rust.clear_cache()
    monkeypatch.setattr(_rust, '_load_extension', lambda required=False: FakeExtension())
    _rust.compile_config(Outer())
    assert _rust._SCHEMA_CACHE_ATTR not in Outer.__dict__


def test_modal_rust_success_path_routes_without_argparse(monkeypatch):
    from kwconf import _modal_rust
    from kwconf import _rust

    seen = {}

    class Command(kwconf.Config):
        __command__ = 'do_work'
        value: int = 0

        @classmethod
        def main(cls, argv=None, **kwargs):
            seen['argv'] = argv
            seen['kwargs'] = kwargs
            return 7

    class Root(kwconf.ModalCLI):
        __subconfigs__ = [Command]

    class FakeIndex:
        def route(self, argv):
            assert argv == ['do-work', '--value=3']
            return (['do_work'], 1)

    class Probe:
        pass

    Probe.explicit_keys = ('value',)
    Probe.values = {'value': 3}

    monkeypatch.setattr(_rust, 'extension_available', lambda: True)
    monkeypatch.setattr(_rust, 'make_completion_index', lambda *a, **kw: FakeIndex())
    monkeypatch.setattr(_rust, 'try_parse_config', lambda *a, **kw: Probe())

    class Parsed(dict):
        _explicit_argv_keys = frozenset({'value'})

    monkeypatch.setattr(
        Command,
        'cli',
        classmethod(lambda cls, **kw: Parsed(value=3)),
    )
    result = _modal_rust.try_modal_main(
        Root(),
        ['do-work', '--value=3'],
        strict=True,
        autocomplete=False,
    )
    assert result == 7
    assert seen == {'argv': False, 'kwargs': {'value': 3}}


def test_modal_named_parameter_probe_matches_common_signatures():
    from kwconf import _modal_rust

    def positional(argv=None):
        return argv

    def keyword_only(*, argv=None):
        return argv

    def kwargs_only(**kwargs):
        return kwargs

    assert _modal_rust._has_named_parameter(positional, 'argv')
    assert _modal_rust._has_named_parameter(keyword_only, 'argv')
    assert not _modal_rust._has_named_parameter(kwargs_only, 'argv')


def test_python_backend_does_not_claim_native_completion(monkeypatch):
    from kwconf import _completion
    from kwconf import _rust

    class C(kwconf.Config):
        __cli_backend__ = 'python'
        mode = kwconf.Value('a', choices=['a', 'b'])

    monkeypatch.setenv('_ARGCOMPLETE', '1')
    monkeypatch.setenv('COMP_LINE', 'prog --mo')
    monkeypatch.setenv('COMP_POINT', str(len('prog --mo')))
    monkeypatch.setattr(
        _rust,
        'compile_completion_index',
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Rust should not run')),
    )
    assert _completion.try_config_argcomplete(C(), autocomplete='auto') is False


def test_shell_sensitive_choice_completion_delegates():
    from kwconf import _rust

    class C(kwconf.Config):
        value = kwconf.Value('plain', choices=['plain', 'has space'])

    with pytest.raises(_rust.UnsupportedSchema):
        _rust.completion_specs_for_config(C())


def test_static_completion_includes_flag_negation_and_aliases():
    from kwconf import _rust

    class C(kwconf.Config):
        enabled = kwconf.Value(False, isflag=True, alias=['active'], short_alias=['e'])

    specs = _rust.completion_specs_for_config(C())
    spellings = [spelling for _, names, *_ in specs for spelling in names]
    assert '--enabled' in spellings
    assert '--no-enabled' in spellings
    assert '--active' in spellings
    assert '--no-active' in spellings
    assert '-e' in spellings


def test_descriptive_completion_protocol_delegates(monkeypatch):
    from kwconf import _completion

    class C(kwconf.Config):
        mode = kwconf.Value('a', choices=['a', 'b'], help='run mode')

    monkeypatch.setenv('_ARGCOMPLETE', '1')
    monkeypatch.setenv('COMP_LINE', 'prog --mo')
    monkeypatch.setenv('COMP_POINT', str(len('prog --mo')))
    monkeypatch.setenv('_ARGCOMPLETE_SHELL', 'zsh')
    assert _completion.try_config_argcomplete(C(), autocomplete='auto') is False


@pytest.mark.parametrize('shell', ['zsh', 'fish', 'powershell'])
def test_non_bash_shell_protocols_delegate(monkeypatch, shell):
    from kwconf import _completion

    class C(kwconf.Config):
        mode = kwconf.Value('a', choices=['a', 'b'])

    monkeypatch.setenv('_ARGCOMPLETE', '1')
    monkeypatch.setenv('COMP_LINE', 'prog --mo')
    monkeypatch.setenv('COMP_POINT', str(len('prog --mo')))
    monkeypatch.setenv('_ARGCOMPLETE_SHELL', shell)
    assert _completion.try_config_argcomplete(C(), autocomplete='auto') is False


def test_invalid_argcomplete_separator_protocol_delegates(monkeypatch):
    from kwconf import _completion

    class C(kwconf.Config):
        mode = kwconf.Value('a', choices=['a', 'b'])

    monkeypatch.setenv('_ARGCOMPLETE', '1')
    monkeypatch.setenv('COMP_LINE', 'prog --mo')
    monkeypatch.setenv('COMP_POINT', str(len('prog --mo')))
    monkeypatch.setenv('_ARGCOMPLETE_IFS', 'too-long')
    assert _completion.try_config_argcomplete(C(), autocomplete='auto') is False


def test_argcomplete_suppress_space_parity(monkeypatch):
    from kwconf import _completion

    monkeypatch.setenv('_ARGCOMPLETE_SUPPRESS_SPACE', '1')
    got = _completion._argcomplete_quote_simple([('--mode', '')])
    assert got == [('--mode', '')]


def test_inline_equals_completion_delegates_to_argcomplete():
    from kwconf import _completion

    class FakeIndex:
        def complete(self, argv, prefix):
            raise AssertionError('shell word-break completion must delegate')

    assert _completion._complete_with_index(FakeIndex(), ([], '--mode=b')) is None


def test_double_dash_completion_delegates_to_argcomplete():
    from kwconf import _completion

    class FakeIndex:
        def complete(self, argv, prefix):
            raise AssertionError('post-separator completion must delegate')

    assert _completion._complete_with_index(FakeIndex(), (['--'], '--mo')) is None


def test_subconfig_completion_exposes_selector_names_but_delegates_after_use(monkeypatch):
    from kwconf import _completion
    from kwconf import _rust

    class Inner(kwconf.Config):
        depth: int = 1

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(Inner, choices={'inner': Inner})

    cfg = Outer()
    specs = _rust.completion_specs_for_config(cfg)
    spellings = [spelling for _, names, *_ in specs for spelling in names]
    assert '--inner' in spellings
    assert '--inner.__class__' in spellings

    class FakeIndex:
        def complete_values(self, argv, prefix):
            raise AssertionError('selected SubConfig completion must delegate')

    monkeypatch.setattr(_rust, 'compile_completion_index', lambda *a, **kw: FakeIndex())
    monkeypatch.setenv('_ARGCOMPLETE', '1')
    monkeypatch.setenv('COMP_LINE', 'prog --inner inner --inner.')
    monkeypatch.setenv('COMP_POINT', str(len('prog --inner inner --inner.')))
    assert _completion.try_config_argcomplete(cfg, autocomplete='auto') is False


def test_modal_completion_with_subconfig_selector_delegates():
    from kwconf import _completion
    from kwconf import _rust

    class Inner(kwconf.Config):
        depth: int = 1

    class Root(kwconf.ModalCLI):
        class Train(kwconf.Config):
            __command__ = 'train'
            inner = kwconf.SubConfig(Inner)

            @classmethod
            def main(cls, argv=False, **kwargs):
                return 0

    with pytest.raises(_rust.UnsupportedSchema):
        _completion._modal_static_model(Root())


def test_shell_sensitive_option_alias_delegates_completion():
    from kwconf import _rust

    class C(kwconf.Config):
        value = kwconf.Value('', alias=['value:rich'])

    with pytest.raises(_rust.UnsupportedSchema):
        _rust.completion_specs_for_config(C())


def test_shell_sensitive_modal_command_delegates_completion():
    from kwconf import _completion
    from kwconf import _rust

    class Root(kwconf.ModalCLI):
        class Weird(kwconf.Config):
            __command__ = 'bad:command'

            @classmethod
            def main(cls, argv=False, **kwargs):
                return 0

    with pytest.raises(_rust.UnsupportedSchema):
        _completion._modal_static_model(Root())
