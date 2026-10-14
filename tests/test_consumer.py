from fraud.consumer import handle_message

from conftest import make_tx


class DeadLetterSpy:
    def __init__(self):
        self.messages = []

    def __call__(self, raw, error):
        self.messages.append((raw, error))


def test_valid_message_is_processed_and_stored(repo, engine):
    spy = DeadLetterSpy()
    raw = make_tx().model_dump_json().encode()

    result = handle_message(raw, repo, engine, spy)

    assert result is not None
    assert "tx-1" in repo.transactions
    assert spy.messages == []


def test_malformed_json_goes_to_dlq(repo, engine):
    spy = DeadLetterSpy()

    result = handle_message(b"{not json", repo, engine, spy)

    assert result is None
    assert repo.transactions == {}
    assert spy.messages[0][0] == b"{not json"


def test_schema_violation_goes_to_dlq(repo, engine):
    spy = DeadLetterSpy()
    raw = make_tx().model_dump_json().replace('"amount":50.0', '"amount":-1').encode()

    assert handle_message(raw, repo, engine, spy) is None
    assert len(spy.messages) == 1


def test_empty_message_goes_to_dlq(repo, engine):
    spy = DeadLetterSpy()

    assert handle_message(None, repo, engine, spy) is None
    assert len(spy.messages) == 1


def test_redelivered_message_is_not_duplicated(repo, engine):
    spy = DeadLetterSpy()
    raw = make_tx().model_dump_json().encode()

    handle_message(raw, repo, engine, spy)
    handle_message(raw, repo, engine, spy)

    assert len(repo.transactions) == 1
