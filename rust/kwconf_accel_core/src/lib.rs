//! Python-independent command-line kernel shared by the kwconf accelerator.
//!
//! This crate deliberately has no PyO3 dependency.  The `_kwconf_rust`
//! extension is a thin ABI3 adapter, and native Rust frontends such as
//! `kwconf-rs` can consume the same recognition/completion/router primitives.

mod core;

pub use core::*;
