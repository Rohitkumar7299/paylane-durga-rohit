"""
settlement-worker — settles queued payments.

Polls 'queue:settlement', and for each job: debits the payer, credits the
payee, writes the two ledger entries, and marks the payment SETTLED.

The customer already got an ACCEPTED response before any of this ran. This
is the work that happens later.

Env:
    DATABASE_URL, REDIS_URL
    SETTLE_DELAY_MS   artificial per-job delay (default 200) — makes queue
                      depth visible on the dashboard
"""
import json
import logging
import os
import random
import signal
import time

import redis
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://paylane:paylane_dev_pw@localhost:5432/paylane"
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SETTLEMENT_QUEUE = "queue:settlement"
DLQ = "queue:settlement:dead"
SETTLE_DELAY_MS = int(os.getenv("SETTLE_DELAY_MS", "200"))

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","service":"settlement-worker","msg":"%(message)s"}',
)
log = logging.getLogger("settlement-worker")

# NOTE: pool_pre_ping is off and pool_recycle is unset. A connection that has
# been idle long enough for the database to drop it will be handed out anyway.
engine = create_engine(DATABASE_URL, pool_pre_ping=False, pool_size=2)
r = redis.from_url(REDIS_URL, decode_responses=True)

_running = True


def _stop(signum, frame):  # noqa: ARG001
    global _running
    log.info("shutdown signal received, finishing current job")
    _running = False


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def settle(payment_ref: str, amount_paise: int) -> None:
    """
    Settle one payment: move the money, write the ledger pair, mark it done.
    """
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            row = conn.execute(
                text(
                    """SELECT payer_ref, payee_ref, amount_paise, status
                       FROM payments WHERE payment_ref = :r"""
                ),
                {"r": payment_ref},
            ).mappings().first()

            if not row:
                log.error("payment %s not found", payment_ref)
                trans.rollback()
                return

            payer, payee = row["payer_ref"], row["payee_ref"]

            balance = conn.execute(
                text("SELECT balance_paise FROM accounts WHERE account_ref = :r"),
                {"r": payer},
            ).scalar_one()

            if balance < amount_paise:
                conn.execute(
                    text(
                        """UPDATE payments
                           SET status='FAILED', failure_reason='insufficient funds'
                           WHERE payment_ref = :r"""
                    ),
                    {"r": payment_ref},
                )
                conn.execute(
                    text(
                        """INSERT INTO audit_log (actor, action, entity_ref, detail)
                           VALUES ('settlement-worker','PAYMENT_FAILED',:r,
                                   'insufficient funds')"""
                    ),
                    {"r": payment_ref},
                )
                trans.commit()
                log.warning("payment %s failed: insufficient funds", payment_ref)
                return

            # Move the money.
            conn.execute(
                text(
                    """UPDATE accounts SET balance_paise = balance_paise - :a
                       WHERE account_ref = :r"""
                ),
                {"a": amount_paise, "r": payer},
            )
            conn.execute(
                text(
                    """UPDATE accounts SET balance_paise = balance_paise + :a
                       WHERE account_ref = :r"""
                ),
                {"a": amount_paise, "r": payee},
            )

            # The double-entry pair.
            conn.execute(
                text(
                    """INSERT INTO ledger_entries
                         (payment_ref, account_ref, direction, amount_paise)
                       VALUES (:p, :r, 'DEBIT', :a)"""
                ),
                {"p": payment_ref, "r": payer, "a": amount_paise},
            )
            conn.execute(
                text(
                    """INSERT INTO ledger_entries
                         (payment_ref, account_ref, direction, amount_paise)
                       VALUES (:p, :r, 'CREDIT', :a)"""
                ),
                {"p": payment_ref, "r": payee, "a": amount_paise},
            )

            conn.execute(
                text(
                    """UPDATE payments SET status='SETTLED', settled_at=now()
                       WHERE payment_ref = :r"""
                ),
                {"r": payment_ref},
            )
            conn.execute(
                text(
                    """INSERT INTO audit_log (actor, action, entity_ref, detail)
                       VALUES ('settlement-worker','PAYMENT_SETTLED',:r,:d)"""
                ),
                {"r": payment_ref, "d": f"amount={amount_paise}"},
            )

            trans.commit()
            log.info("settled %s amount=%s", payment_ref, amount_paise)
        except Exception:
            trans.rollback()
            raise


def main():
    log.info("settlement-worker starting, polling %s", SETTLEMENT_QUEUE)
    while _running:
        job = r.brpop(SETTLEMENT_QUEUE, timeout=2)
        if not job:
            continue

        _, raw = job
        try:
            payload = json.loads(raw)
            payment_ref = payload["payment_ref"]
            amount = payload["amount_paise"]
        except (ValueError, KeyError) as e:
            log.error("malformed job discarded: %s", e)
            r.lpush(DLQ, raw)
            continue

        # Simulated settlement latency.
        time.sleep(SETTLE_DELAY_MS / 1000.0 + random.uniform(0, 0.05))

        try:
            settle(payment_ref, amount)
        except Exception as e:  # noqa: BLE001
            # Transient failure: put the job back and let it be retried.
            log.error("settlement failed for %s, requeueing: %s", payment_ref, e)
            r.lpush(SETTLEMENT_QUEUE, raw)
            time.sleep(0.5)

    log.info("settlement-worker stopped")


if __name__ == "__main__":
    main()
