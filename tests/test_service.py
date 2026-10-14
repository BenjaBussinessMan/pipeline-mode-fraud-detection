from fraud.service import process_transaction, score_only

from conftest import make_tx


def test_process_persists_transaction_and_profile(repo, engine):
    result = process_transaction(make_tx(), repo, engine)

    assert not result.is_fraud
    assert "tx-1" in repo.transactions
    assert repo.get_profile("acc-1").count == 1


def test_process_is_idempotent_on_redelivery(repo, engine):
    tx = make_tx()
    process_transaction(tx, repo, engine)
    process_transaction(tx, repo, engine)

    assert len(repo.transactions) == 1
    assert repo.get_profile("acc-1").count == 1


def test_fraud_is_stored_and_listed(repo, engine):
    for i in range(6):
        process_transaction(make_tx(transaction_id=f"n{i}", amount=50.0 + i), repo, engine)

    result = process_transaction(make_tx(transaction_id="big", amount=9000.0), repo, engine)

    assert result.is_fraud
    assert [t["transaction_id"] for t in repo.list_flagged()] == ["big"]
    assert repo.stats() == {
        "total_transactions": 7,
        "flagged_transactions": 1,
        "fraud_rate": round(1 / 7, 4),
    }


def test_score_only_does_not_change_state(repo, engine):
    score_only(make_tx(), repo, engine)

    assert repo.transactions == {}
    assert repo.get_profile("acc-1") is None
