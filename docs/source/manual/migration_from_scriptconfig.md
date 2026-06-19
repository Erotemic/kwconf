# Migrating from scriptconfig to kwconf

`kwconf` is the successor to `scriptconfig`. It keeps the small-script workflow,
modal CLIs, nested configs, argparse integration, and file load/dump. The main
changes make parsing explicit and reduce old compatibility paths.

This page is also written for LLM-assisted ports. Many models know
`scriptconfig` better than `kwconf`, so use this as the review checklist.

## Quick map

| Task | scriptconfig | kwconf |
| ---- | ------------ | ------ |
| Import | `import scriptconfig as scfg` | `import kwconf` |
| Base class | `scfg.Config` / `scfg.DataConfig` | `kwconf.Config` |
| Field metadata | `scfg.Value(...)` | `kwconf.Value(...)` |
| Flag metadata | `scfg.Value(..., isflag=True)` | `kwconf.Flag(...)` |
| Parser keyword | `type=` | `parser=` (`type=` is a deprecated alias) |
| CLI argument source | `cmdline=` or `argv=` | `argv=` |
| CLI config file options | usually present | opt in with `special_options=True` |
| Comma list strings | often auto-split | use `parser='csv'`, `nargs`, or `parser='yaml'` |
| Normalize hook | `normalize` | `__post_init__` |
| Dynamic defaults | `default` | `__default__` |
| Value subclass hook | `cast` | `coerce` |

## Minimal port

```python
# scriptconfig
import scriptconfig as scfg


class MyConfig(scfg.DataConfig):
    option1 = scfg.Value(1, help='first option')
    option2 = 2


config = MyConfig.cli(argv=['--option1=3'])
```

```python
# kwconf
import kwconf


class MyConfig(kwconf.Config):
    option1 = kwconf.Value(1, help='first option')
    option2 = 2


config = MyConfig.cli(argv=['--option1=3'])
```

The class can still be used as an object, mapping, or argparse-like namespace:

```python
assert config.option1 == 3
assert config['option1'] == 3
```

## Untyped path first

`kwconf` does not require type annotations. This makes direct ports small.

```python
import kwconf


class FileHashConfig(kwconf.Config):
    fpath = kwconf.Value(None, position=1, help='file to hash')
    hasher = kwconf.Value('sha1', choices=['sha1', 'sha512'])


cfg = FileHashConfig.cli(argv=['README.rst', '--hasher=sha512'])
```

Add annotations later for static checks, editor help, parser selection, and
validation:

```python
class FileHashConfig(kwconf.Config):
    fpath: str | None = kwconf.Value(None, position=1, help='file to hash')
    hasher: str = kwconf.Value('sha1', choices=['sha1', 'sha512'])
```

## Parser model

`kwconf` uses `parser=` for string parsing. A parser reads one CLI/env string
for one field. See [Coercion and CLI Contract](coercion_and_cli.rst) for the
full contract.

### `auto`

`auto` is the default. It reads scalar strings such as `3`, `3.5`, `true`, and
`null`. Comma strings stay strings.

```python
class C(kwconf.Config):
    value = kwconf.Value(None)  # parser='auto'


assert C.cli(argv=['--value=3']).value == 3
assert C.cli(argv=['--value=a,b']).value == 'a,b'
```

### `csv`

Use `csv` for comma-separated lists.

```python
class C(kwconf.Config):
    nums = kwconf.Value(default_factory=list, parser='csv')


assert C.cli(argv=['--nums=1,2,3']).nums == [1, 2, 3]
```

With annotations, `csv` parses each item as the element type:

```python
class C(kwconf.Config):
    tags: list[str] = kwconf.Value(default_factory=list, parser='csv')
    nums: list[int] = kwconf.Value(default_factory=list, parser='csv')
```

### `yaml`

Use `yaml` for YAML-shaped strings: lists, dicts, scalars, and nested values.

```python
class C(kwconf.Config):
    payload = kwconf.Value(None, parser='yaml')


assert C.cli(argv=['--payload={enabled: true}']).payload == {'enabled': True}
```

## Scriptconfig footguns and kwconf fixes

### Smartcast comma lists

Scriptconfig's smartcast could turn `--items=a,b,c` into a list. That was handy
for short demos and risky for real strings.

`kwconf` keeps the string unless the field asks for structure:

```python
class C(kwconf.Config):
    items = ''
    csv_items = kwconf.Value(default_factory=list, parser='csv')
    argv_items = kwconf.Value(default_factory=list, nargs='+')


assert C.cli(argv=['--items=a,b,c']).items == 'a,b,c'
assert C.cli(argv=['--csv-items=a,b,c']).csv_items == ['a', 'b', 'c']
assert C.cli(argv=['--argv-items', 'a', 'b', 'c']).argv_items == ['a', 'b', 'c']
```

### Special option collisions

Scriptconfig commonly added `--config`, `--dump`, and `--dumps` to every CLI.
Those names often collide with real fields.

`kwconf` makes them opt-in:

```python
class MyConfig(kwconf.Config):
    __special_options__ = True
    value = 1


cfg = MyConfig.cli(argv=['--config=config.yaml'])
```

You can also pass `special_options=True` per call.

### `cmdline` examples

Late scriptconfig already supports `argv`. Older docs, examples, and LLM
answers often use `cmdline` because that was the historical spelling.

