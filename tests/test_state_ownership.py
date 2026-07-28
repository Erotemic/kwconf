import kwconf


def test_class_instance_and_runtime_state_are_independent():
    class Demo(kwconf.Config):
        payload = kwconf.Value([])

    class_template = Demo.__default__['payload']
    cfg = Demo()

    assert cfg._default['payload'] is not class_template
    assert cfg._default['payload'].value is not class_template.value
    assert cfg._data['payload'] is not cfg._default['payload'].value

    cfg.payload.append('runtime-only')
    assert cfg.payload == ['runtime-only']
    assert cfg._default['payload'].value == []
    assert class_template.value == []

    cfg.load(argv=False)
    assert cfg.payload == []
    assert cfg._data['payload'] is not cfg._default['payload'].value


def test_constructor_value_is_snapshotted_as_reset_baseline():
    class Demo(kwconf.Config):
        payload = kwconf.Value([])

    supplied = ['initial']
    cfg = Demo(payload=supplied)

    # Preserve ordinary Python constructor semantics for the current value,
    # while keeping reset state independent.
    assert cfg.payload is supplied
    assert cfg._default['payload'].value == ['initial']
    assert cfg._default['payload'].value is not supplied

    supplied.append('runtime-change')
    assert cfg.payload == ['initial', 'runtime-change']
    assert cfg._default['payload'].value == ['initial']

    cfg.load(argv=False)
    assert cfg.payload == ['initial']
    assert cfg.payload is not cfg._default['payload'].value


def test_update_defaults_changes_baseline_without_aliasing_runtime():
    class Demo(kwconf.Config):
        payload = kwconf.Value([])

    cfg = Demo()
    replacement = ['new-default']
    cfg.update_defaults({'payload': replacement})

    assert cfg.payload == []
    assert cfg._default['payload'].value == ['new-default']
    assert cfg._default['payload'].value is not replacement

    replacement.append('external-change')
    cfg.load(argv=False)
    assert cfg.payload == ['new-default']
    assert cfg.payload is not cfg._default['payload'].value


def test_subconfig_templates_are_schema_only():
    class Inner(kwconf.Config):
        payload = kwconf.Value([])

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(Inner)

    class_template = Outer.__default__['inner']
    cfg1 = Outer()
    cfg2 = Outer()

    assert cfg1._default['inner'] is not class_template
    assert cfg2._default['inner'] is not class_template
    assert cfg1._data['inner'] is not cfg2._data['inner']
    assert isinstance(cfg1.inner, Inner)
    assert isinstance(cfg2.inner, Inner)

    cfg1.inner.payload.append('only-cfg1')
    assert cfg2.inner.payload == []
    assert class_template.value is Inner


def test_default_factory_recipe_is_reinvoked_on_reset():
    calls = []

    def make_payload():
        calls.append(len(calls))
        return []

    class Demo(kwconf.Config):
        payload = kwconf.Value(default_factory=make_payload)

    cfg = Demo()
    assert calls == [0]
    cfg.payload.append('runtime')

    # A factory is a recipe, not a materialized reset snapshot. Reset invokes
    # it again, matching dataclasses.default_factory construction semantics.
    cfg.load(argv=False)
    assert calls == [0, 1]
    assert cfg.payload == []

    other = Demo()
    assert calls == [0, 1, 2]
    assert other.payload == []



def test_noncopyable_concrete_baselines_raise_actionable_error():
    import pytest

    class NonCopyable:
        def __deepcopy__(self, memo):
            raise TypeError('cannot deepcopy')

    supplied = NonCopyable()

    class ConstructorDemo(kwconf.Config):
        payload = None

    with pytest.raises(TypeError, match='default_factory'):
        ConstructorDemo(payload=supplied)

    cfg = ConstructorDemo()
    with pytest.raises(TypeError, match='default_factory'):
        cfg.update_defaults({'payload': supplied})

    class DeclaredDemo(kwconf.Config):
        payload = supplied

    with pytest.raises(TypeError, match='default_factory'):
        DeclaredDemo()
