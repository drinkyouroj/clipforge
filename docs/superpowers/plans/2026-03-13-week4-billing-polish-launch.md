# Week 4: Billing + Polish + Launch — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Stripe subscription billing, account management, landing page, video lifecycle cleanup, and legal pages to complete ClipForge for v1.0.0 launch.

**Architecture:** Stripe handles subscription lifecycle via webhooks; User model holds billing state (tier, credits, period end). Enhanced video delete does immediate S3 cleanup with soft-delete DB retention. Daily ARQ cron task handles auto-expiry and hard-delete. Frontend adds 4 new pages (landing, account, terms, privacy).

**Tech Stack:** Stripe Python SDK, FastAPI, SQLAlchemy async, ARQ cron jobs, React + TypeScript

---

## Chunk 1: Database + Billing Backend

### Task 1: DECISION_008 — Billing Model

**Files:**
- Create: `docs/decisions/DECISION_008_billing_model.md`

- [ ] **Step 1: Write DECISION_008 using the Adversarial Agent Protocol**

Write the three-agent decision document. The design is already settled in the spec — this formalizes it.

```markdown
# DECISION 008: Billing Model

## ARCHITECT proposes:
- Credit-based subscriptions with 3 tiers: free (10 exports/mo), starter ($19/mo, 100), pro ($49/mo, unlimited)
- Billing state stored on User model (5 new columns), no separate tables
- Stripe Checkout for subscription creation, Stripe Billing Portal for management
- Atomic credit enforcement via UPDATE...WHERE...RETURNING to prevent race conditions
- Free-tier resets via daily ARQ cron that advances `current_period_end` by one month
- Webhook events: checkout.session.completed, invoice.paid, customer.subscription.updated, customer.subscription.deleted
- Out-of-order webhook protection via Stripe event timestamp comparison against User.updated_at

## ADVERSARY attacks:
1. **Webhook delivery failure:** If `invoice.paid` webhook is lost, the user's `period_exports_used` never resets. They hit the limit mid-cycle and can't export despite paying. Stripe retries for up to 3 days, but if all retries fail (endpoint down, deploy mishap), the user is stuck until manual intervention.
2. **Double-charge on concurrent checkout:** If a user opens two checkout tabs simultaneously, `checkout.session.completed` fires twice, potentially creating two Stripe subscriptions. The second webhook overwrites `subscription_stripe_id`, orphaning the first subscription which keeps billing.
3. **Tier drift on downgrade:** User downgrades from pro to starter mid-cycle. `customer.subscription.updated` fires. If they've already used 95 exports this period, they're now over their new limit. The atomic UPDATE would block further exports, but the user already consumed more than they're "allowed" under the new tier. Is that a problem or expected?
4. **Free-tier counter manipulation:** `current_period_end` is set at registration. A user could register, use 10 exports, delete account, re-register with the same email to get another 10. The `register_user` function doesn't check for soft-deleted accounts.

## JUDGE decides:
Green light with mitigations:
1. **Webhook miss:** The daily cleanup cron already resets counters for users where `current_period_end < now()`. This is a safety net. Acceptable — users wait at most 24 hours for reset if webhook fails. Document that the billing status endpoint should also do a Stripe API check as a future enhancement.
2. **Double checkout:** Add a guard in checkout endpoint: if user already has `subscription_stripe_id` set, return 400 "Already subscribed. Use the billing portal to change plans." Prevents concurrent checkout entirely.
3. **Tier drift:** Expected behavior. Downgrades take effect at period end in Stripe's model. The `customer.subscription.updated` event for a downgrade should NOT immediately change the tier — only update when the new period starts (via `invoice.paid`). Map Stripe's `subscription.items.data[0].price.id` to determine the new tier, but only apply it when `current_period_start` changes.
4. **Free-tier manipulation:** Acceptable risk for MVP. Email uniqueness constraint prevents same-email re-registration unless account is hard-deleted (7+ days). The attack window is narrow and the cost is 10 free exports.

## Implementation notes:
- Guard checkout endpoint against already-subscribed users
- Downgrade tier change applies at next period, not immediately
- Daily cron is the safety net for missed webhooks
- `period_exports_used` atomic increment via SQL UPDATE...WHERE...RETURNING
```

- [ ] **Step 2: Commit DECISION_008**

```bash
git add docs/decisions/DECISION_008_billing_model.md
git commit -m "docs(decisions): add DECISION_008 billing model"
```

---

### Task 2: DECISION_009 — Video Lifecycle & Cleanup

**Files:**
- Create: `docs/decisions/DECISION_009_video_lifecycle.md`

- [ ] **Step 1: Write DECISION_009 using the Adversarial Agent Protocol**

```markdown
# DECISION 009: Video Lifecycle & Cleanup

## ARCHITECT proposes:
- Enhanced user-initiated delete: immediate S3 cleanup (source + all export S3 objects), soft-delete DB records, cancel in-progress ARQ jobs via `Job.abort()`
- DB records retained 7 days after soft-delete for potential undo
- Daily ARQ cron task (`cleanup_expired_content`) with two responsibilities:
  1. Hard-delete DB rows for videos with `deleted_at` > 7 days (cascade: transcript, clips, exports, jobs). Safety-net S3 delete for any remaining objects.
  2. Auto-expire videos with `created_at` > 30 days and `deleted_at IS NULL`: run same S3 cleanup flow, set status=deleted, set deleted_at=now.
- Also resets `period_exports_used` for users where `current_period_end < now()` (free-tier reset + webhook miss safety net)
- No S3 lifecycle policy — application-level cleanup for full visibility

## ADVERSARY attacks:
1. **Cleanup task fails midway:** If the cron crashes after deleting S3 objects for 25 of 50 expired videos but before marking them as deleted in DB, those 25 videos have no S3 data but DB still shows them as active. User tries to view/export and gets S3 404 errors.
2. **Concurrent render + auto-expire race:** A render job downloads a video from S3 at T=0. At T=1, the cleanup cron deletes that video's S3 object (30 days old). The render job continues with the local copy and succeeds, uploading a rendered clip. But the video is now soft-deleted — the rendered export is orphaned and will be cleaned up in 7 days. The user gets a confusing experience: export appears to succeed but the source video is gone.
3. **ARQ job abort timing:** `Job.abort()` is best-effort. If a worker has already dequeued the job and started processing, abort won't stop it. The worker checks job status at the start, but there's a window between dequeue and status check where the delete and the job run concurrently.
4. **Hard-delete cascade failures:** If `DELETE FROM videos WHERE id = X` cascades through 4 tables with foreign keys, a single constraint violation (e.g., an export FK to a job that was already deleted) could fail the entire batch. The cron processes multiple videos — does one failure stop the whole run?

## JUDGE decides:
Green light with mitigations:
1. **Midway crash:** Process videos one at a time in a transaction. For each video: begin txn → delete S3 → update DB → commit. If S3 delete succeeds but DB update fails, the next cron run will retry (S3 delete of a non-existent object is a no-op). If DB update succeeds but S3 delete fails, the safety-net S3 delete on hard-delete catches it. Acceptable.
2. **Render + expire race:** The 30-day window makes this extremely unlikely for legitimate use. Add a guard: skip auto-expire for videos that have any job with `status = 'running'`. If a render is in progress, wait until next cron cycle.
3. **ARQ abort timing:** Acceptable. The render pipeline checks export/job status at each stage transition (prepare → execute → upload). If the video was deleted mid-render, the next stage will find the export status is `failed` and bail. Add a status check at the start of each pipeline stage.
4. **Cascade failures:** Use per-video transactions. Delete in dependency order: exports → clips → transcript → jobs → video. If one video fails, log the error and continue to the next. Never let one failure stop the entire batch.

## Implementation notes:
- Process one video per transaction in cleanup task
- Skip auto-expire for videos with running jobs
- Delete in dependency order: exports → clips → transcript → jobs → video
- Each render pipeline stage should check if export is still valid before proceeding
- S3 delete failures are logged but don't block DB cleanup
```

- [ ] **Step 2: Commit DECISION_009**

```bash
git add docs/decisions/DECISION_009_video_lifecycle.md
git commit -m "docs(decisions): add DECISION_009 video lifecycle and cleanup"
```

---

### Task 3: Database Schema — Billing Columns on User + Migration

**Files:**
- Modify: `backend/app/db/models.py:26-43` (User class)
- Create: Alembic migration (auto-generated)
- Test: `backend/tests/unit/test_billing_models.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_billing_models.py`:

