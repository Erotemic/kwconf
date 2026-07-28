# kwconf codebase audit — 2026-07-02

> **Follow-up:** the 2026-07-27 release-readiness pass, its eight release-gate
> fixes, and the remaining tracked defects are recorded in
> [`2026-07-27-release-readiness-audit.md`](2026-07-27-release-readiness-audit.md).

> **Current status (revalidated 2026-07-10).** The remediation pass fixed and
> regression-tested every high-severity finding in §1, but the audit is **not
> fully closed**. Several concrete correctness defects from §§2–3 remain
> reproducible, including dropped constructor arguments, modal
> inheritance/discovery failures, and invisible unknown-attribute writes.
> Conflicting SubConfig selector spellings are now safe by default and have
> opt-in warning/error diagnostics through `cli(validate=...)`. Alias hijacking now has an
> **opt-in safeguard**, not an automatically enforced fix: projects can call
> `MyConfig.validate()` in tests or CI, while normal class construction and CLI
> startup do not rescan static schemas. The next planning step is to turn that
> seed API into a coherent, recursive, side-effect-free validation subsystem.
> See [§8 Current sequencing](#8-current-sequencing-updated-2026-07-10) and
> [§9 Remediation status](#9-remediation-status-revalidated-2026-07-10).
>
> Current verification snapshot: **397 passed, 2 skipped**;
> `uv run --extra linting ./run_linter.sh` and
> `uv run --with ty ty check ./kwconf` pass. The narrower configured Ruff gate
> for `kwconf/` and `tests/` is clean, but `ruff check .` still reports nine
> fixable issues outside that gate. GitLab's lint job is currently
> `allow_failure: true`, and GitHub does not run Ruff, so “Ruff enforced across
> the repository” is not yet accurate.

Audited at version 0.10.1 (unreleased), branch `dev/0.10.1`, commit `03cff1f`.

**Method.** Full read of every module in `kwconf/` (~8.7k lines including
`_cli/` and `util/`), plus packaging, CI, tests, and docs. Findings marked
**[verified]** were reproduced by executing code against the current tree
(Python 3.13/3.14 via `uv run`); everything else was confirmed by reading the
source. Line numbers are as of commit `03cff1f`.

**Relationship to the design doc.** Nothing here contradicts the locked
decisions in `dev/planning/design.md` (trust-the-Python-boundary, positional
`Value(10)`, `parser=` over `type=`, static typing as a bonus). Several
findings are cases where the implementation fails to deliver on those locked
decisions (e.g. union-aware coercion, WYSIWYG defaults).

**Original audit snapshot.** Test suite: 332 collected, 328 passed, 4 skipped,
~1s. `ty check ./kwconf` green in CI. The architecture is sound and the design
voice is consistent; the problems below are concentrated in a handful of
systemic patterns (shared mutable templates, duplicated load paths,
argparse-internal pinning) rather than spread uniformly.

---

## 1. High-severity correctness bugs

These break mainstream usage or silently corrupt state. Roughly ordered by
impact.

### 1.1 `.cli()` shares the class-level mutable default object across instances **[verified]**

`config.py:1641-1653`. In the argv-defaults merge, `default_value =
self.__default__[key].value` reads the **class** template (materializing and
caching `default_factory` output on it), and `_setitem` stores that same
object into instance `_data`. Consequences:

- `tags: list = Value(default_factory=list)` → `c1 = C.cli(argv=[]); c2 =
  C.cli(argv=[])` gives `c1['tags'] is c2['tags'] is
  C.__default__['tags'].value`; appending to one shows up in the other.
- For plain mutable defaults (`items = Value(['a'])`), mutating one instance
  permanently mutates the class default — all future instances inherit the
  mutation.

This defeats `default_factory` (whose entire purpose is per-instance copies)
and undermines the WYSIWYG-defaults contract. `_materialize_default_items` /
`clone_default` already do the per-instance copying correctly; this one merge
path bypasses them.

### 1.2 Mixing `SubConfig` with dict-valued fields crashes `load()` **[verified]**

`subconfig.py:753-765` with `_flatten_nested` at `subconfig.py:405-427`.
`apply_dot_updates` flattens *every* nested mapping into dotted keys without
knowing whether a mapping is a subconfig node or a plain dict leaf. The final
leaf loop calls `_ensure_parent_node` uncaught, so a config with `inner =
SubConfig(Inner)` and `hyperparams = {'lr': 0.1}` raises `KeyError:
'hyperparams'` on `cfg.load({'hyperparams': {'lr': 0.5}}, argv=False)`. The
same path is hit by `--config` files and `pending_updates`
(`config.py:1308-1316`). Also: non-string dict keys (e.g. `{1: 'a'}` from
YAML) crash `'.'.join` with `TypeError`. Dict-typed leaf fields alongside
subconfigs is a mainstream scriptconfig pattern — this is a hard regression.

### 1.3 Provenance collapses when an option precedes the subcommand — modal subcommands run with defaults **[verified]**

`argparse_ext.py:1014-1036` (`_deepest_subparser_for_argv`) matches
subcommands only as *leading* tokens; the walk breaks on the first token not
in `choices` and never skips option tokens. `parse_known_result(['--verbose',
'cmd', '--opt=1'])` returns the root as `selected_parser` and `explicit_keys
== []`. In `ModalCLI.main` (`modal.py:866-868, 927`) `explicit_kw` is then
silently empty, so the subcommand's `main(**explicit_kw)` receives **no
user-supplied values** whenever any root-level option (or `--`) precedes the
command name. Also mis-attributes strict-mode errors and usage text to the
root parser.

### 1.4 `@register` used as a decorator binds the class to `None` **[verified]**

`modal.py:507-528`. `_wrapper` never returns `cli_cls`, so both
`@modal.register` and `@ModalCLI.register(command=...)` evaluate to `None`.
The module's own docstring examples (`modal.py:207-216, 287-303`) use exactly
this pattern and only pass because they never reference the name afterward.
Any later reference (`Command1.main(...)`, imports, tests) hits
`AttributeError` on `None`. One-line fix.

### 1.5 `--config` special option wipes previously merged `data=` values **[verified]**

`config.py:1655-1659`. Handling `--config` calls a full recursive
`self.load(...)`, whose first act (`config.py:1301`) resets `_data` to
defaults before applying the file. `C.cli(data={'a': 1}, argv=['--config',
f])` where the file only sets `b` yields `a == 0` (class default). Effective
precedence is "config file resets everything", including keys the file never
mentions.

### 1.6 `required=True` is enforced by value-equality with the default **[verified]**

`config.py:1343-1355` + `value.py:1042` (`self.required = False  # hack`
disables argparse's own enforcement). The fallback check `if self[k] ==
v.value: raise Exception(...)` fires even when the user *did* explicitly pass
the default value (`Value(0, required=True)` with `--k=0` raises). The
`_explicit_argv_keys` provenance that would decide this correctly exists
(`config.py:609`) but is not consulted. Also raises bare `Exception`, and `==`
against exotic defaults (e.g. numpy arrays) would itself error.

### 1.7 `position=` is computed but never applied **[verified]**

`config.py:2831-2837`. `_keyorder` is sorted by position but — as the code's
own NOTE admits — "currently computed but unused downstream (the build loop
iterates self._data)". Declaring `second = Value(None, position=2); first =
Value(None, position=1)` and parsing `['AAA', 'BBB']` yields `first='BBB',
second='AAA'`. The duplicate-position check works; the ordering it implies
never happens.

### 1.8 Annotation processing mutates shared `Value` templates in place **[verified]**

`config.py:150-229` (esp. 175-176, 218). `value._annotation = annotation`
runs before any `.copy()`. Subclass `__default__` merging shares template
objects with bases, so an annotation-only override in a subclass (`class
Sub(Base): x: str` over `Base`'s `x: int = Value(0)`) rewrites the *base
class's* template — `Base(x=5)` then spuriously warns that 5 doesn't match
`str`.

### 1.9 `Literal[...] | str` unions restrict the CLI to the literal values **[verified]**

`annotations.py:245-252` (`choices_from_annotation`). The union branch returns
the first member's choices, ignoring that a sibling `str` member permits any
string. `mode: Literal['a','b'] | str = 'a'` + `--mode custom` → `invalid
choice` + `SystemExit`. Related: a union of multiple `Literal`s returns only
the first literal's choices (`Literal['a'] | Literal['b']` → `('a',)`), making
`'b'` unreachable from the CLI.

### 1.10 `Optional` container annotations silently skip element coercion **[verified]**

`coerce.py:143-174` (`element_annotation`). `list[int] | None` is not
unwrapped (the union origin matches no container branch), then
`_candidate_types` reduces to `[NoneType]` and each token falls back to
string. `items: list[int] | None = Value(None, nargs='*')` with `--items 1 2
3` yields `['1','2','3']` plus a spurious validation warning; `csv` parsing
has the same hole. `Optional[list[T]]` is arguably the most common container
annotation, and design.md locks union-aware coercion in.

### 1.11 `exit_on_error=False` is silently ignored **[verified]**

`argparse_ext.py:600-602`. `CompatArgumentParser.__init__` pops
`exit_on_error` *before* calling `super().__init__()`, and stdlib argparse
(3.9+) re-sets the attribute to its own default, clobbering the popped value.
Every downstream branch keyed on `exit_on_error` (`parse_known_args`,
`parse_result`, `ExtendedArgumentParser.parse_args:996`, `modal.py:841`) never
sees the user's `False`; callers expecting `ArgumentError` get `SystemExit`.
The class docstring says it exists for Python 3.6–3.8 compatibility — versions
no longer supported. Fix: assign after `super().__init__`.

### 1.12 `CounterOrKeyValAction` corrupts values starting with the option's first letter **[verified]**

`argparse_ext.py:424-453`. The grouped-short-option normalization (`-vvv` →
count) triggers for *any* option string starting with `-` — including long
options — and strips leading characters equal to the option's first letter.
Failures: `--flag=false` → `'alse'`; `--verbose=vip` → `'ip'`; `--flag=ff` →
`3`; `-f fff` (separate token) → `4`. The guard must require an actual short
option and only fire for the joined `-vvv` spelling.

### 1.13 Opaque modal commands read a stale or undefined `parserkw` **[verified]**

`modal.py:663-674`. The opaque-command branch uses `**parserkw` *before* the
line that assigns `parserkw` for this command, so it picks up whatever was
left over: the root's kwargs, the previous command's kwargs (including
`aliases` — on 3.13 this raises `conflicting subparser alias` at build time;
on older Pythons the alias is silently hijacked), or nothing at all
(`UnboundLocalError` when the opaque command is first inside a nested modal).

### 1.14 `Config.__json__` truncates output **[verified]**

`config.py:912-914`. Inside the walker loop, `if hasattr(item, '__json__'):
return item.__json__()` returns from the whole method instead of assigning
`walker[path] = item.__json__()` — a config containing one nested
`__json__`-capable object serializes to just that object's JSON, dropping
every other key.

### 1.15 Sphinx docs build crashes on Python 3.14 **[verified]**

`docs/source/conf.py:135`. `parse_version` uses `node.value.s`;
`ast.Constant.s` was removed in 3.14, so `sphinx-build` dies with
`AttributeError`. RTD pins 3.13 so published docs still build, but the repo's
own dev/CI Python is 3.14. Fix: `node.value.value`.

---

## 2. Medium-severity bugs and surprising behavior

### File/data loading

- **Nonexistent config path treated as YAML content** **[verified]** —
  `subconfig.py:365` and the duplicated copy at `config.py:281`: `isinstance(data,
  str) and ('\n' in data or not os.path.exists(data))` routes a mistyped path
  into the YAML-string branch. `--config typo.yaml` → `TypeError: Expected
  mapping`; `C.cli(data='no_such_file.yaml')` → `AttributeError` (strict mode
  lists the *characters* of the filename as unknown options). Should raise
  `FileNotFoundError` and validate the parsed payload is a Mapping. An empty
  YAML file (parses to `None`) crashes `load` at `config.py:1266`.
- **`load()` mutates the caller's `data` dict** **[verified]** —
  `config.py:279` returns dict input as-is; `load` then renames alias keys and
  pops unknown keys in the caller's object (`config.py:1274-1296`).
- **`load()` is reset-then-merge** **[verified]** — `config.py:1301` resets
  every key not present in the new source back to defaults. May be intentional,
  but the docstring says "updates" and it contradicts the dict-like `update()`
  semantics the class otherwise mimics. Document loudly or change.
- **Empty-dict updates are silently dropped** **[verified]** —
  `subconfig.py:416-427`: `cfg.load({'hyperparams': {}}, argv=False)` leaves the
  default untouched with no warning.
- **Conflicting `key` + `key.__class__` updates corrupt the tree**
  **[verified]** — `subconfig.py:735-765`: the sugar scan skips keys already in
  `selectors` but never removes them from `leaf_updates`, so `{'optim.__class__':
  'sgd', 'optim': 'adam'}` leaves `cfg['optim'] == 'adam'` (a raw `str` replacing
  the subconfig node) instead of erroring.
- **`scan_config_path` greedily takes the next token** — `subconfig.py:339-346`:
  `--config --verbose` treats `--verbose` as the path; also ignores the `--`
  separator.

### Parser state and reuse

- **`ExtendedArgumentParser.parse_args` permanently flips `exit_on_error`**
  **[verified]** — `argparse_ext.py:987-1011`: line 1001 mutates with no
  `finally`; a reused parser leaks raw `ArgumentError` on the second parse
  instead of the SystemExit+usage policy.
- **`_explicitly_given` accumulates across parses** **[verified]** —
  `argparse_ext.py:292-297`: nothing in argparse_ext clears the set (only
  `Config.argparse` does, at build time). A reused parser reports stale
  provenance — and `ParseResult.explicit_keys` is the package's core provenance
  primitive.
- **Fuzzy hyphens silently disabled by `allow_abbrev=False` on 3.12.3+**
  **[verified]** — `argparse_ext.py:826-844`: the POST-GH-114180 variant nests
  the exact normalized match inside `if self.allow_abbrev:`; the PRE variant
  checks it outside the guard, so the same program behaves differently across
  interpreter versions. Hoist the exact-match out of the abbrev branch.
- **`dump()` mutates global PyYAML state** **[verified]** —
  `config.py:1728-1737` installs a `dict` representer on the shared
  `yaml.SafeDumper` on every call, changing behavior of unrelated
  `yaml.safe_dump` calls process-wide. Use a local Dumper subclass.
- **Modal metadata dicts are class-shared but instance-mutated** —
  `modal.py:377-385, 388-481`: `_init_subconfig_metadata` returns the same dict
  object for dict inputs, and `_update_metadata` writes live objects
  (`'subconfig'`, `'main_func'`, `'parserkw'`) into class-shared
  `__subconfigs__` entries, contradicting the "per-instance" comment.

### CLI/UX correctness

- **`--dump`/`--dumps` exit 1 on success** **[verified]** — `config.py:1703`:
  `sys.exit(1)` after a successful dump breaks `tool --dumps > cfg.yaml` in any
  pipeline/CI.
- **Intercepted errors drop the argument name** **[verified]** —
  `argparse_ext.py:1004-1009` reports `ex.message` (`invalid int value: 'bad'`)
  instead of `str(ex)` (`argument --num: invalid int value: 'bad'`); with several
  typed options the user can't tell which failed.
- **`--version <child>` prints the child's version (or literal `None`)**
  **[verified]** — `modal.py:869-882`: root's version is unreachable once a
  child command token appears; a versionless child prints `None` and returns 0.
- **No-command handling prints the wrong prog and a misleading message**
  **[verified]** — `modal.py:884-910`: builds a fresh parser whose prog derives
  from `sys.argv[0]` (`usage: -c ...`); root-no-command claims "A submodal CLI
  was executed"; the `sub_main is None` branch is unreachable dead code.
- **`ModalCLI.main(argv=False)` crashes** **[verified]** — `modal.py:790-797`:
  the guard only handles *truthy* int/bool sentinels; falsy `argv=False`/`0`
  (the established `Config.main` convention) falls into a list comprehension
  over `False` → `TypeError`.
- **`special_options=True` collides with user fields named
  `config`/`dump`/`dumps`** **[verified]** — `config.py:2865-2896` raises
  `ArgumentError: conflicting option string` at parser build with no pre-check
  or clearer diagnostic.
- **`from_env(prefix='')` reads arbitrary environment variables** —
  `config.py:668-697`: with the default empty prefix, a config with a `path`,
  `home`, `user`, or `lang` field silently absorbs `$PATH`/`$HOME`/etc. The
  dangerous behavior is the *default*; consider requiring a prefix or warning.
  (Also shadows the module-level `import os`.)

### Class construction semantics

- **Silent field-dropping in class bodies** **[verified]** —
  `config.py:232-245`: annotation-only fields (`annotation_only: str`) produce
  no field (dataclass users expect a required field); a field literally named
  `default` is skipped by a legacy-compat guard; callable defaults are treated
  as methods. All silent — at minimum warn.
- **Alias collisions silently hijack real fields** **[opt-in validator added
  2026-07-10]** — originally, with `opt1 = Value(1, alias=['opt2']); opt2 =
  Value(2)`, `C(opt2=99)` set `opt1=99` and left `opt2=2`. Projects can now add
  `C.validate()` to their tests or CI to check the complete accepted long-name
  namespace: canonical field names, declared aliases, inherited fields, and
  generated fuzzy-hyphen spellings. Ambiguous schemas raise a targeted
  `ValueError`. The check is deliberately not run during class construction or
  CLI invocation, so already-validated schemas add no recurring startup scan.
- **Extra positional constructor args silently dropped** **[fixed
  2026-07-10]** — construction now raises `TypeError` for extra positional
  values and for duplicate semantic bindings, including positional-plus-keyword
  and canonical-plus-alias forms. The implementation checks argument count
  before default materialization, binds only supplied positional keys, and
  combines alias normalization, duplicate detection, and unknown-key collection
  in one keyword pass rather than adding a schema-wide validation scan.
- **`@dataconf` on a plain class drops underscore attributes and inherited
  fields** **[verified]** — `dataconfig.py:113-136`: the copy loop skips
  everything starting with `_` (killing `__post_init__`, `__validate__`,
  `_helper`) except a small whitelist, and iterates `vars(cls)` only (no MRO
  walk), so fields from plain base classes vanish.
- **`MetaModalCLI` auto-registers every public class-valued attribute; subclassing
  drops inherited commands** **[fixed 2026-07-10]** — command tables now inherit
  declarations from class attributes, `__subconfigs__`, and class-level
  `register()`. Normal subclass attribute overriding replaces or hides an
  inherited attribute-declared command, while unrelated helper classes are no
  longer discovered implicitly. Implicit discovery is restricted to `Config`
  and `ModalCLI`; compatible custom command classes remain available through
  explicit registration.
- **Int-for-float validation warnings** **[verified]** —
  `annotations.py:341-342`: bare `isinstance` check rejects `int` where `float`
  is annotated, violating the PEP 484 numeric tower; with `__validate__='warn'`
  as default, `FloatCfg(x=1)` nags on idiomatic Python. Compounded by
  `format_annotation` (`annotations.py:359-361`) collapsing unions/generics to
  `'Union'`/`'list'` — the one message meant to explain a mismatch names no
  actual type.

### Code generation

- **`port_to_config()` emits invalid code for typed fields** **[verified]** —
  `value.py:406-458` + `config.py:1964-1977`: `_to_value_kw` copies all truthy
  `__dict__` entries, which now includes private `_annotation`,
  `_user_gave_type`, `_parser_spec` → output like `kwconf.Value(3, type=int,
  _annotation=<class 'int'>)` (SyntaxError on exec). Also emits redundant
  `help=None`.
- **Help formatter hides metavars for real `--no-*` options** —
  `argparse_ext.py:526-536, 572-580`: the `startswith('--no-')` +
  `isinstance(default, int)` test can't distinguish auto-generated negations
  from a genuine `--no-cache` option with default `0`/`False`, rendering it as a
  bare flag.

---

## 3. API design concerns

- **The mkinit `__submodules__` spec is a landmine** — `kwconf/__init__.py:37-44`
  lists `'cli'` (no such module — the package is `_cli/`) and `'annotations'`
  (nothing imported from it), and omits `'subconfig'` (from which `SubConfig`
  *is* imported). Running `mkinit -w` as the in-file `__autogen__` comment
  instructs would drop `SubConfig` from the public API, fail on `cli`, and dump
  ~8 annotation helpers into the top level. Fix the spec or delete the comment.
- **`register_parser` is not exported** — it is the documented extension point
  (`coerce.py:23`, docs manual) but users must reach into `kwconf.coerce`.
  Consider adding it to the top-level API.
- **`Config.copy()` returns a plain `dict`** — `config.py:939-940`. The name
  promises an independent Config; it also diverges from `asdict()` (which nests
  subconfigs). Rename, fix, or document.
- **Mapping-contract violation for aliases** — `cfg[alias]` resolves while
  `alias in cfg` is `False` (`config.py:948-1016`, intentional per docstring),
  breaking the `m[k] ⇒ k in m` invariant generic Mapping code relies on. Worth
  an explicit ADR note if kept.
- **Unknown-attribute assignment silently lands in `__dict__`** — initially
  flagged as a dual-namespace footgun, but this is now an explicit design
  decision rather than a correctness defect. The class declaration is the
  persistence contract; undeclared attributes are ordinary transient Python
  state and intentionally do not participate in mapping access, CLI generation,
  validation, serialization, or deserialization. The remaining open question is
  the separate experimental `__allow_newattr__` mode, which promotes unknown
  names into `_data` without yet guaranteeing a complete dynamic-field
  round-trip contract.
- **`expand_multipass_parser` ignores its `parser` argument** —
  `subconfig.py:870-960`: both branches rebuild the parser; the caller-supplied
  one is discarded (the docstring example passes one in).
- **`subconfig.py` `__all__` is incoherent** — `subconfig.py:35-48` omits
  half the underscore-free API that config.py actually calls
  (`coerce_data_updates`, `distribute_explicit_argv_keys`, ...).
- **Bare `Exception` raises** — required-field enforcement (`config.py:1355`),
  new-key rejection (`config.py:1043`). Use typed exceptions (`KeyError`,
  a `RequiredError`, ...) so callers can catch precisely.
- **`NoCommandError(SystemExit)` carries a message string as `code`** —
  `modal.py:959`: exit status works by interpreter convention but is odd for
  programmatic callers; also `modal.py:926-931` prints a noisy duplicate
  `ERROR ex = ...` before every re-raise (with dead `return 1` after `raise`).

---

## 4. Systemic themes (refactor targets)

These recur across findings and are worth fixing as themes, not point-fixes.

1. **Shared mutable state.** Class-level `Value` templates are mutated in
   place (§1.1, §1.8), modal `__subconfigs__` metadata is class-shared but
   instance-mutated, `_explicitly_given` accumulates, `dump()` mutates global
   yaml state. A single ownership rule — *templates are frozen; anything
   per-instance/per-parse is copied first* — would eliminate the whole class.
2. **The `__default__` / `_default` / `_data` state model.** Each can hold
   Values or raw values; `config.py:1635` itself says "this implementation is
   messy and needs refactor". §1.1, §1.5, §1.6 and the load/reset semantics
   are all symptoms. This is the highest-leverage refactor in the package.
3. **Duplicated load/normalize logic.** "str/path/stream → json-try-then-yaml
   → dict" exists twice (`subconfig.py:349-402` vs `config.py:258-311`) and
   has already drifted; SubConfig default normalization exists twice
   (`subconfig.py:247-274` vs `config.py:335-372`); the two ~120-line
   `add_argument` builders in value.py (`:748-992`) have diverged (live parser
   pops `type` for non-flag args, the kw/port path keeps it; only the live
   path has the named-type guard) — so ported argparse code doesn't match live
   CLI behavior; strict unknown-args handling exists twice
   (`argparse_ext.py:163-180` vs `modal.py:836-858`); hyphen-normalize/dedupe
   exists three times (`argparse_ext.py:484-494`, `modal.py:623-638`,
   `modal.py:640-654`).
4. **argparse private-internal pinning.** The layer subclasses `_StoreAction`,
   reimplements `parse_known_args` (frozen at the 3.10 source), overrides
   `_parse_optional`/`_get_option_tuples` (pinned to 3.7.2 / 3.12.3 sources
   behind two hand-maintained version gates), and touches
   `_UNRECOGNIZED_ARGS_ATTR`, `_SubParsersAction`, `_choices_actions`,
   `_negative_number_matcher`, `_defaults`. 3.13 already diverged (stdlib
   added `allow_abbrev` gating and `=`-partition handling to
   `_get_option_tuples`; kwconf's copy has neither — single-dash long options
   abbreviate on 3.13+ even with `allow_abbrev=False`). Every CPython argparse
   refactor requires manual re-porting. Mitigations: a CI job against
   python-dev/prereleases, a conformance test suite that diffs behavior
   against stdlib per version, and shrinking the overridden surface where
   possible.
5. **Subconfig selector machinery.** Three interacting fixpoint loops with
   magic iteration caps (`max_iter = 20` / `32`; `subconfig.py:490-560,
   645-690, 731-751`) plus frame-walking `resolve_localns`/`get_stack_frame`
   (`subconfig.py:57-106`, `stacklevel + 2`, copies caller globals per `cli()`
   call). Hardest-to-reason-about code in the package and the site of §1.2.

---

## 5. Maintainability and dead code

- `util/util_class.py:47-100` — ~55 commented-out lines of `hybridmethod`
  with debug prints. Delete (git remembers).
- `dataconfig.py:139-212` — `__example__` (~70 lines) referenced nowhere;
  `dataconfig.py:123-132` — three branches that all do `namespace[k] = v`.
- `config.py` — `HANDLE_INHERITENCE = 1` debug constant (`:426`, misspelled);
  unreachable `style='orig'` code after the "no longer supported" raise
  (`:1950-1992`); `if 0:` block (`:1998-2006`); redundant if/else both
  choosing `mode='yaml'` (`:1690-1693`).
- `value.py:295` — `_check_values` never invoked (call commented out);
  `value.py:517-521` — `_from_action` stores `repr(group_key)` even for the
  runtime path, so dynamically built classes get group titles like
  `"'mygroup1'"`.
- `subconfig.py:221-223` — `instantiate`'s `_dont_call_post_init` /
  `_enable_setattr` guard is a no-op (`Config.__init__` sets it
  unconditionally); `subconfig.py:977-984` — duplicated `isinstance` check.
- `diagnostics.py:25,27` — `DEBUG_DATA_CONFIG` / `DEBUG_META_DATA_CONFIG`
  have zero uses (stale flags from the removed "DataConfig" name).
- `_ubelt_repr_extension.py:22-25` — unreachable `else` branch; relies on
  private `ub.util_repr._REPR_EXTENSIONS` (already carries one rename
  fallback) — any ubelt refactor silently disables it.
- `argparse_ext.py:408-414` — `key_default` assigned only inside an `if`
  with no else; latent `UnboundLocalError` (the Boolean parent class raises a
  proper error in the same situation).
- Outstanding in-code markers worth triaging into issues: `value.py:95`
  (deprecate `position` — see §1.7 before deciding), `value.py:889` (merge the
  duplicated builders — see theme 3), `config.py:1635` (state-model refactor —
  theme 2), `config.py:2662` (FIXME: `--foo=bar baz biz` with `nargs='+'`),
  `modal.py:607` (`group` metadata collected but never used),
  `modal.py:504` (stale TODO — `alias=` already exists),
  `dataconfig.py:86` (xdoctest module-scope simulation).
- Complexity hotspots (for when they're next touched): `Config.load` ≈220
  lines, `_read_argv` ≈310, `Config.argparse` ≈280, `port_to_argparse` ≈320,
  `ModalCLI.argparse` ≈190, `ModalCLI.main` ≈180,
  `CounterOrKeyValAction.__call__`.

---

## 6. Tooling, CI, and packaging

- **Ruff is configured but never enforced** — not in CI, `run_linter.sh`
  (flake8 syntax-subset only: `E9,F63,F7,F82`), or `requirements/linting.txt`
  (contains only flake8). 37 outstanding violations (35 auto-fixable: mostly
  I001 import sorting; plus F401 unused `_Flag` import at `config.py:100`,
  E713 at `argparse_ext.py:698`). AGENTS.md says "use ruff" — make CI agree:
  add ruff to linting.txt, run_linter.sh, and the CI lint job.
- **`uv run pytest` (the AGENTS.md command) fails out of the box** — zero
  runtime deps and no dev dependency group means pytest is absent until
  `uv run --extra tests pytest`. Add a `[dependency-groups] dev` group (uv
  syncs it by default) or fix AGENTS.md.
- **`tests/conftest.py` sys.path shim defeats the installed-artifact CI
  jobs** — the sdist/wheel test jobs deliberately run pytest from a sandbox so
  tests exercise the installed package, but the conftest prepends the repo
  root to `sys.path`, so `import kwconf` resolves to the checkout. Same
  pattern in .gitlab-ci.yml. Guard the shim (e.g. env var) or drop it.
- **uv.lock churns on every `uv` invocation** — pyproject's bare-date
  `[tool.uv] exclude-newer = "2026-06-18"` normalizes differently than the
  committed lock's `2026-06-19T04:00:00Z`. Pin a full timestamp in pyproject.
  (This audit reproduced the churn and reverted it.)
- **sdist gaps** — ships all 36 `tests/test_*.py` but *not*
  `tests/conftest.py`, and omits `CHANGELOG.md`. Downstream test runs from the
  sdist won't match the repo. No MANIFEST.in exists; add one or prune tests
  from the sdist deliberately.
- **Permanently skipped test** — `tests/test_modal.py:9`
  (`pytest.skip('does not work yet')`, `test_modal_fuzzy_hyphens`). CHANGELOG
  0.10.1 claims the fuzzy-hyphen fix landed — either the skip is stale and the
  test should be reactivated, or the fix is untested by it. (Also relevant to
  the `allow_abbrev` interaction in §2.)
- **pytest 10 deprecation** — `tests/test_data_versus_default.py` passes a
  generator to `parametrize` (`PytestRemovedIn10Warning`).
- **pyproject nits** — `[build-system]` lists setuptools twice (`>=41.0.1`
  and `>=77`); `[tool.xcookie] version = "0.10.0"` is stale vs 0.10.1
  (regenerating CI would embed the wrong version); `[tool.codespell] skip`
  references `./scriptconfig.egg-info` (port leftover);
  `package-data."*" = ["requirements/*.txt"]` is inert (requirements/ is not
  in a package); requirement files carry markers back to Python 2.7/3.8
  despite `requires-python >= 3.10`; coverage excludes still reference
  `six.PY2`.
- **.gitignore gaps** — `.venv/`, `.mypy_cache/`, `.ruff_cache/` aren't
  explicitly listed (currently ignored only via global/default handling).
  Workdir clutter (six `kwconf-source-*.tar.gz`, stale 0.9.2 `dist/`,
  `htmlcov/`) is untracked and ignored — fine, but worth an occasional sweep.

## 7. Docs

- `docs/source/conf.py:135` — the 3.14 crash (§1.15).
- `docs/source/index.rst` — `:gitlab_url:` points at
  `gitlab.kitware.com/computer-vision/kwconf` while README badges point at
  `gitlab.kitware.com/Erotemic/kwconf`; one is wrong. Also a literal
  `:github_url: None`.
- `.readthedocs.yml` — duplicate `- method: pip / path: .` install entry.
- CHANGELOG 0.10.0 release date reads "2026-06-18 (ish)".
- Modal docstring examples use the `@register` decorator pattern that
  currently returns `None` (§1.4) — fix the bug, then the examples become
  correct as written.

---

## 8. Current sequencing (updated 2026-07-10)

The original sequencing was appropriate for the first remediation pass, but it
is now historical. The remaining work should be ordered first by whether it can
silently reinterpret or discard configuration, and second by whether the
relevant fact is static or invocation-dependent.

### Status vocabulary

Use these labels consistently so a CI-only check is not mistaken for universal
runtime protection:

- **Fixed automatically** — every user receives the corrected behavior without
  opting into an additional check.
- **Opt-in safeguard available** — a project is protected when it runs the
  documented validation gate; normal execution intentionally does not pay for
  the check.
- **Open runtime defect** — invalid behavior depends on constructor arguments,
  input data, environment, parser reuse, or assignment and therefore must be
  rejected in the normal execution path.
- **Decision required** — multiple contracts are defensible, but the current
  behavior is unsafe, misleading, or undocumented.
- **Deferred architectural risk** — important maintenance work that should not
  displace smaller concrete correctness fixes.

### Phase A — establish the opt-in validation architecture

`Config.validate()` currently provides one useful static check: alias namespace
ambiguity. Treat that implementation as the seed of a validation subsystem,
not as a collection point for arbitrary runtime checks.

1. **Lock the validation contract.** Validation must inspect static schema
   declarations only. It must not construct Config instances, build argparse
   parsers, call `default_factory`, read argv/environment/filesystem state,
   mutate templates, or run implicitly during class construction, instance
   construction, or CLI startup. Repeated calls must be idempotent.
2. **Introduce structured, aggregate diagnostics.** Prefer a dedicated
   `SchemaValidationError` carrying structured issues and report all discovered
   schema problems in one CI run instead of failing at the first collision.
3. **Make Config validation recursive.** A root `Config.validate()` should
   validate all reachable SubConfig classes and variants with a local visited
   set. Static checks should include alias/fuzzy-name collisions, annotation-
   only declarations once their contract is chosen, duplicate selector or
   variant names/aliases, unsupported variant objects, and other immutable
   schema-graph invariants.
4. **Add `ModalCLI.validate()`.** One root call should validate inherited and
   nested command trees, duplicate command names/aliases, unsupported
   registrations, static registration conflicts, and each command Config.
   This complements rather than replaces the runtime modal fixes in Phase B.
5. **Document the CI recipe.** Show a focused project test such as
   `RootConfig.validate()` or `RootCLI.validate()`, preferably requiring only
   one root call for a complete public CLI graph.
6. **Test the performance and purity contract.** Keep explicit regressions that
   class definition, Config construction, and `cli(argv=False)` do not invoke
   validation. Also prove validation does not materialize factories or
   SubConfigs, build parsers, mutate `__default__`, or change results across
   repeated calls.

Current status: alias namespace checking is **opt-in safeguard available**.
The broader recursive/aggregate Config and Modal validation architecture is
**open**.

### Phase B — runtime correctness blockers

These remain reproducible in the current tree and can silently corrupt or lose
user intent. They depend on actual calls or input values and must not be moved
behind an optional CI validator.

Completed 2026-07-10: constructor calls now reject extra positional
arguments and duplicate semantic bindings with `TypeError`, without a recurring
schema scan or an extra traversal of the declared fields.

No outstanding Phase B item remains from the unknown-attribute finding.
Undeclared attributes are intentionally transient object state; the declaration
alone defines the mapping and persistence contract.

### Phase C — safety-sensitive decisions that need an explicit contract

These are partly API-design choices, but leaving the current behavior implicit
is risky enough that each should be resolved before a stable contract is
claimed.

1. **Environment ingestion default** (§2). `from_env(prefix='')` can absorb
   ambient variables such as `PATH`, `HOME`, or `USER` into same-named fields.
   Preferred contract: require a nonempty prefix, or require callers to pass
   `prefix=''` explicitly to opt into unnamespaced ingestion.
2. **Public `load()` semantics** (§2). It still means reset-to-defaults and
   then merge, despite the “updates” wording. Either document this as reload
   semantics and add a distinct incremental API, or make `load()` incremental.
3. **Annotation-only fields** (§2). `x: int` is silently ignored. Choose whether
   this declares a required field or is invalid schema. Once chosen, enforce or
   diagnose the static declaration through the opt-in validation path rather
   than adding a repeated CLI-startup scan.
4. **Alias / Mapping semantics** (§3). Decide whether aliases are lookup-only
   conveniences or actual mapping keys, then document and test the chosen
   invariant.
5. **`Config.copy()`** (§3). Decide whether it returns another Config or should
   be deprecated in favor of the already explicit `asdict()` / `to_dict()`
   APIs.
6. **Dynamic config fields / `__allow_newattr__`** (§3). Ordinary attached
   attributes are intentionally transient and need no warning. The separate
   experimental flag currently inserts unknown assignments into `_data`, so
   they serialize, but it does not provide declared parser/type/default/CLI
   metadata or guaranteed symmetric loading. Preferred direction if retained:
   formalize a clearly named dynamic-field mode with round-trip mapping/file
   semantics while keeping schema-derived CLI and static validation limited to
   declared fields; otherwise deprecate the flag.

### Phase D — correctness hardening

These are real defects or misleading APIs, but their blast radius is narrower
than Phase B.

- **Completed:** parser provenance is replaced on every parse, scoped to the
  selected parser, and removed from returned argparse namespaces.
- **Completed:** `expand_multipass_parser(parser=...)` extends and returns the
  supplied parser; SubConfig ingestion starts from a bare parser to avoid stale
  default-variant arguments.
- **Completed:** root and nested no-command diagnostics use the deepest selected
  parser, and `NoCommandError` separates integer exit status from message text.
- Split special-option collision handling into two layers: statically diagnose
  known `config` / `dump` / `dumps` namespace conflicts in CLI validation, and
  still fail safely with a kwconf-specific error if an unvalidated schema
  reaches parser construction.
- Distinguish generated negation flags from genuine user-declared `--no-*`
  options in help formatting.
- **Completed:** `subconfig.py.__all__` now exposes only the supported public
  declaration type, `SubConfig`; parser/loading helpers are explicitly internal.
- **Completed:** remaining bare `Exception` raises now use `KeyError`,
  `TypeError`, or `NotImplementedError` according to the failed contract.

### Phase E — tooling and release confidence

- Make the repository-wide lint claim true: fix the nine remaining
  `ruff check .` findings, run Ruff in GitHub CI, and decide whether the GitLab
  lint job should remain non-blocking.
- Make local lint/type commands self-contained. The default dev dependency
  group has Ruff but not flake8 or ty, so the documented successful invocations
  require `--extra linting` and `--with ty` respectively.
- Add prerelease/python-dev coverage and behavioral conformance tests around
  the remaining argparse introspection adapters before the next
  supported-Python expansion.

### Phase F — architectural refactors, only after the concrete defects

The systemic themes in §4 remain valid engineering risks, but they are not all
current release blockers. Do not let them displace the focused fixes above.

- **Completed:** `__default__` is schema-only, `_default` is the independent
  per-instance reset baseline, and `_data` contains current runtime values.
- **Completed:** flat/nested source ingestion, parser-shell construction, field
  argument generation, and argparse-port generation use canonical helpers.
- **Completed:** version-pinned argparse engine copies and private Action bases
  are gone; selector discovery uses argparse bootstrap parsers. Remaining
  private access is isolated to option/subparser/parser-structure introspection.
- **Partially completed:** selector token parsing is now argparse-owned, but the
  fixed-point SubConfig realization model remains inherently complex and should
  be simplified only when making another substantive feature change there.

---

## 9. Remediation status (revalidated 2026-07-10)

The source snapshot contains the focused remediation commits through
`0140ccf`. The historical findings and original line numbers above still
explain the bugs as first observed; this section is the current risk register.

### Verification snapshot

- `uv run pytest -q`: **445 passed, 3 skipped**. The three skips are
  xdoctest examples marked skipped, not disabled behavior regressions.
- `uv run --extra linting ./run_linter.sh`: passes for `kwconf/` and `tests/`.
- `uv run --with ty ty check ./kwconf`: passes.
- `uv run ruff check .`: **nine fixable findings remain** in `dev/`, `docs/`,
  `examples/`, and `run_tests.py`.
- GitLab runs flake8, Ruff, formatter checks, and ty, but the lint job is
  `allow_failure: true`. GitHub runs flake8 and ty but not Ruff.

### Fixed and regression-tested — high-severity §1

| Finding | Current status |
| --- | --- |
| §1.1 shared class mutable defaults via `.cli()` | Fixed: argv defaults are materialized per instance |
| §1.2 SubConfig + dict-leaf crashes `load()` | Fixed: flattening stops at ordinary mapping leaves |
| §1.3 provenance collapses on a leading option | Fixed: subcommand discovery skips option tokens |
| §1.4 `@register` decorator returns `None` | Fixed: decorator returns the registered class |
| §1.5 `--config` wipes prior `data=` values | Fixed: config-file values merge at the intended precedence layer |
| §1.6 `required=` rejects an explicitly supplied default | Fixed: enforcement uses provenance rather than value equality |
| §1.7 `position=` computed but unused | Fixed: parser construction honors position ordering |
| §1.8 annotation processing mutates shared templates | Fixed: templates are copied before annotation metadata is applied |
| §1.9 `Literal[...] \| str` restricts the CLI | Fixed: union choices account for unrestricted members |
| §1.10 Optional containers skip element coercion | Fixed: container element annotations are recovered through unions |
| §1.11 `exit_on_error=False` ignored | Fixed for the documented extended-parser behavior |
| §1.12 counter-action value corruption | Fixed: grouped-count normalization is restricted to short joined options |
| §1.13 opaque commands reuse stale `parserkw` | Fixed: each command builds its own parser kwargs |
| §1.14 `__json__` truncation | Fixed: nested JSON conversion updates the walker rather than returning early |
| §1.15 Sphinx Python 3.14 crash | Fixed: version extraction uses the supported AST value attribute |

### Fixed — additional concrete findings

The following original findings are closed with focused fixes and, where
behavioral, regression tests:

- Caller-dict mutation during `load()`, global PyYAML mutation during `dump()`,
  missing-file / non-mapping payload handling, empty-dict updates,
  `scan_config_path` token handling, and the internal `--config` precedence
  path.
- Successful `--dump` exit status, intercepted error context,
  `main(argv=False)`, modal version handling, fuzzy-hyphen behavior, and
  `@dataconf` preservation of hooks and inherited fields.
- Numeric-tower validation, annotation formatting, and typed
  `port_to_config()` output.
- Conflicting SubConfig selector spellings no longer replace a nested Config
  with raw selector text. Explicit `path.__class__` wins deterministically on
  the lean path; `cli/load(validate='warn'|'error')` optionally diagnoses
  ambiguous same-source declarations, and `__validate__ = 'error'` enables the
  strict check class-wide. Cross-source precedence remains valid by design.
- Modal command declarations now inherit across subclasses for attribute,
  `__subconfigs__`, and class-level `register()` forms. Subclass attribute
  overriding replaces or hides inherited attribute commands, subclass
  registration is isolated from the parent, and unrelated public helper
  classes are no longer treated as implicit commands.
- Modal command metadata is copied at the instance boundary before parser
  materialization. Class-level `__subconfigs__` entries remain declarative;
  live `subconfig`, `parserkw`, and dispatch state are confined to each modal
  instance, and caller-owned `sub_clis` dictionaries are not mutated.
- Constructor calls reject extra positional values and duplicate semantic
  bindings with `TypeError`. The fast path avoids a full field-name list and
  combines keyword alias normalization and conflict detection in one pass.
- A follow-up audit of the staged SubConfig code removed redundant selector
  application and arbitrary convergence guards. Selectors are now monotone and
  idempotent, nested source precedence is preserved as defaults < data <
  `--config` < argv, ordinary dict leaves containing `__class__` are not
  misclassified as selectors, and reused nested configs clear child argv
  provenance.
- The same audit repaired the dynamic-import tri-state: field-level `None`
  inherits the call-level policy, while True or False explicitly overrides it.
  Nested classes use resolvable `module.qualname.Class` identifiers for import
  and serialization.
- SubConfig serialization now resolves registry choices by exact class
  identity, preventing a selected subclass from being recorded as an earlier
  base-class choice and restored as the wrong implementation.
- The staged loader now keeps mapping/config-file structure intact until the
  canonical update boundary. This preserves conflict-validation provenance,
  prevents ``--config`` from shredding ordinary dict leaves, and lets parent
  selectors reveal nested SubConfigs before their mappings are applied.
- Parse-result provenance now resets at the shared boundary for both kwconf's
  extended parser and ordinary `argparse.ArgumentParser` instances using
  kwconf actions.
- Public export of `register_parser` and correction of the mkinit submodule
  specification.
- The dead-code removals listed in the prior remediation pass.
- `uv run pytest`, lock timestamp stability, installed-artifact test isolation,
  sdist inclusion of `conftest.py` / `CHANGELOG.md`, and the pytest-10
  parametrization warning.

### Opt-in safeguards and validation architecture

- **Available now:** `Config.validate()` checks canonical names, declared
  aliases, inherited fields, and generated fuzzy-hyphen spellings. Normal class
  construction and CLI invocation do not run the scan.
- **Available now:** `Config.cli(..., validate=...)` and `load(validate=...)`
  provide an explicit runtime policy beyond annotation checks. The default
  `None` preserves class/field value validation without a structural source
  scan; explicit `'warn'` / `'error'` diagnoses conflicting SubConfig selector
  spellings; and `False` selects the lean opt-out. `__validate__ = 'error'`
  enables strict structural checks class-wide. The baseline loader remains safe
  without the scan through deterministic explicit-selector precedence.
- **Status:** alias collision protection is an **opt-in safeguard available**,
  not a fixed-automatically invariant. Projects that do not run validation can
  still define an ambiguous schema.
- **Open:** formalize the side-effect-free validation contract, aggregate
  diagnostics, recurse through SubConfig graphs, add `ModalCLI.validate()`,
  document a one-root-call CI recipe, and test non-materialization,
  non-mutation, idempotence, and zero implicit invocation.

### Open — correctness blockers

No remaining item is currently classified as a confirmed release-blocking
runtime correctness defect. Unknown attached attributes are resolved by
contract: declared fields are the persistence boundary, while undeclared
attributes are ordinary transient Python state and intentionally do not round
trip. `__allow_newattr__` remains a separate experimental dynamic-field design
question. Alias collisions remain an opt-in `Config.validate()` safeguard
rather than a recurring production-time check.

### Open — narrower correctness and API defects

- Parser provenance is replaced on every parse for extended and plain argparse
  parsers, including selected child parsers.
- `expand_multipass_parser` preserves and extends the supplied parser.
- Root/nested no-command usage and `NoCommandError` programmatic semantics are
  fixed.
- Special-option collisions still surface as low-level argparse conflicts;
  static CLI validation and a safe runtime diagnostic are both still open.
- Genuine `--no-*` options can still receive generated-negation help treatment.
- `subconfig.py.__all__` now matches the intended public surface, and bare
  `Exception` raises have been replaced with intent-specific exception types.

### Decision required — not safely dismissible as “just design”

- **`from_env(prefix='')`** is a safety-sensitive default and remains
  unchanged. The mechanism is useful; the implicit unnamespaced default is the
  concern.
- **Public `load()` reset-vs-update semantics** remain unchanged and are still
  inconsistent with the current docstring wording.
- **Annotation-only fields** remain silently ignored. Their semantic contract
  must be chosen before adding an opt-in static validation rule.
- **Alias membership semantics** and **`Config.copy()` returning a dict** need
  explicit contracts, but are lower risk than the three decisions above.
- `_check_values` remains intentional opt-in developer infrastructure and is
  not considered accidental dead code.

### Open — tooling accuracy

The earlier remediation text said the tree was Ruff-clean and Ruff was
“enforced.” The accurate status is narrower:

- The configured `kwconf/` + `tests/` Ruff and formatting gate is clean.
- The repository as a whole is not Ruff-clean yet.
- Ruff runs in the non-blocking GitLab lint job, but not in GitHub CI.
- The default dev group does not actually mirror all lint/type dependencies:
  flake8 and ty require separate installation paths.

### Deferred architectural risks

The first three systemic themes in §4 are now substantially resolved: state
ownership is explicit, loading/parser construction have canonical paths, and
kwconf no longer vendors argparse's private parse engine. The fixed-point
SubConfig path has also been hardened: progress, not magic iteration counts,
drives convergence; selector application is idempotent; and source precedence
is tested directly. Remaining architectural risk is limited to the inherent
complexity of dynamic schema realization and a few isolated argparse
introspection adapters. Those should remain covered by behavioral tests rather
than motivating another broad rewrite by default.
