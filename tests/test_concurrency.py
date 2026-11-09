import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from budgetgate import BudgetExceeded, BudgetView, Store

LIMIT = 100
THREADS = 8
ATTEMPTS_PER_THREAD = 50


def reserve_ones(store: Store, barrier: threading.Barrier) -> list[uuid.UUID]:
    barrier.wait()
    won = []
    for _ in range(ATTEMPTS_PER_THREAD):
        try:
            won.append(store.reserve("test_key", 1))
        except BudgetExceeded:
            pass
    return won


def test_concurrent_reserves_never_exceed_limit() -> None:
    store = Store()
    store.set_limit("test_key", LIMIT)
    barrier = threading.Barrier(THREADS)

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = [pool.submit(reserve_ones, store, barrier) for _ in range(THREADS)]
        won = [reservation_id for f in futures for reservation_id in f.result()]

    assert len(won) == LIMIT
    assert len(set(won)) == LIMIT
    assert store.view("test_key") == BudgetView(
        limit=LIMIT, used=LIMIT, committed=0, reserved=LIMIT
    )
