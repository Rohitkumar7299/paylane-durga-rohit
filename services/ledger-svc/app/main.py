"""
ledger-svc — accounts and the double-entry ledger.

The system of record for money. Every settled payment produces exactly two
ledger entries: a DEBIT on the payer and a CREDIT on the payee. The two must
always sum to zero across a payment — that invariant is what reconciliation
checks.

    GET  /accounts                  list accounts with balances
    GET  /accounts/{ref}            fetch one account
    GET  /accounts/{ref}/entries    ledger entries for an account
    GET  /reconcile                 check the double-entry invariant
    GET  /health                    liveness + dependency check
    GET  /metrics                   Prometheus metrics
"""
import os
from contextlib import contextmanager

import redis
from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://paylane:paylane_dev_pw@localhost:5432/paylane"
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

engine = create_engine(DATABASE_URL, pool_pre_ping=False, pool_size=5)
r = redis.from_url(REDIS_URL, decode_responses=True)

app = FastAPI(title="paylane ledger-svc")
Instrumentator().instrument(app).expose(app)


@contextmanager
def db_session():
    conn = engine.connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.get("/health")
def health():
    try:
        with db_session() as c:
            c.execute(text("SELECT 1"))
        r.ping()
        return {"status": "ok", "service": "ledger-svc"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, detail=str(e))


@app.get("/accounts")
def list_accounts():
    with db_session() as c:
        rows = c.execute(
            text(
                """SELECT account_ref, holder_name, ifsc, balance_paise, status
                   FROM accounts ORDER BY id"""
            )
        ).mappings().all()
    return {"accounts": [dict(x) for x in rows]}


@app.get("/accounts/{account_ref}")
def get_account(account_ref: str):
    with db_session() as c:
        row = c.execute(
            text(
                """SELECT account_ref, holder_name, ifsc, balance_paise, status
                   FROM accounts WHERE account_ref = :r"""
            ),
            {"r": account_ref},
        ).mappings().first()
    if not row:
        raise HTTPException(404, detail="account not found")
    return dict(row)


@app.get("/accounts/{account_ref}/entries")
def account_entries(account_ref: str, limit: int = 50):
    with db_session() as c:
        rows = c.execute(
            text(
                """SELECT payment_ref, direction, amount_paise, created_at
                   FROM ledger_entries
                   WHERE account_ref = :r
                   ORDER BY id DESC LIMIT :l"""
            ),
            {"r": account_ref, "l": limit},
        ).mappings().all()
    return {"account_ref": account_ref, "entries": [dict(x) for x in rows]}


@app.get("/reconcile")
def reconcile():
    """
    Reconciliation check.

    For every settled payment there must be exactly one DEBIT and one CREDIT
    of equal value. Anything else is a break: a payment settled twice, a
    half-written pair, or a mismatched amount.
    """
    with db_session() as c:
        breaks = c.execute(
            text(
                """SELECT payment_ref,
                          COUNT(*)                                   AS entry_count,
                          SUM(CASE WHEN direction='DEBIT'  THEN 1 ELSE 0 END) AS debits,
                          SUM(CASE WHEN direction='CREDIT' THEN 1 ELSE 0 END) AS credits,
                          SUM(CASE WHEN direction='DEBIT'  THEN amount_paise
                                   ELSE -amount_paise END)           AS net_paise
                   FROM ledger_entries
                   GROUP BY payment_ref
                   HAVING COUNT(*) <> 2
                       OR SUM(CASE WHEN direction='DEBIT'  THEN amount_paise
                                   ELSE -amount_paise END) <> 0"""
            )
        ).mappings().all()

        total = c.execute(
            text("SELECT COUNT(DISTINCT payment_ref) AS n FROM ledger_entries")
        ).scalar_one()

    return {
        "payments_with_entries": total,
        "break_count": len(breaks),
        "breaks": [dict(b) for b in breaks],
        "status": "CLEAN" if not breaks else "BREAKS_FOUND",
    }
