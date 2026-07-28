from collections import defaultdict
from typing import Any, cast

import ubelt as ub

import kwconf


def test_modal_fuzzy_hyphens():
    callnums: defaultdict[str, int] = defaultdict(lambda: 0)

    class _TestCommandTemplate(kwconf.Config):
        # not a normal pattern, just make tests more concise.
        __command__ = '_base_'
        common_option = kwconf.Flag(
            cast(Any, None), help='an option with an underscore'
        )

        @classmethod
        def main(cls, argv=None, **kwargs):
            self = cls.cli(argv=argv, data=kwargs)
            callnums[cls.__command__] += 1
            print(f'Called {cls.__command__} with: ' + str(self))

        def _parserkw(self):
            return super()._parserkw() | {'exit_on_error': False}

    class Do_Command1(_TestCommandTemplate):
        __command__ = 'do_command1'
        __aliases__ = ['do-command1']

    class Do_Command2(_TestCommandTemplate):
        __command__ = 'do_command2'
        __aliases__ = ['do-command2']

    class Do_Command3(_TestCommandTemplate):
        __command__ = 'do_command3'
        __aliases__ = ['do-command3']

    class Do_Command4(_TestCommandTemplate):
        __command__ = 'do_command4'
        __aliases__ = ['do-command4']

    class TestSubModalCLI(kwconf.ModalCLI):
        """
        Second level modal CLI
        """

        __version__ = '4.5.6'
        __command__ = 'sub_modal'
        __aliases__ = ['sub-modal']
        __subconfigs__ = [
            Do_Command3,
            Do_Command4,
        ]

        def _parserkw(self):
            return super()._parserkw() | {'exit_on_error': False}

    class TestModalCLI(kwconf.ModalCLI):
        """
        Top level modal CLI
        """

        __version__ = '1.2.3'
        __subconfigs__ = [
            Do_Command1,
            Do_Command2,
            TestSubModalCLI,
        ]

        def _parserkw(self):
            return super()._parserkw() | {'exit_on_error': False}

    try:
        TestModalCLI.main(argv=['--help'])
    except SystemExit:
        print('prevent system exit due to calling --help')

    try:
        TestModalCLI.main(argv=['sub_modal', '--help'])
    except SystemExit:
        print('prevent system exit due to calling --help')

    # Run with different variants of fuzzy hyphens

    TestModalCLI.main(argv=['sub_modal', '--version'])

    TestModalCLI.main(argv=['do_command1', '--common_option'])
    TestModalCLI.main(argv=['do_command1', '--common-option'])
    TestModalCLI.main(argv=['do_command2'])

    TestModalCLI.main(argv=['sub_modal', 'do_command3'])
    TestModalCLI.main(argv=['sub_modal', 'do_command4', '--common_option'])
    TestModalCLI.main(argv=['sub_modal', 'do_command4', '--common-option'])

    # Use hyphens in the modal commands
    print('NEW STUFF')
    TestModalCLI.main(argv=['do-command1'])

    TestModalCLI.main(argv=['sub_modal', 'do-command4', '--common-option=3'])
    TestModalCLI.main(argv=['sub-modal', 'do-command4', '--common-option=4'])

    print(f'callnums = {ub.urepr(callnums, nl=1)}')

    # Every underscore/hyphen command spelling routed to its command.
    assert callnums['do_command1'] == 3  # do_command1 x2 + do-command1
    assert callnums['do_command2'] == 1
    assert callnums['do_command3'] == 1
    assert callnums['do_command4'] == 4


def test_register_decorator_returns_class():
    """
    Using ``register`` as a decorator must leave the decorated name bound to
    the class, not None.
    """

    class MyModalCLI(kwconf.ModalCLI): ...

    @MyModalCLI.register
    class Command1(kwconf.Config):
        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs)
            return 0

    assert Command1 is not None
    assert issubclass(Command1, kwconf.Config)

    modal = MyModalCLI()

    @modal.register(command='cmd2')
    class Command2(kwconf.Config):
        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs)
            return 0

    assert Command2 is not None
    assert issubclass(Command2, kwconf.Config)

    # The registered commands still dispatch.
    assert MyModalCLI.main(argv=['Command1']) == 0
    assert modal.main(argv=['cmd2']) == 0


def test_modal_customize_command_classlevel():
    class MyModalCLI(kwconf.ModalCLI): ...

    @MyModalCLI.register(command='command1')
    class Command1(kwconf.Config):
        """The first subcommand."""

        __alias__ = [
            'alias1'
        ]  # should be used because alias not given in the decorator
        foo = kwconf.Value('spam', help='spam spam spam spam')

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs, verbose=True)

    @MyModalCLI.register(command='command2', alias=['alias2', 'alias3'])
    class Command2(kwconf.Config):
        """The second subcommand."""

        bar = 'biz'
        __alias__ = [
            'overwritten'
        ]  # wil not be used because alias is given in the decorator

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs, verbose=True)

    with ub.CaptureStdout(suppress=True) as cap:
        MyModalCLI.main(argv=['--help'], _noexit=True)
    assert cap.text is not None
    assert 'command1' in cap.text
    assert 'command2' in cap.text
    assert 'alias2' in cap.text
    assert 'alias3' in cap.text
    assert 'alias1' in cap.text
    assert 'overwritten' not in cap.text
    assert 'Command1' not in cap.text
    assert 'Command2' not in cap.text

    assert MyModalCLI.main(argv=['command1']) == 0
    assert MyModalCLI.main(argv=['command2']) == 0


