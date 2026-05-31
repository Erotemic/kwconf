"""
Minimal kwconf usage.

This is the shape to copy into a small script: declare a Config subclass,
parse it with `.cli(...)`, and then pass the resulting object into your real
function. The output prints each resolved field as a colorized
``name : type = value`` row, then shows the plain application plan that would
be handed to real work.

DEMO:
    Command::

        python examples/01_minimal_config.py --width=128 --height=96 --method=lanczos --dst=thumb.png --tags demo small --dry-run
"""

import _bootstrap  # noqa: F401
from _bootstrap import _dump_text, print_resolved_config, print_rule, rich_print

import kwconf as kw


class ResizeConfig(kw.Config):
    """Options for a tiny image-resize command."""

    width: int = kw.Value(512, short_alias=['w'], help='output width')
    height: int = kw.Value(512, short_alias=['H'], help='output height')
    method: str = kw.Value('bilinear', choices=['nearest', 'bilinear', 'lanczos'])
    output: str = kw.Value('resized.png', alias=['dst'], help='output file')
    tags: list = kw.Value(default_factory=list, nargs='*', help='free-form labels')
    dry_run = kw.Flag(False, help='print work without doing it')

    def __post_init__(self):
        # Post-init is the right place for explicit normalization that would
        # otherwise be too magical. Here we keep it simple: validate dimensions.
        if self.width <= 0 or self.height <= 0:
            raise ValueError('width and height must be positive')


def plan_resize(config):
    """Return a small, testable plan instead of doing real image IO."""
    return {
        'size': (config.width, config.height),
        'method': config.method,
        'output': config.output,
        'tags': list(config.tags),
        'dry_run': config.dry_run,
    }


def main(argv=None):
    print_rule('kwconf example 01: minimal Config')
    rich_print(
        'The CLI starts as strings; kwconf resolves them into typed Python '
        'fields that downstream code can use directly.',
        style='white',
    )
    config = ResizeConfig.cli(argv=argv)
    print_resolved_config(config)
    print_rule('Why this is interesting')
    rich_print('--dst populated output because output declared alias=[\'dst\'].')
    rich_print('--dry-run became True because dry_run is a kw.Flag.')
    rich_print('--tags demo small stayed a list instead of a single string.')
    rich_print(
        'width and height are real ints, so downstream code can use them directly.'
    )
    plan = plan_resize(config)
    rich_print('PLAN:', style='bold yellow')
    print(_dump_text(plan))
    return config


if __name__ == '__main__':
    main()
