"""
Offline smoke suite for the Alimne (slide-study-ai) payment path.

WHAT THIS GUARDS
    1. The Flask app imports and its routes register (test client boots).
    2. The JWT verify helpers accept a valid token and reject a bad one.
    3. POST /api/stripe/checkout builds a session URL and handles the
       stale/deleted Stripe customer guard (recreates the customer).
    4. POST /api/stripe/webhook verifies signatures, grants tokens on
       checkout.session.completed, and is idempotent (no double-grant).

EVERYTHING IS MOCKED. This suite makes NO real network calls: no Stripe API,
no Supabase, no Groq. It never moves money and never touches real keys.

Run:  python -m pytest -q
"""
import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest

import app as appmod


# ── shared fixtures / helpers ────────────────────────────────────────────────
@pytest.fixture
def client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def _make_fake_stripe():
    """A stand-in for the `stripe` module.

    error.SignatureVerificationError must be a REAL exception class because the
    webhook handler uses it in an `except` clause; everything else is a mock.
    """
    class SignatureVerificationError(Exception):
        pass

    fake = SimpleNamespace()
    fake.error = SimpleNamespace(SignatureVerificationError=SignatureVerificationError)
    fake.Webhook = SimpleNamespace(construct_event=MagicMock())
    fake.Customer = SimpleNamespace(retrieve=MagicMock(), create=MagicMock())
    fake.checkout = SimpleNamespace(Session=SimpleNamespace(create=MagicMock()))
    return fake


# ── 1. app boots + routes register ───────────────────────────────────────────
def test_app_imports_and_routes_register():
    rules = {r.rule for r in appmod.app.url_map.iter_rules()}
    # The payment path this suite guards must be wired up.
    assert "/api/stripe/checkout" in rules
    assert "/api/stripe/webhook" in rules
    assert "/api/config" in rules


def test_config_endpoint_boots_offline(client):
    # A lightweight GET proves the test client boots and serves a route without
    # any external service configured.
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "auth_enabled" in body
    # No SUPABASE_URL in this offline run → auth is disabled.
    assert body["auth_enabled"] is False


# ── 2. JWT verify helper: valid accepted, bad rejected ───────────────────────
def test_jwt_verify_accepts_valid_and_rejects_bad(monkeypatch):
    secret = "test-hs256-secret-not-a-real-key"
    # Route the helper down the HS256 (shared-secret) branch.
    monkeypatch.setattr(appmod, "SUPABASE_JWT_SECRET", secret)

    good = pyjwt.encode(
        {"sub": "user-123", "aud": "authenticated", "exp": int(time.time()) + 3600},
        secret,
        algorithm="HS256",
    )
    assert appmod._verify_jwt(good) == "user-123"

    payload = appmod._jwt_payload(good)
    assert payload is not None and payload["sub"] == "user-123"

    # Signed with the WRONG secret → must be rejected.
    forged = pyjwt.encode(
        {"sub": "attacker", "aud": "authenticated", "exp": int(time.time()) + 3600},
        "a-different-secret-that-is-also-32-bytes-long",
        algorithm="HS256",
    )
    assert appmod._verify_jwt(forged) is None

    # Garbage / empty tokens → rejected.
    assert appmod._verify_jwt("not.a.jwt") is None
    assert appmod._verify_jwt(None) is None


# ── 3. checkout session creation (+ stale customer guard) ─────────────────────
def _prime_checkout(monkeypatch, fake_stripe, user):
    """Wire the checkout route to run fully offline."""
    monkeypatch.setattr(appmod, "_stripe", fake_stripe)
    monkeypatch.setattr(appmod, "STRIPE_PRICE_ID", "price_test_123")
    monkeypatch.setattr(appmod, "_get_user", lambda uid: user)
    # A chainable mock so the "persist new customer id" write is a no-op.
    monkeypatch.setattr(appmod, "_get_sb", lambda: MagicMock())
    fake_stripe.checkout.Session.create.return_value = SimpleNamespace(
        url="https://checkout.stripe.com/session_test"
    )


def test_checkout_reuses_existing_valid_customer(client, monkeypatch):
    fake = _make_fake_stripe()
    _prime_checkout(monkeypatch, fake, {"email": "s@x.com", "name": "S",
                                        "stripe_customer_id": "cus_existing"})
    # A live, non-deleted customer.
    fake.Customer.retrieve.return_value = SimpleNamespace(deleted=False)

    resp = client.post("/api/stripe/checkout")
    assert resp.status_code == 200
    assert resp.get_json()["url"] == "https://checkout.stripe.com/session_test"

    fake.Customer.retrieve.assert_called_once_with("cus_existing")
    fake.Customer.create.assert_not_called()  # reused, not recreated
    _, kwargs = fake.checkout.Session.create.call_args
    assert kwargs["customer"] == "cus_existing"


