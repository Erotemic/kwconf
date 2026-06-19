# kwconf design — successor to scriptconfig

Living design doc. Tracks what is **locked** vs **open**. Companion to the dated
log in `dev/journals/claude.md` and the typing experiments in `dev/poc/`.

Status legend: **[LOCKED]** decided · **[OPEN]** undecided · **[GPT]** waiting on
the pending ChatGPT report · **[TODO]** implementation work, direction agreed.

## 0. Implementation status (chunks 1–17, all committed; suite green + `ty check ./kwconf` green)

1. removed `@dataclass_transform` (Option A)
2. `kwconf/coerce.py` — the `auto` parser (additive)
3. `Value(parser=…)` kwarg → routes through `coerce.py`
4. `Config.coerce(**kwargs)` opt-in coercing constructor
5. **boundary**: plain constructor trusts (no string coercion at the Python boundary)
6. **static check**: public `Value`/`Flag` typed `-> T` via a function facade in
   `__init__.py` (no `.pyi`) — `x: int = Value(None)` errors on ty/mypy/pyright
7. `parser=` canonical, `type=` deprecated (mutually exclusive)
8. `from_cli` / `from_yaml` / `from_env` named constructors
9. **`auto` is the default parser** (annotation-gated; union & strict-bool honored)
10. `argparse_ext` made kwconf-free (`_infer_scalar` helper) + AST guard test
11. scalar CLI parsing routed through the field `coerce` (union-aware CLI)
12. nargs/positional CLI fields routed through `coerce` (per-element via
    `coerce.element_annotation`)
13. `port_to_argparse(kwconf_primatives=True)` — 1-to-1 emission using
    `argparse_ext` + our coerce; default stays lightweight pure argparse
14. **`smartcast` retired** (module deleted); the deprecated `type=` path maps
    onto `kwconf.coerce`
15. **`Value`/`Flag` are explicit-signature factory functions** (no `*args/**kwargs`);
    the runtime wrappers are the classes `_Value`/`_Flag`. So `x: int = Value(None)`
    errors on ty/mypy/pyright.
16. `parser=` rename (was `coerce=`); see §2.
17. **`Value`/`Flag` functions live in `kwconf.value`** (next to their classes;
    `__init__` just re-exports). Two `Value` overloads give precise inference:
    `T` from a positional/keyword `default`, or from `default_factory`'s return
    type (works with no annotation). No false positives for `required=`.

Remaining: per-feature opt-in "vendored QoL" flags on `port_to_argparse` (the
master `kwconf_primatives` switch exists; granular ones are future work).

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

- **`type=` → `parser=`.** (Named `parser` because it only ever parses a string
  at the text boundary; briefly called `coerce=`.) The old `type` kwarg was
  overloaded (argparse type + smartcast hint + container shape). `parser` is a
  callable `str -> value` OR a string key into a registry (`'auto'`, `'yaml'`,
  `'csv'`, ...). Default `'auto'`. Precedence: **explicit `parser` >
  annotation-derived auto > untyped auto.** `parser=str` is the escape hatch to
  keep a string verbatim. The runtime *mechanism* keeps the `coerce` name
  (`Value.coerce()`, `Config.coerce()`, `kwconf.coerce`). **[LOCKED]**
- **Parsers are annotation-aware or not.** Aware parsers receive the field
  annotation and use it to steer the produced type; unaware parsers keep the
  single-arg `str -> value` contract. `'auto'` and `'csv'` are aware (`'csv'` is
  `'auto'` mapped over the comma-split, gated by the *element* annotation, so
  `list[str]` keeps each element a string instead of `[1, 2, '3o']`); `'yaml'`
  is unaware (it produces its own typed structure). Custom parsers opt in via
  `register_parser(name, fn, annotation_aware=True)`, after which the dispatcher
  passes `(token, annotation)`. **[LOCKED]**
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
  not allowed → **silently fall back to string** (do not raise, do not warn).
  Reporting a value/annotation mismatch is the job of the single Config
  validation layer (§4), so there is one voice consistent across all parsers.
  **[REVISED 2026-06; supersedes earlier "warn and fall back" — the warning
  moved to the validation layer to avoid double-warning and to cover yaml too]**
