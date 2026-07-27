# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
"""
``default_factory`` is deferred: the factory is never invoked at
class-definition time. It is materialized lazily on first read of a class
template's ``.value`` (and cached there), while Config construction and reset
invoke the recipe directly for a fresh runtime value.
"""

import copy

import kwconf


def test_factory_not_called_at_class_definition():
    calls = []

    def factory():
        calls.append(1)
        return ['fresh']

    class C(kwconf.Config):
        tags: list = kwconf.Value(default_factory=factory)

    # Defining the class must not run the factory.
    assert calls == []
    # Instantiating does (once, for that instance's value).
    C()
    assert len(calls) == 1


def test_per_instance_values_are_not_shared():
    class C(kwconf.Config):
        tags: list = kwconf.Value(default_factory=list)

    a = C()
    b = C()
    a['tags'].append('x')
    assert a['tags'] == ['x']
    assert b['tags'] == []
    assert a['tags'] is not b['tags']


def test_template_value_materializes_lazily_and_caches():
    class C(kwconf.Config):
        tags: list = kwconf.Value(default_factory=list)

    template = C.__default__['tags']
    first = template.value
    assert first == []
    # Cached: same object on repeated template access.
    assert template.value is first


def test_unmaterialized_template_survives_deepcopy():
    # The sentinel must be copy/deepcopy-safe so a not-yet-read factory
    # template still materializes correctly after copying.
    class C(kwconf.Config):
        tags: list = kwconf.Value(default_factory=list)

    template = C.__default__['tags']
    dup = copy.deepcopy(template)
    assert dup.value == []


def test_explicit_value_assignment_overrides_factory():
    v = kwconf.Value(default_factory=list)
    v.value = [1, 2, 3]
    assert v.value == [1, 2, 3]


def test_factory_field_round_trips_through_cli():
    class C(kwconf.Config):
        tags: list = kwconf.Value(default_factory=list, nargs='+')

    assert C.cli(argv=[])['tags'] == []
    assert C.cli(argv=['--tags', 'a', 'b'])['tags'] == ['a', 'b']


def test_cli_instances_do_not_share_factory_default():
    """
    The argv-defaults merge must store per-instance defaults, not the class
    template's (cached) factory output.
    """
    import kwconf

    class C(kwconf.Config):
        tags: list = kwconf.Value(default_factory=list)

    c1 = C.cli(argv=[])
    c2 = C.cli(argv=[])
    assert c1['tags'] is not c2['tags']
    c1['tags'].append('x')
    assert c2['tags'] == []
    assert C.cli(argv=[])['tags'] == []


def test_cli_instance_mutation_does_not_corrupt_class_default():
    import kwconf

    class D(kwconf.Config):
        items = kwconf.Value(['a'])

    d1 = D.cli(argv=[])
    d1['items'].append('MUT')
    assert D.cli(argv=[])['items'] == ['a']
    assert D.__default__['items'].value == ['a']


def test_noncopyable_factory_output_is_supported_and_recreated_on_reset():
    import threading

    calls = []

    def make_lock():
        calls.append(1)
        return threading.Lock()

    class C(kwconf.Config):
        lock = kwconf.Value(default_factory=make_lock)

    cfg = C()
    first = cfg.lock
    assert len(calls) == 1

    cfg.load(argv=False)
    assert len(calls) == 2
    assert cfg.lock is not first
