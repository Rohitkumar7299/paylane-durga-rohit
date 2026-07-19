"""
payment-svc — the payment initiation service.

Accepts a payment instruction, validates it against the mandate, records it,
and queues it for settlement. Returns ACCEPTED to the caller immediately:
the money has not moved yet. Settlement happens asynchronously in
settlement-worker.

    POST /payments            submit a payment instruction
    GET  /payments/{ref}      fetch one payment
    GET  /payments            list recent payments
    GET  /health              liveness + dependency check
    GET  /metrics             Prometheus metrics
"""
import json
import os
import uuid
from contextlib import contextmanager

import httpx
import redis
from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://paylane:paylane_dev_pw@localhost:5432/paylane"
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MANDATE_SVC_URL = os.getenv("MANDATE_SVC_URL", "http://localhost:3001")
SETTLEMENT_QUEUE = "queue:settlement"

engine = create_engine(DATABASE_URL, pool_pre_ping=False, pool_size=5)
r = redis.from_url(REDIS_URL, decode_responses=True)

app = FastAPI(title="paylane payment-svc")
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


def audit(conn, actor: str, action: str, entity_ref: str, detail: str = ""):
    """Append-only audit trail. Never updated, never deleted."""
    conn.execute(
        text(
            """INSERT INTO audit_log (actor, action, entity_ref, detail)
               VALUES (:a, :ac, :e, :d)"""
        ),
        {"a": actor, "ac": action, "e": entity_ref, "d": detail},
    )


class PaymentRequest(BaseModel):
    mandate_ref: str = Field(..., examples=["MND-5001"])
    amount_paise: int = Field(..., gt=0, examples=[50000])
    idempotency_key: str | None = Field(
        None,
        description="Caller-supplied key. Two requests with the same key must "
        "result in exactly one payment.",
    )


@app.get("/health")
def health():
    try:
        with db_session() as c:
            c.execute(text("SELECT 1"))
        r.ping()
        return {"status": "ok", "service": "payment-svc"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, detail=str(e))


@app.post("/payments", status_code=201)
def create_payment(req: PaymentRequest):
    """
    Accept a payment instruction.

    Flow: validate the mandate (call to mandate-svc) -> record the payment
    as ACCEPTED -> push a settlement job onto the queue -> return.
    """
    # 1. Validate against the mandate.
    try:
        resp = httpx.get(f"{MANDATE_SVC_URL}/mandates/{req.mandate_ref}", timeout=5.0)
    except httpx.RequestError as e:
        raise HTTPException(503, detail=f"mandate-svc unreachable: {e}") from e

    if resp.status_code == 404:
        raise HTTPException(400, detail="unknown mandate")
    resp.raise_for_status()
    mandate = resp.json()

    if mandate["status"] != "ACTIVE":
        raise HTTPException(400, detail="mandate is not active")
    if req.amount_paise > mandate["max_amount_paise"]:
        raise HTTPException(
            400,
            detail=f"amount exceeds mandate cap of {mandate['max_amount_paise']} paise",
        )

    payment_ref = f"PAY-{uuid.uuid4().hex[:12].upper()}"

    with db_session() as c:
        # 2. Record the instruction.
        c.execute(
            text(
                """INSERT INTO payments
                     (payment_ref, idempotency_key, mandate_ref, payer_ref,
                      payee_ref, amount_paise, status)
                   VALUES (:ref, :idem, :mnd, :payer, :payee, :amt, 'ACCEPTED')"""
            ),
            {
                "ref": payment_ref,
                "idem": req.idempotency_key,
                "mnd": req.mandate_ref,
                "payer": mandate["payer_ref"],
                "payee": mandate["payee_ref"],
                "amt": req.amount_paise,
            },
        )
        audit(
            c,
            "payment-svc",
            "PAYMENT_ACCEPTED",
            payment_ref,
            f"amount={req.amount_paise} mandate={req.mandate_ref}",
        )

    # 3. Queue for settlement. The caller does not wait for this.
    r.lpush(
        SETTLEMENT_QUEUE,
        json.dumps({"payment_ref": payment_ref, "amount_paise": req.amount_paise}),
    )

    return {
        "payment_ref": payment_ref,
        "status": "ACCEPTED",
        "note": "queued for settlement",
    }


@app.get("/payments/{payment_ref}")
def get_payment(payment_ref: str):
    with db_session() as c:
        row = c.execute(
            text(
                """SELECT payment_ref, mandate_ref, payer_ref, payee_ref,
                          amount_paise, status, failure_reason, created_at, settled_at
                   FROM payments WHERE payment_ref = :r"""
            ),
            {"r": payment_ref},
        ).mappings().first()
    if not row:
        raise HTTPException(404, detail="payment not found")
    return dict(row)


@app.get("/payments")
def list_payments(limit: int = 20):
    with db_session() as c:
        rows = c.execute(
            text(
                """SELECT payment_ref, payer_ref, payee_ref, amount_paise,
                          status, created_at
                   FROM payments ORDER BY id DESC LIMIT :l"""
            ),
            {"l": limit},
        ).mappings().all()
    return {"payments": [dict(x) for x in rows]}
