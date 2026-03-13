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
