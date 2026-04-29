

def test_paths_with_commas():
    """
    kwconf intentionally does NOT split comma-separated strings into lists
    (a deliberate departure from scriptconfig). A path that contains commas
    must round-trip as a string both with and without an explicit type.
    """
    from kwconf.value import Value

    self = Value('key')
    self.update('/path/with,commas')
    print('self.value = {!r}'.format(self.value))
    assert self.value == '/path/with,commas'

    self = Value('key', type=str)
    self.update('/path/with,commas')
    print('self.value = {!r}'.format(self.value))
    assert self.value == '/path/with,commas'


def test_paths_with_commas_in_config():
    import kwconf
    class TestConfig(kwconf.DataConfig):
        __default__ = {
            'key': kwconf.Value(None, type=str),
        }

    kw = {
        'key': '/path/with,commas',
    }
    config = TestConfig.cli(default=kw, argv=False)
    print(config['key'])
    assert isinstance(config['key'], str), 'specifying a type should prevent smartcast'

    # Pre-0.7 the bare ``argv=True`` path could raise on default values
    # containing commas. Using an explicit empty argv here to avoid binding
    # to the test runner's sys.argv while still exercising the cli path.
    config = TestConfig.cli(default=kw, argv=[])
    print(config['key'])
    assert isinstance(config['key'], str), 'specifying a type should prevent smartcast'


def test_globstr_with_nargs():
    from os.path import join
    import ubelt as ub
    import kwconf
    dpath = ub.Path.appdir('kwconf', 'tests', 'files').ensuredir()
    ub.touch(join(dpath, 'file1.txt'))
    ub.touch(join(dpath, 'file2.txt'))
    ub.touch(join(dpath, 'file3.txt'))

    class TestConfig(kwconf.DataConfig):
        __default__ = {
            'paths': kwconf.Value(None, nargs='+'),
        }

    argv = '--paths {dpath}/*'.format(dpath=dpath)
    config = TestConfig.cli(argv=argv)

    # ub.cmd(f'echo {dpath}/*', shell=True)

    import glob
    argv = '--paths ' + ' '.join(list(glob.glob(join(dpath, '*'))))
    config = TestConfig.cli(argv=argv)

    argv = '--paths=' + ','.join(list(glob.glob(join(dpath, '*'))))
    config = TestConfig.cli(argv=argv)  # NOQA
