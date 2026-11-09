import pytest
from budgetgate import Store


@pytest.fixture
def store() -> Store:
    """A store with one budget of 10 on "test_key"."""
    s = Store()
    s.set_limit("test_key", 10)
    return s
