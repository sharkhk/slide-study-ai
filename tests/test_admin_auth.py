"""
Offline tests for the /admin authentication redesign (token no longer leaks into
request logs, the page source or localStorage).

WHAT THIS GUARDS
    1. ?token= in the URL never authenticates any more; GET /admin?token=... is
       302-redirected to plain /admin (and the onrender -> alimne.app canonical
       redirect does not carry the token across either).
    2. Scripts can still authenticate with the X-Admin-Token header.
    3. POST /admin/login sets an HttpOnly / Secure / SameSite=Strict, Path=/admin
       cookie holding an HMAC derived from ADMIN_TOKEN (never the token itself);
       'remember' makes it a 30-day cookie, otherwise a session cookie. A wrong
       token is a 401 and the endpoint is rate limited per IP.
    4. Cookie-authenticated admin POSTs must carry X-Requested-With:
       alimne-admin (CSRF defence in depth); header-authenticated ones need not.
    5. The dashboard / gate HTML never contains the token; the gate removes the
       legacy localStorage key and never stores the token again.
    6. POST /admin/logout clears the cookie; rotating ADMIN_TOKEN invalidates
       every existing cookie.
    7. The visitor tracker and the app log never record the token.

EVERYTHING IS OFFLINE (no Supabase / Stripe / network). The token below is a
dummy test value, not a real secret.
Run:  python -m pytest -q
"""
import hashlib
import hmac
import logging

import pytest

import app as appmod

TOKEN = "test-admin-token-not-a-real-secret-0001"
CSRF = {"X-Requested-With": "alimne-admin"}


@pytest.fixture
def client(monkeypatch):
    appmod.app.config["TESTING"] = True
    monkeypatch.setattr(appmod, "ADMIN_TOKEN", TOKEN)
    monkeypatch.setattr(appmod, "_rate_limit", {})
    return appmod.app.test_client()


def _admin_cookie_header(resp):
    for h in resp.headers.getlist("Set-Cookie"):
        if h.startswith("alimne_admin="):
            return h
    return None


def _attrs(set_cookie):
    """'k=v; HttpOnly; Path=/admin' -> {'httponly': '', 'path': '/admin', ...}"""
    out = {}
    for part in set_cookie.split(";")[1:]:
        k, _, v = part.strip().partition("=")
        out[k.lower()] = v
    return out


def _expected_session(token=TOKEN):
    return hmac.new(token.encode(), b"alimne-admin-session-v1", hashlib.sha256).hexdigest()


def _login(client, token=TOKEN, remember=True, **kw):
    return client.post("/admin/login", json={"token": token, "remember": remember}, **kw)


# ── 1. the query string no longer authenticates ─────────────────────────────────
def test_query_token_never_authenticates_and_redirects_to_plain_admin(client):
    r = client.get(f"/admin?token={TOKEN}")
    assert r.status_code == 302
    loc = r.headers["Location"]
    assert loc.endswith("/admin") and "?" not in loc and TOKEN not in loc
    assert _admin_cookie_header(r) is None          # the redirect does not log you in
    assert TOKEN not in r.get_data(as_text=True)

    # Following it lands on the (unauthenticated) gate, not the dashboard.
    r2 = client.get("/admin")
    assert r2.status_code == 401
    assert "Subscribers" not in r2.get_data(as_text=True)

    # A query token on an admin POST is ignored too.
    assert client.post(f"/admin/clear?token={TOKEN}").status_code == 401


def test_any_admin_query_string_is_stripped(client):
    r = client.get("/admin?token=wrong&x=1")
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin")


def test_canonical_onrender_redirect_drops_admin_query(client):
    r = client.get(f"/admin?token={TOKEN}", base_url="https://slide-study-ai.onrender.com")
    assert r.status_code == 301
    assert r.headers["Location"] == "https://alimne.app/admin"
    # Non-admin pages keep their query string exactly as before.
    r2 = client.get("/s/abc123?x=1", base_url="https://slide-study-ai.onrender.com")
    assert r2.headers["Location"] == "https://alimne.app/s/abc123?x=1"


