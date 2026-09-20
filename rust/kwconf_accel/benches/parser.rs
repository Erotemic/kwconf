use kwconf_cli_core::{
    CompletionCommandSpec, CompletionOptionSpec, CoreCompletionIndex, CoreFlatParser,
    FieldSpec, KIND_COUNTER, KIND_FLAG, KIND_OPTIONAL, KIND_VALUE,
};
use criterion::{criterion_group, criterion_main, BatchSize, BenchmarkId, Criterion, Throughput};
use std::hint::black_box;

const SCHEMA_SIZES: &[usize] = &[1, 16, 64, 256, 1024];
const DENSE_SIZES: &[usize] = &[1, 16, 64, 256];

fn scalar_specs(size: usize) -> Vec<FieldSpec> {
    (0..size)
        .map(|idx| {
            (
                format!("option_{idx}"),
                vec![format!("--option_{idx}"), format!("--option-{idx}")],
                KIND_VALUE,
            )
        })
        .collect()
}

fn sparse_argv(size: usize) -> Vec<String> {
    let index = size.saturating_sub(1);
    vec![format!("--option-{index}=value")]
}

fn dense_argv(size: usize) -> Vec<String> {
    (0..size)
        .map(|idx| format!("--option-{idx}=value{idx}"))
        .collect()
}

fn mixed_specs(size: usize) -> Vec<FieldSpec> {
    (0..size)
        .map(|idx| {
            let kind = match idx % 4 {
                0 => KIND_VALUE,
                1 => KIND_FLAG,
                2 => KIND_COUNTER,
                _ => KIND_OPTIONAL,
            };
            (
                format!("option_{idx}"),
                vec![format!("--option_{idx}"), format!("--option-{idx}")],
                kind,
            )
        })
        .collect()
}

fn mixed_argv(size: usize) -> Vec<String> {
    (0..size)
        .map(|idx| match idx % 4 {
            0 | 3 => format!("--option-{idx}=value{idx}"),
            1 | 2 => format!("--option-{idx}"),
            _ => unreachable!(),
        })
        .collect()
}

fn completion_specs(size: usize) -> Vec<CompletionOptionSpec> {
    (0..size)
        .map(|idx| {
            (
                vec![],
                vec![format!("--option_{idx}"), format!("--option-{idx}")],
                true,
                vec!["alpha".to_owned(), "beta".to_owned(), "gamma".to_owned()],
                format!("option {idx}"),
            )
        })
        .collect()
}

fn modal_specs(size: usize) -> Vec<CompletionCommandSpec> {
    (0..size)
        .map(|idx| {
            (
                vec![],
                format!("command_{idx}"),
                vec![format!("command-{idx}")],
                format!("command {idx}"),
            )
        })
        .collect()
}

fn counter_parser() -> CoreFlatParser {
    CoreFlatParser::new(vec![(
        "verbose".to_owned(),
        vec!["--verbose".to_owned(), "-v".to_owned()],
        KIND_COUNTER,
    )])
    .unwrap()
}

fn benchmark_schema_build(c: &mut Criterion) {
    let mut group = c.benchmark_group("schema_build");
    for &size in SCHEMA_SIZES {
        group.throughput(Throughput::Elements(size as u64));
        let specs = scalar_specs(size);
        group.bench_with_input(BenchmarkId::from_parameter(size), &size, |b, _| {
            b.iter_batched(
                || specs.clone(),
                |owned| CoreFlatParser::new(black_box(owned)).unwrap(),
                BatchSize::SmallInput,
            )
        });
    }
    group.finish();
}

fn benchmark_sparse_parse(c: &mut Criterion) {
    let mut group = c.benchmark_group("parse_sparse");
    for &size in SCHEMA_SIZES {
        let parser = CoreFlatParser::new(scalar_specs(size)).unwrap();
        let argv = sparse_argv(size);
        group.throughput(Throughput::Elements(argv.len() as u64));
        group.bench_with_input(BenchmarkId::from_parameter(size), &size, |b, _| {
            b.iter(|| parser.parse(black_box(&argv)))
        });
    }
    group.finish();
}

fn benchmark_dense_parse(c: &mut Criterion) {
    let mut group = c.benchmark_group("parse_dense");
    for &size in DENSE_SIZES {
        let parser = CoreFlatParser::new(scalar_specs(size)).unwrap();
        let argv = dense_argv(size);
        group.throughput(Throughput::Elements(argv.len() as u64));
        group.bench_with_input(BenchmarkId::from_parameter(size), &size, |b, _| {
            b.iter(|| parser.parse(black_box(&argv)))
        });
    }
    group.finish();
}

