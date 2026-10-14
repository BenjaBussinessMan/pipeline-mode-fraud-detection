from datetime import datetime, timezone

import pytest

from fraud.repository import InMemoryRepository
from fraud.schemas import Transaction
from fraud.scoring import AccountProfile, ScoringEngine

NOON = datetime(2025, 3, 10, 12, 0, tzinfo=timezone.utc)


def make_tx(**overrides) -> Transaction:
    data = {
        "transaction_id": "tx-1",
        "account_id": "acc-1",
        "amount": 50.0,
        "currency": "USD",
        "merchant_category": "grocery",
        "country": "US",
        "timestamp": NOON,
    }
    data.update(overrides)
    return Transaction(**data)


def seasoned_profile(**overrides) -> AccountProfile:
    """Profile with stable history around 50 (std ~ 5.3)."""
    data = {
        "account_id": "acc-1",
        "count": 20,
        "mean": 50.0,
        "m2": 20 * 28.0,
        "last_country": "US",
        "last_ts": NOON.timestamp() - 7200,
        "recent": (),
    }
    data.update(overrides)
    return AccountProfile(**data)


@pytest.fixture
def engine() -> ScoringEngine:
    return ScoringEngine(threshold=0.7)


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()
