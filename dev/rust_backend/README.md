# Experimental Rust CLI backend

This directory is a measurement campaign, not a packaging commitment.

The first candidate targets the part of kwconf that currently costs the most
for ordinary flat CLIs: rebuilding an argparse schema on every `Config.cli()`
call. It does **not** put Rust on the normal `import kwconf` path.

The extension implements a small flat option dispatcher with `std::collections::HashMap`.
It intentionally does not depend on `clap`, Serde, or `kwconf-rs`: those are good
abstractions for a native Rust application, but translating a Python kwconf
schema into a second clap command tree on every process start would attack the
wrong cost center. The prototype does reuse the relevant grammar decisions from
`kwconf-rs` -- exact long options, dash/underscore aliases, boolean negation,
and compact short flags -- while keeping Python's existing `Value.coerce()` as
the conversion authority.

## Build

Use the active Python environment:

```bash
python dev/rust_backend/build_backend.py --release
```

The helper uses an installed `maturin` when available, otherwise `uv tool run`
to obtain it. A Rust toolchain (`cargo`) must already be on `PATH`.

### Stable-ABI release policy

The shipping accelerator deliberately uses PyO3's ``abi3-py310`` feature. A
single platform wheel should therefore work across CPython 3.10 and newer
without rebuilding for each interpreter minor version. ``build_backend.py``
checks the produced wheel tag and refuses a non-``abi3`` artifact. This is a
release constraint, not a benchmark accident: CPython-version-specific PyO3
builds may be useful as private diagnostics, but they are not candidates for
the default kwconf accelerator merely because they benchmark faster.

The native Criterion/perf layer does not use PyO3 at all, so it remains useful
for separating Stable-ABI marshaling cost from parser-algorithm cost.

To only build a wheel for inspection:

```bash
python dev/rust_backend/build_backend.py --release --wheel
```

## Backend policy

`Config` now defaults to `__cli_backend__ = 'auto'`. An installed accelerator
is therefore used automatically for schemas/argv that are inside the proven
fast-path boundary. Pure-Python installations do not import the Rust bridge; a
single cached extension probe fails and execution continues through the normal
argparse implementation.

The policy can be overridden per process:

```bash
KWCONF_CLI_BACKEND=python python my_cli.py ...  # force canonical Python path
KWCONF_CLI_BACKEND=auto python my_cli.py ...    # accelerator when available
KWCONF_CLI_BACKEND=rust python my_cli.py ...    # require the accelerator
```

or per config class:

```python
class MyConfig(kwconf.Config):
    __cli_backend__ = 'python'
```

`rust` requires the extension to be installed. `auto` silently uses Python if
the extension is absent. Both accelerated modes fall back to argparse for
unsupported schema/argv cases so Python remains the semantic and diagnostic
authority. The Python bridge and binary exchange a tiny versioned protocol
identifier; ``auto`` ignores a stale/incompatible accelerator while explicit
``rust`` mode reports the mismatch. This lets the optional wheel and pure
Python package be upgraded independently without making an old FFI silently
authoritative. This is intentionally a fast-success-path architecture rather
than a second CLI framework.

The current fast path supports flat configs plus fixed realized SubConfig
leaves, exact long options and aliases, dash/underscore spellings, normal
scalar options, optional/bare values, boolean flags and negation, counters,
short aliases/clusters, primitive choices, required options, and mutex checks.
Dynamic SubConfig selector tokens intentionally transfer ownership to the
canonical multipass implementation because they can replace the realized leaf
grammar. Positional arguments, multi-value
`nargs`, configs that opt out of kwconf short-cluster semantics, arbitrary
Python parser/type callbacks, and object-valued choices fall back to argparse.
The callback boundary is deliberate: a fast-path miss is retried by argparse,
so speculative execution of user code in the Rust bridge could otherwise run
that code twice. Unknown option spellings also fall back because they may be
argparse abbreviations.

## Why this is not a Rust reimplementation of argparse

Argparse exposes Python extension points (custom ``Action`` classes, callable
``type=`` converters, parser subclass overrides, formatter classes, and parser
introspection) that are more valuable to preserve than to imitate. A complete
Rust clone would also couple kwconf to CPython-version-specific error/help
details that the stdlib already implements correctly.

The accelerator therefore treats the existing argparse parser as an on-demand
compatibility object. Common successful parses use the compact Rust IR; help,
diagnostics, custom behavior, rich formatting, and dynamic completion
materialize/use the real parser only when requested. Differential parity tests
are the gate for expanding the Rust grammar. This boundary is also reusable if
a broader argparse-compatible accelerator is explored later.

## argparse ecosystem compatibility

The accelerator does not replace the real ``ArgumentParser`` exposed by
``Config.argparse()``. Exact Python extension points remain authoritative, but
static completion can now avoid constructing that parser entirely.

The ownership rule is deliberately explicit:

- ordinary supported argv is parsed by ``kwconf-cli-core``;
- fixed realized SubConfig leaves are flattened into the same parser; selector
  tokens that change the realized schema fall back to kwconf's canonical
  multipass implementation;
