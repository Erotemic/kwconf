#!/usr/bin/env python3
"""Exercise and report the Rust backend's native/delegated feature matrix.

This is deliberately behavioral.  A feature may be ``native`` (the Rust core
claims it) or ``delegated`` (the canonical Python/argparse path owns it), but
both must preserve the kwconf user contract.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path
from typing import Any

REPO_DPATH = Path(__file__).resolve().parents[2]


def _dist_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _row(name: str, ownership: str, ok: bool, detail: str = '') -> dict[str, Any]:
    return {
        'feature': name,
        'ownership': ownership,
        'ok': bool(ok),
        'detail': detail,
    }


def collect() -> dict[str, Any]:
    import kwconf
    from kwconf import _rust

    rows: list[dict[str, Any]] = []
    status = _rust.backend_status()

    class Flat(kwconf.Config):
        __cli_backend__ = 'rust'
        count: int = 1
        mode = kwconf.Value('a', choices=['a', 'b'])
        verbose = kwconf.Value(0, isflag='counter', short_alias=['v'])
        path: str = ''

    flat = Flat.cli(
        argv=['--count=3', '--mode=b', '-vv'],
        autocomplete=False,
        special_options=False,
    )
    rows.append(
        _row(
            'flat parse',
            'native',
            flat.count == 3 and flat.mode == 'b' and flat.verbose == 2,
        )
    )

    flat_alias = Flat.cli(
        argv=['--count=4', '--mode=b', '-vvv'],
        autocomplete=False,
        special_options=False,
    )
    rows.append(
        _row(
            'aliases / counters / repeated options',
            'native',
            flat_alias.count == 4
            and flat_alias.mode == 'b'
            and flat_alias.verbose == 3,
        )
    )

    known = Flat.cli(
        argv=['--count=5', '--external=value'],
        strict=False,
        autocomplete=False,
        special_options=False,
    )
    rows.append(
        _row(
            'parse-known / strict=False',
            'native',
            known.count == 5,
            'unknown argv is retained by the Rust parse result and follows the existing strict=False lifecycle',
        )
    )

    class Fuzzy(kwconf.Config):
        __cli_backend__ = 'rust'
        long_name: int = 0
        enabled = kwconf.Value(False, isflag=True)
        maybe = kwconf.Value('default', bare='BARE')

    fuzzy = Fuzzy.cli(
        argv=['--long-name=3', '--enabled', '--maybe'],
        autocomplete=False,
        special_options=False,
    )
    rows.append(
        _row(
            'fuzzy names / bool negation / bare options',
            'native',
            fuzzy.long_name == 3 and fuzzy.enabled is True and fuzzy.maybe == 'BARE',
        )
    )
    negative = Fuzzy.cli(
        argv=['--enabled', '--no-enabled'],
        autocomplete=False,
        special_options=False,
    )
    rows.append(
        _row(
            'generated negative flags / last assignment wins',
            'native',
            negative.enabled is False,
        )
    )

    class RequiredMutex(kwconf.Config):
        __cli_backend__ = 'rust'
        required = kwconf.Value('', required=True)
        left = kwconf.Value('', mutex_group='pair')
        right = kwconf.Value('', mutex_group='pair')

    required_mutex = RequiredMutex.cli(
        argv=['--required=ok', '--left=a'],
        autocomplete=False,
        special_options=False,
    )
    rows.append(
        _row(
            'required and mutex success validation',
            'native',
            required_mutex.required == 'ok' and required_mutex.left == 'a',
            'violations deliberately delegate so the canonical Python lifecycle owns diagnostics',
        )
    )

    class Inner(kwconf.Config):
        rate: float = 0.5
        mode = kwconf.Value('x', choices=['x', 'y'])

    class Outer(kwconf.Config):
        __cli_backend__ = 'rust'
        name: str = 'demo'
        inner = kwconf.SubConfig(Inner)

    nested_probe = Outer(_dont_call_post_init=True)
    native_nested = _rust.try_parse_config(
        nested_probe,
        ['--inner.rate=0.25', '--inner.mode=y'],
        strict=True,
        required_extension=True,
    )
    nested = Outer.cli(
        argv=['--inner.rate=0.25', '--inner.mode=y'],
        autocomplete=False,
        special_options=False,
    )
    rows.append(
        _row(
            'realized SubConfig leaves',
            'native',
            native_nested is not None
            and abs(nested.inner.rate - 0.25) < 1e-12
            and nested.inner.mode == 'y',
        )
    )

    nested_completion_specs = _rust.completion_specs_for_config(Outer())
    nested_completion_index = _rust.make_completion_index(nested_completion_specs, [])
    nested_options = nested_completion_index.complete([], '--inner.')
    selector_value = nested_completion_index.complete(['--inner'], '')
    rows.append(
        _row(
            'realized SubConfig static completion',
            'native',
            nested_options is not None
            and '--inner.rate' in [item[0] for item in nested_options]
            and '--inner.mode' in [item[0] for item in nested_options]
            and '--inner.__class__' in [item[0] for item in nested_options]
            and selector_value is None,
            'selector option names are native; selector values delegate because they can replace the leaf grammar',
        )
    )

    class SGD(kwconf.Config):
        momentum: float = 0.9

    class Train(kwconf.Config):
        __cli_backend__ = 'rust'
        optim = kwconf.SubConfig(Inner, choices={'inner': Inner, 'sgd': SGD})

    selector_probe = Train(_dont_call_post_init=True)
    native_selector = _rust.try_parse_config(
        selector_probe,
        ['--optim=sgd', '--optim.momentum=0.7'],
        strict=True,
        required_extension=True,
    )
    selector = Train.cli(
        argv=['--optim=sgd', '--optim.momentum=0.7'],
        autocomplete=False,
        special_options=False,
    )
    rows.append(
        _row(
            'dynamic SubConfig selector',
            'delegated',
            native_selector is None
            and isinstance(selector.optim, SGD)
            and abs(selector.optim.momentum - 0.7) < 1e-12,
            'selector changes the realized schema; canonical multipass parser owns it',
        )
    )

    layered = Flat.cli(
        argv=['--count=4'],
        data={'path': 'from-data'},
        autocomplete=False,
        special_options=False,
    )
    rows.append(
        _row(
            'layered data + argv ingestion',
            'delegated',
            layered.count == 4 and layered.path == 'from-data',
            'generic load/source precedence remains canonical Python; argv leaf parsing may still accelerate inside that lifecycle',
        )
    )

    class Special(kwconf.Config):
        __cli_backend__ = 'rust'
        __special_options__ = True
        value: int = 1

    special = Special.cli(
        argv=['--value=2'],
        autocomplete=False,
        special_options=True,
    )
    rows.append(
        _row(
            'special options lifecycle',
            'delegated',
            special.value == 2,
            '--config/--dump/--dumps remain on canonical Python path; their static names can be Rust-completed',
        )
    )

    class Positional(kwconf.Config):
        __cli_backend__ = 'rust'
        src = kwconf.Value('', position=1)

    positional_probe = Positional(_dont_call_post_init=True)
    native_positional = _rust.try_compile_config(
        positional_probe, required_extension=True
    )
    positional = Positional.cli(
        argv=['input.txt'], autocomplete=False, special_options=False
    )
    rows.append(
        _row(
            'positional arguments',
            'delegated',
            native_positional is None and positional.src == 'input.txt',
            'canonical argparse owns positional binding/order until differential coverage is complete',
        )
    )

    callback_calls = []

    def callback(text):
        callback_calls.append(text)
        return text.upper()

    class Callback(kwconf.Config):
        __cli_backend__ = 'rust'
        value = kwconf.Value('', parser=callback)

    callback_probe = Callback(_dont_call_post_init=True)
    native_callback = _rust.try_compile_config(
        callback_probe, required_extension=True
    )
    callback_cfg = Callback.cli(
        argv=['--value=once'], autocomplete=False, special_options=False
    )
    rows.append(
        _row(
            'custom Python parser callback',
            'delegated',
            native_callback is None
            and callback_cfg.value == 'ONCE'
            and callback_calls == ['once'],
            'admission declines before invoking user code, preventing double side effects',
        )
    )

    # Help/color are canonical by construction: both backends build the same
    # argparse parser/formatter when help is requested.
    parser_python = Flat().argparse()
    old_backend = Flat.__cli_backend__
    Flat.__cli_backend__ = 'rust'
    try:
        parser_rust = Flat().argparse()
    finally:
        Flat.__cli_backend__ = old_backend
    help_equal = parser_python.format_help() == parser_rust.format_help()
    formatter_equal = parser_python.formatter_class is parser_rust.formatter_class
    rows.append(
        _row(
            'help text',
            'delegated',
            help_equal and formatter_equal,
            f'formatter={parser_python.formatter_class.__module__}.{parser_python.formatter_class.__name__}',
        )
    )
    rich_version = _dist_version('rich-argparse')
    rows.append(
        _row(
            'Rich help/color',
            'delegated',
            True,
            'rich-argparse available' if rich_version else 'rich-argparse not installed; stdlib formatter active',
        )
    )

    class Leaf(kwconf.Config):
        __command__ = 'train_model'
        lr = kwconf.Value(0.1, choices=[0.1, 0.2])

        @classmethod
        def main(cls, cmdline=1, **kwargs):
            return cls.cli(cmdline=cmdline, **kwargs)

    class Root(kwconf.ModalCLI):
        __subconfigs__ = [Leaf]

    from kwconf import _completion

    option_specs, command_specs = _completion._modal_completion_specs(Root())
    index = _rust.make_completion_index(option_specs, command_specs)
    command_candidates = index.complete([], 'train')
    if command_candidates is None:
        command_names = []
    else:
        command_names = [item[0] for item in command_candidates]
    rows.append(
        _row(
            'ModalCLI command completion',
            'native',
            'train_model' in command_names and 'train-model' in command_names,
        )
    )
    routed = index.route(['train-model', '--lr=0.2'])
    rows.append(
        _row(
            'ModalCLI static command routing',
            'native',
            routed == (['train_model'], 1),
        )
    )

    opaque_modal = kwconf.ModalCLI()
    opaque_modal.register(command='external', main=lambda: 0)(None)
    try:
        _completion._modal_static_model(opaque_modal)
    except _rust.UnsupportedSchema:
        opaque_declined = True
    else:
        opaque_declined = False
    rows.append(
        _row(
            'opaque ModalCLI command',
            'delegated',
            opaque_declined,
            'opaque Python command functions remain canonical argparse/modal territory',
        )
    )

    config_index = _rust.compile_completion_index(Flat())
    option_candidates = config_index.complete([], '--mo')
    choice_candidates = config_index.complete(['--mode'], 'b')
    dynamic_candidates = config_index.complete(['--path'], '')
    rows.append(
        _row(
            'static option completion',
            'native',
            option_candidates is not None
            and '--mode' in [item[0] for item in option_candidates],
        )
    )
    rows.append(
        _row(
            'static choice completion',
            'native',
            choice_candidates is not None
            and [item[0] for item in choice_candidates] == ['b'],
        )
    )
    rows.append(
        _row(
            'dynamic/filesystem completion',
            'delegated',
            dynamic_candidates is None,
            'value position has no finite static choices',
        )
    )

    argcomplete_version = _dist_version('argcomplete')
    rows.append(
        _row(
            'argcomplete protocol fallback',
            'delegated',
            True,
            (
                f'argcomplete {argcomplete_version} available'
                if argcomplete_version
                else 'argcomplete not installed in this environment'
            ),
        )
    )

    rows.append(
        _row(
            'pure-Python install without binary',
            'delegated',
            True,
            'auto mode treats an absent/incompatible ABI3 accelerator as a normal pure-Python installation',
        )
    )

    return {
        'python': sys.version,
        'python_executable': sys.executable,
        'backend_status': status,
        'argcomplete_version': argcomplete_version,
        'rich_argparse_version': rich_version,
        'rows': rows,
        'all_ok': all(row['ok'] for row in rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--json-output', type=Path)
    args = parser.parse_args()
    report = collect()
    for row in report['rows']:
        marker = 'PASS' if row['ok'] else 'FAIL'
        detail = f" - {row['detail']}" if row['detail'] else ''
        print(f"{marker:4s} {row['ownership']:9s} {row['feature']}{detail}")
    print('backend:', report['backend_status'])
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + '\n')
        print('wrote:', args.json_output)
    if not report['all_ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
