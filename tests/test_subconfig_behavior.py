# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
import textwrap
from typing import Any

import pytest

import kwconf


class SGDConfig(kwconf.Config):
    lr = kwconf.Value(0.01, type=float)
    momentum = kwconf.Value(0.9, type=float)


class AdamConfig(kwconf.Config):
    lr = kwconf.Value(0.001, type=float)
    beta1 = kwconf.Value(0.9, type=float)


class BackboneConfig(kwconf.Config):
    patch = kwconf.Value(4, type=int)


class SegformerConfig(kwconf.Config):
    backbone = kwconf.SubConfig(BackboneConfig, choices={'vit': BackboneConfig})
    heads = 1


class ModelConfig(kwconf.Config):
    name = 'base'


class TrainConfig(kwconf.Config):
    optim = kwconf.SubConfig(
        AdamConfig, choices={'adam': AdamConfig, 'sgd': SGDConfig}
    )
    model = kwconf.SubConfig(
        ModelConfig, choices={'base': ModelConfig, 'seg': SegformerConfig}
    )
    epochs = kwconf.Value(10, type=int)


def test_flat_fastpath():
    class FlatConfig(kwconf.Config):
        foo = 1

    cfg = FlatConfig.cli(argv=['--foo', '3'])
    assert cfg.foo == 3
    assert not cfg._has_subconfigs


def test_nested_leaf_override_via_cli():
    cfg = TrainConfig.cli(
        argv=['--optim.lr=0.02'], allow_subconfig_overrides=True
    )
    assert cfg.optim.lr == pytest.approx(0.02)


def test_selector_via_dunder_class_and_sugar():
    cfg = TrainConfig.cli(
        argv=['--optim.__class__=sgd', '--optim.momentum=0.7'],
        allow_subconfig_overrides=True,
    )
    assert isinstance(cfg.optim, SGDConfig)
    assert cfg.optim.momentum == pytest.approx(0.7)

    cfg2 = TrainConfig.cli(
        argv=['--optim=sgd', '--optim.momentum=0.5'],
        allow_subconfig_overrides=True,
    )
    assert isinstance(cfg2.optim, SGDConfig)
    assert cfg2.optim.momentum == pytest.approx(0.5)


def test_nested_selector_and_deep_leaves():
    cfg = TrainConfig.cli(
        argv=[
            '--model=seg',
            '--model.backbone=vit',
            '--model.backbone.patch=16',
        ],
        allow_subconfig_overrides=True,
    )
    assert isinstance(cfg.model, SegformerConfig)
    assert isinstance(cfg.model.backbone, BackboneConfig)
    assert cfg.model.backbone.patch == 16


def test_variant_aware_help(capsys):
    with pytest.raises(SystemExit):
        TrainConfig.cli(
            argv=['--model=seg', '--help'], allow_subconfig_overrides=True
        )
    out = capsys.readouterr().out
    assert 'model.backbone.patch' in out


def test_precedence_default_file_kwargs_cli(tmp_path):
    cfg_path = tmp_path / 'train.yaml'
    cfg_text = textwrap.dedent(
        """
        optim:
            __class__: sgd
            lr: 0.2
        epochs: 5
        """
    )
    cfg_path.write_text(cfg_text)
    kw_overrides = {'epochs': 8}
    cli_overrides = ['--epochs=12']
    cfg = TrainConfig.cli(
        data=kw_overrides,
        argv=['--config', str(cfg_path), *cli_overrides],
        allow_subconfig_overrides=True,
        special_options=True,
    )
    assert isinstance(cfg.optim, SGDConfig)
    assert cfg.optim.lr == pytest.approx(0.2)
    assert cfg.epochs == 12


def test_unknown_key_error():
    with pytest.raises(SystemExit):
        TrainConfig.cli(
            argv=['--optim.unknown=1'], allow_subconfig_overrides=True
        )


