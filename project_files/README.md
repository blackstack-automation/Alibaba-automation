# Alibaba DirectMail Orchestration Dashboard

## What this is

A self-hosted platform to replace manual sending via the Alibaba Cloud DirectMail
console. It lets us:

- Connect multiple Alibaba Cloud accounts (AccessKey/Secret pairs)
- Track sender addresses ("servers") within each account, along with their
  current sending quota/reputation
- Upload recipient lists (CSV/XLSX)
- Upload/manage HTML email templates
- Launch a send job that intelligently distributes recipients across
  accounts/senders based on available quota, respecting Alibaba's rate limits
- Watch live sent/failed counters while a job runs
- Review a log of every send attempt (success + failure reason)

Target volume: 20,000–30,000 emails/day, scaling across multiple Alibaba
accounts and sender addresses as quota allows.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Flask (Python 3.11+) | Matches existing Dev TV stack |
| DB | SQLite (WAL mode) | Matches existing Dev TV stack; sufficient for this scale |
| Job queue / workers | Celery + Redis (or RQ + Redis as lighter alternative) | Needed for rate-limited, resumable, concurrent sending |
| Alibaba SDK | `alibabacloud_dm20151123` + `alibabacloud_tea_openapi` | Official V2.0 Python SDK |
| Frontend | Server-rendered Jinja2 templates + HTMX + Alpine.js | No heavy SPA build step, fast to ship, matches Flask-first stack; swap to React later if needed |
| Realtime updates | Server-Sent Events (SSE) or polling every 2-3s | Simplest way to get "live" counters without a websocket server |
| Auth | Flask-Login, single-team internal tool | Not multi-tenant SaaS — internal use only |
| Hosting | Existing ₹499/mo VPS (4 vCPU / 8GB RAM / 200GB SSD) | Already provisioned for the social media tool; this app is lighter |

## Document index

Read in this order when starting development in Claude Code:

1. `ARCHITECTURE.md` — system design, components, data flow, job lifecycle
2. `DATABASE_SCHEMA.md` — full SQLite schema, every table/column/relationship
3. `BACKEND_SPEC.md` — Flask app structure, folder layout, routes, worker logic
4. `FRONTEND_SPEC.md` — pages, components, wireframe-level UI detail
5. `ALIBABA_INTEGRATION.md` — SDK usage, quota handling, rate limiting, error mapping
6. `DEVELOPMENT_PLAN.md` — phased build order with acceptance criteria per phase
7. `SETUP.md` — environment variables, dependencies, local dev, deployment steps

## Non-goals (explicitly out of scope for v1)

- Multi-tenant / multi-user permissions (single internal team only)
- Attachments (Alibaba `SingleSendMail` doesn't support them)
- Built-in template editor/WYSIWYG (templates are uploaded as raw HTML files
  produced elsewhere)
- Open/click tracking dashboards beyond what Alibaba's `ClickTrace` param
  natively provides (bounce/complaint webhook integration is a v2 item)
- Automatic list-cleaning/verification (assume lists are pre-verified via the
  existing ValidReach tooling)

## Naming convention used throughout these docs

- "Account" = one Alibaba Cloud account (AccessKey/Secret pair)
- "Sender" = one verified sender address within an Alibaba account (referred
  to as "server" colloquially, but stored/modeled as `sender_addresses`)
- "Job" = one send operation: one template + one recipient list (or segment)
  + a set of eligible senders + a schedule
- "Attempt" = one `SingleSendMail` API call for one recipient, logged with its
  result
