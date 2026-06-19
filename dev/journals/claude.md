# kwconf successor — design journal

Durable cross-machine notes from design sessions with Claude. Memory written
here (instead of machine-local agent memory) so it survives machine changes.

---

## 2026-06-17 — `Value` API, `smartcast` rework, coercion boundary, typing

Context: reworking kwconf into a "scriptconfig successor without the footguns."
Started from the `type=` kwarg on `Value` and expanded into smartcast, the
coercion boundary, and static-typing guarantees.

### Decisions made (still pre-implementation; POCs only)

- **`Value(type=...)` → `Value(coerce=...)`.** The old `type` kwarg is
  overloaded across three jobs: argparse `type=`, a smartcast hint, and a
  container "shape" (`list`/`dict`, which must NOT be called as `list(str)`).
  Rename to `coerce` (matches the existing `Value.coerce()` method, honest that
  it's best-effort not a strict cast, and doesn't collide with "the parser" =
  ArgumentParser). `coerce` may be a callable or a string key into a registry
  (e.g. `'yaml'`, `'csv'`).

- **The untyped default parser is named `'auto'`** (drop the "smart"/"smartcast"
  name — "smart" in a name ≈ footgun).

- **Annotation gates parsing.** The PEP 526 field annotation is the source of
  truth for the value type. A `X | Y | None` union bounds the candidate set the
  `auto` parser may produce. Invariant: *runtime output type ∈ annotation union*,
  with one deliberate exception (warn + fall back to string). So annotations are
  **statically binding but runtime-advisory**.

- **No comma-splitting** (the real scriptconfig footgun, not bool/None parsing):
  `"1,2,3"` stays the string `"1,2,3"` under every annotation. Lists come from
  `nargs`, `coerce='csv'|'yaml'`, or an already-typed source.

- **Coercion boundary (DECIDED — user 100% on board).** The normal Python
  constructor `MyConfig(x='123')` TRUSTS the user and does NOT coerce (`x` stays
  `'123'`). We never fail on type inconsistencies at the Python boundary; static
  analysis is the only guard there ("if we wanted strict we'd write Rust").
  Coercion happens ONLY at the text boundary (argv, env). Implication: parsing
  must move OUT of the universal `coerce()`/assignment path and INTO ingestion
  adapters (argparse/env). Core = trust; adapters = parse. Add an opt-in
  alt-constructor **`Config.coerce(key=val, ...)`** that parses string inputs
  (also handy for tests).
  - This is *forced* by the typing direction: with `dataclass_transform`,
    `MyConfig(x='123')` is already a static error for an `int` field. If runtime
    *also* coerced it, the checker and runtime would disagree on the same line.
  - Complementary guarantees: Python boundary = statically checked, no runtime
    coercion; argv boundary = no static info, runtime parse.

- **bool/int precedence.** Fixed global precedence
  `None → int → float → complex → bool → str` (`str` always last = catch-all),
  intersected with the annotation. `int` claims `"1"`; `bool` claims `"1"`/`"0"`
  only when int is absent, and always claims `"true"`/`"false"`. So `"true"`
  under `int | None` (no bool/str) → warn + fall back to string.

- **The annotation now carries three jobs** that usually agree but can diverge:
  static attribute type, the parse candidate menu, and default-value validation.
  `coerce=str` on an `int` field deliberately breaks job-1-vs-2 alignment; that's
  the sanctioned escape hatch. Precedence: explicit `coerce` > annotation-derived
  `auto` > untyped `auto`.

### Open questions / not yet decided

- Containers are the relocated footgun: `list[int]` annotation must NOT mean
  `list(str)`. Needs a per-type string→T parse registry that special-cases
  containers. Single CLI token → list requires `nargs` or `coerce='csv'|'yaml'`.
- PEP 563 stringized annotations (`from __future__ import annotations`) require
  runtime `get_type_hints()` to drive parsing → can `NameError`; need a fallback
  to `Any`. (kwconf already has `kwconf/annotations.py` doing best-effort
  resolution.)
- dict-style `__default__ = {...}` configs have no annotations → always `auto`
  unless we add per-field `coerce=`.
- `bool | None` parsing `"123"` currently → `True` (`bool(int("123"))`). Decide
  whether bool should accept only `0/1/true/false` when not unioned with `int`.
- Should `choices=[1,2,3]` inform the parser's target type? (Probably yes.)
- Does annotation `: bool` auto-imply flag behavior, or still require `Flag()`?

### Static-typing POC results (ty 0.0.49, pyright 1.1.410, mypy 2.1.0, Python 3.12)

