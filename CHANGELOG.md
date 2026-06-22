# Changelog
We [keep a changelog](https://keepachangelog.com/en/1.0.0/).
We aim to adhere to [semantic versioning](https://semver.org/spec/v2.0.0.html).


## [Version 0.10.1] - Unreleased

### Fixed
* `__fuzzy_hyphens__ = False` on a `Config` now actually rejects the hyphen
  spelling of option flags on the command line. Previously the variant was still
  accepted on the input side; the setting only stopped advertising it in
  `--help`.
* A parent `ModalCLI` opting out of fuzzy hyphens now propagates the opt-out to
  its subcommands and submodals (command names and option flags). Propagation is
  resolved per-invocation (`argparse(..., fuzzy_hyphens=...)`), so a `Config`
  reused under two different modals still resolves independently — no class
  attribute is mutated.

## [Version 0.10.0] - Released 2026-06-18 (ish)

First public release. `kwconf` is a successor to `scriptconfig`: typed,
dependency-free configuration objects that parse consistently from Python
kwargs, the command line, the environment, and config files.

### Added
* `Config` base class with declarative class-attribute schemas and `Value` /
  `Flag` / `SubConfig` field metadata.
* `parser=` keyword selecting a coercion parser: `'auto'` (default, scalar
  inference), `'csv'`, `'yaml'`, or any callable. Annotation-aware parsers
  (`'auto'`, `'csv'`) steer their output by the field annotation;
  `register_parser(..., annotation_aware=...)` registers custom ones.
* Coercion boundary: the Python boundary (constructor, assignment, defaults) is
  trusted (WYSIWYG); only the text boundary (argv/env/files) is parsed.
* Optional annotation validation via `__validate__` / `Value(validate=)`,
  defaulting to `'warn'` as the single mismatch voice.
* Modal CLIs (`ModalCLI` / `ModalValue`), nested configs (`SubConfig` + dotted
  overrides), argparse round-tripping, and YAML/JSON load/dump.
* `kwconf` console command and `python -m kwconf`.
* Ships `py.typed`; `Value` / `Flag` are typed factory functions giving static
  default-vs-annotation checking on ty, mypy, and pyright.

### Changed (vs scriptconfig)
* `type=` renamed to `parser=` (`type=` kept as a deprecated alias).
* Comma-strings no longer auto-split into lists; use `parser='csv'` or `nargs`.
* `--config` / `--dump` / `--dumps` special options are opt-in.

### Dependencies
* No required runtime dependencies. `ubelt` and `PyYAML` are optional extras
  (`pip install kwconf[ubelt]`, `pip install kwconf[yaml]`).
