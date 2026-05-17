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

class C(kw.DataConfig):
    mode: typing.Literal['x', 'y'] = 'x'
""",
        ns,
    )
    C = ns['C']
    assert C.__default__['mode'].type is str
    assert list(C.__default__['mode'].parsekw['choices']) == ['x', 'y']


def test_annotations_helpers_do_not_break_forward_refs():
    class C(kw.DataConfig):
        node: 'NotYetDefined' = None  # noqa: F821

    template = C.__default__['node']
    assert getattr(template, '_annotation', None) in {'NotYetDefined', None}
