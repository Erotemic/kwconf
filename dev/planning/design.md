# kwconf design — successor to scriptconfig

Living design doc. Tracks what is **locked** vs **open**. Companion to the dated
log in `dev/journals/claude.md` and the typing experiments in `dev/poc/`.

Status legend: **[LOCKED]** decided · **[OPEN]** undecided · **[GPT]** waiting on
the pending ChatGPT report · **[TODO]** implementation work, direction agreed.

## 1. Vision & guiding principles

- Successor to scriptconfig, **without the footguns**. The biggest historical
  footgun was comma-strings auto-splitting into lists (not bool/None parsing).
- **The untyped case stays dead simple** for quick CLIs; you *progressively
  harden* by adding type annotations. **[LOCKED]**
- **We trust the user at the Python boundary and never fail at runtime on type
  inconsistency.** Static analysis is the guard. "If we wanted strict, we'd
  write Rust." **[LOCKED]**
- **We will not require keyword arguments or any ugly syntax** to get the good
  ergonomics. Positional `Value(10)` stays. **[LOCKED]**
- Static typing (primary checker: **ty**; also mypy/pyright) is a *bonus we lean
  into where it's free*, never a constraint that warps the API. **[LOCKED]**

## 2. The `Value` API

- **`type=` → `coerce=`.** The old `type` kwarg was overloaded (argparse type +
  smartcast hint + container shape). `coerce` is a callable `str -> value` OR a
  string key into a registry (`'auto'`, `'yaml'`, `'csv'`, ...). Default `'auto'`.
  Precedence: **explicit `coerce` > annotation-derived auto > untyped auto.**
  `coerce=str` is the escape hatch to keep a string verbatim. **[LOCKED]**
- **`default` is positional-allowed.** `Value(10)`, `Value((256, 256))`,
  `Value('soft2')` all valid. No keyword requirement. **[LOCKED]**
- `default_factory=` (keyword) for mutable defaults. `required=True` with no
  default → required field. **[LOCKED]**
- **`annotations=` kwarg** lets dict-style / `__default__` configs declare a
  field's type when there is no real PEP 526 annotation. **Error if
  `annotations=` is given AND a real annotation exists** for that field (the
  normal class-attribute case). **[LOCKED]**
- **Flags:** use `kwconf.Flag` or `isflag=True`. A bare `: bool` annotation does
  **NOT** auto-imply flag behavior. (Tempting, but deferred — may revisit before
  the public release.) **[LOCKED for now, revisit pre-publish]**
- Other metadata carried by `Value` (unchanged in spirit): `help`, `alias`,
  `short_alias`, `choices`, `position`, `nargs`, `group`, `mutex_group`, `tags`,
  `validate`. **[LOCKED]**
- **`choices` informs the parse target** type where possible (e.g.
  `choices=[1,2,3]` ⇒ parse tokens as int). **[LOCKED]**

## 3. The `auto` parser (replaces `smartcast`)

Drop the "smart" name — anything "smart" in a name tends to be a footgun.

- **Runs only on strings** (parse iff `isinstance(value, str)`); real Python
  objects pass through untouched. **[LOCKED]**
- **Fixed, documented global precedence** intersected with the annotation:
  `None → int → float → complex → bool → str` (`str` is always the final
  catch-all). The annotation union is the *candidate menu*. **[LOCKED]**
- **Invariant:** runtime output type ∈ annotation union, with the single
  exception below. Annotations are **statically binding but runtime-advisory.**
  **[LOCKED]**
- **No-match fallback:** when nothing in the candidate set matches and `str` is
  not allowed → **warn and fall back to string** (do not raise). **[LOCKED]**
- **bool rules:** `int` claims `"1"`/`"0"` when `int` is in the union; `bool`
  always claims `true`/`false`. When `bool` is **not** unioned with `int`, the
  `auto` parser accepts **only `0/1/true/false`** for bool — this strictness is
  special to `'auto'`; a user can override with a custom `coerce`. **[LOCKED]**
- **No comma-splitting:** `"1,2,3"` stays the literal string under every
  annotation. **[LOCKED]**
- **Containers** (`list[int]`, `dict[...]`, ...): `auto` cannot build them from a
  single token → **warn**, pointing at `coerce='csv'|'yaml'` or `nargs`. The
  `str -> T` registry MUST special-case containers (never `list(str)`, which is
  the relocated original footgun). **[LOCKED policy; registry TODO]**

## 4. Coercion boundary & ingestion

