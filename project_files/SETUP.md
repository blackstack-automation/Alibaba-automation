# Setup & Deployment

## Prerequisites on the VPS

- Python 3.11+
- Redis server (`apt install redis-server`)
- SQLite3 (usually preinstalled on Ubuntu)
- `nginx` as reverse proxy in front of gunicorn (standard setup, matches
  existing Dev TV VPS pattern)
- `supervisor` or `systemd` to keep the Flask app, Celery worker, and
  Celery beat processes running persistently

## Local development setup

```bash
git clone <repo>
cd mail-dashboard
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env: set SECRET_KEY, generate ENCRYPTION_KEY (see below)

# Generate an encryption key for AccessKey/Secret storage:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Paste output into .env as ENCRYPTION_KEY

flask db upgrade
flask create-admin --email you@example.com --password <choose-one>

# Terminal 1: Flask dev server
flask run

# Terminal 2: Redis (if not already running as a service)
redis-server

# Terminal 3: Celery worker
celery -A celery_worker.celery worker --loglevel=info

# Terminal 4: Celery beat (scheduler)
celery -A celery_beat.celery beat --loglevel=info
```

## Environment variables reference

| Variable | Required | Notes |
|---|---|---|
| `SECRET_KEY` | Yes | Flask session signing key |
| `DATABASE_URL` | Yes | `sqlite:///instance/mail_dashboard.db` |
| `REDIS_URL` | Yes | `redis://localhost:6379/0` |
| `ENCRYPTION_KEY` | Yes | Fernet key for AccessKey/Secret encryption — **back this up securely, losing it means losing access to all stored Alibaba credentials** |
| `ADMIN_EMAIL` | No | Used only by seed/CLI convenience commands |
| `SEND_RATE_LIMIT_PER_SECOND` | No | Default 5, tune based on observed stability |
| `JOB_FAILURE_THRESHOLD_PERCENT` | No | Default 5, above this a completed job is flagged `completed_with_errors` |

## Production deployment (VPS)

```bash
# gunicorn for the Flask app
gunicorn -w 4 -b 127.0.0.1:8000 wsgi:app

# nginx reverse proxy config (standard) → proxies to 127.0.0.1:8000

# systemd unit files needed (create three):
# 1. mail-dashboard-web.service    → runs gunicorn command above
# 2. mail-dashboard-worker.service → celery -A celery_worker.celery worker
# 3. mail-dashboard-beat.service   → celery -A celery_beat.celery beat
```

Each systemd unit should have `Restart=always` so a crash doesn't require
manual intervention — this matters especially for the Celery worker,
since a dead worker mid-job means a stuck job.

## Backup strategy

- SQLite file (`instance/mail_dashboard.db`) — back up daily via cron
  (`sqlite3 .backup` command, not a raw file copy, to avoid WAL
  corruption risk)
- `.env` file (specifically `ENCRYPTION_KEY`) — back up separately and
  securely (not in the same place as the DB backup); losing this key
  permanently locks out all stored Alibaba credentials, requiring
  re-entry of every account's AccessKey/Secret

## Runbook: common operational situations

### A job appears stuck (status stays "sending" with no progress)

1. Check Celery worker is alive: `systemctl status mail-dashboard-worker`
2. Check Redis is reachable: `redis-cli ping`
3. Check worker logs for errors on the specific `job_id`
4. If the worker crashed mid-job, restart it — Celery will not
   automatically resume unacknowledged tasks depending on broker
   settings, so verify `task_acks_late` is configured if resumability
   after a crash is important
5. As a last resort, manually inspect `send_logs` for that `job_id` to
   see how far it got, and manually update `jobs.status` if needed

### A sender is stuck in cooldown longer than expected

1. Check `sender_addresses.last_cooldown_reason` and `quota_checks`
   history for that sender
2. Manually flip status back to `active` via the Senders edit page once
   you've confirmed via the Alibaba console that the account is no longer
   rate-limited
3. Consider lowering `baseline_daily_quota` if this sender keeps hitting
   cooldown — it means our estimate is too optimistic

### Need to add a brand new Alibaba account mid-operation

1. Add via `/accounts/new`, test connection
2. Add its sender address(es) with a conservative `baseline_daily_quota`
   (see warm-up guidance in `ALIBABA_INTEGRATION.md`)
3. New sender will automatically be included in allocation planning for
   the next job created — no restart needed

## What Claude Code needs to know before starting

- This is a **from-scratch build** — no existing codebase to integrate
  with beyond general conventions already used in other Dev TV Flask
  projects (Flask + SQLite + VPS pattern).
- Follow the folder structure in `BACKEND_SPEC.md` exactly so future docs
  and this runbook stay accurate.
- Do not skip the "test with a small real list first" step in
  `DEVELOPMENT_PLAN.md` Phase 6 — sends are irreversible and consume real
  quota.
- Ask before making architectural deviations from these docs (e.g.
  switching Celery for RQ, or SQLite for Postgres) — these choices were
  made deliberately based on the existing stack and expected scale.
