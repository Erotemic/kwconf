# Changelog
We [keep a changelog](https://keepachangelog.com/en/1.0.0/).
We aim to adhere to [semantic versioning](https://semver.org/spec/v2.0.0.html).


## Version 0.12.1 - Unreleased

### Added
* A normal-sized argparse-vs-kwconf comparison example and self-contained
  HTML benchmark report now present cold startup, warm invocation, component,
  completion, ModalCLI, help/color, and native-vs-delegated evidence together.
  The Rust evidence bundle emits the report automatically.
* An experimental optional Rust-backed CLI accelerator can bypass argparse
  schema construction for common scalar/flag/counter/bare-option parses, fixed
  realized SubConfig leaves, static completion, and static ModalCLI routing,
  while conservatively falling back to the existing parser for unsupported or
  dynamic semantics and canonical diagnostics. ``Config`` defaults to ``__cli_backend__ = 'auto'``: an
  installed compatible accelerator is used for proven fast-path cases, while a
  pure-Python install remains fully functional. The bridge uses a versioned FFI
  protocol and refuses stale binaries. Dedicated benchmarks measure hot parsing,
  Config/class construction, schema construction, extension import cost, and
  typed/explicit fresh-process CLI startup against stdlib ``argparse``.
* The accelerator performance campaign now includes pure-Rust Criterion
  benchmarks, repeatable perf/flamegraph/Callgrind/Massif workloads, Python
  bridge cProfile workloads, argv-density FFI scaling, and an interleaved
  fresh-process CLI campaign that records raw trials and paired argparse
  deltas. Native parser logic now lives in a separate Rust-only crate from the
  PyO3 wrapper so Rust-only timings do not link the Python extension machinery
  or conflate FFI conversion with dispatch. The shipping extension remains
  pinned to PyO3's ``abi3-py310`` Stable ABI, and the build helper rejects
  accidentally version-specific wheels.
* The Rust campaign now covers static shell completion and static ModalCLI
  routing in the Python-independent ``kwconf-cli-core`` crate. Ordinary option,
  finite-choice, nested-leaf, and modal-command completions can answer the
  argcomplete wire protocol before importing argparse/argcomplete; dynamic
  callbacks, filesystem completion, shell quoting, mutex-sensitive completion,
  help/errors, and opaque modal commands delegate to the canonical Python
  implementation. Fixed realized SubConfig leaves are accelerated while
  schema-changing selectors retain the multipass Python parser.
* End-to-end evaluation tooling now includes completion-vs-argcomplete, modal
  dispatch, plain/Rich help-color parity, native/FFI profiles, and a single
  evidence-bundle command that archives build metadata, feature ownership, raw
  trials, generated programs, profiles, wheel contents/hashes, changed-source
  snapshots, and every command log into one tarball.

### Changed
* Rust evidence reports now flush the command ledger before HTML rendering, so
  benchmark sections that were skipped after a failed gate explain why instead
  of appearing as unexplained missing data.
* The optional native accelerator now ships as a separate ``kwconf-rust``
  distribution maintained in the same repository. The normal ``kwconf``
  package remains pure Python and has no binary dependency; installing
  ``kwconf-rust`` adds the ABI3 ``_kwconf_rust`` module and pins the exact
  matching ``kwconf`` version. xcookie workspace CI builds and publishes the
  accelerator independently across Linux, macOS, and Windows.
* The top-level package API is now resolved lazily, and flat ``Config`` schema
  construction no longer imports the modal, dataconfig, SubConfig, argparse,
  pprint/inspect, textwrap, optional ubelt repr integration, or YAML helpers
  unless the selected feature needs them. Common ``argv`` list/tuple and
  ``data=None`` / plain-dict ingestion paths likewise defer the JSON, shlex, and
  file-ingestion stack. Type-only implementation imports are represented by a
  small runtime shim plus shipped ``.pyi`` metadata so simple typed schemas do
  not import the stdlib ``typing`` stack merely to start a CLI.
* Config metaclass normalization now enriches annotated fields once after
  inherited/declared defaults are merged instead of copying them in both the
  collection and normalization passes. Root-API collision lookup is cached,
  common scalar annotations/defaults have direct paths, and Config construction
  materializes ordinary Value reset metadata and live state together. These
  changes reduce Python declaration/instance overhead that remains visible even
  when argv token parsing is accelerated.
* Optional ubelt pretty-print registration is now lazy in both import orders.
  ``ub.urepr(config)`` retains its integration when ubelt is present, without
  importing ubelt during ordinary kwconf startup or registering a global
  typename handler that could match unrelated classes named ``Config``.
* The optional Rust wheel uses Maturin's standard pure-Rust layout: a tiny
  generated ``_kwconf_rust/__init__.py`` re-export wrapper around the native
  ABI3 child extension. The build helper verifies the ABI3 wheel tag and native
  child instead of treating that wrapper as a packaging failure. Its FFI protocol
  reports explicit parse/completion/modal capabilities, and the extension remains
  a thin PyO3 adapter over ``kwconf-cli-core`` so the recognition/completion/router
  primitives can converge with ``kwconf-rs`` without introducing a Python
  dependency into native Rust programs.
* The common successful Rust-backed ``Config.cli()`` lifecycle for flat and
  fixed-realized nested schemas now bypasses the generic data/argparse loader
  entirely after a side-effect-free eligibility probe. Serialization, parser construction, code-generation, generic
  ``load()``/``_read_argv()`` bodies, and Value argparse/codegen helpers live
  behind lazy cold modules, while fallback, SubConfig, completion, help/error,
  and pure-Python behavior keep the canonical implementation. The direct path
  preserves reset/default-factory and provenance semantics before committing
  accelerated results. Top-level lazy API resolution also uses the builtin
  importer directly rather than importing ``importlib`` on first access.
* Static completion and ModalCLI startup no longer eagerly import stdlib
  ``typing``, ``pprint``, or ``inspect``. Type-only names reuse kwconf's small
  runtime typing shim, diagnostic pretty-printing imports ``pprint`` only when
  debugging is enabled, and normal Python/classmethod modal entry points inspect
  their code object directly with a lazy ``inspect.signature`` fallback for
  exotic callables. This removes fixed Python import cost from the paths where
  the Rust completion/router is intended to beat argparse.
* Static ModalCLI routing now builds only command-routing metadata instead of
  compiling completion schemas for every leaf before selecting a command.
  Command-name completion likewise avoids leaf schema compilation, while
  option completion materializes only the selected leaf. This reduces modal
  orchestration overhead without changing the Rust ABI, routing semantics, or
  canonical fallback behavior. The release evidence gates also enforce clean
  Rust formatting and Python linting for the accelerator campaign.
* Static ModalCLI routing and command-name completion now resolve command
  metadata without materializing argparse parser/formatter kwargs. Successful
  Rust routing therefore does not import argparse, inspect, typing, or
  rich-argparse solely for unused help metadata; canonical help/error and
  delegated paths still build the same parser stack when needed.

### Fixed
* Annotation introspection now normalizes PEP 585 generic aliases before the
  plain-runtime-class fast path. This restores Python 3.10 behavior for
  ``list[T]`` / optional-container coercion and validation while retaining the
  lazy ``typing`` import optimization. Cold SubConfig and runtime-typing shim
  annotations are also explicit enough for the static checker.
* The Rust evidence campaign now accepts Maturin's normal pure-Rust wrapper
  layout, uses at least two startup/completion observations in ``--quick`` mode,
  instantiates ``Config`` before exercising the instance ``argparse()`` API, and
  uses a deterministic filesystem-completion fixture so exact argcomplete wire
  parity is not defeated by directory iteration order. Required-field tests now
  assert kwconf's canonical provenance ``ValueError`` contract instead of
  incorrectly expecting argparse ``SystemExit``. Runtime validation warnings are
  attributed to the first caller outside kwconf, making their user-visible source
  location backend-invariant across hot/cold Python and Rust paths.
* The Rust cold-start benchmark no longer imports ``argparse`` in the kwconf
  child workloads before choosing a backend. It now reports separate
  ``kwconf_core`` and declaration/instance rows plus absolute baseline deltas so
  package-shell cost, Config/Value cost, extension cost, metaclass work, and
  one-shot CLI cost can be distinguished.
* Rust fast-path schema admission now rejects arbitrary Python parser/type
  callbacks and object-valued choices before speculative parsing. This prevents
  a later argparse fallback from executing user callback/equality code twice;
  builtin scalar coercers and kwconf's own named parsers remain accelerated.
* The optional-ubelt fresh-interpreter tests now explicitly expose the detected
  ubelt site-packages root when running children with ``python -S``; ``-S`` no
  longer makes an installed optional dependency disappear and create a false
  full-suite failure. The full Rust evidence campaign now gates cargo formatting,
  clippy, Ruff, and the complete pytest suite, while kernel-restricted ``perf``
  is reported as unavailable instead of as four failed profiling commands.


## Version 0.12.0 - Released 2026-09-19

### Added
* ``Config.port_to_pydantic()`` generates Pydantic 2 ``BaseModel`` source. It
  translates annotations, defaults and importable default factories, help text,
  long aliases, JSON-compatible tags, and simple nested ``SubConfig`` models.
  Kwconf-specific CLI metadata is emitted as ``REVIEW(kwconf-port)`` comments.
  Source generation does not import Pydantic.
* Expanded the README comparison with Pydantic and ``pydantic-settings``,
  including their CLI support and the ``port_to_pydantic()`` field mappings.
* ``Value(..., bare=VALUE)`` defines an option's bare CLI result without
  exposing argparse's ``const`` terminology. Bare values retain explicit
  ``--key=value`` / ``--key value`` and ``-k=value`` / ``-k value`` forms.
* Bare-capable short aliases now have deterministic compact clustering (for
  example ``-pv`` and ``-vvv``), controlled by
  ``__short_alias_clusters__`` / ``argparse(short_alias_clusters=...)``.

### Changed
* CLI parser construction and reuse avoid per-field dynamic ``argparse.Action``
  classes, and fuzzy underscore/hyphen fallback lookup is cached per parser
  schema. This reduces overhead without changing accepted CLI syntax.
* Config construction now clones internal ``Value`` metadata directly instead
  of routing each field through generic ``copy.copy`` reconstruction, and
  skips ``deepcopy`` for builtin atomic immutable defaults. Parser construction
  also fast-paths fields without explicit aliases and avoids an unnecessary
  kwargs copy for non-positional options. These keep the same ownership and
  CLI semantics while improving large-schema startup scaling.
* Compact short tokens no longer use undelimited attached values for options
  that have a bare form. ``-fVALUE`` is reserved for ordinary required-value
  options; use ``-f=VALUE`` or ``-f VALUE`` for a flag, counter, ``bare=``
  value, or other optional-value short option. Counter clustering is now a
  parser-level lexical rule rather than a ``CounterOrKeyValAction`` repair for
  argparse's ``-vvv`` -> ``-v`` + ``vv`` interpretation.

### Fixed
* ``Config.port_from_click()`` ignores Click's generated help option by asking
  Click for that option directly. This supports both the historical ``help``
  storage name and Click 8.5's reserved ``_click_default_help`` name.
* The ``csv`` parser now preserves empty fields instead of dropping them. For
  example, ``a,,b`` parses as ``['a', '', 'b']``, and an empty token parses as
  ``['']``. Leading and trailing empty fields are preserved as well.


## [Version 0.11.0] - 2026-08-05

### Development
* Ruff (lint + format) is now enforced by `run_linter.sh` and CI, and shipped
  in the linting extra. A `[dependency-groups] dev` group makes `uv run
  pytest` work without `--extra tests`. The Sphinx docs build again on Python
  3.14. The sdist now ships `tests/conftest.py` and `CHANGELOG.md` (new
  `MANIFEST.in`). `[tool.uv].exclude-newer` is pinned to a full timestamp so
  `uv run` no longer dirties `uv.lock`. Misc pyproject cleanups (duplicate
  build requirement, stale xcookie version, codespell path).
* `kwconf/` is clean under both `ty` (0.0.64) and `mypy --check-untyped-defs`.
  The help-formatter bases are now resolved under `TYPE_CHECKING`, so the
  optional rich-argparse swap no longer defeats base-class inference, and the
  remaining suppressions are narrowed to argparse's overloaded `parse_args`
  and PyYAML's lazy import.
* Restored the executable ``dataconf`` examples, its disabled pickle example,
  the associated xdoctest FIXME, and the manual compatibility example suite
  after they were inadvertently dropped during the decorator refactor.

### Added
* Every public `Config` operation now has a matching private alias (for example,
  `_load`, `_cli`, `_dump`, and `_validate`). Kwconf uses these non-shadowable
  aliases internally, so schemas may safely use ordinary API names such as
  `load`, `cli`, or `validate` as fields without redirecting framework calls.
* `Config.cli(..., validate=...)` and `Config.load(..., validate=...)` now
  provide a per-ingestion override for runtime validation. `False` selects the
  lean path, `'warn'` enables structural diagnostics while continuing with
  deterministic safe precedence, and `'error'` / `True` raises
  `ConfigValidationError`. The default `None` preserves existing field/class
  value-validation policy without enabling an additional structural scan;
  classes that set `__validate__ = 'error'` opt into strict structural checks
  automatically.
* `Config.validate()` provides an explicit static-schema validation gate for
  project test suites and CI. It detects aliases that collide with canonical
  field names, aliases on other fields, inherited fields, or generated
  fuzzy-hyphen spellings. Validation is intentionally opt-in and is never run
  during class construction or normal CLI invocation, avoiding repeated
  startup work for schemas that have already been checked in CI.
* `register_parser` (the documented parser extension point) is now exported at
  the top level: `kwconf.register_parser(...)`.
* `kwconf.ConfigValidationError` (a `TypeError` subclass) is now raised for
  strict runtime-validation failures, including annotation mismatches and
  contradictory SubConfig selector spellings. Existing ``except TypeError``
  handlers keep working while a CLI can catch the specific validation failure.

### Changed
* Declared fields now win over non-mapping `Config` API names on instances,
  while class access continues to expose inherited classmethods and methods.
  Mapping methods (`clear`, `copy`, `get`, `items`, `keys`, `pop`, `popitem`,
  `update`, and `values`) remain method-first so `Config` continues to satisfy
  the normal mapping protocol; matching field values remain available through
  item access.
* Config state ownership is now explicit. Class-level ``__default__`` entries
  are treated as immutable schema templates; each instance owns an independent ``_default``
  reset baseline; and ``_data`` contains only current raw values and realized
  SubConfigs. Constructor/default overrides update cloned instance metadata, and
  resetting a config deep-copies from the instance baseline instead of exposing
  or materializing class templates.
* Mapping/file/string ingestion now goes through one shared normalization
  boundary for flat and nested configs. Parser creation, argument ordering,
  special options, and live/ported ``add_argument`` specifications likewise use
  canonical builders instead of parallel implementations.
* Staged SubConfig realization remains supported, but argparse now interprets
  argv in every pass. The manual selector-token scanner and version-pinned
  copies of argparse's parse engine were removed. Kwconf actions now subclass
  the public ``argparse.Action`` API; remaining private reads are isolated to
  option/subparser introspection where argparse exposes no public enumeration
  interface.
* ``kwconf.subconfig.__all__`` now reflects the intended public API: wildcard
  imports expose only ``SubConfig``. The module's parser/loading helpers remain
  explicitly importable for internal and advanced use, but are documented as
  implementation details without compatibility guarantees.
* Documentation now makes the object-state boundary explicit: declared fields
  are the mapping, CLI, validation, and persistence contract, while undeclared
  attributes are intentional transient Python state and are omitted from
  serialization without warning. ``__allow_newattr__`` is documented as a
  separate experimental dynamic-key escape hatch whose round-trip contract is
  not yet stable.
* Modal ``--help`` command listings now show a single spelling per command by
  default (e.g. ``export_data`` instead of ``export_data (export-data)``). The
  hyphen/underscore-duplicate spellings (such as fuzzy-hyphen aliases) still
  route to the command; they are just hidden from the listing. Intentional,
  non-duplicate aliases are still shown.
* The default ``--help`` description for a config with no docstring and no
  ``__description__`` is now ``no description for <module>.<qualname>`` (naming
  the class that needs documenting) instead of
  ``argparse CLI generated by kwconf <version>``. This is deterministic (no
  version string) and, in a modal command listing, points at exactly which
  command class is missing a description.

### Fixed
* ``Value(default_factory=...)`` now follows dataclass-style recipe semantics:
  construction and reset invoke the factory directly instead of deep-copying a
  materialized result. Non-copyable factory outputs such as thread locks are
  therefore supported. Concrete declared defaults and constructor/default
  overrides must be deep-copyable so reset baselines cannot silently share
  mutable identity; the resulting error points non-copyable values toward a
  factory declaration.
* ``SubConfig(instance)`` now clones the instance's reset baseline through
  Config-aware construction. Factory-backed child values are recreated rather
  than deep-copied, so instance templates may contain non-copyable factory
  outputs without sharing them across parent configs.
* ``@dataconf`` now generates a Config subclass of the decorated class instead
  of copying methods into an unrelated replacement. Zero-argument ``super()``
  and descriptor state are preserved, Config construction remains authoritative,
  and standard-library dataclass fields (including ``default_factory`` fields)
  are translated into kwconf declarations.
* Required fields are now enforced from canonical provenance for the current
  ``data=`` / ``--config`` / argv merge. Explicit values equal to the default
  count as supplied, stale argv history cannot satisfy a later load, factory
  output identity is irrelevant, and dotted provenance reaches SubConfigs.
* Mapping ingestion now rejects multiple canonical/alias spellings that target
  the same field instead of silently choosing a hash-order-dependent winner.
  The duplicate-binding diagnostic also applies to nested dotted aliases.
* ``port_to_config()`` preserves importable ``default_factory`` recipes in the
  emitted source. Factories that cannot be represented as stable imports raise
  a targeted code-generation error rather than being invoked and frozen into a
  concrete default.
* Properties, cached properties, and other non-Value descriptors are no longer
  collected as configuration fields.
* ``Config.coerce()`` now resolves long aliases through the canonical field's
  parser metadata, and ``Config.validate()`` rejects duplicate ``short_alias``
  declarations before argparse construction.
* Inline source parsing now honors an explicit ``mode`` strictly: JSON mode no
  longer falls back to YAML. Missing string and ``os.PathLike`` config paths
  consistently raise ``FileNotFoundError``.
* Runtime ``Literal`` validation now compares both value and type, matching
  typing semantics where ``Literal[1]`` does not admit ``True``.
* ``ClassVar`` declarations remain class-only metadata instead of becoming
  Config fields, including classes converted with ``@dataconf``.
* ``Config.__json__()`` no longer treats complex numbers as JSON scalars or
  sorts mappings with incomparable mixed key types. The transformed result is
  validated with the standard JSON encoder, producing a targeted ``TypeError``
  for unsupported values and keys.
* Inline JSON/YAML mappings are parsed before applying the missing-path
  diagnostic, so mapping values may contain paths, URLs, or names ending in
  ``.json`` / ``.yaml`` without being mistaken for filenames.
* Modal multiple inheritance now applies subclass attribute shadowing before
  deduplicating command names. Hiding a left-base binding therefore reveals an
  otherwise equivalent command supplied by a later base instead of dropping
  the command entirely.
* Argparse behavior is now identical on every supported Python. An end-of-options
  separator in front of a subcommand (``prog -- run --opt=1``) is consumed by the
  parser instead of being offered to the subparsers action as the command name,
  and ``parse_args`` raises ``argparse.ArgumentError`` for unrecognized arguments
  when ``exit_on_error=False`` instead of exiting. CPython only gained both in
  3.13 (and late 3.12 patch releases); ``CompatArgumentParser`` backports them.
* ``format_annotation`` no longer renders parameterized generics as their bare
  origin (``list[int]`` printed as ``list``) on Python 3.10, where
  ``list[int]`` is itself an instance of ``type``.
* Audited and simplified the staged SubConfig parser path. Selector choices are
  now applied exactly once, selecting the already-realized class is idempotent,
  and lower-precedence ``data=`` / ``--config`` values are no longer erased by
  repeated reconstruction. Nested source precedence is now consistently
  defaults < data < ``--config`` < explicit argv, including when argv changes
  the selected implementation.
* SubConfig selector discovery no longer has arbitrary 20-pass / 32-pass
  convergence limits. Each pass must consume selector tokens and each
  fixed-point step must remove resolved paths, so valid deeply nested schemas
  terminate by progress rather than a magic depth bound.
* ``allow_subconfig_overrides=False`` no longer mistakes an ordinary dict leaf
  containing a ``__class__`` key for a SubConfig selector. Reused nested config
  instances also clear stale child ``_explicit_argv_keys`` provenance on every
  parse.
* Parse provenance is now reset for kwconf actions installed on plain
  ``argparse.ArgumentParser`` objects as well as ``ExtendedArgumentParser``
  instances, including parser trees with subcommands.
* Invalid bare SubConfig import selectors now raise a targeted
  ``Cannot interpret class spec`` error instead of leaking an unpacking error;
  imported non-Config objects receive a precise ``TypeError``.
* SubConfig import policy now honors its tri-state API: field-level ``None``
  inherits the call-level default, while True or False explicitly enables or
  disables imports for that node. Nested importable classes now serialize and
  resolve through their full ``module.qualname.Class`` path instead of losing
  the qualname.
* SubConfig choice serialization now matches the selected implementation by
  exact class identity. A subclass can no longer serialize as an earlier
  base-class choice and then deserialize into the wrong class.
* Staged nested loading now preserves raw mapping structure until the canonical
  update boundary. This keeps structural-validation provenance when argv or
  ``--config`` is present, preserves ordinary dict-valued fields in config
  files, and correctly applies nested mappings for SubConfigs revealed by a
  parent selector instead of treating those mappings as selector tokens.
* Reusing an argparse parser no longer carries explicit-option provenance from
  an earlier parse into a later one. Provenance is replaced on each parse,
  remains scoped to the selected modal parser, and is no longer exposed as a
  private marker in ordinary ``argparse.Namespace`` dictionaries.
* ``expand_multipass_parser(parser=...)`` now extends and returns the supplied
  parser instead of replacing it, preserving parser identity, custom arguments,
  groups, and caller configuration. SubConfig CLI ingestion now starts from a
  bare root parser and materializes the realized schema into it once, avoiding
  duplicate arguments from the preliminary default variant.
* Modal invocations without a leaf command now print usage from the deepest
  selected parser, so root usage has a stable class-derived program name and
  nested usage retains the full command path. ``NoCommandError`` now carries an
  integer exit ``code`` plus separate ``message`` and ``parser`` attributes
  instead of storing diagnostic text in ``SystemExit.code``.
* Remaining bare ``Exception`` raises now use catchable, intent-specific
  exception types: undeclared mapping keys raise ``KeyError``, incompatible
  positional use of boolean/counter argparse actions raises ``TypeError``, and
  the removed ``style='orig'`` exporter raises ``NotImplementedError``.
* ``Config`` construction now rejects extra positional arguments and duplicate
  bindings (including positional-plus-keyword and canonical-plus-alias forms)
  with ``TypeError`` instead of silently truncating or overwriting values. The
  fast path checks the positional count before materializing defaults, binds
  only the supplied positional keys, and folds alias normalization, duplicate
  detection, and unknown-key collection into one keyword pass.
* Modal parser metadata is now instance-owned. Constructing or building a
  parser for one ``ModalCLI`` no longer writes live ``subconfig``,
  ``parserkw``, or dispatch callable objects into the class-level
  ``__subconfigs__`` declarations, so sibling modal instances and reused
  command classes cannot contaminate each other. Caller-provided ``sub_clis``
  dictionaries and mutable alias lists are copied as part of the same
  ownership boundary.
* `ModalCLI` subclasses now inherit commands declared by their parents through
  class attributes, `__subconfigs__`, or class-level `register()`. A subclass
  can replace or hide an attribute-declared command using normal Python
  attribute overriding, and registering a new command on the subclass no
  longer mutates the parent's command list. Implicit discovery is now limited
  to `Config` and `ModalCLI` subclasses, so unrelated public helper classes are
  left as ordinary attributes instead of becoming broken commands; compatible
  custom command classes can still be registered explicitly.
* A data source containing both scalar SubConfig sugar (`inner: a`) and an
  explicit selector (`inner.__class__: b`) can no longer replace the realized
  nested Config with the raw string `a`. The explicit `.__class__` spelling
  wins deterministically on the lean path. Opt-in runtime validation diagnoses
  the ambiguous source: `validate='warn'` warns and continues safely, while
  `validate='error'` raises before mutation. Nested and dotted duplicate
  selector spellings are diagnosed by the same check.
* `ModalCLI.main` no longer prints a stray ``ERROR ex = <repr>`` line to
  stdout before re-raising a subcommand exception. The leftover debug
  print (and an unreachable ``return 1`` after the ``raise``) double-reported
  every failure for downstream CLIs that install their own top-level error
  handler; exceptions now propagate untouched.
* `@dataconf` on a plain class now preserves underscore-prefixed hooks and
  helpers (`__post_init__`, `__validate__`, `_helper`, ...) and picks up
  fields inherited from plain base classes by walking the MRO. Previously it
  skipped every underscore attribute and only read the decorated class's own
  namespace, silently losing both.
* `position=` now controls positional binding order. The position-sorted key
  order was computed but the parser build loop still iterated declaration
  order, so `second = Value(position=2); first = Value(position=1)` bound the
  first argv token to `second`. The build loop now follows the position
  order.
* Underscore/hyphen interchange (fuzzy hyphens) now works regardless of
  `allow_abbrev` on Python 3.12.3+. The exact hyphen-normalized match was
  nested inside the `allow_abbrev` guard in the newer-argparse code path, so
  `allow_abbrev=False` silently disabled fuzzy hyphens there (and only there,
  making behavior differ across interpreter versions). Only prefix
  abbreviation is gated by `allow_abbrev` now. The previously
  `pytest.skip`-ed `test_modal_fuzzy_hyphens` is reactivated.
* Subcommand provenance now survives a leading option before the command.
  `_deepest_subparser_for_argv` matched a subcommand only as the very first
  token, so any preceding option (or `--`) collapsed the walk to the root
  parser -- silently dropping every user-supplied subcommand value in modal
  dispatch. It now skips the parser's own options (and their separate-token
  values) to reach the command token.
* `CounterOrKeyValAction` no longer corrupts long-option values that begin
  with the option name's first letter. The grouped-short-option handling
  (`-vvv` → count) wrongly fired for long options too, so `--flag=false`
  became `'alse'` and `--flag=ff` became `3`; it now applies only to genuine
  short options.
* `scan_config_path` no longer greedily consumes the following token as the
  `--config` value when that token is another option (`--config --verbose`
  now raises "requires a value"), and it stops scanning at the `--`
  end-of-options separator.
* A mistyped config path (`--config typo.yaml`, `data='no_such.yaml'`) now
  raises a clear `FileNotFoundError` instead of being silently parsed as
  inline YAML content and failing later with an obscure error. A config file
  that does not parse to a mapping raises a clear `TypeError`, and an empty
  file is treated as "no overrides".
* A plain dict-valued leaf field alongside a `SubConfig` no longer crashes
  `load()`. Nested update mappings are now flattened only across SubConfig
  boundaries, so a dict field (`load({'hyperparams': {'lr': 0.5}})`) is
  assigned whole instead of being shredded into dotted keys and raising
  `KeyError` (non-string dict keys likewise no longer crash `'.'.join`).
  An explicit empty-dict update to a leaf field is also applied instead of
  being silently dropped.
* Annotation validation now honors the PEP 484 numeric tower: an `int` is
  accepted where `float` (or `complex`) is annotated, so idiomatic
  `Config(x=1)` for a `float` field no longer emits a spurious warning.
* Validation mismatch messages now name the real annotation
  (`int | None`, `list[int]`) instead of collapsing unions and generics to
  `Union` / `list`.
* `Optional` container annotations now coerce their elements. A field typed
  `list[int] | None` (or `Optional[list[int]]`) with `nargs`, or parsed via
  `parser='csv'`, kept its tokens as strings; `element_annotation` now
  unwraps the `Optional`/`Union` wrapper first. Union coercion also handles
  `Literal` members (`Literal['a'] | Literal['b']` parses like `str`).
* A `Literal[...] | str` annotation no longer restricts the CLI to the
  literal values (the `str` member admits any string, so no `choices` are
  applied). A union of several `Literal`s now combines all members' values
  instead of exposing only the first literal's.
* `--config <file>` now merges the file's values over the current state.
  Previously it triggered a full reset-load that restored defaults for every
  key the file did not mention, silently wiping `data=` values. Explicit CLI
  values still win over the file.
* `Value(required=True)` no longer rejects a user who explicitly supplies the
  default value (on argv or in `data=`). Enforcement now consults explicit
  provenance first; the value-vs-default comparison remains only as a
  fallback for untracked sources. The failure also raises `ValueError` with a
  clearer message instead of a bare `Exception`.
* `Config.cli()` / `load(argv=...)` no longer store the class template's
  default object into instances. Mutable defaults (including
  `default_factory` output) were shared between every CLI-constructed
  instance and the class itself, so mutating one instance's list leaked into
  all others and permanently corrupted the class default.
* Annotation processing at class creation no longer mutates shared `Value`
  templates in place. A subclass overriding only a field's annotation
  (`class Sub(Base): x: str`) used to rewrite the base class's template,
  making unrelated `Base(...)` calls warn against the subclass's annotation.
* `port_to_config` now emits valid, executable code for typed fields.
  Previously private runtime attributes (`_annotation=<class 'int'>`,
  `_user_gave_type=True`, ...) leaked into the generated `Value(...)` calls
  (a `SyntaxError` on exec), and every field carried a redundant `help=None`.
* `Config.load` / `cli(data=...)` no longer mutate the caller's `data` dict
  (alias keys were renamed and unknown keys popped in place).
* A `--version` request that resolves to a submodal without its own
  `__version__` now reports the invoking root's version instead of printing
  the literal `None`.
* `ModalCLI.main(argv=False)` (and `argv=0`) no longer crashes with
  `TypeError`; the falsy sentinel now means "do not read the CLI", matching
  the `Config.main` convention, and takes the no-command path.
* Opaque modal commands (registered with `main=` and no config class) no
  longer reuse the previous command's parser kwargs, which could hijack that
  command's aliases or crash at build time (`UnboundLocalError` /
  `conflicting subparser alias`). Aliases passed to `register(alias=...)` for
  opaque commands are now honored.
* Intercepted parse errors now keep argparse's `argument --name:` prefix in
  the printed message (previously `ex.message` dropped it, hiding which
  option failed).
* `exit_on_error=False` is now honored by `CompatArgumentParser` /
  `ExtendedArgumentParser`. Modern argparse re-set the attribute during
  construction, so parse errors always raised `SystemExit` instead of
  `argparse.ArgumentError`. `ExtendedArgumentParser.parse_args` also no longer
  leaves `exit_on_error` permanently flipped off on a reused parser.
* `Config.dump` / `dumps` no longer register a `dict` representer on the
  shared `yaml.SafeDumper`, which changed the output of unrelated
  `yaml.safe_dump` calls in the same process.
* A successful `--dump` / `--dumps` now exits with status 0 instead of 1, so
  shell pipelines like `tool --dumps > config.yaml` no longer report failure.
* `Config.__json__` now converts a nested object with a `__json__` method in
  place. Previously the first such object made the method return early,
  discarding every other key in the config.
* `ModalCLI.register` used as a decorator (`@modal.register` or
  `@ModalCLI.register(command=...)`) now returns the decorated class instead of
  rebinding the decorated name to `None`.
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
