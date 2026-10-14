from datetime import datetime, timezone

from fraud.scoring import AccountProfile

from conftest import NOON, make_tx, seasoned_profile


def test_normal_transaction_is_not_flagged(engine):
    result = engine.score(make_tx(amount=52.0), seasoned_profile())

    assert result.score == 0.0
    assert not result.is_fraud
    assert result.reasons == []


def test_amount_far_above_mean_is_flagged(engine):
    result = engine.score(make_tx(amount=500.0), seasoned_profile())

    assert result.score == 1.0
    assert result.is_fraud
    assert any("standard deviations" in r for r in result.reasons)


def test_cold_start_high_amount_is_suspicious_but_not_fraud_alone(engine):
    result = engine.score(make_tx(amount=6000.0), AccountProfile("acc-1"))

    assert result.score == 0.5
    assert not result.is_fraud


def test_cold_start_small_amount_is_clean(engine):
    result = engine.score(make_tx(amount=100.0), AccountProfile("acc-1"))

    assert result.score == 0.0


def test_velocity_burst_raises_score(engine):
    now = NOON.timestamp()
    profile = seasoned_profile(recent=tuple(now - i for i in range(1, 8)), last_ts=now - 1)

    result = engine.score(make_tx(), profile)

    assert result.score > 0.5
    assert any("transactions in" in r for r in result.reasons)


def test_old_transactions_do_not_count_as_burst(engine):
    now = NOON.timestamp()
    profile = seasoned_profile(recent=tuple(now - 600 - i for i in range(8)))

    assert engine.score(make_tx(), profile).score == 0.0


def test_country_change_within_an_hour_is_impossible_travel(engine):
    now = NOON.timestamp()
    profile = seasoned_profile(last_country="US", last_ts=now - 600)

    result = engine.score(make_tx(country="ES"), profile)

    assert result.score == 0.6
    assert any("US->ES" in r for r in result.reasons)


def test_country_change_after_long_gap_is_mild(engine):
    profile = seasoned_profile(last_country="US", last_ts=NOON.timestamp() - 86400)

    assert engine.score(make_tx(country="ES"), profile).score == 0.15


def test_risky_category_and_night_hours_are_weak_signals(engine):
    night = datetime(2025, 3, 10, 3, 0, tzinfo=timezone.utc)
    result = engine.score(
        make_tx(merchant_category="crypto", timestamp=night),
        seasoned_profile(last_ts=night.timestamp() - 7200),
    )

    assert result.score == round(1 - 0.8 * 0.9, 4)
    assert not result.is_fraud


def test_signals_combine_beyond_threshold(engine):
    now = NOON.timestamp()
    profile = seasoned_profile(last_country="US", last_ts=now - 300)

    result = engine.score(make_tx(amount=100.0, country="ES", merchant_category="crypto"), profile)

    assert result.is_fraud
    assert len(result.reasons) >= 3


def test_threshold_is_configurable():
    from fraud.scoring import ScoringEngine

    strict = ScoringEngine(threshold=0.1)
    profile = seasoned_profile(last_country="US", last_ts=NOON.timestamp() - 86400)

    assert strict.score(make_tx(country="ES"), profile).is_fraud


def test_update_profile_tracks_running_mean_and_std(engine):
    profile = AccountProfile("acc-1")
    for i, amount in enumerate([10.0, 20.0, 30.0]):
        tx = make_tx(transaction_id=f"t{i}", amount=amount)
        profile = engine.update_profile(profile, tx, engine.score(tx, profile))

    assert profile.count == 3
    assert profile.mean == 20.0
    assert profile.std == 10.0
    assert profile.last_country == "US"


def test_flagged_transaction_does_not_poison_baseline(engine):
    profile = seasoned_profile()
    tx = make_tx(amount=5000.0)
    result = engine.score(tx, profile)

    updated = engine.update_profile(profile, tx, result)

    assert result.is_fraud
    assert updated.count == profile.count
    assert updated.mean == profile.mean
    assert updated.last_ts == NOON.timestamp()


def test_recent_window_is_bounded(engine):
    profile = AccountProfile("acc-1")
    for i in range(50):
        tx = make_tx(transaction_id=f"t{i}", amount=10.0)
        profile = engine.update_profile(profile, tx, engine.score(tx, profile))

    assert len(profile.recent) == 20
