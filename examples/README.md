# kwconf examples

This directory contains small, executable examples that show how the main
kwconf systems fit together. They are intentionally self-contained: each file
can be run directly from a source checkout, and `run_all.py` executes the full
set with deterministic arguments.

## Run everything

```bash
python examples/run_all.py
```

## Examples

- `01_minimal_config.py` - the smallest useful `kw.Config`: typed class
  attributes, `kw.Value` metadata, aliases, programmatic construction, CLI
  parsing, and `__post_init__` normalization.
- `02_cli_surface.py` - CLI conveniences: positional arguments, short aliases,
  fuzzy hyphens, boolean flags, counters, choices, and explicit list input.
- `03_config_files.py` - YAML / JSON loading and dumping, special `--config`,
  and the normal precedence model where CLI overrides config-file values.
- `04_nested_configs.py` - nested config trees with `kw.SubConfig`, dotted CLI
  overrides, selector choices, and YAML round-tripping.
- `05_modal_cli.py` - subcommand CLIs with `kw.ModalCLI` and `kw.ModalValue`,
  including aliases and nested modal dispatch.
- `06_large_scale_app.py` - a larger, research-pipeline-shaped example that
  combines nested dataset / model / optimizer / trainer configs with a modal
  app. This is meant to show the pattern you would scale up in a real repo.
- `07_decorator_and_dynamic.py` - compatibility helpers: `@kw.dataconf` and
  `kw.define` for dynamic or migration-heavy situations.

## Notes

The examples use `kw.Config` as the public base class. They avoid hidden
smart-casting behavior: comma-separated strings stay strings unless a schema
explicitly asks for structured parsing or the code handles normalization in
`__post_init__`.
