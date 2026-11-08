//! Contract tests for `BudgetStore`, through the public API only.

use std::{
    sync::{Arc, Barrier},
    thread,
};

use budgetcore::{BudgetError, BudgetStore, BudgetView, InMemoryStore, ReservationId};

/// A store with one budget already set up.
fn store_with(key: &str, limit: i64) -> InMemoryStore {
    let store = InMemoryStore::new();
    store.set_limit(key, limit).unwrap();
    store
}

#[test]
fn unknown_key_fails_closed() {
    let store = store_with("test_key", 10);
    let before_view = store.view("test_key").unwrap();

    assert_eq!(
        store.reserve("unknown", 5),
        Err(BudgetError::UnknownKey("unknown".into()))
    );
    assert_eq!(
        store.view("unknown"),
        Err(BudgetError::UnknownKey("unknown".into()))
    );

    let after_view = store.view("test_key").unwrap();
    assert_eq!(before_view, after_view);
}

#[test]
fn set_limit_creates_empty_budget() {
    let store = InMemoryStore::new();

    store.set_limit("test_key", 10).unwrap();
    assert_eq!(
        store.view("test_key").unwrap(),
        BudgetView {
            limit: 10,
            used: 0,
            committed: 0,
            reserved: 0
        }
    )
}

#[test]
fn set_limit_rejects_negative_for_new_key() {
    let store = InMemoryStore::new();
    assert_eq!(
        store.set_limit("test_key", -1),
        Err(BudgetError::InvalidAmount)
    );
    assert_eq!(
        store.view("test_key"),
        Err(BudgetError::UnknownKey("test_key".into()))
    );
}

#[test]
fn set_limit_rejects_negative_for_existing_key() {
    let store = store_with("test_key", 10);
    assert_eq!(
        store.set_limit("test_key", -1),
        Err(BudgetError::InvalidAmount)
    );
    assert_eq!(
        store.view("test_key").unwrap(),
        BudgetView {
            limit: 10,
            used: 0,
            committed: 0,
            reserved: 0
        },
    );
}

#[test]
fn set_limit_update_keeps_usage() {
    let store = store_with("test_key", 10);

    let id1 = store.reserve("test_key", 3).unwrap();
    store.commit(id1, 3).unwrap();
    let _id2 = store.reserve("test_key", 2).unwrap();

    store.set_limit("test_key", 5).unwrap();

    assert_eq!(
        store.view("test_key").unwrap(),
        BudgetView {
            limit: 5,
            used: 5,
            committed: 3,
            reserved: 2
        }
    );
}

#[test]
fn reserve_then_commit_frees_unused() {
    let store = store_with("test_key", 10);

    // Hold the whole budget.
    let id1 = store.reserve("test_key", 10).unwrap();
    assert_eq!(
        store.reserve("test_key", 1),
        Err(BudgetError::Exceeded {
            requested: 1,
            available: 0
        })
    );

    // Settle less than what was reserved.
    store.commit(id1, 6).unwrap();
    assert_eq!(
        store.view("test_key").unwrap(),
        BudgetView {
            limit: 10,
            used: 6,
            committed: 6,
            reserved: 0
        }
    );

    // The unused 4 is available again.
    let _id2 = store.reserve("test_key", 4).unwrap();
    assert_eq!(
        store.reserve("test_key", 1),
        Err(BudgetError::Exceeded {
            requested: 1,
            available: 0
        })
    );
}

#[test]
fn reserve_then_release_restores_budget() {
    let store = store_with("test_key", 10);
    let id1 = store.reserve("test_key", 10).unwrap();

    store.release(id1).unwrap();

    assert_eq!(
        store.view("test_key").unwrap(),
        BudgetView {
            limit: 10,
            used: 0,
            committed: 0,
            reserved: 0,
        }
    );

    // The budget is usable again
    let _id2 = store
        .reserve("test_key", 10)
        .expect("full budget should be reservable after release");
}

#[test]
fn failed_commit_keeps_reservation_live() {
    let store = store_with("test_key", 10);
    let id = store.reserve("test_key", 10).unwrap();
    assert_eq!(
        store.commit(id, 11).unwrap_err(),
        BudgetError::InvalidAmount
    );

    // The failed commit didn't reach the store.
    assert_eq!(
        store.view("test_key").unwrap(),
        BudgetView {
            limit: 10,
            used: 10,
            committed: 0,
            reserved: 10,
        }
    );

    // The ID is still live: releasing it frees the budget.
    store.release(id).unwrap();
    assert_eq!(
        store.view("test_key").unwrap(),
        BudgetView {
            limit: 10,
            used: 0,
            committed: 0,
            reserved: 0,
        }
    );
}