def test_modal_customize_command_instancelevel():
    class MyModalCLI(kwconf.ModalCLI): ...

    modal = MyModalCLI()

    @modal.register(command='command1')
    class Command1(kwconf.Config):
        """The first subcommand."""

        __alias__ = 'alias1'
        foo = kwconf.Value('spam', help='spam spam spam spam')

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs, verbose=True)

    @modal.register(command='command2', alias=['alias2', 'alias3'])
    class Command2(kwconf.Config):
        """The second subcommand."""

        __alias__ = ['overwritten']
        bar = 'biz'

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs, verbose=True)

    with ub.CaptureStdout(suppress=False) as cap:
        modal.main(argv=['--help'], _noexit=True)
    assert cap.text is not None
    assert 'command1' in cap.text
    assert 'command2' in cap.text
    assert 'alias2' in cap.text
    assert 'alias3' in cap.text
    assert 'alias1' in cap.text
    assert 'overwritten' not in cap.text
    assert 'Command1' not in cap.text
    assert 'Command2' not in cap.text

    assert modal.main(argv=['command1']) == 0
    assert modal.main(argv=['command2']) == 0


def test_customized_modals():
    """
    We should be able to reuse the same subconfig in different modals but
    have them be under different commands.
    """

    class Modal1(kwconf.ModalCLI): ...

    class Modal2(kwconf.ModalCLI): ...

    modal1 = Modal1()
    modal2 = Modal2()

    class Command1(kwconf.Config):
        foo = kwconf.Value('spam', help='spam spam spam spam')

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs, verbose=True)

    modal1.register(Command1, command='command1')
    modal2.register(Command1, command='action1')

    with ub.CaptureStdout(suppress=False) as cap:
        try:
            modal1.main(argv=['--help'])
        except SystemExit:
            ...
        else:
            raise AssertionError('should have exited')
    assert cap.text is not None
    assert 'command1' in cap.text
    assert 'action1' not in cap.text

    with ub.CaptureStdout(suppress=False) as cap:
        modal2.main(argv=['--help'], _noexit=True)
    assert cap.text is not None
    assert 'command1' not in cap.text
    assert 'action1' in cap.text


def test_submodals():
    """
    We should be able to reuse the same subconfig in different modals but
    have them be under different commands.

    CommandLine:
        xdoctest -m tests/test_modal.py test_submodals
    """
    import kwconf
    from kwconf.modal import NoCommandError

    class Modal1(kwconf.ModalCLI): ...

    class Modal2(kwconf.ModalCLI): ...

    class Modal3(kwconf.ModalCLI): ...

    class Command(kwconf.Config):
        __command__ = 'command'
        foo = kwconf.Value('spam', help='spam spam spam spam')

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs, verbose=True)

    Modal3.register(Command, command='command4')
    Modal2.register(Modal3, command='modal3')
    Modal2.register(Command, command='command3')
    Modal1.register(Modal2, command='modal2')
    Modal1.register(Command, command='command1')
    Modal1.register(Command, command='command2')

    with ub.CaptureStdout(suppress=False) as cap:
        Modal1.main(argv=['--help'], _noexit=True)
    assert cap.text is not None
    assert 'modal2' in cap.text
    with ub.CaptureStdout(suppress=False) as cap:
        Modal1.main(argv=['modal2', '--help'], _noexit=True)
    assert cap.text is not None
    assert 'modal3' in cap.text
    with ub.CaptureStdout(suppress=False) as cap:
        Modal1.main(argv=['command1', '--help'], _noexit=True)
    assert cap.text is not None
    assert 'foo' in cap.text
    with ub.CaptureStdout(suppress=False) as cap:
        Modal1.main(argv=['modal2', 'modal3', '--help'], _noexit=True)
    assert cap.text is not None
    assert 'command4' in cap.text
    with ub.CaptureStdout(suppress=False) as cap:
        Modal1.main(argv=['modal2', 'command3', '--help'], _noexit=True)
    assert cap.text is not None
    assert 'foo' in cap.text

    assert Modal1.main(argv=['command1']) == 0

    # What happens when modals are given no args?
    try:
        Modal1.main(argv=[])
    except NoCommandError as ex:
        assert 'no command was given' in str(ex)
    else:
        assert False

    try:
        Modal1.main(argv=['modal2'])
    except NoCommandError as ex:
        assert 'no command was given' in str(ex)
    else:
        assert False

    try:
        Modal1.main(argv=['modal2', 'modal3'])
    except NoCommandError as ex:
        assert 'no command was given' in str(ex)
    else:
        assert False


