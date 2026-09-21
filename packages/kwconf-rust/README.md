# kwconf-rust

`kwconf-rust` is the optional native accelerator for [`kwconf`](https://github.com/Erotemic/kwconf).

The normal `kwconf` distribution remains pure Python. Installing this package
adds the `_kwconf_rust` CPython Stable-ABI extension; `kwconf` discovers it in
`auto` backend mode and delegates only CLI shapes whose semantics are covered
by the differential compatibility suite.

```bash
python -m pip install kwconf-rust
```

The package version is synchronized with `kwconf` and requires the exact same
`kwconf` version. Set `KWCONF_CLI_BACKEND=python` to force the canonical Python
implementation even when this accelerator is installed.

The Rust sources are maintained in the same repository as `kwconf`; the shared
Python-independent parser core remains under `rust/kwconf_accel_core`.