- **Python boundary** (constructor, item/attr assignment, defaults): TRUST. No
  coercion, no runtime type failure. `MyConfig(x='123')` keeps `'123'` (and is
  ideally a *static* type error rather than silent magic). **[LOCKED]**
- **Text boundary** (argv, env): parse via the `coerce`/`auto` path. Typed file
  formats (YAML/JSON/TOML) respect their own typing — a quoted `"123"` stays a
  string; no re-parse. **[LOCKED]**
- **`Config.coerce(**kwargs)`** — opt-in alternative constructor that parses
  string inputs (mirrors the argv/env path; also great for tests). **[LOCKED]**
- **Architecture:** physically move parsing **out of the universal
  assignment/`coerce()` path and into argv/env ingestion adapters.** Core =
  trust; adapters = parse. **[LOCKED direction; TODO implementation]**
- **Why the boundary is forced, not just tidy:** with `dataclass_transform`,
  `MyConfig(x='123')` is already a static error for an `int` field. If the
  runtime *also* coerced it, the checker and runtime would disagree on the same
  line. Complementary guarantees: Python boundary = statically checked + no
  runtime coercion; argv boundary = no static info + runtime parse. **[LOCKED]**

## 5. Static typing strategy

- **Type `Value(...) -> T`** (the attrs/pydantic trick: typed to return the
  value type, not the `Value` wrapper). This gives **default-vs-annotation
  checking** (`x: str = Value(None)` → error) on **ty, mypy, and pyright**, and
  it **works with positional defaults**. Today `Value` is typed to return
  `Value`, so this never fires. **This is the headline, unblocked change.**
  **[LOCKED — implement first]**
- **Annotation resolution for parsing** uses `typing.get_type_hints` /
  best-effort resolution (PEP 563 / `from __future__ import annotations` safe),
  falling back to `Any` on unresolved forward refs. kwconf already has a
  best-effort resolver in `kwconf/annotations.py`. **[LOCKED]**
- **`dataclass_transform` (constructor-kwarg checking) — OPEN.** Positional
  defaults make the synthesized `__init__` mark every `Value`-wrapped field as
  **required** on mypy + pyright (the spec says standardized field-specifier
  params are keyword-only), producing spurious "missing field" errors when you
  omit a defaulted wrapped field. Bare `x: int = 5` fields are fine. So whether
  to apply `dataclass_transform` at all is undecided. **[GPT]** — see Q1 of the
  pending ChatGPT report.
- **Runtime-class `Value` vs `-> T` typing** must be reconciled (factory
  function vs `.pyi` stub vs `__new__` overloads). **[GPT / OPEN]**

### Verified checker facts (mypy 2.1.0 · pyright 1.1.410 · ty 0.0.49)

- Default-vs-annotation validation: works on all three, positionally (it's a
  plain typed assignment once `Value -> T`).
- mypy + pyright fully synthesize/check `__init__`; **ty 0.0.49 does not yet**
  for hand-rolled transforms (ty#1327 is closed/Stable → transient; we follow
  the spec and assume it lands).
- Positional `default` ⇒ field read as required by mypy + pyright.
- `required=True`/no-default → field correctly required.
- Bare `x: int = 5` is fully checked and correctly optional everywhere.

Policy: **do not cater to type-checker bugs/incompleteness.** Follow PEP 681 /
the typing spec so it works now or eventually. Separate transient checker gaps
(ignore) from real spec constraints (design around).

## 6. Open questions (consolidated)

1. **[GPT]** Apply `dataclass_transform` or not, given positional defaults break
   optional-detection for wrapped fields? Any spec-conformant way to keep
   positional `Value(10)` *and* get constructor-kwarg checking without spurious
   "required" errors?
2. **[GPT]** Mechanism to keep `Value` a runtime class while typing it `-> T`.
3. **[TODO]** Contents of the `coerce` registry and the per-type `str -> T`
   parsers, especially container handling.
4. **[TODO]** The ingestion-adapter refactor (move parsing off the assignment
   path; add argv/env adapters + `Config.coerce`).
5. **[OPEN]** Revisit whether `: bool` should auto-imply flag behavior before
   public release.

## 7. Migration from scriptconfig

- `type=` → `coerce=`, with `type=` kept as a **deprecated alias** for a long
  while. **[LOCKED intent]**
- Comma-splitting removed: `"1,2,3"` no longer auto-splits → use `nargs` or
  `coerce='csv'`. Call this out loudly in the migration guide. **[LOCKED]**
- Positional `Value(...)` idiom is preserved, which keeps migration low-churn.
  **[LOCKED]**
