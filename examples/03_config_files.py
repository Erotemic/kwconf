"""
Loading and dumping config files.

The important pattern is: defaults come from the class, files or Python data
update those defaults, and CLI arguments are the final override layer.
"""

import json
import tempfile
from pathlib import Path

import _bootstrap  # noqa: F401
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
    print(config.dumps(mode='yaml'))
    return config


def demo():
    with tempfile.TemporaryDirectory() as dpath:
        dpath = Path(dpath)
        yaml_path = dpath / 'report.yaml'
        json_path = dpath / 'report.json'

        yaml_path.write_text(
            'title: weekly status\n'
            'limit: 20\n'
            'format: html\n'
            'metadata: {owner: alice, priority: 2}\n'
        )
        json_path.write_text(json.dumps({'title': 'from json', 'limit': 5}))

        # Load a YAML file through the ordinary data argument.
        config = ReportConfig.cli(data=str(yaml_path), argv=['--limit=3'])
        assert config.title == 'weekly status'
        assert config.limit == 3  # CLI wins over file data.
        assert config.metadata == {'owner': 'alice', 'priority': 2}

        # The opt-in special --config option is useful for real CLIs.
        config2 = ReportConfig.cli(argv=['--config', str(json_path), '--format=json'])
        assert config2.title == 'from json'
        assert config2.limit == 5
        assert config2.format == 'json'

        # Dump / load roundtrip.
        dumped = config2.dumps(mode='json')
        config3 = ReportConfig()
        config3.load(dumped, mode='json', argv=False)
        assert config3.asdict() == config2.asdict()

    print('03_config_files: ok')


if __name__ == '__main__':
    main()
