# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
"""
Corner cases surfaced while refreshing the manual (coercion_and_cli,
core_contract, migration). These pin down behavior the docs now promise so the
prose cannot silently drift from the runtime again.
"""

import os

import pytest

import kwconf


# --------------------------------------------------------------------------
# The ``parser=list`` footgun (the old docs recommended ``type=list``).
# --------------------------------------------------------------------------
def test_parser_list_callable_is_a_footgun():
    # Passing the builtin ``list`` as a parser does NOT build a list from a
    # comma string -- it splits the string into characters. The docs steer
    # users to csv/yaml/nargs instead; this test documents why.
    assert kwconf.Value(None, parser=list).coerce('1,2,3') == [
        '1',
        ',',
        '2',
        ',',
        '3',
    ]


def test_csv_is_the_comma_list_tool():
    # The correct replacement for the old ``type=list`` comma form.
    assert kwconf.Value(None, parser='csv').coerce('1,2,3') == [1, 2, 3]


def test_yaml_is_the_structured_tool():
    pytest.importorskip('yaml')
    assert kwconf.Value(None, parser='yaml').coerce('[1, 2, 3]') == [1, 2, 3]


# --------------------------------------------------------------------------
# Public subclassing surface: ``ValueClass`` / ``FlagClass``.
# The public ``Value``/``Flag`` are typed factory *functions* and cannot be
# subclassed; the docs now point reusable-subclass authors at these aliases.
# --------------------------------------------------------------------------
def test_value_and_flag_classes_are_exported():
    import inspect

    assert inspect.isclass(kwconf.value._Value)
    assert inspect.isclass(kwconf.value._Flag)
    assert issubclass(kwconf.value._Flag, kwconf.value._Value)


def test_valueclass_is_subclassable_for_custom_coerce():
    # The migration guide's "roll your own Path" recipe.
    class Path(kwconf.value._Value):
        def __init__(self, value=None, **kw):
            super().__init__(value, parser=str, **kw)

        def coerce(self, value):
            if isinstance(value, str):
                value = os.path.expanduser(value)
            return value

    assert Path().coerce('~/x') == os.path.expanduser('~/x')


def test_valueclass_subclass_usable_as_a_field():
    class Path(kwconf.value._Value):
        def __init__(self, value=None, **kw):
            super().__init__(value, parser=str, **kw)

        def coerce(self, value):
            if isinstance(value, str):
                value = os.path.expanduser(value)
            return value

    class C(kwconf.Config):
        out = Path('~/out')

    assert C.cli(argv=['--out=~/elsewhere'])['out'] == os.path.expanduser(
        '~/elsewhere'
    )
