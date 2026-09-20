use std::collections::{HashMap, HashSet};

pub const KIND_VALUE: u8 = 0;
pub const KIND_FLAG: u8 = 1;
pub const KIND_COUNTER: u8 = 2;
pub const KIND_OPTIONAL: u8 = 3;

pub const OP_VALUE: u8 = 0;
pub const OP_FLAG_BARE: u8 = 1;
pub const OP_FLAG_VALUE: u8 = 2;
pub const OP_COUNTER_BARE: u8 = 3;
pub const OP_COUNTER_VALUE: u8 = 4;
pub const OP_OPTIONAL_BARE: u8 = 5;

pub type RawAssignment = (usize, u8, Option<(String, bool)>);
pub type ParseOutput = (Vec<RawAssignment>, Vec<String>, Option<String>);
pub type FieldSpec = (String, Vec<String>, u8);

pub type CompletionOptionSpec = (Vec<String>, Vec<String>, bool, Vec<String>, String);
pub type CompletionCommandSpec = (Vec<String>, String, Vec<String>, String);
pub type CompletionResult = Vec<(String, String)>;

#[derive(Clone, Debug)]
struct CompletionOption {
    spellings: Vec<String>,
    takes_value: bool,
    choices: Vec<String>,
    help: String,
}

#[derive(Clone, Debug)]
struct CompletionCommand {
    name: String,
    aliases: Vec<String>,
    help: String,
}

#[derive(Clone, Debug, Default)]
pub struct CoreCompletionIndex {
    options: HashMap<Vec<String>, Vec<CompletionOption>>,
    commands: HashMap<Vec<String>, Vec<CompletionCommand>>,
}

impl CoreCompletionIndex {
    pub fn new(
        option_specs: Vec<CompletionOptionSpec>,
        command_specs: Vec<CompletionCommandSpec>,
    ) -> Self {
        let mut options: HashMap<Vec<String>, Vec<CompletionOption>> = HashMap::new();
        let mut commands: HashMap<Vec<String>, Vec<CompletionCommand>> = HashMap::new();
        for (path, spellings, takes_value, choices, help) in option_specs {
            options.entry(path).or_default().push(CompletionOption {
                spellings,
                takes_value,
                choices,
                help,
            });
        }
        for (path, name, aliases, help) in command_specs {
            commands.entry(path).or_default().push(CompletionCommand {
                name,
                aliases,
                help,
            });
        }
        Self { options, commands }
    }

