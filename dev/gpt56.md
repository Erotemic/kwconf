# GPT-5.6 Engineering Journal: kwconf CLI Performance Experiment

Date: 2026-09-22  
Repository: `kwconf`  
Authoring assistant: GPT-5.6 Sol  
Status: Historical engineering journal; not normative API documentation.

## Purpose

This note records a multi-round experiment to determine whether an optional Rust
backend could materially improve `kwconf` command-line startup and parsing while
preserving the semantics and ergonomics of the existing Python API.

The experiment ended with a **negative shipping decision** for the Rust backend,
but it was still useful. It gave us a much better decomposition of `kwconf`
startup costs, exposed several Python-side costs that were worth optimizing, and
left behind a cleaner benchmark methodology for future work.

The most important conclusion is:

> The Rust parser itself was substantially faster than argparse, but the total
> user-visible benefit was too small to justify a second parser implementation,
> a native-extension release surface, and a permanent semantic fallback boundary.

The useful Python-side optimizations discovered during the experiment were kept.
The Rust backend and its production/release/test machinery were removed.

## Why we tried Rust

The motivating observation was that CLI startup is part of the user experience.
`kwconf` provides a much richer configuration model than direct argparse usage,
but that richness has historically made parser construction and startup more
expensive.

Rust seemed attractive for several reasons:

1. Parsing a small token stream is a good fit for a compact native parser.
2. Static `Config` schemas can often be compiled into a much smaller parse model
   than a full Python `ArgumentParser` object graph.
3. Shell completion has similar grammar needs and might benefit from the same
   compiled representation.
4. A native parser might make `kwconf` competitive with or faster than direct
   argparse while retaining the higher-level declarative API.

The experiment therefore explored an optional `kwconf-rust` package exposing a
`_kwconf_rust` extension, together with Python-side routing that used Rust for
supported static cases and delegated richer cases to the canonical Python path.

## Architecture that was explored

The design deliberately kept `kwconf` usable as a pure-Python package. The Rust
package was an optional accelerator.

For the common flat case, the fast path eventually became roughly:

```text
Config.cli()
    |
    +-- inspect static Config schema
    +-- load _kwconf_rust
    +-- construct/cache FlatParser
    +-- parse argv in Rust
    +-- apply parsed values back to Config
```

A major optimization during the experiment was moving the common native path
into a small direct hot core rather than importing the larger generic Rust bridge.
The explicit public `.argparse()` API remained Python and continued to return the
real `kwconf.argparse_ext.ExtendedArgumentParser`.

Unsupported or dynamic cases delegated back to Python. This was necessary to
preserve behavior instead of approximating it.

Examples of features that were native or close to native included ordinary flat
options, aliases, counters, choices, boolean flags/negation, repeated options,
parse-known behavior, static completion, and some static ModalCLI routing.

Examples that still needed Python delegation included dynamic `SubConfig`
selectors, Python callbacks, richer positional behavior, config-file/data-source
precedence, special dump/config lifecycle behavior, diagnostics/help formatting,
dynamic/filesystem completion, opaque Python command functions, and other
semantics whose source of truth remained Python/argparse.

That hybrid contract was functionally safe, but it became one of the main costs
of shipping the feature: users could enable a Rust backend without every CLI
actually running fully in Rust, and the project had to maintain and test both the
native subset and the delegation boundary.

## Benchmark methodology evolved during the experiment

One of the most valuable outcomes was discovering that our first benchmarks were
not asking the right question.

Early measurements emphasized warm in-process loops. Those are useful for
understanding parser-engine throughput, but they are not representative of what
a user feels when invoking a Python CLI from a shell.

We changed the benchmark suite to emphasize **fresh-process latency** and to split
that latency into attributable phases:

```text
process startup
library import / API realization
Config/schema definition
Config instance construction
backend materialization
parser engine
canonical reset / compatibility work
apply/finalize
```

We also added a `python -S` diagnostic to distinguish ordinary Python `site`
startup from CLI-specific work. This was never intended as a recommended runtime
mode; it was a way to see what the CLI would look like if interpreter startup
were cheaper.

### A benchmark bug we found

The production-style cold benchmark originally performed a warmup parse and then
one timed parse even when the requested repeat count was one. The parent process
measured the entire child lifetime, so the reported "cold" process actually
contained **two parses**.

That was corrected so the default cold measurement performs exactly one parse
per fresh process. Repeated-throughput mode still performs an intentional warmup
before the requested timed loop.

The corrected benchmark records `cold_parses_per_process = 1` so this assumption
is explicit and machine-checkable.

This is worth remembering: when startup differences are measured in fractions of
a millisecond, a benchmark that accidentally executes the operation twice can
completely distort the conclusion.

## What the measurements showed

The exact numbers varied somewhat between rounds and machines, so the values in
this section should be treated as representative measurements from this campaign,
not permanent performance promises.

