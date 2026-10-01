"""
Admin session cookies expire and can be revoked on the server (review, 2026-10-01).

Bug: the alimne_admin cookie was HMAC(ADMIN_TOKEN, constant) - the SAME value for
every login on every device, with no issue time. Sign out only deleted it in that
one browser and an unticked "Remember" only made it a browser-session cookie, so a
value copied once (shared/stolen device, HAR export, cookie-reading extension) kept
full admin power until ADMIN_TOKEN was rotated.

Now the cookie carries a signed issue time and lifetime: the server rejects it after
30 days with "Remember", after 12 hours without, and Sign out (when it is really the
signed-in admin asking) revokes every cookie issued before it. Rotating ADMIN_TOKEN
still invalidates everything.

EVERYTHING IS OFFLINE. The token below is a dummy test value, not a real secret.
"""
import time as _real_time

import pytest

import app as appmod

TOKEN = "test-admin-token-not-a-real-secret-0003"
CSRF = {"X-Requested-With": "alimne-admin"}
DAY = 24 * 3600


@pytest.fixture
def clock(monkeypatch):
    """A controllable time.time() for app.py (the rest of time is untouched)."""
    now = {"t": 1_900_000_000.0}

    class _T:
        def __getattr__(self, name):
            return getattr(_real_time, name)

        @staticmethod
        def time():
            return now["t"]

    monkeypatch.setattr(appmod, "time", _T())
    return now


@pytest.fixture
def client(monkeypatch, clock):
    appmod.app.config["TESTING"] = True
    monkeypatch.setattr(appmod, "ADMIN_TOKEN", TOKEN)
    monkeypatch.setattr(appmod, "_rate_limit", {})
    monkeypatch.setattr(appmod, "_admin_not_before", [0])
    return appmod.app.test_client()


def _cookie_value(resp):
    for h in resp.headers.getlist("Set-Cookie"):
        if h.startswith("alimne_admin="):
            return h.split(";", 1)[0].split("=", 1)[1]
    return None


def _login(client, remember=True):
    r = client.post("/admin/login", json={"token": TOKEN, "remember": remember})
    assert r.status_code == 200
    return _cookie_value(r)


def _fresh(value):
    """A brand-new browser that only has this cookie value (a copied cookie)."""
    c = appmod.app.test_client()
    c.set_cookie("alimne_admin", value, path="/admin")
    return c


def test_every_login_gets_its_own_cookie_value(client, clock):
    a = _login(client)
    b = _login(client)                 # even within the same millisecond
    clock["t"] += 5
    c = _login(client)
    assert a and b and c and len({a, b, c}) == 3, "two logins must not share one cookie value"
    assert TOKEN not in a


def test_remember_cookie_is_rejected_by_the_server_after_30_days(client, clock):
    value = _login(client, remember=True)
    clock["t"] += 29 * DAY
    assert _fresh(value).get("/admin/session").status_code == 204
    clock["t"] += 2 * DAY
    assert _fresh(value).get("/admin/session").status_code == 401
    assert _fresh(value).get("/admin").status_code == 401


def test_session_cookie_is_rejected_by_the_server_after_12_hours(client, clock):
    value = _login(client, remember=False)
    clock["t"] += 11 * 3600
    assert _fresh(value).get("/admin/session").status_code == 204
    clock["t"] += 2 * 3600
    assert _fresh(value).get("/admin/session").status_code == 401


def test_sign_out_revokes_a_copied_cookie(client, clock):
    """The reviewer's probe: login, sign out, then replay the old value elsewhere."""
    stolen = _login(client)
    other_device = _login(client)
    clock["t"] += 1
    r = client.post("/admin/logout", headers=CSRF)
    assert r.status_code == 200
    assert _fresh(stolen).get("/admin/session").status_code == 401
    assert _fresh(stolen).post("/admin/clear", headers=CSRF).status_code == 401
    # Sign out ends every session, on every device.
    assert _fresh(other_device).get("/admin/session").status_code == 401


def test_signing_in_again_right_after_sign_out_works(client, clock):
    _login(client)
    client.post("/admin/logout", headers=CSRF)
    # same clock tick: the new session must not be caught by the revocation
    value = _login(client)
    assert _fresh(value).get("/admin/session").status_code == 204
    assert client.get("/admin").status_code == 200


def test_unauthenticated_logout_cannot_sign_the_admin_out(client, clock):
    value = _login(client)
    stranger = appmod.app.test_client()
    assert stranger.post("/admin/logout").status_code == 200        # clears only its own cookie
    assert stranger.post("/admin/logout", headers=CSRF).status_code == 200
    # a cookie-holder without the CSRF header (e.g. a cross-site form) is not the admin either
    _fresh(value).post("/admin/logout")
    assert _fresh(value).get("/admin/session").status_code == 204


@pytest.mark.parametrize("bad", [
    "", "v2", "v2.1.2", "v2.x.2592000.ab.cd", "v1.1900000000000.2592000.ab.00",
    "v2.1900000000000.2592000.abcd." + "0" * 64,
    "v2.1900000000000.99999999999.abcd." + "0" * 64,
    "v2.１９.2592000.abcd." + "0" * 64,               # non-ASCII digits
    "v2." + "1" * 600 + ".2592000.abcd." + "0" * 64,
])
def test_malformed_or_forged_cookies_are_rejected(client, bad):
    assert _fresh(bad).get("/admin/session").status_code == 401


def test_lifetime_and_issue_time_cannot_be_edited(client, clock):
    value = _login(client, remember=False)
    ver, iat, ttl, nonce, sig = value.split(".")
    longer = ".".join([ver, iat, str(365 * DAY), nonce, sig])
    later = ".".join([ver, str(int(iat) + 10 * DAY * 1000), ttl, nonce, sig])
    clock["t"] += 13 * 3600
    assert _fresh(longer).get("/admin/session").status_code == 401
    assert _fresh(later).get("/admin/session").status_code == 401


def test_a_cookie_from_the_future_is_rejected(client, clock):
    clock["t"] += 10 * DAY
    value = _login(client)
    clock["t"] -= 10 * DAY
    assert _fresh(value).get("/admin/session").status_code == 401


def test_rotating_admin_token_still_invalidates_every_cookie(client, monkeypatch):
    value = _login(client)
    monkeypatch.setattr(appmod, "ADMIN_TOKEN", "rotated-test-admin-token-0004")
    assert _fresh(value).get("/admin/session").status_code == 401


def test_sign_out_button_says_it_signs_out_every_device(client):
    _login(client)
    html = client.get("/admin").get_data(as_text=True)
    assert "on every device" in html and "على جميع الأجهزة" in html
