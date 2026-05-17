"""Run every kwconf example with deterministic arguments."""

import _bootstrap  # noqa: F401
import runpy
from pathlib import Path


EXAMPLE_FILES = [
    '01_minimal_config.py',
    '02_cli_surface.py',
    '03_config_files.py',
    '04_nested_configs.py',
    '05_modal_cli.py',
    '06_large_scale_app.py',
    '07_decorator_and_dynamic.py',
]


def main():
    base = Path(__file__).parent
    for name in EXAMPLE_FILES:
        namespace = runpy.run_path(str(base / name))
        namespace['demo']()
    print('all examples: ok')


if __name__ == '__main__':
    main()