def test_reserved_class_name_error():
    with pytest.raises(ValueError):

        class BadConfig(kwconf.Config):
            __default__ = {'__class__': 1}


def test_dotted_access_for_config_and_dataconfig():
    class Inner(kwconf.Config):
        __default__ = {'leaf': 1}

    class Outer(kwconf.Config):
        __default__ = {'inner': Inner()}

    cfg = Outer()
    cfg['inner.leaf'] = 5
    assert cfg['inner.leaf'] == 5
    assert cfg['inner']['leaf'] == 5

    class InnerDC(kwconf.Config):
        leaf = 1

    class OuterDC(kwconf.Config):
        inner = InnerDC()

    dcfg = OuterDC()
    dcfg['inner.leaf'] = 9
    assert dcfg['inner.leaf'] == 9
    assert dcfg.inner.leaf == 9


def test_dump_and_load_roundtrip(tmp_path):
    class ChoiceA(kwconf.Config):
        x = 1

    class ChoiceB(kwconf.Config):
        x = 2

    class Outer(kwconf.Config):
        __default__ = {
            'inner': kwconf.SubConfig(
                ChoiceA, choices={'a': ChoiceA, 'b': ChoiceB}
            ),
            'root': 3,
        }

    cfg = Outer.cli(
        argv=['--inner=b', '--inner.x=10'], allow_subconfig_overrides=True
    )
    out_path = tmp_path / 'cfg.yaml'
    with open(out_path, 'w') as file:
        cfg.dump(stream=file)

    cfg2 = Outer()
    cfg2.load(out_path, argv=False)
    assert isinstance(cfg2['inner'], ChoiceB)
    assert cfg2['inner'].x == 10
    assert cfg2['root'] == 3


def test_subconfig_overrides_disabled(capsys):
    cfg = TrainConfig.cli(
        argv=['--optim.beta1=0.3'], allow_subconfig_overrides=False
    )
    assert cfg.optim.beta1 == pytest.approx(0.3)

    with pytest.raises(SystemExit):
        TrainConfig.cli(argv=['--optim=sgd'], allow_subconfig_overrides=False)
    err = capsys.readouterr().err
    assert 'allow_subconfig_overrides=True' in err
    with pytest.raises(SystemExit):
        TrainConfig.cli(
            argv=['--optim.__class__=sgd'], allow_subconfig_overrides=False
        )


def test_subconfig_class_in_dict():
    cfg = TrainConfig.cli(argv=[], allow_subconfig_overrides=False)
    data = cfg.to_dict()
    assert data['optim']['__class__'] == 'adam'


def test_subconfig_stacklevel_localns_resolution():
    class LocalOpt(kwconf.Config):
        __default__ = {'lr': 0.2}

    class TrainLocal(kwconf.Config):
        __default__ = {
            'optim': kwconf.SubConfig(AdamConfig, choices={'adam': AdamConfig}),
        }

    def wrapper_cli():
        return TrainLocal.cli(
            argv=['--optim=LocalOpt'],
            allow_subconfig_overrides=True,
            stacklevel=1,
        )

    cfg = wrapper_cli()
    assert isinstance(cfg['optim'], LocalOpt)

    def wrapper_load():
        cfg = TrainLocal()
        cfg.load(
            argv=['--optim=LocalOpt'],
            allow_subconfig_overrides=True,
            stacklevel=1,
        )
        return cfg

    cfg2 = wrapper_load()
    assert isinstance(cfg2['optim'], LocalOpt)


def test_config_attribute_lookup_matches_typed_style():
    class SimpleConfig(kwconf.Config):
        value: int = 3

    cfg = SimpleConfig()
    assert cfg.value == 3
    cfg.value = 4
    assert cfg['value'] == 4


