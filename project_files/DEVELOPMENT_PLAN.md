# Development Plan — Phased Build Order

Build in this order. Each phase should be fully working and testable
before moving to the next — don't build the send engine before the data
model + CRUD screens exist to feed it.

## Phase 0 — Project scaffolding

- [ ] Initialize Flask app factory pattern per `BACKEND_SPEC.md` folder
      structure
- [ ] Set up SQLite + Flask-SQLAlchemy + Flask-Migrate, run first empty
      migration
- [ ] Set up `.env` handling (`python-dotenv`), copy `.env.example`
- [ ] Set up Tailwind (CDN is fine to start — swap to CLI build later if
      needed) and base layout template with nav
- [ ] Set up Flask-Login with a single seeded admin user (`flask
      create-admin` CLI command)
- [ ] Basic health-check route (`/healthz`) returning 200 for deployment
      verification

**Acceptance**: `flask run` boots, login page works, logging in shows an
empty dashboard shell with nav links to all planned sections (pages can
be stubs).

## Phase 1 — Accounts & Senders (data layer + CRUD)

- [ ] Implement `accounts` and `sender_addresses` models exactly per
      `DATABASE_SCHEMA.md`, run migration
- [ ] Implement encryption helpers (`services/alibaba_client.py`
      `decrypt_secret`, plus an `encrypt_secret` counterpart), generate
      and document `ENCRYPTION_KEY` setup in `SETUP.md`
- [ ] Build Accounts list/add/edit/delete routes + templates
- [ ] Build "Test Connection" button — call a lightweight, side-effect-free
      Alibaba API method (check SDK docs for a suitable read-only call,
      e.g. querying sender address list) to confirm credentials are valid
      before saving
- [ ] Build Senders list/add/edit/delete routes + templates, scoped under
      an account

**Acceptance**: Can add a real Alibaba account, test the connection
successfully, add at least one sender address to it, edit/delete both,
and see them reflected correctly in the dashboard sender health grid
(grid can be minimal at this stage).

## Phase 2 — Templates

- [ ] Implement `templates` model
- [ ] Build upload flow (file upload + paste HTML tabs), size validation
      against 80KB limit
- [ ] Build live preview (sandboxed iframe)
- [ ] Build templates list (card grid) and detail/edit/delete

**Acceptance**: Can upload an HTML template, see an accurate preview, and
see a clear error if a template exceeds 80KB.

## Phase 3 — Recipients

- [ ] Implement `recipient_lists` and `recipients` models
- [ ] Build CSV/XLSX upload with `pandas`/`openpyxl`
- [ ] Build column-mapping step (detected columns → email/first_name/
      last_name/custom fields)
- [ ] Build import validation: regex-based email format check, in-file
      duplicate detection, summary counts (`valid_count`,
      `duplicate_count`, `invalid_count`)
- [ ] Build recipient list detail page (paginated table)

**Acceptance**: Can upload a CSV of a few thousand rows, map columns
correctly, see accurate valid/duplicate/invalid counts, and browse the
imported recipients in a paginated table.

## Phase 4 — Quota tracking foundation (no sending yet)

- [ ] Implement `quota_checks` model
- [ ] Implement `services/quota.py`: `remaining_quota_today(sender)`
      function that queries `send_logs` (will return full quota since no
      sends exist yet — fine, this phase is about the plumbing)
- [ ] Wire the dashboard sender health grid to show real baseline quota
      and 0 used (since nothing sent yet)

**Acceptance**: Sender health grid on dashboard accurately reflects
configured baseline quotas per sender across all accounts.

## Phase 5 — Job creation & allocation (no actual sending yet)

- [ ] Implement `jobs` and `job_allocations` models
- [ ] Build the New Job wizard (template select, recipient list select,
      subject override, schedule choice)
- [ ] Implement `services/allocation.py` `build_allocation_plan()` per
      `BACKEND_SPEC.md` pseudocode
