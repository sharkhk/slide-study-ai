"""
Offline tests for the login + download-recovery fixes (server side).

WHAT THIS GUARDS
    1. /api/guide returns a canonical, HMAC-signed guide_blob, and POST
       /api/rehydrate rebuilds the PDF from it (free, new job id) while rejecting
       tampered, unsigned, oversized or key-less requests.
    2. _auth_optional is tri-state (uid / None = no token / False = token sent
       but rejected), and the generation endpoints answer 401 BEFORE any credit
       is spent instead of silently treating a signed-in user as anonymous.
    3. Distinct auth codes (auth_required / token_expired / token_invalid /
       auth_unavailable), JWT leeway, and the JWKS last-good-key fallback.
    4. /api/auth/me: effective tokens + plan, 503 retry on DB errors.
    5. Job endpoints answer 404 code 'expired'; the print view wraps tables,
       sets lang/dir/viewport and shows a bilingual expired page.
    6. Refund guard: a disconnect or failure refunds exactly once; a hollow
       guide (no notes) is a refunded error; 'partial' flags a missing quiz.
    7. Misc: 413 JSON, onrender → alimne.app redirect, sweeper, /api/config
       never waits on a slow DB.

EVERYTHING IS OFFLINE: no Supabase, Groq, Stripe or JWKS network calls.
Run:  python -m pytest -q
"""
import hashlib
import hmac
import io
import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest

import app as appmod

SECRET = "test-hs256-secret-not-a-real-key-0000"   # >= 32 bytes (no PyJWT key warning)
KEY = b"test-guide-signing-key"


# ── helpers ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def _guide(lang="en", flashcards=True):
    return {
        "title": "Photosynthesis" if lang == "en" else "البناء الضوئي",
        "subtitle": "Biology 101",
        "objectives": ["Explain the light reactions"],
        "sections": [{"title": "Light reactions", "bullets": ["Water is split", "ATP is made"],
                      "table": {"headers": ["Stage", "Place"], "rows": [["Light", "Thylakoid"]]}}],
        "keywords": [{"term": "Chlorophyll", "definition": "Green pigment"}],
        "flashcards": [{"q": "Where?", "a": "Chloroplast"}] if flashcards else [],
        "mcqs": [{"q": "Gas made?", "options": ["A) O2", "B) N2"], "answer": "A", "explanation": "O2"}],
        "language": lang,
    }


def _store(guide=None, filename="lecture_study_guide.pdf", md="# T\n\n- a\n", pdf=b"%PDF-1.4 test"):
    jid = appmod.uuid.uuid4().hex
    appmod.store_job(jid, pdf, md, guide if guide is not None else _guide(), None, filename)
    return jid


def _tok(sub="user-1", exp_in=3600, iat_in=0, secret=SECRET, **extra):
    now = int(time.time())
    claims = {"sub": sub, "aud": "authenticated", "exp": now + exp_in, "iat": now + iat_in, **extra}
    return pyjwt.encode(claims, secret, algorithm="HS256")


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(appmod, "_AUTH_ENABLED", True)
    monkeypatch.setattr(appmod, "SUPABASE_JWT_SECRET", SECRET)


@pytest.fixture
def no_charge(monkeypatch):
    """Fail loudly if anything tries to spend a credit."""
    calls = []
    def _boom(*a, **k):
        calls.append(a)
        raise AssertionError("a credit was consumed")
    monkeypatch.setattr(appmod, "_consume_token", _boom)
    monkeypatch.setattr(appmod, "_anon_durable_consume", _boom)
    monkeypatch.setattr(appmod, "_anon_consume", _boom)
    return calls


# ── 1. guide_blob / sig / rehydrate ─────────────────────────────────────────────
def test_guide_returns_canonical_signed_blob(client, monkeypatch):
    monkeypatch.setattr(appmod, "_GUIDE_KEY", KEY)
    jid = _store()
    r = client.get(f"/api/guide/{jid}")
    assert r.status_code == 200
    d = r.get_json()
    # Existing fields are kept.
    for k in ("title", "subtitle", "sections", "flashcards", "mcqs", "keywords", "objectives", "language"):
        assert k in d
    assert d["filename"] == "lecture_study_guide.pdf"
    assert 0 < d["expires_in"] <= appmod._JOB_TTL
    blob = d["guide_blob"]
    assert isinstance(blob, str)
    obj = json.loads(blob)
    assert obj["v"] == 1 and obj["filename"] == "lecture_study_guide.pdf"
    assert set(obj["guide"]) == set(appmod._GUIDE_KEYS)
    # Canonical form: sorted keys, compact separators, UTF-8 (not \\u escapes).
    assert blob == json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert d["sig"] == hmac.new(KEY, blob.encode("utf-8"), hashlib.sha256).hexdigest()


def test_guide_blob_keeps_arabic_unescaped(client, monkeypatch):
    monkeypatch.setattr(appmod, "_GUIDE_KEY", KEY)
    jid = _store(_guide("ar"))
    blob = client.get(f"/api/guide/{jid}").get_json()["guide_blob"]
    assert "البناء الضوئي" in blob


