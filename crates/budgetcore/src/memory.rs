use std::{
    collections::HashMap,
    sync::{Mutex, MutexGuard, PoisonError},
};

use uuid::Uuid;

use crate::store::{BudgetError, BudgetStore, BudgetView, ReservationId};

#[derive(Debug, Default)]
struct State {
    budgets: HashMap<String, Budget>,
    reservations: HashMap<ReservationId, Reservation>,
}

impl State {
    fn budget_mut(&mut self, key: &str) -> Result<&mut Budget, BudgetError> {
        self.budgets
            .get_mut(key)
            .ok_or_else(|| BudgetError::UnknownKey(key.to_owned()))
    }

    fn issue_id(&self) -> ReservationId {
        loop {
            let id = ReservationId(Uuid::new_v4());
            if !self.reservations.contains_key(&id) {
                return id;
            }
        }
    }
}

/// What a live reservation holds on part of a budget.
#[derive(Debug)]
struct Reservation {
    key: String,
    amount: i64,
}

#[derive(Debug, Default)]
pub struct InMemoryStore {
    state: Mutex<State>,
}

impl InMemoryStore {
    pub fn new() -> Self {
        Self::default()
    }

    /// Lock the map. If another thread panicked while holding the lock
    /// carry on with the data anyway: every `State` method checks before it
    /// mutates, so a panic can't leave a state half-updated
    fn state(&self) -> MutexGuard<'_, State> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl BudgetStore for InMemoryStore {
    fn set_limit(&self, key: &str, limit: i64) -> Result<(), BudgetError> {
        if limit < 0 {
            return Err(BudgetError::InvalidAmount);
        }
        self.state()
            .budgets
            .entry(key.to_owned())
            .and_modify(|b| b.limit = limit)
            .or_insert(Budget {
                limit,
                committed: 0,
                reserved: 0,
            });

        Ok(())
    }

    fn reserve(&self, key: &str, amount: i64) -> Result<ReservationId, BudgetError> {
        let mut state = self.state();

        state.budget_mut(key)?.try_reserve(amount)?;

        let id = state.issue_id();
        state.reservations.insert(
            id,
            Reservation {
                key: key.to_owned(),
                amount,
            },
        );
        Ok(id)
    }

    fn commit(&self, id: ReservationId, actual: i64) -> Result<(), BudgetError> {
        let mut guard = self.state();
        let state = &mut *guard;

        let reservation = state
            .reservations
            .get(&id)
            .ok_or(BudgetError::UnknownReservation(id))?;

        state
            .budgets
            .get_mut(&reservation.key)
            .expect("held reservation's budget must exist")
            .try_commit(reservation.amount, actual)?;

        // Only reached on success.
        state.reservations.remove(&id);
        Ok(())
    }

    fn release(&self, id: ReservationId) -> Result<(), BudgetError> {
        let mut state = self.state();
        let reservation = state
            .reservations
            .remove(&id)
            .ok_or(BudgetError::UnknownReservation(id))?;

        state
            .budget_mut(&reservation.key)
            .expect("held reservation's budget must exist")
            .release(reservation.amount);
        Ok(())
    }

    fn view(&self, key: &str) -> Result<BudgetView, BudgetError> {
        self.state()
            .budgets
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
    fn release_frees_full_amount() {
        let mut budget = get_budget(10, 5, 5);
        budget.release(5);
        assert_eq!(budget.reserved, 0);
        assert_eq!(budget.committed, 5);
        assert_eq!(budget.available(), 5);
    }
}
