from collections.abc import AsyncIterator

import pytest
from budgetgate import Store
from budgetgate.gateway import Gateway


@pytest.fixture
def store() -> Store:
    """A store with one budget of 10 on "test_key"."""
    s = Store()
    s.set_limit("test_key", 10)
    return s


@pytest.fixture
async def gateway(store: Store) -> AsyncIterator[Gateway]:
    """A running gateway on a free port, serving the store fixture."""
    async with Gateway(store, port=0) as gw:
        yield gw
