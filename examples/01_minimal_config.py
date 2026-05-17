"""
Minimal kwconf usage.

This is the shape to copy into a small script: declare a Config subclass,
parse it with `.cli(...)`, and then pass the resulting object into your real
function.
"""

import _bootstrap  # noqa: F401
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
    plan = plan_resize(config)
    print(plan)
    return plan


def demo():
    config = ResizeConfig.cli(argv=[
        '--width=128',
        '--height=96',
        '--method=lanczos',
        '--dst=thumb.png',
        '--tags', 'demo', 'small',
        '--dry-run',
    ])
    assert config.width == 128
    assert config.output == 'thumb.png'
    assert config.tags == ['demo', 'small']
    assert config.dry_run is True

    # Instances are both namespace-like and dict-like.
    assert config['width'] == config.width
    assert plan_resize(config)['size'] == (128, 96)

    # Programmatic construction uses the same schema and normalization.
    assert ResizeConfig(width=64, height=64).width == 64
    print('01_minimal_config: ok')


if __name__ == '__main__':
    main()
