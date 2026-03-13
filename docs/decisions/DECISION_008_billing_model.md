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
