# Backend Spec (Flask)

## Folder structure

```
mail-dashboard/
├── app/
│   ├── __init__.py              # app factory, extension init
│   ├── config.py                # Config classes (Dev/Prod), reads from .env
│   ├── extensions.py            # db, login_manager, csrf, limiter, celery instances
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── account.py
│   │   ├── sender.py
│   │   ├── template.py
│   │   ├── recipient.py
│   │   ├── job.py
│   │   └── send_log.py
│   ├── routes/
│   │   ├── __init__.py          # blueprint registration
│   │   ├── auth.py
│   │   ├── accounts.py
│   │   ├── senders.py
│   │   ├── templates.py
│   │   ├── recipients.py
│   │   ├── jobs.py
│   │   └── dashboard.py
│   ├── services/
│   │   ├── alibaba_client.py    # DmClient factory, encryption helpers
│   │   ├── quota.py             # quota calculation logic
│   │   ├── allocation.py        # recipient-to-sender allocation algorithm
│   │   ├── csv_import.py        # recipient list parsing/validation
│   │   └── template_validate.py # HTML size/basic validation
│   ├── tasks/
│   │   ├── __init__.py          # celery app init
│   │   ├── dispatch.py          # dispatch_job task
│   │   ├── send.py              # send_recipient task
│   │   └── scheduler.py         # review_sender_health, poll_pending_jobs (beat tasks)
│   ├── templates/               # Jinja2 HTML templates (see FRONTEND_SPEC.md)
│   └── static/
│       ├── css/
│       └── js/
├── migrations/                  # Alembic migration files
├── tests/
│   ├── test_allocation.py
│   ├── test_quota.py
│   ├── test_csv_import.py
│   └── test_routes.py
├── instance/
│   └── mail_dashboard.db        # SQLite file (gitignored)
├── .env.example
├── requirements.txt
├── celery_worker.py             # entrypoint: celery -A celery_worker.celery worker
├── celery_beat.py               # entrypoint: celery -A celery_beat.celery beat
├── wsgi.py                      # entrypoint for gunicorn
└── manage.py                    # CLI: create-admin, seed-data, etc.
```

## Key dependencies (`requirements.txt`)

```
Flask>=3.0
Flask-SQLAlchemy>=3.1
Flask-Migrate>=4.0
Flask-Login>=0.6
Flask-WTF>=1.2
Flask-Limiter>=3.5
celery[redis]>=5.3
redis>=5.0
cryptography>=42.0
python-dotenv>=1.0
pandas>=2.2              # CSV/XLSX parsing
openpyxl>=3.1             # XLSX support for pandas
alibabacloud_dm20151123
alibabacloud_tea_openapi
alibabacloud_credentials
gunicorn>=21.2
```

## Route map

### Auth (`/auth`)
- `GET/POST /auth/login`
- `GET /auth/logout`

### Dashboard (`/`)
- `GET /` — overview: active jobs, today's send totals across all
  accounts, quota health summary (which senders are in cooldown/warmup)

### Accounts (`/accounts`)
- `GET /accounts` — list all accounts with sender counts and status
- `GET/POST /accounts/new` — add account (AccessKey/Secret form,
  test-connection button before saving)
- `GET/POST /accounts/<id>/edit`
- `POST /accounts/<id>/delete`
- `POST /accounts/<id>/test-connection` — AJAX, calls a lightweight
  Alibaba API call to verify credentials work

### Senders (`/accounts/<account_id>/senders`)
- `GET /accounts/<account_id>/senders` — list senders for an account
- `GET/POST /accounts/<account_id>/senders/new`
- `GET/POST /senders/<id>/edit`
- `POST /senders/<id>/delete`
- `POST /senders/<id>/set-status` — manually flip active/cooldown/disabled
- `GET /senders/<id>/quota-history` — chart data (JSON) for quota_checks

