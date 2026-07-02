# kwconf codebase audit — 2026-07-02

> **Remediation status (updated 2026-07-02).** Most findings below have been
> fixed on branch `dev/audit-fixes`, one focused commit per issue with tests.
> See [§9 Remediation status](#9-remediation-status) for the per-finding
> table and the short list of items deliberately **deferred** as design
> decisions for the maintainer. Suite after fixes: **376 passed, 2 skipped**;
> `ruff check`, `ruff format --check`, and `ty check ./kwconf` all clean.

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

**Snapshot.** Test suite: 332 collected, 328 passed, 4 skipped, ~1s. `ty check
./kwconf` green in CI. The architecture is sound and the design voice is
consistent; the problems below are concentrated in a handful of systemic
patterns (shared mutable templates, duplicated load paths, argparse-internal
pinning) rather than spread uniformly.

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
- **Alias collisions silently hijack real fields** **[verified]** —
  `config.py:1370-1392`: with `opt1 = Value(1, alias=['opt2']); opt2 =
  Value(2)`, `C(opt2=99)` sets `opt1=99` and leaves `opt2=2`
  (`_normalize_alias_dict` maps unconditionally while `__getitem__` prefers the
  real key — inconsistent). Two fields declaring the same alias last-writer-win.
  No duplicate-alias validation anywhere.
- **Extra positional constructor args silently dropped** **[verified]** —
  `config.py:560-561`: `zip` truncation means `C(10, 20, 30, 40)` on a 2-field
  config succeeds; `C(10, x=20)` silently prefers the keyword instead of raising
  "multiple values".
- **`@dataconf` on a plain class drops underscore attributes and inherited
  fields** **[verified]** — `dataconfig.py:113-136`: the copy loop skips
  everything starting with `_` (killing `__post_init__`, `__validate__`,
  `_helper`) except a small whitelist, and iterates `vars(cls)` only (no MRO
  walk), so fields from plain base classes vanish.
- **`MetaModalCLI` auto-registers every public class-valued attribute; subclassing
  drops inherited commands** **[verified]** — `modal.py:143-181`: a stashed
  helper class becomes a "command" (build fails with a confusing `ValueError`),
  and `class Sub(Base): pass` has zero commands because `__subconfigs__` is
  rebuilt from the class's own namespace only.
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
- **Unknown-attribute assignment silently lands in `__dict__`** —
  `config.py:1794-1797`: `cfg.typo = 5` appears to work but never serializes
  and `'typo' in cfg` is `False`; new-key rejection raises bare `Exception`
  (`config.py:1043-1046`) so the `except KeyError → AttributeError` translation
  never engages. Classic dual-namespace footgun.
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

## 8. Suggested sequencing

**Quick wins (small diffs, high value):**
`@register` return (§1.4), `__json__` walker assignment (§1.14), `--dump`
exit code, `exit_on_error` assignment order (§1.11), conf.py `node.value.value`
(§1.15), `str(ex)` in error interception, opaque-command `parserkw` ordering
(§1.13), export `register_parser`, fix the mkinit spec, ruff `--fix` +
enforce in CI, uv.lock timestamp pin, dev dependency group, delete the dead
code in §5.

**Correctness cluster around defaults/state (do together):**
§1.1, §1.8, and the template-ownership rule from theme 4.1 — these are one
refactor: never store class-template objects into instances, never mutate
templates after class creation. Then §1.6 (consult `_explicit_argv_keys` for
`required`) and §1.5 (make `--config` merge instead of reset) fall out of the
same precedence-merge code.

**Union/annotation cluster (do together):**
§1.9, §1.10, int-for-float, `format_annotation` — all in
`annotations.py`/`coerce.py`, all "unwrap unions properly, then decide".

**Subconfig load path:**
§1.2 plus the dict-leaf/config-node distinction, missing-file errors, empty
dict/None payload validation, and deduplicating the two load implementations
(theme 4.3). This is one coherent piece of work on `apply_dot_updates` /
`coerce_data_updates`.

**Modal/argparse hardening:**
§1.3 (skip option tokens in the subparser walk), §1.12 (counter guard),
parser-reuse state (§2), fuzzy-hyphen/allow_abbrev consistency, and a stdlib
conformance test harness for the pinned argparse internals (theme 4.4).

**Deliberate decisions needed (not bugs until decided):**
`load()` reset-vs-update semantics; `from_env('')` default; annotation-only
class fields (silently ignored today — error? required field?); `position=`
(implement or deprecate per `value.py:95`); alias/Mapping contract; whether
`copy()` should exist.

---

## 9. Remediation status

Fixed on branch `dev/audit-fixes` (one reviewable commit per issue, each with
a regression test). Line numbers in the sections above refer to the original
audit commit `03cff1f` and will have shifted.

### Fixed (high-severity §1)

| Finding | Commit summary |
| --- | --- |
| §1.1 shared class mutable defaults via `.cli()` | Use per-instance defaults in the argv-defaults merge |
| §1.2 SubConfig + dict-leaf crashes `load()` | Flatten subconfig updates only across SubConfig boundaries |
| §1.3 provenance collapses on leading option | Skip leading options when locating the subcommand for provenance |
| §1.4 `@register` decorator returns `None` | Fix ModalCLI.register decorator rebinding the class to None |
| §1.5 `--config` wipes `data=` values | Merge `--config` file values instead of reset-loading |
| §1.6 `required=` rejects explicit default | Enforce required= via provenance, not value equality |
| §1.7 `position=` computed but unused | Apply position= ordering when building the parser |
| §1.8 annotation processing mutates shared templates | Copy Value templates before applying annotation metadata |
| §1.9 `Literal[...] \| str` restricts CLI | Derive CLI choices correctly from union annotations |
| §1.10 `Optional` container skips element coercion | Coerce elements through Optional/Union container annotations |
| §1.11 `exit_on_error=False` ignored + leaked | Honor exit_on_error=False in the extended parsers |
| §1.12 counter-action value corruption | Restrict counter-flag grouping normalization to short options |
| §1.13 opaque-command stale `parserkw` | Build opaque modal commands with their own parser kwargs |
| §1.14 `__json__` truncation | Fix Config.__json__ truncating output at the first nested __json__ object |
| §1.15 Sphinx 3.14 crash | Fix sphinx-build crash on Python 3.14 |

### Fixed (medium §2, API §3, dead code §5, tooling §6/§7)

- `load()` mutates caller dict; `dump()` mutates global yaml; missing-file /
  non-mapping payload errors; empty-dict update dropped; `scan_config_path`
  greedy token; `--dump` exit code; intercepted error names the argument;
  `main(argv=False)` crash; `--version` versionless-submodal `None`;
  int-for-float numeric tower + `format_annotation` display; fuzzy-hyphen vs
  `allow_abbrev` consistency (+ reactivated `test_modal_fuzzy_hyphens`);
  `@dataconf` drops hooks / inherited fields; `port_to_config` invalid codegen.
- API: mkinit `__submodules__` spec fixed; `register_parser` exported.
- Dead code: `HANDLE_INHERITENCE`, `if 0:` block, redundant yaml if/else,
  `DEBUG_DATA_CONFIG`/`DEBUG_META_DATA_CONFIG`, commented `hybridmethod`,
  `__example__`.
- Tooling: ruff enforced (linter script, CI extra) + tree made ruff-clean;
  `[dependency-groups] dev` so `uv run pytest` works; `uv.lock` timestamp pin;
  `MANIFEST.in` ships `conftest.py`/`CHANGELOG.md`; conftest sys.path shim
  guarded; pytest-10 parametrize deprecation; pyproject nits (duplicate
  setuptools, stale xcookie version, codespell path).

### Deferred — maintainer design decisions (not fixed)

These are judgment calls, not defects; left for the maintainer:

- **`load()` reset-vs-update semantics** (§2 "reset-then-merge"). The internal
  `--config` merge is fixed (§1.5) via a private `_reset` flag, but the public
  `load()` still resets keys absent from the new source. Decide whether that is
  the intended contract and document it, or change it.
- **`from_env(prefix='')` default** (§2). Still reads arbitrary env vars into
  matching fields by default. Decide: require a prefix, or warn.
- **Annotation-only class fields silently ignored** (§2). `x: int` with no
  value still produces no field. Decide: error, or treat as required.
- **Alias / Mapping contract** (§2.20): `cfg[alias]` works while `alias in cfg`
  is False. Keep (with an ADR note) or reconcile.
- **`Config.copy()` returning a plain dict** (§3). Rename / fix / document.
- **`_check_values`** (`value.py`) left in place: it is intentional opt-in
  developer infrastructure, not accidental dead code.

### Larger refactors not attempted (out of scope for point-fixes)

The systemic themes in §4 remain open: the `__default__`/`_default`/`_data`
state-model refactor (theme 4.2), full de-duplication of the two load/normalize
paths (theme 4.3, only partially reduced here via the shared
`looks_like_config_path` helper), the two ~120-line `add_argument` builders in
`value.py`, and a stdlib-argparse conformance harness for the pinned internals
(theme 4.4). Each is a standalone project.
