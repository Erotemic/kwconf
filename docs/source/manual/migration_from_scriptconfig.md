# Migrating from scriptconfig to kwconf

`kwconf` started as a port of `scriptconfig` and keeps most of the high-value
features intact -- modal CLIs, subconfig dispatch, argparse roundtripping,
file load/dump. The public API is largely the same. There are a small number
of deliberate breaks that make the new library cleaner. This page lists them
and shows what to change.

## TL;DR

| What                                                  | Before (`scriptconfig`)       | After (`kwconf`)                                                       |
| ----------------------------------------------------- | ----------------------------- | ---------------------------------------------------------------------- |
| Import name                                           | `import scriptconfig as scfg` | `import kwconf as kw`                                                  |
| Primary base class                                    | `scfg.Config` / `scfg.DataConfig` | `kw.Config`                                           |
| Coerce method on Value                                | `Value.cast(v)`               | `Value.coerce(v)`                                                      |
| Parser keyword                                        | `type=`                       | `parser=` (`type=` kept as a deprecated alias)                        |
| Comma-separated CLI strings                           | auto-split into a list        | stay a literal string (use `parser='csv'` / `nargs`)                  |
| `type='smartcast'` aliases                            | three string variants         | removed -- pass a callable                                             |
| `kwconf.Path` / `kwconf.PathList`                     | available                     | removed -- use `Value(parser=str)` and explicit globbing              |
| `kwconf.DataConfig` class                             | alternate kwconf base name | removed -- only `Config` is exposed                    |
| `Config(data=, default=, cmdline=)` ctor              | available                  | removed -- use `Config.cli(...)` or `MyConfig(**kwargs).load(...)` |
| `default` class attribute                             | accepted (deprecation warned) | removed -- use `__default__`                                           |
| `normalize` method                                    | accepted (deprecation warned) | removed -- use `__post_init__`                                         |
| `description` / `epilog` / `prog` class attributes    | accepted (deprecation warned) | removed -- use `__description__` / `__epilog__` / `__prog__`           |
| `cmdline=` kwarg on `load()` / `cli()`                | available                     | removed -- use `argv=`                                                 |
| `--config` / `--dump` / `--dumps` special CLI options | on by default                 | off by default (opt in via `__special_options__ = True` or per-call)   |
| Modal subcommand dispatch                             | forwards resolved defaults as kwargs | forwards only explicitly supplied child args as kwargs        |

The rest of this document walks through each item.

## Replace the import

```python
# before
import scriptconfig as scfg

# after
import kwconf as kw
```

The two libraries are not pin-compatible at runtime: there is no
`scriptconfig` shim. Update your imports directly.

## `Config` is the only kwconf base class

`scriptconfig` exposed both `Config` and `DataConfig` with
overlapping responsibilities. `kwconf` consolidates them into a single
public class: `Config`. The implementation, the metaclass, and all the
``cli`` / ``load`` / ``argparse`` / ``dump`` machinery now live on this one
class.

```python
# scriptconfig
class MyConfig(scfg.Config):
    x = 1

cfg = MyConfig(data={'x': 2}, cmdline=False)

# kwconf
class MyConfig(kw.Config):
    x = 1

cfg = MyConfig(x=2)                         # dataclass-style kwargs
# or
cfg = MyConfig().load({'x': 2})             # explicit load
# or
cfg = MyConfig.cli(data={'x': 2}, argv=False)
```

The old ``Config(data=..., default=..., cmdline=...)`` constructor signature is
gone. The kwconf ``Config`` constructor is dataclass-style. To populate a config from a file/dict/argv, use one of:

* ``MyConfig(**kwargs)`` for direct keyword construction;
* ``MyConfig().load(data=..., argv=...)`` after construction;
* ``MyConfig.cli(data=..., argv=...)`` for the CLI-aware path.

## Comma-splitting is gone

This is the most user-visible break. Under scriptconfig, a CLI argument like
`--items=a,b,c` was silently split into a list. kwconf does not do this.

