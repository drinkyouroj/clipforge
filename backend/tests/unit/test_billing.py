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
