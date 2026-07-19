"""
mandate-svc — standing payment permissions.

A mandate is a payer's standing permission for a payee to be paid, up to a
cap. Read-heavy and rarely changing, so lookups are cached in Redis.

    GET  /mandates            list mandates
    GET  /mandates/{ref}      fetch one mandate (cached)
    GET  /health              liveness + dependency check
    GET  /metrics             Prometheus metrics
"""
import json
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
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "60"))

engine = create_engine(DATABASE_URL, pool_pre_ping=False, pool_size=5)
r = redis.from_url(REDIS_URL, decode_responses=True)

app = FastAPI(title="paylane mandate-svc")
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
        return {"status": "ok", "service": "mandate-svc"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, detail=str(e))


@app.get("/mandates/{mandate_ref}")
def get_mandate(mandate_ref: str):
    """Fetch a mandate. Served from Redis when warm, Postgres when cold."""
    cache_key = f"mandate:{mandate_ref}"
    cached = r.get(cache_key)
    if cached:
        payload = json.loads(cached)
        payload["_source"] = "cache"
        return payload

    with db_session() as c:
        row = c.execute(
            text(
                """SELECT mandate_ref, payer_ref, payee_ref,
                          max_amount_paise, status
                   FROM mandates WHERE mandate_ref = :r"""
            ),
            {"r": mandate_ref},
        ).mappings().first()

    if not row:
        raise HTTPException(404, detail="mandate not found")

    payload = dict(row)
    r.setex(cache_key, CACHE_TTL_SECONDS, json.dumps(payload))
    payload["_source"] = "db"
    return payload


@app.get("/mandates")
def list_mandates(limit: int = 50):
    with db_session() as c:
        rows = c.execute(
            text(
                """SELECT mandate_ref, payer_ref, payee_ref,
                          max_amount_paise, status
                   FROM mandates ORDER BY id LIMIT :l"""
            ),
            {"l": limit},
        ).mappings().all()
    return {"mandates": [dict(x) for x in rows]}
