"""Kafka consumer: validate, score, persist, then commit the offset.

Offsets are committed only after the result is stored (at-least-once). Duplicates
are harmless because persistence is idempotent on transaction_id.
"""

import logging
import signal
from collections.abc import Callable

from confluent_kafka import Consumer, KafkaError, Producer
from pydantic import ValidationError

from fraud.config import Settings, get_settings
from fraud.repository import PostgresRepository, Repository
from fraud.schemas import ScoreResult, Transaction
from fraud.scoring import ScoringEngine
from fraud.service import process_transaction

logger = logging.getLogger("fraud.consumer")

DeadLetter = Callable[[bytes | None, str], None]


def handle_message(
    raw: bytes | None,
    repo: Repository,
    engine: ScoringEngine,
    dead_letter: DeadLetter,
) -> ScoreResult | None:
    """Process one message. Invalid payloads go to the DLQ and return None."""
    try:
        tx = Transaction.model_validate_json(raw or b"")
    except ValidationError as exc:
        dead_letter(raw, f"invalid transaction: {exc.error_count()} validation error(s)")
        return None

    result = process_transaction(tx, repo, engine)
    if result.is_fraud:
        logger.warning(
            "fraud detected tx=%s account=%s score=%.2f reasons=%s",
            tx.transaction_id,
            tx.account_id,
            result.score,
            "; ".join(result.reasons),
        )
    return result


def _build_dead_letter(producer: Producer, topic: str) -> DeadLetter:
    def dead_letter(raw: bytes | None, error: str) -> None:
        logger.error("sending message to DLQ: %s", error)
        producer.produce(topic, value=raw, headers={"error": error})
        producer.flush(5)

    return dead_letter


def run(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    repo = PostgresRepository(settings.database_url)
    repo.open()
    engine = ScoringEngine(settings.fraud_threshold)

    consumer = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": settings.kafka_group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    dlq = Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})
    dead_letter = _build_dead_letter(dlq, settings.kafka_dlq_topic)

    running = True

    def stop(*_: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    consumer.subscribe([settings.kafka_topic])
    logger.info("consuming topic=%s group=%s", settings.kafka_topic, settings.kafka_group_id)

    try:
        while running:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    logger.error("kafka error: %s", msg.error())
                continue
            handle_message(msg.value(), repo, engine, dead_letter)
            consumer.commit(message=msg, asynchronous=False)
    finally:
        consumer.close()
        repo.close()
        logger.info("consumer stopped")


if __name__ == "__main__":
    run()