def test_subconfig_nested_class_scope_resolution():
    class Container:
        class LocalOpt(kwconf.Config):
            __default__ = {'lr': 0.3}

    class ContainerTrain(kwconf.Config):
        __default__ = {
            'optim': kwconf.SubConfig(
                Container.LocalOpt,
                choices={'local': Container.LocalOpt},
            ),
        }

    cfg = ContainerTrain.cli(
        argv=['--optim=local'],
        allow_subconfig_overrides=True,
        stacklevel=0,
    )
    assert isinstance(cfg['optim'], Container.LocalOpt)


def test_subconfig_local_scope_resolution_in_function():
    def build_cfg():
        class LocalOpt(kwconf.Config):
            __default__ = {'lr': 0.4}

        class TrainLocal(kwconf.Config):
            __default__ = {
                'optim': kwconf.SubConfig(
                    LocalOpt,
                    choices={'local': LocalOpt},
                ),
            }

        cfg = TrainLocal.cli(
            argv=['--optim=local'],
            allow_subconfig_overrides=True,
            stacklevel=1,
        )
        return cfg, LocalOpt

    cfg, local_cls = build_cfg()
    assert isinstance(cfg['optim'], local_cls)


def test_value_wrapped_config_upgrades_to_subconfig():
    class InnerConfig(kwconf.Config):
        x = 2

    class OuterConfig(kwconf.Config):
        __default__ = {
            'inner_cfg': kwconf.Value(InnerConfig()),
            'inner_dc': kwconf.Value(InnerConfig()),
        }

    cfg = OuterConfig()
    assert cfg._has_subconfigs
    assert isinstance(cfg._subconfig_meta['inner_cfg'], kwconf.SubConfig)
    assert isinstance(cfg._subconfig_meta['inner_dc'], kwconf.SubConfig)
    assert isinstance(cfg['inner_cfg'], InnerConfig)
    assert isinstance(cfg['inner_dc'], InnerConfig)


def test_dataconfig_class_default_selector_by_classname():
    class OptimizerConfig(kwconf.Config):
        lr = 1e-3

    class Adam(OptimizerConfig):
        beta1 = 0.9

    class Sgd(OptimizerConfig):
        momentum = 0.9

    class TrainCfg(kwconf.Config):
        optim = Adam
        epochs = kwconf.Value(10, type=int)

    cfg = TrainCfg.cli(
        argv='--optim=Sgd --optim.momentum=0.8 --epochs=20',
        allow_subconfig_overrides=True,
    )
    assert isinstance(cfg._subconfig_meta['optim'], kwconf.SubConfig)
    assert isinstance(cfg.optim, Sgd)
    assert cfg.optim.momentum == pytest.approx(0.8)
    assert cfg.epochs == 20


def test_dataconfig_value_wrapped_subconfig():
    class OptimizerConfig(kwconf.Config):
        lr = 1e-3

    class Adam(OptimizerConfig):
        beta1 = 0.9

    class TrainCfg(kwconf.Config):
        optim = kwconf.Value(Adam)

    cfg = TrainCfg()
    assert isinstance(cfg._subconfig_meta['optim'], kwconf.SubConfig)
    assert isinstance(cfg.optim, Adam)


