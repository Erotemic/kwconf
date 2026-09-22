# Native backend experiment outcome

The optional Rust CLI accelerator was removed after the 0.12.x experiment.
The parser core itself was substantially faster than argparse, but end-to-end
Python CLI latency remained dominated by interpreter startup, importing the
native extension added a fixed cold cost, and full kwconf semantics required a
large delegation/fallback surface. The maintenance and release complexity did
not justify the practical user-facing gain.

The Python-side improvements discovered during the experiment remain part of
kwconf: lazy top-level imports, cold-method splitting, cheaper Config state
materialization, warning-stack cleanup, and corrected cold benchmark semantics.
The retained benchmarks in this directory compare canonical Python kwconf with
stdlib argparse and should continue to guard those wins.
