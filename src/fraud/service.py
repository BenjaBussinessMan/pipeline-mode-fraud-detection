from fraud.repository import Repository
from fraud.schemas import ScoreResult, Transaction
from fraud.scoring import AccountProfile, ScoringEngine


def score_only(tx: Transaction, repo: Repository, engine: ScoringEngine) -> ScoreResult:
    """Dry run: score against the stored profile without changing any state."""
    profile = repo.get_profile(tx.account_id) or AccountProfile(tx.account_id)
    return engine.score(tx, profile)


def process_transaction(
    tx: Transaction, repo: Repository, engine: ScoringEngine
) -> ScoreResult:
    """Score, then persist the transaction and the updated profile atomically.

    Re-delivery of the same transaction_id is a no-op, which makes the Kafka
    consumer safe under at-least-once delivery.
    """
    profile = repo.get_profile(tx.account_id) or AccountProfile(tx.account_id)
    result = engine.score(tx, profile)
    repo.save_result(tx, result, engine.update_profile(profile, tx, result))
    return result
