import argparse
import inspect

import pytest

import kwconf

CLASSMETHOD_NAMES = {
    'validate',
    'coerce',
    'from_cli',
    'from_yaml',
    'from_env',
    'cli',
    'demo',
    'parse_args',
    'parse_known_args',
    'port_from_click',
    'port_from_argparse',
    'cls_from_argparse',
}

INSTANCE_METHOD_NAMES = {
    'asdict',
    'to_dict',
    'copy',
    'update',
    'pop',
    'popitem',
    'clear',
    'keys',
    'update_defaults',
    'load',
    'dump',
    'dumps',
    'port_to_config',
    'port_to_argparse',
    'argparse',
}

INHERITED_MAPPING_NAMES = {'get', 'items', 'values'}
PROPERTY_NAMES = {'namespace'}
MAPPING_NAMES = {
    'clear',
    'copy',
    'get',
    'items',
    'keys',
    'pop',
    'popitem',
    'update',
    'values',
}
ALL_PUBLIC_OPERATION_NAMES = (
    CLASSMETHOD_NAMES
    | INSTANCE_METHOD_NAMES
    | INHERITED_MAPPING_NAMES
    | PROPERTY_NAMES
)
SHADOWABLE_NAMES = ALL_PUBLIC_OPERATION_NAMES - MAPPING_NAMES


def test_every_public_operation_has_matching_private_alias():
    """The private operation surface must stay complete and descriptor-safe."""
    discovered = set()
    for name in dir(kwconf.Config):
        if name.startswith('_'):
            continue
        value = inspect.getattr_static(kwconf.Config, name)
        if isinstance(value, (classmethod, staticmethod, property)) or callable(
            value
        ):
            discovered.add(name)
    assert discovered == ALL_PUBLIC_OPERATION_NAMES

    for name in sorted(ALL_PUBLIC_OPERATION_NAMES):
        public = inspect.getattr_static(kwconf.Config, name)
        private = inspect.getattr_static(kwconf.Config, '_' + name)
        assert private is public

    for name in CLASSMETHOD_NAMES:
        assert isinstance(
            inspect.getattr_static(kwconf.Config, name), classmethod
        )
    assert isinstance(
        inspect.getattr_static(kwconf.Config, 'namespace'), property
    )


def test_config_api_names_can_be_instance_fields():
    defaults = {name: f'field-{name}' for name in SHADOWABLE_NAMES}

    class CollisionConfig(kwconf.Config):
        __default__ = defaults

    cfg = CollisionConfig()

    for name, expected in defaults.items():
        assert cfg[name] == expected
        assert getattr(cfg, name) == expected
        assert hasattr(cfg, '_' + name)

        class_value = getattr(CollisionConfig, name)
        if name == 'namespace':
            assert isinstance(class_value, property)
        else:
            assert callable(class_value)

    # Class operations stay available even when their names are instance fields.
    CollisionConfig.validate()
    CollisionConfig._validate()
    assert CollisionConfig.cli(argv=False).cli == 'field-cli'
    assert CollisionConfig._cli(argv=False).cli == 'field-cli'

    # Private instance operations remain usable when the public spelling is data.
    cfg._load({'load': 'changed'}, argv=False)
    assert cfg.load == 'changed'
    cfg.load = 'assigned'
    assert cfg['load'] == 'assigned'
    assert '"load": "assigned"' in cfg._dumps(mode='json')
    assert isinstance(cfg._namespace, argparse.Namespace)
    assert cfg._namespace.load == 'assigned'
    assert isinstance(cfg._argparse(), argparse.ArgumentParser)


def test_mapping_names_remain_methods_but_are_valid_keys():
    defaults = {name: f'field-{name}' for name in MAPPING_NAMES}

    class MappingCollisionConfig(kwconf.Config):
        __default__ = defaults

    cfg = MappingCollisionConfig()

    for name, expected in defaults.items():
        assert cfg[name] == expected
        assert callable(getattr(cfg, name))
        assert callable(getattr(cfg, '_' + name))

    assert dict(cfg) == defaults
    assert set(cfg.keys()) == set(defaults)
    assert dict(cfg.items()) == defaults
    assert list(cfg.values()) == list(defaults.values())
    assert cfg.get('keys') == 'field-keys'
    assert cfg.copy() == defaults

    cfg.update({'get': 'changed'})
    assert cfg['get'] == 'changed'
    cfg.keys = 'changed-keys'
    assert cfg['keys'] == 'changed-keys'
    assert callable(cfg.keys)

    with pytest.raises(TypeError):
        cfg.pop('keys')
    with pytest.raises(TypeError):
        cfg.popitem()
    with pytest.raises(TypeError):
        cfg.clear()


