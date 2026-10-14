from datetime import datetime, timezone
from typing import Any, Protocol

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from fraud.scoring import AccountProfile
from fraud.schemas import ScoreResult, Transaction


class Repository(Protocol):
    def ping(self) -> bool: ...

    def get_profile(self, account_id: str) -> AccountProfile | None: ...

    def save_result(
        self, tx: Transaction, result: ScoreResult, profile: AccountProfile
    ) -> bool:
        """Persist transaction and profile atomically. False if already processed."""
        ...

    def list_flagged(self, limit: int = 50) -> list[dict[str, Any]]: ...

    def stats(self) -> dict[str, Any]: ...


def _stats(total: int, flagged: int) -> dict[str, Any]:
    return {
        "total_transactions": total,
        "flagged_transactions": flagged,
        "fraud_rate": round(flagged / total, 4) if total else 0.0,
    }


class PostgresRepository:
    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 5) -> None:
        self._pool = ConnectionPool(dsn, min_size=min_size, max_size=max_size, open=False)

    def open(self) -> None:
        self._pool.open(wait=True, timeout=30)

    def close(self) -> None:
        self._pool.close()

    def ping(self) -> bool:
        try:
            with self._pool.connection() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def get_profile(self, account_id: str) -> AccountProfile | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT tx_count, mean, m2, last_country, last_ts, recent "
                "FROM account_profiles WHERE account_id = %s",
                (account_id,),
            ).fetchone()
        if row is None:
            return None
        count, mean, m2, last_country, last_ts, recent = row
        return AccountProfile(
            account_id=account_id,
            count=count,
            mean=mean,
            m2=m2,
            last_country=last_country,
            last_ts=last_ts,
            recent=tuple(recent or ()),
        )

    def save_result(
        self, tx: Transaction, result: ScoreResult, profile: AccountProfile
    ) -> bool:
        with self._pool.connection() as conn:
            with conn.transaction():
                inserted = conn.execute(
                    "INSERT INTO transactions (transaction_id, account_id, amount, currency, "
                    "merchant_category, country, ts, score, is_fraud, reasons) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (transaction_id) DO NOTHING",
                    (
                        tx.transaction_id,
                        tx.account_id,
                        tx.amount,
                        tx.currency,
                        tx.merchant_category,
                        tx.country.upper(),
                        tx.timestamp,
                        result.score,
                        result.is_fraud,
                        Jsonb(result.reasons),
                    ),
                ).rowcount
                if inserted == 0:
                    return False
                conn.execute(
                    "INSERT INTO account_profiles (account_id, tx_count, mean, m2, "
                    "last_country, last_ts, recent) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (account_id) DO UPDATE SET tx_count = EXCLUDED.tx_count, "
                    "mean = EXCLUDED.mean, m2 = EXCLUDED.m2, "
                    "last_country = EXCLUDED.last_country, last_ts = EXCLUDED.last_ts, "
                    "recent = EXCLUDED.recent, updated_at = now()",
                    (
                        profile.account_id,
                        profile.count,
                        profile.mean,
                        profile.m2,
                        profile.last_country,
                        profile.last_ts,
                        list(profile.recent),
                    ),
                )
        return True

    def list_flagged(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            cur = conn.execute(
                "SELECT transaction_id, account_id, amount, currency, merchant_category, "
                "country, ts, score, reasons FROM transactions "
                "WHERE is_fraud ORDER BY ts DESC LIMIT %s",
                (limit,),
            )
            columns = [c.name for c in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

    def stats(self) -> dict[str, Any]:
        with self._pool.connection() as conn:
            total, flagged = conn.execute(
                "SELECT count(*), count(*) FILTER (WHERE is_fraud) FROM transactions"
            ).fetchone()
        return _stats(total, flagged)


class InMemoryRepository:
    """Test double and local fallback with the same contract as PostgresRepository."""

    def __init__(self) -> None:
        self.transactions: dict[str, dict[str, Any]] = {}
        self.profiles: dict[str, AccountProfile] = {}

    def ping(self) -> bool:
        return True

    def get_profile(self, account_id: str) -> AccountProfile | None:
        return self.profiles.get(account_id)

    def save_result(
        self, tx: Transaction, result: ScoreResult, profile: AccountProfile
    ) -> bool:
        if tx.transaction_id in self.transactions:
            return False
        self.transactions[tx.transaction_id] = {
            "transaction_id": tx.transaction_id,
            "account_id": tx.account_id,
            "amount": tx.amount,
            "currency": tx.currency,
            "merchant_category": tx.merchant_category,
            "country": tx.country.upper(),
            "ts": tx.timestamp,
            "score": result.score,
            "is_fraud": result.is_fraud,
            "reasons": result.reasons,
            "processed_at": datetime.now(timezone.utc),
        }
        self.profiles[profile.account_id] = profile
        return True

    def list_flagged(self, limit: int = 50) -> list[dict[str, Any]]:
        flagged = [t for t in self.transactions.values() if t["is_fraud"]]
        flagged.sort(key=lambda t: t["ts"], reverse=True)
        return flagged[:limit]

    def stats(self) -> dict[str, Any]:
        flagged = sum(1 for t in self.transactions.values() if t["is_fraud"])
        return _stats(len(self.transactions), flagged)
