# CLI runtime benchmarks

`cli_runtime.py` measures where kwconf CLI cost comes from instead of treating
"kwconf versus argparse" as one number. It uses `timerit` for robust inline
measurements and records long-form CSV suitable for comparing revisions.
Timerit 1.1.0 is sufficient; that release introduced the `min_duration` API
used by this benchmark.

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

The CSV records minimum and mean robust timerit samples, standard deviation,
loop counts, Python/platform metadata, kwconf version, and the Git revision.
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
