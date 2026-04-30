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
| Primary base class                                    | `scfg.DataConfig`             | `kw.DataConfig`                                                        |
| Coerce method on Value                                | `Value.cast(v)`               | `Value.coerce(v)`                                                      |
| Comma-separated CLI strings                           | auto-split into a list        | stay a literal string                                                  |
| `type='smartcast'` aliases                            | three string variants         | removed -- pass a callable                                             |
| `kwconf.Path` / `kwconf.PathList`                     | available                     | removed -- use `Value(type=str)` and explicit globbing                 |
| `kwconf.Config` class                                 | base class for DataConfig     | removed -- only `DataConfig` is exposed                                |
| `Config(data=, default=, cmdline=)` ctor              | available                     | removed -- use `DataConfig.cli(...)` or `MyConfig(**kwargs).load(...)` |
| `default` class attribute                             | accepted (deprecation warned) | removed -- use `__default__`                                           |
| `normalize` method                                    | accepted (deprecation warned) | removed -- use `__post_init__`                                         |
| `description` / `epilog` / `prog` class attributes    | accepted (deprecation warned) | removed -- use `__description__` / `__epilog__` / `__prog__`           |
| `cmdline=` kwarg on `load()` / `cli()`                | available                     | removed -- use `argv=`                                                 |
| `--config` / `--dump` / `--dumps` special CLI options | on by default                 | off by default (opt in via `__special_options__ = True` or per-call)   |

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

## `Config` is gone; only `DataConfig` is exposed

`scriptconfig` exposed two base classes (`Config` and `DataConfig`) with
overlapping responsibilities. `kwconf` consolidates them into a single
public class: `DataConfig`. The implementation, the metaclass, and all the
``cli`` / ``load`` / ``argparse`` / ``dump`` machinery now live on this one
class.

```python
# scriptconfig
class MyConfig(scfg.Config):
    x = 1

cfg = MyConfig(data={'x': 2}, cmdline=False)

# kwconf
class MyConfig(kw.DataConfig):
    x = 1

cfg = MyConfig(x=2)                         # dataclass-style kwargs
# or
cfg = MyConfig().load({'x': 2})             # explicit load
# or
cfg = MyConfig.cli(data={'x': 2}, argv=False)
```

The ``Config(data=..., default=..., cmdline=...)`` constructor signature is
gone with the class. To populate a config from a file/dict/argv, use one of:

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

## `type='smartcast'` aliases are removed

scriptconfig accepted three magic strings for the `type=` argument of
`Value`: `'smartcast'`, `'smartcast:v1'`, and `'smartcast:legacy'`. All
three are gone. Passing a string for `type` now raises a clear `TypeError`.

```python
# before
kw.Value([], type='smartcast:legacy')

# after -- pass a callable
kw.Value(0, type=int)                # explicit int parsing
kw.Value(None)                       # default scalar inference
# (for CLI list input use ``nargs='+'`` instead of ``type=list``;
#  see "Comma-splitting is gone" above.)
```

The default un-typed inference (int, float, complex, bool, None) still
runs for un-annotated string CLI input -- only the auto-list behavior is
removed.

If you want richer string parsing (lists, dicts, scalars), use the
named YAML type:

```python
class C(kw.DataConfig):
    items = kw.Value(None, type='yaml')

C.cli(argv=['--items=[1,2,3]'])['items']    # [1, 2, 3]
C.cli(argv=['--items={a: 1}'])['items']     # {'a': 1}
C(items='auto')['items']                    # 'auto'
C(items='1')['items']                       # 1  (yaml parses scalars)
```

``type='yaml'`` runs ``yaml.safe_load`` on string inputs. The same
parsing happens whether the value comes from argv, a file, or kwargs --
matching how ``type=int`` already coerces strings everywhere. Pass an
already-parsed Python value to bypass it.

## `kwconf.Path` and `kwconf.PathList` are removed

`Path` was a thin wrapper around `ub.expandpath`. `PathList` was a comma- or
glob-based list. Both are removed; their value-add was small enough that
keeping them in the public surface is no longer worthwhile.

```python
# before
class C(scfg.DataConfig):
    out = scfg.Path(help='output dir')
    inputs = scfg.PathList(help='input glob')

# after -- expand and glob explicitly in __post_init__
class C(kw.Config):
    out: str = kw.Value(None, help='output dir')
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
need a reusable subclass, it is straightforward to roll your own:

```python
class Path(kw.Value):
    def __init__(self, value=None, **kw):
        super().__init__(value, type=str, **kw)
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
class MyConfig(scfg.DataConfig):
    config = None  # silently shadowed by the special --config

# kwconf: opt in either per-call:
cfg = MyConfig.cli(argv=[...], special_options=True)
# or at the class level:
class MyConfig(kw.DataConfig):
    __special_options__ = True
    other = 'foo'
```

If your existing code expected ``--config <path>`` to work, add
``special_options=True`` (or set ``__special_options__ = True`` on the
class).

## `Value.cast` -> `Value.coerce`

If you subclassed `Value` and overrode `cast`, rename the override to
`coerce`. The new name is honest about what the function does (it goes
through `smartcast`, which both type-infers and is permissive about input
shapes -- it is not a clean type-cast).

```python
# before
class MyValue(scfg.Value):
    def cast(self, value):
        ...

# after
class MyValue(kw.Value):
    def coerce(self, value):
        ...
```

Direct callers (`template.cast(value)`) similarly become `template.coerce(value)`.

## Optional annotation-based validation

Set ``__validate__ = 'error'`` (or ``'warn'``) on a class to have kwconf
check assignments against the field's type annotation after coercion.
Off by default, since most callers don't want runtime type policing.

```python
import typing

class C(kw.DataConfig):
    __validate__ = 'error'
    mode: typing.Literal['fast', 'slow'] = 'fast'
    count: int | None = None

C(mode='wrong')  # TypeError
C(count=[1, 2])  # TypeError
```

Per-field opt-out is available with ``Value(..., validate=False)``.
Annotations the validator can't reason about (custom generics, callables,
etc.) are silently skipped -- the goal is to under-validate rather than
misvalidate.

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
2. Replace any `scfg.Config` (or `kw.Config`) base class with `kw.DataConfig`.
3. Replace any `MyConfig(data=..., default=..., cmdline=...)` construction
   with one of the patterns in the section above (kwargs / `.load(...)` /
   `.cli(...)`).
4. Find any `--key=a,b,c` CLI invocations and either:
   * declare the field with `nargs='+'` and switch to space-separated input, or
   * keep the comma form and split in `__post_init__`.
5. Replace any `type='smartcast*'` strings with concrete callables.
6. Replace `Path` / `PathList` usage with `Value(type=str)` plus explicit
   path handling in `__post_init__`.
7. If you subclassed `Value`, rename `cast` -> `coerce`.
8. If your CLI relied on the built-in `--config`, `--dump`, or `--dumps`
   special options, opt in with `special_options=True` (per-call) or
   `__special_options__ = True` on the class.
9. Run your test suite and review any deprecation warnings.