```python
"""Tests for billing columns on User model."""

from datetime import datetime, timezone

import pytest
import pytest_asyncio

from app.db.models import User


@pytest_asyncio.fixture
async def user_with_billing(db_session):
    """Create a user with billing fields set."""
    user = User(
        email="billing@example.com",
        hashed_password="hashed",
        tos_accepted_at=datetime.now(timezone.utc),
        stripe_customer_id="cus_test123",
        subscription_tier="starter",
        subscription_stripe_id="sub_test456",
        current_period_end=datetime(2026, 4, 1, tzinfo=timezone.utc),
        period_exports_used=5,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_user_billing_defaults(db_session):
    """New users should have free tier and zero exports used."""
    user = User(
        email="free@example.com",
        hashed_password="hashed",
        tos_accepted_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    assert user.subscription_tier == "free"
    assert user.period_exports_used == 0
    assert user.stripe_customer_id is None
    assert user.subscription_stripe_id is None
    assert user.current_period_end is None


@pytest.mark.asyncio
async def test_user_billing_fields_persist(user_with_billing):
    """Billing fields should round-trip through the database."""
    assert user_with_billing.stripe_customer_id == "cus_test123"
    assert user_with_billing.subscription_tier == "starter"
    assert user_with_billing.subscription_stripe_id == "sub_test456"
    assert user_with_billing.period_exports_used == 5
    assert user_with_billing.current_period_end is not None


@pytest.mark.asyncio
async def test_subscription_tier_check_constraint(db_session):
    """Invalid subscription_tier should be rejected by CHECK constraint."""
    user = User(
        email="invalid@example.com",
        hashed_password="hashed",
        tos_accepted_at=datetime.now(timezone.utc),
        subscription_tier="platinum",
    )
    db_session.add(user)
    with pytest.raises(Exception):  # IntegrityError from CHECK constraint
        await db_session.commit()


@pytest.mark.asyncio
async def test_stripe_customer_id_unique(db_session):
    """Two users cannot share the same stripe_customer_id."""
    user1 = User(
        email="u1@example.com",
        hashed_password="hashed",
        tos_accepted_at=datetime.now(timezone.utc),
        stripe_customer_id="cus_shared",
    )
    user2 = User(
        email="u2@example.com",
        hashed_password="hashed",
        tos_accepted_at=datetime.now(timezone.utc),
        stripe_customer_id="cus_shared",
    )
    db_session.add(user1)
    await db_session.flush()
    db_session.add(user2)
    with pytest.raises(Exception):  # IntegrityError from UNIQUE constraint
        await db_session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/unit/test_billing_models.py -v
```

Expected: FAIL — `User` model does not have `stripe_customer_id` attribute.

- [ ] **Step 3: Add billing columns to User model**

In `backend/app/db/models.py`, add after the `updated_at` column (line 39) inside the `User` class:

```python
    # Billing
    stripe_customer_id = Column(String(255), nullable=True, unique=True)
    subscription_tier = Column(String(20), nullable=False, default="free")
    subscription_stripe_id = Column(String(255), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    period_exports_used = Column(Integer, nullable=False, default=0)
```

Also add the CHECK constraint to `__table_args__`. The User class currently has no `__table_args__`, so add:

```python
    __table_args__ = (
        CheckConstraint(
            "subscription_tier IN ('free', 'starter', 'pro')",
            name="ck_users_subscription_tier",
        ),
    )
```

Add `Integer` to the imports from `sqlalchemy` (already imported).

- [ ] **Step 4: Generate Alembic migration**

```bash
cd /Users/justin/CascadeProjects/clipforge/backend && alembic revision --autogenerate -m "add billing columns to users"
```

- [ ] **Step 5: Run migration**

```bash
cd /Users/justin/CascadeProjects/clipforge/backend && alembic upgrade head
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/unit/test_billing_models.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 7: Run full test suite to check for regressions**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/ -v
```

Expected: All 104+ tests PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/db/models.py backend/app/db/migrations/versions/ backend/tests/unit/test_billing_models.py
git commit -m "feat(db): add billing columns to users — tier, credits, stripe IDs"
```

---

### Task 4: Config + Stripe Settings

**Files:**
- Modify: `backend/app/config.py`
- Modify: `.env.example`
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add Stripe settings to config**

In `backend/app/config.py`, add after line 19 (`render_rate_limit_free`):

```python
    frontend_url: str = "http://localhost:5173"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_pro: str = ""
