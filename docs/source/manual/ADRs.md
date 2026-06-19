# kwconf ADR Set

## Table of Contents

1. [ADR-0001 — Interoperability across CLI, kwargs, and on-disk config files](#adr-0001--interoperability-across-cli-kwargs-and-on-disk-config-files)
2. [ADR-0002 — Config is the only public base class](#adr-0002--config-is-the-only-public-base-class)
3. [ADR-0003 — Preferred schema style is declarative class attributes](#adr-0003--preferred-schema-style-is-declarative-class-attributes)
4. [ADR-0004 — Value is optional metadata](#adr-0004--value-is-optional-metadata)
5. [ADR-0005 — Type annotations improve typing support](#adr-0005--type-annotations-improve-typing-support)
6. [ADR-0006 — Configuration precedence is fixed](#adr-0006--configuration-precedence-is-fixed)
7. [ADR-0007 — Smart parsing is replaced by the `auto` parser](#adr-0007--smart-parsing-is-replaced-by-the-auto-parser)
8. [ADR-0008 — Nested configs remain explicit](#adr-0008--nested-configs-remain-explicit)
9. [ADR-0009 — Coercion happens at the text boundary, not the Python boundary](#adr-0009--coercion-happens-at-the-text-boundary-not-the-python-boundary)
10. [ADR-0010 — Runtime validation is advisory and defaults to warn](#adr-0010--runtime-validation-is-advisory-and-defaults-to-warn)

---

## ADR-0001 — Interoperability across CLI, kwargs, and on-disk config files

**Decision**
kwconf defines one configuration model that must work consistently across:

* Python keyword arguments
* on-disk config files
* command line arguments

These are not separate modes with separate semantics. They are different input paths into the same config object.

**Why add this**
This is the main architectural rule. It states the purpose of the system in operational terms.

**What the ADR should lock down**

* The config object is the canonical representation of configuration state.
* CLI parsing must map onto the same field model used by Python construction.
* On-disk config files must map onto the same field model used by Python construction.
* Differences between these interfaces should be limited to syntax, not semantics.
* Any feature that only works cleanly in one input path should be treated as suspect.

---

## ADR-0002 — Config is the only public base class

**Decision**
`Config` is the single public base class for kwconf configs. The
former `DataConfig` base class has been renamed to `Config`. No
`kwconf.DataConfig` alias is exposed.

**Why add this**
The library needs one public entry point and one primary mental model.
Two competing base classes with overlapping responsibilities created
duplication in the implementation and confusion in the public surface.

**What the ADR should lock down**

* All documentation and examples use `Config`.
* New features target `Config`.
* `kwconf.DataConfig` is not part of the public API.
* The metaclass, ``cli`` / ``load`` / ``argparse`` / ``dump`` lifecycle,
  and dataclass-style ``__init__(*args, **kwargs)`` all live on
  ``Config``.

---

## ADR-0003 — Preferred schema style is declarative class attributes

**Decision**
The preferred way to define config schema is with class attributes on `Config`. Type annotations are encouraged, but not required.

**Why add this**
This is the main simplification in kwconf. It keeps schema declaration close to normal Python class definition.

**What the ADR should lock down**

* Class attributes are the default schema form.
* `__default__` dict style remains allowed where needed.
* `__default__` dict style is not the preferred style for new code.
* Methods and helper behavior should support class-attribute schemas first.

---

## ADR-0004 — Value is optional metadata

**Decision**
`Value` is used for field metadata and field-specific behavior. It is not required for ordinary fields.

**Why add this**
This keeps the common case simple and avoids wrapper-heavy schemas.

**What the ADR should lock down**

* Raw defaults are valid for ordinary fields.
* `Value` is used for help text, aliases, choices, flags, positional behavior, default factories, and related metadata.
* `Value` should not be required just to define a normal field.
* Metadata should be explicit and local to the field that needs it.

---

## ADR-0005 — Type annotations improve typing support

**Decision**
Annotations improve static analysis, editor support, runtime parsing, and code
clarity. They are a bonus we lean into where it is free, never a constraint that
warps the API.

**Why add this**
States the role of typing without turning kwconf into a type-first framework.

**What this locks down**

* Annotations inform parsing (the candidate type menu) and validation, but
  remain *statically binding, runtime-advisory* — kwconf never fails at runtime
  on a type inconsistency.
* `Value` / `Flag` are typed factory functions annotated to return the field's
  value type `T`. So `x: int = Value(None)` is a static error on ty, mypy, and
  pyright — including the positional form. To subclass the runtime wrapper, use
  the exported `ValueClass` / `FlagClass`.
* Positional defaults stay (`Value(10)`); kwconf does **not** apply
  `dataclass_transform`. There is no spec-conformant way to keep positional
  `Value(10)` *and* get clean constructor-kwarg checking, so we keep the
  ergonomics and deliver default-vs-annotation checking instead.
* Explicit field metadata still drives CLI behavior; the system stays
  configuration-oriented.

---

## ADR-0006 — Configuration precedence is fixed

**Decision**
Configuration precedence is:

1. class defaults
2. runtime default overrides
3. mapping or file data
4. CLI arguments

**Why add this**
This needs to be explicit and stable.

**What the ADR should lock down**

* The precedence order above is normative.
* All loading paths must respect the same order.
* New features must fit into this order.
* Documentation and tests should use the same terminology for overrides.

---

## ADR-0007 — Smart parsing is replaced by the `auto` parser

**Decision**
scriptconfig's `smartcast` is retired. String parsing now goes through named
parsers selected with `parser=` (the canonical keyword; `type=` is a deprecated
alias). The default, `'auto'`, infers scalars only.

**Why add this**
"Smart" in a name tends to mean footgun. The biggest historical footgun —
comma-strings auto-splitting into lists — is removed without losing convenience.

**What this locks down**

* `'auto'` runs only on strings and infers a scalar by a fixed precedence
  (`None → int → float → complex → bool → str`) intersected with the annotation.
  `str` is the final catch-all; no match falls back silently to the string.
* **No comma-splitting.** `"1,2,3"` stays a literal string under every
  annotation. Opt into structure explicitly: `nargs`, `parser='csv'`, or
  `parser='yaml'`.
* Parsers are **annotation-aware or not.** `'auto'` and `'csv'` are aware (they
  steer the produced type by the annotation; `'csv'` is `'auto'` over the
  comma-split, gated by the *element* type). `'yaml'` is unaware (it produces its
  own typed structure). Custom parsers opt in via
  `register_parser(name, fn, annotation_aware=True)`.
* `auto` never builds a container from one token — it warns and points at
  `csv`/`yaml`/`nargs`. Convenience never overrides an explicit `parser=`.

---

## ADR-0008 — Nested configs remain explicit

**Decision**
Nested configs are supported, but the schema must make nesting explicit. Dotted keys are update syntax, not the canonical schema representation.

**Why add this**
Nested config is useful, but it is also a common source of hidden behavior.

**What the ADR should lock down**

* Nesting is explicit in the schema.
* Dotted overrides are allowed as an interface convenience.
* Serialized config should represent the logical nested structure.
* Nested implementation selection should prefer explicit choices over open-ended resolution.
* Compatibility paths for more dynamic selection should not define the main design.

---

## ADR-0009 — Coercion happens at the text boundary, not the Python boundary

**Decision**
Parsing lives in the text-ingestion path (argv, env, untyped files). The Python
boundary — constructor, item/attribute assignment, and a field's own default —
is trusted and passes values through verbatim.

**Why add this**
It keeps one config model (ADR-0001) while resolving the tension that text
inputs are untyped and Python inputs already carry types. Coercing trusted
Python values would also contradict the static checker, which already flags
`MyConfig(x='123')` for an `int` field.

**What this locks down**

* `MyConfig(x='123')` keeps `'123'`; a `Value('512')` default is WYSIWYG. No
  coercion and no runtime type failure at the Python boundary.
* argv/env parse via the `parser`/`auto` path. Typed files (YAML/JSON/TOML)
  respect their own typing — a quoted `"123"` stays a string.
* Opt into text-boundary parsing from Python with `Config.coerce(**kwargs)` and
  the `from_cli` / `from_env` / `from_yaml` adapters. Plain `MyConfig(...)`
  stays the trusted path.
* All input paths resolve to the same field model; parsing is the boundary
  adapter, not a per-path semantic.

---

## ADR-0010 — Runtime validation is advisory and defaults to warn

**Decision**
Validation checks a value against its annotation and **warns** by default. It is
the single place type mismatches are reported. Tune it with `__validate__`
(class) or `Value(validate=)` (field): `'warn'` (default), `'error'`/`True`, or
`False`.

**Why add this**
Parsers used to warn inconsistently (some paths warned, others did not). One
advisory voice makes mismatch reporting uniform across `auto`/`csv`/`yaml`/custom
parsers, consistent with the runtime-advisory stance of ADR-0005.

**What this locks down**

* Default `'warn'` accepts the value and emits a `UserWarning`; `'error'` raises
  `TypeError`; `False` disables.
* Runs on *user-supplied* values (constructor / data / assignment / parsed
  argv-env) but **not** on a field's own trusted default — a WYSIWYG
  `Value('512')` on an `int` field never warns about itself.
* Parsers no longer emit value-level mismatch warnings; validation is the one
  voice. (The `auto` container-shape hint in ADR-0007 is parser misuse, not a
  value mismatch, so it stays.)
* Annotations the validator cannot reason about are skipped — under-validate
  rather than misvalidate.
