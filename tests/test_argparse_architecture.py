import argparse
import inspect

import kwconf
from kwconf import argparse_ext


def test_kwconf_actions_use_public_argparse_action_base():
    assert issubclass(argparse_ext.BooleanFlagOrKeyValAction, argparse.Action)
    assert argparse._StoreAction not in (
        argparse_ext.BooleanFlagOrKeyValAction.__mro__
    )

    class Demo(kwconf.Config):
        count = kwconf.Value(0, type=int)

    parser = Demo().argparse()
    action = next(a for a in parser._actions if a.dest == 'count')
    assert isinstance(action, argparse.Action)
    assert argparse._StoreAction not in type(action).__mro__


def test_extended_parser_does_not_override_private_parse_engine():
    assert '_parse_optional' not in argparse_ext.ExtendedArgumentParser.__dict__
    assert (
        '_get_option_tuples' not in argparse_ext.ExtendedArgumentParser.__dict__
    )
    source = inspect.getsource(argparse_ext.ExtendedArgumentParser)
    assert 'def _parse_optional' not in source
    assert 'def _get_option_tuples' not in source


def test_parser_reuse_has_parse_local_provenance_and_clean_namespaces():
    class Demo(kwconf.Config):
        number = kwconf.Value(0, type=int)

    parser = Demo().argparse()
    first = parser.parse_known_result(['--number=3'])
    second = parser.parse_known_result([])

    assert first.explicit_keys == frozenset({'number'})
    assert second.explicit_keys == frozenset()
    assert vars(first.namespace) == {'number': 3}
    assert vars(second.namespace) == {'number': 0}

    ordinary = parser.parse_args(['--number=4'])
    assert vars(ordinary) == {'number': 4}


def test_fuzzy_normalization_respects_end_of_options_separator():
    parser = argparse_ext.ExtendedArgumentParser()
    parser.add_argument('--my-option')
    parser.add_argument('rest', nargs='*')

    namespace = parser.parse_args(['--', '--my_option=value'])
    assert namespace.my_option is None
    assert namespace.rest == ['--my_option=value']


def test_plain_argparse_parser_reuse_resets_kwconf_provenance():
    import argparse

    from kwconf import argparse_ext

    parser = argparse.ArgumentParser()
    parser.add_argument('--flag', action=argparse_ext.BooleanFlagOrKeyValAction)

    first = argparse_ext.parse_known_result(parser, ['--flag'])
    second = argparse_ext.parse_known_result(parser, [])

    assert first.explicit_keys == frozenset({'flag'})
    assert second.explicit_keys == frozenset()
    assert vars(second.namespace) == {'flag': None}


def test_plain_argparse_subparser_provenance_uses_namespace_fallback():
    import argparse

    from kwconf import argparse_ext

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command')
    child = subparsers.add_parser('run')
    child.add_argument('--flag', action=argparse_ext.BooleanFlagOrKeyValAction)

    result = argparse_ext.parse_known_result(parser, ['run', '--flag'])

    assert result.explicit_keys == frozenset({'flag'})
    assert vars(result.namespace) == {'command': 'run', 'flag': True}
