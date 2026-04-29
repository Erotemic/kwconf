"""
Tests for porting back and forth to / from argparse.

These tests focus on stable structural properties of the generated source
code (key calls, argument order) rather than full-text matches that would
break for incidental changes (description, version banners, etc).
"""
import argparse

import kwconf


def _normalize_lines(text):
    """Split into lines and drop blank/trailing whitespace lines."""
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def test_port_kwconf_from_argparse():
    parser = argparse.ArgumentParser()
    parser.add_argument('--flag1', action='count')
    parser.add_argument('--flag2', action='store_true')
    parser.add_argument('--flag3', action='count',
                        help='specified looooooooooooooooooooooonggg help ')
    parser.add_argument('--flag4', action='store_true', help='specified help')

    text = kwconf.Config.port_from_argparse(parser)

    # Structural assertions: each argparse field becomes a kwconf.Value.
    assert 'class MyConfig(kwconf.DataConfig):' in text
    assert "flag1 = kwconf.Value(None, isflag='counter'" in text
    assert 'flag2 = kwconf.Value(False, isflag=True' in text
    assert "flag3 = kwconf.Value(None, isflag='counter'" in text
    assert 'flag4 = kwconf.Value(False, isflag=True' in text
    assert "help='specified help'" in text

    # The generated module should be runnable.
    ns = {}
    exec(text, ns, ns)
    cls = ns['MyConfig']
    instance = cls()
    # The ported config should expose the same fields.
    assert set(instance.keys()) == {'flag1', 'flag2', 'flag3', 'flag4'}


def test_port_argparse_from_kwconf():
    class MyConfig(kwconf.Config):
        param1 = kwconf.Value(None, type=str, help='help text')

    argparse_text = MyConfig().port_to_argparse()

    # Structural assertions: just check the parser is built and the field
    # is registered with the expected metadata.
    assert 'import argparse' in argparse_text
    assert 'parser = argparse.ArgumentParser(' in argparse_text
    assert "formatter_class=argparse.RawDescriptionHelpFormatter," in argparse_text
    assert "parser.add_argument('--param1'" in argparse_text
    assert "help='help text'" in argparse_text
    assert "type=str" in argparse_text


def test_port_argparse_from_kwconf_with_unwrapped_values():
    class MyConfig(kwconf.Config):
        option1 = kwconf.Value('default1', help='option1 help')
        option2 = kwconf.Value('default2', help='option2 help')
        option3 = kwconf.Value('default3', help='option3 help')
        option4 = 'default4'

    argparse_text = MyConfig().port_to_argparse()

    # Each field must produce one add_argument call with the right defaults.
    expected_lines = [
        "parser.add_argument('--option1', help='option1 help', default='default1', dest='option1', required=False)",
        "parser.add_argument('--option2', help='option2 help', default='default2', dest='option2', required=False)",
        "parser.add_argument('--option3', help='option3 help', default='default3', dest='option3', required=False)",
        "parser.add_argument('--option4', help='', default='default4', dest='option4', required=False)",
    ]
    actual_lines = _normalize_lines(argparse_text)
    for line in expected_lines:
        assert line in actual_lines, f'missing line: {line}'

    # And the generated source should execute and behave correctly.
    ns = {}
    exec(argparse_text, ns, ns)
    parser = ns['parser']
    args = parser.parse_args(['--option1=ALT', '--option3=ALT3'])
    assert args.option1 == 'ALT'
    assert args.option2 == 'default2'
    assert args.option3 == 'ALT3'
    assert args.option4 == 'default4'


def test_port_argparse_with_optin_fancy_features():
    class MyConfig(kwconf.Config):
        my_flag = kwconf.Value(False, isflag=True)
        my_counter = kwconf.Value(0, isflag='counter')
        my_option = kwconf.Value('default')

    argparse_text = MyConfig().port_to_argparse(
        fuzzy_hyphens=True, flag_value_mode=True)
    assert 'from kwconf' not in argparse_text
    assert '--my-option' in argparse_text
    assert '_PortedBooleanFlagOrKeyValAction' in argparse_text
    assert '_PortedCounterOrKeyValAction' in argparse_text

    ns = {}
    exec(argparse_text, ns, ns)
    parser = ns['parser']

    args = parser.parse_args(['--my-flag'])
    assert args.my_flag is True

    args = parser.parse_args(['--my-flag=0'])
    assert args.my_flag == 0

    args = parser.parse_args(['--my_counter', '--my_counter'])
    assert args.my_counter == 2

    args = parser.parse_args(['--my_counter=5'])
    assert args.my_counter == 5

    args = parser.parse_args(['--my-option=spam'])
    assert args.my_option == 'spam'