- static option names, aliases, finite primitive choices, nested leaf options,
  SubConfig selector option names, and static ModalCLI commands use
  ``CoreCompletionIndex`` and emit the normal argcomplete fd/environment
  protocol; once a SubConfig selector is consumed, completion delegates so the
  newly realized leaf grammar is rebuilt canonically;
- dynamic/filesystem completion, custom Python completers, shell quoting and
  word-break-sensitive candidates, positional completion, and mutex-sensitive
  completion delegate to real argcomplete unchanged;
- static ModalCLI command/alias routing can happen in Rust before argparse is
  constructed; help, errors, opaque commands, and unsupported leaf grammar
  delegate before user code runs;
- help/error rendering remains canonical argparse/rich-argparse. Consequently
  Python/Rust/auto help is expected to be byte-identical, including ANSI color
  whenever Rich is selected.

This is stronger than a best-effort clone: each request is either owned by a
small Rust contract with differential parity tests or by the exact existing
Python implementation.

## Relation to kwconf-rs

The Python-independent Cargo package ``kwconf-cli-core`` is now the intended
convergence seam. It owns exact option recognition, compact short clusters,
conservative fallback detection, static completion, and static modal routing.
The ``_kwconf_rust`` distribution is only an ``abi3-py310`` PyO3 adapter over
that core.

The current ``kwconf-rs`` project can continue to use its native ``clap``
presentation/help/error layer while progressively consuming the same core
mechanics. See ``dev/rust_backend/KWCONF_RS_CONVERGENCE.md`` for the next
milestone: a versioned schema IR and a shared differential corpus runnable
against canonical Python kwconf, Python + Rust accelerator, and pure kwconf-rs.
This lets Python compatibility and native-Rust ergonomics converge without
forcing arbitrary Python callbacks into a Rust API.

## End-to-end evidence bundle

Use the review-quality evaluation campaign for normal handoffs:

```bash
python dev/rust_backend/evidence_bundle.py
# minimal edit/test-loop diagnostic
python dev/rust_backend/evidence_bundle.py --quick
# exhaustive release-performance/profiling campaign
python dev/rust_backend/evidence_bundle.py --deep
```

The default review profile builds/installs the ABI3 wheel, runs backend/feature
parity, full pytest, Ruff, required Cargo gates, real
startup/completion/modal/help benchmarks, exact completion/help wire parity,
and import diagnostics. It retains every semantic coverage dimension while
reducing repeated fresh-process samples that add little information: delegated
completion gets two parity trials, help gets a small representative sample, and
headline/native timing gets moderate paired/interleaved sampling. Criterion,
cProfile, perf, and the separate ``kwconf-rs`` test run move to ``--deep``.

Required correctness failures are collected before the expensive repeated
benchmarks. In review mode a failed gate causes those timing campaigns to be
recorded as skipped; use ``--deep`` when performance evidence is still wanted
from a failing tree. Every command row records elapsed time in ``commands.json``
and ``SUMMARY.md`` so the collector's own runtime can be audited.

The bundle also contains the exact changed source snapshot, generated benchmark
programs, raw observations, wheel metadata/hash, and every command log. When a
``~/code/kwconf-rs`` checkout is present, review mode captures its relevant
state/metadata while ``--deep`` also runs its tests as non-blocking convergence
evidence. Required failures make the command exit nonzero *after* the evidence
tarball has been written.

## Measure

Run the dedicated benchmark after building the extension:

```bash
python dev/benchmarks/rust_cli_runtime.py --quick
```

Use the same Python executable that ran `build_backend.py`. The Rust
benchmark is intentionally stdlib-only so it does not need a PEP 723
dependency environment. You can also build, check, and immediately run the
quick benchmark in one interpreter with:

```bash
python dev/rust_backend/build_backend.py --release --benchmark
```

It records the costs that make up both warm and fresh-process CLI latency:

- hot parsing with a prebuilt schema;
- Config instance construction;
- argparse/Rust schema construction;
- declarative kwconf class construction (including typed schemas);
- warm end-to-end `Config.cli()` with the Rust schema cache populated;
- typed-schema warm end-to-end execution;
- cold imports in fresh Python processes;
- cold one-shot CLI execution for explicit-Value and typed schemas.

Every row includes both a ratio and an absolute delta from its family baseline.
The delta is particularly useful for cold startup, where a near-1.0 ratio can
still hide several milliseconds of application-visible latency.

The last two are mandatory for evaluating this experiment. A Rust parser that
wins a microbenchmark but loses once dynamic-extension import cost is included
is not a startup improvement.

The CSV defaults to `dev/benchmarks/_results/rust_cli_runtime.csv`.

## Decision rule

Do not replace the Python backend based on the Rust-core parser number alone.
The useful comparisons are `kwconf_rust` versus `argparse` in both
`warm_end_to_end` and `cold_end_to_end`, plus `rust_extension` in `cold_import`.
If cold one-shot CLIs do not beat argparse at representative schema sizes, keep
this as an opt-in accelerator or narrow the Rust boundary further rather than
making it a default dependency.

