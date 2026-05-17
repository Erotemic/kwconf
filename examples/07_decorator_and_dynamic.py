"""
Decorator and dynamic-class helpers.

Most new code should inherit from kw.Config directly. These helpers are useful
when migrating old code or generating schemas from another source.
"""

import _bootstrap  # noqa: F401
import kwconf as kw


@kw.dataconf
class DecoratedConfig:
    chip_size: tuple = kw.Value((256, 256), help='tile size')
    channels: str = 'red|green|blue'
    workers: int = kw.Value(2, short_alias=['j'])


def main(argv=None):
    config = DecoratedConfig.cli(argv=argv)
    print(config.asdict())
    return config


def demo():
    config = DecoratedConfig.cli(argv=['--chip-size', '512,512', '-j', '8'])
    assert isinstance(config, kw.Config)
    assert config.workers == 8

    DynamicConfig = kw.define({
        'alpha': kw.Value(1, type=int),
        'name': 'generated',
    }, name='DynamicConfig')
    dynamic = DynamicConfig.cli(argv=['--alpha=3'])
    assert isinstance(dynamic, kw.Config)
    assert dynamic.alpha == 3
    assert dynamic.name == 'generated'
    print('07_decorator_and_dynamic: ok')


if __name__ == '__main__':
    main()