def test_modal_version():
    """
    Modal CLIs should be able to cause the version to print

    CommandLine:
        KWCONF_DEBUG_MODAL=1 xdoctest -m tests/test_modal.py test_submodals
    """
    import kwconf
    # from kwconf import diagnostics
    # diagnostics.DEBUG_MODAL = 1

    class Modal1(kwconf.ModalCLI):
        __version__ = '1.1.1'

        class Modal2(kwconf.ModalCLI):
            __version__ = '2.2.2'

            class Modal3(kwconf.ModalCLI):
                __version__ = '3.3.3'

    with ub.CaptureStdout(suppress=False) as cap:
        Modal1.main(argv=['--version'])
    assert cap.text is not None
    assert '1.1.1' in cap.text

    with ub.CaptureStdout(suppress=False) as cap:
        Modal1.main(argv=['Modal2', '--version'])
    assert cap.text is not None
    assert '2.2.2' in cap.text

    with ub.CaptureStdout(suppress=False) as cap:
        Modal1.main(argv=['Modal2', 'Modal3', '--version'])
    assert cap.text is not None
    assert '3.3.3' in cap.text


def test_modal_version_fallback_to_root():
    """
    A submodal without its own __version__ reports the root's version
    instead of printing the literal ``None``.
    """
    import kwconf

    class Root(kwconf.ModalCLI):
        __version__ = '9.9.9'

        class Child(kwconf.ModalCLI):
            pass

    with ub.CaptureStdout(suppress=False) as cap:
        Root.main(argv=['--version', 'Child'])
    assert cap.text is not None
    assert '9.9.9' in cap.text
    assert 'None' not in cap.text


def test_modal_command_name_resolution():
    """
    The command name comes from the attribute a command is bound to, unless the
    class sets ``__command__`` (which wins). See
    :func:`test_modal_command_name_precedence`.
    """
    import kwconf

    class Command1(kwconf.Config):
        """The first subcommand."""

        __command__ = 'command1'

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs)

    class Command2(kwconf.Config):
        """The second subcommand."""

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs)

    class Modal1(kwconf.ModalCLI):
        __version__ = '1.1.1'

        wont_use_this_key = Command1  # __command__ overrides the attribute name
        will_use_this_key = Command2  # no __command__: attribute name is used

    help_text = Modal1().argparse().format_help()
    assert 'command1' in help_text
    assert 'wont_use_this_key' not in help_text
    assert 'will_use_this_key' in help_text
    assert 'Command2' not in help_text


def test_modal_command_name_precedence():
    """
    Command-name precedence (high -> low):
    ``ModalValue(command=)`` > ``__command__`` > attribute name > class name.
    """
    import kwconf

    class WithCmd(kwconf.Config):
        __command__ = 'declared'

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs)
            return 0

    class WithoutCmd(kwconf.Config):
        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs)
            return 0

    # 1. __command__ wins over the attribute name.
    class M1(kwconf.ModalCLI):
        my_attr = WithCmd

    assert M1.main(argv=['declared'], _noexit=True) == 0
    assert M1.main(argv=['my_attr'], _noexit=True) == 1

    # 2. ModalValue(command=) wins over __command__.
    class M2(kwconf.ModalCLI):
        my_attr = kwconf.ModalValue(WithCmd, command='explicit')

    assert M2.main(argv=['explicit'], _noexit=True) == 0
    assert M2.main(argv=['declared'], _noexit=True) == 1
    assert M2.main(argv=['my_attr'], _noexit=True) == 1

    # 3. No __command__: the attribute name is used.
    class M3(kwconf.ModalCLI):
        my_attr = WithoutCmd

    assert M3.main(argv=['my_attr'], _noexit=True) == 0

    # 4. No attribute name and no __command__ (__subconfigs__ list): class name.
    class M4(kwconf.ModalCLI):
        __subconfigs__ = [WithoutCmd]

    assert M4.main(argv=['WithoutCmd'], _noexit=True) == 0


def test_modal_inherits_declared_commands():
    """A modal subclass retains its parent's command tree."""
    calls = []

    class ParentCommand(kwconf.Config):
        @classmethod
        def main(cls, argv=None, **kwargs):
            calls.append('parent')
            return 0

    class ChildCommand(kwconf.Config):
        @classmethod
        def main(cls, argv=None, **kwargs):
            calls.append('child')
            return 0

    class Parent(kwconf.ModalCLI):
        parent = ParentCommand

    class Child(Parent):
        child = ChildCommand

    assert Child.main(argv=['parent'], _noexit=True) == 0
    assert Child.main(argv=['child'], _noexit=True) == 0
    assert calls == ['parent', 'child']

    parent_help = Parent().argparse().format_help()
    child_help = Child().argparse().format_help()
    assert 'parent' in parent_help
    assert 'child' not in parent_help
    assert 'parent' in child_help
    assert 'child' in child_help


def test_modal_inherits_explicit_registrations_without_sharing_list():
    """Explicit lists and register() participate in normal inheritance."""
    calls = []

    class ListedCommand(kwconf.Config):
        @classmethod
        def main(cls, argv=None, **kwargs):
            calls.append('listed')
            return 0

    class Parent(kwconf.ModalCLI):
        __subconfigs__ = [ListedCommand]

    @Parent.register(command='registered')
    class RegisteredCommand(kwconf.Config):
        @classmethod
        def main(cls, argv=None, **kwargs):
            calls.append('registered')
            return 0

    class Child(Parent):
        pass

    @Child.register(command='child')
    class ChildCommand(kwconf.Config):
        @classmethod
        def main(cls, argv=None, **kwargs):
            calls.append('child')
            return 0

    parent_specs = cast(list[Any], Parent.__subconfigs__)
    child_specs = cast(list[Any], Child.__subconfigs__)
    parent_commands = [
        item.get('command') or item['cls'].__name__
        for item in parent_specs
    ]
    child_commands = [
        item.get('command') or item['cls'].__name__
        for item in child_specs
    ]
    assert parent_commands == ['ListedCommand', 'registered']
    assert child_commands == ['ListedCommand', 'registered', 'child']

    assert Child.main(argv=['ListedCommand'], _noexit=True) == 0
    assert Child.main(argv=['registered'], _noexit=True) == 0
    assert Child.main(argv=['child'], _noexit=True) == 0
    assert calls == ['listed', 'registered', 'child']