### Templates (`/templates`)
*(route namespace `/mail-templates` to avoid clashing with Flask's Jinja
"templates" folder concept — naming callout for Claude Code)*
- `GET /mail-templates` — list with size, last used date
- `GET/POST /mail-templates/new` — upload HTML file or paste HTML,
  validates < 80KB, shows live preview (iframe sandboxed)
- `GET /mail-templates/<id>` — view/preview
- `GET/POST /mail-templates/<id>/edit`
- `POST /mail-templates/<id>/delete`

### Recipients (`/recipients`)
- `GET /recipients` — list of uploaded lists with counts
- `GET/POST /recipients/upload` — CSV/XLSX upload, column-mapping step
  (map columns to email/first_name/last_name/custom), then import summary
  (valid/duplicate/invalid counts)
- `GET /recipients/<list_id>` — paginated table of recipients in a list
- `POST /recipients/<list_id>/delete`

### Jobs (`/jobs`)
- `GET /jobs` — list all jobs with status badges
- `GET/POST /jobs/new` — select template + recipient list, override
  subject, choose "send now" or schedule datetime, review allocation
  preview (which senders/how many each) before confirming
- `GET /jobs/<id>` — job detail page: live counters, per-sender
  allocation breakdown, failed-recipient table with error reasons
- `GET /jobs/<id>/status` — **SSE endpoint**, streams
  `{sent, failed, total, status}` every 2s while job is active
- `POST /jobs/<id>/pause`
- `POST /jobs/<id>/resume`
- `POST /jobs/<id>/cancel`
- `GET /jobs/<id>/export-failed` — CSV download of failed recipients +
  error codes for that job

## Allocation algorithm (`services/allocation.py`)

Pseudocode for `build_allocation_plan(job)`:

```python
def build_allocation_plan(recipient_count: int) -> list[dict]:
    """
    Returns a list of {sender_id, count} allocations that sum to
    recipient_count (or as close as available quota allows).
    """
    eligible_senders = SenderAddress.query.filter_by(status='active').all()

    plan = []
    remaining = recipient_count

    for sender in sorted(eligible_senders, key=lambda s: s.remaining_quota_today, reverse=True):
        if remaining <= 0:
            break
        take = min(sender.remaining_quota_today, remaining)
        if take > 0:
            plan.append({"sender_id": sender.id, "count": take})
            remaining -= take

    if remaining > 0:
        # Not enough total quota today across all senders.
        # Flag this back to the caller so the UI can warn the user
        # and offer to schedule the overflow for the next day.
        pass

    return plan, remaining  # remaining = unallocated count, if any
```

`sender.remaining_quota_today` is a computed property:
`baseline_daily_quota - (SELECT COUNT(*) FROM send_logs WHERE sender_id = ? AND date(sent_at) = date('now') AND status = 'sent')`

## Rate limiting inside Celery

Each `send_recipient` task should be dispatched with a Celery rate limit
tied to the sender, e.g. `send_recipient.apply_async(args=[...], queue=f"sender_{sender_id}")`
with a per-queue worker concurrency cap, OR simpler for v1: a shared
`send_recipient` task that accepts `sender_id` and self-throttles using
Celery's `rate_limit` option per task type combined with a small
`time.sleep()` jitter — recommend starting simple (global rate limit
across all sends, e.g. no more than N/sec) and only adding per-sender
queues if the simple approach proves insufficient during testing.

## Environment config (`.env.example`)

```
FLASK_ENV=production
SECRET_KEY=change-me
DATABASE_URL=sqlite:///instance/mail_dashboard.db
REDIS_URL=redis://localhost:6379/0
ENCRYPTION_KEY=generate-with-fernet-generate-key
ADMIN_EMAIL=you@devtv.example
SEND_RATE_LIMIT_PER_SECOND=5
JOB_FAILURE_THRESHOLD_PERCENT=5
```

## CLI commands (`manage.py`)

- `flask create-admin --email x --password y`
- `flask seed-demo-data` (optional, for local dev/testing without touching
  real Alibaba accounts)
- `flask db upgrade` (Alembic, standard Flask-Migrate command)
