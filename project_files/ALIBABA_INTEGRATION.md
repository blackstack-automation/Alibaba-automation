# Alibaba DirectMail Integration Details

## SDK

```bash
pip install alibabacloud_dm20151123 alibabacloud_tea_openapi alibabacloud_credentials
```

## Client factory (`services/alibaba_client.py`)

```python
from alibabacloud_dm20151123.client import Client as DmClient
from alibabacloud_tea_openapi import models as open_api_models
from cryptography.fernet import Fernet
import os

def decrypt_secret(encrypted_value: str) -> str:
    key = os.environ["ENCRYPTION_KEY"].encode()
    f = Fernet(key)
    return f.decrypt(encrypted_value.encode()).decode()

def get_client_for_account(account) -> DmClient:
    """account is an Account model instance"""
    config = open_api_models.Config(
        access_key_id=account.access_key_id,
        access_key_secret=decrypt_secret(account.access_key_secret_encrypted),
        endpoint=account.region_endpoint,
    )
    return DmClient(config)
```

Cache clients per-account within a single Celery task invocation (don't
re-instantiate per recipient in a tight loop) but don't hold them across
tasks — each task call should build fresh from current DB state in case
credentials were rotated.

## `SingleSendMail` — full request parameter reference

Use this exact mapping when building the request object in
`tasks/send.py`.

| Param | Required | Source in our schema |
|---|---|---|
| `AccountName` | Yes | `sender_addresses.email_address` |
| `AddressType` | Yes | Always `1` (specific sender address) |
| `ReplyToAddress` | Yes | `"true"` if `sender_addresses.reply_to_address` is set, else `"false"` — **string, not boolean** |
| `Subject` | Yes | `jobs.subject_override` or `templates.subject_default`, truncate/validate ≤100 chars |
| `ToAddress` | Yes | `recipients.email_address` (single recipient per call in v1 — see batching note below) |
| `HtmlBody` | Conditional | `templates.html_body` |
| `TextBody` | Conditional | `templates.text_body` (one of HtmlBody/TextBody required) |
| `FromAlias` | No | `sender_addresses.from_alias`, ≤15 chars |
| `ClickTrace` | No | `"1"` if tracking enabled for the job (v2 feature, default `"0"`) |
| `TagName` | No | `f"job_{job.id}"` — lets us cross-reference in Alibaba's own console/reports |
| `ReplyAddress` | No | `sender_addresses.reply_to_address` |
| `ReplyAddressAlias` | No | `sender_addresses.reply_to_alias` |
| `UnSubscribeLinkType` | No | `default` (recommended, let Alibaba handle common ISPs) |
| `UnSubscribeFilterLevel` | No | `default` |

Response: `RequestId`, `EnvId` — store both in `send_logs`.

## Batching note (single recipient per call vs comma-joined)

`ToAddress` technically supports comma-separated addresses (up to 100),
but **v1 should send one recipient per call** because:
- Per-recipient personalization (first name, etc.) isn't supported by
  `SingleSendMail`'s comma-joined `ToAddress` — every recipient in one
  call gets the identical body
- Per-recipient success/failure tracking is cleaner — a single API error
  on a joined call is ambiguous about which of the N addresses failed
- Our rate-limiting and quota-counting logic is simpler at 1:1

If throughput becomes a bottleneck later, revisit `BatchSendMail`
(template-based, requires pre-registering both the template and the
recipient list *in Alibaba's system*, not just ours) as a v2 optimization.

## Error code → internal handling map

| Alibaba error code | Meaning | Our handling |
|---|---|---|
| `InvalidSendMail.Spam` | Frequency limit or quota exceeded | Mark sender `cooldown` immediately, log `send_logs.status='failed'`, do NOT retry this recipient on the same sender — requeue on a different sender if available, else leave for next job |
| `InvalidToAddress` / `InvalidReceiverName.Malformed` / `InvalidReceiver.NotFound` / `InvalidToAddress.Spam` | Bad recipient address | Mark recipient invalid, log failure, don't retry (retrying won't fix a bad address) |
| `InvalidMailAddress.NotFound` | Sender address not found/misconfigured | Mark sender `disabled`, alert admin (flash message / log), don't retry |
| `InvalidMailAddressStatus.Malformed` | Sender frozen | Mark sender `disabled`, alert admin |
| `InvalidBody` | HTML/text body malformed | Should be caught at template upload validation — if this fires at send time, fail the whole job and flag the template for review |
| `InvalidSubject.Malformed` | Subject > 100 chars | Should be caught at job-creation form validation |
| `InvalidFromAlias.Malformed` / `InvalidReplyAddressAlias.Malformed` | Alias > 15 chars | Should be caught at sender-creation form validation |
| `InvalidIP.NotFound` | IP protection misconfiguration | Mark sender `disabled`, alert admin — requires manual console check |
| Network/timeout errors | Transient | Retry up to 3x with exponential backoff (Celery `autoretry_for` + `retry_backoff`) |

## Quota/frequency limit handling (recap from architecture doc)

Alibaba's actual limit is **not a flat number we can fetch via a single
documented API call reliably** — it's account/sender reputation-based and
can change. Our approach:

1. Seed `baseline_daily_quota` manually per sender based on what's visible
   in the Alibaba console.
2. Track actual sends per sender per day via `send_logs`.
3. Treat `InvalidSendMail.Spam` as ground truth — if it fires, we're over
   the real limit *right now*, regardless of our estimate. Immediately
   cooldown that sender for the rest of the day.
4. Each morning (scheduled Celery Beat task `review_sender_health`):
   - Reset any `cooldown` senders back to `active` (Alibaba's limits are
     typically daily-rolling)
   - If a sender had zero failures over the trailing 7 days AND
     consistently used >80% of its quota, propose a baseline increase
     (log a suggestion; **do not auto-increase without human confirmation
     in v1** — surface it in the dashboard as a "Consider raising quota
     for Sender X" notice instead)
   - If a sender hit cooldown more than twice in 7 days, propose a
     baseline decrease and flag for review

## Warm-up guidance (for new accounts/senders)

Document this as operational guidance (not hard-coded logic in v1, since
warm-up schedules are inherently judgment calls):

- New sender: start `baseline_daily_quota` low (e.g. 50-100/day)
- Increase gradually over 1-2 weeks as delivery stays clean, watching the
  Alibaba console's own reputation/limit indicators
- Avoid sending to unverified/cold lists during warm-up — reserve
  warm-up sends for your highest-quality, most-engaged recipients if
  possible

## Rate limiting at the application layer

Even within a single sender's quota, sending too fast can itself trigger
throttling independent of the daily cap. Recommend:
- Global send rate cap configurable via `SEND_RATE_LIMIT_PER_SECOND` env
  var (start conservative, e.g. 3-5/sec across the whole app, tune up
  after observing stability)
- Implement via Celery task rate limiting:
  `@celery.task(rate_limit='5/s')` on `send_recipient`
