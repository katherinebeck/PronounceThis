# Ready-to-sell audit (no changes made) — see chat response for full text

Key findings
- Stripe (preview env is a SANDBOX account, AU, "American Accent Prep sandbox"): product prod_VCpoaMFmXT1deV "American Accent Prep — Membership"; prices accent_coach_monthly $9/mo (price_1UCQ8zE3YhPWHalzLKoouN3Q), accent_coach_yearly $90/yr (price_1UCQ90E3YhPWHalzIuLrkDh9); no trial days; webhook → preview URL, events "*"; NO saved Customer Portal configuration in test mode; 0 customers/subs in test. Live-mode config not verifiable from preview (production secrets).
- Checkout requires login first (POST /payments/checkout → require_login). Buy-first is not supported.
- Access = memberships row status active && (end null or future). past_due keeps access; subscription.deleted → end=now. Plan display comes from subscription metadata lookup_key → does NOT update on monthly→annual via Portal (offer_title stale, duplicate membership rows possible).
- sync_from_stripe_customer treats past_due as inactive (inconsistent with webhook path).
- Kit/ConvertKit: no integration, no keys. Recommend native Stripe→Kit (Kit's Stripe integration) — no backend code.
- Sales page: none; app root is the product (Word page). Payment success/cancel pages exist. No /pricing route.
- Legacy Kajabi env vars + kajabi router still mounted (unused).

Minimum build (proposed, awaiting approval)
1. Public /pricing sales page in-app (dark theme), CTAs → Checkout.
2. Guest checkout: allow POST /payments/checkout without login (Stripe collects email); success page auto-sends magic link; _grant_from_session creates user (already does) and uses customer_details.email fallback.
3. Plan-change correctness: derive lookup_key from subscription.items[0].price.lookup_key (not metadata); one membership row per customer (offer_id "stripe") or supersede rows.
4. Save Stripe Customer Portal configuration (live + test): cancel at period end, switch monthly↔annual with proration, update payment method, invoices.
5. Live-mode checklist: live keys in production secrets, live webhook endpoint https://app.katherinebeck.com/api/stripe/webhook, live prices with same lookup_keys, rename product to Pronounce This.
6. Optional: remove Kajabi router/env; align sync_from_stripe_customer with past_due rule; welcome email.