def test_modal_runtime_metadata_is_instance_owned():
    """Building one parser must not mutate class or sibling metadata."""

    class Command(kwconf.Config):
        value = 1

        @classmethod
        def main(cls, argv=None, **kwargs):
            return 0

    class App(kwconf.ModalCLI):
        command = kwconf.ModalValue(Command, alias=['cmd'])

    class_spec = App.__subconfigs__[0]
    left = App()
    right = App()
    left_spec = left._subconfig_metadata[0]
    right_spec = right._subconfig_metadata[0]

    assert left_spec is not class_spec
    assert right_spec is not class_spec
    assert left_spec is not right_spec
    assert left_spec['alias'] is not class_spec['alias']
    assert right_spec['alias'] is not class_spec['alias']

    declarative_keys = set(class_spec)
    left.argparse()

    assert set(class_spec) == declarative_keys
    assert 'parserkw' not in class_spec
    assert 'subconfig' not in class_spec
    assert 'main_func' not in class_spec
    assert 'parserkw' not in right_spec
    assert 'subconfig' not in right_spec
    assert 'main_func' not in right_spec
    assert left_spec['subconfig'] is not right_spec.get('subconfig')

    right.argparse()
    assert left_spec['subconfig'] is not right_spec['subconfig']
    assert left_spec['parserkw'] is not right_spec['parserkw']
    assert set(class_spec) == declarative_keys


def test_modal_instance_registration_copies_metadata_dicts():
    """Instance registration should not retain a caller-owned metadata dict."""

    class Command(kwconf.Config):
        @classmethod
        def main(cls, argv=None, **kwargs):
            return 0

    source = {'cls': Command, 'command': 'run', 'alias': ['go']}
    modal = kwconf.ModalCLI(sub_clis=[source])
    instance_spec = modal._subconfig_metadata[0]

    assert instance_spec is not source
    assert instance_spec['alias'] is not source['alias']
    modal.argparse()
    assert set(source) == {'cls', 'command', 'alias'}
    assert 'parserkw' not in source
    assert 'subconfig' not in source


def test_modal_command_attribute_override_and_shadow():
    """Normal attribute overriding also applies to inherited commands."""
    calls = []

    class Original(kwconf.Config):
        @classmethod
        def main(cls, argv=None, **kwargs):
            calls.append('original')
            return 0

    class Replacement(kwconf.Config):
        @classmethod
        def main(cls, argv=None, **kwargs):
            calls.append('replacement')
            return 0

    class Helper:
        pass

    class Parent(kwconf.ModalCLI):
        run: type = Original

    class Replaced(Parent):
        run: type = Replacement

    class Hidden(Parent):
        run: type = Helper

    assert Replaced.main(argv=['run'], _noexit=True) == 0
    assert calls == ['replacement']

    assert Hidden.__subconfigs__ == []
    Hidden().argparse()
    assert Hidden.run is Helper


def test_modal_shadowing_reveals_later_base_command():
    class LeftCommand(kwconf.Config):
        __command__ = 'run'

    class RightCommand(kwconf.Config):
        __command__ = 'run'

    class Left(kwconf.ModalCLI):
        left_binding: type = LeftCommand

    class Right(kwconf.ModalCLI):
        right_binding = RightCommand

    class Helper:
        pass

    class Child(Left, Right):
        left_binding: type = Helper

    assert len(Child.__subconfigs__) == 1
    assert Child.__subconfigs__[0]['cls'] is RightCommand
    assert Child.__subconfigs__[0]['command'] == 'run'


def test_modal_ignores_unrelated_public_helper_classes():
    """Only Config and ModalCLI subclasses are discovered implicitly."""

    class Helper:
        pass

    class Command(kwconf.Config):
        @classmethod
        def main(cls, argv=None, **kwargs):
            return 0

    class App(kwconf.ModalCLI):
        helper = Helper
        command = Command

    help_text = App().argparse().format_help()
    assert 'command' in help_text
    assert [item['command'] for item in App.__subconfigs__] == ['command']
    assert App.helper is Helper
    assert App.main(argv=['command'], _noexit=True) == 0


