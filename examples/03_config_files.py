"""
Loading and dumping config files.

The important pattern is: defaults come from the class, files or Python data
update those defaults, and CLI arguments are the final override layer. The
script prints the resolved config and the concrete Python types produced by
file loading plus CLI coercion.

DEMO:
    Command::

        python examples/03_config_files.py --config examples/data/report.yaml --limit=3 --format=json --metadata '{owner: bob, priority: 1}' --labels urgent external

    Expected output::

        RESOLVED CONFIG:
        title: weekly status
        limit: 3
        format: json
        output: report.html
        labels:
        - urgent
        - external
        metadata:
          owner: bob
          priority: 1
        RESOLVED TYPES:
        __class__: ReportConfig
        title: str
        limit: int
        format: str
        output: str
        labels:
          list_of: str
        metadata:
          owner: str
          priority: int
"""

import _bootstrap  # noqa: F401
from _bootstrap import print_resolved_config
import kwconf as kw


class ReportConfig(kw.Config):
    __special_options__ = True

    title: str = 'demo report'
    limit: int = 10
    format: str = kw.Value('markdown', choices=['markdown', 'json', 'html'])
    output: str = 'report.md'
    labels: list = kw.Value(default_factory=list, nargs='*')
    metadata: dict = kw.Value(default_factory=dict, type='yaml')

    def __post_init__(self):
        # Explicit migration / normalization hooks belong here.
        if isinstance(self.labels, str):
            self.labels = [self.labels]


def main(argv=None):
    config = ReportConfig.cli(argv=argv)
    print_resolved_config(config)
    return config


if __name__ == '__main__':
    main()
