# Python accelerator / kwconf-rs convergence

The Python accelerator is a stepping stone toward native Rust applications,
not a second independent Rust CLI grammar.

## Shared layer

`rust/kwconf_accel_core` builds the PyO3-free Cargo package
`kwconf-cli-core`.  It should contain mechanics that are useful from either
Python or native Rust:

- option spelling / aliases / fuzzy-hyphen normalization inputs;
- boolean negation and short-cluster recognition;
- static command routing;
- static completion indices;
- eventually a versioned schema IR that both frontends can emit.

The Python extension `_kwconf_rust` is a thin ABI3 adapter over this crate.
`kwconf-rs` should be able to depend on the same core without linking Python.

## Frontend-owned behavior

Some behavior should *not* be forced into the shared core:

- Python `argparse.Action`, `type=` callbacks, and dynamic argcomplete
  completers remain Python-owned;
- Python error/help text remains stdlib/rich-argparse-owned when exact parity is
  required;
- native `kwconf-rs` can retain `clap`-native help/error/color conventions for
  a pure Rust application.

The shared layer should therefore return "not claimed" for behavior requiring
a frontend rather than approximating it.

## Next convergence milestone

After the Python accelerator settles, extract the Python-to-Rust field tuples
into a serialized/versioned schema IR.  Port the corresponding kwconf-rs
schema builder to emit/consume that IR, then move differential grammar tests
into a corpus runnable against:

1. canonical Python kwconf/argparse;
2. Python kwconf + `_kwconf_rust`;
3. pure `kwconf-rs`.

That gives Rust work one semantic target while allowing each frontend to keep
its appropriate presentation and extension ecosystem.
