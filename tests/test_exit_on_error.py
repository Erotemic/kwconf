"""
Tests for exit_on_error semantics on the extended parsers.
"""

import argparse

import pytest

from kwconf.argparse_ext import CompatArgumentParser, ExtendedArgumentParser


@pytest.mark.parametrize(
    'parser_cls', [CompatArgumentParser, ExtendedArgumentParser]
)
def test_exit_on_error_false_is_honored(parser_cls):
    """
    exit_on_error=False must survive construction (modern argparse re-sets
    the attribute in its own __init__) and turn parse errors into
    ArgumentError instead of SystemExit.
    """
    parser = parser_cls(exit_on_error=False)
    assert parser.exit_on_error is False

    parser.add_argument('--num', type=int)
    with pytest.raises(argparse.ArgumentError):
        parser.parse_known_args(['--num', 'bad'])


@pytest.mark.parametrize(
    'parser_cls', [CompatArgumentParser, ExtendedArgumentParser]
)
def test_exit_on_error_defaults_true(parser_cls):
    parser = parser_cls()
    assert parser.exit_on_error is True
    parser.add_argument('--num', type=int)
    with pytest.raises(SystemExit):
        parser.parse_args(['--num', 'bad'])


def test_intercepted_error_names_the_argument(capsys):
    """
    The intercepted usage error must keep argparse's "argument --name:"
    prefix so the user can tell which of several options failed.
    """
    parser = ExtendedArgumentParser()
    parser.add_argument('--num', type=int)
    parser.add_argument('--other', type=int)

    with pytest.raises(SystemExit):
        parser.parse_args(['--num', 'bad'])
    err = capsys.readouterr().err
    assert 'argument --num:' in err


def test_extended_parse_args_restores_exit_on_error(capsys):
    """
    A successful parse_args must not permanently flip exit_on_error off:
    a reused parser has to keep the SystemExit+usage policy on later parses.
    """
    parser = ExtendedArgumentParser()
    parser.add_argument('--num', type=int)

    parser.parse_args(['--num', '1'])
    assert parser.exit_on_error is True

    with pytest.raises(SystemExit):
        parser.parse_args(['--num', 'bad'])
    assert parser.exit_on_error is True
    # And the usage policy actually printed an error message.
    assert 'invalid int value' in capsys.readouterr().err
