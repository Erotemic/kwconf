from __future__ import annotations

import typing

import kwconf as kw
from kwconf import annotations as ann


def test_annotations_helpers_infer_literal_and_optional():
    annotation = typing.Optional[typing.Literal['a', 'b']]
    assert ann.choices_from_annotation(annotation) == ('a', 'b')
    assert ann.runtime_type_from_annotation(annotation) is str
    assert ann.value_matches_annotation('a', annotation)
    assert ann.value_matches_annotation(None, annotation)
    assert not ann.value_matches_annotation('c', annotation)


def test_annotations_helpers_resolve_future_annotations():
    ns = {}
    exec(
        """
from __future__ import annotations
import typing
import kwconf as kw

class C(kw.Config):
    mode: typing.Literal['x', 'y'] = 'x'
""",
        ns,
    )
    C = ns['C']
    assert C.__default__['mode'].type is str
    assert list(C.__default__['mode'].parsekw['choices']) == ['x', 'y']


def test_annotations_helpers_do_not_break_forward_refs():
    class C(kw.Config):
        node: 'NotYetDefined' = None  # noqa: F821

    template = C.__default__['node']
    assert getattr(template, '_annotation', None) in {'NotYetDefined', None}


def test_choices_literal_or_str_union_is_unrestricted():
    """
    ``Literal[...] | str`` admits any string: the CLI must not restrict the
    field to the literal values.
    """
    import typing

    from kwconf import annotations as ann

    assert ann.choices_from_annotation(typing.Literal['a', 'b'] | str) is None

    class C(kw.Config):
        mode: typing.Literal['a', 'b'] | str = 'a'

    cfg = C.cli(argv=['--mode', 'custom'])
    assert cfg['mode'] == 'custom'
    cfg = C.cli(argv=['--mode', 'a'])
    assert cfg['mode'] == 'a'


def test_choices_union_of_literals_combines():
    """A union of Literals exposes every member's values as choices."""
    import typing

    from kwconf import annotations as ann

    annotation = typing.Literal['a'] | typing.Literal['b']
    assert ann.choices_from_annotation(annotation) == ('a', 'b')
