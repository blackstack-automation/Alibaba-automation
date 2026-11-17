# Frontend Spec

## Stack

- **Jinja2** server-rendered templates (Flask default) — no separate
  frontend build/deploy step
- **HTMX** for partial page updates (form submissions, table refreshes)
  without full page reloads
- **Alpine.js** for small client-side interactivity (dropdowns, modals,
  live counter animation)
- **Server-Sent Events** for the live job status stream on the job detail
  page
- **Tailwind CSS** (via CDN or CLI build) for styling — utility-first,
  fast to iterate, no design system to build from scratch
- **Chart.js** for the quota-history sparkline/chart on sender detail pages

This keeps the whole app as one Flask codebase, no separate frontend
repo/build pipeline — consistent with the rest of the Dev TV stack.

## Site map

```
/                              Dashboard (overview)
/auth/login                    Login
/accounts                      Accounts list
/accounts/new                  Add account
/accounts/<id>/edit            Edit account
/accounts/<id>/senders         Senders for this account
/accounts/<id>/senders/new     Add sender
/senders/<id>/edit             Edit sender
/senders/<id>/quota-history    Sender quota chart (partial, loaded via HTMX)
/mail-templates                Templates list
/mail-templates/new            Upload template
/mail-templates/<id>           Template detail/preview
/recipients                    Recipient lists
/recipients/upload             Upload wizard
/recipients/<id>                List detail (paginated recipient table)
/jobs                          Jobs list
/jobs/new                      New job wizard
/jobs/<id>                     Job detail (live status)
```

## Page-by-page detail

### Dashboard (`/`)

**Purpose**: at-a-glance system health, first thing seen on login.

Sections:
1. **Today's totals** — big numbers: total sent today (all accounts),
   total failed today, overall success rate %
2. **Active jobs** — cards for any job currently `sending`, each showing
   live sent/failed/total (auto-refreshing via HTMX polling every 3s or
   SSE)
3. **Sender health grid** — table of all senders across all accounts:
   account label, sender email, status badge (active/cooldown/warming
   up/disabled), quota used today (progress bar: sent_today /
   baseline_daily_quota), last cooldown reason if applicable
4. **Quick actions** — "New Job", "Upload Recipients", "Add Account"
   buttons

### Accounts list (`/accounts`)

Table: Label | Sender count | Status | Actions (Edit/Senders/Delete)
"+ Add Account" button top right.

### Add/Edit Account (`/accounts/new`, `/accounts/<id>/edit`)

Form fields:
- Label (text)
- Access Key ID (text)
- Access Key Secret (password-style input, masked, shows "••••" on edit
  with an option to replace)
- Region endpoint (dropdown, default `dm.aliyuncs.com`)
- Notes (textarea, optional)

Buttons: "Test Connection" (AJAX call, shows green check or red error
inline before allowing save), "Save"

### Senders list (`/accounts/<id>/senders`)

Table: Email | Alias | Status | Baseline quota | Sent today | Actions
"+ Add Sender" button.

### Add/Edit Sender

Form fields:
- Email address
- From alias (max 15 chars, live character counter)
- Reply-to address / alias (optional)
- Baseline daily quota (number input, with helper text explaining this is
  a manually-tracked estimate that should be adjusted based on observed
  Alibaba console limits)
- Status (dropdown: active/warming_up/cooldown/disabled — manual override)

### Templates list (`/mail-templates`)

Card grid (not table) — each card shows a thumbnail-style preview (iframe
scaled down via CSS transform), name, size in KB, last used date, size
warning badge if close to 80KB limit.

### Upload Template (`/mail-templates/new`)

- Name (text)
- Default subject (text, max 100 chars, live counter)
- Upload method: tabs for "Upload .html file" vs "Paste HTML"
- Live preview pane (iframe, sandboxed, updates on paste/upload)
- Size validation message (red if over 80KB, shows exact KB)
- Optional plaintext body (textarea)

### Recipients list (`/recipients`)

Table: List name | Total | Valid | Duplicates | Invalid | Uploaded | Actions
"+ Upload List" button.

### Upload wizard (`/recipients/upload`)

Multi-step (can be one page with Alpine.js step state, no need for full
page reloads):
1. **Upload** — file picker (CSV/XLSX), drag-drop zone
2. **Map columns** — after upload, show detected columns with dropdowns to
   map to `email_address` (required), `first_name`, `last_name`, or "Custom
   field" for anything else
3. **Review** — summary before commit: X total rows, Y valid emails, Z
   duplicates found (within file), W invalid format — table preview of
   first 20 rows
4. **Confirm** — commits to DB, redirects to list detail page

### Recipient list detail (`/recipients/<id>`)

Paginated table of recipients (search/filter by email). Delete list
button (with confirmation modal — destructive action).

### Jobs list (`/jobs`)

Table: Name | Template | Recipient list | Status badge | Sent/Total |
Scheduled/Started | Actions (View, Cancel if pending/sending)

Status badges color-coded:
- `pending` — gray
- `queued` — blue
- `sending` — blue, pulsing/animated
- `completed` — green
- `completed_with_errors` — yellow
- `failed` — red
- `cancelled` — gray, strikethrough

### New Job wizard (`/jobs/new`)

Steps:
1. **Name** the job (auto-suggested from template + date)
2. **Select template** (dropdown with preview thumbnail)
3. **Select recipient list** (dropdown showing valid count)
4. **Subject** — pre-filled from template default, editable
5. **Schedule** — radio: "Send immediately" / "Schedule for later"
   (datetime picker if scheduled)
6. **Allocation preview** — before confirming, show a table: which
   senders will be used and how many recipients each will get, computed
   from `build_allocation_plan()`. If total available quota < recipient
   count, show a clear warning: "Only X of Y recipients can be sent today
   given current quota. Remaining Z will need a follow-up job tomorrow."
   with an option to proceed with partial send or cancel.
7. **Confirm & Create**

### Job detail (`/jobs/<id>`)

**This is the most important page** — the "live status" the user asked
for.

Layout:
- Header: job name, status badge, template name, recipient list name,
  created/started/completed timestamps
- **Live counters** (large, prominent): Sent (green) | Failed (red) |
  Remaining (gray) | Total — updates via SSE stream while status is
  `sending`, connection auto-closes when job completes
- **Progress bar** — sent+failed / total, animated
- **Per-sender breakdown table** — sender email, allocated count, sent,
  failed, % complete — updates alongside the live counters
- **Failed recipients table** (paginated) — email, sender used, error
  code, error message, timestamp. "Export Failed as CSV" button.
- **Controls**: Pause / Resume / Cancel buttons (visible based on current
  status — e.g. Pause only shown while `sending`)

## Component notes for Claude Code

- Build a shared `_status_badge.html` Jinja partial/macro for consistent
  status coloring across Jobs list, Job detail, and Sender status.
- Build a shared `_flash_messages.html` partial for form success/error
  banners.
- All destructive actions (delete account, delete sender, delete
  recipient list, cancel job) go through a confirmation modal — use a
  single reusable Alpine.js modal component, not one-off modals per page.
- Use HTMX `hx-boost` on the main nav for fast page transitions without a
  full SPA rewrite.
- Mobile responsiveness is a nice-to-have, not a priority — this is an
  internal ops tool primarily used on desktop.