def test_subconfig_config_string_cases():
    class OptimizerConfig(kwconf.Config):
        lr = kwconf.Value(0.01, type=float)

    class SGDLocal(OptimizerConfig):
        momentum = kwconf.Value(0.9, type=float)

    class AdamLocal(OptimizerConfig):
        beta1 = kwconf.Value(0.9, type=float)

    class TrainLocal(kwconf.Config):
        optim = kwconf.SubConfig(
            SGDLocal, choices={'adam': AdamLocal, 'sgd': SGDLocal}
        )
        model = kwconf.Value('vit', choices=['vit', 'resnet50'])
        epochs = kwconf.Value(10, type=int)

    cases: list[dict[str, Any]] = [
        {
            'argv': '--config "{model: resnet50, optim.momentum: 0.88}"',
            'optim': SGDLocal,
        },
        {
            'argv': '--config "{model: resnet50, optim: {momentum: 0.88}}"',
            'optim': SGDLocal,
        },
        {
            'argv': '--config "{model: resnet50, optim: adam, optim.beta1: 0.88}"',
            'optim': AdamLocal,
        },
        {
            'argv': '--config "{model: resnet50, optim.__class__: adam, optim.beta1: 0.88}"',
            'optim': AdamLocal,
        },
        {
            'argv': '--config "{model: resnet50, optim: {__class__: adam, beta1: 0.88}}"',
            'optim': AdamLocal,
        },
    ]

    for case in cases:
        cfg = TrainLocal.cli(
            argv=case['argv'],
            allow_import=True,
            allow_subconfig_overrides=True,
            special_options=True,
        )
        assert cfg.model == 'resnet50'
        assert isinstance(cfg.optim, case['optim'])
        if isinstance(cfg.optim, SGDLocal):
            assert cfg.optim.momentum == pytest.approx(0.88)
        else:
            assert cfg.optim.beta1 == pytest.approx(0.88)


def test_subconfig_class_identifier_module_path():
    class Inner(kwconf.Config):
        __default__ = {'x': 1}

    class Outer(kwconf.Config):
        __default__ = {'inner': kwconf.SubConfig(Inner)}

    cfg = Outer()
    data = cfg.to_dict()
    assert data['inner']['__class__'] == f'{Inner.__module__}.{Inner.__name__}'


def test_dict_leaf_field_alongside_subconfig():
    """
    A plain dict-valued leaf field must not be shredded into dotted keys just
    because the config also has a SubConfig; load() used to crash with
    KeyError trying to treat the dict field as a subconfig node.
    """

    class Inner(kwconf.Config):
        x = kwconf.Value(1)

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(Inner)
        hyperparams = kwconf.Value(None)

    cfg = Outer()
    cfg.load({'hyperparams': {'lr': 0.5}}, argv=False)
    assert cfg['hyperparams'] == {'lr': 0.5}
    assert cfg['inner']['x'] == 1

    # The subconfig itself still updates via a nested mapping.
    cfg2 = Outer()
    cfg2.load({'inner': {'x': 9}}, argv=False)
    assert cfg2['inner']['x'] == 9

    # Non-string dict keys in a leaf must not crash '.'.join.
    cfg3 = Outer()
    cfg3.load({'hyperparams': {1: 'a', 2: 'b'}}, argv=False)
    assert cfg3['hyperparams'] == {1: 'a', 2: 'b'}


def test_empty_dict_leaf_update_applies():
    """An explicit empty-dict update to a leaf field must not be dropped."""

    class Inner(kwconf.Config):
        x = kwconf.Value(1)

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(Inner)
        hyperparams = kwconf.Value(None)

    cfg = Outer()
    cfg['hyperparams'] = {'lr': 0.1}
    cfg.load({'hyperparams': {}}, argv=False)
    assert cfg['hyperparams'] == {}


def test_scan_config_path_does_not_swallow_next_option():
    import pytest

    from kwconf.subconfig import scan_config_path

    assert scan_config_path(['--config', 'demo.yaml']) == 'demo.yaml'
    assert scan_config_path(['--config=demo.yaml']) == 'demo.yaml'
    assert scan_config_path(['--verbose']) is None

    # A following option means --config had no value.
    with pytest.raises(ValueError):
        scan_config_path(['--config', '--verbose'])
    with pytest.raises(ValueError):
        scan_config_path(['--config'])

    # Tokens after -- are positional, not a --config value.
    assert scan_config_path(['--', '--config', 'x.yaml']) is None


def test_conflicting_subconfig_selectors_are_safe_without_scan():
    """The lean path is deterministic and never stores selector text as a node."""

    class A(kwconf.Config):
        a = 1

    class B(kwconf.Config):
        b = 2

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(A, choices={'a': A, 'b': B})

    cfg = Outer.cli(
        data={'inner': 'a', 'inner.__class__': 'b'},
        argv=False,
    )
    assert isinstance(cfg.inner, B)
    assert cfg.inner.b == 2


