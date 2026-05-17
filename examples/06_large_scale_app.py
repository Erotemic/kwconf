"""
A larger, repo-scale pattern.

This example sketches a research pipeline with nested configs for datasets,
models, optimizers, trainers, and logging. The commands only print plans, but
this is the structure you would scale up for real training / evaluation code.
"""

from pathlib import Path

import _bootstrap  # noqa: F401
import kwconf as kw


class FolderDataset(kw.Config):
    root: str = 'data/images'
    channels: list = kw.Value(default_factory=lambda: ['red', 'green', 'blue'], type='yaml')
    cache = kw.Flag(False)


class CocoDataset(kw.Config):
    ann_file: str = 'annotations.json'
    image_root: str = 'images'
    category: str = 'zebra'


class ResNet(kw.Config):
    depth: int = kw.Value(50, choices=[18, 34, 50, 101])
    pretrained = kw.Flag(True)


class UNet(kw.Config):
    depth: int = 5
    width: int = 64


class Adam(kw.Config):
    lr: float = 0.001
    beta1: float = 0.9


class SGD(kw.Config):
    lr: float = 0.01
    momentum: float = 0.9


class Trainer(kw.Config):
    max_steps: int = 100
    batch_size: int = 4
    accumulate_grad_batches: int = 1
    precision: str = kw.Value('fp32', choices=['fp32', 'fp16', 'bf16'])


class Logging(kw.Config):
    level: str = kw.Value('INFO', choices=['DEBUG', 'INFO', 'WARNING'])
    run_name: str = 'auto'
    tags: list = kw.Value(default_factory=list, nargs='*')


class TrainConfig(kw.Config):
    __special_options__ = True
    __description__ = 'Train a model with nested, selectable components.'

    profile: str = kw.Value('local', choices=['local', 'debug', 'cluster'])
    dataset = kw.SubConfig(FolderDataset, choices={
        'folder': FolderDataset,
        'coco': CocoDataset,
    })
    model = kw.SubConfig(ResNet, choices={
        'resnet': ResNet,
        'unet': UNet,
    })
    optim = kw.SubConfig(Adam, choices={
        'adam': Adam,
        'sgd': SGD,
    })
    trainer = kw.SubConfig(Trainer)
    logging = kw.SubConfig(Logging)
    dry_run = kw.Flag(False)

    def __post_init__(self):
        if self.logging.run_name == 'auto':
            self.logging.run_name = f'{self.profile}-{self.model.__class__.__name__.lower()}'


class EvalConfig(kw.Config):
    __special_options__ = True
    checkpoint: str = 'runs/latest/checkpoint.pt'
    dataset = kw.SubConfig(CocoDataset)
    metrics: list = kw.Value(default_factory=lambda: ['accuracy'], nargs='*')


class ExportConfig(kw.Config):
    checkpoint: str = 'runs/latest/checkpoint.pt'
    output: str = 'exported-model.onnx'
    opset: int = 17


def build_train_plan(config):
    return {
        'profile': config.profile,
        'dataset_type': config.dataset.__class__.__name__,
        'model_type': config.model.__class__.__name__,
        'optim_type': config.optim.__class__.__name__,
        'max_steps': config.trainer.max_steps,
        'lr': config.optim.lr,
        'run_name': config.logging.run_name,
        'dry_run': config.dry_run,
    }


class TrainCommand(TrainConfig):
    __command__ = 'train'

    @classmethod
    def main(cls, argv=None, **kwargs):
        # ModalCLI pre-parses arguments and forwards default selector values as
        # None. Drop those empty defaults before feeding them back into Config.
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        config = cls.cli(argv=argv, data=kwargs, allow_subconfig_overrides=True)
        plan = build_train_plan(config)
        print(plan)
        return plan


class EvalCommand(EvalConfig):
    __command__ = 'eval'

    @classmethod
    def main(cls, argv=None, **kwargs):
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        config = cls.cli(argv=argv, data=kwargs)
        plan = {
            'checkpoint': config.checkpoint,
            'dataset': config.dataset.asdict(),
            'metrics': list(config.metrics),
        }
        print(plan)
        return plan


class ExportCommand(ExportConfig):
    __command__ = 'export'

    @classmethod
    def main(cls, argv=None, **kwargs):
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        config = cls.cli(argv=argv, data=kwargs)
        plan = config.asdict()
        print(plan)
        return plan


class ResearchApp(kw.ModalCLI):
    """Large-scale kwconf example app."""

    __version__ = '0.1.0'

    train = kw.ModalValue(TrainCommand, alias=['fit'])
    eval = kw.ModalValue(EvalCommand, alias=['score'])
    export = ExportCommand


def main(argv=None):
    return ResearchApp.main(argv=argv)


def demo():
    data_path = Path(__file__).parent / 'data' / 'large_train.yaml'

    # Direct command execution gets the full Config.cli behavior: --config,
    # selector choices, dotted leaf overrides, and CLI-over-file precedence.
    plan = TrainCommand.main(argv=[
        '--config', str(data_path),
        '--optim.lr=0.01',
        '--logging.tags', 'example', 'large-scale',
        '--dry-run',
    ])
    assert plan['dataset_type'] == 'FolderDataset'
    assert plan['model_type'] == 'UNet'
    assert plan['optim_type'] == 'SGD'
    assert plan['max_steps'] == 25
    assert plan['lr'] == 0.01
    assert plan['run_name'] == 'yaml-demo'
    assert plan['dry_run'] is True

    # Modal dispatch demonstrates how the same command plugs into an app.
    # The modal parser is built from the default tree, so keep this path to
    # ordinary leaf overrides and use direct Config.cli when you need selector
    # multipass parsing.
    modal_plan = ResearchApp.main(argv=[
        'fit',
        '--profile=debug',
        '--trainer.max_steps=25',
        '--optim.lr=0.01',
        '--dry_run',
    ])
    assert modal_plan['model_type'] == 'ResNet'
    assert modal_plan['optim_type'] == 'Adam'
    assert modal_plan['max_steps'] == 25
    assert modal_plan['lr'] == 0.01

    eval_plan = ResearchApp.main(argv=[
        'score',
        '--checkpoint=demo.pt',
        '--metrics', 'accuracy', 'f1',
    ])
    assert eval_plan['checkpoint'] == 'demo.pt'
    assert eval_plan['metrics'] == ['accuracy', 'f1']

    print('06_large_scale_app: ok')


if __name__ == '__main__':
    main()
