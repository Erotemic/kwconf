"""
Test porting back and forth to / from argparse
"""
import kwconf
import ubelt as ub
import argparse


def port_kwconf_from_argparse():
    """
    xdoctest ~/code/kwconf/tests/test_argparse_roundtrip.py port_kwconf_from_argparse
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--flag1', action='count')
    parser.add_argument('--flag2', action='store_true')
    parser.add_argument('--flag3', action='count', help='specified looooooooooooooooooooooonggg help ')
    parser.add_argument('--flag4', action='store_true', help='specified help')

    text = kwconf.DataConfig.port_argparse(parser)
    print(text)

    tq = '"""'

    want = ub.codeblock(
        """
        import ubelt as ub
        import kwconf

        class MyConfig(kwconf.DataConfig):
            """ + tq + """
            $
            """ + tq + """
            flag1 = kwconf.Value(None, isflag='counter', help=None)
            flag2 = kwconf.Value(False, isflag=True, help=None)
            flag3 = kwconf.Value(None, isflag='counter', help=ub.paragraph(
                    '''
                    specified looooooooooooooooooooooonggg help
                    '''))
            flag4 = kwconf.Value(False, isflag=True, help='specified help')
        """)
    print(text)
    print(want)
    assert text == want

    ns = {}
    exec(text, ns, ns)
    MyConfig = ns['MyConfig']

    # Note: we currently can't create argparse objects with the same flexible
    # flag or key/value specification. Future work may fix this.
    recon = MyConfig().port_to_argparse()
    print(recon)


def port_argparse_from_kwconf():
    """
    xdoctest ~/code/kwconf/tests/test_argparse_roundtrip.py port_argparse_from_kwconf
    """

    class MyConfig(kwconf.DataConfig):
        param1 = kwconf.Value(None, type=str, help='help text')

    argparse_text = MyConfig().port_to_argparse()

    import re
    argparse_text = re.sub(
        r"(description=')[^']*'",
        r"\1kwconf',",
        argparse_text, count=1)

    want = ub.codeblock(
        """
        import argparse
        parser = argparse.ArgumentParser(
            description='kwconf',
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument('--param1', help='help text', type=str, dest='param1', required=False)
        """)
    print(argparse_text)
    print(want)
    assert argparse_text == want


def port_argparse_from_kwconf_with_unwrapped_values():
    """
    xdoctest ~/code/kwconf/tests/test_argparse_roundtrip.py port_argparse_from_kwconf_with_unwrapped_values
    """

    class MyConfig(kwconf.DataConfig):
        option1 = kwconf.Value('default1', help='option1 help')
        option2 = kwconf.Value('default2', help='option2 help')
        option3 = kwconf.Value('default3', help='option3 help')
        option4 = 'default4'

    argparse_text = MyConfig().port_to_argparse()
    print(argparse_text)

    argparse_text = re.sub(
        r"(description=')[^']*'",
        r"\1kwconf',",
        argparse_text, count=1)

    want = ub.codeblock(
        """
        import argparse
        parser = argparse.ArgumentParser(
            prog='MyConfig',
            description='kwconf',
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument('--option1', help='option1 help', default='default1', dest='option1', required=False)
        parser.add_argument('--option2', help='option2 help', default='default2', dest='option2', required=False)
        parser.add_argument('--option3', help='option3 help', default='default3', dest='option3', required=False)
        parser.add_argument('--option4', help='', default='default4', dest='option4', required=False)
        """)
    print(want)
    assert argparse_text == want


def test_port_argparse_with_optin_fancy_features():
    class MyConfig(kwconf.DataConfig):
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
