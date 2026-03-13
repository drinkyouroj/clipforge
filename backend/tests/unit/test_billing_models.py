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
