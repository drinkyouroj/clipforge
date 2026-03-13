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
