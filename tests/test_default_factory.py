# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
"""
``default_factory`` is deferred: the factory is never invoked at
class-definition time. It is materialized lazily on first read of a template's
``.value`` (and cached there), while each Config instance receives its own
fresh value via ``clone_default``.
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