    fn find_option<'a>(&'a self, path: &[String], spelling: &str) -> Option<&'a CompletionOption> {
        self.options.get(path)?.iter().find(|item| {
            item.spellings.iter().any(|candidate| candidate == spelling)
        })
    }

    fn active_path(&self, args: &[String]) -> Vec<String> {
        let mut path: Vec<String> = Vec::new();
        let mut index = 0usize;
        while index < args.len() {
            let token = &args[index];
            if token.starts_with('-') {
                let option_name = token.split_once('=').map(|x| x.0).unwrap_or(token.as_str());
                if token.find('=').is_none() {
                    if let Some(option) = self.find_option(&path, option_name) {
                        if option.takes_value {
                            index += 1;
                        }
                    }
                }
                index += 1;
                continue;
            }
            let mut matched = None;
            if let Some(items) = self.commands.get(&path) {
                for command in items {
                    if token == &command.name || command.aliases.iter().any(|alias| alias == token) {
                        matched = Some(command.name.clone());
                        break;
                    }
                }
            }
            if let Some(name) = matched {
                path.push(name);
            }
            index += 1;
        }
        path
    }

    pub fn route(&self, args: &[String]) -> Option<(Vec<String>, usize)> {
        let mut path: Vec<String> = Vec::new();
        let mut consumed = 0usize;
        loop {
            let commands = self.commands.get(&path)?;
            let token = args.get(consumed)?;
            if token.starts_with('-') {
                return None;
            }
            let mut matched = None;
            for command in commands {
                if token == &command.name || command.aliases.iter().any(|alias| alias == token) {
                    matched = Some(command.name.clone());
                    break;
                }
            }
            let name = matched?;
            path.push(name);
            consumed += 1;
            if !self.commands.contains_key(&path) {
                return Some((path, consumed));
            }
        }
    }

    fn complete_internal(
        &self,
        args_before: &[String],
        prefix: &str,
        include_help: bool,
    ) -> Option<CompletionResult> {
        let path = self.active_path(args_before);

        let describe_option = |option: &CompletionOption| {
            if include_help {
                option.help.clone()
            } else {
                String::new()
            }
        };
        let describe_command = |command: &CompletionCommand| {
            if include_help {
                command.help.clone()
            } else {
                String::new()
            }
        };

        if let Some((option_name, value_prefix)) = prefix.split_once('=') {
            if let Some(option) = self.find_option(&path, option_name) {
                if option.takes_value && !option.choices.is_empty() {
                    let help = describe_option(option);
                    return Some(
                        option
                            .choices
                            .iter()
                            .filter(|choice| choice.starts_with(value_prefix))
                            .map(|choice| (format!("{option_name}={choice}"), help.clone()))
                            .collect(),
                    );
                }
                if option.takes_value {
                    // Argcomplete's default completer may provide filesystem
                    // or user-defined values. Static Rust completion cannot
                    // claim a value position without a finite choice set.
                    return None;
                }
            }
            return Some(Vec::new());
        }

        if let Some(previous) = args_before.last() {
            if let Some(option) = self.find_option(&path, previous) {
                if option.takes_value && !option.choices.is_empty() {
                    let help = describe_option(option);
                    return Some(
                        option
                            .choices
                            .iter()
                            .filter(|choice| choice.starts_with(prefix))
                            .map(|choice| (choice.clone(), help.clone()))
                            .collect(),
                    );
                }
                if option.takes_value {
                    return None;
                }
            }
        }

        let mut result: CompletionResult = Vec::new();
        if let Some(items) = self.options.get(&path) {
            for option in items {
                let help = describe_option(option);
                for spelling in &option.spellings {
                    if spelling.starts_with(prefix) {
                        result.push((spelling.clone(), help.clone()));
                    }
                }
            }
        }
        if let Some(items) = self.commands.get(&path) {
            for command in items {
                let help = describe_command(command);
                if command.name.starts_with(prefix) {
                    result.push((command.name.clone(), help.clone()));
                }
                for alias in &command.aliases {
                    if alias.starts_with(prefix) {
                        result.push((alias.clone(), help.clone()));
                    }
                }
            }
        }
        // Preserve schema / alias declaration order to match argparse +
        // argcomplete.  De-duplicate without sorting: completion ordering is
        // user-visible and is part of the compatibility contract.
        let mut deduped: CompletionResult = Vec::with_capacity(result.len());
        let mut seen: HashSet<String> = HashSet::with_capacity(result.len());
        for item in result {
            if seen.insert(item.0.clone()) {
                deduped.push(item);
            }
        }
        Some(deduped)
    }

    pub fn complete(&self, args_before: &[String], prefix: &str) -> Option<CompletionResult> {
        self.complete_internal(args_before, prefix, true)
    }

    /// Candidate-only completion for shells/protocols that do not consume
    /// descriptions. This avoids cloning help strings and converting tuple
    /// metadata across an FFI boundary for the common Bash fast path.
    pub fn complete_values(&self, args_before: &[String], prefix: &str) -> Option<Vec<String>> {
        self.complete_internal(args_before, prefix, false)
            .map(|items| items.into_iter().map(|item| item.0).collect())
    }
}

#[derive(Clone, Debug)]
struct OptionEntry {
    field: usize,
    kind: u8,
    negative: bool,
}

#[derive(Clone, Debug)]
pub struct CoreFlatParser {
    options: HashMap<String, OptionEntry>,
}