def test_rehydrate_round_trip_rebuilds_pdf_for_free(client, monkeypatch, no_charge):
    monkeypatch.setattr(appmod, "_GUIDE_KEY", KEY)
    old = _store()
    g = client.get(f"/api/guide/{old}").get_json()

    r = client.post("/api/rehydrate", json={"guide_blob": g["guide_blob"], "sig": g["sig"]})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert appmod._valid_job(d["job_id"]) and d["job_id"] != old
    assert d["expires_in"] == appmod._JOB_TTL
    assert d["filename"] == "lecture_study_guide.pdf"
    assert not no_charge                      # rehydrate never consumes a credit

    # The rebuilt job is a real, downloadable PDF with the same guide content.
    dl = client.get(f"/api/download/{d['job_id']}")
    assert dl.status_code == 200
    assert dl.mimetype == "application/pdf"
    assert dl.data.startswith(b"%PDF")
    g2 = client.get(f"/api/guide/{d['job_id']}").get_json()
    assert g2["title"] == "Photosynthesis"
    assert g2["sections"][0]["bullets"] == ["Water is split", "ATP is made"]
    assert g2["guide_blob"] == g["guide_blob"]          # stable across restore
    assert appmod.get_job(d["job_id"])["slides"] is None


def test_rehydrate_rejects_tampered_blob(client, monkeypatch):
    monkeypatch.setattr(appmod, "_GUIDE_KEY", KEY)
    g = client.get(f"/api/guide/{_store()}").get_json()
    tampered = g["guide_blob"].replace("Photosynthesis", "Free Pro Account")
    assert tampered != g["guide_blob"]
    r = client.post("/api/rehydrate", json={"guide_blob": tampered, "sig": g["sig"]})
    assert r.status_code == 403
    assert r.get_json()["code"] == "bad_signature"

    # A forged signature over the tampered blob with the WRONG key also fails.
    forged = hmac.new(b"attacker-key", tampered.encode(), hashlib.sha256).hexdigest()
    r = client.post("/api/rehydrate", json={"guide_blob": tampered, "sig": forged})
    assert r.status_code == 403

    # A non-ASCII sig must be rejected cleanly (not a 500 from compare_digest).
    r = client.post("/api/rehydrate", json={"guide_blob": g["guide_blob"], "sig": "ابجد"})
    assert r.status_code == 403


@pytest.mark.parametrize("body", [None, {}, {"guide_blob": "x"}, {"sig": "y"},
                                  {"guide_blob": 1, "sig": "y"}, ["guide_blob", "sig"]])
def test_rehydrate_bad_request(client, monkeypatch, body):
    monkeypatch.setattr(appmod, "_GUIDE_KEY", KEY)
    r = client.post("/api/rehydrate", json=body) if body is not None else \
        client.post("/api/rehydrate", data="not json", content_type="text/plain")
    assert r.status_code == 400
    assert r.get_json()["code"] == "bad_request"


def test_rehydrate_signed_but_wrong_shape_is_bad_request(client, monkeypatch):
    monkeypatch.setattr(appmod, "_GUIDE_KEY", KEY)
    blob = json.dumps({"v": 2, "guide": {}})
    sig = hmac.new(KEY, blob.encode(), hashlib.sha256).hexdigest()
    r = client.post("/api/rehydrate", json={"guide_blob": blob, "sig": sig})
    assert r.status_code == 400 and r.get_json()["code"] == "bad_request"


def test_rehydrate_too_large(client, monkeypatch):
    monkeypatch.setattr(appmod, "_GUIDE_KEY", KEY)
    blob = "x" * (appmod._GUIDE_BLOB_MAX + 1)
    r = client.post("/api/rehydrate", json={"guide_blob": blob, "sig": "00"})
    assert r.status_code == 413
    assert r.get_json()["code"] == "too_large"


def test_rehydrate_unavailable_without_key(client, monkeypatch):
    monkeypatch.setattr(appmod, "_GUIDE_KEY", b"")
    jid = _store()
    g = client.get(f"/api/guide/{jid}").get_json()
    assert "guide_blob" in g and "sig" not in g          # no key → no sig issued
    r = client.post("/api/rehydrate", json={"guide_blob": g["guide_blob"], "sig": "ab"})
    assert r.status_code == 503
    assert r.get_json()["code"] == "unavailable"


def test_rehydrate_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(appmod, "_GUIDE_KEY", KEY)
    monkeypatch.setattr(appmod, "_client_ip", lambda: "203.0.113.77")
    monkeypatch.setattr(appmod, "_rate_limit", {})
    codes = [client.post("/api/rehydrate", json={}).status_code for _ in range(21)]
    assert codes[:20] == [400] * 20
    assert codes[20] == 429
    assert client.post("/api/rehydrate", json={}).get_json()["code"] == "rate_limited"