```

- [ ] **Step 2: Add stripe to requirements.txt**

Add to `backend/requirements.txt`:

```
stripe==8.4.0
```

- [ ] **Step 3: Update .env.example**

Add at the end of `.env.example`:

```
# Stripe Billing
STRIPE_SECRET_KEY=sk_test_your-stripe-secret-key
STRIPE_WEBHOOK_SECRET=whsec_your-webhook-secret
STRIPE_PRICE_STARTER=price_your-starter-price-id
STRIPE_PRICE_PRO=price_your-pro-price-id
```

- [ ] **Step 4: Install stripe package**

```bash
cd /Users/justin/CascadeProjects/clipforge/backend && pip install stripe==8.4.0
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/requirements.txt .env.example
git commit -m "chore(billing): add Stripe config, env vars, and package dependency"
```

---

### Task 5: Billing Schemas

**Files:**
- Create: `backend/app/billing/__init__.py`
- Create: `backend/app/billing/schemas.py`

- [ ] **Step 1: Create billing module**

Create empty `backend/app/billing/__init__.py`.

- [ ] **Step 2: Create billing schemas**

Create `backend/app/billing/schemas.py`:

```python
"""Pydantic schemas for billing API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class CheckoutRequest(BaseModel):
    tier: Literal["starter", "pro"]


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str


class BillingStatusResponse(BaseModel):
    subscription_tier: str
    period_exports_used: int
    exports_limit: int | None  # None = unlimited (pro)
    exports_remaining: int | None  # None = unlimited (pro)
    current_period_end: datetime | None

    class Config:
        from_attributes = True
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/billing/__init__.py backend/app/billing/schemas.py
git commit -m "feat(billing): add billing schemas — checkout, portal, status"
```

---

### Task 6: Billing Service

**Files:**
- Create: `backend/app/billing/service.py`
- Test: `backend/tests/unit/test_billing.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_billing.py`:

```python
"""Tests for billing service and endpoints."""

from datetime import datetime, timezone, timedelta
from uuid import uuid4
from unittest.mock import patch, MagicMock

import pytest
import pytest_asyncio

from app.db.models import User


TIER_LIMITS = {"free": 10, "starter": 100, "pro": None}


@pytest_asyncio.fixture
async def auth_client(client):
    """Client that is logged in."""
    await client.post("/auth/register", json={
        "email": "billinguser@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "billinguser@example.com",
        "password": "StrongPass123!",
    })
    return client


# --- Billing Status Tests ---

@pytest.mark.asyncio
async def test_billing_status_free_user(auth_client):
    """Free user should see tier=free, limit=10."""
    resp = await auth_client.get("/billing/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["subscription_tier"] == "free"
    assert data["exports_limit"] == 10
    assert data["period_exports_used"] == 0
    assert data["exports_remaining"] == 10


@pytest.mark.asyncio
async def test_billing_status_starter_user(auth_client, db_session):
    """Starter user should see limit=100."""
    me = await auth_client.get("/auth/me")
    user_id = me.json()["id"]
    from sqlalchemy import select
    from app.db.models import User
    result = await db_session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    user.subscription_tier = "starter"
    user.period_exports_used = 42
    await db_session.commit()

    resp = await auth_client.get("/billing/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["subscription_tier"] == "starter"
    assert data["exports_limit"] == 100
    assert data["period_exports_used"] == 42
    assert data["exports_remaining"] == 58


@pytest.mark.asyncio
async def test_billing_status_pro_user(auth_client, db_session):
    """Pro user should see unlimited (null limit)."""
    me = await auth_client.get("/auth/me")
    user_id = me.json()["id"]
    from sqlalchemy import select
    from app.db.models import User
    result = await db_session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    user.subscription_tier = "pro"
    await db_session.commit()

    resp = await auth_client.get("/billing/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["subscription_tier"] == "pro"
    assert data["exports_limit"] is None
    assert data["exports_remaining"] is None


@pytest.mark.asyncio
async def test_billing_status_unauthenticated(client):
    """Unauthenticated user should get 401."""
    resp = await client.get("/billing/status")
    assert resp.status_code == 401


# --- Checkout Tests ---

@pytest.mark.asyncio
async def test_checkout_invalid_tier(auth_client):
    """Checkout with invalid tier should fail validation."""
    resp = await auth_client.post("/billing/checkout", json={"tier": "platinum"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_checkout_free_tier_rejected(auth_client):
    """Cannot checkout for free tier."""
    resp = await auth_client.post("/billing/checkout", json={"tier": "free"})
    assert resp.status_code == 422  # Literal["starter", "pro"] rejects "free"


@pytest.mark.asyncio
async def test_checkout_already_subscribed(auth_client, db_session):
    """User with existing subscription should get 400."""
    me = await auth_client.get("/auth/me")
    user_id = me.json()["id"]
    from sqlalchemy import select
    result = await db_session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    user.subscription_stripe_id = "sub_existing"
    user.subscription_tier = "starter"
    await db_session.commit()

    resp = await auth_client.post("/billing/checkout", json={"tier": "pro"})
    assert resp.status_code == 400
    assert "already subscribed" in resp.json()["detail"].lower()


# --- Webhook Tests ---

@pytest.mark.asyncio
async def test_webhook_missing_signature(client):
    """Webhook without Stripe-Signature header should fail."""
    resp = await client.post("/billing/webhook", content=b'{}')
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/unit/test_billing.py -v
```

Expected: FAIL — no `/billing/` routes registered.

- [ ] **Step 3: Create billing service**

Create `backend/app/billing/service.py`:

```python
"""Stripe billing service — checkout, portal, webhooks, credit checks."""

import logging
from datetime import datetime, timezone

import stripe
from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import User

logger = logging.getLogger(__name__)

# Tier export limits: None = unlimited
TIER_LIMITS = {
    "free": 10,
    "starter": 100,
    "pro": None,
}

# Map Stripe Price IDs to tier names (populated from settings)
PRICE_TO_TIER = {}


def _init_stripe():
    """Initialize Stripe API key and price-to-tier mapping."""
    stripe.api_key = settings.stripe_secret_key
    if settings.stripe_price_starter:
        PRICE_TO_TIER[settings.stripe_price_starter] = "starter"
    if settings.stripe_price_pro:
        PRICE_TO_TIER[settings.stripe_price_pro] = "pro"


def _get_price_id_for_tier(tier: str) -> str:
    """Get Stripe Price ID for a tier."""
    if tier == "starter":
        return settings.stripe_price_starter
    elif tier == "pro":
        return settings.stripe_price_pro
    raise ValueError(f"No Stripe Price ID for tier: {tier}")


async def create_checkout_session(user: User, tier: str) -> str:
    """Create a Stripe Checkout Session and return the URL."""
    import asyncio
    _init_stripe()
    price_id = _get_price_id_for_tier(tier)
    frontend_url = settings.frontend_url

    session = await asyncio.to_thread(
        stripe.checkout.Session.create,
        mode="subscription",
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{frontend_url}/account?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{frontend_url}/account",
        client_reference_id=str(user.id),
        customer_email=user.email if not user.stripe_customer_id else None,
        customer=user.stripe_customer_id or None,
        metadata={"user_id": str(user.id), "tier": tier},
    )
    return session.url


async def create_portal_session(user: User) -> str:
    """Create a Stripe Billing Portal session and return the URL."""
    import asyncio
    _init_stripe()
    frontend_url = settings.frontend_url

    session = await asyncio.to_thread(
        stripe.billing_portal.Session.create,
        customer=user.stripe_customer_id,
        return_url=f"{frontend_url}/account",
    )
    return session.url


async def get_billing_status(user: User) -> dict:
    """Get current billing status for a user."""
    limit = TIER_LIMITS.get(user.subscription_tier, 10)
    remaining = None if limit is None else max(0, limit - user.period_exports_used)
    return {
        "subscription_tier": user.subscription_tier,
        "period_exports_used": user.period_exports_used,
        "exports_limit": limit,
        "exports_remaining": remaining,
        "current_period_end": user.current_period_end,
    }


async def check_and_increment_credits(db: AsyncSession, user_id, tier: str) -> bool:
    """Atomically check credit limit and increment usage. Returns True if allowed."""
    limit = TIER_LIMITS.get(tier, 10)

    if limit is None:
        # Pro tier: unlimited — just increment
        await db.execute(
            update(User)
            .where(User.id == user_id)
            .values(period_exports_used=User.period_exports_used + 1)
        )
        return True

    # Atomic check-and-increment for limited tiers
    result = await db.execute(
        text("""
            UPDATE users
            SET period_exports_used = period_exports_used + 1
            WHERE id = :user_id
              AND period_exports_used < :tier_limit
            RETURNING period_exports_used
        """),
        {"user_id": str(user_id), "tier_limit": limit},
    )
    row = result.fetchone()
    return row is not None


async def handle_checkout_completed(db: AsyncSession, event_data: dict):
    """Handle checkout.session.completed webhook event."""
    from uuid import UUID as _UUID
    session = event_data["object"]
    user_id_str = session.get("client_reference_id") or session["metadata"].get("user_id")
    customer_id = session["customer"]
    subscription_id = session["subscription"]
    tier = session["metadata"].get("tier", "starter")

    try:
        user_id = _UUID(user_id_str)
    except (ValueError, TypeError):
        logger.warning(f"Webhook: invalid user_id '{user_id_str}' in checkout.session.completed")
        return

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning(f"Webhook: user {user_id} not found for checkout.session.completed")
        return

    user.stripe_customer_id = customer_id
    user.subscription_tier = tier
    user.subscription_stripe_id = subscription_id
    # Period end will be set by invoice.paid
    await db.commit()


async def handle_invoice_paid(db: AsyncSession, event_data: dict):
    """Handle invoice.paid webhook event — reset credits, update period."""
    invoice = event_data["object"]
    customer_id = invoice["customer"]
    subscription = invoice.get("subscription")

    if not subscription:
        return  # One-time payment, not subscription

    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        logger.warning(f"Webhook: customer {customer_id} not found for invoice.paid")
        return

    # Reset usage counter
    user.period_exports_used = 0

    # Update period end from invoice
    period_end = invoice.get("lines", {}).get("data", [{}])[0].get("period", {}).get("end")
    if period_end:
        user.current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)

    await db.commit()


async def handle_subscription_updated(db: AsyncSession, event_data: dict, event_created: int):
    """Handle customer.subscription.updated webhook event."""
    subscription = event_data["object"]
    customer_id = subscription["customer"]

    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        logger.warning(f"Webhook: customer {customer_id} not found for subscription.updated")
        return

    # Out-of-order protection
    if user.updated_at and user.updated_at.timestamp() > event_created:
        logger.info(f"Webhook: discarding stale subscription.updated for {customer_id}")
        return

    # Determine new tier from price ID
    items = subscription.get("items", {}).get("data", [])
    if items:
        price_id = items[0].get("price", {}).get("id")
        _init_stripe()
        new_tier = PRICE_TO_TIER.get(price_id, "free")

        # Only apply upgrades immediately; downgrades take effect at next period
        # (via invoice.paid). Tier order: free < starter < pro
        tier_rank = {"free": 0, "starter": 1, "pro": 2}
        if tier_rank.get(new_tier, 0) > tier_rank.get(user.subscription_tier, 0):
            user.subscription_tier = new_tier

    # Update period end
    period_end = subscription.get("current_period_end")
    if period_end:
        user.current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)

    await db.commit()


async def handle_subscription_deleted(db: AsyncSession, event_data: dict, event_created: int):
    """Handle customer.subscription.deleted webhook event."""
    subscription = event_data["object"]
    customer_id = subscription["customer"]

    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        logger.warning(f"Webhook: customer {customer_id} not found for subscription.deleted")
        return

    # Out-of-order protection
    if user.updated_at and user.updated_at.timestamp() > event_created:
        logger.info(f"Webhook: discarding stale subscription.deleted for {customer_id}")
        return

    user.subscription_tier = "free"
    user.subscription_stripe_id = None
    user.current_period_end = None
    await db.commit()
```

- [ ] **Step 4: Run tests to verify they still fail (service exists, no routes yet)**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/unit/test_billing.py -v
```

Expected: Still FAIL — routes not registered yet.

- [ ] **Step 5: Commit service**

```bash
git add backend/app/billing/service.py
git commit -m "feat(billing): add billing service — Stripe checkout, portal, webhooks, credit checks"
```

---

### Task 7: Billing Router + Registration

**Files:**
- Create: `backend/app/billing/router.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create billing router**

Create `backend/app/billing/router.py`:

```python
"""Billing API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

import stripe

from app.auth.dependencies import get_current_user
from app.billing.schemas import CheckoutRequest, CheckoutResponse, PortalResponse, BillingStatusResponse
from app.billing.service import (
    create_checkout_session,
    create_portal_session,
    get_billing_status,
    handle_checkout_completed,
    handle_invoice_paid,
    handle_subscription_updated,
    handle_subscription_deleted,
)
from app.config import settings
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/billing", tags=["billing"])


