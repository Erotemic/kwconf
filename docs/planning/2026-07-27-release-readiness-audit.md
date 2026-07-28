# kwconf 0.10.1 release-readiness audit — 2026-07-27

This follow-up audit was performed against post-`v0.10.0` development and then
rechecked after the initial regression-fix overlay. Unlike the differential
audit, this pass also records pre-existing defects that should not be lost when
the immediate release blockers are repaired.

## Release gate: fixed in the 2026-07-27 overlay

The following eight correctness issues are release-gating and have focused
regression tests in `tests/test_release_readiness_regressions.py`.

1. **Required fields use current-ingestion provenance.** A field is satisfied
   only when the current `load()` receives it through `data=`, `--config`, or
   explicit argv. Equality with a default is never used as a proxy, stale argv
   provenance is cleared, factory identity cannot accidentally satisfy a
   requirement, and dotted provenance is distributed to realized SubConfigs.
2. **Canonical/alias duplicate bindings are rejected.** Mapping ingestion is
   source-order deterministic and raises when two spellings target the same
   field, including canonical-plus-alias, alias-plus-alias, and nested dotted
   aliases.
3. **`@dataconf` preserves Python method semantics.** The generated Config is a
   subclass of the decorated class, so methods retain their original
   `__class__` closure and zero-argument `super()` works.
4. **Stdlib dataclass fields are translated completely.** In particular,
   `dataclasses.field(default_factory=...)` remains a factory recipe instead of
   disappearing when the dataclass decorator removes the class attribute.
5. **Concrete reset baselines never fall back to shared identity.** Concrete
   declared defaults and constructor/default overrides must support
   `copy.deepcopy`; otherwise kwconf raises an actionable error recommending
   `Value(default_factory=...)`. Factory outputs themselves are never copied.
6. **`SubConfig(instance)` uses Config-aware baseline cloning.** The instance is
   a reset-baseline template. Concrete baselines are copied and factory recipes
   are re-invoked; live runtime objects are neither deep-copied nor shared.
7. **`port_to_config()` preserves factory semantics.** Importable factories are
   emitted as `default_factory=...`; local/lambda/dynamically constructed
   factories produce a clear code-generation error rather than silently
   materializing one value.
8. **Descriptors are behavior, not fields.** Properties, cached properties, and
   other non-Value descriptors remain descriptors and are excluded from
   `__default__`.

### Locked state semantics

- A `default_factory` is a recipe invoked for each construction/reset.
- A concrete default is a snapshot baseline and therefore must be deeply
  copyable.
- Constructor and `update_defaults()` values become concrete reset baselines;
  they are trusted as Python values, but must still be deeply copyable because
  reset isolation is part of the Config contract.
- `SubConfig(instance)` clones the instance's reset baseline, not arbitrary
  mutations to its current runtime state.

## Follow-up defects fixed in the miscellaneous overlay

These seven issues were confirmed during the same release-readiness pass and
were fixed after the top-eight overlay.

- [x] **`Config.coerce()` alias parser lookup.** Aliased keys now use the
  canonical field's parser/type metadata, so `C.coerce(alias='42')` matches
  `C.coerce(canonical='42')`.
- [x] **`short_alias` schema collisions.** `Config.validate()` now rejects two
  fields claiming the same short option before argparse construction.
- [x] **Strict inline mode enforcement.** `mode='json'` no longer parses YAML
  inline text successfully.
- [x] **Consistent missing-path exceptions.** Missing `os.PathLike` inputs now
  raise the same `FileNotFoundError` diagnostic as missing string paths.
- [x] **Type-sensitive `Literal` validation.** `Literal[1]` rejects `True` even
  though `True == 1` in Python.
- [x] **Exclude `ClassVar` declarations.** Class-only metadata no longer becomes
  instance configuration fields, including through `@dataconf`.
- [x] **Make `Config.__json__()` actually JSON-safe.** Complex values now raise
  an explicit error, mixed incomparable mapping keys are not sorted, and the
  transformed result is checked by the standard JSON encoder.

## Documentation preservation correction

The release-readiness overlay initially replaced the ``dataconf`` function
docstring and accidentally removed its executable examples, the disabled pickle
example, the xdoctest FIXME, and the manual ``__example__()`` coverage. Those
items are restored. ``AGENTS.md`` now states that doctests and TODO comments must
never be removed unless the underlying issue is explicitly addressed, and a
regression test checks that the restored ``dataconf`` documentation remains.

## Verification checklist

Before tagging the release:

- [ ] Run the complete supported test matrix with test extras installed.
- [ ] Run Ruff format/check and both configured type checkers.
- [ ] Exercise `port_to_config()` from an installed wheel, not only a source
  checkout.
- [ ] Confirm release notes describe the concrete-default deepcopy requirement
  and factory recipe semantics.
