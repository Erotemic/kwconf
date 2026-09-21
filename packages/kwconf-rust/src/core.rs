//! Compatibility pointer for the early accelerator prototype.
//!
//! The implementation moved to the Python-independent `kwconf-cli-core`
//! crate in `../kwconf_accel_core`.  Keep this file as a breadcrumb for old
//! patches and review links; new Rust code should import `kwconf_cli_core`.

pub use kwconf_cli_core::*;