def test_signing_key_derivation(monkeypatch):
    monkeypatch.delenv("GUIDE_SIGNING_KEY", raising=False)
    monkeypatch.setattr(appmod, "SUPABASE_SERVICE_ROLE_KEY", "svc-role")
    assert appmod._guide_signing_key() == hashlib.sha256(b"alimne-guide-v1|svc-role").digest()
    monkeypatch.setattr(appmod, "SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setattr(appmod, "SUPABASE_JWT_SECRET", "jwt-secret")
    assert appmod._guide_signing_key() == hashlib.sha256(b"alimne-guide-v1|jwt-secret").digest()
    monkeypatch.setattr(appmod, "SUPABASE_JWT_SECRET", "")
    assert appmod._guide_signing_key() == b""
    monkeypatch.setenv("GUIDE_SIGNING_KEY", "explicit")
    assert appmod._guide_signing_key() == b"explicit"


# ── 2. _auth_optional tri-state + 401 before any credit ────────────────────────
def test_auth_optional_tri_state(auth_on):
    with appmod.app.test_request_context("/"):
        assert appmod._auth_optional(appmod.request) is None              # no token → anon
    with appmod.app.test_request_context("/", headers={"Authorization": f"Bearer {_tok()}"}):
        assert appmod._auth_optional(appmod.request) == "user-1"
    with appmod.app.test_request_context("/", headers={"Authorization": f"Bearer {_tok(exp_in=-120)}"}):
        assert appmod._auth_optional(appmod.request) is False
        body, status = appmod._auth_rejected()
        assert status == 401 and body.get_json()["code"] == "token_expired"
    with appmod.app.test_request_context("/", headers={"Authorization": "Bearer not.a.jwt"}):
        assert appmod._auth_optional(appmod.request) is False
        body, status = appmod._auth_rejected()
        assert status == 401 and body.get_json()["code"] == "token_invalid"


def test_auth_optional_dev_mode_when_auth_disabled():
    with appmod.app.test_request_context("/", headers={"Authorization": "Bearer junk"}):
        assert appmod._auth_optional(appmod.request) == "dev"


def test_text_endpoint_401_before_spending_credit(client, auth_on, no_charge):
    r = client.post("/api/summarize-text", json={"text": "hello world"},
                    headers={"Authorization": f"Bearer {_tok(exp_in=-120)}", "X-Device-Id": "device-abc-123"})
    assert r.status_code == 401
    assert r.get_json()["code"] == "token_expired"
    assert not no_charge


def test_file_endpoint_401_before_parsing_upload_or_spending(client, auth_on, no_charge):
    data = {"file": (io.BytesIO(b"hello"), "notes.txt")}
    r = client.post("/api/summarize-stream", data=data, content_type="multipart/form-data",
                    headers={"Authorization": "Bearer forged.token.value"})
    assert r.status_code == 401
    assert r.get_json()["code"] == "token_invalid"
    assert not no_charge


def test_youtube_endpoint_401_before_spending_credit(client, auth_on, no_charge, monkeypatch):
    monkeypatch.setattr(appmod, "_yt_duration", lambda vid: (_ for _ in ()).throw(AssertionError("reached yt-dlp")))
    r = client.post("/api/youtube", json={"url": "https://youtu.be/dQw4w9WgXcQ"},
                    headers={"Authorization": f"Bearer {_tok(exp_in=-120)}"})
    assert r.status_code == 401 and r.get_json()["code"] == "token_expired"
    assert not no_charge


def test_demo_stays_free_and_anonymous_even_with_bad_token(client, auth_on, no_charge, monkeypatch):
    monkeypatch.setattr(appmod, "ollama_running", lambda: False)   # stop before any LLM work
    r = client.post("/api/summarize-text", json={"demo": True},
                    headers={"Authorization": f"Bearer {_tok(exp_in=-120)}"})
    assert r.status_code == 503          # reached the demo path, no 401
    assert not no_charge


def test_share_with_rejected_token_still_shares_anonymously(client, auth_on, monkeypatch):
    sb = MagicMock()
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)
    jid = _store()
    r = client.post(f"/api/share/{jid}", headers={"Authorization": "Bearer junk"})
    assert r.status_code == 200
    inserted = sb.table.return_value.insert.call_args[0][0]
    assert inserted["created_by"] is None


# ── 3. distinct auth codes, leeway, JWKS fallback ──────────────────────────────
def test_auth_check_distinct_codes(client, auth_on):
    r = client.get("/api/referral/stats")
    assert r.status_code == 401 and r.get_json()["code"] == "auth_required"
    r = client.get("/api/referral/stats", headers={"Authorization": f"Bearer {_tok(exp_in=-120)}"})
    assert r.status_code == 401 and r.get_json()["code"] == "token_expired"
    r = client.get("/api/referral/stats", headers={"Authorization": f"Bearer {_tok(secret='x' * 40)}"})
    assert r.status_code == 401 and r.get_json()["code"] == "token_invalid"


def test_jwt_leeway_tolerates_small_clock_skew(auth_on):
    # iat a few seconds in the future (Render clock behind Supabase) → accepted.
    assert appmod._verify_jwt(_tok(iat_in=5)) == "user-1"
    # Just past exp, within leeway → accepted; well past → expired.
    assert appmod._verify_jwt(_tok(exp_in=-3)) == "user-1"
    assert appmod._jwt_verify(_tok(exp_in=-60)) == (None, "expired")


def test_hs256_without_secret_is_rejected(monkeypatch):
    monkeypatch.setattr(appmod, "SUPABASE_JWT_SECRET", "")
    assert appmod._jwt_verify(_tok()) == (None, "invalid")