### The Rust parser engine was genuinely fast

On the production-style CLI used near the end of the experiment, the parser
engine itself was approximately:

```text
argparse parse            ~141 us
Rust FlatParser parse      ~21 us
```

On another 64-field synthetic case the Rust token parse was around 9-11 us versus
roughly 90 us for argparse.

So the central hypothesis was not wrong: a compact native parser can beat the
Python parser engine by a large factor.

### But parser time was not the dominant cold cost

Ordinary fresh Python startup was roughly 43-45 ms in the measured environment.
That means even a hypothetical zero-cost CLI parser cannot produce a dramatic
whole-process speedup when both implementations must start the same Python
interpreter.

A representative late measurement looked approximately like:

```text
bare Python process       ~45 ms
argparse CLI              ~49 ms
kwconf + Rust CLI         ~49 ms
```

The exact ordering fluctuated within process noise, but the important result was
that the user-visible cold totals were effectively tied.

The `python -S` diagnostic made the hidden difference much clearer. With much of
normal `site` startup removed, Rust showed a substantially larger end-to-end
advantage. That confirmed that the parser architecture itself was efficient; the
problem was that normal Python startup masked most of the win.

### Backend materialization exposed the native-extension tax

A key late-stage decomposition showed that Rust backend materialization for the
production-style CLI was roughly:

```text
import/check _kwconf_rust       ~424 us
extract normalized schema        ~44 us
construct/cache FlatParser       ~23 us
---------------------------------------
total                            ~494 us
```

A 64-field synthetic case was similar, around 0.52-0.61 ms total depending on the
round.

The important discovery was that the Python-side protocol compatibility check was
not the culprit. Calling `_kwconf_rust.backend_info()` and checking the protocol
cost only about a microsecond. Nearly all of the ~0.4-0.6 ms fixed cost came from
loading the extension itself: Python import machinery, locating/loading the
shared object, dynamic linking, PyO3/module initialization, and related native
module setup.

That fixed cost consumed much of the advantage gained by the faster Rust parser.

### The remaining Python-side cost was larger than the parser

The other conspicuous cost was realizing the lazy `kwconf.Config` API and its
Python dependencies. A representative late measurement was around 1.4-1.7 ms.

Actual class declaration and instance construction were much smaller than that.
Once instrumentation separated lazy API realization from subclass construction,
it became clear that module-loading and dependency work had previously been
misattributed to "schema definition".

This distinction directly motivated Python-side import and cold-path cleanup.

## Why we decided not to ship the Rust backend

The final decision was not "Rust is slow." The Rust parser was fast.

The decision was that the **system-level tradeoff was poor** for this library.

### 1. The cold-start win was too small

Normal CLI invocation still had to start Python. Python startup dominated the
wall clock, leaving only a few milliseconds of CLI-specific work available to
optimize.

The native extension then introduced its own ~0.4-0.6 ms cold-load cost.

The resulting whole-process improvement was too small and noisy to be compelling.

### 2. The semantic surface was not naturally all-native

`kwconf.Config` and especially `kwconf.ModalCLI` can express behavior that is
inherently Python-dynamic or is deeply coupled to the canonical Python lifecycle.

Maintaining a native subset therefore required a permanent ownership contract:
Rust handled some cases, Python handled others, and code had to decide safely
which side owned each invocation.

That is additional architectural complexity even when fallback is perfectly
correct.

### 3. The release/packaging burden was real

Shipping the accelerator meant maintaining another distribution, native build
configuration, wheel jobs, platform compatibility, PyO3/Rust tooling, protocol
compatibility, and another set of tests and evidence gates.

For a small practical latency improvement, that maintenance burden was not
justified.

### 4. A native launcher was not an acceptable escape hatch

One theoretical way to avoid Python startup would be to place a native executable
or shim in front of Python, especially for completion.

That would fundamentally change deployment and invocation semantics: virtualenv
integration, editable installs, schema synchronization, shell wiring, and command
launch behavior would all become more complicated.

For `kwconf`, that was judged to be the wrong architecture merely to win startup
benchmarks.

## Python-side optimizations worth keeping

The Rust experiment was valuable because it forced us to measure the Python path
carefully. Several optimizations remain useful after deleting all Rust support.

The retained direction includes:

- lazy top-level API realization;
- moving cold `Config` functionality out of the startup-sensitive module path;
- splitting cold `Value` behavior similarly where useful;
- reducing unnecessary import-time dependencies such as eager `ubelt` usage;
- cheaper metaclass / Config-class construction work;
- cheaper Config state/default materialization;
- keeping argparse construction out of mere `kwconf` import and Config definition;
- warning-stack and related small Python cleanup discovered while profiling;
- the corrected one-parse production benchmark;
- benchmark tooling that distinguishes process startup, API realization, schema
  construction, parser materialization, parse time, and lifecycle/application
  costs.

