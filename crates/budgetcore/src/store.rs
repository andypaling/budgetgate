use std::{error::Error, fmt};

/// A snapshot of one budget.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BudgetView {
    pub limit: i64,
    /// `committed + reserved`. This is the number checked against `limit`.
    pub used: i64,
    /// Reporting only; not part of the safety check
    pub committed: i64,
    pub reserved: i64,
}

/// A hold on part of a budget. Only a store can create one.
#[derive(Debug, PartialEq, Eq)]
#[must_use = "a reservation must be committed or released, or the budget leaks"]
pub struct Reservation {
    key: String,
    amount: i64,
}

impl Reservation {
    pub(crate) fn new(key: String, amount: i64) -> Self {
        Self { key, amount }
    }

    pub fn key(&self) -> &str {
        &self.key
    }
    pub fn amount(&self) -> i64 {
        self.amount
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BudgetError {
    /// No limit has been set for this key. Fails closed.
    UnknownKey(String),
    /// `set_limit`: limit < 0
    /// `reserve`: amount <= 0
    /// `commit`: actual < 0 or actual > the reserved amount
    InvalidAmount,
    /// Reserving would take `used` past `limit`
    /// `available` is `limit - used`, clamped to 0 (it would be negative
    /// after `set_limit` lowered the limit below current usage).
    Exceeded { requested: i64, available: i64 },
}

impl fmt::Display for BudgetError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            BudgetError::UnknownKey(key) => {
                write!(f, "no limit set for the key: {key:?}")
            }
            BudgetError::InvalidAmount => write!(f, "Invalid amount"),
            BudgetError::Exceeded {
                requested,
                available,
            } => write!(
                f,
                "budget exceeded: requested: {requested:?}, available: {available:?}"
            ),
        }
    }
}

impl Error for BudgetError {}

#[derive(Debug)]
pub struct CommitError {
    pub reservation: Reservation,
    pub error: BudgetError,
}

impl fmt::Display for CommitError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "commit failed for key {:?}.", self.reservation.key(),)
    }
}

impl Error for CommitError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(&self.error)
    }
}

/// Shared budgets.
///
/// No `reserve` ever takes `used` past `limit`.
/// `set_limit` may lower a limit below current usage; existing reservations
/// and commits stand, and new reserves fail until `used` drops below `limit`.
pub trait BudgetStore: Send + Sync {
    /// Create or change a limit (>= 0). Always allowed, even below current usage
    fn set_limit(&self, key: &str, limit: i64) -> Result<(), BudgetError>;

    /// Reserve `amount` (> 0) if `used + amount <= limit`.
    fn reserve(&self, key: &str, amount: i64) -> Result<Reservation, BudgetError>;

    /// Settle a reservation: `actual` (0..=amount) becomes committed and the
    /// rest is released. On error the reservation is handed back unchanged.
    fn commit(&self, r: Reservation, actual: i64) -> Result<(), CommitError>;

    /// Give the whole reservation back. Errors if the provided reservation into in the store.
    fn release(&self, r: Reservation) -> Result<(), BudgetError>;

    /// Current state of one budget
    fn view(&self, key: &str) -> Result<BudgetView, BudgetError>;
}
