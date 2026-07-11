# Architecture decision records

These decisions define the public shape of `kwconf`. They are intentionally
short and operational.

## Table of contents

1. [ADR-0001 — One field model for all inputs](#adr-0001--one-field-model-for-all-inputs)
2. [ADR-0002 — `Config` is the public base class](#adr-0002--config-is-the-public-base-class)
3. [ADR-0003 — Class attributes are the preferred schema style](#adr-0003--class-attributes-are-the-preferred-schema-style)
4. [ADR-0004 — `Value` is optional metadata](#adr-0004--value-is-optional-metadata)
5. [ADR-0005 — Type annotations improve the contract](#adr-0005--type-annotations-improve-the-contract)
6. [ADR-0006 — Configuration precedence is fixed](#adr-0006--configuration-precedence-is-fixed)
7. [ADR-0007 — Named parsers replace smart parsing](#adr-0007--named-parsers-replace-smart-parsing)
8. [ADR-0008 — Nested configs are explicit](#adr-0008--nested-configs-are-explicit)
9. [ADR-0009 — Coercion runs for string-only sources](#adr-0009--coercion-runs-for-string-only-sources)
10. [ADR-0010 — Runtime validation is tiered and performance-conscious](#adr-0010--runtime-validation-is-tiered-and-performance-conscious)
11. [ADR-0011 — Declared fields define the persistence contract](#adr-0011--declared-fields-define-the-persistence-contract)

---

## ADR-0001 — One field model for all inputs

**Decision**
`kwconf` uses one configuration model across Python kwargs, files, env, and CLI
arguments.

**Locks down**

* The config object is the canonical representation.
* CLI parsing maps onto the same fields used by Python construction.
* File loading maps onto the same fields used by Python construction.
* Input-path differences are syntax differences.

## ADR-0002 — `Config` is the public base class

**Decision**
`Config` is the public base class for user configs.

**Locks down**

* Documentation and examples use `Config`.
* New features target `Config`.
* `kwconf.DataConfig` is outside the public API.
* `kwconf.subconfig` publicly exports only `SubConfig`; the module's
  loading and staged-parser helpers are implementation details even though they
  remain available through explicit imports.
* The `cli` / `load` / `argparse` / `dump` lifecycle lives on `Config`.

## ADR-0003 — Class attributes are the preferred schema style

**Decision**
The preferred schema form is class attributes on `Config`. Type annotations are
encouraged and optional.

**Locks down**

* Raw class defaults are valid fields.
* `__default__` dict style remains available for migration and dynamic cases.
* New examples should start with class attributes.

## ADR-0004 — `Value` is optional metadata

**Decision**
`Value` stores field metadata and field-specific behavior. Ordinary fields can
be raw class attributes.

**Locks down**

* Use raw defaults for simple fields.
* Use `Value` for help, aliases, choices, flags, positions, `nargs`, default
  factories, parsers, groups, and validation policy.
* Metadata stays local to the field that needs it.

## ADR-0005 — Type annotations improve the contract

**Decision**
Annotations improve static analysis, editor support, parser selection,
validation, and readability.

**Locks down**

* Annotations inform parsing and validation.
* Runtime validation is advisory by default.
* `Value` / `Flag` are typed factory functions, so static checkers can catch
  mismatched field defaults.
* Subclass the runtime wrappers with `ValueClass` / `FlagClass`.

## ADR-0006 — Configuration precedence is fixed

**Decision**
Configuration precedence is:

1. class defaults;
2. runtime default overrides;
3. mapping or file data;
4. explicit CLI arguments.

**Locks down**

* All loading paths use this order.
* New features must fit into this order.
* Docs and tests should use the same terminology.

## ADR-0007 — Named parsers replace smart parsing

**Decision**
String parsing uses named parsers selected with `parser=`. The default parser
is `auto`.

**Locks down**

* `auto` reads one scalar from one CLI/env string.
* `csv` reads comma-separated lists.
* `yaml` reads YAML-shaped strings.
* `nargs` reads multiple CLI tokens.
* Comma strings stay strings under `auto`.
* `type=` remains a deprecated alias for migration.

## ADR-0008 — Nested configs are explicit

**Decision**
Nested configs are declared with `SubConfig`. Dotted keys are update syntax.

**Locks down**

* The schema declares the tree shape.
* Dotted overrides are an interface convenience.
* Serialized config represents the logical nested structure.
* Selector choices should prefer explicit registries.

## ADR-0009 — Coercion runs for string-only sources

**Decision**
Coercion runs for `sys.argv` tokens and `os.environ` values. Python kwargs,
assignment, defaults, and typed YAML/JSON values are used as Python values.

**Locks down**

* The constructor is the trusted Python path.
* `Config.coerce(**kwargs)` opts into parser-based string coercion from Python.
* `from_env` parses env strings.
* `from_yaml` keeps the file format's native types.
* Parsing is a boundary adapter, not a per-path field model.

## ADR-0010 — Runtime validation is tiered and performance-conscious

**Decision**
Annotation/value validation checks user-supplied values after parsing and
defaults to `warn`. Structural source validation is opt-in through
`cli(validate=...)` / `load(validate=...)`, or through the fully strict class
policy `__validate__ = 'error'`. The default class `warn` policy intentionally
does not add a structural traversal to every CLI startup.

**Locks down**

* `validate=None` preserves field/class value policy and selects the lean
  structural path.
* Explicit `validate='warn'` checks structural input consistency, emits
  `UserWarning`, and continues with deterministic safe precedence.
* Explicit `validate='error'` / `True` raises `ConfigValidationError` before
  applying structurally ambiguous input.
* Explicit `validate=False` disables runtime validation for values ingested by
  that call.
* `__validate__ = 'error'` opts a class into strict structural checks; the
  default `__validate__ = 'warn'` remains value-only.
* The lean path is still safe: explicit `path.__class__` wins over scalar
  selector sugar, so a SubConfig is never replaced by raw selector text.
* Conflicts are scoped to one source. Normal precedence between defaults,
  data/files, and argv remains intentional.
* Field defaults are accepted as declared.
* Unsupported annotation forms are skipped.
* Parser-enforced constraints remain hard errors regardless of `validate`.
* `Config.validate()` is the distinct opt-in static-schema gate for tests/CI;
  it is never an implicit startup scan.

## ADR-0011 — Declared fields define the persistence contract

**Decision**
The class declaration defines the configuration, mapping, CLI, validation, and
serialization contract. Undeclared attributes attached to an instance are
ordinary transient Python state, not configuration fields.

**Locks down**

* ``cfg.temp = value`` is allowed when ``temp`` is undeclared.
* The attached value is accessible as a Python attribute but is absent from
  mapping access, serialization, deserialization, CLI generation, and schema
  validation.
* Omitting transient attributes from serialization is intentional and does not
  produce a warning. Declare a field when persistence or round-trip behavior is
  required.
* ``__allow_newattr__ = True`` is not the default attribute policy. It is an
  experimental opt-in that promotes unknown assignments into dynamic config
  keys stored in ``_data``.
* Dynamic keys currently lack declared defaults, annotations, parser metadata,
  help text, CLI options, and guaranteed symmetric deserialization.

**Open direction**
If dynamic persisted configuration is kept, formalize ``__allow_newattr__`` (or
replace it with a more explicit name such as ``__allow_dynamic_fields__``) as a
round-trip-capable mapping extension mode. Unknown loaded keys should then be
accepted symmetrically, while schema-derived CLI and static validation remain
limited to declared fields unless metadata is supplied explicitly.

## ADR-0012 — State and parser ownership have one canonical path

**Decision**
Configuration state has three non-overlapping ownership layers, and all input
and parser construction paths share canonical normalization/building helpers.
Staged SubConfig selection is orchestration around argparse; kwconf does not
implement an independent argv grammar.

**Locks down**

* Class ``__default__`` entries are schema templates. Instance operations never
  store runtime values into them or materialize mutable defaults through them.
* Instance ``_default`` entries are cloned metadata plus the reset baseline for
  that instance. Constructor and ``default=`` overrides modify only this layer.
* Instance ``_data`` contains current raw values and realized SubConfig objects.
  Mutable values never alias the corresponding reset baseline.
* Flat loading and nested loading use the same mapping/file/inline-text
  normalization boundary; argv forms use the same argv normalizer.
* ``Config.argparse``, SubConfig parser expansion, and argparse port generation
  derive their field calls from canonical parser-building helpers.
* Multipass selection may rebuild the known selector set, but every pass uses
  ``argparse.parse_known_args``. Kwconf does not manually decide token/value
  boundaries.
* Kwconf parser actions subclass public ``argparse.Action``. The package does
  not vendor ``parse_known_args`` or override argparse's private
  ``_parse_optional`` / ``_get_option_tuples`` engine.
* Private argparse access is confined to small compatibility adapters for
  enumerating registered option strings, walking selected subparsers, and
  importing/exporting parser structure. Those adapters require behavioral
  tests whenever supported Python versions change.

