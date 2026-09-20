# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
"""
Test that we can play very nicely with argparse
"""

import argparse
from pathlib import Path


def setup_args1():
    parser = argparse.ArgumentParser(
        description='Description 1',
    )

    # Configuration
    parser.add_argument(
        '--config', '-c', type=Path, help='Path to configuration YAML file'
    )

    parser.add_argument(
        '--output-dir', '-o', type=Path, help='Output directory'
    )
    return parser


def setup_args2():
    parser = argparse.ArgumentParser(
        description='Description 2',
    )

    # Input data
    parser.add_argument(
        'input_dir', type=Path, help='Directory containing the input'
    )

    parser.add_argument(
        '--option',
        type=str,
        choices=['value1', 'value2'],
        help='Some option',
    )
    return parser


def main1():
    parser = setup_args1()
    args = parser.parse_args()
    print(f'args={args}')


def main2():
    parser = setup_args2()
    args = parser.parse_args()
    print(f'args={args}')


def build_modal():
    from kwconf.modal import ModalCLI

    modal = ModalCLI()

    import kwconf

    # FIXME: doesn't work when you use Config instead of Config.
    cli1 = kwconf.Config.cls_from_argparse(setup_args1(), name='mode1')
    cli1.main = main2  # ty: ignore[unresolved-attribute]

    cli2 = kwconf.Config.cls_from_argparse(setup_args2(), name='mode2')
    cli2.main = main2  # ty: ignore[unresolved-attribute]

    modal.register(cli1)
    modal.register(cli2)
    return modal


def test_argparse_playnice():
    """ """
    modal = build_modal()
    parser = modal.argparse()
    parser.print_usage()


if __name__ == '__main__':
    """
    CommandLine:
        python ~/code/kwconf/tests/test_argparse_integration.py
    """
    build_modal().main()


def test_positional_order_follows_position_not_declaration():
    """
    ``position=`` must control positional binding order even when fields are
    declared out of order (the sorted key order used to be computed but never
    applied to the build loop).
    """
    import kwconf

    class C(kwconf.Config):
        second = kwconf.Value(None, position=2)
        first = kwconf.Value(None, position=1)

    cfg = C.cli(argv=['AAA', 'BBB'])
    assert cfg['first'] == 'AAA'
    assert cfg['second'] == 'BBB'


def test_kwconf_ordinary_fields_share_one_argparse_action_class():
    """Parser fields carry per-field state on instances, not dynamic classes."""
    import kwconf
    from kwconf import value as value_mod

    class C(kwconf.Config):
        count = kwconf.Value(0, parser=int)
        name = kwconf.Value('', parser=str)

    parser = C().argparse()
    actions = {
        action.dest: action
        for action in parser._actions
        if action.dest in {'count', 'name'}
    }
    assert type(actions['count']) is value_mod._SmartParseAction
    assert type(actions['name']) is value_mod._SmartParseAction
    assert (
        actions['count']._kwconf_template
        is not actions['name']._kwconf_template
    )
    # The shared action's public ``type`` callable must not point back to the
    # action itself. argparse includes ``type`` in Action.__repr__, so a bound
    # action method would recurse forever here.
    assert '_SmartParseAction' in repr(actions['count'])
    assert '_SmartParseAction' in repr(actions['name'])

    parsed = parser.parse_args(['--count=3', '--name=alice'])
    assert parsed.count == 3
    assert parsed.name == 'alice'


def test_port_from_kwconf_parser_hides_internal_smart_coercer():
    """Round-tripping a live kwconf parser must expose public field metadata."""
    import kwconf

    class C(kwconf.Config):
        plain = kwconf.Value(None, group='group-a')
        count = kwconf.Value(0, type=int, mutex_group='mutex-a')
        other = kwconf.Value(None, mutex_group='mutex-a')

    parser = C().argparse()
    text = C.port_from_argparse(parser)

    assert '_SmartValueCoercer' not in text
    assert 'plain = kwconf.Value(None' in text
    assert 'group="\'group-a\'"' in text
    assert 'count = kwconf.Value(0, type=int' in text

    namespace = {}
    exec(text, namespace, namespace)
    Ported = namespace['MyConfig']
    reparsed = Ported.cli(argv=['--count=3'])
    assert reparsed.count == 3
