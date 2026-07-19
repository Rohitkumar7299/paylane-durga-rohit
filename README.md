# paylane

A small payments platform: accept a payment instruction, validate it against a
mandate, settle it asynchronously, and keep a double-entry ledger and an
append-only audit trail.

The application code is complete and working. **The platform work is not.**
There is no pipeline, no infrastructure code, no orchestration, no packaging,
and no observability stack — that is the work.

---

## Architecture

```
  Browser
     |
     v
  portal (Node/Express, :3000)
     |
     |---> mandate-svc  (FastAPI, :3001)  --- Redis (cache)
     |                                     \
     |---> payment-svc  (FastAPI, :3002)  --- Postgres
     |          |                          /
     |          \--> Redis  queue:settlement
     |                       |
     |                       v
     |               settlement-worker (no port) --- Postgres
     |
     \---> ledger-svc   (FastAPI, :3003)  --- Postgres
```

| Service | Port | Responsibility |
|---|---|---|
| `portal` | 3000 | Submit a payment, view payments and accounts. Holds no data. |
| `mandate-svc` | 3001 | Standing payment permissions and their caps. Read-heavy, Redis-cached. |
| `payment-svc` | 3002 | Accept and validate an instruction, persist it, queue it for settlement. |
| `ledger-svc` | 3003 | Accounts, balances, double-entry ledger, reconciliation. |
| `settlement-worker` | — | Consumes `queue:settlement`, moves the money, writes the ledger pair. |

**The synchronous path** ends at ACCEPTED. `payment-svc` validates the mandate,
records the instruction, pushes a job onto the queue, and returns — in
milliseconds. No money has moved.

**The asynchronous path** is where money actually moves. `settlement-worker`
pulls the job, checks the payer's balance, debits and credits the two accounts,
writes two ledger entries, and marks the payment SETTLED. If the queue backs up,
the site stays fast — payments just take longer to settle. Queue depth is the
metric that tells you this is happening.

### Data model

- `accounts` — who can send and receive, with balances in paise
- `mandates` — payer's standing permission for a payee, with a cap
- `payments` — the instruction: ACCEPTED, then SETTLED or FAILED
- `ledger_entries` — double entry. Every settled payment writes exactly one
  DEBIT and one CREDIT of equal value
- `audit_log` — append-only. Nothing updates it, nothing deletes from it

The double-entry invariant is what `GET /ledger-svc/reconcile` checks: any
payment whose entries don't consist of exactly one DEBIT and one CREDIT netting
to zero is a **break**.

---

## Quickstart

Requires Docker (for the datastores), Python 3.12, and Node 20.

```bash
docker compose up -d                 # postgres + redis
pip install -r services/payment-svc/requirements.txt
pip install -r services/mandate-svc/requirements.txt
pip install -r services/settlement-worker/requirements.txt
(cd services/portal && npm ci)

python3 scripts/seed-db.py           # schema + accounts + mandates
./scripts/start-s1.sh                # all five services
```

Then open http://localhost:3000

Stop everything with `./scripts/stop-s1.sh`.

### Verify it works

```
$ curl -s localhost:3003/accounts
  ACC-1001   Meera Nair           Rs   5,000.00
  ACC-2001   Bluepeak Utilities   Rs       0.00

$ curl -s -X POST localhost:3002/payments \
    -H 'Content-Type: application/json' \
    -d '{"mandate_ref":"MND-5001","amount_paise":50000}'
{"payment_ref":"PAY-F10BC8E98712","status":"ACCEPTED","note":"queued for settlement"}

# ... a moment later, in logs/settlement-worker.log:
{"level":"INFO","service":"settlement-worker","msg":"settled PAY-F10BC8E98712 amount=50000"}

$ curl -s localhost:3003/accounts
  ACC-1001   Meera Nair           Rs   4,500.00
  ACC-2001   Bluepeak Utilities   Rs     500.00

$ curl -s localhost:3003/reconcile
{"payments_with_entries":1,"break_count":0,"breaks":[],"status":"CLEAN"}
```

### Things worth trying

```bash
# Mandate cap is enforced (MND-5001 is capped at Rs 2000)
curl -s -X POST localhost:3002/payments -H 'Content-Type: application/json' \
  -d '{"mandate_ref":"MND-5001","amount_paise":300000}'
# {"detail":"amount exceeds mandate cap of 200000 paise"}

# The cache is real: first call says "db", second says "cache"
curl -s localhost:3001/mandates/MND-5001
curl -s localhost:3001/mandates/MND-5001

# Insufficient funds fails at settlement, not at acceptance —
# the caller already got a 201
curl -s -X POST localhost:3002/payments -H 'Content-Type: application/json' \
  -d '{"mandate_ref":"MND-5004","amount_paise":500000}'
```

---

## Endpoints

Every service exposes `GET /health` (checks Postgres and Redis) and
`GET /metrics` (Prometheus format).

**payment-svc**
- `POST /payments` — `{mandate_ref, amount_paise, idempotency_key?}`
- `GET /payments/{ref}`
- `GET /payments?limit=20`

**mandate-svc**
- `GET /mandates`
- `GET /mandates/{ref}` — cached, response includes `_source: db|cache`

**ledger-svc**
- `GET /accounts`, `GET /accounts/{ref}`, `GET /accounts/{ref}/entries`
- `GET /reconcile` — the double-entry check

---

## Configuration

Every service reads its configuration from the environment. Nothing is
hardcoded to localhost in a way you can't override — this is what makes one
artifact runnable on a laptop, in CI, and in a cluster.

| Variable | Default | Used by |
|---|---|---|
| `DATABASE_URL` | `postgresql://paylane:paylane_dev_pw@localhost:5432/paylane` | all Python services |
| `REDIS_URL` | `redis://localhost:6379/0` | all Python services |
| `MANDATE_SVC_URL` | `http://localhost:3001` | payment-svc, portal |
| `PAYMENT_SVC_URL` | `http://localhost:3002` | portal |
| `LEDGER_SVC_URL` | `http://localhost:3003` | portal |
| `CACHE_TTL_SECONDS` | `60` | mandate-svc |
| `SETTLE_DELAY_MS` | `200` | settlement-worker |

---

## Current state, and what's missing

This repo is at **S1**: services run as host processes, datastores run in
containers, and everything is started by a shell script on one machine.

What a payments platform actually needs, and this doesn't have:

- No container images for the services — only the datastores are containerized
- No pipeline. Nothing is built, tested, scanned, or published automatically
- No infrastructure code. The environment is whatever your laptop happens to be
- No orchestration, no packaging, no deployment mechanism
- No observability stack wired up, though every service already exposes
  `/metrics` and logs as JSON
- No backup or restore procedure for the database that holds the money
- No runbook for any of it

That list is the work.

One scaffold is provided to save you from a blind alley: `deploy/docker-compose.ec2.reference.yml` shows the shape of the compose file that runs on the deploy target, pulling images from the registry rather than building them. It has `TODO` markers, not answers — completing them is part of the deployment milestone.
