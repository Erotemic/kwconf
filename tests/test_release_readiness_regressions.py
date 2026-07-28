"""Regression coverage for the 0.10.1 release-readiness audit."""

import dataclasses
import functools
import json
import threading

import pytest

import kwconf


def test_required_tracks_current_data_config_and_argv_sources(tmp_path):
    class C(kwconf.Config):
        __special_options__ = True
        x = kwconf.Value(1, required=True)
        other = 0

    config_fpath = tmp_path / 'config.json'
    config_fpath.write_text(json.dumps({'x': 1}))

    # A --config value equal to the declared default is still explicitly given.
    cfg = C.cli(argv=['--config', str(config_fpath)])
    assert cfg.x == 1

    # Provenance is scoped to the current load, not retained from old argv.
    cfg = C.cli(argv=['--x=2'])
    with pytest.raises(ValueError, match='Required variable'):
        cfg.load({'other': 3}, argv=False)

    # Factory output identity/equality never substitutes for provenance.
    class FactoryRequired(kwconf.Config):
        payload = kwconf.Value(default_factory=list, required=True)

    with pytest.raises(ValueError, match='Required variable'):
        FactoryRequired.cli(argv=False)


def test_required_provenance_is_distributed_to_subconfigs():
    class Inner(kwconf.Config):
        x = kwconf.Value(1, required=True)

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(Inner)

    assert Outer.cli(data={'inner': {'x': 1}}, argv=False).inner.x == 1
    with pytest.raises(ValueError, match="Required variable 'x'"):
        Outer.cli(data={}, argv=False)


def test_mapping_alias_duplicates_are_rejected_deterministically():
    class C(kwconf.Config):
        x = kwconf.Value(0, alias=['a', 'b'])

    for data in ({'a': 1, 'b': 2}, {'x': 1, 'a': 2}):
        with pytest.raises(TypeError, match='Multiple input keys'):
            C.cli(data=data, argv=False)


def test_nested_mapping_alias_duplicates_are_rejected():
    class Inner(kwconf.Config):
        x = kwconf.Value(0, alias=['alias_x'])

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(Inner)

    with pytest.raises(TypeError, match='Multiple input keys'):
        Outer.cli(
            data={'inner.x': 1, 'inner.alias_x': 2},
            argv=False,
        )


def test_dataconf_preserves_zero_argument_super():
    class Base:
        def greet(self):
            return 'base'

    @kwconf.dataconf
    class Child(Base):
        x = 1

        def greet(self):
            return super().greet() + '-child'

    assert Child(x=2).greet() == 'base-child'


def test_dataconf_translates_stdlib_default_factory_fields():
    @kwconf.dataconf
    @dataclasses.dataclass
    class C:
        payload: list = dataclasses.field(default_factory=list)
        count: int = 3

    first = C()
    second = C()
    first.payload.append('first')
    assert first.asdict() == {'payload': ['first'], 'count': 3}
    assert second.asdict() == {'payload': [], 'count': 3}


def test_concrete_defaults_require_deepcopy_but_factories_do_not():
    class NonCopyable:
        def __deepcopy__(self, memo):
            raise TypeError('cannot deepcopy')

    value = NonCopyable()

    class Bad(kwconf.Config):
        payload = value

    with pytest.raises(TypeError, match='default_factory'):
        Bad()

    class Good(kwconf.Config):
        payload = kwconf.Value(default_factory=NonCopyable)

    assert isinstance(Good().payload, NonCopyable)


def test_subconfig_instance_clones_baseline_without_copying_factory_output():
    class Inner(kwconf.Config):
        lock = kwconf.Value(default_factory=threading.Lock)
        payload = kwconf.Value(default_factory=list)

    template = Inner()
    template.payload.append('runtime-only')

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(template)

    first = Outer()
    second = Outer()
    assert first.inner.lock is not template.lock
    assert first.inner.lock is not second.inner.lock
    assert first.inner.payload == []
    assert second.inner.payload == []


def test_port_to_config_preserves_importable_default_factory():
    class Source(kwconf.Config):
        payload = kwconf.Value(default_factory=list)

    text = Source().port_to_config()
    assert 'default_factory=list' in text
    assert 'payload = kwconf.Value([])' not in text

    namespace = {}
    exec(text, namespace)
    first = namespace['Source']()
    second = namespace['Source']()
    assert first.payload == []
    assert first.payload is not second.payload


def test_port_to_config_rejects_unrepresentable_default_factory():
    def local_factory():
        return []

    class Source(kwconf.Config):
        payload = kwconf.Value(default_factory=local_factory)

    with pytest.raises(ValueError, match='cannot represent'):
        Source().port_to_config()


def test_descriptors_are_not_collected_as_config_fields():
    class C(kwconf.Config):
        x = 2

        @property
        def double(self):
            return self.x * 2

        @functools.cached_property
        def triple(self):
            return self.x * 3

    cfg = C()
    assert cfg.asdict() == {'x': 2}
    assert cfg.double == 4
    assert cfg.triple == 6
    assert 'double' not in C.__default__
    assert 'triple' not in C.__default__
