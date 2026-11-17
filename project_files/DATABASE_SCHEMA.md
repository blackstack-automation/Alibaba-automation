# Database Schema (SQLite, WAL mode)

Enable WAL mode on app startup:

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
```

## Entity relationship summary

```
users
accounts 1───* sender_addresses
accounts 1───* quota_checks (via sender_addresses)
sender_addresses 1───* send_logs
templates 1───* jobs
recipient_lists 1───* recipients
recipient_lists 1───* jobs
jobs 1───* send_logs
jobs 1───* job_allocations
```

## Tables

### `users`

Internal login accounts for the dashboard (small, fixed set).

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',   -- 'admin' | 'operator'
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
);
```

### `accounts`

One row per Alibaba Cloud account.

```sql
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,                       -- human-friendly name, e.g. "Account A - Client X"
    access_key_id TEXT NOT NULL,
    access_key_secret_encrypted TEXT NOT NULL,  -- Fernet-encrypted
    region_endpoint TEXT NOT NULL DEFAULT 'dm.aliyuncs.com',
    status TEXT NOT NULL DEFAULT 'active',      -- 'active' | 'disabled'
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### `sender_addresses`

Verified sender addresses ("servers") within an account. Each account can
have multiple.

```sql
CREATE TABLE sender_addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    email_address TEXT NOT NULL,
    from_alias TEXT,                            -- max 15 chars per Alibaba limit
    reply_to_address TEXT,
    reply_to_alias TEXT,
    status TEXT NOT NULL DEFAULT 'active',       -- 'active' | 'cooldown' | 'warming_up' | 'disabled'
    baseline_daily_quota INTEGER NOT NULL DEFAULT 200,  -- manually seeded, adjusted over time
    warmup_started_at TEXT,
    last_cooldown_at TEXT,
    last_cooldown_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(account_id, email_address)
);

CREATE INDEX idx_sender_addresses_account ON sender_addresses(account_id);
CREATE INDEX idx_sender_addresses_status ON sender_addresses(status);
```

### `quota_checks`

Historical log of observed/estimated quota per sender over time — lets us
see whether a sender's trust is climbing or shrinking.

```sql
CREATE TABLE quota_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL REFERENCES sender_addresses(id) ON DELETE CASCADE,
    checked_at TEXT NOT NULL DEFAULT (datetime('now')),
    sent_today_count INTEGER NOT NULL DEFAULT 0,
    estimated_remaining INTEGER,
    source TEXT NOT NULL DEFAULT 'computed',    -- 'computed' | 'manual' | 'api'
    note TEXT
);

CREATE INDEX idx_quota_checks_sender ON quota_checks(sender_id, checked_at);
```

### `templates`

Uploaded HTML email templates.

```sql
CREATE TABLE templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    html_body TEXT NOT NULL,                    -- raw HTML, validated < 80KB at upload
    text_body TEXT,                              -- optional plaintext fallback
    subject_default TEXT,                        -- default subject line, editable per job
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### `recipient_lists`

An uploaded batch of recipients (one CSV/XLSX upload = one list).

```sql
CREATE TABLE recipient_lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source_filename TEXT,
    total_count INTEGER NOT NULL DEFAULT 0,
    valid_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    invalid_count INTEGER NOT NULL DEFAULT 0,
    uploaded_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### `recipients`

Individual recipients belonging to a list. Deduplicated at insert time
against `email_address` within the same list; cross-list dedup handled at
job-build time (see `BACKEND_SPEC.md`).

```sql
CREATE TABLE recipients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id INTEGER NOT NULL REFERENCES recipient_lists(id) ON DELETE CASCADE,
    email_address TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    custom_fields TEXT,                          -- JSON blob for any extra CSV columns
    is_valid_format INTEGER NOT NULL DEFAULT 1,   -- 0/1, basic regex check at import
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_recipients_list ON recipients(list_id);
CREATE INDEX idx_recipients_email ON recipients(email_address);
```

### `jobs`

A send job: template + recipient list + schedule + status.

```sql
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    template_id INTEGER NOT NULL REFERENCES templates(id),
    recipient_list_id INTEGER NOT NULL REFERENCES recipient_lists(id),
    subject_override TEXT,                        -- if null, use template.subject_default
    status TEXT NOT NULL DEFAULT 'pending',
        -- 'pending' | 'queued' | 'sending' | 'paused' |
        -- 'completed' | 'completed_with_errors' | 'failed' | 'cancelled'
    scheduled_at TEXT,                             -- null = send immediately on creation
    started_at TEXT,
    completed_at TEXT,
    total_recipients INTEGER NOT NULL DEFAULT 0,
    sent_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_scheduled ON jobs(scheduled_at);
```

Note: `sent_count`/`failed_count` on this table are the **durable**
counters, updated periodically (e.g. every N completed tasks or on job
completion) from the authoritative Redis live counters. The dashboard's
*live* number during an active job reads Redis directly for lowest latency;
this column is the source of truth once the job finishes or if Redis is
unavailable.

### `job_allocations`

Records which sender was assigned to which chunk of a job — useful for
debugging and for the allocation algorithm to avoid re-allocating already
in-flight chunks on retry.

```sql
CREATE TABLE job_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    sender_id INTEGER NOT NULL REFERENCES sender_addresses(id),
    allocated_count INTEGER NOT NULL DEFAULT 0,
    sent_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_job_allocations_job ON job_allocations(job_id);
```

### `send_logs`

One row per individual send attempt — the detailed audit trail and the
source for failed-recipient review/export.

```sql
CREATE TABLE send_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    recipient_id INTEGER NOT NULL REFERENCES recipients(id),
    sender_id INTEGER NOT NULL REFERENCES sender_addresses(id),
    status TEXT NOT NULL,                          -- 'sent' | 'failed' | 'retrying'
    alibaba_request_id TEXT,
    alibaba_env_id TEXT,
    error_code TEXT,                                -- e.g. 'InvalidSendMail.Spam'
    error_message TEXT,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    sent_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_send_logs_job ON send_logs(job_id);
CREATE INDEX idx_send_logs_sender_date ON send_logs(sender_id, sent_at);
CREATE INDEX idx_send_logs_status ON send_logs(status);
```

This table is what powers:
- "How many did sender X send today?" (quota calculation)
- "Show me failed recipients for job Y, with reasons" (failure review/export)
- Live dashboard counts, as a fallback if Redis counters are lost

## Migration tooling

Use **Flask-Migrate (Alembic)** even though this is SQLite — it gives us
versioned, repeatable schema changes as the app evolves, and Alembic
supports SQLite's limited `ALTER TABLE` via batch mode automatically.

## Retention notes

`send_logs` will grow fastest (up to 30k rows/day). At that rate it's
still trivially small for SQLite (a few million rows/year, low IO). No
pruning needed for v1; revisit if this project runs multi-year.
