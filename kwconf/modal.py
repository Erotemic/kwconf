"""
The kwconf ModalCLI

This module defines a way to group several smaller kwconf CLIs into a
single parent CLI that chooses between them "modally". E.g. if we define two
configs: do_foo and do_bar, we use ModalCLI to define a parent program that can run
one or the other. Let's make this more concrete.

CommandLine:
    xdoctest -m kwconf.modal __doc__:0

Example

    >>> import kwconf
    >>> #
    >>> class DoFooCLI(kwconf.DataConfig):
    >>>     __command__ = 'do_foo'
    >>>     option1 = kwconf.Value(None, help='option1')
    >>>     #
    >>>     @classmethod
    >>>     def main(cls, argv=1, **kwargs):
    >>>         self = cls.cli(argv=argv, data=kwargs)
    >>>         print('Called Foo with: ' + str(self))
    >>> #
    >>> class DoBarCLI(kwconf.DataConfig):
    >>>     __command__ = 'do_bar'
    >>>     option1 = kwconf.Value(None, help='option1')
    >>>     #
    >>>     @classmethod
    >>>     def main(cls, argv=1, **kwargs):
    >>>         self = cls.cli(argv=argv, data=kwargs)
    >>>         print('Called Bar with: ' + str(self))
    >>> #
    >>> #
    >>> class MyModalCLI(kwconf.ModalCLI):
    >>>     __version__ = '1.2.3'
    >>>     foo = DoFooCLI
    >>>     bar = DoBarCLI
    >>> #
    >>> modal = MyModalCLI()
    >>> MyModalCLI.main(argv=['do_foo'])
    >>> #MyModalCLI.main(argv=['do-foo'])
    >>> MyModalCLI.main(argv=['--version'])
    >>> try:
    >>>     MyModalCLI.main(argv=['--help'])
    >>> except SystemExit:
    >>>     print('prevent system exit due to calling --help')

Note:
    Submodals in :class:`ModalCLI` must be registered as classes (or via
    :meth:`register`). For declarative metadata (e.g. aliases) use
    :class:`kwconf.ModalValue`.

    >>> import kwconf
    >>> class ChildModal(kwconf.ModalCLI):
    >>>     ...
    >>> class ParentModal(kwconf.ModalCLI):
    >>>     child = ChildModal           # supported
    >>>     child2 = kwconf.ModalValue(ChildModal, alias=['kid'])  # supported
    >>>     # child3 = kwconf.Value(ChildModal)  # Value is for config values

    If you want nested config nodes that are wrapped in ``Value(...)``, see
    :class:`kwconf.SubConfig` in ``docs/source/manual/nested_configs.rst``.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import ubelt as ub

from kwconf.util.util_class import class_or_instancemethod
from kwconf import diagnostics
# from kwconf.config import MetaConfig


DEFAULT_GROUP = 'commands'


class ModalValue(ub.NiceRepr):
    """
    Declarative wrapper for registering a modal subcommand with extra metadata.

    Example:
        >>> import kwconf
        >>> class Child(kwconf.DataConfig):
        ...     @classmethod
        ...     def main(cls, argv=1, **kwargs):
        ...         ...
        >>> class Root(kwconf.ModalCLI):
        ...     child = kwconf.ModalValue(Child, alias=['kid'])
    """

    def __init__(self,
                 value: type,
                 command: Optional[str] = None,
                 alias: Optional[Union[str, List[str]]] = None,
                 group: Optional[str] = None) -> None:
        self.value = value
        self.command = command
        self.alias = alias
        self.group = group

    def __nice__(self) -> str:
        name = getattr(self.value, '__name__', repr(self.value))
        return f'{name}'


class MetaModalCLI(type):
    """
    A metaclass to help minimize boilerplate when defining a ModalCLI
    """

    @staticmethod
    def __new__(mcls: type,
                name: str,
                bases: Tuple[type, ...],
                namespace: Dict[str, Any],
                *args: Any,
                **kwargs: Any) -> type:
        # Note: this code has an impact on startuptime efficiency.
        # optimizations here can help.

        # Iterate over class attributes and register any Config or ModalCLI
        # objects in the __subconfigs__ dictionary the attribute names
        # will be used as the command name.
        final_subconfigs = []
        for k, v in namespace.items():
            if k.startswith('_'):
                continue
            if isinstance(v, type):
                final_subconfigs.append({
                    'command': getattr(v, '__command__', None) or k,
                    'cls': v,
                })
            elif isinstance(v, ModalValue):
                if not isinstance(v.value, type):
                    raise TypeError(
                        f'ModalValue for attribute {k!r} must wrap a class, '
                        f'got {type(v.value)!r}'
                    )
                final_subconfigs.append({
                    'command': v.command if v.command is not None else (getattr(v.value, '__command__', None) or k),
                    'cls': v.value,
                    'alias': v.alias,
                    'group': v.group,
                })
        cls_subconfigs = namespace.get('__subconfigs__', [])
        if cls_subconfigs:
            final_subconfigs.extend(cls_subconfigs)

        # Helps make the class pickleable. Pretty hacky though.
        # for k in attr_subconfigs.keys():
        #     namespace.pop(k)
        namespace['__subconfigs__'] = final_subconfigs

        cls = super().__new__(mcls, name, bases, namespace, *args, **kwargs)  # type: ignore
        return cls


class ModalCLI(metaclass=MetaModalCLI):
    """
    Contains multiple kwconf.DataConfig items with corresponding `main`
    functions.

    CommandLine:
        xdoctest -m kwconf.modal ModalCLI

    Example:
        >>> from kwconf.modal import *  # NOQA
        >>> import kwconf
        >>> self = ModalCLI(description='A modal CLI')
        >>> #
        >>> @self.register
        >>> class Command1Config(kwconf.DataConfig):
        >>>     __command__ = 'command1'
        >>>     __default__ = {
        >>>         'foo': 'spam'
        >>>     }
        >>>     @classmethod
        >>>     def main(cls, argv=1, **kwargs):
        >>>         config = cls.cli(argv=argv, data=kwargs)
        >>>         print('config1 = {}'.format(ub.urepr(dict(config), nl=1)))
        >>> #
        >>> @self.register
        >>> class Command2Config(kwconf.DataConfig):
        >>>     __command__ = 'command2'
        >>>     foo = 'eggs'
        >>>     baz = 'biz'
        >>>     @classmethod
        >>>     def main(cls, argv=1, **kwargs):
        >>>         config = cls.cli(argv=argv, data=kwargs)
        >>>         print('config2 = {}'.format(ub.urepr(dict(config), nl=1)))
        >>> #
        >>> parser = self.argparse()
        >>> parser.print_help()
        ...
        A modal CLI
        ...
        commands:
          {command1,command2}  specify a command to run
            command1           argparse CLI generated by kwconf...
            command2           argparse CLI generated by kwconf...
        >>> self.run(argv=['command1'])
        config1 = {
            'foo': 'spam',
        }
        >>> self.run(argv=['command2', '--baz=buz'])
        config2 = {
            'foo': 'eggs',
            'baz': 'buz',
        }

    CommandLine:
        xdoctest -m kwconf.modal ModalCLI:1

    Example:
        >>> # Declarative modal CLI (new in 0.7.9)
        >>> import kwconf
        >>> class MyModalCLI(kwconf.ModalCLI):
        >>>     #
        >>>     class Command1(kwconf.DataConfig):
        >>>         __command__ = 'command1'
        >>>         foo = kwconf.Value('spam', help='spam spam spam spam')
        >>>         @classmethod
        >>>         def main(cls, argv=1, **kwargs):
        >>>             config = cls.cli(argv=argv, data=kwargs)
        >>>             print('config1 = {}'.format(ub.urepr(dict(config), nl=1)))
        >>>     #
        >>>     class Command2(kwconf.DataConfig):
        >>>         __command__ = 'command2'
        >>>         foo = 'eggs'
        >>>         baz = 'biz'
        >>>         @classmethod
        >>>         def main(cls, argv=1, **kwargs):
        >>>             config = cls.cli(argv=argv, data=kwargs)
        >>>             print('config2 = {}'.format(ub.urepr(dict(config), nl=1)))
        >>> #
        >>> MyModalCLI.main(argv=['command1'])
        >>> MyModalCLI.main(argv=['command2', '--baz=buz'])

    Example:
        >>> # Declarative modal CLI (new in 0.7.9)
        >>> import kwconf
        >>> class MyModalCLI(kwconf.ModalCLI):
        >>>     ...
        >>> #
        >>> @MyModalCLI.register(command='command1')
        >>> class Command1(kwconf.DataConfig):
        >>>     foo = kwconf.Value('spam', help='spam spam spam spam')
        >>>     @classmethod
        >>>     def main(cls, argv=1, **kwargs):
        >>>         config = cls.cli(argv=argv, data=kwargs)
        >>>         print('config1 = {}'.format(ub.urepr(dict(config), nl=1)))
        >>> #
        >>> @MyModalCLI.register(command='command2')
        >>> class Command2(kwconf.DataConfig):
        >>>     foo = 'eggs'
        >>>     baz = 'biz'
        >>>     @classmethod
        >>>     def main(cls, argv=1, **kwargs):
        >>>         config = cls.cli(argv=argv, data=kwargs)
        >>>         print('config2 = {}'.format(ub.urepr(dict(config), nl=1)))
        >>> #
        >>> MyModalCLI.main(argv=['command1'])
        >>> MyModalCLI.main(argv=['command2', '--baz=buz'])

    Example:
        >>> # Key/value modal CLI (uses names as commands)
        >>> import kwconf
        >>> #
        >>> class Command1(kwconf.DataConfig):
        >>>     foo = kwconf.Value('spam', help='spam spam spam spam')
        >>>     @classmethod
        >>>     def main(cls, argv=1, **kwargs):
        >>>         config = cls.cli(argv=argv, data=kwargs)
        >>>         print('config1 = {}'.format(ub.urepr(dict(config), nl=1)))
        >>> #
        >>> class Command2(kwconf.DataConfig):
        >>>     foo = 'eggs'
        >>>     baz = 'biz'
        >>>     @classmethod
        >>>     def main(cls, argv=1, **kwargs):
        >>>         config = cls.cli(argv=argv, data=kwargs)
        >>>         print('config2 = {}'.format(ub.urepr(dict(config), nl=1)))
        >>> #
        >>> class MyModalCLI(kwconf.ModalCLI):
        >>>     command1 = Command1
        >>>     command2 = Command2
        >>> #
        >>> MyModalCLI.main(argv=['command1'])
        >>> MyModalCLI.main(argv=['command2', '--baz=buz'])
    """
    __subconfigs__: List[Dict[str, Any]] = []

    def __init__(self,
                 description: str = '',
                 sub_clis: Optional[List[Dict[str, Any]]] = None,
                 version: Optional[str] = None) -> None:
        if sub_clis is None:
            sub_clis = []

        if self.__class__.__name__ != 'ModalCLI':
            self.description = description or ub.codeblock(self.__doc__ or '')
        else:
            self.description = description

        _instance_subconfigs = sub_clis + self.__subconfigs__

        # On the instance level we ensure all subconfigs are transformed into a
        # table of dictionaries containing the class and its overridden
        # metadata.
        self._subconfig_metadata: List[Dict] = [
            self._init_subconfig_metadata(cls)
            for cls in _instance_subconfigs
        ]

        if version is None:
            version = getattr(self.__class__, '__version__', None)
        if version is None:
            version = getattr(self.__class__, 'version', None)
        self.version = version

    @staticmethod
    def _init_subconfig_metadata(cli_cls) -> Dict:
        """
        Rectifies a subconfig subclass into a table of metadata, which can be
        modified on a per-instance level. This is slightly redundant, but it
        allows reuse of CLIs in different contexts.

        Args:
            cli_cls (type): the subconfig class
        """
        if isinstance(cli_cls, dict):
            # Input given as a dictionary, must correspond to specific structure:
            metadata = cli_cls
            # assert 'cls' in metadata
        else:
            metadata = {
                'cls': cli_cls,
            }
        return metadata

    @staticmethod
    def _update_metadata(metadata: Dict):
        """
        Given a metadata dictionary (which must contain a "cls" item) we
        introspect and fill in other unspecified items. To make initialization
        faster we only do this when we need to build the argparse object
        explicitly.

        Args:
            metadata (dict): modified inplace
        """
        cli_cls = metadata['cls']
        if cli_cls is None:
            # cant introspect anything, will assume the user specified
            # enough information and call the main as an opaque function
            metadata['is_opaque'] = True
            return

        if not hasattr(cli_cls, 'main'):
            raise ValueError(ub.paragraph(
                f'''
                The ModalCLI expects that registered subconfigs have a
                ``main`` classmethod with the signature
                ``main(cls, argv: bool, **kwargs)``,
                but {cli_cls} is missing one.
            '''))

        if metadata.get('command') is None:
            command = getattr(cli_cls, '__command__', None)
            if command is None:
                command = cli_cls.__name__
            if command is None:
                raise ValueError(ub.paragraph(
                    f'''
                    The ModalCLI expects that registered subconfigs have a
                    ``__command__: str`` attribute, but {cli_cls} is missing one.
                '''))
            metadata['command'] = command

        if metadata.get('alias') is None:
            metadata['alias'] = getattr(cli_cls, '__alias__', [])

        if metadata.get('group') is None:
            metadata['group'] = getattr(cli_cls, '__group__', DEFAULT_GROUP)

        parserkw = {}
        if metadata['alias']:
            if isinstance(metadata['alias'], str):
                metadata['alias'] = [metadata['alias']]
            parserkw['aliases'] = metadata['alias']

        # group = 'FOO'
        # print(f'cli_cls={cli_cls}')
        # print(isinstance(cli_cls, ModalCLI))
        # print('cli_cls.__bases__ = {}'.format(ub.urepr(cli_cls.__bases__, nl=1)))
        # print('ModalCLI = {}'.format(ub.urepr(ModalCLI, nl=1)))

        if isinstance(cli_cls, ModalCLI) or issubclass(cli_cls, ModalCLI):
            # Another modal layer
            if isinstance(cli_cls, type):
                modal = cli_cls()
            else:
                modal = cli_cls
            parserkw.update(modal._parserkw())
            parserkw['help'] = parserkw['description'].split('\n')[0]
            metadata.update({
                'is_modal': True,
                'parserkw': parserkw,
                'main_func': cli_cls.main,
                'subconfig': modal,
            })
        else:
            # A leaf Config CLI
            subconfig = cli_cls()
            parserkw.update(subconfig._parserkw())
            parserkw['help'] = parserkw['description'].split('\n')[0]
            metadata.update({
                'is_modal': False,
                'parserkw': parserkw,
                'main_func': cli_cls.main,
                'subconfig': subconfig,
            })

    def __call__(self, cli_cls: type) -> type:
        """ alias of register """
        return self.register(cli_cls)

    @class_or_instancemethod  # type: ignore
    def register(cls_or_self,
                 cli_cls: Optional[type] = None,
                 command: Optional[str] = None,
                 alias: Optional[List[str]] = None,
                 group: Optional[str] = None,
                 main: Optional[Any] = None) -> Any:
        """
        Add a sub-CLI to this modal CLI

        Args:
            cli_cls (kwconf.DataConfig | None):
                A CLI-aware config object to register as a sub CLI.
                If None, then this is called as a wrapped closure

        # TODO: ability to specify alias when registering the modal command
        """

        def _wrapper(cli_cls):
            # Note: the order or registration is how it will appear in the CLI help
            # Hack for older kwconf
            # if not hasattr(cli_cls, 'default'):
            #     cli_cls.default = cli_cls.__default__
            if isinstance(cls_or_self, type):
                # Called as a class method
                metadata = cls_or_self._init_subconfig_metadata(cli_cls)
                cls_or_self.__subconfigs__.append(metadata)
            else:
                # Called as an instance method
                metadata = cls_or_self._init_subconfig_metadata(cli_cls)
                cls_or_self._subconfig_metadata.append(metadata)

            if command is not None:
                metadata['command'] = command
            if alias is not None:
                metadata['alias'] = alias
            if main is not None:
                metadata['main_func'] = main

        if cli_cls is None:
            return _wrapper
        else:
            return _wrapper(cli_cls)

    def _parserkw(self):
        """
        Generate the kwargs for making a new argparse.ArgumentParser
        """
        from kwconf.argparse_ext import RawDescriptionDefaultsHelpFormatter
        parserkw = dict(
            description=self.description,
            formatter_class=RawDescriptionDefaultsHelpFormatter,
            epilog=getattr(self, '__epilog__', None),
            prog=getattr(self, '__prog__', None),
        )
        if hasattr(self, '__allow_abbrev__'):
            parserkw['allow_abbrev'] = self.__allow_abbrev__
        return parserkw

    def argparse(self, parser: Optional[Any] = None, special_options: Any = ...) -> Any:
        """
        Builds a new argparse object for this ModalCLI or extends an existing
        one with it.
        """

        if parser is None:
            parserkw = self._parserkw()
            # import argparse as argparse_mod
            # parser = argparse_mod.ArgumentParser(**parserkw)
            from kwconf import argparse_ext
            parser = argparse_ext.ExtendedArgumentParser(**parserkw)

        if hasattr(self, 'version') and self.version is not None:
            # NOTE: having a --version argument for the modal CLI causes
            # some issues because when we parse the arguments, we dont
            # know if version should be passed to the subcommand or not.
            # We work around this by using a special destination for
            # the modal version flag.
            parser.add_argument('--version', action='store_true',
                                dest='__modal_version_request__',
                                help='show version number and exit')
        parser.set_defaults(__submodal__=self)

        # Prepare information to be added to the subparser before it is created
        for metadata in self._subconfig_metadata:
            self._update_metadata(metadata)
        cmdinfo_list = self._subconfig_metadata
        fuzzy_hyphens = getattr(self, '__fuzzy_hyphens__', 1)

        # Build a list of primary command names to display as the valid options
        # for subparsers. This avoids cluttering the screen with all aliases
        # which happens by default.

        # The subparser is what enables the modal CLI. It will redirect a
        # command to a chosen subparser.
        # group_to_cmdinfos = ub.group_items(cmdinfo_list, key=lambda x: x['group'])

        # TODO: groups?
        # https://stackoverflow.com/questions/32017020/grouping-argparse-subparser-arguments

        _command_choices = [d['command'] for d in cmdinfo_list]
        _metavar = '{' + ','.join(_command_choices) + '}'
        command_subparsers = parser.add_subparsers(
            title='commands',
            # dest='__command__',
            help='specify a command to run', metavar=_metavar)

        # group_to_subparser = {}
        # for group, cmdinfos in group_to_cmdinfos.items():
        #     ...

        def value_like_fuzzy_long_names(names):
            if not names:
                return []
            if isinstance(names, str):
                names = [names]
            long_names = list(names)
            if fuzzy_hyphens:
                # Match Value._resolve_alias behavior:
                # only add underscore->hyphen variants.
                unique_long_names = set(long_names)
                modified_long_names = {n.replace('_', '-') for n in unique_long_names}
                extra_long_names = modified_long_names - unique_long_names
                long_names += sorted(extra_long_names)
            return long_names

        for cmdinfo in cmdinfo_list:
            # group = cmdinfo['group']
            # Add a new command to subparser_group

            command_names = value_like_fuzzy_long_names([cmdinfo['command']])
            main_cmd, aliases = command_names[0], command_names[1:]

            if cmdinfo.get('is_opaque'):
                external_parser = command_subparsers.add_parser(
                    main_cmd, add_help=False, **parserkw)
                external_parser.set_defaults(__opaque_main__=cmdinfo['main_func'])
                continue

            # copy so we dont have inplace issues
            # could just make this part of the update metadata method
            parserkw = {**cmdinfo['parserkw']}

            aliases = value_like_fuzzy_long_names(aliases)

            if 'aliases' in parserkw:
                parserkw['aliases'] = value_like_fuzzy_long_names(list(parserkw['aliases']) + list(aliases))
            else:
                if aliases:
                    parserkw['aliases'] = aliases

            # Argparse aliases should be unique and should not include the main command.
            if parserkw.get('aliases'):
                seen = set()
                unique_aliases = []
                for alias in parserkw['aliases']:
                    if alias == main_cmd:
                        continue
                    if alias in seen:
                        continue
                    seen.add(alias)
                    unique_aliases.append(alias)
                parserkw['aliases'] = unique_aliases

            if cmdinfo['is_modal']:
                # Note sure if we need to do the prog modification here
                # parserkw['prog'] = ' '.join([parser.prog, main_cmd])
                modal_inst = cmdinfo['subconfig']
                modal_parser = command_subparsers.add_parser(
                    main_cmd, **parserkw)
                modal_parser = modal_inst.argparse(parser=modal_parser)
                modal_parser.set_defaults(__main_function__=cmdinfo['main_func'])
                modal_parser.set_defaults(__submodal__=modal_inst)
            else:
                # When an error occurs we want usage to print out the command
                # the user used to invoke the subparser. has a few corner
                # cases, but this works better than defaults
                parserkw['prog'] = ' '.join([parser.prog, main_cmd])
                subparser = command_subparsers.add_parser(
                    main_cmd, **parserkw)
                subparser = cmdinfo['subconfig'].argparse(subparser)
                subparser.set_defaults(__main_function__=cmdinfo['main_func'])
                subparser.set_defaults(__submodal__=None)  # indicate to the parser that we parsed a leaf command
        return parser

    build_parser = argparse

    def _handle_autocomplete(self, parser, autocomplete='auto'):
        if autocomplete:
            try:
                import argcomplete
                # Need to run: "$(register-python-argcomplete xdev)"
                # or activate-global-python-argcomplete --dest=-
                # activate-global-python-argcomplete --dest ~/.bash_completion.d
                # To enable this.
            except ImportError:
                argcomplete = None
                if autocomplete != 'auto':
                    raise
        else:
            argcomplete = None

        if argcomplete is not None:
            argcomplete.autocomplete(parser)

    @class_or_instancemethod  # type: ignore
    def main(self,
             argv: Optional[Sequence[str]] = None,
             strict: bool = True,
             autocomplete: Any = 'auto',
             _noexit: bool = False) -> Any:
        """
        Execute the modal CLI as the main script
        """
        if diagnostics.DEBUG_MODAL:
            if argv is None:
                print(f'[kwconf.modal.ModalCLI.main] Calling main of {self} with argv={argv}, sys.argv={sys.argv}')
            else:
                print(f'[kwconf.modal.ModalCLI.main] Calling main of {self} with argv={argv}')

        # Create an instance of we called as a classmethod
        if isinstance(self, type):
            self = self()  # type: ignore[call-arg,assignment]

        parser = self.argparse()
        # parser.exit_on_error = False
        self._handle_autocomplete(parser=parser, autocomplete=autocomplete)

        if diagnostics.DEBUG_MODAL:
            _dump_parser(parser)
            print('[kwconf.modal.ModalCLI.main] parsing args')

        # To handle opaque sub commands we always parse known arguments but we
        # will raise an error if strict and the subcommand is not opqaue
        if isinstance(argv, (int, bool)) and argv:
            argv = None
        try:
            ns, unknown_args = parser.parse_known_args(args=argv)
        except SystemExit as ex:
            if diagnostics.DEBUG_MODAL:
                print(f'[kwconf.modal.ModalCLI.main] Modal main {self} caught an SystemExit error {ex}')
            if _noexit:
                return 1
            raise
        kw = ns.__dict__

        if diagnostics.DEBUG_MODAL:
            print(f'[kwconf.modal.ModalCLI.main] Modal main {self} parsed arguments: ' + ub.urepr(kw, nl=1))  # type: ignore
            if unknown_args:
                print(f'[kwconf.modal.ModalCLI.main] Modal main {self} unknown args: ' + ub.urepr(unknown_args, nl=1))  # type: ignore

        __opaque_main__ = kw.pop('__opaque_main__', None)
        if __opaque_main__ is not None:
            # If we are calling an opaque function we are going to invoke it
            # directly which means it will reparse the arguments. We patch
            # sys.argv while this happens.
            if diagnostics.DEBUG_MODAL:
                print(f'Want to call __opaque_main__={__opaque_main__}')
            forwarded = unknown_args[1:] if unknown_args[:1] == ["--"] else unknown_args
            # TODO: need a better leading arg for the command name, we can
            # probably add one to the metadata.
            their_argv = ['opaque-script-name'] + forwarded
            with _temp_argv(their_argv):
                return __opaque_main__()

        if strict and unknown_args:
            from gettext import gettext
            msg = gettext('unrecognized arguments: %s') % ' '.join(unknown_args)
            try:
                if getattr(parser, 'exit_on_error', True):
                    # Also use the extended deepest parser logic we added to
                    # the extended parser here.
                    deepest = parser._deepest_subparser_for_argv(argv)
                    if deepest is None:
                        deepest = self
                    # deepest.print_usage()
                    deepest.error(msg)  # type: ignore
                else:
                    from argparse import ArgumentError
                    raise ArgumentError(None, msg)
            except SystemExit as ex:
                if diagnostics.DEBUG_MODAL:
                    print(f'[kwconf.modal.ModalCLI.main] Modal main {self} caught an SystemExit error {ex}')
                if _noexit:
                    return 1
                raise

        # NOTE: This is a funky way of handling allowing modals to requst
        # versions. There are special variable we assume only modal CLIs
        # define. If a subcli defines them, then our assumptions break.
        version_request = kw.pop('__modal_version_request__', None)
        sub_modal = kw.pop('__submodal__', None)
        sub_main = kw.pop('__main_function__', None)
        if version_request:
            if sub_modal is None:
                if diagnostics.DEBUG_MODAL:
                    print('[kwconf.modal.ModalCLI.main] Our modal CLI got a modal version request for the root modal')
                print(self.version)
            else:
                if diagnostics.DEBUG_MODAL:
                    print(f'[kwconf.modal.ModalCLI.main] Our modal CLI got a modal version request for a submodal {sub_modal}')
                print(sub_modal.version)
            return 0

        if sub_modal is not None:
            # This case happens when a submodal is not given any commands
            if diagnostics.DEBUG_MODAL:
                print(f'[kwconf.modal.ModalCLI.main] returned main, but it belongs to a different ModalCLI {sub_modal}, using our hack to print help and exit')
            sub_modal.argparse().print_usage(sys.stderr)
            # sub_modal.argparse().print_help(sys.stderr)
            if not _noexit:
                raise NoCommandError('A submodal CLI was executed but no command was given.')
            return 1

        if sub_main is None:
            # This case happens when the root modal is not given any commands
            if diagnostics.DEBUG_MODAL:
                print('[kwconf.modal.ModalCLI.main] returned modal options did not specify the main function, printing help and exiting')
            parser.print_usage(sys.stderr)
            # parser.print_help(sys.stderr)
            if not _noexit:
                raise NoCommandError('A modal CLI was executed but no command was given.')
            return 1

        # Check how main wants to be invoked
        # We are making the assumption that subcommands register a main
        # classmethod, which will have a control argument that will tell it to
        # use the given input arguments instead of reparsing the CLI (which we
        # already did).
        # TODO: should ensure this works in a standardized way
        import inspect
        main_sig = inspect.signature(sub_main)
        control_kw = {}
        if 'argv' in main_sig.parameters:
            # Use current standard argument control
            control_kw['argv'] = False

        try:
            ret = sub_main(**control_kw, **kw)
        except Exception as ex:
            print('ERROR ex = {!r}'.format(ex))
            raise
            return 1
        else:
            if ret is None:
                ret = 0
            return ret

    run = main  # alias for backwards compatibility, TODO: deprecate and remove


def _dump_parser(parser, indent=0):
    import argparse
    pad = "  " * indent
    print(f"{pad}Parser: {parser.prog!r}")
    for a in parser._actions:
        opts = ", ".join(a.option_strings) if a.option_strings else a.dest
        print(f"{pad}  Arg: {opts}  (action={a.__class__.__name__})")

    # Find subparsers (if any)
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            for name, sp in a.choices.items():
                print(f"{pad}  Subcommand: {name}")
                _dump_parser(sp, indent + 1)


class NoCommandError(SystemExit):
    ...


from contextlib import contextmanager  # NOQA


@contextmanager
def _temp_argv(argv):
    old = sys.argv[:]
    sys.argv[:] = argv
    try:
        yield
    finally:
        sys.argv[:] = old
