"""Idempotent Stripe catalog setup for Accent Coach.

Run once to create the Product + Prices in the connected sandbox. Safe to
re-run — dedupes on `metadata.emergent_product_id` for the product and on
`lookup_key` for the price.

    python setup_stripe.py
"""
from __future__ import annotations

import os
from pathlib import Path

import stripe
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

EMERGENT_PRODUCT_ID = "accent_coach"
TAX_CODE = "txcd_10103001"  # SaaS

CATALOG = {
    "name": "Pronounce This — Membership",
    "prices": [
        {"lookup_key": "accent_coach_monthly", "amount": 900, "currency": "usd", "interval": "month"},
        {"lookup_key": "accent_coach_yearly", "amount": 9000, "currency": "usd", "interval": "year"},
    ],
}


def get_or_create_product() -> stripe.Product:
    for p in stripe.Product.list(active=True).auto_paging_iter():
        if p.to_dict().get("metadata", {}).get("emergent_product_id") == EMERGENT_PRODUCT_ID:
            print(f"Reusing product {p.id}")
            return p
    p = stripe.Product.create(
        name=CATALOG["name"],
        tax_code=TAX_CODE,
        metadata={"managed_by": "emergent", "emergent_product_id": EMERGENT_PRODUCT_ID},
    )
    print(f"Created product {p.id}")
    return p


def ensure_price(product_id: str, spec: dict) -> None:
    existing = stripe.Price.list(
        lookup_keys=[spec["lookup_key"]], active=True, limit=1
    ).data
    if existing:
        e = existing[0]
        same_amount = e.unit_amount == spec["amount"] and e.currency == spec["currency"]
        if same_amount:
            print(f"  Reusing price {e.id} ({spec['lookup_key']})")
            return
        # Amount changed — archive the old and create a new one under the same lookup_key.
        stripe.Price.modify(e.id, active=False)
        print(f"  Archived stale price {e.id} ({spec['lookup_key']})")
    kwargs = dict(
        product=product_id,
        unit_amount=spec["amount"],
        currency=spec["currency"],
        lookup_key=spec["lookup_key"],
        transfer_lookup_key=True,
    )
    if spec.get("interval"):
        kwargs["recurring"] = {"interval": spec["interval"]}
    p = stripe.Price.create(**kwargs)
    print(f"  Created price {p.id} ({spec['lookup_key']}, ${spec['amount']/100}/{spec.get('interval','once')})")


def main():
    product = get_or_create_product()
    for spec in CATALOG["prices"]:
        ensure_price(product.id, spec)
    print("Done.")


if __name__ == "__main__":
    main()
