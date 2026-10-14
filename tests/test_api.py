import pytest
from fastapi.testclient import TestClient

from fraud.api.main import create_app
from fraud.service import process_transaction

from conftest import make_tx


@pytest.fixture
def client(repo, engine):
    with TestClient(create_app(repo=repo, engine=engine)) as test_client:
        yield test_client


def payload(**overrides) -> dict:
    data = {
        "transaction_id": "tx-1",
        "account_id": "acc-1",
        "amount": 50.0,
        "currency": "USD",
        "merchant_category": "grocery",
        "country": "US",
        "timestamp": "2025-03-10T12:00:00Z",
    }
    data.update(overrides)
    return data


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reports_unavailable_database(repo, engine):
    repo.ping = lambda: False
    with TestClient(create_app(repo=repo, engine=engine)) as test_client:
        assert test_client.get("/health").status_code == 503


def test_score_clean_transaction(client):
    response = client.post("/v1/score", json=payload())

    assert response.status_code == 200
    body = response.json()
    assert body["transaction_id"] == "tx-1"
    assert body["is_fraud"] is False


def test_score_flags_large_amount_for_known_account(client, repo, engine):
    for i in range(6):
        process_transaction(make_tx(transaction_id=f"n{i}", amount=50.0 + i), repo, engine)

    response = client.post("/v1/score", json=payload(transaction_id="big", amount=9000))

    assert response.json()["is_fraud"] is True


@pytest.mark.parametrize(
    "override",
    [{"amount": -5}, {"amount": 0}, {"country": "USA"}, {"currency": "DOLLAR"}, {"account_id": ""}],
)
def test_score_rejects_invalid_payload(client, override):
    assert client.post("/v1/score", json=payload(**override)).status_code == 422


def test_flagged_endpoint_returns_only_fraud(client, repo, engine):
    for i in range(6):
        process_transaction(make_tx(transaction_id=f"n{i}", amount=50.0 + i), repo, engine)
    process_transaction(make_tx(transaction_id="big", amount=9000.0), repo, engine)

    response = client.get("/v1/transactions/flagged")

    assert response.status_code == 200
    assert [t["transaction_id"] for t in response.json()] == ["big"]


def test_flagged_limit_is_validated(client):
    assert client.get("/v1/transactions/flagged?limit=0").status_code == 422


def test_profile_found_and_not_found(client, repo, engine):
    process_transaction(make_tx(), repo, engine)

    assert client.get("/v1/accounts/acc-1/profile").json()["transactions"] == 1
    assert client.get("/v1/accounts/nope/profile").status_code == 404


def test_stats(client, repo, engine):
    process_transaction(make_tx(), repo, engine)

    assert client.get("/v1/stats").json()["total_transactions"] == 1
