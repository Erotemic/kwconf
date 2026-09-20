# kwconf-cli-core contract

`kwconf-cli-core` is the Python-independent mechanics layer shared by the
optional Python accelerator and intended future native `kwconf-rs` integration.
It is deliberately smaller than either frontend.

## Claim-or-delegate rule

The core may return a successful result only when the request is inside its
explicit grammar. A frontend must delegate every other request to its canonical
implementation rather than interpreting a partial result as an error.

For Python kwconf this means:

- successful supported argv may be committed without constructing argparse;
- unsupported syntax, invalid values, help, and user-facing errors are retried
  through the canonical Python parser;
- static Bash completion can be emitted directly;
- dynamic or shell-sensitive completion is handed to argcomplete;
- static modal routing can select a leaf before argparse construction;
- opaque/dynamic modal commands are handed to `ModalCLI`.

This distinction is part of the compatibility contract. `not claimed` is not a
parse error.

## Flat parser IR

`FieldSpec` is currently:

```text
(canonical_key, option_spellings, kind)
```

Kinds cover required-value, bool/flag, counter, and optional/bare-value fields.
The parser returns ordered assignment operations plus unknown argv and an
optional fallback reason. Python remains responsible for destination-specific
coercion, choices, required/mutex diagnostics, and committing values.

Stable behavior currently includes:

- exact long/short option recognition;
- canonical aliases supplied by the frontend;
- generated `--no-*` spellings for flag/counter fields;
- compact short clusters;
- repeated assignments in argv order;
- a conservative fallback on abbreviations, unsupported missing-value states,
  and syntax outside the core grammar.

## Completion / routing IR

`CompletionOptionSpec` contains:

```text
(command_path, option_spellings, takes_value, finite_choices, help)
```

`CompletionCommandSpec` contains:

```text
(parent_path, canonical_command, aliases, help)
```

The completion index preserves declaration and alias order. It returns `None`
for dynamic value positions so the frontend can delegate to filesystem/custom
completion. The router canonicalizes command aliases and returns the number of
argv tokens consumed before the selected leaf.

The core does **not** implement shell quoting or Rich formatting. Those are
frontend presentation responsibilities.

## Versioning

The Python ABI adapter exposes a separate integer protocol version through
`backend_info()`. Any incompatible change to the FFI tuples, operation codes,
or claim/delegate semantics must bump that version. The pure Rust crate may
add methods without changing the Python protocol when the adapter surface is
unchanged.

## kwconf-rs convergence

The intended direction is for `kwconf-rs` to consume this crate (or its
stabilized successor) for mechanics that must match Python kwconf exactly,
while retaining clap-native Rust APIs, help, errors, source layering, and
compile-time derives. A later versioned schema IR and shared differential corpus
should let all three implementations run against one semantic target:

1. Python kwconf + argparse;
2. Python kwconf + `_kwconf_rust`;
3. native `kwconf-rs`.
