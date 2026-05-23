"""
Minimal kwconf usage.

This is the shape to copy into a small script: declare a Config subclass,
parse it with `.cli(...)`, and then pass the resulting object into your real
function. The script prints the resolved config and the concrete Python types
produced by CLI coercion.

DEMO:
    Command::

        python examples/01_minimal_config.py --width=128 --height=96 --method=lanczos --dst=thumb.png --tags demo small --dry-run

    Expected output::

        RESOLVED CONFIG:
        width: 128
        height: 96
        method: lanczos
        output: thumb.png
        tags:
        - demo
        - small
        dry_run: true
        RESOLVED TYPES:
        __class__: ResizeConfig
        width: int
        height: int
        method: str
        output: str
        tags:
          list_of: str
        dry_run: bool
        PLAN:
        {'size': (128, 96), 'method': 'lanczos', 'output': 'thumb.png', 'tags': ['demo', 'small'], 'dry_run': True}
"""

import _bootstrap  # noqa: F401
from _bootstrap import print_resolved_config
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
    config = ResizeConfig.cli(argv=argv)
    print_resolved_config(config)
    plan = plan_resize(config)
    print('PLAN:')
    print(plan)
    return config


if __name__ == '__main__':
    main()