A useful invariant after the cleanup is:

```text
import kwconf                  -> should not require argparse
realize Config / Value         -> should not require argparse
construct a Config subclass    -> should not require argparse
instantiate Config             -> should not require argparse
Config.cli()                   -> argparse may load here
```

That keeps ordinary library use cheap while retaining one canonical parser and
one canonical semantic implementation.

## Cleanup result

The production Rust experiment was removed rather than merely disabled.

The cleanup removed the native package/workspace, bridge modules, direct Rust hot
core, backend-selection/fallback machinery, Rust completion and ModalCLI routing,
backend-specific tests, evidence machinery, and native release/CI surface.

Generated CI/package files are expected to remain owned by xcookie rather than
being manually maintained downstream.

A final polish pass also removed the last dead Rust-only instance state and
rewrote comments that still described otherwise-useful Python optimizations in
Rust-specific terms.

At that point the package again had one clear runtime architecture:

```text
kwconf declarative API
        |
        v
optimized Python Config lifecycle
        |
        v
canonical argparse-compatible parser
```

## Lessons for future performance work

### Measure the user-visible operation first

Warm loops can make a subsystem optimization look transformative even when users
will never notice it. For CLIs, fresh-process measurements should be the headline;
warm throughput is supporting evidence.

### Decompose before optimizing

"Parser startup" turned out to contain very different costs:

- Python process startup,
- package import,
- lazy API realization,
- class/schema definition,
- backend materialization,
- token parsing,
- result application.

Without separating them, it was easy to optimize a 20 us component while missing
a 1.5 ms import cost or a 45 ms interpreter cost.

### Do not move costs between buckets and call it optimization

Importing `_kwconf_rust` earlier would have made "backend materialization" look
faster while leaving total cold latency unchanged.

Likewise, prebuilding a parser during class construction can move time from parse
to definition without improving the operation users care about.

Total fresh-process latency must remain the arbiter.

### Native extensions have a meaningful fixed cold cost

For microsecond-scale work, a several-hundred-microsecond extension load is not a
rounding error. Native acceleration is most compelling when enough work follows
the load to amortize it, or when the extension is already resident for unrelated
reasons.

### Semantic duplication is itself a performance cost for maintainers

A second implementation needs contracts, fallback policy, parity tests, release
machinery, diagnostics, and ongoing reasoning about which implementation owns a
case.

Even if runtime overhead is small, engineering overhead can dominate the value of
the optimization.

### Negative experiments should leave artifacts

This journal exists so a future maintainer does not rediscover the same idea,
see that Rust can parse tokens much faster, and repeat the entire experiment
without knowing why it was previously retired.

The right takeaway is not "never use Rust." It is:

> For the measured `kwconf` architecture, an optional native parser did not buy
> enough end-user latency to justify its fixed load cost and semantic/release
> complexity. Revisit only if one of the surrounding constraints changes.

## Conditions that could justify revisiting native acceleration

A future native experiment might make sense if one or more of these assumptions
change materially:

1. Python interpreter startup becomes much cheaper.
2. `kwconf` gains a workload where the parser is invoked many times per process
   and parser throughput becomes dominant.
3. A native extension is already loaded for other reasons, eliminating most of
   the fixed-load tax.
4. The supported CLI semantics become sufficiently static that nearly the entire
   grammar can be owned by one native implementation without a large delegation
   boundary.
5. Packaging native wheels becomes effectively free for the project.
6. There is a compelling non-Python consumer of the same schema/compiler that
   makes the native implementation valuable independent of Python CLI latency.

Absent one of those changes, further effort is better spent reducing Python
startup/import/configuration costs in the canonical implementation.

## Practical next directions

The experiment suggests a clearer optimization priority for `kwconf`:

1. Keep top-level imports and API realization lean.
2. Keep argparse and rich presentation machinery cold until CLI parsing/help is
   actually requested.
3. Continue measuring Config/metaclass construction independently from imports.
4. Profile Python `ExtendedArgumentParser` construction, which remains a much
   larger cost than token parsing.
5. Preserve the one-parse fresh-process benchmark as the release-facing startup
   signal.
6. Treat warm parser throughput as diagnostic, not the headline result.
7. Prefer Python-side simplifications that improve every installation over
   optional accelerator paths that improve only a subset of invocations.

## Final assessment

The Rust experiment was technically successful at proving that a compiled parser
could be very fast, but unsuccessful as a product optimization for `kwconf`.

That is still a useful result.

We ended with:

- better performance instrumentation;
- a corrected cold-start benchmark;
- several retained Python startup and Config-construction improvements;
- a simpler runtime architecture than the experimental branch had accumulated;
- evidence explaining why a native parser is not currently worth maintaining.

The durable recommendation is to continue optimizing the single Python
implementation unless the surrounding economics of Python startup, native module
loading, or semantic ownership change substantially.