# ── 2. header auth (scripts) ────────────────────────────────────────────────────
def test_header_auth_works_without_csrf_header(client):
    r = client.post("/admin/clear", headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    page = client.get("/admin", headers={"X-Admin-Token": TOKEN})
    assert page.status_code == 200 and "Subscribers" in page.get_data(as_text=True)
    assert client.post("/admin/clear", headers={"X-Admin-Token": "nope"}).status_code == 401


def test_non_ascii_admin_header_is_rejected_not_a_500(client):
    # secrets.compare_digest raises TypeError on non-ASCII str input.
    r = client.post("/admin/clear", headers={"X-Admin-Token": "café"})
    assert r.status_code == 401


# ── 3. login ────────────────────────────────────────────────────────────────────
def test_login_sets_hardened_cookie_and_cookie_authenticates(client):
    r = _login(client, remember=True)
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    sc = _admin_cookie_header(r)
    assert sc is not None
    value = sc.split(";", 1)[0].split("=", 1)[1]
    assert value == _expected_session() and TOKEN not in sc
    a = _attrs(sc)
    assert "httponly" in a and "secure" in a
    assert a.get("samesite", "").lower() == "strict"
    assert a.get("path") == "/admin"
    assert a.get("max-age") == str(30 * 24 * 3600)
    assert "no-store" in r.headers.get("Cache-Control", "")

    page = client.get("/admin")
    assert page.status_code == 200 and "Subscribers" in page.get_data(as_text=True)
    assert "no-store" in page.headers.get("Cache-Control", "")


def test_login_without_remember_is_a_session_cookie(client):
    r = _login(client, remember=False)
    assert r.status_code == 200
    a = _attrs(_admin_cookie_header(r))
    assert "max-age" not in a and "expires" not in a
    assert "httponly" in a and "secure" in a and a.get("samesite", "").lower() == "strict"


@pytest.mark.parametrize("body", [
    {"token": "wrong-token", "remember": True},
    {"token": "", "remember": True},
    {"token": 12345},
    {"remember": True},
    {"token": "café"},
])
def test_wrong_token_is_401_and_sets_no_cookie(client, body):
    r = client.post("/admin/login", json=body)
    assert r.status_code == 401
    assert r.get_json()["ok"] is False
    assert _admin_cookie_header(r) is None
    assert client.get("/admin").status_code == 401


def test_login_is_rate_limited_per_ip(client):
    ip = {"REMOTE_ADDR": "203.0.113.7"}
    for _ in range(10):
        assert client.post("/admin/login", json={"token": "guess"}, environ_base=ip).status_code == 401
    r = _login(client, environ_base=ip)          # even the right token is throttled now
    assert r.status_code == 429 and _admin_cookie_header(r) is None
    # A different IP is unaffected.
    assert _login(client, environ_base={"REMOTE_ADDR": "203.0.113.8"}).status_code == 200


# ── 4. CSRF defence in depth for cookie-authenticated POSTs ─────────────────────
def test_cookie_post_requires_x_requested_with(client):
    _login(client)
    assert client.post("/admin/clear").status_code == 401
    assert client.post("/admin/clear", headers={"X-Requested-With": "XMLHttpRequest"}).status_code == 401
    assert client.post("/admin/block", json={"ip": "198.51.100.1"}).status_code == 401
    assert "198.51.100.1" not in appmod._blocked_ips

    r = client.post("/admin/clear", headers=CSRF)
    assert r.status_code == 200 and r.get_json()["ok"] is True
    r = client.post("/admin/block", json={"ip": "198.51.100.1"}, headers=CSRF)
    assert r.status_code == 200
    r = client.post("/admin/unblock", json={"ip": "198.51.100.1"}, headers=CSRF)
    assert r.status_code == 200 and "198.51.100.1" not in appmod._blocked_ips
    # grant/cancel get past auth (then fail validation, proving auth passed)
    assert client.post("/admin/user/grant", json={"user_id": "x", "amount": 1}, headers=CSRF).status_code == 400
    assert client.post("/admin/user/cancel", json={"user_id": "x"}, headers=CSRF).status_code == 400
    assert client.post("/admin/user/grant", json={"user_id": "x", "amount": 1}).status_code == 401
    assert client.post("/admin/user/cancel", json={"user_id": "x"}).status_code == 401


# ── 5. the token never reaches the page ─────────────────────────────────────────
def test_dashboard_and_gate_html_never_contain_the_token(client):
    gate = client.get("/admin")
    assert gate.status_code == 401
    g = gate.get_data(as_text=True)
    assert TOKEN not in g
    assert 'localStorage.removeItem("alimne_admin_token")' in g     # migration
    assert "localStorage.setItem" not in g and "?token=" not in g
    assert "/admin/login" in g
    # bilingual (English + Arabic) user-facing text
    assert "Remember on this device" in g and "تذكّرني على هذا الجهاز" in g
    assert 'dir="rtl"' in g

    _login(client)
    for page in (client.get("/admin"), client.get("/admin", headers={"X-Admin-Token": TOKEN})):
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert TOKEN not in html
        assert "const TOKEN" not in html and "X-Admin-Token" not in html
        assert "localStorage.setItem" not in html
        assert "alimne-admin" in html and "X-Requested-With" in html
        assert "/admin/logout" in html


# ── 6. logout + rotation ────────────────────────────────────────────────────────
def test_logout_clears_cookie(client):
    _login(client)
    assert client.get("/admin").status_code == 200
    r = client.post("/admin/logout", headers=CSRF)
    assert r.status_code == 200 and r.get_json()["ok"] is True
    sc = _admin_cookie_header(r)
    assert sc is not None
    a = _attrs(sc)
    assert sc.startswith("alimne_admin=;") and a.get("max-age") == "0"
    assert a.get("path") == "/admin"
    assert client.get("/admin").status_code == 401
    assert client.post("/admin/clear", headers=CSRF).status_code == 401


def test_rotating_admin_token_invalidates_existing_cookies(client, monkeypatch):
    _login(client)
    assert client.get("/admin").status_code == 200
    monkeypatch.setattr(appmod, "ADMIN_TOKEN", "rotated-test-admin-token-0002")
    assert client.get("/admin").status_code == 401
    assert client.post("/admin/clear", headers=CSRF).status_code == 401
    assert client.get("/admin/session").status_code == 401
    # the new token works (via header and a fresh login)
    assert client.post("/admin/clear", headers={"X-Admin-Token": "rotated-test-admin-token-0002"}).status_code == 200
    assert _login(client, token="rotated-test-admin-token-0002").status_code == 200
    assert client.get("/admin").status_code == 200


def test_session_probe(client):
    assert client.get("/admin/session").status_code == 401
    _login(client)
    assert client.get("/admin/session").status_code == 204


# ── 7. tracker + logs never record the token ────────────────────────────────────
def test_visitor_tracker_and_logs_never_record_the_token(client, caplog):
    with appmod._vis_lock:
        appmod._visitors.clear()
    with caplog.at_level(logging.DEBUG):
        client.get(f"/admin?token={TOKEN}")
        client.post("/admin/login", json={"token": "wrong-" + TOKEN})
        _login(client)
        client.get("/admin")
        # (not /admin/clear — that would empty the very list we inspect)
        client.post("/admin/unblock", json={"ip": "198.51.100.2"}, headers={"X-Admin-Token": TOKEN})
    with appmod._vis_lock:
        recorded = repr(appmod._visitors)
        paths = [v["path"] for v in appmod._visitors]
    assert TOKEN not in recorded
    assert all("?" not in p for p in paths)
    assert TOKEN not in caplog.text
    assert _expected_session() not in caplog.text and _expected_session() not in recorded