## Performance laboratory

The accelerator now has three benchmark layers. Keep them separate when
interpreting a result:

1. **Native Rust (`criterion`)** measures `CoreFlatParser` from the separate
   ``kwconf-cli-core`` crate without Python or PyO3. It covers schema construction, sparse and dense argv, compact short
   clusters, and the fallback detector. This is the right layer for Rust data
   structure and allocation changes.
2. **Python/PyO3 (`rust_cli_runtime.py`)** measures the extension call boundary,
   Python bridge/application work, kwconf declaration/construction, and both
   warm and fresh-process behavior. The `rust_pyo3_parse` row intentionally
   includes conversion of Python strings into Rust plus conversion of the Rust
   parse result back into Python. It is not a pure-Rust number.
3. **Fresh CLI (`cli_startup.py`)** is the headline user-facing benchmark. It
   launches complete argparse and kwconf programs in shuffled interleaved
   rounds, records every subprocess observation, and reports median paired
   deltas. Use this before making claims about startup speed.

Run all timing layers after rebuilding/installing the wheel:

```bash
python dev/rust_backend/build_backend.py --release --benchmark-all
```

For a quicker iteration, run the layers independently:

```bash
# Pure Rust statistics-driven microbenchmarks.
python dev/rust_backend/profile_backend.py criterion
# Save/compare a fixed native baseline while optimizing.
python dev/rust_backend/profile_backend.py criterion --save-baseline main
python dev/rust_backend/profile_backend.py criterion --baseline main

# Python / PyO3 / kwconf component accounting.
python dev/benchmarks/rust_cli_runtime.py --quick

# Actual process-launch -> parsed config -> exit latency.
python dev/benchmarks/cli_startup.py --quick
```

For publication-quality startup measurements, prefer many trials and pin the
parent to an otherwise idle CPU. Children inherit that affinity:

```bash
python dev/benchmarks/cli_startup.py --trials 100 --cpu 4
# Optionally keep the exact standalone programs used by the campaign.
python dev/benchmarks/cli_startup.py --quick --script-dir /tmp/kwconf-startup
```

The startup benchmark appends raw observations and summaries below
`dev/benchmarks/_results/`. Do not commit machine-local result files as a
universal baseline.

### Native profiling

`profile_backend.py` builds a symbolized release-equivalent profiling binary
and provides repeatable workloads for `build`, `parse-sparse`, `parse-dense`, `parse-mixed`,
`short-cluster`, and `fallback`.

```bash
# Hardware counters: cycles, instructions, branches, cache misses, etc.
python dev/rust_backend/profile_backend.py perf-stat \
    --workload parse-sparse --schema-size 256

# Sampling profile + a text report.
python dev/rust_backend/profile_backend.py perf-record \
    --workload parse-dense --schema-size 256

# SVG native flamegraph (requires cargo-flamegraph).
python dev/rust_backend/profile_backend.py flamegraph \
    --workload parse-dense --schema-size 256

# Deterministic instruction/call accounting (requires Valgrind).
python dev/rust_backend/profile_backend.py callgrind \
    --workload parse-sparse --schema-size 256

# Heap/stack growth profile (requires Valgrind).
python dev/rust_backend/profile_backend.py massif \
    --workload build --schema-size 256 --iterations 10000
```

Profiles are written below ignored `dev/benchmarks/_profiles/`.

### Python / PyO3 bridge profiling

Native core profiles cannot explain PyO3 conversion or time spent applying
assignments/coercions back in Python. For native samples through the actual
extension, install a symbolized profiling wheel and run the Python workload
under perf:

```bash
python dev/rust_backend/build_backend.py --profile profiling
python dev/rust_backend/profile_backend.py perf-python \
    --workload pyo3-parse --schema-size 256
```

Use cProfile for the Python boundary layers:

```bash
python dev/rust_backend/profile_backend.py python-cprofile \
    --workload pyo3-parse --schema-size 256 --iterations 100000
python dev/rust_backend/profile_backend.py python-cprofile \
    --workload rust-bridge --schema-size 256 --iterations 100000
python dev/rust_backend/profile_backend.py python-cprofile \
    --workload kwconf-cli --schema-size 256 --iterations 10000
```

The `pyo3-parse` workload is the extension call only, `rust-bridge` adds
kwconf's Python assignment/coercion layer, and `kwconf-cli` measures the normal
cached user-facing call. Together with Criterion this lets us attribute a
regression to native parsing, FFI conversion, or Python application work.

### Performance decision hierarchy

Optimize in this order:

1. full fresh-process CLI latency;
2. one-shot declaration/schema-build + parse in an already-running Python;
3. cached user-facing `Config.cli()`;
4. PyO3 parse/bridge scaling as argv grows;
5. pure native parser/schema cost.

A native Rust win that does not improve the first three is not by itself a
reason to complicate the implementation.
