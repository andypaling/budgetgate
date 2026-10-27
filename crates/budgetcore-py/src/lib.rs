use pyo3::prelude::*;

#[pyfunction]
fn hello() -> &'static str {
    "Hello from budget core"
}

#[pymodule]
fn _budgetcore(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(hello, m)?)?;
    Ok(())
}
