use kwconf_cli_core::{
    CompletionCommandSpec, CompletionOptionSpec, CoreCompletionIndex, CoreFlatParser, FieldSpec,
    KIND_COUNTER, KIND_FLAG, KIND_OPTIONAL, KIND_VALUE,
};
use std::hint::black_box;

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

fn usage() -> ! {
    eprintln!(
        "usage: kwconf-accel-profile WORKLOAD SCHEMA_SIZE ITERATIONS\n\
         workloads: build, parse-sparse, parse-dense, parse-mixed, short-cluster, fallback, \
         complete-options, complete-choice, route-modal"
    );
    std::process::exit(2);
}

fn parse_usize(text: Option<String>) -> usize {
    text.and_then(|value| value.parse().ok())
        .unwrap_or_else(|| usage())
}

fn main() {
    let mut args = std::env::args().skip(1);
    let workload = args.next().unwrap_or_else(|| usage());
    let size = parse_usize(args.next());
    let iterations = parse_usize(args.next());
    if args.next().is_some() {
        usage();
    }

    let mut checksum = 0usize;
    match workload.as_str() {
        "build" => {
            let specs = scalar_specs(size);
            for _ in 0..iterations {
                let parser = CoreFlatParser::new(black_box(specs.clone())).unwrap();
                black_box(parser);
                checksum = checksum.wrapping_add(1);
            }
        }
        "parse-sparse" => {
            let parser = CoreFlatParser::new(scalar_specs(size)).unwrap();
            let index = size.saturating_sub(1);
            let argv = vec![format!("--option-{index}=value")];
            for _ in 0..iterations {
                let result = parser.parse(black_box(&argv));
                checksum = checksum.wrapping_add(black_box(result.0.len()));
            }
        }
        "parse-dense" => {
            let parser = CoreFlatParser::new(scalar_specs(size)).unwrap();
            let argv: Vec<String> = (0..size)
                .map(|idx| format!("--option-{idx}=value{idx}"))
                .collect();
            for _ in 0..iterations {
                let result = parser.parse(black_box(&argv));
                checksum = checksum.wrapping_add(black_box(result.0.len()));
            }
        }
        "parse-mixed" => {
            let parser = CoreFlatParser::new(mixed_specs(size)).unwrap();
            let argv = mixed_argv(size);
            for _ in 0..iterations {
                let result = parser.parse(black_box(&argv));
                checksum = checksum.wrapping_add(black_box(result.0.len()));
            }
        }
        "short-cluster" => {
            let parser = CoreFlatParser::new(vec![(
                "verbose".to_owned(),
                vec!["--verbose".to_owned(), "-v".to_owned()],
                KIND_COUNTER,
            )])
            .unwrap();
            let argv = vec![format!("-{}", "v".repeat(size))];
            for _ in 0..iterations {
                let result = parser.parse(black_box(&argv));
                checksum = checksum.wrapping_add(black_box(result.0.len()));
            }
        }
        "complete-options" => {
            let index = CoreCompletionIndex::new(completion_specs(size), vec![]);
            for _ in 0..iterations {
                let result = index.complete_values(black_box(&[]), black_box("--option-"));
                checksum = checksum.wrapping_add(black_box(result.as_ref().map_or(0, Vec::len)));
            }
        }
        "complete-choice" => {
            let index = CoreCompletionIndex::new(completion_specs(size), vec![]);
            let before = vec![format!("--option-{}", size.saturating_sub(1))];
            for _ in 0..iterations {
                let result = index.complete_values(black_box(&before), black_box("b"));
                checksum = checksum.wrapping_add(black_box(result.as_ref().map_or(0, Vec::len)));
            }
        }
        "route-modal" => {
            let index = CoreCompletionIndex::new(vec![], modal_specs(size));
            let argv = vec![format!("command-{}", size.saturating_sub(1))];
            for _ in 0..iterations {
                let result = index.route(black_box(&argv));
                checksum = checksum.wrapping_add(black_box(
                    result.as_ref().map_or(0, |(_, consumed)| *consumed),
                ));
            }
        }
        "fallback" => {
            let parser = CoreFlatParser::new(scalar_specs(size)).unwrap();
            let argv = vec!["--definitely-unknown=value".to_owned()];
            for _ in 0..iterations {
                let result = parser.parse(black_box(&argv));
                checksum = checksum.wrapping_add(black_box(result.2.is_some()) as usize);
            }
        }
        _ => usage(),
    }
    println!("checksum={checksum}");
}
