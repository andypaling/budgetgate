use std::{
    collections::HashMap,
    sync::{Mutex, MutexGuard, PoisonError},
};

use crate::store::{BudgetError, BudgetStore, BudgetView, CommitError, Reservation};

#[derive(Debug, Default)]
pub struct InMemoryStore {
    budgets: Mutex<HashMap<String, Budget>>,
}

impl InMemoryStore {
    pub fn new() -> Self {
        Self::default()
    }

    /// Lock the map. If another thread panicked while holding the lock
    /// carry on with the data anyway: every `Budget` method checks before it
    /// mutates, so a panic can't leave a budget half-updated
    fn budgets(&self) -> MutexGuard<'_, HashMap<String, Budget>> {
        self.budgets.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl BudgetStore for InMemoryStore {
    fn set_limit(&self, key: &str, limit: i64) -> Result<(), BudgetError> {
        if limit < 0 {
            return Err(BudgetError::InvalidAmount);
        }
        self.budgets()
            .entry(key.to_owned())
            .and_modify(|b| b.limit = limit)
            .or_insert(Budget {
                limit,
                committed: 0,
                reserved: 0,
            });

        Ok(())
    }

    fn reserve(&self, key: &str, amount: i64) -> Result<crate::store::Reservation, BudgetError> {
        let mut budgets = self.budgets();
        let budget = budgets
            .get_mut(key)
            .ok_or_else(|| BudgetError::UnknownKey(key.to_owned()))?;

        budget.try_reserve(amount)?;
        Ok(Reservation::new(key.to_owned(), amount))
    }

    fn commit(
        &self,
        r: crate::store::Reservation,
        actual: i64,
    ) -> Result<(), crate::store::CommitError> {
        let mut budgets = self.budgets();

        let Some(budget) = budgets.get_mut(r.key()) else {
            return Err(CommitError {
                error: BudgetError::UnknownKey(r.key().to_owned()),
                reservation: r,
            });
        };

        budget
            .try_commit(r.amount(), actual)
            .map_err(|err| CommitError {
                reservation: r,
                error: err,
            })
    }

    fn release(&self, r: crate::store::Reservation) -> Result<(), BudgetError> {
        let mut budgets = self.budgets();

        let Some(budget) = budgets.get_mut(r.key()) else {
            return Err(BudgetError::UnknownKey(r.key().to_owned()));
        };

        budget.release(r.amount());
        Ok(())
    }

    fn view(&self, key: &str) -> Result<BudgetView, BudgetError> {
        self.budgets()
            .get(key)
            .map(Budget::to_view)
            .ok_or_else(|| BudgetError::UnknownKey(key.to_owned()))
    }
}

#[derive(Debug)]
struct Budget {
    limit: i64,
    committed: i64,
    reserved: i64,
}

impl Budget {
    /// Committed plus reserved - can't overflow
    fn used(&self) -> i64 {
        self.committed
            .checked_add(self.reserved)
            .expect("committed + reserved overflowed i64")
    }

    fn available(&self) -> i64 {
        (self.limit - self.used()).max(0)
    }

    fn to_view(&self) -> BudgetView {
        BudgetView {
            limit: self.limit,
            used: self.used(),
            committed: self.committed,
            reserved: self.reserved,
        }
    }

    fn try_reserve(&mut self, amount: i64) -> Result<(), BudgetError> {
        let available = self.available();

        if amount <= 0 {
            Err(BudgetError::InvalidAmount)
        } else if amount > available {
            Err(BudgetError::Exceeded {
                requested: amount,
                available,
            })
        } else {
            self.reserved += amount;
            Ok(())
        }
    }

    fn try_commit(&mut self, amount: i64, actual: i64) -> Result<(), BudgetError> {
        if !(0..=amount).contains(&actual) {
            return Err(BudgetError::InvalidAmount);
        }

        debug_assert!(
            amount <= self.reserved,
            "commit of {amount}, but only {} reserved",
            self.reserved
        );

        self.reserved -= amount;
        self.committed += actual;
        Ok(())
    }

    fn release(&mut self, amount: i64) {
        debug_assert!(
            amount <= self.reserved,
            "release of {amount} but only {} reserved",
            self.reserved
        );
        self.reserved -= amount;
    }
}
