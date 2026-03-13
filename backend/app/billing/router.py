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
