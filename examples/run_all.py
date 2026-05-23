"""Run every kwconf example command documented in the DEMO sections."""

import shlex
import subprocess
import sys
from pathlib import Path

import _bootstrap  # noqa: F401


EXAMPLE_COMMANDS = [
    [
        sys.executable,
        'examples/01_minimal_config.py',
        '--width=128', '--height=96', '--method=lanczos', '--dst=thumb.png',
        '--tags', 'demo', 'small', '--dry-run',
    ],
    [
        sys.executable,
        'examples/02_cli_surface.py',
        'raw.dat', 'clean.dat', '-vvv', '-j', '4', '--dry-run', '--mode=safe',
        '--include', 'metadata', 'features',
    ],
    [
        sys.executable,
        'examples/03_config_files.py',
        '--config', 'examples/data/report.yaml', '--limit=3', '--format=json',
        '--metadata', '{owner: bob, priority: 1}', '--labels', 'urgent', 'external',
    ],
    [
        sys.executable,
        'examples/04_nested_configs.py',
        '--dataset.root=data/images', '--dataset.augment', '--optim=sgd',
        '--optim.momentum=0.7', '--epochs=3',
    ],
    [
        sys.executable,
        'examples/05_modal_cli.py',
        'fit', '--epochs=3', '--dry-run',
    ],
    [
        sys.executable,
        'examples/06_large_scale_app.py',
        'fit', '--profile=debug', '--trainer.max_steps=25', '--optim.lr=0.01', '--dry_run',
    ],
    [
        sys.executable,
        'examples/06_large_scale_app.py',
        'train-direct', '--config', 'examples/data/large_train.yaml',
        '--optim.lr=0.01', '--dry-run', '--logging.tags', 'example', 'large-scale',
    ],
    [
        sys.executable,
        'examples/07_decorator_and_dynamic.py',
        '--chip-size', '[512, 512]', '-j', '8',
    ],
]


def main():
    repo_root = Path(__file__).resolve().parents[1]
    for command in EXAMPLE_COMMANDS:
        rel_command = [command[0], *command[1:]]
        print('$ ' + shlex.join(rel_command), flush=True)
        subprocess.run(command, cwd=repo_root, check=True)
    print('all example commands: ok')


if __name__ == '__main__':
    main()
