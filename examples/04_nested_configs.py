"""
Nested config trees and selector choices.

Use SubConfig for structured objects that have their own schemas. Dotted CLI
keys update leaves. Selector choices switch one implementation for another.
The script prints the resolved config and the concrete Python types produced by
CLI coercion, including the selected nested config classes.

DEMO:
    Command::

        python examples/04_nested_configs.py --dataset.root=data/images --dataset.augment --optim=sgd --optim.momentum=0.7 --epochs=3

    Expected output::

        RESOLVED CONFIG:
        dataset:
          root: data/images
          augment: true
          __class__: __main__.Dataset
        optim:
          lr: 0.01
          momentum: 0.7
          __class__: sgd
        epochs: 3
        RESOLVED TYPES:
        __class__: TrainConfig
        dataset:
          __class__: Dataset
          root: str
          augment: bool
        optim:
          __class__: SGD
          lr: float
          momentum: float
        epochs: int
        SUMMARY:
        {'dataset_root': 'data/images', 'augment': True, 'optim_cls': 'SGD', 'optim': {'lr': 0.01, 'momentum': 0.7}, 'epochs': 3}
"""

import _bootstrap  # noqa: F401
from _bootstrap import print_resolved_config
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
    print_resolved_config(config)
    summary = describe(config)
    print('SUMMARY:')
    print(summary)
    return config


if __name__ == '__main__':
    main()
