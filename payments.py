# payments.py
# One-off "Full house" unlock using Stripe Checkout.
# Card details go to Stripe's secure page and never touch this app.
# Stripe is the "source of truth": we ask Stripe whether this user has paid.

from datetime import datetime, timedelta, timezone

import stripe

from ai_scanner import get_secret

PRICE_TEXT = "NZ$19"
ACCESS_DAYS = 365          # how long one payment unlocks the full house

FREE_ROOMS = 2             # free plan: rooms you can save
FREE_SCANS = 5             # free plan: AI scans per 30 days
PAID_SCANS = 30            # paid plan: AI scans per 30 days


def _setup():
    key = get_secret("STRIPE_SECRET_KEY")
    if not key:
        raise RuntimeError("Payments aren't set up yet (no STRIPE_SECRET_KEY).")
    stripe.api_key = key


def create_checkout_url(user):
    """Ask Stripe for a secure payment page for this user, and return its web address."""
    _setup()
    app_url = (get_secret("APP_URL") or "http://localhost:8501").rstrip("/")

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{"price": get_secret("STRIPE_PRICE_ID"), "quantity": 1}],
        customer_email=user["email"],
        client_reference_id=user["id"],
        metadata={"user_id": user["id"]},
        # Copy the user ID onto the payment itself, so we can find it again later
        payment_intent_data={"metadata": {"user_id": user["id"]}},
        # After paying, Stripe sends them back here with the session ID in the web address
        success_url=f"{app_url}/?checkout_session={{CHECKOUT_SESSION_ID}}",
        cancel_url=app_url,
    )
    return session.url


def verify_checkout(session_id, user):
    """When someone comes back from Stripe: check that THIS user really paid."""
    _setup()
    session = stripe.checkout.Session.retrieve(session_id)
    return session.payment_status == "paid" and session.client_reference_id == user["id"]


def has_paid(user):
    """Ask Stripe: has this user made a successful payment in the last year?"""
    _setup()
    results = stripe.PaymentIntent.search(
        query=f"metadata['user_id']:'{user['id']}' AND status:'succeeded'",
        limit=10,
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=ACCESS_DAYS)
    return any(
        datetime.fromtimestamp(p.created, timezone.utc) > cutoff
        for p in results.data
    )