def _es256_token(kid="kid-1"):
    from cryptography.hazmat.primitives.asymmetric import ec
    priv = ec.generate_private_key(ec.SECP256R1())
    tok = pyjwt.encode({"sub": "es-user", "aud": "authenticated", "exp": int(time.time()) + 3600},
                       priv, algorithm="ES256", headers={"kid": kid})
    return tok, priv.public_key()


class _FakeJwks:
    def __init__(self, key, down=False):
        self.key, self.down = key, down

    def get_signing_key_from_jwt(self, token):
        if self.down:
            raise pyjwt.PyJWKClientConnectionError("JWKS unreachable")
        return SimpleNamespace(key=self.key)


def test_jwks_last_good_key_survives_outage(monkeypatch):
    tok, pub = _es256_token()
    monkeypatch.setattr(appmod, "_jwks_last_good", {})
    monkeypatch.setattr(appmod, "_get_jwks_client", lambda: _FakeJwks(pub))
    payload, reason = appmod._jwt_verify(tok)
    assert payload["sub"] == "es-user" and reason == ""
    assert appmod._jwks_last_good["kid-1"] is pub

    # JWKS goes down → the last-good key for that kid keeps sessions valid.
    monkeypatch.setattr(appmod, "_get_jwks_client", lambda: _FakeJwks(pub, down=True))
    assert appmod._verify_jwt(tok) == "es-user"

    # Down AND no cached key → 'unavailable' (retryable), not a sign-out.
    monkeypatch.setattr(appmod, "_jwks_last_good", {})
    assert appmod._jwt_verify(tok) == (None, "unavailable")


def test_auth_me_503_auth_unavailable_on_jwks_outage(client, monkeypatch):
    tok, pub = _es256_token()
    monkeypatch.setattr(appmod, "_AUTH_ENABLED", True)
    monkeypatch.setattr(appmod, "_jwks_last_good", {})
    monkeypatch.setattr(appmod, "_get_jwks_client", lambda: _FakeJwks(pub, down=True))
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 503
    assert r.get_json()["code"] == "auth_unavailable"


# ── 4. /api/auth/me ────────────────────────────────────────────────────────────
def test_effective_plan_tokens_mirror_consume_token():
    from datetime import datetime, timezone
    now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    cur, old = "2026-10", "2026-09"
    eff = appmod._effective_plan_tokens
    # Same month: balance as stored.
    assert eff({"subscription_status": "free", "tokens_remaining": 2, "tokens_month": cur}, now) == ("free", 2)
    # New month: free resets to 3, an active Pro to 30.
    assert eff({"subscription_status": "free", "tokens_remaining": 0, "tokens_month": old}, now) == ("free", 3)
    assert eff({"subscription_status": "active", "tokens_remaining": 0, "tokens_month": old,
                "subscription_period_end": "2026-10-20T00:00:00+00:00"}, now) == ("pro", 30)
    # Lapsed paid period (missed webhook) → free plan, 3 on rollover.
    assert eff({"subscription_status": "active", "tokens_remaining": 0, "tokens_month": old,
                "subscription_period_end": "2026-09-20T00:00:00.12345+00:00"}, now) == ("free", 3)
    # Active with no period end → Pro; NULL month counts as a new month.
    assert eff({"subscription_status": "active", "tokens_remaining": 7, "tokens_month": None}, now) == ("pro", 30)


def test_auth_me_returns_effective_tokens_and_plan(client, auth_on, monkeypatch):
    row = {"id": "user-1", "email": "s@x.com", "name": "S", "avatar_url": "a",
           "tokens_remaining": 0, "tokens_month": "1999-01", "subscription_status": "active",
           "subscription_period_end": None, "stripe_customer_id": "cus_1", "referral_code": "ABC"}
    monkeypatch.setattr(appmod, "_get_user", lambda uid: dict(row))
    monkeypatch.setattr(appmod, "_get_sb", lambda: MagicMock())
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {_tok()}"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["tokens_remaining"] == 30 and d["plan"] == "pro"
    # Unchanged fields the Account panel depends on.
    assert d["subscription_status"] == "active" and d["has_billing"] is True
    assert d["referral_code"] == "ABC" and d["email"] == "s@x.com"


def test_auth_me_503_retry_on_db_error(client, auth_on, monkeypatch):
    def _down(uid):
        raise RuntimeError("postgrest timeout")
    monkeypatch.setattr(appmod, "_get_user", _down)
    monkeypatch.setattr(appmod, "_get_sb", lambda: MagicMock())
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {_tok()}"})
    assert r.status_code == 503
    assert r.get_json()["code"] == "retry"


def test_auth_me_creates_missing_row_without_overwriting(client, auth_on, monkeypatch):
    sb = MagicMock()
    rows = iter([None, {"id": "user-1", "email": "new@x.com", "tokens_remaining": 3,
                        "tokens_month": time.strftime("%Y-%m", time.gmtime()), "referral_code": "R1"}])
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)
    monkeypatch.setattr(appmod, "_get_user", lambda uid: next(rows))
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {_tok(email='new@x.com')}"})
    assert r.status_code == 200 and r.get_json()["plan"] == "free"
    _, kwargs = sb.table.return_value.upsert.call_args
    assert kwargs.get("ignore_duplicates") is True          # ON CONFLICT DO NOTHING


