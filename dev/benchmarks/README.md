# CLI runtime benchmarks

`cli_runtime.py` measures where kwconf CLI cost comes from instead of treating
"kwconf versus argparse" as one number. It uses `timerit` for robust inline
measurements and records long-form CSV suitable for comparing revisions.
Timerit 1.1.0 is sufficient; that release introduced the `min_duration` API
used by this benchmark.

Each run also measures ``python -c pass`` once as a Python interpreter
startup control. Every runtime plot reports that absolute startup reference,
and every revision-comparison plot reports the current/baseline startup ratio.
This gives the microbenchmarks an operational scale and helps distinguish code
changes from machine-wide timing drift. The raw CSV records the startup row and
``ratio_vs_python_startup`` for every measured case.

The benchmark separates these dimensions:

- parser construction as the number of configured options grows;
- parser reuse as schema size grows while argv stays small;
- parser reuse as the number of supplied argv options grows;
- compact short-counter cluster length (`-vvvv...`);
- fuzzy underscore/hyphen long-option normalization as schema size grows;
- end-to-end config initialization + parser construction + parsing.

For the general parser families, four implementations are shown when useful:

- `argparse`: a minimal stdlib parser with one canonical long spelling;
- `argparse_aliases`: stdlib argparse with both underscore and hyphen long
  spellings registered, approximating that part of kwconf's default feature
  surface;
- `kwconf_no_extras`: kwconf with fuzzy hyphens and short cluster
  normalization disabled;
- `kwconf_default`: normal kwconf behavior.

This makes it possible to distinguish the cost of kwconf's lexical extensions
from costs such as config initialization, coercion/provenance actions, and
parser construction.

## Run

The script has PEP 723 dependency metadata, so `uv` can provision its benchmark
requirements without adding them to kwconf's runtime or development
dependencies.

```bash
uv run dev/benchmarks/cli_runtime.py --quick
uv run dev/benchmarks/cli_runtime.py
```

By default results go under the ignored `dev/benchmarks/_results/` directory.
To keep a result elsewhere:

```bash
uv run dev/benchmarks/cli_runtime.py \
    --output /tmp/kwconf-cli-runtime.csv \
    --plot-dir /tmp/kwconf-cli-plots
```

Select families or scaling points explicitly when investigating a regression:

```bash
uv run dev/benchmarks/cli_runtime.py \
    --families build,schema_parse \
    --schema-sizes 1,8,32,128,512,2048

uv run dev/benchmarks/cli_runtime.py \
    --families argv_parse \
    --argv-schema-size 512 \
    --argv-sizes 0,1,8,32,128,512
```

The default CSV is an append-only measurement history. Every invocation gets
one `run_id`; every row records Python/platform metadata, kwconf and timerit
versions, the Git revision, dirty state, a Git working-state fingerprint, and
the UTC timestamp. A one-time schema widening may rewrite an older CSV when new
metadata columns are introduced, but existing measurement rows are preserved.

By default a new run is compared with the most recent compatible prior run from
the same history. Compatibility requires the same Python/platform and matching
benchmark case parameters. The tool writes `cli_runtime_comparison.csv`, prints
a compact current/baseline ratio summary, and writes comparison plots below the
normal plot directory. Ratios below 1 mean the current code is faster.

Run the benchmark before and after an optimization using the same command:

```bash
uv run dev/benchmarks/cli_runtime.py --quick
# edit / optimize
uv run dev/benchmarks/cli_runtime.py --quick
```

Select an older baseline explicitly with a prefix of its run id, Git revision,
Git-state hash, kwconf version, or timestamp:

```bash
uv run dev/benchmarks/cli_runtime.py --quick --compare-to 41bad80a6658
```

Use `--compare-to none` when only recording a measurement. The Git-state hash
also distinguishes tracked dirty-worktree changes at the same commit, which is
useful while iterating before committing an optimization. Untracked paths are
included through Git status, while their file contents are not hashed.

Machine-specific timings should not be committed as a universal baseline;
compare results from the same machine/environment when checking regressions.
The short-normalizer microbenchmark is feature-detected, so the script can also
be copied to an older revision that predates that helper when doing a
before/after comparison.

## Profile a hotspot

The same tool can run a repeatable `cProfile` workload:

```bash
uv run dev/benchmarks/cli_runtime.py \
    --profile kwconf_cli \
    --profile-schema-size 256 \
    --profile-argv-size 1

uv run dev/benchmarks/cli_runtime.py \
    --profile short_normalizer \
    --profile-argv-size 64

uv run dev/benchmarks/cli_runtime.py \
    --profile fuzzy_normalizer \
    --profile-schema-size 1024
```

Use `--profile-output result.prof` to retain a profile for tools such as
`tuna`, `snakeviz`, or `python -m pstats`.

## Interpretation

`short_normalizer_only` and `fuzzy_normalizer_only` are microbenchmarks. They
are intentionally plotted beside full parses to show whether lexical
normalization is material to the complete operation; they are not semantically
equivalent argparse alternatives.

In particular, the expected scaling properties are:

- valid short-cluster normalization is proportional to argv token bytes that
  actually need decomposition and should not grow with the number of schema
  options;
- a fuzzy long spelling may require work proportional to the registered long
  options, so this family is the one to watch for schema-width regressions;
- parser construction is expected to grow with schema size and should be
  evaluated separately from reuse of an already-built parser.

## Plot backend

The benchmark forces Matplotlib's non-interactive `Agg` backend when writing
plots. This intentionally ignores interactive backends selected by a user
Matplotlib rc file (for example `QtAgg`), so `uv run` does not need Qt bindings.

## Experimental Rust backend campaign

