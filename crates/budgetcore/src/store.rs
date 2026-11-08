use std::{error::Error, fmt};

use uuid::Uuid;

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

/// Identifies one live reservation. A random UUID v4,
/// so IDs don't repeat themselves across stores.
#[derive(Copy, Clone, Hash, Debug, PartialEq, Eq)]
pub struct ReservationId(pub(crate) Uuid);

impl From<Uuid> for ReservationId {
    fn from(uuid: Uuid) -> Self {
        Self(uuid)
    }
}

impl From<ReservationId> for Uuid {
    fn from(id: ReservationId) -> Self {
        id.0
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
    /// No live reservation has this ID.
    /// It was never issued or it has been committed / released.
    UnknownReservation(ReservationId),
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
            BudgetError::UnknownReservation(id) => {
                write!(f, "no live reservation with id {}", id.0)
            }
        }
    }
}

impl Error for BudgetError {}

/// Shared budgets.
///
/// No `reserve` ever takes `used` past `limit`.
/// `set_limit` may lower a limit below current usage; existing reservations
/// and commits stand, and new reserves fail until `used` drops below `limit`.
pub trait BudgetStore: Send + Sync {
    /// Create or change a limit (>= 0). Always allowed, even below current usage
    ///
    /// Errors: `InvalidAmount` if `limit < 0`
    fn set_limit(&self, key: &str, limit: i64) -> Result<(), BudgetError>;

    /// Reserve `amount` (> 0) if `used + amount <= limit`, and return an ID
    /// for the hold. The hold lasts until it is committed or released.
    ///
    /// Errors: `UnknownKey`, `InvalidAmount` if `amount <= 0`, `Exceeded`.
    fn reserve(&self, key: &str, amount: i64) -> Result<ReservationId, BudgetError>;

    /// Settle a reservation: `actual` (0..=amount) becomes committed and the
    /// rest is released. On error nothing changes and the ID stays valid,
    /// so the caller can retry or release.
    ///
    /// Errors: `UnknownReservation`, `InvalidAmount` if `actual` is out of range.
    fn commit(&self, id: ReservationId, actual: i64) -> Result<(), BudgetError>;

    /// Give the whole reservation back.
    ///
    /// Errors: `UnknownReservation`
    fn release(&self, id: ReservationId) -> Result<(), BudgetError>;

    /// Current state of one budget
    ///
    /// Errors: `UnknownKey`
    fn view(&self, key: &str) -> Result<BudgetView, BudgetError>;
}
