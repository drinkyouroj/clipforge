# Week 4: Billing + Polish + Launch — Design Spec

## Goal

Add Stripe subscription billing, account management, a public landing page, video lifecycle cleanup, and legal placeholder pages to complete ClipForge for launch. Tag v1.0.0 on completion.

## Context

Weeks 1-3 built the full pipeline: upload → transcription → clip detection → rendering → export. Week 4 adds monetization, user-facing polish, and operational hygiene. The system currently has 6 DB tables, JWT auth with httpOnly cookies, ARQ job queue, and S3/R2 storage.

---

## 1. Database Schema Changes

### User Model — New Columns

| Column | Type | Default | Notes |
|--------|------|---------|-------|
| `stripe_customer_id` | String(255), nullable, unique | null | Created on first Stripe checkout |
| `subscription_tier` | String(20), not null | `"free"` | CHECK: `free`, `starter`, `pro` |
| `subscription_stripe_id` | String(255), nullable | null | Stripe subscription ID |
| `current_period_end` | DateTime(tz), nullable | null | End of current billing cycle |
| `period_exports_used` | Integer, not null | 0 | Reset on each `invoice.paid` webhook |

### Tier Definitions (Application Constants)

| Tier | Monthly Price | Export Limit | Stripe Price ID Source |
|------|--------------|--------------|----------------------|
| `free` | $0 | 10 | (none) |
| `starter` | $19 | 100 | `STRIPE_PRICE_STARTER` env var |
| `pro` | $49 | unlimited (None) | `STRIPE_PRICE_PRO` env var |

No new tables. User model holds all billing state. Single Alembic migration adds 5 columns.

---

## 2. Stripe Integration

### Module: `backend/app/billing/`

| File | Responsibility |
|------|---------------|
| `router.py` | HTTP endpoints |
| `service.py` | Stripe API calls, credit checks, webhook processing |
| `schemas.py` | Pydantic request/response models |

### Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST /billing/checkout` | JWT required | Creates Stripe Checkout Session for selected tier, returns redirect URL |
| `POST /billing/portal` | JWT required | Creates Stripe Billing Portal session for subscription management |
| `POST /billing/webhook` | No auth (Stripe signature) | Receives and processes Stripe webhook events |
| `GET /billing/status` | JWT required | Returns current tier, exports used, exports remaining, period end |

### Webhook Events

| Event | Action |
|-------|--------|
| `checkout.session.completed` | Set `stripe_customer_id`, `subscription_tier`, `subscription_stripe_id`, `current_period_end` on User |
| `invoice.paid` | Reset `period_exports_used` to 0, update `current_period_end` |
| `customer.subscription.updated` | Update `subscription_tier` to match new plan (handles upgrades/downgrades) |
| `customer.subscription.deleted` | Reset `subscription_tier` to `free`, clear `subscription_stripe_id` and `current_period_end` |

### Credit Enforcement

Modify existing `POST /exports` endpoint: before creating the export, check if the user's tier has a limit and `period_exports_used >= limit`. Return HTTP 402 with message "Export limit reached. Upgrade your plan." if exceeded. Increment `period_exports_used` on successful export creation.

### Webhook Security

- Verify Stripe signature using `STRIPE_WEBHOOK_SECRET` and `stripe.Webhook.construct_event()`
- Return 200 immediately to prevent Stripe retries on processing errors (process async if needed)
- Idempotent handling: check if subscription state already matches before updating

### Configuration (.env additions)

```
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_STARTER=price_...
STRIPE_PRICE_PRO=price_...
```

---

## 3. Video Lifecycle & Cleanup

### User-Initiated Delete (Enhanced)

Current `DELETE /videos/{id}` only sets `deleted_at`. Enhanced flow:

1. Set `deleted_at` on Video record (existing behavior)
2. Delete S3 source object immediately (`video.s3_key`)
3. Find all exports for this video's clips — delete their S3 objects
4. Cancel any in-progress jobs for this video (set status to `failed`, error_message: "video deleted by user")
5. DB records (video, transcript, clips, exports, jobs) remain for 7 days

### Daily Cleanup ARQ Task: `cleanup_expired_content`

Scheduled to run once per day via ARQ cron. Two responsibilities:

1. **Purge soft-deleted videos (7+ days):** Hard-delete DB rows for videos where `deleted_at` is set and older than 7 days. Cascade through transcript, clips, exports, jobs. Delete any remaining S3 objects as safety net.

