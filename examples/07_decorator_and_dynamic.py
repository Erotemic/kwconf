"""
Decorator and dynamic-class helpers.

Most new code should inherit from kw.Config directly. These helpers are useful
when migrating old code or generating schemas from another source. The script
prints both configs as ``name : type = value`` rows to show that the resolved
objects still use the same Config machinery.

DEMO:
    Command::

        python examples/07_decorator_and_dynamic.py --chip-size '[512, 512]' -j 8
"""

import _bootstrap  # noqa: F401
from _bootstrap import print_resolved_config

import kwconf as kw


@kw.dataconf
class DecoratedConfig:
    chip_size: list = kw.Value([256, 256], type='yaml', help='tile size')
    channels: str = 'red|green|blue'
    workers: int = kw.Value(2, short_alias=['j'])


DynamicConfig = kw.define({
    'alpha': kw.Value(1, type=int),
    'name': 'generated',
}, name='DynamicConfig')


def main(argv=None):
    config = DecoratedConfig.cli(argv=argv)
    print_resolved_config(config, label='DECORATED CONFIG')

    dynamic = DynamicConfig.cli(argv=['--alpha=3'])
    print_resolved_config(dynamic, label='DYNAMIC CONFIG')
    return config


if __name__ == '__main__':
    main()
