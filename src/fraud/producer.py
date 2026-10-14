"""Transaction simulator that publishes a realistic stream with injected fraud."""

import logging
import random
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from confluent_kafka import Producer

from fraud.config import Settings, get_settings
from fraud.schemas import Transaction

logger = logging.getLogger("fraud.producer")

COUNTRIES = ["US", "MX", "CO", "ES", "BR", "AR"]
CATEGORIES = ["grocery", "restaurant", "fuel", "retail", "travel", "utilities"]
RISKY = ["crypto", "gambling", "wire_transfer"]
ACCOUNTS = 40


class TransactionGenerator:
    def __init__(
        self,
        fraud_ratio: float,
        seed: int | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._clock = clock
        self._rng = random.Random(seed)
        self._fraud_ratio = fraud_ratio
        self._home = {f"acc-{i:03d}": self._rng.choice(COUNTRIES) for i in range(ACCOUNTS)}
        self._base = {a: self._rng.uniform(20, 120) for a in self._home}

    def _normal(self, account: str) -> Transaction:
        amount = max(1.0, self._rng.gauss(self._base[account], self._base[account] * 0.3))
        return self._build(account, round(amount, 2), self._rng.choice(CATEGORIES), self._home[account])

    def _build(self, account: str, amount: float, category: str, country: str) -> Transaction:
        return Transaction(
            transaction_id=str(uuid.uuid4()),
            account_id=account,
            amount=amount,
            merchant_category=category,
            country=country,
            timestamp=self._clock(),
        )

    def _fraud(self, account: str) -> list[Transaction]:
        kind = self._rng.choice(["amount", "geo", "burst"])
        home = self._home[account]
        if kind == "amount":
            return [self._build(account, round(self._base[account] * self._rng.uniform(40, 80), 2),
                                self._rng.choice(RISKY), home)]
        if kind == "geo":
            far = self._rng.choice([c for c in COUNTRIES if c != home])
            return [self._build(account, round(self._base[account] * 15, 2),
                                self._rng.choice(RISKY), far)]
        return [self._build(account, round(self._rng.uniform(5, 30), 2), "crypto", home)
                for _ in range(8)]

    def next_batch(self) -> list[Transaction]:
        account = self._rng.choice(list(self._home))
        if self._rng.random() < self._fraud_ratio:
            return self._fraud(account)
        return [self._normal(account)]


def run(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    producer = Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})
    generator = TransactionGenerator(settings.producer_fraud_ratio)
    delay = 1.0 / settings.producer_rate_per_second
    sent = 0

    try:
        while True:
            for tx in generator.next_batch():
                producer.produce(
                    settings.kafka_topic,
                    key=tx.account_id,
                    value=tx.model_dump_json(),
                )
                sent += 1
            producer.poll(0)
            if sent % 100 == 0:
                logger.info("published %d transactions", sent)
            time.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        producer.flush(10)


if __name__ == "__main__":
    run()