2. **Auto-expire old videos (30+ days):** For videos where `deleted_at IS NULL` and `created_at < now() - 30 days`:
   - Delete S3 source object and all export S3 objects
   - Set `deleted_at` to now, set `status` to `deleted`
   - Cancel in-progress jobs
   - These records will be hard-deleted 7 days later by rule 1

No S3 lifecycle policy needed. The ARQ task provides full visibility and logging.

### Modification to `soft_delete_video` Service

Rename/extend to handle immediate S3 cleanup. The service function gains S3 deletion, export S3 cleanup, and job cancellation responsibilities.

---

## 4. Account Page

### Route: `/account`

Accessible from dashboard header ("Account" link next to "Log out").

### Sections

1. **Profile** — email display, account creation date. Read-only for MVP.

2. **Subscription** — current tier badge, period end date, exports used vs. limit with progress bar.
   - Free users: "Upgrade" button → Stripe Checkout
   - Paid users: "Manage Subscription" button → Stripe Billing Portal

3. **Export History** — table of recent exports (last 30 days). Columns: clip title, platform, status, created date, download link (if rendered).

### New API Endpoint

`GET /exports/` — returns list of all exports for the current user, ordered by `created_at` desc. Supports `?limit=50&offset=0` pagination.

### Frontend

Single `AccountPage.tsx` component. No sub-components needed.

---

## 5. Landing Page

### Route: `/` (when unauthenticated)

Routing change: `/` shows `LandingPage` when logged out, `Dashboard` when logged in.

### Sections (top to bottom)

1. **Hero** — headline ("Turn long videos into viral clips with AI"), one-sentence subheadline, CTA button → `/register`
2. **How It Works** — 3 numbered steps: Upload → AI Detects Clips → Export
3. **Features** — 3-4 cards: AI virality scoring, smart reframe, animated captions, multi-platform export
4. **Pricing** — 3-column tier comparison (Free / Starter $19 / Pro $49) with feature rows and CTA buttons
5. **Footer** — links to `/terms`, `/privacy`, `/login`

All static content. No backend endpoints needed.

---

## 6. Legal Pages

### Routes: `/terms` and `/privacy`

Static React components rendering styled placeholder text.

**Terms of Service sections:** Acceptance of Terms, Service Description, User Content & Ownership, Acceptable Use, Limitation of Liability, Termination, Changes to Terms, Contact.

**Privacy Policy sections:** Data We Collect, How We Use It, Data Retention (30-day auto-delete), Data Deletion (user-initiated), Third-Party Services (Stripe, OpenAI Whisper, Anthropic Claude), Contact.

Placeholder text — swap in real legal copy from Termly or lawyer before public launch.

---

## 7. File Structure (New/Modified)

### New Files

```
backend/app/billing/__init__.py
backend/app/billing/router.py         # 4 endpoints
backend/app/billing/service.py        # Stripe API, credit checks, webhook processing
backend/app/billing/schemas.py        # Pydantic models
backend/tests/unit/test_billing.py    # Billing endpoint + webhook tests
backend/tests/unit/test_cleanup.py    # Cleanup task tests

frontend/src/pages/LandingPage.tsx
frontend/src/pages/AccountPage.tsx
frontend/src/pages/TermsPage.tsx
frontend/src/pages/PrivacyPage.tsx
```

### Modified Files

```
backend/app/db/models.py              # 5 new User columns
backend/app/config.py                 # 4 new Stripe settings
backend/app/main.py                   # Register billing router
backend/app/export/router.py          # Credit check on POST, new GET / endpoint
backend/app/videos/service.py         # Enhanced delete with S3 cleanup
backend/app/jobs/worker.py            # Register cleanup task
backend/app/jobs/tasks.py             # cleanup_expired_content task
backend/requirements.txt              # Add stripe package

frontend/src/App.tsx                  # New routes, conditional landing/dashboard
frontend/src/App.css                  # Landing, account, legal page styles
frontend/src/api/client.ts            # Billing API calls (if extracted)
```

### Alembic Migration

Single migration: add `stripe_customer_id`, `subscription_tier`, `subscription_stripe_id`, `current_period_end`, `period_exports_used` to `users` table.

---

## 8. DECISION Protocol

DECISION_008 (billing model) is required before implementing Stripe integration. Covers: data model on User vs separate table, webhook event handling, credit enforcement placement, failure modes (webhook miss, double-charge, subscription state drift).

No other decisions required — video cleanup and frontend pages don't involve the architectural stakes that trigger the protocol.
