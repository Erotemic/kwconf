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
10. [ADR-0010 — Runtime validation defaults to warn](#adr-0010--runtime-validation-defaults-to-warn)

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

## ADR-0010 — Runtime validation defaults to warn

**Decision**
Validation checks user-supplied values against annotations after parsing. The
default policy is `warn`.

**Locks down**

* `warn` accepts the value and emits `UserWarning`.
* `error` / `True` raises `TypeError`.
* `False` disables validation.
* Field defaults are accepted as declared.
* Unsupported annotation forms are skipped.