- **bool rules:** `int` claims `"1"`/`"0"` when `int` is in the union; `bool`
  always claims `true`/`false`. When `bool` is **not** unioned with `int`, the
  `auto` parser accepts **only `0/1/true/false`** for bool — this strictness is
  special to `'auto'`; a user can override with a custom `coerce`. **[LOCKED]**
- **No comma-splitting:** `"1,2,3"` stays the literal string under every
  annotation. **[LOCKED]**
- **Containers** (`list[int]`, `dict[...]`, ...): `auto` cannot build them from a
  single token → **warn**, pointing at `parser='csv'|'yaml'` or `nargs`. This
  shape/usage hint is the *one* parse-time warning `auto` still emits (it is a
  parser-misuse hint the validation layer cannot give); value-level no-match is
  silent (see above). The `str -> T` registry MUST special-case containers
  (never `list(str)`, the relocated original footgun). **[LOCKED]**

## 4. Coercion boundary & ingestion

- **Python boundary** (constructor, item/attr assignment, defaults): TRUST. No
  coercion, no runtime type failure. `MyConfig(x='123')` keeps `'123'` (and is
  ideally a *static* type error rather than silent magic). **[LOCKED]**
- **Text boundary** (argv, env): parse via the `coerce`/`auto` path. Typed file
  formats (YAML/JSON/TOML) respect their own typing — a quoted `"123"` stays a
  string; no re-parse. **[LOCKED]**
- **Opt-in textual constructors** (mirror the argv/env path; great for tests):
  `Config.coerce(**kwargs)` (parse a string-valued dict), plus named adapters
  `Config.from_cli(argv)`, `Config.from_env(prefix=…)`, `Config.from_yaml(path)`.
  Normal `MyConfig(x=…)` stays the trusted, non-coercing path. **[LOCKED]**
- **Architecture:** physically move parsing **out of the universal
  assignment/`coerce()` path and into argv/env ingestion adapters.** Core =
  trust; adapters = parse. **[LOCKED direction; TODO implementation]**
- **Why the boundary is forced, not just tidy:** with `dataclass_transform`,
  `MyConfig(x='123')` is already a static error for an `int` field. If the
  runtime *also* coerced it, the checker and runtime would disagree on the same
  line. Complementary guarantees: Python boundary = statically checked + no
  runtime coercion; argv boundary = no static info + runtime parse. **[LOCKED]**
- **Validation is the single mismatch voice, default `'warn'`.** Controlled by
  `__validate__` (class) / `Value(validate=)` (field): checks a value against
  the annotation and warns (default), raises `TypeError` (`'error'`/`True`), or
  is off (`False`). It runs on *user-supplied* values (constructor / `data=` /
  assignment, and parsed argv/env), but **not** on a field's own trusted default
  — a WYSIWYG `Value('512')` never warns about itself. Combined with parsers no
  longer warning on value-level no-match, mismatches are reported exactly once,
  uniformly across `auto`/`csv`/`yaml`/custom. **[REVISED 2026-06; default
  flipped off → 'warn']**

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
- **Mechanism: a function facade in `kwconf/__init__.py` — no `.pyi`.**
  **[IMPLEMENTED, chunk 6]** Public `kwconf.Value`/`kwconf.Flag` are
  `@overload`ed *functions* returning `T`, wrapping the real runtime classes
  `kwconf.value._Value`/`_Flag`. Internals import the classes via
  `from kwconf.value import _Value as Value`, so `isinstance`/attribute access/
  `._from_action` are unaffected and the ty CI gate stays green — no `.pyi`, no
  class rename. Tradeoff: `isinstance(x, kwconf.Value)` and subclassing the
  *public function* break at runtime; subclass/`isinstance` against the exported
  `kwconf.ValueClass`/`FlagClass` (aliases of `_Value`/`_Flag`) instead.
  Verified: `x: int = Value(None)` errors on ty, mypy, AND pyright
  through `from kwconf import Value`, positionally. **[REVISED 2026-06:
  `ValueClass`/`FlagClass` now exported; no longer "future".]**
- **Do NOT use PEP 681 `converter`** for coercion. The spec's `converter`
  rewrites constructor/assignment *types* — the opposite of our "constructor
  trusts, does not coerce" boundary. (mypy doesn't support it yet anyway.)
  Coercion stays in the ingestion path. **[LOCKED]**
