# kwconf ADR Set

## Table of Contents

1. [ADR-0001 — Interoperability across CLI, kwargs, and on-disk config files](#adr-0001--interoperability-across-cli-kwargs-and-on-disk-config-files)
2. [ADR-0002 — Config is the primary public API](#adr-0002--config-is-the-primary-public-api)
3. [ADR-0003 — Preferred schema style is declarative class attributes](#adr-0003--preferred-schema-style-is-declarative-class-attributes)
4. [ADR-0004 — Value is optional metadata](#adr-0004--value-is-optional-metadata)
5. [ADR-0005 — Type annotations improve typing support](#adr-0005--type-annotations-improve-typing-support)
6. [ADR-0006 — Configuration precedence is fixed](#adr-0006--configuration-precedence-is-fixed)
7. [ADR-0007 — Smart parsing is limited](#adr-0007--smart-parsing-is-limited)
8. [ADR-0008 — Nested configs remain explicit](#adr-0008--nested-configs-remain-explicit)

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

## ADR-0002 — Config is the primary public API

**Decision**
`Config` is the primary base class for new kwconf code. `DataConfig` remains supported for migration and compatibility, but it is not the primary public API.

**Why add this**
The library needs one public entry point and one primary mental model.

**What the ADR should lock down**

* New documentation and examples use `Config`.
* New features target `Config`.
* `DataConfig` is documented as a compatibility or migration surface.
* Migration support does not define the future API.

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
Type annotations are used to improve typing support, runtime casting, static analysis, editor support, and code clarity. They do not redefine the purpose of the library.

**Why add this**
This states the role of typing support without turning kwconf into a type-first framework.

**What the ADR should lock down**

* Annotations may inform runtime type handling.
* Explicit field metadata still matters for CLI behavior.
* Typing support is an enhancement to configuration behavior.
* The system remains configuration-oriented.

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

## ADR-0007 — Smart parsing is limited

**Decision**
Keep smart parsing only where the result is predictable. When parsing is ambiguous, explicit annotations or explicit `Value` metadata take precedence over heuristic behavior.

**Why add this**
This is a direct way to remove weird behavior without removing convenience.

**What the ADR should lock down**

* Predictable scalar coercions may remain.
* Ambiguous string-to-structure coercions should be reduced or bounded.
* Better typing support should reduce reliance on heuristic parsing.
* Convenience must not override explicit declarations.

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
