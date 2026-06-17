# kwconf successor — typing & `auto` parser POCs

Date: 2026-06-17. Checkers: `ty` 0.0.49, `pyright` 1.1.410 (Python 3.12, uv venv
at `dev/poc/.venv`).

Two questions were prototyped:

1. Can a static type checker validate a field's **default** and **constructor
   kwargs** against its annotation, given the `Value(...)` wrapper? (`poc_typing/`)
2. What do the **`auto` parser** semantics (annotation-gated, no comma-split)
   and the **parse-only-at-the-text-boundary** rule look like in practice?
   (`poc_auto_parser/`)

Reproduce:
```
cd dev/poc
.venv/bin/pyright --pythonpath .venv/bin/python poc_typing/<file>.py
.venv/bin/ty check --python .venv poc_typing/<file>.py
.venv/bin/python poc_auto_parser/auto_parser.py
```

## TL;DR for someone who uses `ty`

- **Field-default validation works on both ty and pyright** — `epochs: int =
  Value(None)` is an error — *but only if* `Value` is typed to return `T` (the
  value type), not the `Value` wrapper. Today's `Value` is typed to return
  `Value`, so this check does not fire (and would actually misfire as "`Value`
  not assignable to `int`" under pyright). This is the cheapest, highest-value
  change.
- **Constructor-kwarg checking** (`MyConfig(x='3')` → error; unknown-field →
  error) needs `dataclass_transform`'s `__init__` synthesis. **mypy 2.1.0 and
  pyright 1.1.410 both support it fully** (all transformer forms). The published
  **ty 0.0.49** binary doesn't synthesize a checking `__init__` for hand-rolled
  transforms yet — but ty's tracking issue astral-sh/ty#1327 is closed/completed
  (Stable milestone), so this is a transient gap. Per project policy we follow
  the spec and assume it lands.
- **REAL spec constraint (all checkers):** the field-specifier `default` must be
  passed by KEYWORD. Positional `Value(10)` is treated as a *required* field by
  both mypy and pyright (the spec says the standardized field-specifier params
  are keyword-only). So either use bare `x: int = 5` for simple fields or
  `Value(default=5, ...)` for metadata fields — the positional `Value(5)` idiom
  cannot be both wrapped and optional.

## Finding 1 — type `Value` as a field specifier returning `T`

The attrs/pydantic trick: the field specifier is *typed* `-> T` even though it
returns a wrapper at runtime. Then `x: int = Value(default=10)` reads as
`int = int` (clean) and `x: int = Value(default=None)` reads as `int = None`
(error). Returning `Value[T]` instead makes pyright reject **correct** fields
(`Value[int]` is not `int`). See `value_proposed.py` vs the first attempt.

- `Value(default=10)` → ok; `Value(default=None)` for `int` → error. ✔ both checkers
- factory: `Value(default_factory=lambda: ["a"])` for `list[int]` → error. ✔ both
- `required=True` with no default → overload returns `Any` (no `T` to infer;
  type comes from the annotation, field is required). ✔

## Finding 2 — `dataclass_transform` support differs by checker AND by form

| transform applied via | pyright | ty 0.0.49 |
|---|---|---|
| stdlib `@dataclasses.dataclass` (control) | ✔ | ✔ |
| `@dataclass_transform` on a **decorator fn** | ✔ | ✗ (not checked) |
| `@dataclass_transform` on the **base class** | ✔ | ✗ synth, but **no false positives** |
| `@dataclass_transform` on the **metaclass** (kwconf today) | ✔ | ✗ synth; falls back to `object.__init__` → **false positives** *unless* the base defines a permissive `__init__` |

- kwconf applies the transform on the **metaclass** ([config.py:336](../../kwconf/config.py#L336))
  and the base `Config` defines `__init__(self, *args, **kwargs)`
  ([config.py:485](../../kwconf/config.py#L485)). The permissive `__init__` means ty
  does not emit false positives, but it also means **no kwarg checking** under ty.
- An explicit `__init__` on the **base** does **not** suppress synthesis on
  subclasses under pyright (subclasses don't define their own), so pyright still
  synthesizes and checks `MyConfig(...)`. (`probe_explicit_init.py`)
- Recommendation: keep the metaclass form (works in pyright; harmless in ty once
  a permissive base `__init__` exists). Revisit when ty ships generic support.

## Finding 3 — pyright treats a *positional* default as REQUIRED

`Value(10)` (positional) makes pyright consider the field **required**, so
`MyConfig()` errors "missing field". Confirmed against pydantic itself:
`x: int = Field(5)` shows the same. Only **keyword** `default=` /
`default_factory=` (or a bare class attribute) mark a field optional in pyright.
ty doesn't synthesize `__init__`, so it is unaffected.

Consequence: the ergonomic `Value(10)` positional form is a poor fit if we want
pyright's constructor synthesis. Options: require `default=` keyword, or accept
that positional defaults read as required under pyright. (`probe_defaults.py`,
`probe_single.py`)

## Recommended recipe (verified)

`recipe_recommended.py` — pyright reports exactly the 3 intended errors (2 bad
defaults + 1 bad kwarg); ty reports the 2 default-validation errors and is
silent (no false positives) on construction.

- `Value`/`Flag` = field-specifier **functions returning `T`**
- `@dataclass_transform(field_specifiers=(Value, Flag), kw_only_default=True)`
- defaults passed by **keyword** (`default=`, `default_factory=`)
- `required=True` overload → `-> Any`

## `auto` parser POC (`poc_auto_parser/auto_parser.py`, self-test PASSES)

- Fixed precedence `None → int → float → complex → bool → str` (str = catch-all),
  **intersected with the annotation** (the candidate menu).
- `int` precedes `bool`, so `"1"` → `int 1` when int is allowed; `bool` claims
  `"1"`/`"0"` only when int is absent, and always claims `"true"`/`"false"`.
- No comma-splitting: `"1,2,3"` stays the string `"1,2,3"` under every annotation.
- `str` annotation pins everything to string (the `coerce=str` escape hatch as a type).
- When nothing matches and `str` isn't allowed → **warn + fall back to string**
  (annotations are statically binding but runtime-advisory).
- `list[int]` etc. cannot be built from one token → warn pointing at
  `coerce='csv'|'yaml'` or `nargs`.
- Boundary: `Demo(n="123").n == "123"` (constructor trusts); `Demo.coerce(n="123").n
  == 123` (opt-in textual path, mirrors argv/env; parses iff value is a `str`).

### Open knob surfaced by the POC
`bool | None` parsing `"123"` currently yields `True` (`bool(int("123"))`).
Decide whether bool should accept only `0/1/true/false` rather than any int-ish
string when it shares no union with `int`.