```python
class C(kw.Config):
    items: str = ''

cfg = C.cli(argv=['--items=a,b,c'])
assert cfg.items == 'a,b,c'   # the literal string, not ['a', 'b', 'c']
```

If you need a list on the CLI, declare it explicitly with ``nargs``:

```python
class C(kw.Config):
    tags: list = kw.Value(default_factory=list, nargs='+')

cfg = C.cli(argv=['--tags', 'a', 'b', 'c'])
assert cfg.tags == ['a', 'b', 'c']
```

If you specifically want a comma-separated CLI form, do the split in
``__post_init__``:

```python
class C(kw.Config):
    tags: str = ''

    def __post_init__(self):
        if isinstance(self.tags, str):
            self.tags = [t for t in self.tags.split(',') if t]

cfg = C.cli(argv=['--tags=a,b,c'])
assert cfg.tags == ['a', 'b', 'c']
```

The old auto-split behavior cannot be re-enabled with a flag or string alias
(see below).

## `type=` is now `parser=`

The `type=` keyword was overloaded (argparse type + smartcast hint +
container shape). It is renamed to `parser=`, a callable `str -> value` or a
string key into the parser registry (`'auto'`, `'csv'`, `'yaml'`). `type=` is
kept as a **deprecated alias** for a long while (the two are mutually
exclusive), so existing code keeps working -- but prefer `parser=` in new code.

```python
# before
kw.Value(0, type=int)
kw.Value(None, type='yaml')

# after
kw.Value(0, parser=int)
kw.Value(None, parser='yaml')
```

Parsers may or may not be **annotation-aware**. `'auto'` (the default) and `'csv'`
steer their output by the field annotation; `'yaml'` produces its own typed
structure. Register a custom parser with
`kwconf.coerce.register_parser(name, fn, annotation_aware=...)`. See the
coercion manual for the full model.

## `type='smartcast'` aliases are removed

scriptconfig accepted three magic strings for the `type=` argument of
`Value`: `'smartcast'`, `'smartcast:v1'`, and `'smartcast:legacy'`. All
three are gone. Passing an unknown string for `parser`/`type` raises a clear
`TypeError` listing the known names.

```python
# before
kw.Value([], type='smartcast:legacy')

# after -- pass a callable or a named parser
kw.Value(0, parser=int)              # explicit int parsing
kw.Value(None)                       # default scalar inference ('auto')
```

The default un-typed inference (int, float, complex, bool, None) still
runs for un-annotated string CLI input -- only the auto-list behavior is
removed.

For CLI list input, declare `nargs='+'` (space-separated) or `parser='csv'`
(comma-separated):

```python
class C(kw.Config):
    nums: list[int] = kw.Value(default_factory=list, parser='csv')

C.cli(argv=['--nums=1,2,3'])['nums']        # [1, 2, 3]
```

If you want richer string parsing (lists, dicts, scalars), use the
named YAML parser:

```python
class C(kw.Config):
    items = kw.Value(None, parser='yaml')

C.cli(argv=['--items=[1,2,3]'])['items']    # [1, 2, 3]
C.cli(argv=['--items={a: 1}'])['items']     # {'a': 1}
C(items='auto')['items']                    # 'auto'
C.cli(argv=['--items=1'])['items']          # 1  (yaml parses scalars)
```

`parser='yaml'` runs `yaml.safe_load` on string inputs at the text boundary
(argv/env/file). The plain constructor still trusts its input: `C(items='1')`
keeps the string `'1'` (the Python boundary does not coerce). Use
`C.coerce(items='1')` to opt into text-boundary parsing from Python.

## `kwconf.Path` and `kwconf.PathList` are removed

`Path` was a thin wrapper around `ub.expandpath`. `PathList` was a comma- or
glob-based list. Both are removed; their value-add was small enough that
keeping them in the public surface is no longer worthwhile.

