

def test_paths_with_commas():
    from kwconf.value import Value, Path

    self = Value('key')
    self.update('/path/with,commas')
    print('self.value = {!r}'.format(self.value))
    assert isinstance(self.value, list), 'without specifying types a string with commas will be smartcast'

    self = Value('key', type=str)
    self.update('/path/with,commas')
    print('self.value = {!r}'.format(self.value))
    assert isinstance(self.value, str), 'specifying a type should prevent smartcast'

    self = Path('key')
    self.update('/path/with,commas')
    print('self.value = {!r}'.format(self.value))
    assert isinstance(self.value, str), 'specifying a type should prevent smartcast'


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

    # In the past setting argv=True did cause an error
    config = TestConfig.cli(default=kw, argv=True)
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