def test_cli_validate_error_rejects_conflicting_subconfig_selectors():
    import kwconf

    class A(kwconf.Config):
        a = 1

    class B(kwconf.Config):
        b = 2

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(A, choices={'a': A, 'b': B})

    with pytest.raises(
        kwconf.ConfigValidationError,
        match="Conflicting SubConfig selector updates for 'inner'",
    ):
        Outer.cli(
            data={'inner': 'a', 'inner.__class__': 'b'},
            argv=False,
            validate='error',
        )


def test_cli_validate_warns_and_uses_safe_subconfig_precedence():
    import kwconf

    class A(kwconf.Config):
        a = 1

    class B(kwconf.Config):
        b = 2

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(A, choices={'a': A, 'b': B})

    with pytest.warns(
        UserWarning,
        match="Conflicting SubConfig selector updates for 'inner'",
    ):
        cfg = Outer.cli(
            data={'inner': 'a', 'inner.__class__': 'b'},
            argv=False,
            validate='warn',
        )
    assert isinstance(cfg.inner, B)


def test_nested_and_dotted_selector_duplicates_are_validated():
    import kwconf

    class A(kwconf.Config):
        a = 1

    class B(kwconf.Config):
        b = 2

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(A, choices={'a': A, 'b': B})

    with pytest.raises(
        kwconf.ConfigValidationError,
        match="Conflicting SubConfig selector updates for 'inner'",
    ):
        Outer.cli(
            data={
                'inner': {'__class__': 'a'},
                'inner.__class__': 'b',
            },
            argv=False,
            validate='error',
        )


def test_class_error_policy_enables_structural_validation():
    import kwconf

    class A(kwconf.Config):
        a = 1

    class B(kwconf.Config):
        b = 2

    class Outer(kwconf.Config):
        __validate__ = 'error'
        inner = kwconf.SubConfig(A, choices={'a': A, 'b': B})

    with pytest.raises(kwconf.ConfigValidationError):
        Outer.cli(
            data={'inner': 'a', 'inner.__class__': 'b'},
            argv=False,
        )


def test_cross_source_subconfig_override_is_not_a_conflict():
    import kwconf

    class A(kwconf.Config):
        a = 1

    class B(kwconf.Config):
        b = 2

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(A, choices={'a': A, 'b': B})

    cfg = Outer.cli(
        data={'inner': 'a'},
        argv=['--inner=b'],
        validate='error',
    )
    assert isinstance(cfg.inner, B)


def test_default_cli_path_does_not_run_structural_scan(monkeypatch):
    import kwconf.subconfig as subconfig_mod

    class Inner(kwconf.Config):
        value = 1

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(Inner, choices={'inner': Inner})

    def fail_if_called(*args, **kwargs):
        raise RuntimeError('structural validation scan ran')

    monkeypatch.setattr(
        subconfig_mod, '_find_selector_update_conflicts', fail_if_called
    )
    cfg = Outer.cli(data={'inner': {'value': 2}}, argv=False)
    assert cfg.inner.value == 2


def test_cli_validate_override_reaches_nested_values():
    class Inner(kwconf.Config):
        value: int = kwconf.Value(0, validate=False)

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(Inner)

    with pytest.raises(kwconf.ConfigValidationError, match='does not match'):
        Outer.cli(
            data={'inner': {'value': 'not-an-int'}},
            argv=False,
            validate='error',
        )