def test_submodal_usage_improvement():
    """
    We print the deepest usage helps unlike default argparse
    """
    import sys

    import pytest

    import kwconf

    if sys.version_info[0:2] < (3, 13):
        pytest.skip('Does not work on older pythons')

    # from kwconf import diagnostics
    # diagnostics.DEBUG_MODAL = 1

    class Modal1(kwconf.ModalCLI):
        __version__ = '1.1.1'

        class Modal2(kwconf.ModalCLI):
            class Modal3(kwconf.ModalCLI):
                class Command1(kwconf.Config):
                    arg1 = 'foobar'

                    @classmethod
                    def main(cls, argv=None, **kwargs):
                        cls.cli(argv=argv, data=kwargs)

    assert (
        Modal1().main(argv=['Modal2', 'Modal3', 'Command1', '--arg1=32']) == 0
    )

    import io
    from contextlib import redirect_stderr

    from xdoctest.utils import util_str

    if 0:
        from kwconf import diagnostics

        diagnostics.DEBUG_MODAL = 1

    stderr_capture = io.StringIO()
    # Redirect stderr to the StringIO object within this context
    with redirect_stderr(stderr_capture):
        Modal1().main(
            argv=['Modal2', 'Modal3', 'Command1', '--arg2=32'], _noexit=True
        )
    text = util_str.strip_ansi(stderr_capture.getvalue())
    print(text)
    assert 'Modal2 Modal3 Command1 [' in text
    assert 'arg1' in text

    stderr_capture = io.StringIO()
    # Redirect stderr to the StringIO object within this context
    with redirect_stderr(stderr_capture):
        Modal1().main(argv=['Modal2', 'Modal3', '--arg2=32'], _noexit=True)
    text = stderr_capture.getvalue()
    text = util_str.strip_ansi(stderr_capture.getvalue())
    print(text)
    assert 'Modal2 Modal3 [' in text
    assert 'arg1' not in text
    assert '--version' not in text

    stderr_capture = io.StringIO()
    # Redirect stderr to the StringIO object within this context
    with redirect_stderr(stderr_capture):
        Modal1().main(argv=[], _noexit=True)
    text = util_str.strip_ansi(stderr_capture.getvalue())
    print(text)
    assert '--version' in text


def test_modal_value_declarative_registration():
    class Command1(kwconf.Config):
        foo = 'spam'

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs)

    class MyModalCLI(kwconf.ModalCLI):
        # command defaults to the attribute name: "my_cmd"
        my_cmd = kwconf.ModalValue(Command1, alias=['alias_cmd'])

    with ub.CaptureStdout(suppress=True) as cap:
        MyModalCLI.main(argv=['--help'], _noexit=True)

    assert cap.text is not None
    assert 'my_cmd' in cap.text
    assert 'alias_cmd' in cap.text
    assert MyModalCLI.main(argv=['my_cmd']) == 0
    assert MyModalCLI.main(argv=['alias_cmd']) == 0


def test_modal_value_command_override():
    class Command1(kwconf.Config):
        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs)

    class MyModalCLI(kwconf.ModalCLI):
        configured_name = kwconf.ModalValue(
            Command1, command='real_name', alias='rn'
        )

    with ub.CaptureStdout(suppress=True) as cap:
        MyModalCLI.main(argv=['--help'], _noexit=True)

    assert cap.text is not None
    assert 'real_name' in cap.text
    assert 'configured_name' not in cap.text
    assert 'rn' in cap.text
    assert MyModalCLI.main(argv=['real_name']) == 0
    assert MyModalCLI.main(argv=['rn']) == 0


def test_modal_value_alias_fuzzy_hyphens():
    class Command1(kwconf.Config):
        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs)

    class FuzzyModal(kwconf.ModalCLI):
        __fuzzy_hyphens__ = 1
        my_cmd = kwconf.ModalValue(Command1, alias='alias_cmd')

    class StrictModal(kwconf.ModalCLI):
        __fuzzy_hyphens__ = 0
        my_cmd = kwconf.ModalValue(Command1, alias='alias_cmd')

    class FuzzyModalHyphenAlias(kwconf.ModalCLI):
        __fuzzy_hyphens__ = 1
        my_cmd = kwconf.ModalValue(Command1, alias='alias-cmd')

    assert FuzzyModal.main(argv=['my_cmd']) == 0
    assert FuzzyModal.main(argv=['my-cmd']) == 0
    assert FuzzyModal.main(argv=['alias_cmd']) == 0
    assert FuzzyModal.main(argv=['alias-cmd']) == 0

    assert StrictModal.main(argv=['my_cmd']) == 0
    assert StrictModal.main(argv=['alias_cmd']) == 0
    assert StrictModal.main(argv=['my-cmd'], _noexit=True) == 1
    assert StrictModal.main(argv=['alias-cmd'], _noexit=True) == 1

    # Match Value behavior: fuzzy hyphens adds underscore->hyphen variants,
    # but does not add hyphen->underscore variants.
    assert FuzzyModalHyphenAlias.main(argv=['alias-cmd']) == 0
    assert FuzzyModalHyphenAlias.main(argv=['alias_cmd'], _noexit=True) == 1