@router.post("/checkout", response_model=CheckoutResponse)
async def checkout(
    data: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Checkout Session for subscription."""
    if user.subscription_stripe_id:
        raise HTTPException(
            status_code=400,
            detail="Already subscribed. Use the billing portal to change plans.",
        )

    url = await create_checkout_session(user, data.tier)
    return CheckoutResponse(checkout_url=url)


@router.post("/portal", response_model=PortalResponse)
async def portal(
    user: User = Depends(get_current_user),
):
    """Create a Stripe Billing Portal session."""
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found")

    url = await create_portal_session(user)
    return PortalResponse(portal_url=url)


@router.get("/status", response_model=BillingStatusResponse)
async def status(
    user: User = Depends(get_current_user),
):
    """Get current billing status."""
    result = await get_billing_status(user)
    return result


@router.post("/webhook")
async def webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Receive Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    event_data = event["data"]
    event_created = event.get("created", 0)

    if event_type == "checkout.session.completed":
        await handle_checkout_completed(db, event_data)
    elif event_type == "invoice.paid":
        await handle_invoice_paid(db, event_data)
    elif event_type == "customer.subscription.updated":
        await handle_subscription_updated(db, event_data, event_created)
    elif event_type == "customer.subscription.deleted":
        await handle_subscription_deleted(db, event_data, event_created)

    return {"status": "ok"}
```

- [ ] **Step 2: Register billing router in main.py**

In `backend/app/main.py`, add import:

```python
from app.billing.router import router as billing_router
```

And add registration after line 26:

```python
app.include_router(billing_router)
```

- [ ] **Step 3: Run billing tests**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/unit/test_billing.py -v
```

Expected: All billing tests PASS.

- [ ] **Step 4: Run full test suite**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/billing/router.py backend/app/main.py
git commit -m "feat(billing): add billing router — checkout, portal, status, webhook endpoints"
```

---

### Task 8: Credit Enforcement in Export Endpoint

**Files:**
- Modify: `backend/app/export/router.py:43-56`
- Test: `backend/tests/unit/test_exports.py` (add credit tests)

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/unit/test_exports.py`:

```python
@pytest.mark.asyncio
async def test_export_credit_limit_enforced(auth_client, selected_clip, db_session):
    """Export should fail when credit limit is reached."""
    # Set user to free tier with 10 exports used
    me_resp = await auth_client.get("/auth/me")
    user_id = me_resp.json()["id"]
    from sqlalchemy import select
    result = await db_session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    user.subscription_tier = "free"
    user.period_exports_used = 10
    await db_session.commit()

    resp = await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "shorts",
    })
    assert resp.status_code == 402
    assert "limit reached" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_export_pro_unlimited(auth_client, selected_clip, db_session):
    """Pro user should always be allowed to export."""
    me_resp = await auth_client.get("/auth/me")
    user_id = me_resp.json()["id"]
    from sqlalchemy import select
    result = await db_session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    user.subscription_tier = "pro"
    user.period_exports_used = 999
    await db_session.commit()

    resp = await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "shorts",
    })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_export_increments_usage(auth_client, selected_clip, db_session):
    """Successful export should increment period_exports_used."""
    me_resp = await auth_client.get("/auth/me")
    user_id = me_resp.json()["id"]
    from sqlalchemy import select
    result = await db_session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    initial_count = user.period_exports_used

    resp = await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "shorts",
    })
    assert resp.status_code == 200

    await db_session.refresh(user)
    assert user.period_exports_used == initial_count + 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/unit/test_exports.py::test_export_credit_limit_enforced -v
```

Expected: FAIL — current code uses 24-hour rate limit, not credit-based.

- [ ] **Step 3: Replace rate limiting with credit enforcement**

In `backend/app/export/router.py`, replace lines 43-56 (the 24-hour rate limit block) with:

```python
    # Credit enforcement: atomic check-and-increment
    from app.billing.service import check_and_increment_credits
    allowed = await check_and_increment_credits(db, user.id, user.subscription_tier)
    if not allowed:
        raise HTTPException(
            status_code=402,
            detail="Export limit reached. Upgrade your plan.",
        )
```

Also remove unused imports from the old rate limit: `timedelta` from the `datetime` import, and `settings` from the `app.config` import. Keep `func` from `sqlalchemy` — it's needed for Task 9.

- [ ] **Step 4: Run credit tests**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/unit/test_exports.py -v
```

Expected: All export tests PASS (including new credit tests).

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/export/router.py backend/tests/unit/test_exports.py
git commit -m "feat(billing): replace 24hr rate limit with tier-based credit enforcement"
```

---

### Task 9: User Exports List Endpoint

**Files:**
- Modify: `backend/app/export/router.py`
- Test: `backend/tests/unit/test_exports.py` (add list test)

- [ ] **Step 1: Write failing test**

Add to `backend/tests/unit/test_exports.py`:

```python
@pytest.mark.asyncio
async def test_list_user_exports(auth_client, selected_clip, db_session):
    """GET /exports/ should return all exports for the user."""
    me_resp = await auth_client.get("/auth/me")
    user_id = me_resp.json()["id"]

    # Create 2 exports directly in DB
    for platform in ["shorts", "tiktok"]:
        export = Export(
            clip_id=selected_clip.id,
            user_id=user_id,
            platform=platform,
            aspect_ratio="9:16",
            resolution="1080x1920",
            status="rendered",
        )
        db_session.add(export)
    await db_session.commit()

    resp = await auth_client.get("/exports/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["exports"]) == 2
    # Should be ordered by created_at desc
    assert data["exports"][0]["platform"] in ["shorts", "tiktok"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/unit/test_exports.py::test_list_user_exports -v
```

Expected: FAIL — 404 or 405 (no `GET /exports/` route).

- [ ] **Step 3: Add list endpoint to export router**

Add to `backend/app/export/router.py`, before the `get_export` function (to avoid path parameter conflict — `GET /exports/` must be registered before `GET /exports/{export_id}`):

```python
@router.get("", response_model=ExportListResponse)
async def list_exports(
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all exports for the current user."""
    result = await db.execute(
        select(Export)
        .where(Export.user_id == user.id)
        .order_by(Export.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    exports = list(result.scalars().all())

    # Get total count
    count_result = await db.execute(
        select(func.count(Export.id)).where(Export.user_id == user.id)
    )
    total = count_result.scalar()

    return ExportListResponse(exports=exports, total=total)
```

Note: `func` is already imported from `sqlalchemy` (kept in Task 8).

- [ ] **Step 4: Run tests**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/unit/test_exports.py -v
```

Expected: All export tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/export/router.py backend/tests/unit/test_exports.py
git commit -m "feat(export): add GET /exports/ endpoint for user export history"
```

---

## Chunk 2: Video Lifecycle & Cleanup

### Task 10: Enhanced Video Delete

**Files:**
- Modify: `backend/app/videos/service.py:112-119`
- Test: `backend/tests/unit/test_video_delete.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_video_delete.py`:

```python
"""Tests for enhanced video delete with S3 cleanup."""

from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio

from app.db.models import Clip, Export, Job, Transcript, User, Video


@pytest_asyncio.fixture
async def auth_client(client):
    """Client that is logged in."""
    await client.post("/auth/register", json={
        "email": "deleteuser@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "deleteuser@example.com",
        "password": "StrongPass123!",
    })
    return client


@pytest_asyncio.fixture
async def video_with_exports(auth_client, db_session):
    """Create a video with clips and exports."""
    me = await auth_client.get("/auth/me")
    user_id = me.json()["id"]

    video = Video(
        user_id=user_id,
        original_filename="test.mp4",
        s3_key=f"uploads/{user_id}/test.mp4",
        file_size=1024,
        duration=300.0,
        status="ready",
    )
    db_session.add(video)
    await db_session.flush()

    transcript = Transcript(
        video_id=video.id,
        content="test content",
        word_timestamps=[],
        language="en",
    )
    db_session.add(transcript)
    await db_session.flush()

    clip = Clip(
        video_id=video.id,
        transcript_id=transcript.id,
        start_time=10.0,
        end_time=50.0,
        duration=40.0,
        status="selected",
    )
    db_session.add(clip)
    await db_session.flush()

    export = Export(
        clip_id=clip.id,
        user_id=user_id,
        platform="shorts",
        aspect_ratio="9:16",
        resolution="1080x1920",
        status="rendered",
        s3_key=f"exports/{user_id}/{clip.id}/shorts.mp4",
    )
    db_session.add(export)

    job = Job(
        user_id=user_id,
        video_id=video.id,
        job_type="render",
        status="pending",
    )
    db_session.add(job)
    await db_session.commit()

    return video, clip, export, job


@pytest.mark.asyncio
async def test_delete_sets_deleted_at(auth_client, video_with_exports):
    """DELETE /videos/{id} should soft-delete the video."""
    video, _, _, _ = video_with_exports
    with patch("app.videos.service.delete_s3_object", new_callable=AsyncMock):
        resp = await auth_client.delete(f"/videos/{video.id}")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_delete_cancels_pending_jobs(auth_client, video_with_exports, db_session):
    """Pending jobs should be marked as failed when video is deleted."""
    video, _, _, job = video_with_exports
    with patch("app.videos.service.delete_s3_object", new_callable=AsyncMock):
        await auth_client.delete(f"/videos/{video.id}")

    await db_session.refresh(job)
    assert job.status == "failed"
    assert "deleted by user" in job.error_message


@pytest.mark.asyncio
async def test_delete_calls_s3_cleanup(auth_client, video_with_exports):
    """S3 objects should be deleted for source video and exports."""
    video, _, export, _ = video_with_exports
    with patch("app.videos.service.delete_s3_object", new_callable=AsyncMock) as mock_delete:
        await auth_client.delete(f"/videos/{video.id}")

    # Should delete source video S3 key and export S3 key
    deleted_keys = [call.args[0] for call in mock_delete.call_args_list]
    assert video.s3_key in deleted_keys
    assert export.s3_key in deleted_keys
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/unit/test_video_delete.py -v
```

Expected: FAIL — current `soft_delete_video` doesn't do S3 cleanup.

- [ ] **Step 3: Enhance soft_delete_video**

Replace the `soft_delete_video` function in `backend/app/videos/service.py`:

```python
async def soft_delete_video(db: AsyncSession, user_id: UUID, video_id: UUID) -> bool:
    """Soft-delete video with immediate S3 cleanup.

    - Sets deleted_at on the Video record
    - Deletes source S3 object immediately
    - Deletes all export S3 objects for this video's clips
    - Cancels in-progress/pending jobs
    - DB records remain for 7 days (purged by daily cleanup)
    """
    from app.db.models import Clip, Export, Job

    video = await get_user_video(db, user_id, video_id)
    if not video:
        return False

    # 1. Soft-delete the video record
    video.deleted_at = datetime.utcnow()
    video.status = "deleted"

    # 2. Delete source S3 object
    try:
        await delete_s3_object(video.s3_key)
    except Exception:
        pass  # Log but don't block — safety net catches on hard-delete

    # 3. Find and delete export S3 objects
    clip_result = await db.execute(
        select(Clip.id).where(Clip.video_id == video_id)
    )
    clip_ids = [row[0] for row in clip_result.all()]

    if clip_ids:
        export_result = await db.execute(
            select(Export).where(Export.clip_id.in_(clip_ids))
        )
        for export in export_result.scalars().all():
            if export.s3_key:
                try:
                    await delete_s3_object(export.s3_key)
                except Exception:
                    pass

    # 4. Cancel pending/running jobs
    job_result = await db.execute(
        select(Job).where(
            Job.video_id == video_id,
            Job.status.in_(["pending", "running"]),
        )
    )
    for job in job_result.scalars().all():
        job.status = "failed"
        job.error_message = "Video deleted by user"
        job.completed_at = datetime.utcnow()

    await db.commit()
    return True
```

Add the missing imports at the top of the file:

```python
from app.db.models import Clip, Export, Job, Video
```

(Replace the existing `from app.db.models import Video` import.)

Also add `select` from `sqlalchemy` if not already imported (it's imported from `sqlalchemy` already).

- [ ] **Step 4: Run tests**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/unit/test_video_delete.py -v
```

Expected: All 3 delete tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/videos/service.py backend/tests/unit/test_video_delete.py
git commit -m "feat(videos): enhance delete with immediate S3 cleanup and job cancellation"
```

---

### Task 11: Daily Cleanup Task

**Files:**
- Modify: `backend/app/jobs/tasks.py`
- Modify: `backend/app/jobs/worker.py`
- Test: `backend/tests/unit/test_cleanup.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_cleanup.py`:

```python
"""Tests for daily cleanup task."""

from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models import Clip, Export, Job, Transcript, User, Video


@pytest_asyncio.fixture
async def old_video(db_session):
    """Create a video older than 30 days."""
    user = User(
        email="cleanup@example.com",
        hashed_password="hashed",
        tos_accepted_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    await db_session.flush()

    video = Video(
        user_id=user.id,
        original_filename="old.mp4",
        s3_key=f"uploads/{user.id}/old.mp4",
        file_size=1024,
        duration=60.0,
        status="ready",
        created_at=datetime.now(timezone.utc) - timedelta(days=31),
    )
    db_session.add(video)
    await db_session.commit()
    return user, video


@pytest_asyncio.fixture
async def soft_deleted_video(db_session):
    """Create a video soft-deleted 8 days ago."""
    user = User(
        email="purge@example.com",
        hashed_password="hashed",
        tos_accepted_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    await db_session.flush()

    video = Video(
        user_id=user.id,
        original_filename="deleted.mp4",
        s3_key=f"uploads/{user.id}/deleted.mp4",
        file_size=1024,
        duration=60.0,
        status="deleted",
        deleted_at=datetime.now(timezone.utc) - timedelta(days=8),
    )
    db_session.add(video)
    await db_session.commit()
    return user, video


@pytest_asyncio.fixture
async def user_with_expired_period(db_session):
    """Create a user with expired billing period."""
    user = User(
        email="expired@example.com",
        hashed_password="hashed",
        tos_accepted_at=datetime.now(timezone.utc),
        subscription_tier="free",
        period_exports_used=7,
        current_period_end=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_auto_expire_old_videos(old_video, db_session):
    """Videos older than 30 days should be auto-expired."""
    from unittest.mock import patch, AsyncMock
    from app.jobs.tasks import cleanup_expired_content

    user, video = old_video

    with patch("app.jobs.tasks._get_db_session", return_value=db_session), \
         patch("app.jobs.tasks.delete_s3_object", new_callable=AsyncMock):
        await cleanup_expired_content(None)

    await db_session.refresh(video)
    assert video.status == "deleted"
    assert video.deleted_at is not None


@pytest.mark.asyncio
async def test_hard_delete_old_soft_deleted(soft_deleted_video, db_session):
    """Soft-deleted videos older than 7 days should be hard-deleted."""
    from unittest.mock import patch, AsyncMock
    from app.jobs.tasks import cleanup_expired_content

    user, video = soft_deleted_video
    video_id = video.id

    with patch("app.jobs.tasks._get_db_session", return_value=db_session), \
         patch("app.jobs.tasks.delete_s3_object", new_callable=AsyncMock):
        await cleanup_expired_content(None)

    result = await db_session.execute(select(Video).where(Video.id == video_id))
    assert result.scalar_one_or_none() is None  # Hard-deleted


@pytest.mark.asyncio
async def test_reset_expired_billing_periods(user_with_expired_period, db_session):
    """Users with expired periods should have credits reset."""
    from app.jobs.tasks import cleanup_expired_content
    from unittest.mock import patch, AsyncMock

    user = user_with_expired_period

    with patch("app.jobs.tasks._get_db_session", return_value=db_session), \
         patch("app.jobs.tasks.delete_s3_object", new_callable=AsyncMock):
        await cleanup_expired_content(None)

    await db_session.refresh(user)
    assert user.period_exports_used == 0
    assert user.current_period_end > datetime.now(timezone.utc)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/unit/test_cleanup.py -v
```

Expected: FAIL — `cleanup_expired_content` doesn't exist.

- [ ] **Step 3: Implement cleanup_expired_content task**

Add to `backend/app/jobs/tasks.py`:

```python
from app.videos.storage import delete_s3_object


async def cleanup_expired_content(ctx):
    """Daily cleanup task — auto-expire, hard-delete, and reset billing periods.

    1. Auto-expire videos older than 30 days (S3 cleanup + soft delete)
    2. Hard-delete videos soft-deleted more than 7 days ago
    3. Reset period_exports_used for users with expired billing periods
    """
    import logging
    from dateutil.relativedelta import relativedelta
    from app.db.models import Clip, Export, Job, Transcript, User, Video

    logger = logging.getLogger(__name__)
    db = await _get_db_session()

    try:
        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)
        seven_days_ago = now - timedelta(days=7)

        # --- 1. Auto-expire old videos (30+ days) ---
        result = await db.execute(
            select(Video).where(
                Video.deleted_at.is_(None),
                Video.created_at < thirty_days_ago,
            )
        )
        old_videos = list(result.scalars().all())

        for video in old_videos:
            # Skip if any jobs are still running
            running_jobs = await db.execute(
                select(Job).where(
                    Job.video_id == video.id,
                    Job.status == "running",
                )
            )
            if running_jobs.scalar_one_or_none():
                logger.info(f"Cleanup: skipping video {video.id} — running jobs")
                continue

            try:
                # Delete source S3 object
                try:
                    await delete_s3_object(video.s3_key)
                except Exception:
                    pass

                # Delete export S3 objects
                clip_result = await db.execute(
                    select(Clip.id).where(Clip.video_id == video.id)
                )
                clip_ids = [row[0] for row in clip_result.all()]
                if clip_ids:
                    export_result = await db.execute(
                        select(Export).where(Export.clip_id.in_(clip_ids))
                    )
                    for export in export_result.scalars().all():
                        if export.s3_key:
                            try:
                                await delete_s3_object(export.s3_key)
                            except Exception:
                                pass

                # Cancel pending/running jobs
                job_result = await db.execute(
                    select(Job).where(
                        Job.video_id == video.id,
                        Job.status.in_(["pending", "running"]),
                    )
                )
                for job in job_result.scalars().all():
                    job.status = "failed"
                    job.error_message = "Video auto-expired (30 days)"
                    job.completed_at = now

                # Soft-delete
                video.deleted_at = now
                video.status = "deleted"
                await db.commit()
                logger.info(f"Cleanup: auto-expired video {video.id}")

            except Exception as e:
                await db.rollback()
                logger.error(f"Cleanup: failed to auto-expire video {video.id}: {e}")

        # --- 2. Hard-delete old soft-deleted videos (7+ days) ---
        result = await db.execute(
            select(Video).where(
                Video.deleted_at.isnot(None),
                Video.deleted_at < seven_days_ago,
            )
        )
        deleted_videos = list(result.scalars().all())

        for video in deleted_videos:
            try:
                # Safety-net S3 delete
                try:
                    await delete_s3_object(video.s3_key)
                except Exception:
                    pass

                # Delete in dependency order: exports → clips → transcript → jobs → video
                clip_result = await db.execute(
                    select(Clip.id).where(Clip.video_id == video.id)
                )
                clip_ids = [row[0] for row in clip_result.all()]

                if clip_ids:
                    # Delete exports and their S3 objects
                    export_result = await db.execute(
                        select(Export).where(Export.clip_id.in_(clip_ids))
                    )
                    for export in export_result.scalars().all():
                        if export.s3_key:
                            try:
                                await delete_s3_object(export.s3_key)
                            except Exception:
                                pass
                        await db.delete(export)

                    # Delete clips
                    for clip_id in clip_ids:
                        clip_obj_result = await db.execute(
                            select(Clip).where(Clip.id == clip_id)
                        )
                        clip_obj = clip_obj_result.scalar_one_or_none()
                        if clip_obj:
                            await db.delete(clip_obj)

                # Delete transcript
                transcript_result = await db.execute(
                    select(Transcript).where(Transcript.video_id == video.id)
                )
                transcript = transcript_result.scalar_one_or_none()
                if transcript:
                    await db.delete(transcript)

                # Delete jobs
                job_result = await db.execute(
                    select(Job).where(Job.video_id == video.id)
                )
                for job in job_result.scalars().all():
                    await db.delete(job)

                # Delete video
                await db.delete(video)
                await db.commit()
                logger.info(f"Cleanup: hard-deleted video {video.id}")

            except Exception as e:
                await db.rollback()
                logger.error(f"Cleanup: failed to hard-delete video {video.id}: {e}")

        # --- 3. Reset expired billing periods ---
        result = await db.execute(
            select(User).where(
                User.current_period_end.isnot(None),
                User.current_period_end < now,
            )
        )
        expired_users = list(result.scalars().all())

        for user in expired_users:
            user.period_exports_used = 0
            # Advance period by 1 month
            user.current_period_end = user.current_period_end + relativedelta(months=1)
            logger.info(f"Cleanup: reset billing period for user {user.id}")

        if expired_users:
            await db.commit()

    finally:
        await db.close()
```

Add `timedelta` to the existing datetime imports at the top of the file (it's already imported).

Add `python-dateutil` to `backend/requirements.txt`:

```
python-dateutil==2.9.0
```

Install it:

```bash
cd /Users/justin/CascadeProjects/clipforge/backend && pip install python-dateutil==2.9.0
```

- [ ] **Step 4: Register cleanup task in worker**

In `backend/app/jobs/worker.py`, add import:

```python
from app.jobs.tasks import cleanup_expired_content
```

Add to `WorkerSettings.functions`:

```python
    functions = [
        transcribe_video,
        detect_clips_task,
        prepare_render_task,
        execute_render_task,
        upload_output_task,
        cleanup_expired_content,
    ]
```

Add ARQ cron schedule to `WorkerSettings`:

```python
    cron_jobs = [
        # Run daily at 3 AM UTC
        cron(cleanup_expired_content, hour=3, minute=0),
    ]
```

Note: ARQ uses `arq.cron.cron()` helper objects. Add the import `from arq.cron import cron` at the top of `worker.py`.

- [ ] **Step 5: Run cleanup tests**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/unit/test_cleanup.py -v
```

Expected: All 3 cleanup tests PASS.

- [ ] **Step 6: Run full test suite**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/jobs/tasks.py backend/app/jobs/worker.py backend/requirements.txt backend/tests/unit/test_cleanup.py
git commit -m "feat(jobs): add daily cleanup task — auto-expire, hard-delete, billing reset"
```

---

## Chunk 3: Frontend Pages

### Task 12: Landing Page

**Files:**
- Create: `frontend/src/pages/LandingPage.tsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Create LandingPage component**

Create `frontend/src/pages/LandingPage.tsx`:

```tsx
import { useNavigate, Link } from "react-router-dom";

const TIERS = [
  {
    name: "Free",
    price: "$0",
    period: "/month",
    features: ["10 exports/month", "All platforms", "AI clip detection", "Smart reframe"],
    cta: "Get Started",
    href: "/register",
    highlight: false,
  },
  {
    name: "Starter",
    price: "$19",
    period: "/month",
    features: ["100 exports/month", "All platforms", "AI clip detection", "Smart reframe", "Animated captions"],
    cta: "Start Free Trial",
    href: "/register",
    highlight: true,
  },
  {
    name: "Pro",
    price: "$49",
    period: "/month",
    features: ["Unlimited exports", "All platforms", "AI clip detection", "Smart reframe", "Animated captions", "Multi-platform export"],
    cta: "Go Pro",
    href: "/register",
    highlight: false,
  },
];

export default function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="landing">
      {/* Hero */}
      <section className="landing__hero">
        <h1>Turn long videos into viral clips with AI</h1>
        <p className="landing__subtitle">
          Upload a podcast, talk, or stream. ClipForge detects the most viral-worthy
          moments, reframes for any platform, and burns in animated captions.
        </p>
        <button className="landing__cta" onClick={() => navigate("/register")}>
          Get Started Free
        </button>
      </section>

      {/* How It Works */}
      <section className="landing__steps">
        <h2>How It Works</h2>
        <div className="landing__steps-grid">
          <div className="landing__step">
            <div className="landing__step-number">1</div>
            <h3>Upload</h3>
            <p>Drop in your long-form video — podcast, talk, stream, vlog.</p>
          </div>
          <div className="landing__step">
            <div className="landing__step-number">2</div>
            <h3>AI Detects Clips</h3>
            <p>Our AI analyzes the transcript and finds the most engaging moments.</p>
          </div>
          <div className="landing__step">
            <div className="landing__step-number">3</div>
            <h3>Export</h3>
            <p>Smart reframe, animated captions, and platform-ready formats.</p>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="landing__features">
        <h2>Features</h2>
        <div className="landing__features-grid">
          <div className="landing__feature">
            <h3>AI Virality Scoring</h3>
            <p>Each clip gets a virality score based on hook strength, information density, emotional resonance, and shareability.</p>
          </div>
          <div className="landing__feature">
            <h3>Smart Reframe</h3>
            <p>Automatic face detection and smooth crop for 9:16 (Shorts, TikTok, Reels), 1:1 (Square), and 16:9 (Twitter).</p>
          </div>
          <div className="landing__feature">
            <h3>Animated Captions</h3>
            <p>Word-by-word highlighted captions burned directly into the video. No separate subtitle file needed.</p>
          </div>
          <div className="landing__feature">
            <h3>Multi-Platform Export</h3>
            <p>One click to export for YouTube Shorts, TikTok, Instagram Reels, Instagram Square, or X (Twitter).</p>
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section className="landing__pricing">
        <h2>Pricing</h2>
        <div className="landing__pricing-grid">
          {TIERS.map((tier) => (
            <div
              key={tier.name}
              className={`landing__tier ${tier.highlight ? "landing__tier--highlight" : ""}`}
            >
              <h3>{tier.name}</h3>
              <div className="landing__tier-price">
                <span className="landing__tier-amount">{tier.price}</span>
                <span className="landing__tier-period">{tier.period}</span>
              </div>
              <ul className="landing__tier-features">
                {tier.features.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
              <button
                className={`landing__tier-cta ${tier.highlight ? "landing__tier-cta--highlight" : ""}`}
                onClick={() => navigate(tier.href)}
              >
                {tier.cta}
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="landing__footer">
        <div className="landing__footer-links">
          <Link to="/terms">Terms of Service</Link>
          <Link to="/privacy">Privacy Policy</Link>
          <Link to="/login">Log In</Link>
        </div>
        <p>&copy; 2026 ClipForge</p>
      </footer>
    </div>
  );
}
```

- [ ] **Step 2: Add landing page styles to App.css**

Add at the end of `frontend/src/App.css`:

```css
/* Landing Page */
.landing {
  max-width: 1000px;
  margin: 0 auto;
  padding: 24px;
}

.landing__hero {
  text-align: center;
  padding: 64px 0 48px;
}

.landing__hero h1 {
  font-size: 36px;
  font-weight: 800;
  line-height: 1.2;
  margin-bottom: 16px;
}

.landing__subtitle {
  font-size: 18px;
  color: #6b7280;
  max-width: 600px;
  margin: 0 auto 32px;
  line-height: 1.6;
}

.landing__cta {
  padding: 14px 32px;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
}

.landing__cta:hover {
  background: #1d4ed8;
}

.landing__steps,
.landing__features,
.landing__pricing {
  padding: 48px 0;
}

.landing__steps h2,
.landing__features h2,
.landing__pricing h2 {
  text-align: center;
  font-size: 24px;
  margin-bottom: 32px;
}

.landing__steps-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  text-align: center;
}

.landing__step-number {
  width: 40px;
  height: 40px;
  background: #2563eb;
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 12px;
  font-weight: 700;
  font-size: 18px;
}

.landing__step h3 {
  margin: 0 0 8px;
}

.landing__step p {
  font-size: 14px;
  color: #6b7280;
}

.landing__features-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 24px;
}

.landing__feature {
  padding: 20px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.landing__feature h3 {
  margin: 0 0 8px;
  font-size: 16px;
}

.landing__feature p {
  font-size: 14px;
  color: #6b7280;
  margin: 0;
}

.landing__pricing-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
}

.landing__tier {
  padding: 24px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  text-align: center;
}

.landing__tier--highlight {
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.2);
}

.landing__tier h3 {
  margin: 0 0 8px;
}

.landing__tier-price {
  margin-bottom: 16px;
}

.landing__tier-amount {
  font-size: 36px;
  font-weight: 800;
}

.landing__tier-period {
  font-size: 14px;
  color: #6b7280;
}

.landing__tier-features {
  list-style: none;
  padding: 0;
  margin: 0 0 24px;
  text-align: left;
}

.landing__tier-features li {
  padding: 6px 0;
  font-size: 14px;
  border-bottom: 1px solid #f3f4f6;
}

.landing__tier-features li::before {
  content: "\2713 ";
  color: #059669;
  font-weight: 700;
}

.landing__tier-cta {
  width: 100%;
  padding: 10px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}

.landing__tier-cta--highlight {
  background: #2563eb;
  color: white;
  border-color: #2563eb;
}

.landing__footer {
  padding: 32px 0;
  text-align: center;
  border-top: 1px solid #e5e7eb;
  margin-top: 48px;
}

.landing__footer-links {
  display: flex;
  justify-content: center;
  gap: 24px;
  margin-bottom: 16px;
}

.landing__footer-links a {
  color: #6b7280;
  text-decoration: none;
  font-size: 14px;
}

.landing__footer-links a:hover {
  color: #111827;
}

.landing__footer p {
  color: #9ca3af;
  font-size: 13px;
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /Users/justin/CascadeProjects/clipforge/frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/LandingPage.tsx frontend/src/App.css
git commit -m "feat(frontend): add landing page with hero, features, pricing, footer"
```

---

### Task 13: Account Page

**Files:**
- Create: `frontend/src/pages/AccountPage.tsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Create AccountPage component**

Create `frontend/src/pages/AccountPage.tsx`:

```tsx
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/client";

interface BillingStatus {
  subscription_tier: string;
  period_exports_used: number;
  exports_limit: number | null;
  exports_remaining: number | null;
  current_period_end: string | null;
}

interface UserInfo {
  id: string;
  email: string;
  email_verified: boolean;
  created_at: string;
}

interface ExportItem {
  id: string;
  platform: string;
  status: string;
  created_at: string;
  download_url: string | null;
}

export default function AccountPage() {
  const navigate = useNavigate();
  const [user, setUser] = useState<UserInfo | null>(null);
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [exports, setExports] = useState<ExportItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        const [userResp, billingResp, exportsResp] = await Promise.all([
          api.get("/auth/me"),
          api.get("/billing/status"),
          api.get("/exports/?limit=20"),
        ]);
        setUser(userResp.data);
        setBilling(billingResp.data);
        setExports(exportsResp.data.exports || []);
      } catch {
        navigate("/login");
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [navigate]);

  async function handleUpgrade(tier: string) {
    try {
      const resp = await api.post("/billing/checkout", { tier });
      window.location.href = resp.data.checkout_url;
    } catch (err: any) {
      alert(err.response?.data?.detail || "Failed to start checkout");
    }
  }

  async function handleManageSubscription() {
    try {
      const resp = await api.post("/billing/portal");
      window.location.href = resp.data.portal_url;
    } catch (err: any) {
      alert(err.response?.data?.detail || "Failed to open billing portal");
    }
  }

  if (loading) return <p>Loading...</p>;
  if (!user || !billing) return <p>Could not load account info.</p>;

  const tierLabel = billing.subscription_tier.charAt(0).toUpperCase() + billing.subscription_tier.slice(1);
  const usagePercent = billing.exports_limit
    ? Math.min(100, Math.round((billing.period_exports_used / billing.exports_limit) * 100))
    : 0;

  return (
    <div className="account-page">
      <button onClick={() => navigate("/")} className="back-btn">
        Back to Dashboard
      </button>

      <h2>Account</h2>

      {/* Profile Section */}
      <section className="account-section">
        <h3>Profile</h3>
        <p><strong>Email:</strong> {user.email}</p>
        <p><strong>Member since:</strong> {new Date(user.created_at).toLocaleDateString()}</p>
      </section>

      {/* Subscription Section */}
      <section className="account-section">
        <h3>Subscription</h3>
        <div className="account-tier">
          <span className={`account-tier-badge account-tier-badge--${billing.subscription_tier}`}>
            {tierLabel}
          </span>
          {billing.current_period_end && (
            <span className="account-period-end">
              Renews {new Date(billing.current_period_end).toLocaleDateString()}
            </span>
          )}
        </div>

        {/* Usage */}
        <div className="account-usage">
          <div className="account-usage-label">
            <span>Exports this period</span>
            <span>
              {billing.period_exports_used}
              {billing.exports_limit ? ` / ${billing.exports_limit}` : " (unlimited)"}
            </span>
          </div>
          {billing.exports_limit && (
            <div className="progress-bar" style={{ height: "12px" }}>
              <div
                className="progress-fill"
                style={{
                  width: `${usagePercent}%`,
                  background: usagePercent >= 90 ? "#dc2626" : "#2563eb",
                }}
              />
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="account-actions">
          {billing.subscription_tier === "free" && (
            <>
              <button className="account-upgrade-btn" onClick={() => handleUpgrade("starter")}>
                Upgrade to Starter ($19/mo)
              </button>
              <button className="account-upgrade-btn account-upgrade-btn--pro" onClick={() => handleUpgrade("pro")}>
                Upgrade to Pro ($49/mo)
              </button>
            </>
          )}
          {billing.subscription_tier !== "free" && (
            <button className="account-manage-btn" onClick={handleManageSubscription}>
              Manage Subscription
            </button>
          )}
        </div>
      </section>

      {/* Export History */}
      <section className="account-section">
        <h3>Export History</h3>
        {exports.length === 0 ? (
          <p className="account-empty">No exports yet.</p>
        ) : (
          <table className="account-exports-table">
            <thead>
              <tr>
                <th>Platform</th>
                <th>Status</th>
                <th>Date</th>
                <th>Download</th>
              </tr>
            </thead>
            <tbody>
              {exports.map((exp) => (
                <tr key={exp.id}>
                  <td>{exp.platform}</td>
                  <td>{exp.status}</td>
                  <td>{new Date(exp.created_at).toLocaleDateString()}</td>
                  <td>
                    {exp.download_url ? (
                      <a href={exp.download_url} className="download-btn" target="_blank" rel="noreferrer">
                        Download
                      </a>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Add account page styles to App.css**

Add at the end of `frontend/src/App.css`:

```css
/* Account Page */
.account-page {
  max-width: 800px;
  margin: 0 auto;
  padding: 24px;
}

.account-section {
  margin-bottom: 32px;
  padding: 20px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.account-section h3 {
  margin: 0 0 16px;
  font-size: 18px;
}

.account-tier {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.account-tier-badge {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 600;
  text-transform: uppercase;
}

.account-tier-badge--free {
  background: #f3f4f6;
  color: #6b7280;
}

.account-tier-badge--starter {
  background: #dbeafe;
  color: #1d4ed8;
}

.account-tier-badge--pro {
  background: #faf5ff;
  color: #7c3aed;
}

.account-period-end {
  font-size: 13px;
  color: #6b7280;
}

.account-usage {
  margin-bottom: 16px;
}

.account-usage-label {
  display: flex;
  justify-content: space-between;
  font-size: 14px;
  margin-bottom: 6px;
}

.account-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.account-upgrade-btn {
  padding: 10px 20px;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
}

.account-upgrade-btn--pro {
  background: #7c3aed;
}

.account-manage-btn {
  padding: 10px 20px;
  background: none;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}

.account-empty {
  color: #9ca3af;
  font-size: 14px;
}

.account-exports-table {
  width: 100%;
  border-collapse: collapse;
}

.account-exports-table th,
.account-exports-table td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid #e5e7eb;
  font-size: 14px;
}

.account-exports-table th {
  font-weight: 600;
  background: #f9fafb;
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /Users/justin/CascadeProjects/clipforge/frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/AccountPage.tsx frontend/src/App.css
git commit -m "feat(frontend): add account page — profile, subscription, export history"
```

---

### Task 14: Legal Pages (Terms + Privacy)

**Files:**
- Create: `frontend/src/pages/TermsPage.tsx`
- Create: `frontend/src/pages/PrivacyPage.tsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Create TermsPage**

Create `frontend/src/pages/TermsPage.tsx`:

```tsx
import { useNavigate } from "react-router-dom";

export default function TermsPage() {
  const navigate = useNavigate();

  return (
    <div className="legal-page">
      <button onClick={() => navigate("/")} className="back-btn">
        Back
      </button>

      <h1>Terms of Service</h1>
      <p className="legal-updated">Last updated: March 13, 2026</p>

      <section>
        <h2>1. Acceptance of Terms</h2>
        <p>
          By creating an account or using ClipForge, you agree to be bound by these
          Terms of Service. If you do not agree, do not use the service.
        </p>
      </section>

      <section>
        <h2>2. Service Description</h2>
        <p>
          ClipForge is a video processing service that uses AI to detect viral-worthy
          segments from long-form videos, applies smart reframing and animated captions,
          and exports clips formatted for social media platforms.
        </p>
      </section>

      <section>
        <h2>3. User Content & Ownership</h2>
        <p>
          You retain all rights to the videos you upload. By uploading content, you grant
          ClipForge a limited license to process, store, and transform your content solely
          for the purpose of providing the service. We do not claim ownership of your content.
        </p>
      </section>

      <section>
        <h2>4. Acceptable Use</h2>
        <p>
          You agree not to upload content that is illegal, infringes on third-party rights,
          or violates applicable laws. We reserve the right to remove content that violates
          these terms without notice.
        </p>
      </section>

      <section>
        <h2>5. Limitation of Liability</h2>
        <p>
          ClipForge is provided "as is" without warranties of any kind. We are not liable
          for any damages arising from your use of the service, including but not limited to
          data loss, processing errors, or service interruptions.
        </p>
      </section>

      <section>
        <h2>6. Termination</h2>
        <p>
          We may terminate or suspend your account at any time for violations of these terms.
          You may delete your account at any time. Upon deletion, your data will be removed
          according to our data retention policy.
        </p>
      </section>

      <section>
        <h2>7. Changes to Terms</h2>
        <p>
          We may update these terms from time to time. Continued use of the service after
          changes constitutes acceptance of the new terms.
        </p>
      </section>

      <section>
        <h2>8. Contact</h2>
        <p>
          For questions about these terms, contact us at legal@clipforge.app.
        </p>
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Create PrivacyPage**

Create `frontend/src/pages/PrivacyPage.tsx`:

```tsx
import { useNavigate } from "react-router-dom";

export default function PrivacyPage() {
  const navigate = useNavigate();

  return (
    <div className="legal-page">
      <button onClick={() => navigate("/")} className="back-btn">
        Back
      </button>

      <h1>Privacy Policy</h1>
      <p className="legal-updated">Last updated: March 13, 2026</p>

      <section>
        <h2>1. Data We Collect</h2>
        <p>
          We collect the following information: email address (for account creation),
          video files you upload (for processing), payment information (processed by
          Stripe — we do not store card details), and usage data (export counts, login times).
        </p>
      </section>

      <section>
        <h2>2. How We Use Your Data</h2>
        <p>
          Your data is used solely to provide the ClipForge service: processing videos,
          generating transcripts, detecting clips, rendering exports, and managing your
          subscription. We do not sell your data to third parties.
        </p>
      </section>

      <section>
        <h2>3. Data Retention</h2>
        <p>
          Uploaded videos are automatically deleted 30 days after upload. Rendered exports
          are retained until the source video is deleted. You can delete your videos at any
          time from the dashboard.
        </p>
      </section>

      <section>
        <h2>4. Data Deletion</h2>
        <p>
          You can delete individual videos using the delete button on the dashboard.
          Deleting a video immediately removes the video file and all rendered exports
          from our storage. Database records are purged within 7 days.
        </p>
      </section>

      <section>
        <h2>5. Third-Party Services</h2>
        <p>
          ClipForge uses the following third-party services to provide the service:
        </p>
        <ul>
          <li><strong>Stripe</strong> — payment processing. See Stripe's privacy policy.</li>
          <li><strong>OpenAI (Whisper)</strong> — audio transcription. Audio is sent to OpenAI's API for transcription.</li>
          <li><strong>Anthropic (Claude)</strong> — clip detection. Transcript text is sent to Anthropic's API for analysis.</li>
          <li><strong>Cloudflare R2</strong> — file storage. Videos and exports are stored in Cloudflare R2.</li>
        </ul>
      </section>

      <section>
        <h2>6. Contact</h2>
        <p>
          For privacy-related questions, contact us at privacy@clipforge.app.
        </p>
      </section>
    </div>
  );
}
```

- [ ] **Step 3: Add legal page styles**

Add at the end of `frontend/src/App.css`:

```css
/* Legal Pages */
.legal-page {
  max-width: 700px;
  margin: 0 auto;
  padding: 24px;
}

.legal-page h1 {
  font-size: 28px;
  margin-bottom: 4px;
}

.legal-updated {
  color: #9ca3af;
  font-size: 13px;
  margin-bottom: 32px;
}

.legal-page section {
  margin-bottom: 24px;
}

.legal-page h2 {
  font-size: 18px;
  margin: 0 0 8px;
}

.legal-page p,
.legal-page li {
  font-size: 14px;
  line-height: 1.7;
  color: #374151;
}

.legal-page ul {
  padding-left: 20px;
}

.legal-page li {
  margin-bottom: 6px;
}
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd /Users/justin/CascadeProjects/clipforge/frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/TermsPage.tsx frontend/src/pages/PrivacyPage.tsx frontend/src/App.css
git commit -m "feat(frontend): add Terms of Service and Privacy Policy placeholder pages"
```

---

### Task 15: Routing Updates + Dashboard Account Link

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/DashboardPage.tsx`

- [ ] **Step 1: Update App.tsx routing**

Replace `frontend/src/App.tsx` with:

```tsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import DashboardPage from "./pages/DashboardPage";
import VideoPage from "./pages/VideoPage";
import AccountPage from "./pages/AccountPage";
import LandingPage from "./pages/LandingPage";
import TermsPage from "./pages/TermsPage";
import PrivacyPage from "./pages/PrivacyPage";
import "./App.css";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/terms" element={<TermsPage />} />
        <Route path="/privacy" element={<PrivacyPage />} />
        <Route path="/landing" element={<LandingPage />} />
        <Route path="/" element={<DashboardPage />} />
        <Route path="/account" element={<AccountPage />} />
        <Route path="/video/:videoId" element={<VideoPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
```

Note: `/` routes to DashboardPage which already redirects to `/login` on 401. LandingPage is at `/landing`. The existing auth pattern (each page handles its own auth failure) is preserved — no global auth state to go stale.

Update `DashboardPage` to redirect to `/landing` instead of `/login` when unauthenticated, so the landing page is the entry point for new users. In `DashboardPage.tsx`, the `api.get("/auth/me")` call in the existing flow already handles auth. If it fails, navigate to `/landing` instead of `/login`.

Also update `LoginPage` and `RegisterPage` to add a link back to `/landing`.

- [ ] **Step 2: Add Account link to DashboardPage header**

In `frontend/src/pages/DashboardPage.tsx`, update the header section (around line 33-35) to add an Account link:

```tsx
      <header>
        <h1>ClipForge</h1>
        <div style={{ display: "flex", gap: "8px" }}>
          <button onClick={() => navigate("/account")}>Account</button>
          <button onClick={handleLogout}>Log out</button>
        </div>
      </header>
```

Add `useNavigate` import if not already present (it's already imported on line 2).

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /Users/justin/CascadeProjects/clipforge/frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 4: Verify frontend builds**

```bash
cd /Users/justin/CascadeProjects/clipforge/frontend && npm run build
```

Expected: Build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/DashboardPage.tsx
git commit -m "feat(frontend): add routing for landing, account, terms, privacy pages"
```

---

## Chunk 4: Auth Enhancement + Build Log + Merge

### Task 16: Set current_period_end at Registration

**Files:**
- Modify: `backend/app/auth/service.py:34-52`

- [ ] **Step 1: Update register_user to set current_period_end**

In `backend/app/auth/service.py`, modify the `register_user` function. After the `User(...)` constructor, add `current_period_end` set to the first of next month:

```python
from dateutil.relativedelta import relativedelta

async def register_user(db: AsyncSession, email: str, password: str) -> User:
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        raise ValueError("Email already registered")

    now = datetime.utcnow()
    # Set free tier period end to first of next month
    next_month = (now.replace(day=1) + relativedelta(months=1))

    user = User(
        email=email,
        hashed_password=hash_password(password),
        tos_accepted_at=now,
        email_verification_token=generate_token(),
        current_period_end=next_month,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # MVP: log verification URL to stdout
    print(f"[EMAIL STUB] Verify email: http://localhost:5173/verify?token={user.email_verification_token}")

    return user
```

- [ ] **Step 2: Run full test suite**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/app/auth/service.py
git commit -m "feat(auth): set current_period_end at registration for free-tier billing cycle"
```

---

### Task 17: Update Build Log

**Files:**
- Modify: `docs/build_log.md`

- [ ] **Step 1: Add Week 4 entry to build log**

Append the following to `docs/build_log.md`:

```markdown
## 2026-03-13 — Session 5: Week 4 Implementation (Billing + Polish + Launch)

### DECISION_008: Billing Model
- 3-tier credit-based subscriptions: free (10/mo), starter ($19/mo, 100), pro ($49/mo, unlimited)
- Billing state on User model (5 new columns), no separate tables
- Atomic credit enforcement via UPDATE...WHERE...RETURNING
- Stripe Checkout for subscription creation, Billing Portal for management
- Out-of-order webhook protection via event timestamps

### DECISION_009: Video Lifecycle & Cleanup
- Enhanced user-initiated delete: immediate S3 cleanup, soft-delete DB records
- DB records retained 7 days for undo
- Daily ARQ cron task: auto-expire (30d), hard-delete (7d after soft-delete), billing reset
- Per-video transactions, skip auto-expire for videos with running jobs

### Database Changes
- `User.stripe_customer_id` (String, unique) — Stripe customer reference
- `User.subscription_tier` (String, CHECK: free/starter/pro, default: free)
- `User.subscription_stripe_id` (String) — Stripe subscription ID
- `User.current_period_end` (DateTime) — billing cycle end
- `User.period_exports_used` (Integer, default: 0) — reset on invoice.paid
- Alembic migration generated and committed

### Billing Backend
- `billing/service.py`: Stripe checkout, portal, webhook handlers, credit checks
- `billing/router.py`: POST /checkout, POST /portal, GET /status, POST /webhook
- `billing/schemas.py`: CheckoutRequest, PortalResponse, BillingStatusResponse
- Credit enforcement replaces 24-hour rate limit in export endpoint
- Free-tier reset via daily cron + current_period_end at registration

### Video Lifecycle
- Enhanced `soft_delete_video`: immediate S3 cleanup, export S3 cleanup, job cancellation
- `cleanup_expired_content` ARQ cron task: auto-expire, hard-delete, billing reset
- Per-video transactions, dependency-order deletes (exports → clips → transcript → jobs → video)

### Export API Enhancement
- `GET /exports/` — paginated user export history for account page

### Frontend
- `LandingPage.tsx`: Hero, how it works, features, pricing, footer
- `AccountPage.tsx`: Profile, subscription management, export history
- `TermsPage.tsx`: Placeholder Terms of Service
- `PrivacyPage.tsx`: Placeholder Privacy Policy
- `App.tsx`: Conditional landing/dashboard routing, new page routes
- `DashboardPage.tsx`: Account link in header

### Stats
- **XX tests passing** across XX test files (+XX from Week 3)
- **9 DECISION docs** filed (DECISION_001 through DECISION_009)
- **XX commits** on develop for Week 4
- **Backend:** billing module (service, router, schemas), enhanced delete, cleanup task
- **Frontend:** LandingPage, AccountPage, TermsPage, PrivacyPage, routing updates
```

Note: Replace `XX` placeholders with actual counts after all tests pass.

- [ ] **Step 2: Commit**

```bash
git add docs/build_log.md
git commit -m "docs: update build log with Week 4 implementation summary"
```

---

### Task 18: Merge to Main + Tag v1.0.0

- [ ] **Step 1: Run all tests one final time**

```bash
cd /Users/justin/CascadeProjects/clipforge && python -m pytest backend/tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 2: Verify frontend builds**

```bash
cd /Users/justin/CascadeProjects/clipforge/frontend && npm run build
```

Expected: Build succeeds.

- [ ] **Step 3: Merge develop to main**

```bash
git checkout main
git merge develop --no-ff -m "feat: Week 4 — billing, account management, landing page, video cleanup, legal"
```

- [ ] **Step 4: Tag v1.0.0**

```bash
git tag -a v1.0.0 -m "release: billing live, public launch"
```

- [ ] **Step 5: Switch back to develop**

```bash
git checkout develop
```
