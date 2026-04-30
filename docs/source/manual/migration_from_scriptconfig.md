# Migrating from scriptconfig to kwconf

`kwconf` started as a port of `scriptconfig` and keeps most of the high-value
features intact -- modal CLIs, subconfig dispatch, argparse roundtripping,
file load/dump. The public API is largely the same. There are a small number
of deliberate breaks that make the new library cleaner. This page lists them
and shows what to change.

## TL;DR

| What | Before (`scriptconfig`) | After (`kwconf`) |
|---|---|---|
| Import name | `import scriptconfig as scfg` | `import kwconf as kw` |
| Primary base class | `scfg.DataConfig` | `kw.DataConfig` |
| Coerce method on Value | `Value.cast(v)` | `Value.coerce(v)` |
| Comma-separated CLI strings | auto-split into a list | stay a literal string |
| `type='smartcast'` aliases | three string variants | removed -- pass a callable |
| `kwconf.Path` / `kwconf.PathList` | available | removed -- use `Value(type=str)` and explicit globbing |
| `kwconf.Config` class | base class for DataConfig | removed -- only `DataConfig` is exposed |
| `Config(data=, default=, cmdline=)` ctor | available | removed -- use `DataConfig.cli(...)` or `MyConfig(**kwargs).load(...)` |
| `default` class attribute | accepted (deprecation warned) | accepted (deprecation warned) |
| `normalize` method | accepted (deprecation warned) | accepted (deprecation warned) |
| `cmdline=` kwarg style | dict form accepted | accepted (deprecated) |

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
* ``MyConfig().load(data=..., cmdline=...)`` after construction;
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

## Lifecycle helpers (still supported, still warned)

These have been deprecated since scriptconfig but still work:

* `default` class attribute -> use `__default__`.
* `normalize` method -> use `__post_init__`.
* `cmdline=` parameter as a dict -> pass `strict`, `argv`, `autocomplete`,
  `special_options` directly to `cli()` / `load()`.

Each of these emits a deprecation warning under `kwconf` exactly as it did
in late `scriptconfig`. Migrate when convenient.

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
8. Run your test suite and review any deprecation warnings.