def test_same_selector_does_not_rebuild_or_erase_lower_precedence_data():
    counts = {'a': 0, 'b': 0}

    class A(kwconf.Config):
        x = 1

        def __init__(self, *args, **kwargs):
            counts['a'] += 1
            super().__init__(*args, **kwargs)

    class B(kwconf.Config):
        y = 2

        def __init__(self, *args, **kwargs):
            counts['b'] += 1
            super().__init__(*args, **kwargs)

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(A, choices={'a': A, 'b': B})

    cfg = Outer.cli(
        data={'inner': 'b', 'inner.y': 7},
        argv=['--inner=b'],
    )
    assert isinstance(cfg.inner, B)
    assert cfg.inner.y == 7
    # The selected implementation is constructed only once. Reapplying the
    # same selector used to rebuild it three times and discard data= values.
    assert counts['b'] == 1


def test_subconfig_source_precedence_data_then_config_then_argv(tmp_path):
    class A(kwconf.Config):
        x = 1

    class B(kwconf.Config):
        y = 2

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(A, choices={'a': A, 'b': B})
        marker = 0

    config_path = tmp_path / 'config.yaml'
    config_path.write_text('inner: a\ninner.x: 5\nmarker: 2\n')

    cfg = Outer.cli(
        data={'inner': 'a', 'inner.x': 3, 'marker': 1},
        argv=[
            '--config',
            str(config_path),
            '--inner=b',
            '--inner.y=9',
            '--marker=4',
        ],
        special_options=True,
    )
    assert isinstance(cfg.inner, B)
    assert cfg.inner.y == 9
    assert cfg.marker == 4

    cfg_without_cli_values = Outer.cli(
        data={'inner': 'a', 'inner.x': 3, 'marker': 1},
        argv=['--config', str(config_path)],
        special_options=True,
    )
    assert isinstance(cfg_without_cli_values.inner, A)
    assert cfg_without_cli_values.inner.x == 5
    assert cfg_without_cli_values.marker == 2


def test_plain_dict_dunder_class_is_not_a_subconfig_selector():
    class Inner(kwconf.Config):
        x = 1

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(Inner)
        metadata = {}

    cfg = Outer.cli(
        data={'metadata': {'__class__': 'ordinary-payload'}},
        argv=['--inner.x=2'],
        allow_subconfig_overrides=False,
    )
    assert cfg.metadata == {'__class__': 'ordinary-payload'}
    assert cfg.inner.x == 2


def test_selector_realization_has_no_arbitrary_depth_limit():
    depth = 24

    class Terminal(kwconf.Config):
        value = 0

    default_cls = Terminal
    selected_cls = Terminal
    selected_classes = {}
    for index in reversed(range(depth)):
        next_default = default_cls
        next_selected = selected_cls

        default_cls = type(
            f'Default{index}',
            (kwconf.Config,),
            {'__module__': __name__, 'value': index},
        )
        selected_cls = type(
            f'Selected{index}',
            (kwconf.Config,),
            {
                '__module__': __name__,
                'next': kwconf.SubConfig(
                    next_default, choices={'selected': next_selected}
                ),
            },
        )
        selected_classes[index] = selected_cls

    class Root(kwconf.Config):
        node = kwconf.SubConfig(default_cls, choices={'selected': selected_cls})

    argv = []
    path = 'node'
    for _ in range(depth):
        argv.append(f'--{path}=selected')
        path += '.next'

    cfg = Root.cli(argv=argv)
    node = cfg.node
    for _ in range(depth - 1):
        node = node.next
    assert isinstance(node, selected_classes[depth - 1])
    assert isinstance(node.next, Terminal)


def test_invalid_import_selector_has_targeted_error():
    class Inner(kwconf.Config):
        x = 1

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(Inner)

    with pytest.raises(ValueError, match='Cannot interpret class spec'):
        Outer.cli(argv=['--inner=not_a_class_path'], stacklevel=None)


