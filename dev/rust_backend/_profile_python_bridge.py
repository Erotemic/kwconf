#!/usr/bin/env python3
"""Repeatable Python/PyO3 workload used by profile_backend.py."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_DPATH = Path(__file__).resolve().parents[2]
if str(REPO_DPATH) not in sys.path:
    sys.path.insert(0, str(REPO_DPATH))

import kwconf
from kwconf import _rust


def make_class(size: int) -> type[kwconf.Config]:
    names = [f'option_{idx}' for idx in range(size)]
    namespace: dict[str, object] = {
        '__annotations__': {name: str for name in names},
        '__cli_backend__': 'rust',
    }
    namespace.update({name: '' for name in names})
    return type('ProfileConfig', (kwconf.Config,), namespace)


def main() -> None:
    workload = sys.argv[1]
    size = int(sys.argv[2])
    iterations = int(sys.argv[3])
    cls = make_class(size)
    config = cls()
    argv = [f'--option-{size - 1}=value']
    compiled = _rust.compile_config(config)
    completion_index = _rust.compile_completion_index(config)

    checksum = 0
    if workload == 'pyo3-parse':
        for _ in range(iterations):
            result = compiled.parser.parse(argv)
            checksum += len(result[0])
    elif workload == 'rust-bridge':
        for _ in range(iterations):
            result = _rust.parse_compiled(config, compiled, argv, strict=True)
            checksum += len(result.values) if result is not None else 0
    elif workload == 'kwconf-cli':
        cls.cli(argv=argv, autocomplete=False, special_options=False)
        for _ in range(iterations):
            result = cls.cli(argv=argv, autocomplete=False, special_options=False)
            checksum += len(result)
    elif workload == 'completion-pyo3':
        for _ in range(iterations):
            complete_values = getattr(completion_index, 'complete_values', None)
            if complete_values is None:
                result = completion_index.complete([], '--option-')
            else:
                result = complete_values([], '--option-')
            checksum += 0 if result is None else len(result)
    else:
        raise SystemExit(f'unknown workload: {workload}')
    print(f'checksum={checksum}')


if __name__ == '__main__':
    main()