def test_dataconf_uses_the_same_collision_policy():
    @kwconf.dataconf
    class CollisionConfig:
        validate: bool = False
        cli: str = 'field-cli'
        load: str = 'field-load'
        namespace: str = 'field-namespace'
        keys: str = 'field-keys'

    cfg = CollisionConfig()

    assert cfg.validate is False
    assert cfg.cli == 'field-cli'
    assert cfg.load == 'field-load'
    assert cfg.namespace == 'field-namespace'
    assert cfg['keys'] == 'field-keys'
    assert callable(cfg.keys)

    CollisionConfig.validate()
    assert CollisionConfig.cli(argv=False).cli == 'field-cli'
    cfg._load({'load': 'changed'}, argv=False)
    assert cfg.load == 'changed'
    assert isinstance(cfg._namespace, argparse.Namespace)


def test_typed_class_attribute_collisions_follow_the_same_policy():
    class CollisionConfig(kwconf.Config):
        validate: bool = False
        cli: str = 'field-cli'
        load: str = 'field-load'
        keys: str = 'field-keys'

    cfg = CollisionConfig()
    assert cfg.validate is False
    assert cfg.cli == 'field-cli'
    assert cfg.load == 'field-load'
    assert cfg['keys'] == 'field-keys'
    assert callable(cfg.keys)

    CollisionConfig.validate()
    assert CollisionConfig.cli(argv=False).cli == 'field-cli'
    assert CollisionConfig.cli(argv=['--validate']).validate is True
    assert CollisionConfig.cli(
        data={'validate': True}, argv=False
    ).validate is True
    cfg._load({'load': 'changed'}, argv=False)
    assert cfg.load == 'changed'


def test_config_ingestion_uses_private_asdict_when_public_name_is_a_field():
    from kwconf._ingest import coerce_mapping_source

    class Inner(kwconf.Config):
        value: int = 1

    class Source(kwconf.Config):
        asdict: str = 'field-asdict'
        inner = kwconf.SubConfig(Inner)

    payload = coerce_mapping_source(Source())
    assert payload['asdict'] == 'field-asdict'
    assert payload['inner']['value'] == 1
    assert isinstance(payload['inner'], dict)


def test_subclass_operation_overrides_update_private_aliases():
    class CustomConfig(kwconf.Config):
        value: int = 1

        @classmethod
        def cli(cls, *args, **kwargs):
            return 'custom-cli'

        def asdict(self):
            return {'custom': self['value']}

        def dump(self, stream=None, mode=None):
            text = f'custom:{self["value"]}'
            if stream is not None:
                stream.write(text)
            return text

    assert CustomConfig.from_cli(argv=False) == 'custom-cli'

    cfg = CustomConfig(value=3)
    assert cfg.to_dict() == {'custom': 3}
    assert cfg.dumps() == 'custom:3'
    assert inspect.getattr_static(
        CustomConfig, '_cli'
    ) is inspect.getattr_static(CustomConfig, 'cli')
    assert inspect.getattr_static(
        CustomConfig, '_asdict'
    ) is inspect.getattr_static(CustomConfig, 'asdict')
    assert inspect.getattr_static(
        CustomConfig, '_dump'
    ) is inspect.getattr_static(CustomConfig, 'dump')


def test_ingestion_ignores_unrelated_mapping_private_asdict():
    from kwconf._ingest import coerce_mapping_source

    class ForeignMapping(dict):
        def _asdict(self, required_argument):
            raise AssertionError('unrelated private method must not be called')

    source = ForeignMapping(value=3)
    assert coerce_mapping_source(source) == {'value': 3}


def test_nested_cli_uses_private_argparse_operation():
    class Inner(kwconf.Config):
        argparse: str = 'field-argparse'
        depth: int = 1

    class Outer(kwconf.Config):
        inner = kwconf.SubConfig(Inner)

    cfg = Outer.cli(argv=['--inner.depth=3'])
    assert cfg.inner.argparse == 'field-argparse'
    assert cfg.inner.depth == 3


def test_modal_cli_uses_private_config_argparse_operation():
    class Command(kwconf.Config):
        argparse: str = 'field-argparse'
        value: str = 'default'

        @classmethod
        def main(cls, argv=False, **kwargs):
            return cls._cli(argv=argv, data=kwargs)

    class Root(kwconf.ModalCLI):
        command = Command

    parser = Root().argparse()
    action = parser._subparsers._group_actions[0]
    assert 'command' in action.choices

    cfg = Root.main(
        argv=['command', '--value=changed'], strict=True, _noexit=True
    )
    assert cfg.argparse == 'field-argparse'
    assert cfg.value == 'changed'