Use `argv` in kwconf:

```python
cfg = MyConfig.cli(argv=['--option1=3'])
cfg = MyConfig().load(data={'option1': 2}, argv=False)
```

Accepted shapes are `None`/`True` for `sys.argv`, `False` to skip CLI parsing,
`list[str]`, or a shell-like string.

### Config vs DataConfig

Scriptconfig has both `Config` and `DataConfig`. `kwconf` exposes one public
base class:

```python
class MyConfig(kwconf.Config):
    option = 1
```

### Constructor overloads

Scriptconfig accepted constructor forms such as `Config(data=..., cmdline=...)`.
`kwconf` constructors are keyword-based:

```python
cfg = MyConfig(option=2)
cfg = MyConfig().load({'option': 2})
cfg = MyConfig.cli(data={'option': 2}, argv=False)
```

### Boolean flags

Prefer `kwconf.Flag` for boolean flags and `Value(..., isflag='counter')` for
counters:

```python
class C(kwconf.Config):
    dry_run = kwconf.Flag(False, help='print actions only')
    verbose = kwconf.Value(0, isflag='counter', short_alias=['v'])
```

Keep positional arguments as separate `Value(position=...)` fields.

### Path helpers

Scriptconfig exposed `Path` and `PathList`. In kwconf, keep path policy in your
config class or application code:

```python
class C(kwconf.Config):
    out = kwconf.Value(None, parser=str, help='output directory')
    inputs = kwconf.Value(default_factory=list, nargs='+', help='input files')

    def __post_init__(self):
        import glob
        import os
        if self.out is not None:
            self.out = os.path.expanduser(self.out)
        self.inputs = [p for pat in self.inputs
                       for p in sorted(glob.glob(os.path.expanduser(pat)))]
```

### Modal defaults

Scriptconfig modal dispatch could forward every resolved child value into the
child `main`, including defaults. That made omitted arguments look explicit.

`kwconf` forwards explicit child argv values. Child commands can then merge repo
or runtime defaults cleanly:

```python
class ArchiveSource(kwconf.Config):
    depth = kwconf.Value('full')
    verbose = kwconf.Flag(False)

    @classmethod
    def main(cls, argv=None, **kwargs):
        repo_defaults = {'depth': '0'}
        config = cls.cli(argv=False, data=kwargs, default=repo_defaults)
        return config
```

### Lifecycle aliases

Rename old non-dunder helpers:

* `default` -> `__default__`
* `normalize` -> `__post_init__`
* `description` -> `__description__`
* `epilog` -> `__epilog__`
* `prog` -> `__prog__`

## `type=` to `parser=`

`type=` is still accepted as a deprecated alias. Use `parser=` in new docs and
new code.

```python
# scriptconfig style
kwconf.Value(0, type=int)
kwconf.Value(None, type='yaml')

# kwconf style
kwconf.Value(0, parser=int)
kwconf.Value(None, parser='yaml')
```

Magic smartcast aliases such as `type='smartcast'`, `type='smartcast:v1'`, and
`type='smartcast:legacy'` are retired. Use `parser='auto'`, `parser='csv'`,
`parser='yaml'`, or a callable.

## `Value.cast` to `Value.coerce`

If you subclassed `Value`, subclass `kwconf.ValueClass` and rename `cast` to
`coerce`.

```python
import kwconf


class MyValue(kwconf.ValueClass):
    def coerce(self, value):
        return value.strip()
```

Direct calls to `template.cast(value)` become `template.coerce(value)`.

## Validation

`kwconf` checks user-supplied values against annotations after parsing. The
default policy is `warn`. Use `__validate__ = 'error'` for stricter CLIs.

```python
class C(kwconf.Config):
    __validate__ = 'error'
    count: int = 0
```

Validation applies to constructor values, loaded data, assignment, parsed argv,
and parsed env. Field defaults are accepted as declared. See [Core Contract](core_contract.rst).

## Things that stayed familiar

* `Config.cli`, `load`, `dump`, and `dumps`.
* Modal CLIs with `ModalCLI`, `ModalValue`, registration, and nested dispatch.
* Nested configs with `SubConfig`, dotted overrides, and selectors.
* argparse integration: `argparse`, `port_to_argparse`, `port_from_argparse`,
  and `cls_from_argparse`.
* Aliases, short aliases, `nargs`, `position`, groups, mutex groups, fuzzy
  hyphens, argcomplete, and rich argparse integration.

## Checklist

1. Replace `import scriptconfig as scfg` with `import kwconf`.
2. Replace `scfg.Config` / `scfg.DataConfig` with `kwconf.Config`.
3. Replace old constructor loading with kwargs, `.load(...)`, or `.cli(...)`.
4. Search for `cmdline=` and migrate to `argv=`. Remember that recent
   scriptconfig already supports `argv`.
5. Replace new-code `type=` examples with `parser=`.
6. Audit comma-separated CLI values. Choose `nargs`, `parser='csv'`, or
   `parser='yaml'` where structure is intended.
7. Opt into `--config`, `--dump`, and `--dumps` if the old CLI exposed them.
8. Replace `Path` / `PathList` with explicit path handling.
9. Rename `cast` overrides to `coerce` on `ValueClass` subclasses.
10. Run tests and review validation warnings.