impl CoreFlatParser {
    pub fn new(specs: Vec<FieldSpec>) -> Result<Self, String> {
        let mut options = HashMap::new();
        for (field, (_key, option_strings, kind)) in specs.into_iter().enumerate() {
            if !matches!(kind, KIND_VALUE | KIND_FLAG | KIND_COUNTER | KIND_OPTIONAL) {
                return Err(format!("unknown kwconf accelerator field kind {kind}"));
            }
            for option in option_strings {
                insert_option(
                    &mut options,
                    option.clone(),
                    OptionEntry {
                        field,
                        kind,
                        negative: false,
                    },
                )?;
                if matches!(kind, KIND_FLAG | KIND_COUNTER) && option.starts_with("--") {
                    let negative = format!("--no-{}", &option[2..]);
                    insert_option(
                        &mut options,
                        negative,
                        OptionEntry {
                            field,
                            kind,
                            negative: true,
                        },
                    )?;
                }
            }
        }
        Ok(Self { options })
    }

    pub fn parse(&self, args: &[String]) -> ParseOutput {
        let mut assignments = Vec::with_capacity(args.len());
        let mut unknown = Vec::new();
        let mut index = 0usize;
        let mut after_separator = false;

        while index < args.len() {
            let token = &args[index];
            if after_separator {
                unknown.push(token.clone());
                index += 1;
                continue;
            }
            if token == "--" {
                after_separator = true;
                index += 1;
                continue;
            }
            if !token.starts_with('-') || token == "-" {
                unknown.push(token.clone());
                index += 1;
                continue;
            }

            if token.starts_with("--") {
                let (option_text, inline) = split_equals(token);
                let Some(entry) = self.options.get(option_text) else {
                    return (
                        assignments,
                        unknown,
                        Some(format!("unknown/abbreviated long option {option_text}")),
                    );
                };
                if let Err(reason) =
                    self.consume_entry(entry, inline, args, &mut index, &mut assignments)
                {
                    return (assignments, unknown, Some(reason));
                }
                index += 1;
                continue;
            }

            let (option_text, inline) = split_equals(token);
            if let Some(entry) = self.options.get(option_text) {
                if let Err(reason) =
                    self.consume_entry(entry, inline, args, &mut index, &mut assignments)
                {
                    return (assignments, unknown, Some(reason));
                }
                index += 1;
                continue;
            }

            if let Err(reason) = self.consume_short_cluster(
                option_text,
                inline,
                args,
                &mut index,
                &mut assignments,
            ) {
                return (assignments, unknown, Some(reason));
            }
            index += 1;
        }

        (assignments, unknown, None)
    }

    fn consume_entry(
        &self,
        entry: &OptionEntry,
        inline: Option<&str>,
        args: &[String],
        index: &mut usize,
        assignments: &mut Vec<RawAssignment>,
    ) -> Result<(), String> {
        match entry.kind {
            KIND_VALUE => {
                let raw = if let Some(value) = inline {
                    value.to_owned()
                } else {
                    let Some(next) = args.get(*index + 1) else {
                        return Err("missing required option value".to_owned());
                    };
                    if next.starts_with('-') {
                        return Err("dash-prefixed required value needs argparse".to_owned());
                    }
                    *index += 1;
                    next.clone()
                };
                assignments.push((entry.field, OP_VALUE, Some((raw, false))));
            }
            KIND_OPTIONAL => {
                if let Some(value) = inline {
                    assignments.push((
                        entry.field,
                        OP_VALUE,
                        Some((value.to_owned(), false)),
                    ));
                } else if let Some(next) = args.get(*index + 1) {
                    if !next.starts_with('-') {
                        *index += 1;
                        assignments.push((
                            entry.field,
                            OP_VALUE,
                            Some((next.clone(), false)),
                        ));
                    } else {
                        assignments.push((entry.field, OP_OPTIONAL_BARE, None));
                    }
                } else {
                    assignments.push((entry.field, OP_OPTIONAL_BARE, None));
                }
            }
            KIND_FLAG => {
                if let Some(value) = inline {
                    assignments.push((
                        entry.field,
                        OP_FLAG_VALUE,
                        Some((value.to_owned(), entry.negative)),
                    ));
                } else if let Some(next) = args.get(*index + 1) {
                    if !next.starts_with('-') {
                        *index += 1;
                        assignments.push((
                            entry.field,
                            OP_FLAG_VALUE,
                            Some((next.clone(), entry.negative)),
                        ));
                    } else {
                        assignments.push((
                            entry.field,
                            OP_FLAG_BARE,
                            Some((String::new(), entry.negative)),
                        ));
                    }
                } else {
                    assignments.push((
                        entry.field,
                        OP_FLAG_BARE,
                        Some((String::new(), entry.negative)),
                    ));
                }
            }
            KIND_COUNTER => {
                if let Some(value) = inline {
                    assignments.push((
                        entry.field,
                        OP_COUNTER_VALUE,
                        Some((value.to_owned(), entry.negative)),
                    ));
                } else if let Some(next) = args.get(*index + 1) {
                    if !next.starts_with('-') {
                        *index += 1;
                        assignments.push((
                            entry.field,
                            OP_COUNTER_VALUE,
                            Some((next.clone(), entry.negative)),
                        ));
                    } else {
                        assignments.push((
                            entry.field,
                            OP_COUNTER_BARE,
                            Some((String::new(), entry.negative)),
                        ));
                    }
                } else {
                    assignments.push((
                        entry.field,
                        OP_COUNTER_BARE,
                        Some((String::new(), entry.negative)),
                    ));
                }
            }
            _ => return Err(format!("invalid field kind {}", entry.kind)),
        }
        Ok(())
    }