def test_auth_me_never_returns_fieldless_row(client, auth_on, monkeypatch):
    monkeypatch.setattr(appmod, "_get_sb", lambda: MagicMock())
    monkeypatch.setattr(appmod, "_get_user", lambda uid: None)   # row still missing after upsert
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {_tok()}"})
    assert r.status_code == 503 and r.get_json()["code"] == "retry"


def test_checkout_503_on_account_lookup_error(client, monkeypatch):
    monkeypatch.setattr(appmod, "_stripe", MagicMock())
    monkeypatch.setattr(appmod, "STRIPE_PRICE_ID", "price_test")
    monkeypatch.setattr(appmod, "_get_user", lambda uid: (_ for _ in ()).throw(RuntimeError("db")))
    r = client.post("/api/stripe/checkout")
    assert r.status_code == 503 and r.get_json()["code"] == "retry"


@pytest.mark.parametrize("results,status,code", [
    ([(False, 0, "db_error")], 503, "retry"),
    ([(False, 0, "no_tokens")], 402, "no_tokens"),
    ([(False, 0, "user_not_found"), (True, 2, "")], None, None),
    ([(False, 0, "user_not_found"), (False, 0, "user_not_found")], 503, "retry"),
])
def test_charge_credit_reasons(monkeypatch, results, status, code):
    seq = iter(results)
    monkeypatch.setattr(appmod, "_consume_token", lambda uid: next(seq))
    ensured = []
    monkeypatch.setattr(appmod, "_ensure_user_row", lambda uid, payload=None: ensured.append(uid) or True)
    with appmod.app.test_request_context("/"):
        charge, err = appmod._charge_credit("user-1", appmod.request)
        if status is None:
            assert err is None and charge.tok_left == 2 and ensured == ["user-1"]
        else:
            assert charge is None and err[1] == status and err[0].get_json()["code"] == code


def test_consume_token_malformed_reply_is_db_error(monkeypatch):
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value = SimpleNamespace(data=[{"oops": 1}])
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)
    assert appmod._consume_token("u") == (False, 0, "db_error")


# ── 5. job endpoints + print view ──────────────────────────────────────────────
def test_download_expired_returns_404_code_expired(client):
    r = client.get(f"/api/download/{'0' * 32}")
    assert r.status_code == 404
    assert r.get_json()["code"] == "expired"


def test_all_job_endpoints_use_code_expired(client):
    gone = "f" * 32
    assert client.get(f"/api/guide/{gone}").get_json()["code"] == "expired"
    assert client.get(f"/api/export/anki/{gone}").get_json()["code"] == "expired"
    assert client.post(f"/api/share/{gone}").get_json()["code"] == "expired"
    r = client.post(f"/api/chat/{gone}", json={"question": "why?"})
    assert r.status_code == 404 and r.get_json()["code"] == "expired"


def test_expired_after_ttl(client):
    jid = _store()
    appmod._jobs[jid]["ts"] -= appmod._JOB_TTL + 1
    assert client.get(f"/api/download/{jid}").get_json()["code"] == "expired"


def test_anki_without_cards_is_no_flashcards(client):
    jid = _store(_guide(flashcards=False))
    r = client.get(f"/api/export/anki/{jid}")
    assert r.status_code == 404 and r.get_json()["code"] == "no_flashcards"


def test_view_md_wraps_table_and_uses_th_only_for_header(client):
    md = "# Title\n\n## Sec\n- point\n\n| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\ntext\n"
    jid = _store(md=md)
    r = client.get(f"/api/view/md/{jid}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert ("<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr>"
            "<tr><td>3</td><td>4</td></tr></table>") in html
    assert html.count("<th>") == 2
    assert '<html lang="en" dir="ltr">' in html
    assert 'name="viewport"' in html


def test_view_md_arabic_is_rtl(client):
    jid = _store(_guide("ar"), md="# عنوان\n\n## قسم\n- نقطة\n")
    html = client.get(f"/api/view/md/{jid}").get_data(as_text=True)
    assert '<html lang="ar" dir="rtl">' in html
    assert "[dir=rtl] h2" in html


def test_view_md_expired_page_is_bilingual_with_link_home(client):
    r = client.get(f"/api/view/md/{'a' * 32}")
    assert r.status_code == 404
    html = r.get_data(as_text=True)
    assert "15 minutes" in html and "10 min" not in html
    assert "انتهت صلاحية" in html
    assert 'href="https://alimne.app/"' in html
    assert 'name="viewport"' in html


def test_store_job_drops_slides_and_sweeper_purges(client):
    jid = appmod.uuid.uuid4().hex
    appmod.store_job(jid, b"%PDF", "# x", _guide(), [{"slide_num": 1, "content": "raw"}], "f.pdf")
    assert appmod._jobs[jid]["slides"] is None
    appmod._jobs[jid]["ts"] -= appmod._JOB_TTL + 5
    appmod._purge_expired_jobs()
    assert jid not in appmod._jobs