The optional Rust-backed CLI accelerator has a separate benchmark while its API and
packaging are experimental. Build it and measure both hot and cold costs with:

```bash
python dev/rust_backend/build_backend.py --release
python dev/benchmarks/rust_cli_runtime.py --quick
```

See `dev/rust_backend/README.md` for the fast-path boundary and decision rule.
The Rust benchmark includes fresh-process import and one-shot CLI measurements;
those should be considered alongside the existing in-process families before
judging whether the extension improves real CLI startup. It also isolates
Config-instance construction and declarative class construction because those
Python costs remain after token parsing moves to Rust. Both explicit ``Value``
and preferred typed declarations are measured.

The cold-import table separates bare ``import kwconf`` from ``kwconf_core``
(resolving ``Config`` and ``Value``) and from the extension itself. Child
workloads import ``argparse`` only for the argparse case, so the kwconf/Rust
cold measurements do not include stdlib parser startup unless the accelerator
actually falls back to it. Each row reports both its baseline ratio and the
absolute latency delta; use the latter when judging millisecond-scale cold
startup differences.

### Headline fresh-process campaign

`rust_cli_runtime.py` is a component benchmark. For the primary question --
"how long does a small real CLI take from process launch until its parsed
configuration is ready?" -- use the interleaved subprocess campaign:

```bash
python dev/benchmarks/cli_startup.py --quick
python dev/benchmarks/cli_startup.py --trials 100 --cpu 4
```

The campaign generates ordinary standalone source files: kwconf uses a
module-scope Config class while argparse constructs its parser in ``main()``.
Each trial round runs every method once in deterministic shuffled order. Raw
subprocess observations and summary statistics are appended separately. The
summary includes p10/median/p90 latency and a **paired** per-round delta from
argparse, which is more informative than comparing independent minima when the
Python process floor dominates the measurement. `--style typed` is the default
because annotated declarations are the preferred kwconf API; `--style value`
keeps the explicit-`Value` form available as a diagnostic. `--argv-size` can
exercise dense command lines separately from the default one-option startup
case. Use ``--script-dir /tmp/kwconf-startup-sources`` to retain the exact
generated programs when auditing a comparison.

The Rust component benchmark also has an `argv_scaling` family. It compares a
prebuilt argparse parser, the PyO3 parser method, and the complete Python Rust
bridge as supplied argv grows. This is specifically intended to reveal when
FFI string/result conversion becomes more expensive than native dispatch.

The successful flat accelerated lifecycle is also guarded by import-surface
regression tests: it must not load the generic Config cold module, Value's
argparse/code-generation module, argparse itself, SubConfig, or YAML/text
helpers. A fixed realized SubConfig CLI has a companion regression test that
permits the lightweight SubConfig declaration/runtime module but still forbids
loading argparse. This is intentional performance architecture rather than merely an
implementation detail: a supported Rust parse should pay only for the core
Config/Value representation and the accelerator bridge.

For pure-Rust Criterion and native profiler commands, see
`dev/rust_backend/README.md`.


### Completion, modal, and help/color benchmarks

Parsing speed is only one part of the CLI experience. The Rust campaign also
measures the other features that distinguish kwconf:

```bash
# Actual argcomplete environment protocol. When argcomplete is installed this
# enforces candidate parity against argparse + argcomplete as well as timing it.
python dev/benchmarks/completion_runtime.py --quick

# Fresh-process static modal dispatch versus argparse subparsers.
python dev/benchmarks/modal_runtime.py --quick

# Plain and forced-color help. Python/Rust/auto output must be byte-identical;
# when rich-argparse is installed this includes Rich ANSI rendering.
python dev/benchmarks/help_runtime.py --quick
```

Static option names, primitive finite choices, realized nested leaves,
SubConfig selector *names*, and static modal command names are eligible for the
Rust completion index. Once a selector value has been consumed, completion
delegates because that selector may have replaced the realized leaf grammar. Dynamic
or filesystem value completion, custom completers, shell quoting/word-break
syntax, and other stateful cases fall through to the real argcomplete parser.
The completion benchmark therefore tests both the native and delegated paths.

For a review-quality run, prefer the one-command evidence campaign. It retains
the generated programs and raw observations in addition to the summaries:

```bash
# Review-quality default: all release gates + representative timing.
python dev/rust_backend/evidence_bundle.py

# Minimal edit/test-loop diagnostic.
python dev/rust_backend/evidence_bundle.py --quick

# Exhaustive statistical/profiling campaign used for release characterization.
python dev/rust_backend/evidence_bundle.py --deep
```

The default review profile keeps every correctness/parity dimension but uses
fewer repeated fresh-process timing samples, uses two trials for delegated
completion cases whose purpose is exact wire parity, and omits deep Criterion,
cProfile, perf, and cross-repository test runs. If a required gate fails, it
skips the repeated performance campaign because those measurements cannot make
the build release-ready; ``--deep`` collects them anyway. The bundle records
per-step elapsed time so future slow stages are visible directly in the
summary.

The command always creates one ``kwconf-rust-evidence-*.tar.gz`` bundle. It
keeps logs even when a required check fails, so the archive can be handed to a
reviewer without rerunning individual diagnostics.

## Static benchmark report

`examples/09_argparse_comparison.py` contains equivalent normal-sized argparse
and kwconf implementations. Benchmark it directly with:

```bash
python dev/benchmarks/realistic_cli_runtime.py --output-json /tmp/realistic.json
```

The Rust evidence collector runs this comparison and writes a self-contained
`benchmark_report.html` that combines the realistic example with cold startup,
in-process parsing, completion, ModalCLI, help/color, and feature-ownership
results. An existing evidence directory can be rendered manually:

```bash
python dev/benchmarks/benchmark_report.py /path/to/evidence-directory
```