    fn consume_short_cluster(
        &self,
        option_text: &str,
        inline: Option<&str>,
        args: &[String],
        index: &mut usize,
        assignments: &mut Vec<RawAssignment>,
    ) -> Result<(), String> {
        if !option_text.starts_with('-') || option_text.starts_with("--") {
            return Err("not a short option cluster".to_owned());
        }
        let body: Vec<char> = option_text[1..].chars().collect();
        if body.len() <= 1 {
            return Err(format!("unknown short option {option_text}"));
        }

        let first_name = format!("-{}", body[0]);
        let Some(first) = self.options.get(&first_name) else {
            return Err(format!("unknown short option {first_name}"));
        };

        if first.kind == KIND_VALUE {
            let mut value: String = body[1..].iter().collect();
            if let Some(explicit) = inline {
                if !value.is_empty() {
                    value.push('=');
                }
                value.push_str(explicit);
            }
            if value.is_empty() {
                let Some(next) = args.get(*index + 1) else {
                    return Err("missing required short-option value".to_owned());
                };
                if next.starts_with('-') {
                    return Err("dash-prefixed required value needs argparse".to_owned());
                }
                *index += 1;
                value = next.clone();
            }
            assignments.push((first.field, OP_VALUE, Some((value, false))));
            return Ok(());
        }

        let mut pos = 0usize;
        while pos < body.len() {
            let name = format!("-{}", body[pos]);
            let Some(entry) = self.options.get(&name) else {
                return Err(format!("invalid kwconf short cluster {option_text}"));
            };
            match entry.kind {
                KIND_FLAG | KIND_COUNTER | KIND_OPTIONAL => {
                    let last = pos + 1 == body.len();
                    if last {
                        if let Some(explicit) = inline {
                            match entry.kind {
                                KIND_FLAG => assignments.push((
                                    entry.field,
                                    OP_FLAG_VALUE,
                                    Some((explicit.to_owned(), entry.negative)),
                                )),
                                KIND_COUNTER => assignments.push((
                                    entry.field,
                                    OP_COUNTER_VALUE,
                                    Some((explicit.to_owned(), entry.negative)),
                                )),
                                KIND_OPTIONAL => assignments.push((
                                    entry.field,
                                    OP_VALUE,
                                    Some((explicit.to_owned(), false)),
                                )),
                                _ => unreachable!(),
                            }
                            pos += 1;
                            continue;
                        }
                    }
                    match entry.kind {
                        KIND_FLAG => assignments.push((
                            entry.field,
                            OP_FLAG_BARE,
                            Some((String::new(), entry.negative)),
                        )),
                        KIND_COUNTER => assignments.push((
                            entry.field,
                            OP_COUNTER_BARE,
                            Some((String::new(), entry.negative)),
                        )),
                        KIND_OPTIONAL => {
                            assignments.push((entry.field, OP_OPTIONAL_BARE, None))
                        }
                        _ => unreachable!(),
                    }
                    pos += 1;
                }
                KIND_VALUE => {
                    let remainder: String = body[pos + 1..].iter().collect();
                    let raw = if !remainder.is_empty() {
                        if let Some(explicit) = inline {
                            format!("{remainder}={explicit}")
                        } else {
                            remainder
                        }
                    } else if let Some(explicit) = inline {
                        explicit.to_owned()
                    } else {
                        let Some(next) = args.get(*index + 1) else {
                            return Err("missing required clustered value".to_owned());
                        };
                        if next.starts_with('-') {
                            return Err(
                                "dash-prefixed required clustered value needs argparse".to_owned(),
                            );
                        }
                        *index += 1;
                        next.clone()
                    };
                    assignments.push((entry.field, OP_VALUE, Some((raw, false))));
                    return Ok(());
                }
                _ => return Err(format!("invalid field kind {}", entry.kind)),
            }
        }
        Ok(())
    }
}

