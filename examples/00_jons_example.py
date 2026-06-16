r"""
Minimal kwconf usage.

This is the shape to copy into a small script: declare a Config subclass,
parse it with `.cli(...)`, and then pass the resulting object into your real
function. The output prints each resolved field as a colorized
``name : type = value`` row, then shows the plain application plan that would
be handed to real work.

DEMO:
    Command::

        python examples/00_jons_example.py

        python examples/00_jons_example.py \
            --tags_typed 1,2,3  \
            --tags_untyped 1,2,3 \
            --tags_yaml "[1,2,3]" 

        
        # I don't like this behavior. 
        python examples/00_jons_example.py --tags_typed 1,2,3

        # I don't like this behavior. 
        python examples/00_jons_example.py --tags_untyped 1,2,3


        # I do like list
        python examples/00_jons_example.py --tags_yaml "[1,2,3]"
"""

import _bootstrap  # noqa: F401
from _bootstrap import _dump_text, print_resolved_config, print_rule, rich_print

import kwconf as kw


class JonsConfig(kw.Config):
    """Options for a tiny image-resize command."""

    width: int = kw.Value(512, short_alias=['w'], help='output width')
    height: int = kw.Value(512, short_alias=['H'], help='output height')
    method: str = kw.Value('bilinear', choices=['nearest', 'bilinear', 'lanczos'])
    output: str = kw.Value('resized.png', alias=['dst'], help='output file')


    tags_untyped: list = kw.Value([], help='free-form labels')

    tags1: list = kw.Value([], nargs='+', help='free-form labels') # Is this stripping? ` --tags1 f f ' '` parses as ['f', 'f']?

    tags_typed: list = kw.Value([], help='free-form labels')

    tags_yaml: list = kw.Value([], type='yaml', help='free-form labels')

    dry_run = kw.Flag(False, help='print work without doing it')

    def __post_init__(self):
        # Post-init is the right place for explicit normalization that would
        # otherwise be too magical. Here we keep it simple: validate dimensions.
        if self.width <= 0 or self.height <= 0:
            raise ValueError('width and height must be positive')


def main(argv=None):
    print_rule('kwconf example 01: minimal Config')
    rich_print(
        'The CLI starts as strings; kwconf resolves them into typed Python '
        'fields that downstream code can use directly.',
        style='white',
    )
    config = JonsConfig.cli(argv=argv)
    print_resolved_config(config)
    return config


if __name__ == '__main__':
    main()
