#!/usr/bin/env python3
"""
Seed the paylane database.

Creates the schema and loads a small set of accounts and mandates so the
platform has something to work with on a cold start.

Usage:  python3 scripts/seed-db.py
Env:    DATABASE_URL (default: postgresql://paylane:paylane_dev_pw@localhost:5432/paylane)
"""
import os
import sys

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://paylane:paylane_dev_pw@localhost:5432/paylane"
)

SCHEMA = """
-- Accounts: who can send and receive money.
CREATE TABLE IF NOT EXISTS accounts (
    id           SERIAL PRIMARY KEY,
    account_ref  TEXT UNIQUE NOT NULL,
    holder_name  TEXT NOT NULL,
    ifsc         TEXT NOT NULL,
    balance_paise BIGINT NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Mandates: standing permission for a payer to pay a payee, with a cap.
CREATE TABLE IF NOT EXISTS mandates (
    id             SERIAL PRIMARY KEY,
    mandate_ref    TEXT UNIQUE NOT NULL,
    payer_ref      TEXT NOT NULL REFERENCES accounts(account_ref),
    payee_ref      TEXT NOT NULL REFERENCES accounts(account_ref),
    max_amount_paise BIGINT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Payments: the instruction. Accepted fast, settled later.
CREATE TABLE IF NOT EXISTS payments (
    id             SERIAL PRIMARY KEY,
    payment_ref    TEXT UNIQUE NOT NULL,
    idempotency_key TEXT,
    mandate_ref    TEXT REFERENCES mandates(mandate_ref),
    payer_ref      TEXT NOT NULL REFERENCES accounts(account_ref),
    payee_ref      TEXT NOT NULL REFERENCES accounts(account_ref),
    amount_paise   BIGINT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'ACCEPTED',
    failure_reason TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    settled_at     TIMESTAMPTZ
);

-- Ledger entries: double-entry. Every settled payment writes two rows.
CREATE TABLE IF NOT EXISTS ledger_entries (
    id           SERIAL PRIMARY KEY,
    payment_ref  TEXT NOT NULL,
    account_ref  TEXT NOT NULL REFERENCES accounts(account_ref),
    direction    TEXT NOT NULL CHECK (direction IN ('DEBIT', 'CREDIT')),
    amount_paise BIGINT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Audit log: append-only. Nothing updates or deletes from this table.
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    entity_ref  TEXT,
    detail      TEXT
);

CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
CREATE INDEX IF NOT EXISTS idx_ledger_payment ON ledger_entries(payment_ref);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_ref);
"""

ACCOUNTS = [
    ("ACC-1001", "Meera Nair", "PYLN0000001", 5_000_00),
    ("ACC-1002", "Ravi Shankar", "PYLN0000001", 2_500_00),
    ("ACC-1003", "Anita Desai", "PYLN0000002", 10_000_00),
    ("ACC-2001", "Bluepeak Utilities", "PYLN0000009", 0),
    ("ACC-2002", "Grand Insurance", "PYLN0000009", 0),
    ("ACC-2003", "Metro Broadband", "PYLN0000009", 0),
]

MANDATES = [
    ("MND-5001", "ACC-1001", "ACC-2001", 2_000_00),
    ("MND-5002", "ACC-1001", "ACC-2003", 1_500_00),
    ("MND-5003", "ACC-1002", "ACC-2002", 3_000_00),
    ("MND-5004", "ACC-1003", "ACC-2001", 5_000_00),
]


def main():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        for stmt in SCHEMA.split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
        print("schema ready")

        for ref, name, ifsc, bal in ACCOUNTS:
            conn.execute(
                text(
                    """INSERT INTO accounts (account_ref, holder_name, ifsc, balance_paise)
                       VALUES (:r, :n, :i, :b)
                       ON CONFLICT (account_ref) DO NOTHING"""
                ),
                {"r": ref, "n": name, "i": ifsc, "b": bal},
            )
        print(f"seeded {len(ACCOUNTS)} accounts")

        for ref, payer, payee, cap in MANDATES:
            conn.execute(
                text(
                    """INSERT INTO mandates (mandate_ref, payer_ref, payee_ref, max_amount_paise)
                       VALUES (:r, :p, :e, :c)
                       ON CONFLICT (mandate_ref) DO NOTHING"""
                ),
                {"r": ref, "p": payer, "e": payee, "c": cap},
            )
        print(f"seeded {len(MANDATES)} mandates")

        conn.execute(
            text(
                """INSERT INTO audit_log (actor, action, entity_ref, detail)
                   VALUES ('seed-script', 'SEED', NULL, 'database seeded')"""
            )
        )
    print("seed complete")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"seed failed: {e}", file=sys.stderr)
        sys.exit(1)
