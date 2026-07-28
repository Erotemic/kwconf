# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
import kwconf


def test_dataconfig_setattr_simple():
    import pytest

    class ExampleConfig(kwconf.Config):
        x: int = 0
        y: str = '3'

    self = ExampleConfig()

    print(f'self.__dict__={self.__dict__}')
    print(f'self.x={self.x}')
    new_val = 432
    self['x'] = new_val
    assert 'x' not in self.__dict__
    assert self['x'] == new_val
    assert self.x == new_val

    new_val = 433
    self.x = new_val
    assert 'x' not in self.__dict__
    assert self['x'] == new_val
    assert self.x == new_val

    new_val = 434
    self['x'] = new_val
    assert 'x' not in self.__dict__
    assert self['x'] == new_val
    assert self.x == new_val

    new_val = 435
    self.x = new_val
    assert 'x' not in self.__dict__
    assert self['x'] == new_val
    assert self.x == new_val

    # self.notakey
    with pytest.raises(AttributeError):
        self.notakey
    self.notakey = 100
    assert 'notakey' not in self
    assert 'notakey' in self.__dict__
    with pytest.raises(KeyError):
        self['notakey']
    assert self.notakey == 100


def test_dataconfig_setattr_combos():

    class ExampleConfig(kwconf.Config):
        x: int = 0
        y: str = '3'

    self = ExampleConfig()

    def setmethod_item(self, key, value):
        # Test setting the value by using __setitem__
        self[key] = value

    def setmethod_attr(self, key, value):
        # Test setting the value by using __setattr__
        setattr(self, key, value)

    def getmethod_item(self, key):
        return self[key]

    def getmethod_attr(self, key):
        return getattr(self, key)

    import itertools as it

    import ubelt as ub

    grid = list(
        ub.named_product(
            {
                'key': ['x'],
                'setmethod': [setmethod_item, setmethod_attr],
                'getmethod': [getmethod_item, getmethod_attr],
            }
        )
    )
    tasks = list(ub.flatten(it.permutations(grid, len(grid))))
    for new_value, task in enumerate(tasks, start=101):
        task['new_value'] = new_value

    for task in tasks:
        key = task['key']
        setmethod = task['setmethod']
        getmethod = task['getmethod']
        new_val = task['key']
        old_val = getmethod(self, key)
        assert new_val != old_val
        assert key in self
        assert key not in self.__dict__
        setmethod(self, key, new_value)
        assert getmethod(self, key) == new_value
        assert key in self
        assert key not in self.__dict__


def test_dataconfig_warning():
    """
    Test that the user gets a warning if they make this common mistake
    """
    import pytest

    import kwconf

    with pytest.warns(Warning):

        class ExampleConfig(kwconf.Config):
            x = (kwconf.Value(None),)


def test_dataconfig_with_funcs():
    import kwconf

    class MyConfig(kwconf.Config):
        __default__ = {
            'a': 1,
            'b': 1,
        }

        def c(self): ...

        @staticmethod
        def d(): ...

        @classmethod
        def e(cls): ...

        f = lambda x: None  # NOQA

    assert callable(MyConfig.c)
    assert callable(MyConfig.f)
    assert callable(MyConfig.e)
    assert callable(MyConfig.d)
    assert not hasattr(MyConfig, 'a')
    assert not hasattr(MyConfig, 'b')
    assert 'e' not in MyConfig.__default__


def test_dataconfig_docstring():
    import kwconf

    class MyConfig1(kwconf.Config): ...

    class MyConfig2(kwconf.Config):
        """
        Hello World
        """

        ...

    assert MyConfig1.__description__ is None

    self1 = MyConfig1()
    self2 = MyConfig2()
    assert self1._description is not None
    # No docstring -> diagnostic fallback naming the missing class.
    assert 'no description for' in self1._description
    assert 'MyConfig1' in self1._description
    assert self2._description == 'Hello World'


def test_config_is_typed_first_too():
    class MyConfig(kwconf.Config):
        x: int = 0
        y: str = '3'

    cfg = MyConfig()
    assert cfg.x == 0
    cfg.x = 10
    assert cfg['x'] == 10


def test_value_default_factory():
    class MyConfig(kwconf.Config):
        tags: list[str] = kwconf.Value(default_factory=list)

    cfg1 = MyConfig()
    cfg2 = MyConfig()
    cfg1.tags.append('alpha')
    assert cfg1.tags == ['alpha']
    assert cfg2.tags == []


def test_dataconf_preserves_hooks_and_helpers():
    """@dataconf on a plain class must keep dunder hooks (__post_init__,
    __validate__) and underscore helpers, not silently drop them."""
    hits = []

    @kwconf.dataconf
    class C:
        x: int = 1

        def __post_init__(self):
            hits.append(self.x)

        def _helper(self):
            return 'helped'

    c = C(x=5)
    assert hits == [5]
    assert c._helper() == 'helped'


def test_dataconf_inherits_fields_from_plain_base():
    """@dataconf must pick up fields inherited from plain (non-Config) base
    classes via the MRO, not just the decorated class's own namespace."""

    class Base:
        base_field: int = 10

    @kwconf.dataconf
    class Child(Base):
        child_field: int = 20

    cfg = Child()
    assert set(cfg.keys()) == {'base_field', 'child_field'}
    assert cfg.base_field == 10
    assert cfg.child_field == 20

    # Subclass field overrides the base default.
    class Base2:
        val: int = 1

    @kwconf.dataconf
    class Child2(Base2):
        val: int = 2

    assert Child2().val == 2


def test_dataconf_does_not_replace_config_init_with_user_init():
    calls = []

    @kwconf.dataconf
    class C:
        x: int = 1

        def __init__(self, x=99):
            calls.append(x)

    cfg = C(x=3)
    assert cfg.asdict() == {'x': 3}
    assert calls == []


def test_dataconf_accepts_a_stdlib_dataclass_input():
    import dataclasses

    @kwconf.dataconf
    @dataclasses.dataclass
    class C:
        x: int = 1
        label: str = 'demo'

    cfg = C(2, label='changed')
    assert cfg.asdict() == {'x': 2, 'label': 'changed'}
