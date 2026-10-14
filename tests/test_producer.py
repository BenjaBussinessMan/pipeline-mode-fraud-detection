from datetime import datetime, timedelta, timezone

from fraud.producer import TransactionGenerator
from fraud.repository import InMemoryRepository
from fraud.scoring import ScoringEngine
from fraud.service import process_transaction


def simulated_clock(step_seconds: float):
    state = {"now": datetime(2025, 3, 10, 9, 0, tzinfo=timezone.utc)}

    def clock() -> datetime:
        state["now"] += timedelta(seconds=step_seconds)
        return state["now"]

    return clock


def test_generator_is_deterministic_with_seed():
    clock = simulated_clock(1)
    a = TransactionGenerator(0.0, seed=1, clock=clock).next_batch()[0]
    b = TransactionGenerator(0.0, seed=1, clock=clock).next_batch()[0]

    assert (a.account_id, a.amount, a.country) == (b.account_id, b.amount, b.country)


def test_generated_stream_flags_some_fraud_but_mostly_clean():
    generator = TransactionGenerator(fraud_ratio=0.05, seed=7, clock=simulated_clock(30))
    repo, engine = InMemoryRepository(), ScoringEngine()

    for _ in range(1500):
        for tx in generator.next_batch():
            process_transaction(tx, repo, engine)

    stats = repo.stats()
    assert 0 < stats["fraud_rate"] < 0.2