def test_download_zip_route_removed():
    rules = {r.rule for r in appmod.app.url_map.iter_rules()}
    assert "/api/download-zip" not in rules
    assert "/api/rehydrate" in rules


# ── 6. refund guard, hollow guides, partial ────────────────────────────────────
class _Counter:
    def __init__(self):
        self.calls = []

    def __call__(self, uid, ip, dev=None):
        self.calls.append((uid, ip, dev))


def _fake_llm(monkeypatch, bullets=True, mcqs=True, pass1_raises=False):
    def p1(slides, language, dcfg=None):
        if pass1_raises:
            raise RuntimeError("groq down")
        return {"title": "T", "subtitle": "", "objectives": ["o"],
                "sections": [{"title": "S1", "slide_nums": [1]}], "keywords": [{"term": "k", "definition": "d"}]}
    def p2(title, sl, language, dcfg=None):
        if not bullets:
            raise RuntimeError("pass2 failed")
        return {"bullets": ["b1", "b2"]}
    monkeypatch.setattr(appmod, "pass1_overview", p1)
    monkeypatch.setattr(appmod, "pass2_section", p2)
    monkeypatch.setattr(appmod, "pass3_flashcards", lambda g, l, d=None: {"flashcards": [{"q": "q", "a": "a"}]})
    monkeypatch.setattr(appmod, "pass4_mcq", lambda g, l, d=None: {"mcqs": [{"q": "q", "options": ["A) x"], "answer": "A"}] if mcqs else []})


def _events(gen):
    out = []
    for chunk in gen:
        out.append(json.loads(chunk[len("data: "):].strip()))
    return out


def test_charge_refund_is_idempotent(monkeypatch):
    c = _Counter()
    monkeypatch.setattr(appmod, "_refund_credit", c)
    ch = appmod._Charge(uid="u")
    assert ch.refund() is True and ch.refund() is False
    assert c.calls == [("u", None, None)]
    settled = appmod._Charge(uid="u")
    settled.settle()
    assert settled.refund() is False and len(c.calls) == 1


def test_disconnect_mid_stream_refunds_exactly_once(monkeypatch):
    c = _Counter()
    monkeypatch.setattr(appmod, "_refund_credit", c)
    _fake_llm(monkeypatch)
    ch = appmod._Charge(ip="198.51.100.9", dev="device-abc-123")
    gen = appmod._stream_text_as_sse("some lecture text " * 20, "en", "x", "text", charge=ch)()
    next(gen)          # first SSE event delivered…
    gen.close()        # …then the client goes away (GeneratorExit)
    assert c.calls == [(None, "198.51.100.9", "device-abc-123")]   # durable device refunded
    gen.close()
    assert len(c.calls) == 1


def test_success_settles_and_never_refunds(monkeypatch):
    c = _Counter()
    monkeypatch.setattr(appmod, "_refund_credit", c)
    _fake_llm(monkeypatch)
    ch = appmod._Charge(uid="u", tok_left=4)
    gen = appmod._stream_text_as_sse("some lecture text " * 20, "en", "x", "text", tok_left=4, charge=ch)()
    evs = _events(gen)
    done = evs[-1]
    assert done["step"] == "done" and done["tokens_remaining"] == 4
    assert "partial" not in done
    gen.close()
    assert c.calls == []
    assert appmod.get_job(done["job_id"])["slides"] is None


def test_exception_refunds_once_and_reports_friendly_error(monkeypatch):
    c = _Counter()
    monkeypatch.setattr(appmod, "_refund_credit", c)
    _fake_llm(monkeypatch, pass1_raises=True)
    ch = appmod._Charge(uid="u")
    gen = appmod._stream_text_as_sse("some lecture text " * 20, "en", "x", "text", charge=ch)()
    evs = _events(gen)
    gen.close()
    assert evs[-1]["error"] == "Processing failed — please try again."   # no raw internals
    assert c.calls == [("u", None, None)]


def test_hollow_guide_is_refunded_error_not_ready(monkeypatch):
    c = _Counter()
    monkeypatch.setattr(appmod, "_refund_credit", c)
    _fake_llm(monkeypatch, bullets=False)
    ch = appmod._Charge(uid="u")
    evs = _events(appmod._stream_text_as_sse("some lecture text " * 20, "en", "x", "text", charge=ch)())
    assert "error" in evs[-1] and "credit was returned" in evs[-1]["error"]
    assert not any(e.get("step") == "done" for e in evs)
    assert c.calls == [("u", None, None)]


def test_partial_flag_when_quiz_missing(monkeypatch):
    monkeypatch.setattr(appmod, "_refund_credit", _Counter())
    _fake_llm(monkeypatch, mcqs=False)
    evs = _events(appmod._stream_text_as_sse("some lecture text " * 20, "en", "x", "text",
                                             charge=appmod._Charge(uid="u"))())
    done = evs[-1]
    assert done["step"] == "done" and done["partial"] is True and done["mcqs"] == 0
    # Summary-only mode asked for no quiz → not partial.
    evs = _events(appmod._stream_text_as_sse("some lecture text " * 20, "en", "x", "text",
                                             include_quiz=False, charge=appmod._Charge(uid="u"))())
    assert "partial" not in evs[-1]