def test_checkout_recreates_stale_customer(client, monkeypatch):
    """The stale-customer guard: a stored id that no longer exists in Stripe
    (retrieve raises "No such customer") must NOT fail checkout — a new customer
    is created instead."""
    fake = _make_fake_stripe()
    _prime_checkout(monkeypatch, fake, {"email": "s@x.com", "name": "S",
                                        "stripe_customer_id": "cus_orphaned"})
    fake.Customer.retrieve.side_effect = Exception("No such customer: cus_orphaned")
    fake.Customer.create.return_value = {"id": "cus_new"}

    resp = client.post("/api/stripe/checkout")
    assert resp.status_code == 200
    assert resp.get_json()["url"] == "https://checkout.stripe.com/session_test"

    fake.Customer.create.assert_called_once()  # recreated
    _, kwargs = fake.checkout.Session.create.call_args
    assert kwargs["customer"] == "cus_new"


def test_checkout_recreates_deleted_customer(client, monkeypatch):
    """A retrievable-but-deleted customer is also treated as stale."""
    fake = _make_fake_stripe()
    _prime_checkout(monkeypatch, fake, {"email": "s@x.com", "name": "S",
                                        "stripe_customer_id": "cus_deleted"})
    fake.Customer.retrieve.return_value = SimpleNamespace(deleted=True)
    fake.Customer.create.return_value = {"id": "cus_fresh"}

    resp = client.post("/api/stripe/checkout")
    assert resp.status_code == 200
    fake.Customer.create.assert_called_once()
    _, kwargs = fake.checkout.Session.create.call_args
    assert kwargs["customer"] == "cus_fresh"


def test_checkout_503_when_stripe_unconfigured(client, monkeypatch):
    monkeypatch.setattr(appmod, "_stripe", None)
    resp = client.post("/api/stripe/checkout")
    assert resp.status_code == 503


# ── 4. webhook: signature handling, token grant, idempotency ─────────────────
def _grant_event(event_id):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"user_id": "u-42"}}},
    }


def test_webhook_rejects_bad_signature(client, monkeypatch):
    fake = _make_fake_stripe()
    monkeypatch.setattr(appmod, "_stripe", fake)
    fake.Webhook.construct_event.side_effect = fake.error.SignatureVerificationError("bad")

    resp = client.post("/api/stripe/webhook", data=b"{}",
                       headers={"Stripe-Signature": "bogus"})
    assert resp.status_code == 400
    assert "signature" in resp.get_json()["error"].lower()


def test_webhook_rejects_malformed_payload(client, monkeypatch):
    fake = _make_fake_stripe()
    monkeypatch.setattr(appmod, "_stripe", fake)
    fake.Webhook.construct_event.side_effect = ValueError("not json")

    resp = client.post("/api/stripe/webhook", data=b"garbage")
    assert resp.status_code == 400
    assert "payload" in resp.get_json()["error"].lower()


def test_webhook_grants_tokens_and_is_idempotent(client, monkeypatch):
    fake = _make_fake_stripe()
    monkeypatch.setattr(appmod, "_stripe", fake)

    sb = MagicMock()
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)
    # Isolate the referral side-effect; we only assert the token grant here.
    monkeypatch.setattr(appmod, "_award_referral", MagicMock())

    event = _grant_event("evt_grant_unique_1")
    fake.Webhook.construct_event.return_value = event

    # First delivery → grants tokens.
    resp1 = client.post("/api/stripe/webhook", data=b"{}",
                        headers={"Stripe-Signature": "sig"})
    assert resp1.status_code == 200
    first = resp1.get_json()
    assert first.get("ok") is True
    assert not first.get("deduped")

    # The grant path wrote to the users table exactly once.
    assert sb.table.call_args_list[0][0][0] == "users"
    update_arg = sb.table.return_value.update.call_args[0][0]
    assert update_arg["subscription_status"] == "active"
    assert update_arg["tokens_remaining"] == 30
    grant_writes = sb.table.return_value.update.call_count

    # Second delivery of the SAME event id → deduped, no further grant.
    resp2 = client.post("/api/stripe/webhook", data=b"{}",
                        headers={"Stripe-Signature": "sig"})
    assert resp2.status_code == 200
    assert resp2.get_json().get("deduped") is True
    # No additional update write happened on the replay.
    assert sb.table.return_value.update.call_count == grant_writes


def test_webhook_503_when_stripe_unconfigured(client, monkeypatch):
    monkeypatch.setattr(appmod, "_stripe", None)
    resp = client.post("/api/stripe/webhook", data=b"{}")
    assert resp.status_code == 503