#[test]
fn lowered_limit_blocks_new_reserves_until_usage_drops() {
    let store = store_with("test_key", 10);
    let id1 = store.reserve("test_key", 10).unwrap();
    store.set_limit("test_key", 5).unwrap();

    assert_eq!(
        store.view("test_key").unwrap(),
        BudgetView {
            limit: 5,
            used: 10,
            committed: 0,
            reserved: 10,
        }
    );
    assert_eq!(
        store.reserve("test_key", 5).unwrap_err(),
        BudgetError::Exceeded {
            requested: 5,
            available: 0
        }
    );

    store.release(id1).unwrap();
    let _id2 = store.reserve("test_key", 3).unwrap();

    assert_eq!(
        store.view("test_key").unwrap(),
        BudgetView {
            limit: 5,
            used: 3,
            committed: 0,
            reserved: 3
        }
    );

    // Only 2 available, proves the limit is 5, not the old 10
    assert_eq!(
        store.reserve("test_key", 3).unwrap_err(),
        BudgetError::Exceeded {
            requested: 3,
            available: 2
        }
    );
}

#[test]
fn keys_are_independent() {
    let store = store_with("a", 10);
    store.set_limit("b", 3).unwrap();

    let _ida = store.reserve("a", 10).unwrap();

    assert_eq!(
        store.view("a").unwrap(),
        BudgetView {
            limit: 10,
            used: 10,
            committed: 0,
            reserved: 10
        }
    );

    assert_eq!(
        store.view("b").unwrap(),
        BudgetView {
            limit: 3,
            used: 0,
            committed: 0,
            reserved: 0
        }
    );

    let _idb = store.reserve("b", 3).unwrap();

    assert_eq!(
        store.view("b").unwrap(),
        BudgetView {
            limit: 3,
            used: 3,
            committed: 0,
            reserved: 3
        }
    );
}

fn reserve_ones(store: &InMemoryStore, key: &str, attempts: usize) -> Vec<ReservationId> {
    let mut won = Vec::new();
    for _ in 0..attempts {
        match store.reserve(key, 1) {
            Ok(id) => won.push(id),
            Err(e) => {
                assert!(
                    matches!(e, BudgetError::Exceeded { .. }),
                    "unexpected error: {e}"
                )
            }
        }
    }
    won
}

#[test]
fn concurrent_reserves_never_exceed_limit() {
    const LIMIT: i64 = 100;
    const THREADS: usize = 8;
    const ATTEMPTS_PER_THREAD: usize = 50;

    let store = Arc::new(store_with("test_key", LIMIT));
    let barrier = Arc::new(Barrier::new(THREADS));

    let handles: Vec<_> = (0..THREADS)
        .map(|_| {
            let store = Arc::clone(&store);
            let barrier = Arc::clone(&barrier);
            thread::spawn(move || {
                barrier.wait();
                reserve_ones(&store, "test_key", ATTEMPTS_PER_THREAD)
            })
        })
        .collect();

    let won: Vec<_> = handles
        .into_iter()
        .flat_map(|handle| handle.join().unwrap())
        .collect();

    assert_eq!(won.len(), usize::try_from(LIMIT).unwrap());
    assert_eq!(
        store.view("test_key").unwrap(),
        BudgetView {
            limit: LIMIT,
            used: LIMIT,
            committed: 0,
            reserved: LIMIT,
        }
    );
}

#[test]
fn double_commit_fails() {
    let store = store_with("test_key", 10);
    let id = store.reserve("test_key", 10).unwrap();
    store.commit(id, 6).unwrap();
    let before_view = store.view("test_key").unwrap();

    assert_eq!(
        store.commit(id, 6),
        Err(BudgetError::UnknownReservation(id))
    );

    assert_eq!(store.view("test_key").unwrap(), before_view);
}

#[test]
fn release_after_commit_fails() {
    let store = store_with("test_key", 10);
    let id = store.reserve("test_key", 10).unwrap();
    store.commit(id, 6).unwrap();
    let before_view = store.view("test_key").unwrap();

    assert_eq!(store.release(id), Err(BudgetError::UnknownReservation(id)));
    assert_eq!(store.view("test_key").unwrap(), before_view);
}

#[test]
fn id_from_another_store_fails() {
    let store_a = store_with("test_key", 10);
    let store_b = store_with("test_key", 10);

    let id_a = store_a.reserve("test_key", 6).unwrap();
    let _id_b = store_b.reserve("test_key", 4).unwrap();

    assert_eq!(
        store_b.commit(id_a, 5),
        Err(BudgetError::UnknownReservation(id_a))
    );
    assert_eq!(
        store_b.view("test_key").unwrap(),
        BudgetView {
            limit: 10,
            used: 4,
            committed: 0,
            reserved: 4
        }
    );
}