- [ ] Build the allocation preview screen in the job wizard — show which
      senders get how many recipients, and the "not enough quota" warning
      path
- [ ] Save job to DB with status `pending`, don't actually send anything
      yet

**Acceptance**: Can create a job, see an accurate allocation preview
based on real sender quotas, and see it land in the Jobs list with status
`pending`.

## Phase 6 — Celery + Redis + actual sending

- [ ] Set up Celery app, Redis connection, `celery_worker.py` entrypoint
- [ ] Implement `tasks/dispatch.py` `dispatch_job` task
- [ ] Implement `tasks/send.py` `send_recipient` task with the full
      `SingleSendMail` parameter mapping from `ALIBABA_INTEGRATION.md`
- [ ] Implement the error code → handling map (cooldown triggers, retry
      logic, etc.)
- [ ] Implement `send_logs` writing on every attempt
- [ ] Wire job status transitions (`pending` → `queued` → `sending` →
      `completed`/`completed_with_errors`)
- [ ] **Test with a small real list first** (e.g. 10-20 real addresses
      you control) before ever running a full 20k+ job — this is a hard
      requirement, not optional, given irreversible send actions and
      quota consumption

**Acceptance**: A small test job (10-20 recipients) sends successfully
through at least one real Alibaba account/sender, `send_logs` rows are
created accurately, sender quota-used numbers update correctly.

## Phase 7 — Live status (SSE) + Job detail page

- [ ] Implement `GET /jobs/<id>/status` SSE endpoint reading from Redis
      live counters (set these counters inside `send_recipient` on
      success/failure)
- [ ] Build the Job detail page per `FRONTEND_SPEC.md`: live counters,
      progress bar, per-sender breakdown table, failed recipients table
- [ ] Implement Pause/Resume/Cancel — Pause should stop new tasks being
      dispatched for that job without killing in-flight ones; Cancel
      should additionally mark remaining un-dispatched recipients as
      skipped
- [ ] Implement `GET /jobs/<id>/export-failed` CSV export

**Acceptance**: Running a real job shows live, accurate sent/failed
counters updating in near real-time in the browser without a manual
refresh, and a failed job's recipients can be exported with error reasons.

## Phase 8 — Quota health automation

- [ ] Implement Celery Beat schedule (`celery_beat.py`)
- [ ] Implement `tasks/scheduler.py` `review_sender_health` daily task:
      reset cooldowns, compute quota adjustment *suggestions* (surfaced in
      UI, not auto-applied per `ALIBABA_INTEGRATION.md`)
- [ ] Implement `tasks/scheduler.py` `poll_pending_jobs` task (checks for
      `scheduled_at <= now()` jobs and triggers dispatch — this is what
      makes the "schedule for later" feature actually fire)
- [ ] Surface quota-adjustment suggestions somewhere visible on the
      dashboard (e.g. a dismissible notice list)

**Acceptance**: A job scheduled for a future time actually fires
automatically at that time without manual intervention. A sender put into
cooldown yesterday is automatically reset to active this morning.

## Phase 9 — Polish & hardening

- [ ] CSRF protection audit on all POST routes
- [ ] Flask-Limiter on login route
- [ ] Error pages (404/500) styled consistently
- [ ] Logging setup (structured logs to file, rotated) for the Celery
      workers especially — this is where debugging send issues will
      happen most
- [ ] Basic automated tests for `allocation.py` and `quota.py` (these are
      the highest-risk business logic, worth real unit tests even if
      nothing else gets full coverage)
- [ ] Write a runbook section in `SETUP.md` for "what to do if a job gets
      stuck" and "how to manually override a sender's status"

**Acceptance**: App is ready for daily production use at real volume.

## Explicit non-goals for this plan (see also README.md)

Do not build these unless separately requested: attachments support,
built-in HTML template editor, open/click analytics dashboard beyond
Alibaba's native tracking, multi-user permission tiers, bounce/complaint
webhook ingestion.
