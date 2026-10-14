"""Pure scoring logic: no I/O, so it is trivial to test and reuse."""

from dataclasses import dataclass, field, replace
from datetime import timezone
from math import sqrt

from fraud.schemas import ScoreResult, Transaction

MIN_HISTORY = 5
VELOCITY_WINDOW_SECONDS = 60.0
VELOCITY_LIMIT = 5
IMPOSSIBLE_TRAVEL_SECONDS = 3600.0
COLD_START_AMOUNT = 5000.0
RISKY_CATEGORIES = frozenset({"crypto", "gambling", "wire_transfer"})
NIGHT_HOURS = range(0, 6)
RECENT_KEEP = 20


@dataclass(frozen=True)
class AccountProfile:
    account_id: str
    count: int = 0
    mean: float = 0.0
    m2: float = 0.0
    last_country: str | None = None
    last_ts: float | None = None
    recent: tuple[float, ...] = field(default_factory=tuple)

    @property
    def std(self) -> float:
        if self.count < 2:
            return 0.0
        return sqrt(self.m2 / (self.count - 1))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _amount_signal(tx: Transaction, profile: AccountProfile) -> tuple[float, str | None]:
    if profile.count < MIN_HISTORY:
        if tx.amount >= COLD_START_AMOUNT:
            return 0.5, f"amount {tx.amount:.2f} is high for an account with little history"
        return 0.0, None

    std = max(profile.std, profile.mean * 0.05, 1e-6)
    z = (tx.amount - profile.mean) / std
    signal = _clamp((z - 2.0) / 4.0)
    if signal > 0:
        return signal, f"amount is {z:.1f} standard deviations above the account mean"
    return 0.0, None


def _velocity_signal(ts: float, profile: AccountProfile) -> tuple[float, str | None]:
    in_window = sum(1 for t in profile.recent if 0 <= ts - t <= VELOCITY_WINDOW_SECONDS)
    burst = in_window + 1
    if burst >= VELOCITY_LIMIT:
        return _clamp((burst - 3) / 7), f"{burst} transactions in {VELOCITY_WINDOW_SECONDS:.0f}s"
    return 0.0, None


def _geo_signal(tx: Transaction, ts: float, profile: AccountProfile) -> tuple[float, str | None]:
    if profile.last_country is None or profile.last_ts is None:
        return 0.0, None
    if tx.country.upper() == profile.last_country:
        return 0.0, None
    if ts - profile.last_ts < IMPOSSIBLE_TRAVEL_SECONDS:
        return 0.6, f"country changed {profile.last_country}->{tx.country.upper()} within an hour"
    return 0.15, f"country changed {profile.last_country}->{tx.country.upper()}"


def _context_signals(tx: Transaction) -> list[tuple[float, str]]:
    signals = []
    if tx.merchant_category.lower() in RISKY_CATEGORIES:
        signals.append((0.2, f"risky merchant category '{tx.merchant_category}'"))
    utc_hour = tx.timestamp.astimezone(timezone.utc).hour
    if utc_hour in NIGHT_HOURS:
        signals.append((0.1, "transaction during night hours (UTC)"))
    return signals


def _to_epoch(tx: Transaction) -> float:
    ts = tx.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.timestamp()


class ScoringEngine:
    def __init__(self, threshold: float = 0.7) -> None:
        self.threshold = threshold

    def score(self, tx: Transaction, profile: AccountProfile) -> ScoreResult:
        ts = _to_epoch(tx)
        candidates = [
            _amount_signal(tx, profile),
            _velocity_signal(ts, profile),
            _geo_signal(tx, ts, profile),
        ]
        candidates.extend(_context_signals(tx))

        combined = 1.0
        reasons: list[str] = []
        for signal, reason in candidates:
            if signal > 0 and reason:
                combined *= 1.0 - signal
                reasons.append(reason)
        score = round(1.0 - combined, 4)

        return ScoreResult(
            transaction_id=tx.transaction_id,
            score=score,
            is_fraud=score >= self.threshold,
            reasons=reasons,
        )

    def update_profile(
        self, profile: AccountProfile, tx: Transaction, result: ScoreResult
    ) -> AccountProfile:
        """Return the next profile. Flagged amounts do not feed the baseline."""
        ts = _to_epoch(tx)
        recent = (*profile.recent, ts)[-RECENT_KEEP:]
        updated = replace(
            profile,
            last_country=tx.country.upper(),
            last_ts=ts,
            recent=recent,
        )
        if result.is_fraud:
            return updated

        count = profile.count + 1
        delta = tx.amount - profile.mean
        mean = profile.mean + delta / count
        m2 = profile.m2 + delta * (tx.amount - mean)
        return replace(updated, count=count, mean=mean, m2=m2)
