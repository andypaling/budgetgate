from collections.abc import AsyncIterator

import pytest
from budgetgate import BudgetView, Store
from budgetgate.client import Client
from budgetgate.gateway import Gateway

KEY = "test_key"


@pytest.fixture
async def client(gateway: Gateway) -> AsyncIterator[Client]:
    """A connected client; closed after the test."""
    async with await Client.connect(port=gateway.port) as c:
        yield c


async def test_reserve_commit_view(client: Client) -> None:
    """A reservation and commit show up in view."""
    await client.set_limit(KEY, 25)
    reservation_id = await client.reserve(KEY, 15)
    await client.commit(reservation_id, 10)
    await client.reserve(KEY, 3)
    assert await client.view(KEY) == BudgetView(
        limit=25,
        used=13,
        committed=10,
        reserved=3,
    )


async def test_view_matches_local_store(client: Client, store: Store):
    await client.set_limit(KEY, 25)
    rid_1 = await client.reserve(KEY, 15)
    rid_2 = await client.reserve(KEY, 5)
    await client.commit(reservation_id=rid_1, actual=10)
    await client.release(reservation_id=rid_2)

    assert await client.view(KEY) == store.view(KEY)
