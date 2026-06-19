# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
"""
Parsers are either annotation-aware or not. ``auto`` and ``csv`` are aware (they
steer the produced type by the field annotation); ``yaml`` is unaware. Custom
parsers opt in via ``register_parser(..., annotation_aware=True)``.

``csv`` is ``auto`` mapped over the comma-split, gated by the container's
element annotation.
"""
import pytest
import kwconf
from kwconf.coerce import coerce, register_parser, element_annotation, auto


def test_csv_respects_element_annotation():
    class C(kwconf.Config):
        tags: list[str] = kwconf.Value(default_factory=list, parser='csv')

    # Without element gating this would be [1, 2, '3o'].
    assert C.cli(argv=['--tags', '1,2,3o'])['tags'] == ['1', '2', '3o']


def test_csv_parses_int_elements():
    class C(kwconf.Config):
        nums: list[int] = kwconf.Value(default_factory=list, parser='csv')

    assert C.cli(argv=['--nums', '1,2,3'])['nums'] == [1, 2, 3]


def test_csv_union_element_annotation():
    class C(kwconf.Config):
        mixed: list[int | str] = kwconf.Value(default_factory=list, parser='csv')

    # int wins where it can, str catches the rest.
    assert C.cli(argv=['--mixed', '1,2,3o'])['mixed'] == [1, 2, '3o']


def test_csv_without_annotation_is_full_auto():
    # Backward compatible: bare csv (no/Any annotation) parses each element
    # with full auto precedence.
    assert coerce('1,2,3', spec='csv') == [1, 2, 3]
    assert coerce('a,b,c', spec='csv') == ['a', 'b', 'c']


def test_yaml_stays_annotation_blind():
    # __validate__=False isolates parsing behavior from the validation layer
    # (which, on by default, would separately warn about the list mismatch).
    class C(kwconf.Config):
        __validate__ = False
        data: list = kwconf.Value(default_factory=list, parser='yaml')

    # yaml produces its own typed structure regardless of the annotation.
    assert C.cli(argv=['--data', 'just-a-string'])['data'] == 'just-a-string'
    assert C.cli(argv=['--data', '[1, 2, 3]'])['data'] == [1, 2, 3]


def test_yaml_mismatch_warns_via_validation_layer():
    # The flip side: with validation on (the default), yaml producing a value
    # that doesn't match the annotation is reported by the single validation
    # voice -- this is what makes warnings consistent across parsers.
    class C(kwconf.Config):
        data: list = kwconf.Value(default_factory=list, parser='yaml')

    with pytest.warns(UserWarning, match='does not match annotation'):
        cfg = C.cli(argv=['--data', 'just-a-string'])
    assert cfg['data'] == 'just-a-string'


def test_register_custom_annotation_aware_parser():
    def head_csv(token, annotation):
        elem = element_annotation(annotation)
        return [auto(p, elem) for p in token.split(',')][:1]

    register_parser('head_csv', head_csv, annotation_aware=True)
    assert coerce('1,2,3', annotation=list[str], spec='head_csv') == ['1']
    # The element annotation reached the custom parser (kept as str).


def test_register_unaware_parser_keeps_single_arg_contract():
    calls = []

    def shouty(token):
        calls.append(token)
        return token.upper()

    register_parser('shouty', shouty)  # annotation_aware defaults to False
    # Must be called with a single argument; annotation is not forwarded.
    assert coerce('hi', annotation=str, spec='shouty') == 'HI'
    assert calls == ['hi']