def test_nested_qualname_import_roundtrip(monkeypatch):
    """Nested importable classes keep a resolvable serialized identifier."""
    import sys
    import types

    module_name = 'kwconf_test_nested_import_target'
    module = types.ModuleType(module_name)
    nested_cls = type(
        'NestedChoice',
        (kwconf.Config,),
        {
            '__module__': module_name,
            '__qualname__': 'ImportContainer.NestedChoice',
            'value': 11,
        },
    )
    container = type('ImportContainer', (), {'NestedChoice': nested_cls})
    setattr(module, 'ImportContainer', container)
    monkeypatch.setitem(sys.modules, module_name, module)

    class DefaultChoice(kwconf.Config):
        value = 0

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(DefaultChoice)

    selector = f'{module_name}.ImportContainer.NestedChoice'
    cfg = Outer.cli(argv=[f'--inner={selector}'], stacklevel=None)
    assert type(cfg.inner) is nested_cls

    data = cfg.to_dict()
    assert data['inner']['__class__'] == selector

    restored = Outer.cli(data=data, argv=False, stacklevel=None)
    assert type(restored.inner) is nested_cls
    assert restored.inner.value == 11


def test_field_allow_import_true_overrides_call_policy(monkeypatch):
    """The field-local tri-state may explicitly enable an import."""
    import sys
    import types

    module_name = 'kwconf_test_import_policy_target'
    module = types.ModuleType(module_name)
    imported_cls = type(
        'ImportedChoice',
        (kwconf.Config,),
        {'__module__': module_name, 'value': 3},
    )
    setattr(module, 'ImportedChoice', imported_cls)
    monkeypatch.setitem(sys.modules, module_name, module)

    class DefaultChoice(kwconf.Config):
        value = 0

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(DefaultChoice, allow_import=True)

    cfg = Outer.cli(
        argv=[f'--inner={module_name}.ImportedChoice'],
        allow_import=False,
        stacklevel=None,
    )
    assert type(cfg.inner) is imported_cls


def test_call_level_allow_import_false_applies_when_field_inherits(monkeypatch):
    """A field with no override inherits the call-level import policy."""
    import sys
    import types

    module_name = 'kwconf_test_inherited_import_policy_target'
    module = types.ModuleType(module_name)
    imported_cls = type(
        'ImportedChoice',
        (kwconf.Config,),
        {'__module__': module_name, 'value': 3},
    )
    setattr(module, 'ImportedChoice', imported_cls)
    monkeypatch.setitem(sys.modules, module_name, module)

    class DefaultChoice(kwconf.Config):
        value = 0

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(DefaultChoice)

    with pytest.raises(ValueError, match='not allowed'):
        Outer.cli(
            argv=[f'--inner={module_name}.ImportedChoice'],
            allow_import=False,
            stacklevel=None,
        )


def test_field_allow_import_false_opts_out(monkeypatch):
    """A SubConfig field may prohibit imports under a permissive caller."""
    import sys
    import types

    module_name = 'kwconf_test_field_import_policy_target'
    module = types.ModuleType(module_name)
    imported_cls = type(
        'ImportedChoice',
        (kwconf.Config,),
        {'__module__': module_name, 'value': 3},
    )
    setattr(module, 'ImportedChoice', imported_cls)
    monkeypatch.setitem(sys.modules, module_name, module)

    class DefaultChoice(kwconf.Config):
        value = 0

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(DefaultChoice, allow_import=False)

    with pytest.raises(ValueError, match='not allowed'):
        Outer.cli(
            argv=[f'--inner={module_name}.ImportedChoice'],
            allow_import=True,
            stacklevel=None,
        )


def test_choice_serialization_uses_exact_selected_class():
    """A subclass must not serialize as an earlier base-class choice."""

    class BaseChoice(kwconf.Config):
        base = 1

    class ChildChoice(BaseChoice):
        child = 2

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(
            BaseChoice,
            choices={'base': BaseChoice, 'child': ChildChoice},
        )

    cfg = Outer.cli(argv=['--inner=child'])
    data = cfg.to_dict()
    assert data['inner']['__class__'] == 'child'

    restored = Outer.cli(data=data, argv=False)
    assert type(restored.inner) is ChildChoice
    assert restored.inner.child == 2