fn benchmark_mixed_parse(c: &mut Criterion) {
    let mut group = c.benchmark_group("parse_mixed");
    for &size in DENSE_SIZES {
        let parser = CoreFlatParser::new(mixed_specs(size)).unwrap();
        let argv = mixed_argv(size);
        group.throughput(Throughput::Elements(argv.len() as u64));
        group.bench_with_input(BenchmarkId::from_parameter(size), &size, |b, _| {
            b.iter(|| parser.parse(black_box(&argv)))
        });
    }
    group.finish();
}

fn benchmark_short_cluster(c: &mut Criterion) {
    let parser = counter_parser();
    let mut group = c.benchmark_group("parse_short_cluster");
    for &count in &[1usize, 4, 16, 64] {
        let argv = vec![format!("-{}", "v".repeat(count))];
        group.throughput(Throughput::Bytes(count as u64));
        group.bench_with_input(BenchmarkId::from_parameter(count), &count, |b, _| {
            b.iter(|| parser.parse(black_box(&argv)))
        });
    }
    group.finish();
}

fn benchmark_completion_build(c: &mut Criterion) {
    let mut group = c.benchmark_group("completion_build");
    for &size in SCHEMA_SIZES {
        group.throughput(Throughput::Elements(size as u64));
        let specs = completion_specs(size);
        group.bench_with_input(BenchmarkId::from_parameter(size), &size, |b, _| {
            b.iter_batched(
                || specs.clone(),
                |owned| CoreCompletionIndex::new(black_box(owned), vec![]),
                BatchSize::SmallInput,
            )
        });
    }
    group.finish();
}

fn benchmark_completion_options(c: &mut Criterion) {
    let mut group = c.benchmark_group("complete_options");
    for &size in SCHEMA_SIZES {
        let index = CoreCompletionIndex::new(completion_specs(size), vec![]);
        group.throughput(Throughput::Elements(size as u64));
        group.bench_with_input(BenchmarkId::from_parameter(size), &size, |b, _| {
            b.iter(|| index.complete_values(black_box(&[]), black_box("--option-")))
        });
    }
    group.finish();
}

fn benchmark_completion_choice(c: &mut Criterion) {
    let mut group = c.benchmark_group("complete_choice");
    for &size in SCHEMA_SIZES {
        let index = CoreCompletionIndex::new(completion_specs(size), vec![]);
        let option = format!("--option-{}", size.saturating_sub(1));
        let before = vec![option];
        group.throughput(Throughput::Elements(1));
        group.bench_with_input(BenchmarkId::from_parameter(size), &size, |b, _| {
            b.iter(|| index.complete_values(black_box(&before), black_box("b")))
        });
    }
    group.finish();
}

fn benchmark_modal_route(c: &mut Criterion) {
    let mut group = c.benchmark_group("modal_route");
    for &size in SCHEMA_SIZES {
        let index = CoreCompletionIndex::new(vec![], modal_specs(size));
        let argv = vec![format!("command-{}", size.saturating_sub(1))];
        group.throughput(Throughput::Elements(1));
        group.bench_with_input(BenchmarkId::from_parameter(size), &size, |b, _| {
            b.iter(|| index.route(black_box(&argv)))
        });
    }
    group.finish();
}

fn benchmark_fallback(c: &mut Criterion) {
    let mut group = c.benchmark_group("fallback_detection");
    for &size in SCHEMA_SIZES {
        let parser = CoreFlatParser::new(scalar_specs(size)).unwrap();
        let argv = vec!["--definitely-unknown=value".to_owned()];
        group.throughput(Throughput::Elements(1));
        group.bench_with_input(BenchmarkId::from_parameter(size), &size, |b, _| {
            b.iter(|| parser.parse(black_box(&argv)))
        });
    }
    group.finish();
}

criterion_group!(
    benches,
    benchmark_schema_build,
    benchmark_sparse_parse,
    benchmark_dense_parse,
    benchmark_mixed_parse,
    benchmark_short_cluster,
    benchmark_fallback,
    benchmark_completion_build,
    benchmark_completion_options,
    benchmark_completion_choice,
    benchmark_modal_route,
);
criterion_main!(benches);
