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

#[cfg(test)]
mod tests {
    use super::*;

    fn get_budget(limit: i64, committed: i64, reserved: i64) -> Budget {
        Budget {
            limit,
            committed,
            reserved,
        }
    }

    #[test]
    fn available_clamps_to_zero_when_over_limit() {
        // Example state after `set_limit` lowered the limit below current usage
        let budget = get_budget(10, 8, 4);
        assert_eq!(budget.used(), 12);
        assert_eq!(budget.available(), 0);
    }

    #[test]
    fn available_is_limit_minus_used() {
        let budget = get_budget(10, 4, 4);
        assert_eq!(budget.available(), 2);
        assert_eq!(budget.used(), 8)
    }

    #[test]
    fn try_reserve_succeeds_on_exact_fit() {
        let mut budget = get_budget(10, 4, 4);
        assert_eq!(budget.try_reserve(2), Ok(()));
        assert_eq!(budget.reserved, 6);
    }

    #[test]
    fn try_reserve_fails_one_over_available() {
        let mut budget = get_budget(10, 4, 4);

        let pre_change_budget_view = budget.to_view();
        let res = budget.try_reserve(3);
        let post_change_budget_view = budget.to_view();

        assert_eq!(
            res,
            Err(BudgetError::Exceeded {
                requested: 3,
                available: 2
            })
        );
        assert_eq!(pre_change_budget_view, post_change_budget_view)
    }

    #[test]
    fn try_reserve_rejects_zero() {
        let mut budget = get_budget(10, 4, 4);

        let pre_change_budget_view = budget.to_view();
        let res = budget.try_reserve(0);
        let post_change_budget_view = budget.to_view();

        assert_eq!(res, Err(BudgetError::InvalidAmount));
        assert_eq!(pre_change_budget_view, post_change_budget_view)
    }

    #[test]
    fn try_reserve_rejects_negative() {
        let mut budget = get_budget(10, 4, 4);

        let pre_change_budget_view = budget.to_view();
        let res = budget.try_reserve(-1);
        let post_change_budget_view = budget.to_view();

        assert_eq!(res, Err(BudgetError::InvalidAmount));
        assert_eq!(pre_change_budget_view, post_change_budget_view)
    }

    #[test]
    fn try_commit_full_moves_reserved_to_committed() {
        let mut budget = get_budget(10, 5, 5);
        assert_eq!(budget.try_commit(5, 5), Ok(()));
        assert_eq!(budget.reserved, 0);
        assert_eq!(budget.committed, 10);
        assert_eq!(budget.available(), 0);
    }

    #[test]
    fn try_commit_partial_frees_the_remainder() {
        let mut budget = get_budget(10, 5, 5);
        assert_eq!(budget.try_commit(5, 3), Ok(()));
        assert_eq!(budget.reserved, 0);
        assert_eq!(budget.committed, 8);
        assert_eq!(budget.available(), 2);
    }

    #[test]
    fn try_commit_zero_frees_everything() {
        let mut budget = get_budget(10, 5, 5);
        assert_eq!(budget.try_commit(5, 0), Ok(()));
        assert_eq!(budget.reserved, 0);
        assert_eq!(budget.committed, 5);
        assert_eq!(budget.available(), 5);
    }

    #[test]
    fn try_commit_rejects_actual_over_amount() {
        let mut budget = get_budget(10, 5, 5);

        let pre_change_budget_view = budget.to_view();
        let res = budget.try_commit(2, 5);
        let post_change_budget_view = budget.to_view();

        assert_eq!(res, Err(BudgetError::InvalidAmount));
        assert_eq!(pre_change_budget_view, post_change_budget_view);
    }

    #[test]
    fn try_commit_rejects_negative_actual() {
        let mut budget = get_budget(10, 5, 5);

        let pre_change_budget_view = budget.to_view();
        let res = budget.try_commit(2, -1);
        let post_change_budget_view = budget.to_view();

        assert_eq!(res, Err(BudgetError::InvalidAmount));
        assert_eq!(pre_change_budget_view, post_change_budget_view);
    }

    #[test]
    #[cfg(debug_assertions)]
    #[should_panic(expected = "only 2 reserved")]
    fn try_commit_panics_over_reserved() {
        let mut budget = get_budget(10, 0, 2);
        let _ = budget.try_commit(5, 5);
    }

    #[test]
    fn release_frees_full_amount() {
        let mut budget = get_budget(10, 5, 5);
        budget.release(5);
        assert_eq!(budget.reserved, 0);
        assert_eq!(budget.committed, 5);
        assert_eq!(budget.available(), 5);
    }

    #[test]
    #[cfg(debug_assertions)]
    #[should_panic(expected = "release of 6 but only 5 reserved")]
    fn release_panics_over_reserved() {
        let mut budget = get_budget(10, 5, 5);
        budget.release(6);
    }
}