fn insert_option(
    options: &mut HashMap<String, OptionEntry>,
    spelling: String,
    entry: OptionEntry,
) -> Result<(), String> {
    if spelling == "-h" || spelling == "--help" {
        return Err(format!(
            "option spelling {spelling:?} conflicts with argparse help"
        ));
    }
    if options.insert(spelling.clone(), entry).is_some() {
        return Err(format!("duplicate option spelling {spelling:?}"));
    }
    Ok(())
}

fn split_equals(token: &str) -> (&str, Option<&str>) {
    if let Some(pos) = token.find('=') {
        (&token[..pos], Some(&token[pos + 1..]))
    } else {
        (token, None)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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

    #[test]
    fn sparse_scalar_parse() {
        let parser = CoreFlatParser::new(scalar_specs(64)).unwrap();
        let argv = vec!["--option-31=value".to_owned()];
        let (assignments, unknown, fallback) = parser.parse(&argv);
        assert_eq!(fallback, None);
        assert!(unknown.is_empty());
        assert_eq!(assignments.len(), 1);
        assert_eq!(assignments[0].0, 31);
        assert_eq!(assignments[0].1, OP_VALUE);
        assert_eq!(assignments[0].2.as_ref().unwrap().0, "value");
    }

    #[test]
    fn static_completion_claims_choices_but_not_dynamic_values() {
        let options = vec![
            (
                vec![],
                vec!["--mode".to_owned()],
                true,
                vec!["alpha".to_owned(), "beta".to_owned()],
                "mode".to_owned(),
            ),
            (
                vec![],
                vec!["--path".to_owned()],
                true,
                vec![],
                "path".to_owned(),
            ),
        ];
        let index = CoreCompletionIndex::new(options, vec![]);
        assert_eq!(
            index.complete(&["--mode".to_owned()], "b").unwrap()[0].0,
            "beta"
        );
        assert!(index.complete(&["--path".to_owned()], "").is_none());
        assert_eq!(
            index.complete_values(&["--mode".to_owned()], "b").unwrap(),
            vec!["beta".to_owned()],
        );
    }

    #[test]
    fn static_modal_router_canonicalizes_aliases() {
        let commands = vec![
            (
                vec![],
                "train_model".to_owned(),
                vec!["train-model".to_owned()],
                "train".to_owned(),
            ),
            (
                vec!["train_model".to_owned()],
                "run".to_owned(),
                vec![],
                "run".to_owned(),
            ),
        ];
        let index = CoreCompletionIndex::new(vec![], commands);
        let route = index
            .route(&[
                "train-model".to_owned(),
                "run".to_owned(),
                "--epochs=2".to_owned(),
            ])
            .unwrap();
        assert_eq!(route.0, vec!["train_model".to_owned(), "run".to_owned()]);
        assert_eq!(route.1, 2);
    }
}
