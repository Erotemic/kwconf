"""
Nested config trees and selector choices.

Use SubConfig for structured objects that have their own schemas. Dotted CLI
keys update leaves. Selector choices switch one implementation for another.
"""

import tempfile
from pathlib import Path

import _bootstrap  # noqa: F401
import kwconf as kw


class Adam(kw.Config):
    lr: float = 0.001
    beta1: float = 0.9


class SGD(kw.Config):
    lr: float = 0.01
    momentum: float = 0.9


class Dataset(kw.Config):
    root: str = 'demo-data'
    augment = kw.Flag(False)


class TrainConfig(kw.Config):
    __special_options__ = True

    dataset = kw.SubConfig(Dataset)
    optim = kw.SubConfig(Adam, choices={'adam': Adam, 'sgd': SGD})
    epochs: int = 10


def describe(config):
    return {
        'dataset_root': config.dataset.root,
        'augment': config.dataset.augment,
        'optim_cls': config.optim.__class__.__name__,
        'optim': config.optim.asdict(),
        'epochs': config.epochs,
    }


def main(argv=None):
    config = TrainConfig.cli(argv=argv, allow_subconfig_overrides=True)
    summary = describe(config)
    print(summary)
    return summary


def demo():
    config = TrainConfig.cli(argv=[
        '--dataset.root=data/images',
        '--dataset.augment',
        '--optim=sgd',
        '--optim.momentum=0.7',
        '--epochs=3',
    ], allow_subconfig_overrides=True)
    assert isinstance(config.optim, SGD)
    assert config.dataset.root == 'data/images'
    assert config.optim.momentum == 0.7

    with tempfile.TemporaryDirectory() as dpath:
        yaml_path = Path(dpath) / 'train.yaml'
        yaml_path.write_text(
            'optim:\n'
            '  __class__: sgd\n'
            '  lr: 0.2\n'
            '  momentum: 0.6\n'
            'epochs: 5\n'
        )
        config2 = TrainConfig.cli(argv=['--config', str(yaml_path), '--optim.lr=0.05'])
        assert isinstance(config2.optim, SGD)
        assert config2.optim.lr == 0.05
        assert config2.epochs == 5

    print('04_nested_configs: ok')


if __name__ == '__main__':
    main()