```python
# before
class C(scfg.Config):
    out = scfg.Path(help='output dir')
    inputs = scfg.PathList(help='input glob')

# after -- expand and glob explicitly in __post_init__
class C(kw.Config):
    out: str = kw.Value(None, parser=str, help='output dir')
    inputs: list = kw.Value(default_factory=list, nargs='+', help='input files')

    def __post_init__(self):
        import os, glob
        if self.out is not None:
            self.out = os.path.expanduser(self.out)
        # expand globs
        expanded = []
        for pat in self.inputs:
            expanded.extend(sorted(glob.glob(os.path.expanduser(pat))))
        self.inputs = expanded
```

Doing this in `__post_init__` keeps the path-handling logic visible
in the user's class instead of buried in a Value subclass. If you do
need a reusable subclass, roll your own -- but note that the public
`kwconf.Value` is now a typed *factory function* (it is annotated to return the
field's value type, which is what gives you static default-vs-annotation
checking). Subclass the underlying class, exposed as `kwconf.ValueClass`
(`kwconf.FlagClass` for flags):

```python
import kwconf

class Path(kwconf.ValueClass):
    def __init__(self, value=None, **kw):
        super().__init__(value, parser=str, **kw)
    def coerce(self, value):
        if isinstance(value, str):
            import os
            value = os.path.expanduser(value)
        return value
```

## `--config` / `--dump` / `--dumps` are off by default

scriptconfig added these "special options" to every CLI by default. kwconf
makes them opt-in because they reserve names that often conflict with
user-defined fields (a common scriptconfig footgun was a class with a
``config`` field colliding with the special ``--config``).

```python
# scriptconfig: --config / --dump / --dumps are always present
class MyConfig(scfg.Config):
    config = None  # silently shadowed by the special --config

# kwconf: opt in either per-call:
cfg = MyConfig.cli(argv=[...], special_options=True)
# or at the class level:
class MyConfig(kw.Config):
    __special_options__ = True
    other = 'foo'
```

If your existing code expected ``--config <path>`` to work, add
``special_options=True`` (or set ``__special_options__ = True`` on the
class).

## Modal dispatch forwards only explicit child arguments

scriptconfig modal dispatch parsed the selected subcommand and then called the
child ``main`` with a kwargs dictionary containing every resolved child value,
including schema defaults. That made omitted values indistinguishable from
values the user explicitly supplied.

kwconf keeps those concepts separate. Modal dispatch still parses enough to
select and validate the child command, but when it calls the child ``main`` it
forwards only arguments that were explicitly present in argv.

```python
class ArchiveSource(kw.Config):
    depth = kw.Value('full')
    verbose = kw.Flag(False)

    @classmethod
    def main(cls, argv=None, **kwargs):
        # In kwconf modal invocation with: archive_source --verbose
        assert kwargs == {'verbose': True}
```

This allows the child command to apply later default sources naturally:

```python
repo_defaults = {'depth': '0'}
config = ArchiveSource.cli(argv=False, data=kwargs, default=repo_defaults)
assert config.depth == '0'
```

If the user explicitly passes ``--depth=full``, modal dispatch forwards
``depth='full'`` and the explicit CLI value wins.

## `Value.cast` -> `Value.coerce`

If you subclassed `Value` and overrode `cast`, rename the override to
`coerce`. The new name is honest about what the function does: it parses a
string at the text boundary (via the `parser=`/`'auto'` path), which both
type-infers and is permissive about input shapes -- it is not a clean
type-cast. (The old scriptconfig `smartcast` module is retired.)

```python
# before
class MyValue(scfg.Value):
    def cast(self, value):
        ...

# after -- subclass the underlying class (the public name is now a function)
import kwconf

class MyValue(kwconf.ValueClass):
    def coerce(self, value):
        ...
```

Direct callers (`template.cast(value)`) similarly become `template.coerce(value)`.

## Annotation-based validation (defaults to `warn`)

