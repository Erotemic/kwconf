import pytest

import kwconf
from kwconf.modal import NoCommandError


class Leaf(kwconf.Config):
    @classmethod
    def main(cls, argv=None, **kwargs):
        return 0


class Child(kwconf.ModalCLI):
    leaf = Leaf


class Root(kwconf.ModalCLI):
    child = Child
    leaf = Leaf


def test_root_no_command_has_stable_usage_and_structured_error(capsys):
    with pytest.raises(NoCommandError) as exc_info:
        Root.main(argv=[])

    error = exc_info.value
    assert error.code == 1
    assert error.message == 'Root: error: no command was given'
    assert str(error) == error.message
    assert error.parser.prog == 'Root'

    stderr = capsys.readouterr().err
    assert stderr.startswith('usage: Root ')
    assert stderr.rstrip().endswith(error.message)
    assert 'submodal CLI' not in stderr


def test_nested_no_command_uses_selected_command_path(capsys):
    with pytest.raises(NoCommandError) as exc_info:
        Root.main(argv=['child'])

    error = exc_info.value
    assert error.code == 1
    assert error.message == 'Root child: error: no command was given'
    assert error.parser.prog == 'Root child'

    stderr = capsys.readouterr().err
    assert stderr.startswith('usage: Root child ')
    assert stderr.rstrip().endswith(error.message)


def test_noexit_returns_the_numeric_status(capsys):
    assert Root.main(argv=[], _noexit=True) == 1
    assert Root.main(argv=['child'], _noexit=True) == 1
    stderr = capsys.readouterr().err
    assert 'Root: error: no command was given' in stderr
    assert 'Root child: error: no command was given' in stderr