def test_modal_fuzzy_hyphens_propagation():
    """
    A parent modal opting out of fuzzy hyphens propagates down at resolve time
    (commands and option flags), without mutating the possibly-shared child.
    """
    import kwconf

    class Leaf(kwconf.Config):
        out_dir = kwconf.Value('x')

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs)
            return 0

    class Sub(kwconf.ModalCLI):
        do_thing = Leaf

    class FuzzyRoot(kwconf.ModalCLI):
        run_leaf = Leaf
        sub = Sub

    class StrictRoot(kwconf.ModalCLI):
        __fuzzy_hyphens__ = False
        run_leaf = Leaf
        sub = Sub

    # Fuzzy root: hyphen spellings accepted at every level.
    assert FuzzyRoot.main(argv=['run-leaf', '--out-dir=A'], _noexit=True) == 0
    assert (
        FuzzyRoot.main(argv=['sub', 'do-thing', '--out-dir=A'], _noexit=True)
        == 0
    )

    # Strict root propagates down: hyphen command names AND option flags are
    # rejected for the whole subtree; canonical spellings still work.
    assert StrictRoot.main(argv=['run_leaf', '--out_dir=A'], _noexit=True) == 0
    assert StrictRoot.main(argv=['run-leaf', '--out_dir=A'], _noexit=True) == 1
    assert StrictRoot.main(argv=['run_leaf', '--out-dir=A'], _noexit=True) == 1
    assert StrictRoot.main(argv=['sub', 'do-thing'], _noexit=True) == 1
    assert (
        StrictRoot.main(argv=['sub', 'do_thing', '--out-dir=A'], _noexit=True)
        == 1
    )

    # The shared Leaf class is not mutated: still fuzzy under FuzzyRoot even
    # after StrictRoot has been built and resolved.
    assert not hasattr(Leaf, '__fuzzy_hyphens__')
    assert FuzzyRoot.main(argv=['run_leaf', '--out-dir=A'], _noexit=True) == 0


def test_modal_command_listing_hides_fuzzy_hyphen_aliases():
    """
    By default the command listing shows one spelling per command: the
    fuzzy-hyphen alias still routes but is hidden from ``--help``, while an
    intentional alias is shown.
    """
    import kwconf

    class ExportData(kwconf.Config):
        """Export the data."""

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs)
            return 0

    class App(kwconf.ModalCLI):
        export_data = kwconf.ModalValue(ExportData, alias=['dump_it'])

    help_text = App().argparse().format_help()
    # Canonical spelling and the intentional alias are shown ...
    assert 'export_data' in help_text
    assert 'dump_it' in help_text
    # ... but their fuzzy-hyphen duplicates are hidden from the listing.
    assert 'export-data' not in help_text
    assert 'dump-it' not in help_text

    # All spellings still route to the command.
    for spelling in ['export_data', 'export-data', 'dump_it', 'dump-it']:
        assert App.main(argv=[spelling], _noexit=True) == 0


def test_arbitrary_opaque_subparser():
    # import pytest
    import sys

    import kwconf

    def opaque_main():
        import argparse

        print(f'sys.argv={sys.argv}')
        parser = argparse.ArgumentParser(
            description='This is the opaque main help message'
        )
        parser.add_argument('--foo', default='bar')
        ns = parser.parse_args()
        print(f'Successfully called the opaque main and got ns={ns}')

    class MyModal(kwconf.ModalCLI):
        __version__ = '1.1.1'

    modal = MyModal()
    modal.register(command='extern_cli', main=opaque_main)(None)
    modal._subconfig_metadata

    # from kwconf import diagnostics
    # diagnostics.DEBUG_MODAL = 1

    print('--------------')
    print('* default help')
    print('--------------')
    try:
        modal.main(argv=['--help'], strict=False)
    except SystemExit:
        ...

    print('--------------')
    print('* try to print extern help')
    print('--------------')
    try:
        modal.main(argv=['extern_cli', '--help'], strict=False)
    except SystemExit:
        ...

    print('--------------')
    print('* invoke trigger cli')
    print('--------------')
    modal.main(argv=['extern_cli'], strict=False)


def test_modal_main_argv_false():
    """
    ``main(argv=False)`` follows the Config.main convention (do not read the
    CLI); for a modal that means "no command" rather than a TypeError.
    """
    import pytest

    from kwconf.modal import NoCommandError

    class Command1(kwconf.Config):
        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs)

    class MyModal(kwconf.ModalCLI):
        cmd1 = Command1

    with pytest.raises(NoCommandError):
        MyModal.main(argv=False)
    assert MyModal.main(argv=False, _noexit=True) == 1
    assert MyModal.main(argv=0, _noexit=True) == 1


def test_opaque_command_first_in_nested_modal():
    """
    An opaque command as the first command of a nested modal used to hit an
    unbound ``parserkw`` at build time.
    """
    calls = []

    def opaque_main():
        calls.append('opaque')

    class Sub(kwconf.ModalCLI):
        __command__ = 'sub'

    sub = Sub()
    sub.register(command='extern', main=opaque_main)(None)

    class Root(kwconf.ModalCLI):
        pass

    root = Root()
    root.register(sub, command='sub')

    root.main(argv=['sub', 'extern'], strict=False)
    assert calls == ['opaque']


def test_opaque_command_does_not_inherit_previous_aliases():
    """
    An opaque command registered after an aliased command used to reuse the
    previous command's parserkw, hijacking its aliases (a build-time
    'conflicting subparser alias' error on newer Pythons).
    """
    calls = []

    def opaque_main():
        calls.append('opaque')

    class Command1(kwconf.Config):
        @classmethod
        def main(cls, argv=None, **kwargs):
            calls.append('command1')
            cls.cli(argv=argv, data=kwargs)

    class MyModal(kwconf.ModalCLI):
        pass

    modal = MyModal()
    modal.register(Command1, command='cmd1', alias=['c1'])
    modal.register(command='extern', main=opaque_main)(None)

    # Building the parser must not raise, and the alias must still route to
    # the aliased command, not the opaque one.
    modal.argparse()
    assert modal.main(argv=['c1'], strict=False) == 0
    modal.main(argv=['extern'], strict=False)
    assert calls == ['command1', 'opaque']