kwconf checks user-supplied values against the field's type annotation after
coercion. This defaults to ``'warn'`` -- a mismatch is accepted (never raises)
but emits a ``UserWarning``. It is the single, parser-agnostic place mismatches
are reported. Set ``__validate__`` on the class (or ``validate=`` per field) to
``'error'``/``True`` to raise instead, or ``False`` to disable:

```python
import typing

class C(kw.Config):
    __validate__ = 'error'        # 'warn' (default) | 'error'/True | False
    mode: typing.Literal['fast', 'slow'] = 'fast'
    count: int | None = None

C(mode='wrong')  # TypeError
C(count=[1, 2])  # TypeError
```

Validation runs on user-supplied values but **not** on a field's own trusted
default, so a WYSIWYG ``kw.Value('512')`` on an ``int`` field never warns about
itself. Per-field opt-out is available with ``Value(..., validate=False)``.
Annotations the validator can't reason about (custom generics, callables, etc.)
are silently skipped -- the goal is to under-validate rather than misvalidate.

## Removed lifecycle / metadata helpers

The deprecated non-dunder forms are gone. Rename them on your classes:

* `default` class attribute -> `__default__`.
* `normalize` method -> `__post_init__`.
* `description` / `epilog` / `prog` class attributes ->
  `__description__` / `__epilog__` / `__prog__`.

Unlike late `scriptconfig`, there is no deprecation warning -- the old
names are simply not consulted.

## `cmdline=` is removed

The `cmdline=` parameter on `load()` and `cli()` has been removed entirely;
pass `argv=` instead. The accepted shapes are unchanged: `True` to parse
`sys.argv`, a list of strings, a single string (split with `shlex`), or
`False` to skip CLI parsing. The dict-form (which scriptconfig accepted as
a deprecated way of forwarding parser kwargs) is gone -- pass `strict`,
`autocomplete`, and `special_options` directly.

## Things that did NOT change

These work the same as in `scriptconfig`:

* Modal CLIs (`ModalCLI`, `ModalValue`, `register`, nested modal dispatch).
* SubConfig nodes (`kw.SubConfig`, dotted CLI overrides, selector arguments).
* argparse integration (`Config.argparse(parser=...)`,
  `Config.port_to_argparse()`, `Config.port_from_argparse()`,
  `Config.cls_from_argparse()`).
* File load / dump (`load`, `dump`, `dumps`, the `--config`, `--dump`,
  `--dumps` special options).
* Aliases, short aliases, `nargs`, `position`, `group`, `mutex_group`.
* `Flag`, `__special_options__`, `__fuzzy_hyphens__`, `__allow_newattr__`.

If you find a feature that you used in scriptconfig and that no longer
works the same in kwconf, that is most likely either a bug or one of the
items listed above. Please file an issue.

## Quick checklist

1. `import scriptconfig as scfg` -> `import kwconf as kw`.
2. Replace any `scfg.Config`, `scfg.DataConfig`, or `kw.DataConfig` base class with `kw.Config`.
3. Replace any `MyConfig(data=..., default=..., cmdline=...)` construction
   with one of the patterns in the section above (kwargs / `.load(...)` /
   `.cli(...)`).
4. Find any `--key=a,b,c` CLI invocations and either:
   * declare the field with `nargs='+'` and switch to space-separated input, or
   * keep the comma form and split in `__post_init__`.
5. Replace any `type='smartcast*'` strings with concrete callables. Rename
   `type=` to `parser=` in new code (`type=` still works as a deprecated alias).
6. Replace `Path` / `PathList` usage with `Value(parser=str)` plus explicit
   path handling in `__post_init__`.
7. If you subclassed `Value`, rename `cast` -> `coerce`.
8. If your CLI relied on the built-in `--config`, `--dump`, or `--dumps`
   special options, opt in with `special_options=True` (per-call) or
   `__special_options__ = True` on the class.
9. Run your test suite and review any deprecation warnings.