def test_refund_credit_routes_to_the_charged_store(monkeypatch):
    sb = MagicMock()
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)
    ip_refunds = []
    monkeypatch.setattr(appmod, "_anon_refund", ip_refunds.append)
    appmod._refund_credit(None, "1.2.3.4", "device-abc-123")
    sb.rpc.assert_called_once_with("anon_refund", {"p_key": "dev:device-abc-123"})
    assert ip_refunds == []                      # the per-IP list was never charged
    appmod._refund_credit(None, "1.2.3.4")
    assert ip_refunds == ["1.2.3.4"]
    # Missing RPC (migration 012 not applied) → logged, never raised.
    sb.rpc.side_effect = RuntimeError("function anon_refund does not exist")
    appmod._refund_credit(None, "1.2.3.4", "device-abc-123")


def _sse_events(resp):
    return [json.loads(line[len("data: "):]) for line in resp.get_data(as_text=True).splitlines()
            if line.startswith("data: ")]


@pytest.mark.parametrize("fail_in", ["text_pipeline", "captions", None])
def test_youtube_route_refunds_at_most_once(client, auth_on, monkeypatch, fail_in):
    # auth on + no token → a genuinely anonymous caller (durable device quota).
    c = _Counter()
    monkeypatch.setattr(appmod, "_refund_credit", c)
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "_yt_duration", lambda vid: 60)
    monkeypatch.setattr(appmod, "_log_usage_async", lambda *a, **k: None)
    monkeypatch.setattr(appmod, "_anon_durable_consume", lambda dev: (True, 1))
    if fail_in == "captions":
        monkeypatch.setattr(appmod, "_fetch_captions", lambda vid: (_ for _ in ()).throw(RuntimeError("HTTPError for https://internal")))
    else:
        monkeypatch.setattr(appmod, "_fetch_captions", lambda vid: "lecture words " * 50)
    _fake_llm(monkeypatch, pass1_raises=(fail_in == "text_pipeline"))
    r = client.post("/api/youtube", json={"url": "https://youtu.be/dQw4w9WgXcQ", "language": "en"},
                    headers={"X-Device-Id": "device-abc-123"})
    evs = _sse_events(r)
    if fail_in is None:
        assert evs[-1]["step"] == "done" and c.calls == []
    else:
        assert "error" in evs[-1] and "internal" not in evs[-1]["error"]
        assert c.calls == [(None, "127.0.0.1", "device-abc-123")]   # exactly once, durable store


def test_yt_download_error_is_friendly():
    yt = pytest.importorskip("yt_dlp")
    msg = appmod._yt_friendly_err(yt.utils.DownloadError("ERROR: [youtube] x: Sign in to confirm you're not a bot"))
    assert "YouTube blocked this video" in msg and "Sign in to confirm" not in msg


# ── 7. misc ────────────────────────────────────────────────────────────────────
def test_413_is_json(client, monkeypatch):
    monkeypatch.setitem(appmod.app.config, "MAX_CONTENT_LENGTH", 64)
    data = {"file": (io.BytesIO(b"x" * 500), "big.txt")}
    r = client.post("/api/summarize-stream", data=data, content_type="multipart/form-data")
    assert r.status_code == 413
    assert r.get_json()["code"] == "too_large"


def test_onrender_host_redirects_page_loads_only(client):
    r = client.get("/s/abc123?x=1", base_url="https://slide-study-ai.onrender.com")
    assert r.status_code == 301
    assert r.headers["Location"] == "https://alimne.app/s/abc123?x=1"
    assert client.get("/healthz", base_url="https://slide-study-ai.onrender.com").status_code == 200
    assert client.get("/api/config", base_url="https://slide-study-ai.onrender.com").status_code == 200
    assert client.post("/privacy", base_url="https://slide-study-ai.onrender.com").status_code != 301
    assert client.get("/privacy").status_code == 200      # canonical host untouched


def test_config_never_waits_on_a_slow_db(client, monkeypatch):
    monkeypatch.setattr(appmod, "_get_sb", lambda: MagicMock())
    monkeypatch.setattr(appmod, "_anon_durable_remaining", lambda dev: time.sleep(2.5) or 0)
    t0 = time.time()
    r = client.get("/api/config", headers={"X-Device-Id": "device-abc-123"})
    elapsed = time.time() - t0
    assert r.status_code == 200
    assert elapsed < 2.2
    assert isinstance(r.get_json()["anon_remaining"], int)


def test_config_uses_durable_count_when_fast(client, monkeypatch):
    monkeypatch.setattr(appmod, "_get_sb", lambda: MagicMock())
    monkeypatch.setattr(appmod, "_anon_durable_remaining", lambda dev: 1)
    r = client.get("/api/config", headers={"X-Device-Id": "device-abc-123"})
    assert r.get_json()["anon_remaining"] == 1


