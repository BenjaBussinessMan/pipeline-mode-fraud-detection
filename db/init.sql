CREATE TABLE IF NOT EXISTS transactions (
    transaction_id    TEXT PRIMARY KEY,
    account_id        TEXT             NOT NULL,
    amount            DOUBLE PRECISION NOT NULL CHECK (amount > 0),
    currency          CHAR(3)          NOT NULL,
    merchant_category TEXT             NOT NULL,
    country           CHAR(2)          NOT NULL,
    ts                TIMESTAMPTZ      NOT NULL,
    score             DOUBLE PRECISION NOT NULL,
    is_fraud          BOOLEAN          NOT NULL,
    reasons           JSONB            NOT NULL DEFAULT '[]',
    processed_at      TIMESTAMPTZ      NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_transactions_account_ts ON transactions (account_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_flagged ON transactions (ts DESC) WHERE is_fraud;

CREATE TABLE IF NOT EXISTS account_profiles (
    account_id   TEXT PRIMARY KEY,
    tx_count     INTEGER            NOT NULL DEFAULT 0,
    mean         DOUBLE PRECISION   NOT NULL DEFAULT 0,
    m2           DOUBLE PRECISION   NOT NULL DEFAULT 0,
    last_country CHAR(2),
    last_ts      DOUBLE PRECISION,
    recent       DOUBLE PRECISION[] NOT NULL DEFAULT '{}',
    updated_at   TIMESTAMPTZ        NOT NULL DEFAULT now()
);
