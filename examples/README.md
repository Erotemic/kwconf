# kwconf examples

This directory contains small, executable examples that show how the main
kwconf systems fit together. Each example has a top-level `DEMO` docstring with
commands to try. Commands print the resolved config as `name : type = value`
rows, so parser behavior is easy to inspect.

## Run everything

```bash
python examples/run_all.py
```

## Try one

```bash
python examples/01_minimal_config.py --help
python examples/01_minimal_config.py --width=128 --height=96 --method=lanczos --dst=thumb.png --tags demo small --dry-run
python examples/03_config_files.py --config examples/data/report.yaml --limit=3 --format=json
```

## Examples

- `01_minimal_config.py` - the smallest useful `kwconf.Config`: plain defaults,
  `kwconf.Value` metadata, aliases, programmatic construction, CLI parsing, and
  `__post_init__` normalization.
- `02_cli_surface.py` - CLI conveniences: positional arguments, short aliases,
  fuzzy hyphens, boolean flags, counters, choices, and explicit list input.
- `03_config_files.py` - YAML / JSON loading and dumping, special `--config`,
  and precedence where explicit CLI values override config-file values.
- `04_nested_configs.py` - nested config trees with `kwconf.SubConfig`, dotted
  CLI overrides, selector choices, and YAML round trips.
- `05_modal_cli.py` - subcommand CLIs with `kwconf.ModalCLI` and
  `kwconf.ModalValue`, including aliases and nested modal dispatch. Headlines
  **fuzzy hyphens** (hyphen / underscore spellings interchangeable) at every
  level - root commands, aliases, submodal commands, nested commands, and leaf
  flags - with a per-object opt-out. Run with no arguments to execute a
  self-check that proves each spelling resolves identically.
- `06_large_scale_app.py` - a research-pipeline-shaped example that combines
  nested dataset / model / optimizer / trainer configs with a modal app.
- `07_decorator_and_dynamic.py` - compatibility helpers: `@kwconf.dataconf`
  and `kwconf.define` for dynamic or migration-heavy cases.
- `08_modal_default_precedence_mwe.py` - bug-report MWE for modal dispatch
  preserving omitted-vs-explicit option semantics, based on a real
  `git-well archive_source` repo-local default issue.

## Parser notes

CLI tokens and env values are strings. Field parsers turn those strings into
Python values:

- `auto` reads scalar strings.
- `csv` reads comma-separated lists.
- `yaml` reads YAML-shaped values.
- `nargs` reads multiple CLI tokens.

Comma strings stay strings under `auto`. Use `csv`, `yaml`, or `nargs` when a
field should accept structured text.