def test_modal_with_positional_arguments_variant1():
    """
    Test that modals can have subcommands with positional arguments,
    including nested modals.
    """

    class NestedModalCLI(kwconf.ModalCLI):
        """Nested modal with positional command"""

        __command__ = 'nested'

    class NestedCommand(kwconf.Config):
        """A nested command with positional args"""

        pos_arg = kwconf.Value(
            'default_pos', position=1, help='A positional argument'
        )
        opt_arg = kwconf.Value('default_opt', help='An optional argument')

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs, verbose=False)

    NestedModalCLI.register(NestedCommand, command='nested_cmd')

    class SimpleCommand(kwconf.Config):
        """Command with a positional argument"""

        filename = kwconf.Value('input.txt', position=1, help='Input filename')
        verbose = kwconf.Flag(False, help='Verbose mode')

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs, verbose=False)

    class TopModalCLI(kwconf.ModalCLI):
        """Top-level modal with positional subcommands"""

    TopModalCLI.register(SimpleCommand, command='simple_pos')
    TopModalCLI.register(NestedModalCLI, command='nested_modal')

    # Test 1: simple positional argument in subcommand
    result = SimpleCommand.cli(argv=['myfile.txt'])
    assert result.filename == 'myfile.txt'
    assert result.verbose is False

    # Test 2: positional argument with optional flag
    result = SimpleCommand.cli(argv=['myfile.txt', '--verbose'])
    assert result.filename == 'myfile.txt'
    assert result.verbose is True

    # Test 3: positional in nested modal subcommand
    result = NestedCommand.cli(argv=['nested_file.txt'])
    assert result.pos_arg == 'nested_file.txt'
    assert result.opt_arg == 'default_opt'

    # Test 4: positional and optional in nested modal subcommand
    result = NestedCommand.cli(
        argv=['nested_file.txt', '--opt_arg', 'custom_opt']
    )
    assert result.pos_arg == 'nested_file.txt'
    assert result.opt_arg == 'custom_opt'

    # Test 5: test via modal main with simple_pos command
    exit_code = TopModalCLI.main(argv=['simple_pos', 'test_modal.txt'])
    assert exit_code == 0

    # Test 6: test via modal main with nested_modal command
    exit_code = TopModalCLI.main(
        argv=['nested_modal', 'nested_cmd', 'test_nested.txt']
    )
    assert exit_code == 0


def test_modal_with_positional_arguments_variant2():
    """
    Test that modals can have subcommands with positional arguments,
    including nested modals. Second variant using algernative declarations
    """

    class NestedCommand(kwconf.Config):
        """A nested command with positional args"""

        pos_arg = kwconf.Value(
            'default_pos', position=1, help='A positional argument'
        )
        opt_arg = kwconf.Value('default_opt', help='An optional argument')

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs, verbose=False)

    class SimpleCommand(kwconf.Config):
        """Command with a positional argument"""

        filename = kwconf.Value('input.txt', position=1, help='Input filename')
        verbose = kwconf.Flag(False, help='Verbose mode')

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs, verbose=False)

    class NestedModalCLI(kwconf.ModalCLI):
        """Nested modal with positional command"""

        nested_cmd = kwconf.ModalValue(NestedCommand)

    class TopModalCLI(kwconf.ModalCLI):
        """Top-level modal with positional subcommands"""

        nested_modal = kwconf.ModalValue(NestedModalCLI)
        simple_pos = kwconf.ModalValue(SimpleCommand)

    # Test 1: simple positional argument in subcommand
    result = SimpleCommand.cli(argv=['myfile.txt'])
    assert result.filename == 'myfile.txt'
    assert result.verbose is False

    # Test 2: positional argument with optional flag
    result = SimpleCommand.cli(argv=['myfile.txt', '--verbose'])
    assert result.filename == 'myfile.txt'
    assert result.verbose is True

    # Test 3: positional in nested modal subcommand
    result = NestedCommand.cli(argv=['nested_file.txt'])
    assert result.pos_arg == 'nested_file.txt'
    assert result.opt_arg == 'default_opt'

    # Test 4: positional and optional in nested modal subcommand
    result = NestedCommand.cli(
        argv=['nested_file.txt', '--opt_arg', 'custom_opt']
    )
    assert result.pos_arg == 'nested_file.txt'
    assert result.opt_arg == 'custom_opt'

    # Test 5: test via modal main with simple_pos command
    exit_code = TopModalCLI.main(argv=['simple_pos', 'test_modal.txt'])
    assert exit_code == 0

    # Test 6: test via modal main with nested_modal command
    exit_code = TopModalCLI.main(
        argv=['nested_modal', 'nested_cmd', 'test_nested.txt']
    )
    assert exit_code == 0


