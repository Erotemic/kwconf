# kwconf-cli-core

`kwconf-cli-core` is the Python-independent command-line kernel used by the
optional `_kwconf_rust` accelerator.  The directory name remains
`kwconf_accel_core` during the experimental overlay campaign, but the Cargo
package and library deliberately use the generic `kwconf-cli-core` /
`kwconf_cli_core` names.

The extraction boundary is intentional: this crate has no PyO3 dependency and
owns only reusable command-line mechanics:

- exact option recognition and compact short clusters;
- flag negation / counters / optional bare values;
- conservative fallback detection;
- static option / finite-choice completion;
- static modal command indexing and routing.

Python-specific coercion, arbitrary callbacks, argparse diagnostics, Rich help,
and dynamic argcomplete behavior stay outside the crate.  That makes the core
a plausible convergence point with `kwconf-rs`: the native Rust project can
reuse the same recognition/completion primitives while still using `clap` (or
another native presentation layer) for its Rust-facing API, help, and errors.

The contract should grow by parity tests, not by guessing at argparse.  Any
operation the core cannot prove equivalent should return control to its caller.
