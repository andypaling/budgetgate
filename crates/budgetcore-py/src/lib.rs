use budgetcore::{BudgetError as CoreError, BudgetStore, BudgetView, InMemoryStore};
use pyo3::{create_exception, exceptions::PyException, prelude::*};
use uuid::Uuid;

create_exception!(
    _budgetcore,
    BudgetError,
    PyException,
    "Base class for all budget errors."
);
create_exception!(
    _budgetcore,
    UnknownKey,
    BudgetError,
    "No limit has been set for this key."
);
create_exception!(
    _budgetcore,
    InvalidAmount,
    BudgetError,
    "An amount or limit was out of range."
);
create_exception!(
    _budgetcore,
    BudgetExceeded,
    BudgetError,
    "The reservation would exceed the limit."
);
create_exception!(
    _budgetcore,
    UnknownReservation,
    BudgetError,
    "No live reservation has this ID."
);

fn to_py_err(err: CoreError) -> PyErr {
    let msg = err.to_string();
    match err {
        CoreError::UnknownKey(_) => UnknownKey::new_err(msg),
        CoreError::InvalidAmount => InvalidAmount::new_err(msg),
        CoreError::Exceeded { .. } => BudgetExceeded::new_err(msg),
        CoreError::UnknownReservation(_) => UnknownReservation::new_err(msg),
    }
}

#[pyclass(frozen, get_all, eq, hash, name = "BudgetView")]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
struct PyBudgetView {
    limit: i64,
    used: i64,
    committed: i64,
    reserved: i64,
}

#[pymethods]
impl PyBudgetView {
    #[new]
    fn new(limit: i64, used: i64, committed: i64, reserved: i64) -> Self {
        Self {
            limit,
            used,
            committed,
            reserved,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "BudgetView(limit={}, used={}, committed={}, reserved={})",
            self.limit, self.used, self.committed, self.reserved,
        )
    }
}

impl From<BudgetView> for PyBudgetView {
    fn from(view: BudgetView) -> Self {
        Self {
            limit: view.limit,
            used: view.used,
            committed: view.committed,
            reserved: view.reserved,
        }
    }
}

#[pyclass(frozen)]
struct Store {
    inner: InMemoryStore,
}

#[pymethods]
impl Store {
    #[new]
    fn new() -> Self {
        Self {
            inner: InMemoryStore::new(),
        }
    }

    fn set_limit(&self, py: Python<'_>, key: &str, limit: i64) -> PyResult<()> {
        py.detach(|| self.inner.set_limit(key, limit))
            .map_err(to_py_err)
    }

    fn reserve(&self, py: Python<'_>, key: &str, amount: i64) -> PyResult<Uuid> {
        py.detach(|| self.inner.reserve(key, amount))
            .map(Uuid::from)
            .map_err(to_py_err)
    }

    fn commit(&self, py: Python<'_>, id: Uuid, actual: i64) -> PyResult<()> {
        py.detach(|| self.inner.commit(id.into(), actual))
            .map_err(to_py_err)
    }

    fn release(&self, py: Python<'_>, id: Uuid) -> PyResult<()> {
        py.detach(|| self.inner.release(id.into()))
            .map_err(to_py_err)
    }

    fn view(&self, py: Python<'_>, key: &str) -> PyResult<PyBudgetView> {
        py.detach(|| self.inner.view(key))
            .map(PyBudgetView::from)
            .map_err(to_py_err)
    }
}

#[pymodule]
mod _budgetcore {
    #[pymodule_export]
    use super::{
        BudgetError, BudgetExceeded, InvalidAmount, PyBudgetView, Store, UnknownKey,
        UnknownReservation,
    };
}
