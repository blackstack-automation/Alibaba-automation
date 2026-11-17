# Architecture

## Components

```
┌─────────────────────────────────────────────────────────────────┐
│                         Flask Web App                            │
│  (routes, auth, HTML rendering, upload handling, SSE endpoint)   │
└───────────────┬───────────────────────────────┬─────────────────┘
                │                               │
                │ writes jobs/config             │ reads live counters
                ▼                               ▼
┌───────────────────────────┐      ┌─────────────────────────────┐
│      SQLite (WAL mode)     │◄────►│   Redis (queue + counters)  │
│  accounts, senders,        │      │  Celery broker/result store │
│  templates, recipients,    │      │  live per-job counters      │
│  jobs, send_logs, quota    │      └─────────────┬───────────────┘
└─────────────────────────────┘                    │
                ▲                                   ▼
                │                     ┌───────────────────────────┐
                │ writes results       │   Celery Worker(s)         │
                └──────────────────────│  - quota refresh task      │
                                       │  - send dispatch task      │
                                       │  - per-recipient send task │
                                       └─────────────┬───────────────┘
                                                       │
                                                       ▼
                                       ┌───────────────────────────┐
                                       │  Alibaba DirectMail API    │
                                       │  (one client per account)  │
                                       └───────────────────────────┘
```

## Why a job queue (Celery + Redis) instead of a simple loop

At 20-30k emails/day, a synchronous loop inside a Flask request would time
out immediately. We need:

- **Concurrency** — multiple accounts/senders sending in parallel
- **Per-account rate limiting** — each account has its own quota; a global
  loop can't easily throttle per-account without a proper task queue
- **Resumability** — if the VPS restarts mid-job, Celery + Redis persistence
  means we don't lose track of what's already been sent
- **Retry logic** — transient failures (network blips, temporary Alibaba
  errors) should retry with backoff without blocking the rest of the job

If Redis feels like too much infra for v1, RQ (Redis Queue) is a lighter
drop-in alternative with a simpler API — same Redis dependency either way.
Recommendation: **use Celery** since it has first-class rate-limiting
(`rate_limit` per task) which maps directly onto our per-account throttling
need.

## Job lifecycle

1. **User creates a job**: selects a template, a recipient list (or a saved
   segment/filter of the master list), and clicks "Send" (immediately or
   scheduled for a future time).
2. **Job is saved** to `jobs` table with status `pending`.
3. **Scheduler** (APScheduler running inside a lightweight beat process, or
   Celery Beat) picks up jobs whose `scheduled_at <= now()` and status is
   `pending`, flips status to `queued`, and triggers the dispatch task.
4. **Dispatch task** (`dispatch_job`):
   - Loads all `sender_addresses` with `status = 'active'` and refreshes/
     checks their current quota (via `quota_checks` cache, refreshed daily
     or before large jobs)
   - Builds an allocation plan: recipient chunks assigned to
     account/sender pairs, respecting `remaining_quota` per sender
   - Enqueues one `send_recipient` task per recipient (or small batch, see
     `ALIBABA_INTEGRATION.md` for batching notes), each tagged with which
     account/sender to use
   - Flips job status to `sending`
5. **`send_recipient` task**:
   - Calls `SingleSendMail` via the assigned account's `DmClient`
   - On success: writes `send_logs` row with `status='sent'`, increments
     Redis counter `job:{id}:sent`
   - On failure: writes `send_logs` row with `status='failed'` + error code
     + error message, increments Redis counter `job:{id}:failed`
   - If failure reason is quota/frequency related
     (`InvalidSendMail.Spam`), triggers a **cooldown flag** on that sender
     (see `ALIBABA_INTEGRATION.md`) so subsequent tasks skip it until
     re-checked
6. **Job completion**: once all tasks for a job report back (Celery
   `chord` or a simple remaining-count check), job status flips to
   `completed` (or `completed_with_errors` if failure rate exceeds a
   threshold, e.g. >5%).
7. **Live status**: Flask exposes `GET /jobs/<id>/status` (SSE stream or
   polled JSON) that reads the Redis counters directly — this is what
   makes the dashboard "live" without hammering SQLite.

## Quota tracking model

Alibaba doesn't expose a single documented "get my current quota" endpoint
that's guaranteed stable — so the plan is:

- Store a **manually-set baseline quota** per sender in `sender_addresses`
  (`baseline_daily_quota`) that we update as we observe Alibaba's console
  values or API responses over time.
- Track a **rolling counter** of emails sent per sender per calendar day in
  `send_logs` (queryable, indexed by `sender_id` + `sent_at` date).
- Before allocating a job, compute
  `remaining_quota = baseline_daily_quota - sent_today`.
- If a sender starts throwing `InvalidSendMail.Spam` errors, immediately
  mark it `cooldown` in `sender_addresses` and stop allocating to it,
  regardless of what the computed remaining quota says — actual API
  feedback overrides our estimate.
- A daily scheduled task (`review_sender_health`) resets `cooldown` flags
  each morning and recalculates `sent_today` counters to zero, and can
  optionally auto-adjust `baseline_daily_quota` upward slowly (warm-up
  logic) if the last N days had a clean delivery rate.

## Failure isolation

Each `send_recipient` task is independent — one failed recipient never
blocks others. Each task is also scoped to a single account/sender, so a
frozen or rate-limited account doesn't stall the whole job; the dispatcher
simply has fewer senders to allocate to and the job runs slower (or, if
total quota that day is insufficient for the full list, the excess
recipients roll into a `queued_overflow` state for the next day — see
`DATABASE_SCHEMA.md` for the `jobs.status` values).

## Security notes

- AccessKey/Secret values are encrypted at rest (Fernet symmetric
  encryption via `cryptography` package, key stored in environment
  variable, never in the DB or in git).
- This is an internal tool — no public signup. Single admin login (or a
  small fixed set of users) via Flask-Login with hashed passwords.
- CSRF protection on all state-changing routes (Flask-WTF).
- Rate-limit the web app's own login route to prevent brute force
  (Flask-Limiter).