- **Runtime field metadata is a separate API** from the typed surface: collect
  `Value` objects in the metaclass into `Config.__kwconf_fields__` /
  `Config.fields()`. Statically, `MyConfig.x` and `cfg.x` are the *field type*
  (`int`), not the wrapper — internals must not expect to recover wrappers from
  `MyConfig.x`. **[LOCKED]**
- **`dataclass_transform` (constructor-kwarg checking) — OPEN.** Positional
  defaults make the synthesized `__init__` mark every `Value`-wrapped field as
  **required** on mypy + pyright (spec: standardized field-specifier params are
  keyword-only — *no* spec-conformant workaround, confirmed by the GPT report),
  producing spurious "missing field" errors when a defaulted wrapped field is
  omitted. Bare `x: int = 5` and keyword `Value(default=…)` fields are fine. So
  whether to apply `dataclass_transform` is the live fork (see §6.1).

### Verified checker facts (mypy 2.1.0 · pyright 1.1.410 · ty 0.0.49)

- Default-vs-annotation validation: works on all three, positionally (it's a
  plain typed assignment once `Value -> T`).
- mypy + pyright fully synthesize/check `__init__` (bad kwarg type, unknown
  kwarg, missing required). **ty 0.0.49 does NOT** for hand-rolled transforms —
  it does default-validation only. RE-VERIFIED 2026-06-17 on
  `dev/poc/poc_typing/gpt_recipe.py` (GPT's recommended metaclass+keyword shape):
  mypy/pyright caught all 4 errors, ty caught only the default. The GPT report's
  "couldn't reproduce the ty gap" does not hold on our setup. ty#1327 is
  closed/Stable, so treat ty's gap as transient and assume it lands.
- **Implication for a ty-primary user:** since ty does no ctor checking either
  way today, positional `Value(10)` forfeits *nothing on ty right now* — it only
  forfeits mypy/pyright ctor checking.
- Positional `default` ⇒ field read as required by mypy + pyright (and ty when
  it synthesizes).
- `required=True`/no-default → field correctly required.
- Bare `x: int = 5` is fully checked and correctly optional everywhere.

Policy: **do not cater to type-checker bugs/incompleteness.** Follow PEP 681 /
the typing spec so it works now or eventually. Separate transient checker gaps
(ignore) from real spec constraints (design around).

## 6. Open questions (consolidated)

1. **[RESOLVED 2026-06-17 — Option A]** Do not apply `dataclass_transform`.
   There is *no* spec-conformant way to keep positional `Value(10)` AND get
   clean constructor-kwarg checking (GPT confirmed; ty/mypy/pyright agree). So:
   - **(A) CHOSEN — positional-first / no transform:** keep positional
     `Value(10)`; deliver static checking via `Value -> T` default-validation
     (works on ty/mypy/pyright) + bare `x:int=5` for fully-checked simple fields.
     No false positives; no static ctor-kwarg checking. The `@dataclass_transform`
     decorator on `MetaConfig` is removed.
   - (B) rejected: apply `dataclass_transform`, steer metadata fields to keyword
     `Value(default=…)`; positional `Value(10)` would then read as "required"
     (spurious "missing field" on mypy/pyright). Not worth it for a ty-primary,
     positional-first project. Revisit only if an opt-in "strict" mode is wanted.
2. ~~Mechanism to keep `Value` a runtime class while typing `-> T`.~~
   **RESOLVED:** `.pyi` facade (see §5). **[LOCKED]**
3. **[TODO]** Contents of the `coerce` registry and the per-type `str -> T`
   parsers, especially container handling.
4. **[TODO]** The ingestion-adapter refactor (move parsing off the assignment
   path; add argv/env adapters + `Config.coerce`).
5. **[OPEN]** Revisit whether `: bool` should auto-imply flag behavior before
   public release.

## 7. Migration from scriptconfig

- `type=` → `parser=`, with `type=` kept as a **deprecated alias** for a long
  while. **[LOCKED intent]**
- Comma-splitting removed: `"1,2,3"` no longer auto-splits → use `nargs` or
  `parser='csv'`. Call this out loudly in the migration guide. **[LOCKED]**
- Positional `Value(...)` idiom is preserved, which keeps migration low-churn.
  **[LOCKED]**
