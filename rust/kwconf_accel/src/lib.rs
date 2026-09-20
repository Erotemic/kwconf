#[cfg(feature = "python-extension")]
use kwconf_cli_core::{
    CompletionCommandSpec, CompletionOptionSpec, CompletionResult, CoreCompletionIndex,
    CoreFlatParser, FieldSpec, ParseOutput,
};
#[cfg(feature = "python-extension")]
use pyo3::exceptions::PyValueError;
#[cfg(feature = "python-extension")]
use pyo3::prelude::*;

#[cfg(feature = "python-extension")]
#[pyclass(frozen)]
struct FlatParser {
    core: CoreFlatParser,
}

#[cfg(feature = "python-extension")]
#[pymethods]
impl FlatParser {
    #[new]
    fn new(specs: Vec<FieldSpec>) -> PyResult<Self> {
        let core = CoreFlatParser::new(specs).map_err(PyValueError::new_err)?;
        Ok(Self { core })
    }

    /// Return (assignments, unknown_args, fallback_reason).
    ///
    /// A non-None fallback reason asks Python to re-run the canonical argparse
    /// path. The fast path only claims argv shapes whose behavior is simple and
    /// exact; help, abbreviations, exotic missing-value cases, and parse errors
    /// stay owned by argparse.
    fn parse(&self, args: Vec<String>) -> ParseOutput {
        self.core.parse(&args)
    }
}

#[cfg(feature = "python-extension")]
#[pyclass(frozen)]
struct CompletionIndex {
    core: CoreCompletionIndex,
}

#[cfg(feature = "python-extension")]
#[pymethods]
impl CompletionIndex {
    #[new]
    fn new(
        option_specs: Vec<CompletionOptionSpec>,
        command_specs: Vec<CompletionCommandSpec>,
    ) -> Self {
        Self {
            core: CoreCompletionIndex::new(option_specs, command_specs),
        }
    }

    fn complete(&self, args_before: Vec<String>, prefix: String) -> Option<CompletionResult> {
        self.core.complete(&args_before, &prefix)
    }

    fn complete_values(&self, args_before: Vec<String>, prefix: String) -> Option<Vec<String>> {
        self.core.complete_values(&args_before, &prefix)
    }

    fn route(&self, args: Vec<String>) -> Option<(Vec<String>, usize)> {
        self.core.route(&args)
    }
}

#[cfg(feature = "python-extension")]
#[pyfunction]
fn backend_info() -> (&'static str, u32) {
    ("kwconf-cli-core", 3)
}

#[cfg(feature = "python-extension")]
#[pyfunction]
fn backend_capabilities() -> Vec<&'static str> {
    vec![
        "flat-parse",
        "nested-static-parse",
        "static-completion",
        "static-completion-values",
        "modal-static-completion",
        "modal-static-route",
        "abi3-py310",
    ]
}

#[cfg(feature = "python-extension")]
#[pymodule]
fn _kwconf_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<FlatParser>()?;
    m.add_class::<CompletionIndex>()?;
    m.add_function(wrap_pyfunction!(backend_info, m)?)?;
    m.add_function(wrap_pyfunction!(backend_capabilities, m)?)?;
    Ok(())
}