def test_modal_with_config_field_special_options():
    """
    Test that modals work with subcommands that have a literal 'config' field
    when __special_options__ = False is set as a class attribute.
    """

    class NestedCommand(kwconf.Config):
        """A nested command with a config field"""

        __special_options__ = False  # Disable special options at class level

        config = kwconf.Value('default_config.yaml', help='Config file path')
        opt_arg = kwconf.Value('default_opt', help='An optional argument')

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs, verbose=False)

    class SimpleCommand(kwconf.Config):
        """Command with a config field"""

        __special_options__ = False  # Disable special options at class level

        config = kwconf.Value('config.yaml', help='Config file path')
        verbose = kwconf.Flag(False, help='Verbose mode')

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs, verbose=False)

    class NestedModalCLI(kwconf.ModalCLI):
        """Nested modal with config command"""

        nested_cmd = kwconf.ModalValue(NestedCommand)

    class TopModalCLI(kwconf.ModalCLI):
        """Top-level modal with config subcommands"""

        nested_modal = kwconf.ModalValue(NestedModalCLI)
        simple_cmd = kwconf.ModalValue(SimpleCommand)

    # Test 1: simple command with default config
    result = SimpleCommand.cli(argv=[])
    assert result.config == 'config.yaml'
    assert result.verbose is False

    # Test 2: simple command with config override
    result = SimpleCommand.cli(argv=['--config', 'custom.yaml', '--verbose'])
    assert result.config == 'custom.yaml'
    assert result.verbose is True

    # Test 3: nested command with default config
    result = NestedCommand.cli(argv=[])
    assert result.config == 'default_config.yaml'
    assert result.opt_arg == 'default_opt'

    # Test 4: nested with config override
    result = NestedCommand.cli(
        argv=['--config', 'nested_custom.yaml', '--opt_arg', 'custom_opt']
    )
    assert result.config == 'nested_custom.yaml'
    assert result.opt_arg == 'custom_opt'

    # Test 5: test via modal main with simple_cmd
    exit_code = TopModalCLI.main(argv=['simple_cmd'])
    assert exit_code == 0

    # Test 6: test via modal main with nested_modal command
    exit_code = TopModalCLI.main(argv=['nested_modal', 'nested_cmd'])
    assert exit_code == 0

    # Test 7: test via modal main with config override
    exit_code = TopModalCLI.main(argv=['simple_cmd', '--config', 'alt.yaml'])
    assert exit_code == 0


def test_modal_forwards_only_explicit_kwargs():
    """
    Modal dispatch should not make omitted child defaults look explicit.
    """

    repo_defaults = {'depth': '0'}
    calls = []

    class ArchiveSource(kwconf.Config):
        __command__ = 'archive_source'

        depth = kwconf.Value('full')
        format = kwconf.Value('auto')
        verbose = kwconf.Flag(False)

        @classmethod
        def main(cls, argv=None, **kwargs):
            calls.append({'argv': argv, 'kwargs': dict(kwargs)})
            return cls.cli(argv=argv, data=kwargs, default=repo_defaults)

    class App(kwconf.ModalCLI):
        archive_source = ArchiveSource

    direct = ArchiveSource.main(argv=['--verbose'])
    modal = App.main(argv=['archive_source', '--verbose'])
    explicit_modal = App.main(
        argv=['archive_source', '--verbose', '--depth=full']
    )

    assert direct.depth == '0'
    assert modal.depth == '0'
    assert explicit_modal.depth == 'full'
    assert calls[0] == {'argv': ['--verbose'], 'kwargs': {}}
    assert calls[1] == {'argv': False, 'kwargs': {'verbose': True}}
    assert calls[2] == {
        'argv': False,
        'kwargs': {'verbose': True, 'depth': 'full'},
    }


def test_modal_subcommand_exception_propagates_cleanly(capsys):
    """A subcommand that raises should propagate the exception unchanged,
    without ModalCLI.main printing a debug line to stdout first.

    Downstream CLIs (e.g. aivm) install their own top-level handler to turn
    domain errors into a clean message; a stray ``ERROR ex = ...`` print here
    double-reported every failure.
    """

    class Boom(RuntimeError):
        pass

    class DoBoom(kwconf.Config):
        __command__ = 'boom'

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs)
            raise Boom('kaboom')

    class RootCLI(kwconf.ModalCLI):
        __subconfigs__ = [DoBoom]

    import pytest

    with pytest.raises(Boom, match='kaboom'):
        RootCLI.main(argv=['boom'])

    captured = capsys.readouterr()
    assert 'ERROR ex' not in captured.out
    assert 'ERROR ex' not in captured.err


def test_modal_subcommand_none_return_is_zero():
    """A subcommand returning ``None`` is treated as a success exit code."""

    class DoNothing(kwconf.Config):
        __command__ = 'noop'

        @classmethod
        def main(cls, argv=None, **kwargs):
            cls.cli(argv=argv, data=kwargs)
            return None

    class RootCLI(kwconf.ModalCLI):
        __subconfigs__ = [DoNothing]

    assert RootCLI.main(argv=['noop']) == 0


if __name__ == '__main__':
    """
    CommandLine:
        python ~/code/kwconf/tests/test_modal.py
    """
    # test_modal_fuzzy_hyphens()
    test_arbitrary_opaque_subparser()