POCs in `dev/poc/` (see `dev/poc/FINDINGS.md`). The user uses **`ty`**. Venv at
`dev/poc/.venv` (git-ignored). Reproduce:
```
cd dev/poc
.venv/bin/pyright --pythonpath .venv/bin/python poc_typing/<file>.py
.venv/bin/ty check --python .venv poc_typing/<file>.py
.venv/bin/mypy poc_typing/<file>.py
.venv/bin/python poc_auto_parser/auto_parser.py
```

CORRECTION to an earlier-in-session over-claim ("ty doesn't support
dataclass_transform"): ty issue astral-sh/ty#1327 ("dataclass_transform
support") is **closed/completed** (Stable milestone). The published **ty 0.0.49**
binary doesn't yet synthesize a checking `__init__` for hand-rolled transforms,
but per the user's principle we **follow the spec and assume it lands**. Both
**mypy and pyright already implement it fully today**. So this is a transient
gap, not a design blocker.

Policy (user): don't cater to type-checker bugs/incompleteness. Follow PEP 681 /
the typing spec so it works now or eventually. Distinguish transient checker
gaps (fine to ignore) from real spec constraints (must design around).

Checker matrix on the verified recipe (field-specifier fns returning `T`,
`@dataclass_transform`, keyword `default=`):

| check | mypy 2.1.0 | pyright 1.1.410 | ty 0.0.49 |
|---|---|---|---|
| bad default `x: int = Value(default=None)` | ✔ | ✔ | ✔ (plain assignment) |
| bad ctor kwarg `C(x='3')` | ✔ | ✔ | ✗ (not synthesized yet) |
| unknown kwarg `C(nope=1)` | ✔ | ✔ | ✗ (not synthesized yet) |
| generic `@dataclass_transform` decorator form | ✔ | ✔ | ✗ (stdlib `@dataclass` only) |
| keyword-default field treated optional | ✔ | ✔ | n/a |

1. **`Value` must be typed to return `T`** (the value type), NOT the `Value`
   wrapper — the attrs/pydantic trick. Then `x: int = Value(default=None)` is a
   static error on ALL THREE checkers (it's a plain typed assignment; needs no
   `dataclass_transform`). Today's `Value` is typed to return `Value`, so the
   check never fires (and misfires as "Value not assignable to int" under pyright).
   **Cheapest high-value change.**

2. **REAL CONSTRAINT (not a checker bug): the field-specifier `default` must be
   passed by KEYWORD.** Positional `Value(10)` is treated as a REQUIRED field by
   BOTH mypy and pyright (so `MyConfig()` errors "missing field"). This matches
   the spec: the standardized field-specifier parameters (`default`,
   `default_factory`, `factory`, ...) "must be keyword-only." Implication for the
   API:
   - simple fields → bare attribute `x: int = 5` (full checking, optional, no
     wrapper); kwconf already collects bare class attrs as defaults.
   - metadata fields → `x: int = Value(default=5, help=..., alias=...)`, i.e.
     the positional `Value(5)` idiom must become keyword `Value(default=5)`.
   - This is the one finding that should actually shape the `Value` signature.

3. `required=True` with no default → field-specifier overload returns `Any`
   (type from the annotation; field required). ✔

4. An explicit `__init__` on the BASE `Config` (kwconf has
   `__init__(self, *args, **kwargs)` at config.py:485) does NOT suppress
   transform `__init__` synthesis on subclasses under pyright/mypy (subclasses
   define no `__init__`). ✔

5. kwconf applies the transform on the **metaclass** (config.py:336); spec
   supports decorator/metaclass/base forms. mypy+pyright handle the metaclass
   form; ty 0.0.49 doesn't synthesize for it yet (transient).

Verified recipe: `dev/poc/poc_typing/recipe_recommended.py` → mypy & pyright
report exactly the 3 intended errors; ty 0.0.49 reports the 2 default-validation
errors (no false positives). (Value/Flag as field-specifier functions returning
`T`, keyword defaults, `@dataclass_transform(field_specifiers=(Value, Flag), kw_only_default=True)`.)

### Auto parser POC

`dev/poc/poc_auto_parser/auto_parser.py` implements the annotation-gated `auto`
parser + the boundary model (`Config` ctor trusts; `Config.coerce()` parses,
"parse iff the value is a `str`"). Self-test PASSES. Matrix output shows
`"1,2,3"` staying a string under every annotation and `str` annotation pinning
all tokens to string.

### Likely next steps

- (a) Wire the `-> T` typing onto the real `Value` and run ty/pyright over the
  existing test configs to see what lights up.
- (b) Design the `coerce` registry + ingestion-adapter refactor (move parsing
  out of assignment into argv/env adapters; add `Config.coerce()`).