# ── 8. review follow-ups ───────────────────────────────────────────────────────
@pytest.mark.parametrize("body,status,code", [
    (b'{"guide_blob":"\\ud800abc","sig":"00"}', 400, "bad_request"),
    (b'{"guide_blob":"abc","sig":"\\ud800"}', 403, "bad_signature"),
])
def test_rehydrate_lone_surrogate_is_json_not_500(client, monkeypatch, body, status, code):
    monkeypatch.setattr(appmod, "_GUIDE_KEY", KEY)
    r = client.post("/api/rehydrate", data=body, content_type="application/json")
    assert r.status_code == status and r.get_json()["code"] == code


def test_rehydrate_busy_is_503_retry_and_slots_are_released(client, monkeypatch):
    monkeypatch.setattr(appmod, "_GUIDE_KEY", KEY)
    g = client.get(f"/api/guide/{_store()}").get_json()
    body = {"guide_blob": g["guide_blob"], "sig": g["sig"]}
    # A normal restore gives its build slot back.
    assert client.post("/api/rehydrate", json=body).status_code == 200
    assert appmod._rehydrate_sem._value == appmod._REHYDRATE_SLOTS

    class _Busy:
        def acquire(self, timeout=None):
            return False
        def release(self):
            raise AssertionError("released a slot it never took")
    monkeypatch.setattr(appmod, "_rehydrate_sem", _Busy())
    r = client.post("/api/rehydrate", json=body)
    assert r.status_code == 503 and r.get_json()["code"] == "retry"


def test_job_cap_evicts_restored_jobs_first(monkeypatch):
    monkeypatch.setattr(appmod, "_jobs", {})
    monkeypatch.setattr(appmod, "_JOBS_MAX_BYTES", 100)
    ids = [appmod.uuid.uuid4().hex for _ in range(3)]
    appmod.store_job(ids[0], b"x" * 40, "", {}, None, "paid.pdf")
    appmod.store_job(ids[1], b"x" * 40, "", {}, None, "old_restore.pdf", rehydrated=True)
    appmod.store_job(ids[2], b"x" * 40, "", {}, None, "new_restore.pdf", rehydrated=True)
    assert ids[1] not in appmod._jobs                     # oldest restored copy went first
    assert ids[0] in appmod._jobs and ids[2] in appmod._jobs


def test_hollow_guide_never_claims_a_refund_that_failed(monkeypatch):
    # e.g. an anonymous visitor before migration 012 (anon_refund RPC missing)
    monkeypatch.setattr(appmod, "_refund_credit", lambda uid, ip, dev=None: False)
    _fake_llm(monkeypatch, bullets=False)
    ch = appmod._Charge(ip="198.51.100.9", dev="device-abc-123")
    last = _events(appmod._stream_text_as_sse("some lecture text " * 20, "en", "x", "text", charge=ch)())[-1]
    assert last["code"] == "no_notes" and last["refunded"] is False
    assert "credit was returned" not in last["error"]


def test_refund_credit_reports_whether_it_worked(monkeypatch):
    sb = MagicMock()
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)
    assert appmod._refund_credit(None, "1.2.3.4", "device-abc-123") is True
    sb.rpc.side_effect = RuntimeError("function anon_refund does not exist")
    assert appmod._refund_credit(None, "1.2.3.4", "device-abc-123") is False


def test_yt_blocked_event_carries_a_code():
    yt = pytest.importorskip("yt_dlp")
    ev = appmod._yt_error_event(yt.utils.DownloadError("ERROR: [youtube] x: Sign in to confirm"))
    assert ev["code"] == "yt_blocked" and "Sign in to confirm" not in ev["error"]
    assert "code" not in appmod._yt_error_event(RuntimeError("boom"))


def test_checkout_sends_a_live_subscriber_to_the_portal(client, monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(appmod, "_stripe", fake)
    monkeypatch.setattr(appmod, "STRIPE_PRICE_ID", "price_test")
    # A stale period_end makes /api/auth/me say 'free' — Stripe still bills them.
    monkeypatch.setattr(appmod, "_get_user", lambda uid: {"email": "s@x.com", "stripe_customer_id": "cus_1",
                                                          "subscription_status": "active"})
    fake.Customer.retrieve.return_value = SimpleNamespace(deleted=False)
    fake.Subscription.list.return_value = SimpleNamespace(data=[SimpleNamespace(status="active")])
    fake.billing_portal.Session.create.return_value = SimpleNamespace(url="https://billing.stripe.com/p/x")
    r = client.post("/api/stripe/checkout")
    assert r.status_code == 200 and r.get_json()["url"] == "https://billing.stripe.com/p/x"
    fake.checkout.Session.create.assert_not_called()      # no second subscription


def test_supabase_init_falls_back_when_options_are_rejected(monkeypatch):
    seen = []
    def fake_create(url, key, options=None):
        seen.append(options)
        if options is not None:
            raise TypeError("unexpected options")
        return "client"
    monkeypatch.setattr(appmod, "_sb_create_client", fake_create)
    monkeypatch.setattr(appmod, "_sb_client", None)
    monkeypatch.setattr(appmod, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(appmod, "SUPABASE_SERVICE_ROLE_KEY", "svc-role")
    assert appmod._get_sb() == "client"                   # never left None (that fails open)
    assert len(seen) == 2 and seen[1] is None