def test_config_option_preserves_ordinary_dict_leaf(tmp_path):
    """The staged --config path must flatten with the live schema."""

    class Inner(kwconf.Config):
        value = 1

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(Inner)
        metadata = {}

    config_path = tmp_path / 'config.yaml'
    config_path.write_text(
        'metadata:\n  __class__: ordinary-payload\n  nested:\n    value: 3\n'
    )
    cfg = Outer.cli(
        argv=['--config', str(config_path)],
        special_options=True,
    )
    assert cfg.metadata == {
        '__class__': 'ordinary-payload',
        'nested': {'value': 3},
    }


def test_parent_selector_can_reveal_nested_mapping_subconfig():
    """Deferred mappings are applied after their parent schema is realized."""

    class LeafA(kwconf.Config):
        x = 1

    class LeafB(kwconf.Config):
        y = 2

    class ParentA(kwconf.Config):
        marker = 'a'

    class ParentB(kwconf.Config):
        child = kwconf.SubConfig(
            LeafA,
            choices={'a': LeafA, 'b': LeafB},
        )

    class Root(kwconf.Config):
        parent = kwconf.SubConfig(
            ParentA,
            choices={'a': ParentA, 'b': ParentB},
        )

    cfg = Root.cli(
        data={
            'parent': {
                '__class__': 'b',
                'child': {'__class__': 'b', 'y': 9},
            }
        },
        argv=False,
    )
    assert type(cfg.parent) is ParentB
    assert type(cfg.parent.child) is LeafB
    assert cfg.parent.child.y == 9


def test_explicit_nested_selector_wins_over_deferred_mapping_selector():
    """Dotted selector precedence remains safe for newly revealed paths."""

    class LeafA(kwconf.Config):
        x = 1

    class LeafB(kwconf.Config):
        y = 2

    class ParentA(kwconf.Config):
        marker = 'a'

    class ParentB(kwconf.Config):
        child = kwconf.SubConfig(
            LeafA,
            choices={'a': LeafA, 'b': LeafB},
        )

    class Root(kwconf.Config):
        parent = kwconf.SubConfig(
            ParentA,
            choices={'a': ParentA, 'b': ParentB},
        )

    cfg = Root.cli(
        data={
            'parent.__class__': 'b',
            'parent.child.__class__': 'b',
            'parent': {'child': {'__class__': 'a', 'y': 9}},
        },
        argv=False,
    )
    assert type(cfg.parent.child) is LeafB
    assert cfg.parent.child.y == 9


def test_structural_validation_survives_staged_data_loading():
    """Adding argv must not erase nested-vs-dotted source provenance."""

    class A(kwconf.Config):
        value = 1

    class B(kwconf.Config):
        value = 2

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(A, choices={'a': A, 'b': B})
        marker = 0

    with pytest.raises(
        kwconf.ConfigValidationError,
        match="Conflicting SubConfig selector updates for 'inner'",
    ):
        Outer.cli(
            data={
                'inner': {'__class__': 'a'},
                'inner.__class__': 'b',
            },
            argv=['--marker=1'],
            validate='error',
        )


def test_structural_validation_preserves_config_file_provenance(tmp_path):
    """The --config bootstrap must validate before flattening the source."""

    class A(kwconf.Config):
        value = 1

    class B(kwconf.Config):
        value = 2

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(A, choices={'a': A, 'b': B})

    config_path = tmp_path / 'conflict.yaml'
    config_path.write_text('inner:\n  __class__: a\ninner.__class__: b\n')
    with pytest.raises(
        kwconf.ConfigValidationError,
        match="Conflicting SubConfig selector updates for 'inner'",
    ):
        Outer.cli(
            argv=['--config', str(config_path)],
            special_options=True,
            validate='error',
        )
