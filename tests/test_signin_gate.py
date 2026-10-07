"""
The sign-in gate (free mode): an anonymous visitor may make ANON_FREE_USES (3) study
guides without an account. After those they must sign in (create a free account) to make
more. Signing in stays free, signed-in users keep their own daily allowance, the sample
lecture stays free and uncounted, and viewing / downloading / restoring a guide that was
already made never needs an account.

What this file pins, SERVER side:

  1. 3 anonymous guides, then 401 `signin_required` with `free_uses` (every endpoint)
  2. the allowance is a LIFETIME one (the long window), not a daily one
  3. the counters and their order: gate, anonymous-IP, IP, anonymous pool, global
  4. rotating the device id runs into FAIR_ANON_IP_DAILY (10 a day per IP); no device id
     is counted per IP (`gate:noid:`) and cannot dodge the gate
  5. a signed-in request never touches a gate key and is never asked to sign in
  6. refunds: a failed generation gives the use back, a disconnect after the paid AI
     work started does not; a refusal rolls back what was already taken
  7. fail open when the database cannot answer
  8. the demo, and guides already made, are never gated
  9. `anon_remaining` on the SSE `done` event, and the /api/config fields
 10. the refusal text, English and Arabic, with the real number
 11. ALIMNE_FREE_MODE=0 is exactly the old token system
 12. the knobs parse safely
 13. the refusal says WHY (`reason`: device / network / pool), each with its own true
     text: a visitor who made no guides is never told "you've used your 3 free guides"
 14. the client (App_dev.jsx) words the three reasons exactly as the server does

EVERYTHING IS OFFLINE: Supabase is an in-memory fake with a clock, Groq / yt-dlp are faked.
"""
import io
import json
import os
import re
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest

import app as appmod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET = "test-hs256-secret-not-a-real-key-0000"
IP = "203.0.113.5"
DEV = "device-aaaa-0001"
TEXT = "Photosynthesis turns light into chemical energy in the chloroplast. " * 12
LONG = 87600                                   # ANON_USES_WINDOW_HOURS: about 10 years

GATE = f"gate:dev:{DEV}"
NOID = f"gate:noid:{IP}"
ANONIP = f"fair:anonip:{IP}"
FAIRIP = f"fair:ip:{IP}"
POOL = "fair:global:anon"
GLOBAL = "fair:global"
ORDER = [GATE, ANONIP, FAIRIP, POOL, GLOBAL]   # the charge order of an anonymous request

# The three sign-in refusals. Each is true for its own cause, and all end with the same call to action.
CTA = "Create a free account to keep going - it's still free."
EN_TEXT = "You've used your 3 free guides. " + CTA                                        # reason "device"
EN_NETWORK = "Today's free guides without an account are used up on your network. " + CTA  # reason "network"
EN_POOL = "Today's free guides without an account are used up. " + CTA                     # reason "pool"
AR_CTA = "أنشئ حسابًا مجانيًا للمتابعة — ما زال الاستخدام مجانيًا."
PER_IP = 10                                    # FAIR_ANON_IP_DAILY: anonymous guides per IP a day, all devices together


# ── fakes + helpers ──────────────────────────────────────────────────────────────
class ClockSb:
    """anon_consume / anon_remaining / anon_refund exactly as migrations 009 + 012 define
    them, WINDOWS INCLUDED, over a clock the test moves by hand (hours)."""
    def __init__(self):
        self.rows = {}                   # key -> {"count": n, "start": hour the window began}
        self.now_h = 0.0
        self.calls = []                  # (rpc name, params), in order
        self.raises = {}                 # (rpc name, key) -> exception to raise

    def advance(self, hours):
        self.now_h += hours

    def seed(self, key, count):
        self.rows[key] = {"count": count, "start": self.now_h}

    def count(self, key):
        return self.rows.get(key, {}).get("count", 0)

    def spent(self):
        """Every counter that holds at least one unit right now."""
        return {k: r["count"] for k, r in self.rows.items() if r["count"]}

    def keys(self, name):
        return [p.get("p_key") for n, p in self.calls if n == name]

    def params(self, name, key=None):
        return [p for n, p in self.calls if n == name and (key is None or p.get("p_key") == key)]

    def rpc(self, name, params):
        sb, key = self, params.get("p_key")

        class _Call:
            def execute(self_):
                sb.calls.append((name, dict(params)))
                if (name, key) in sb.raises:
                    raise sb.raises[(name, key)]
                if name == "anon_consume":
                    lim, win = params["p_limit"], params["p_window_hours"]
                    row = sb.rows.setdefault(key, {"count": 0, "start": sb.now_h})
                    if row["start"] < sb.now_h - win:
                        row["count"], row["start"] = 0, sb.now_h
                    if row["count"] >= lim:
                        return SimpleNamespace(data={"ok": False, "remaining": 0})
                    row["count"] += 1
                    return SimpleNamespace(data={"ok": True, "remaining": max(0, lim - row["count"])})
                if name == "anon_remaining":
                    lim, win = params["p_limit"], params["p_window_hours"]
                    row = sb.rows.get(key)
                    if row is None or row["start"] < sb.now_h - win:
                        return SimpleNamespace(data=lim)
                    return SimpleNamespace(data=max(0, lim - row["count"]))
                if name == "anon_refund":
                    if key in sb.rows:
                        sb.rows[key]["count"] = max(0, sb.rows[key]["count"] - 1)
                    return SimpleNamespace(data=None)
                raise AssertionError(f"unexpected rpc {name}")
        return _Call()


@pytest.fixture
def sb(monkeypatch):
    fake = ClockSb()
    monkeypatch.setattr(appmod, "_get_sb", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _fixed_ip(monkeypatch):
    monkeypatch.setattr(appmod, "_client_ip", lambda: IP)
    monkeypatch.setattr(appmod, "_rate_limit", {})
    monkeypatch.setattr(appmod, "_log_usage_async", lambda *a, **k: None)


@pytest.fixture
def client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(appmod, "_AUTH_ENABLED", True)
    monkeypatch.setattr(appmod, "SUPABASE_JWT_SECRET", SECRET)


def _tok(sub="user-1"):
    now = int(time.time())
    return pyjwt.encode({"sub": sub, "aud": "authenticated", "exp": now + 3600, "iat": now},
                        SECRET, algorithm="HS256")


def _bearer(sub="user-1"):
    return {"Authorization": f"Bearer {_tok(sub)}"}


def _llm(prompt, retries=3, num_predict=4096):
    if "Create a study guide overview" in prompt:
        return {"title": "Topic", "subtitle": "s", "objectives": ["o"],
                "sections": [{"title": "A", "slide_nums": [1]}],
                "keywords": [{"term": "t", "definition": "d"}]}
    if "Extract detailed exam study notes" in prompt:
        return {"bullets": ["Fact one", "Fact two"]}
    return {"flashcards": [{"q": "Q", "a": "A"}],
            "mcqs": [{"q": "Q", "options": ["A) x", "B) y"], "answer": "A", "explanation": "e"}]}


@pytest.fixture
def llm(monkeypatch):
    """Offline generation: the real (fast) pipeline over a fake Groq; counts the AI calls."""
    calls = []
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "_call_ollama", lambda *a, **k: calls.append(1) or _llm(*a, **k))
    monkeypatch.setattr(appmod, "_ensure_arabic_font", lambda: False)
    monkeypatch.setattr(appmod, "_yt_duration", lambda vid: 60)
    monkeypatch.setattr(appmod, "_fetch_captions", lambda vid: "lecture words " * 50)
    return calls


def _sse_events(resp):
    return [json.loads(line[len("data: "):]) for line in resp.get_data(as_text=True).splitlines()
            if line.startswith("data: ")]


def _done(resp):
    """The `done` event of a generation that must have succeeded."""
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    last = _sse_events(resp)[-1]
    assert last.get("step") == "done", last
    return last


def _read_until(resp, marker):
    for chunk in resp.response:
        raw = chunk if isinstance(chunk, bytes) else chunk.encode()
        if marker in raw:
            return True
    return False


def _has_arabic(s):
    return any("؀" <= ch <= "ۿ" for ch in s or "")


def _hdr(device, headers):
    h = {"X-Device-Id": device} if device else {}
    h.update(headers or {})
    return h


def _post_text(client, device=DEV, headers=None, **body):
    return client.post("/api/summarize-text", json={"text": TEXT, "language": "en", **body},
                       headers=_hdr(device, headers))


def _post_file(client, device=DEV, headers=None, **form):
    data = {"file": (io.BytesIO(TEXT.encode()), "lecture.txt"), "language": "en", **form}
    return client.post("/api/summarize-stream", data=data, content_type="multipart/form-data",
                       headers=_hdr(device, headers))


def _post_youtube(client, device=DEV, headers=None, **body):
    return client.post("/api/youtube", json={"url": "https://youtu.be/dQw4w9WgXcQ", "language": "en", **body},
                       headers=_hdr(device, headers))


def _post_demo(client, device=DEV, **body):
    return client.post("/api/summarize-text", json={"demo": True, "language": "en", **body},
                       headers=_hdr(device, None))


ENDPOINTS = [("text", _post_text), ("file", _post_file), ("youtube", _post_youtube)]
EP_IDS = [e[0] for e in ENDPOINTS]


def _charge(device=DEV, uid=None):
    """One charge through the real counters, without the HTTP route (no rate limiter)."""
    with appmod.app.test_request_context("/", headers=_hdr(device, None)):
        return appmod._charge_credit(uid, appmod.request)


def _refused(resp, free_uses=3, reason="device"):
    """A sign-in refusal: 401, the code, the allowance, WHY (`reason`), a message. Returns the body."""
    assert resp.status_code == 401, resp.get_data(as_text=True)[:300]
    d = resp.get_json()
    assert d["code"] == "signin_required" and d["free_uses"] == free_uses and d["error"]
    assert set(d) == {"error", "code", "free_uses", "reason"}
    assert d["reason"] == reason, d
    return d


# ── 1. three free guides, then sign in ───────────────────────────────────────────
def test_the_defaults_are_the_product_rule():
    assert appmod.ANON_FREE_USES == 3
    assert appmod.ANON_USES_WINDOW_HOURS == LONG
    assert appmod.FAIR_ANON_IP_DAILY == PER_IP == 10
    assert appmod.FAIR_USER_DAILY == 40                       # signed-in users are unchanged


def test_three_anonymous_guides_then_the_fourth_needs_an_account(client, auth_on, sb, llm):
    for _ in range(3):
        _done(_post_text(client))
    n = len(llm)
    d = _refused(_post_text(client))
    assert d["error"] == EN_TEXT
    assert len(llm) == n                                      # the refused request cost no AI call
    assert sb.count(GATE) == 3                                # and took nothing
    assert _refused(_post_text(client))                       # it stays refused


def test_the_three_uses_are_shared_by_every_way_of_making_a_guide(client, auth_on, sb, llm):
    _done(_post_file(client))
    _done(_post_text(client))
    _done(_post_youtube(client))
    assert sb.count(GATE) == 3
    for _name, post in ENDPOINTS:
        _refused(post(client))


@pytest.mark.parametrize("name,post", ENDPOINTS, ids=EP_IDS)
def test_every_generation_endpoint_refuses_past_the_gate(client, auth_on, sb, llm, name, post):
    sb.seed(GATE, 3)
    _refused(post(client))
    assert llm == [] and sb.spent() == {GATE: 3}              # nothing ran, nothing else was charged


def test_the_refusal_is_not_an_auth_error_and_not_a_payment_error(client, auth_on, sb, llm):
    sb.seed(GATE, 3)
    r = _post_text(client)
    assert r.status_code == 401 and r.mimetype == "application/json"
    assert r.get_json()["code"] not in ("auth_required", "token_expired", "token_invalid",
                                        "no_tokens", "signin_for_more", "fair_use_device")
    # a request that DOES carry a (bad) token is still answered by the auth check, not the gate
    bad = _post_text(client, headers={"Authorization": "Bearer abc.def.ghi"})
    assert bad.status_code == 401 and bad.get_json()["code"] == "token_invalid"
    assert sb.count(GATE) == 3


def test_another_device_has_its_own_three(client, auth_on, sb, llm):
    sb.seed(GATE, 3)
    _done(_post_text(client, device="device-bbbb-0002"))
    assert sb.count("gate:dev:device-bbbb-0002") == 1


def test_the_old_daily_device_allowance_is_retired(client, auth_on, sb, llm, monkeypatch):
    # FAIR_DEVICE_DAILY used to grant 10 a day. It is still read (legacy config), but it
    # must never again grant an anonymous visitor anything.
    monkeypatch.setattr(appmod, "FAIR_DEVICE_DAILY", 1000)
    for _ in range(3):
        _done(_post_text(client))
    _refused(_post_text(client))
    assert not any(k.startswith("fair:dev:") for k in sb.rows)
    assert "fair_use_device" not in appmod._FAIR_REFUSALS


# ── 2. a lifetime allowance, not a daily one ─────────────────────────────────────
def test_the_free_uses_do_not_come_back_after_24_hours(client, auth_on, sb, llm):
    for _ in range(3):
        _done(_post_text(client))
    _refused(_post_text(client))
    sb.advance(25)                                            # a day later: the daily counters have reset...
    _refused(_post_text(client))                              # ...the free uses have not
    sb.advance(24 * 365)                                      # a year later
    _refused(_post_text(client))
    assert sb.count(GATE) == 3
    # every lookup of the gate asked for the long window, never 24 h
    wins = {p["p_window_hours"] for p in sb.params("anon_consume", GATE)}
    assert wins == {appmod.ANON_USES_WINDOW_HOURS} == {LONG}
    assert {p["p_limit"] for p in sb.params("anon_consume", GATE)} == {3}


def test_daily_counters_reset_but_the_gate_does_not(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "FAIR_ANON_IP_DAILY", 3)
    for _ in range(3):
        _done(_post_text(client))                             # device A: its 3 uses (and the IP's 3 for today)
    other = "device-bbbb-0002"
    _refused(_post_text(client, device=other), reason="network")   # device B: the network is used up for today
    sb.advance(25)
    _done(_post_text(client, device=other))                   # tomorrow B is welcome (a daily counter)
    _refused(_post_text(client))                              # A is still asked to sign in (a lifetime one)


def test_the_window_is_the_knob(sb, monkeypatch):
    monkeypatch.setattr(appmod, "ANON_USES_WINDOW_HOURS", 48)
    charge, err = _charge()
    assert err is None
    assert sb.params("anon_consume", GATE) == [{"p_key": GATE, "p_limit": 3, "p_window_hours": 48}]


# ── 3. the counters and their order ──────────────────────────────────────────────
def test_an_anonymous_request_is_charged_in_the_documented_order(sb):
    charge, err = _charge()
    assert err is None
    assert sb.calls == [
        ("anon_consume", {"p_key": GATE,   "p_limit": 3,    "p_window_hours": LONG}),
        ("anon_consume", {"p_key": ANONIP, "p_limit": 10,   "p_window_hours": 24}),
        ("anon_consume", {"p_key": FAIRIP, "p_limit": 250,  "p_window_hours": 24}),
        ("anon_consume", {"p_key": POOL,   "p_limit": 1200, "p_window_hours": 24}),
        ("anon_consume", {"p_key": GLOBAL, "p_limit": 2000, "p_window_hours": 24}),
    ]
    assert charge.fair_keys == tuple(ORDER) and charge.tok_left is None


def test_a_signed_in_request_is_charged_as_before(sb):
    charge, err = _charge(uid="user-7")
    assert err is None
    assert sb.calls == [
        ("anon_consume", {"p_key": "fair:user:user-7", "p_limit": 40,   "p_window_hours": 24}),
        ("anon_consume", {"p_key": FAIRIP,             "p_limit": 250,  "p_window_hours": 24}),
        ("anon_consume", {"p_key": GLOBAL,             "p_limit": 2000, "p_window_hours": 24}),
    ]


def test_the_anonymous_ip_counter_uses_the_ipv6_64(sb, monkeypatch):
    monkeypatch.setattr(appmod, "_client_ip", lambda: "2001:db8:1:2::abcd")
    charge, err = _charge()
    assert err is None and "fair:anonip:2001:db8:1:2::/64" in charge.fair_keys
    charge, err = _charge(device=None)
    assert err is None and charge.fair_keys[0] == "gate:noid:2001:db8:1:2::/64"


# ── 4. rotating device ids, and sending none ─────────────────────────────────────
def test_rotating_the_device_id_runs_into_the_anonymous_ip_cap(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "FAIR_ANON_IP_DAILY", 4)
    for i in range(4):
        _done(_post_text(client, device=f"device-rota-{i:04d}"))      # a fresh id every time
    d = _refused(_post_text(client, device="device-rota-9999"), reason="network")
    assert d["error"] == EN_NETWORK                                   # this device made nothing: it is not told it did
    assert sb.count("gate:dev:device-rota-9999") == 0                 # its gate unit was given back
    assert sb.count(ANONIP) == 4
    # the cap is on ANONYMOUS use of the network only: an account from the same IP is fine
    _done(_post_text(client, headers=_bearer("user-7")))
    # and another network is not affected
    monkeypatch.setattr(appmod, "_client_ip", lambda: "198.51.100.9")
    _done(_post_text(client, device="device-rota-9999"))


def test_ten_anonymous_guides_per_ip_a_day_by_default(sb):
    # A private window, cleared site data or another browser is a new device id with 3 more
    # guides. What bounds that on one network is this cap: 10 a day per IP, whatever the ids.
    for i in range(PER_IP):
        charge, err = _charge(device=f"device-rota-{i:04d}")
        assert err is None, i
    charge, err = _charge(device="device-rota-9999")
    assert charge is None and err[1] == 401
    assert err[0].get_json()["code"] == "signin_required" and err[0].get_json()["reason"] == "network"
    assert sb.count(ANONIP) == PER_IP and sb.count(FAIRIP) == PER_IP and sb.count(GLOBAL) == PER_IP


def test_a_fresh_browser_buys_three_more_but_a_network_stops_at_ten(client, auth_on, sb, llm):
    """The bypass the reviewers found, end to end: reset the browser after every 3 guides."""
    made = 0
    for browser in range(4):                                          # 4 "private windows" on one network
        for _ in range(3):
            r = _post_text(client, device=f"device-priv-{browser:04d}")
            if r.status_code != 200:
                _refused(r, reason="network")
                break
            _done(r)
            made += 1
    assert made == PER_IP                                             # 3 + 3 + 3 + 1, then the network says sign in
    _refused(_post_text(client, device="device-priv-9999"), reason="network")
    _done(_post_text(client, headers=_bearer("user-7")))              # an account on that network is not affected


def test_no_device_id_is_counted_per_ip_and_cannot_dodge_the_gate(client, auth_on, sb, llm):
    for _ in range(3):
        _done(_post_text(client, device=None))
    # this allowance is the IP's (everyone on it who sends no id shares it), so the refusal says "network"
    d = _refused(_post_text(client, device=None), reason="network")
    assert d["error"] == EN_NETWORK
    assert sb.count(NOID) == 3
    assert sb.params("anon_consume", NOID)[0] == {"p_key": NOID, "p_limit": 3, "p_window_hours": 24}
    assert not any(k.startswith("gate:dev:") for k in sb.rows)


@pytest.mark.parametrize("bad", ["bad id!", "short", "x" * 65, "  "])
def test_a_malformed_device_id_counts_as_none(client, auth_on, sb, llm, bad):
    sb.seed(NOID, 3)
    _refused(_post_text(client, device=bad), reason="network")


def test_no_device_id_and_no_ip_still_meets_the_gate(sb, monkeypatch):
    monkeypatch.setattr(appmod, "_client_ip", lambda: "unknown")
    charge, err = _charge(device=None)
    assert err is None and charge.fair_keys == ("gate:noid:unknown", POOL, GLOBAL)
    sb.seed("gate:noid:unknown", 3)
    charge, err = _charge(device=None)
    assert charge is None and err[1] == 401
    # with a device id an unknown IP is simply not counted per IP (as before)
    charge, err = _charge()
    assert err is None and charge.fair_keys == (GATE, POOL, GLOBAL)


# ── 5. signed-in users ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,post", ENDPOINTS, ids=EP_IDS)
def test_a_signed_in_request_never_touches_a_gate_key(client, auth_on, sb, llm, name, post):
    done = _done(post(client, headers=_bearer("user-7")))
    assert sb.spent() == {"fair:user:user-7": 1, FAIRIP: 1, GLOBAL: 1}
    assert not any(k.startswith(("gate:", "fair:anonip:")) or k == POOL for k in sb.keys("anon_consume"))
    assert "anon_remaining" not in done


def test_a_signed_in_user_is_not_asked_to_sign_in_after_three(client, auth_on, sb, llm):
    sb.seed(GATE, 3)                                          # this very browser used its free guides...
    sb.seed(ANONIP, 10 ** 6)                                  # ...the network's anonymous allowance is gone...
    sb.seed(POOL, 10 ** 6)                                    # ...and so is the anonymous pool
    for _ in range(5):
        _done(_post_text(client, headers=_bearer("user-7")))  # ...but the account just works
    assert sb.count("fair:user:user-7") == 5 and sb.count(GATE) == 3


def test_signing_in_is_the_way_forward(client, auth_on, sb, llm):
    for _ in range(3):
        _done(_post_text(client))
    _refused(_post_text(client))
    _done(_post_text(client, headers=_bearer("brand-new-user")))


def test_the_account_allowance_is_still_the_daily_one(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "FAIR_USER_DAILY", 2)
    h = _bearer("user-9")
    _done(_post_text(client, headers=h))
    _done(_post_text(client, headers=h))
    r = _post_text(client, headers=h)
    assert r.status_code == 429 and r.get_json()["code"] == "fair_use_user"
    sb.advance(25)
    _done(_post_text(client, headers=h))                      # an account's allowance does reset daily


# ── 6. refunds and rollback ──────────────────────────────────────────────────────
def test_a_failed_generation_gives_the_use_back(client, auth_on, sb, llm, monkeypatch):
    real = appmod.pass1_overview
    monkeypatch.setattr(appmod, "pass1_overview", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("groq down")))
    for _ in range(4):                                        # four failures in a row...
        evs = _sse_events(_post_text(client))
        assert evs[-1]["error"] and not any(e.get("step") == "done" for e in evs)
    assert sb.spent() == {}                                   # ...cost the visitor nothing
    assert sb.keys("anon_refund")[:5] == ORDER                # the gate unit went back with the others
    monkeypatch.setattr(appmod, "pass1_overview", real)
    for _ in range(3):
        _done(_post_text(client))                             # all three free guides are still there
    _refused(_post_text(client))


def test_a_hollow_guide_gives_the_use_back(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "pass2_section", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("pass2 failed")))
    assert _sse_events(_post_text(client))[-1]["code"] == "no_notes"
    assert sb.count(GATE) == 0


def test_a_disconnect_before_the_ai_work_gives_the_use_back(client, auth_on, sb, llm):
    r = _post_file(client)
    next(iter(r.response))                                    # first event out, then the client is gone
    r.close()
    assert sb.spent() == {} and llm == []


@pytest.mark.parametrize("name,post", [e for e in ENDPOINTS if e[0] != "youtube"], ids=["text", "file"])
def test_a_disconnect_after_the_ai_work_started_keeps_the_use_spent(client, auth_on, sb, llm, name, post):
    r = post(client)
    assert _read_until(r, b'"step": "pdf"')                   # the paid passes ran; now the client leaves
    r.close()
    assert sb.count(GATE) == 1 and sb.keys("anon_refund") == []


def test_dropping_the_socket_three_times_does_not_buy_a_fourth_guide(client, auth_on, sb, llm):
    for _ in range(3):
        r = _post_text(client)
        assert _read_until(r, b"Quiz ready")
        r.close()
    assert sb.count(GATE) == 3
    _refused(_post_text(client))


def test_youtube_disconnect_after_the_whisper_call_keeps_the_use(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(appmod, "_fetch_captions", lambda vid: (_ for _ in ()).throw(ValueError("no_captions")))
    monkeypatch.setattr(appmod, "_transcribe_with_whisper", lambda vid: "lecture words " * 50)
    r = _post_youtube(client)
    assert _read_until(r, b"Audio transcribed")
    r.close()
    assert sb.count(GATE) == 1 and sb.keys("anon_refund") == []


def test_a_validation_error_never_costs_a_use(client, auth_on, sb, llm):
    assert client.post("/api/summarize-text", json={"text": 123}, headers={"X-Device-Id": DEV}).status_code == 400
    assert client.post("/api/summarize-stream", data={"file": (io.BytesIO(b"x"), "evil.exe")},
                       content_type="multipart/form-data", headers={"X-Device-Id": DEV}).status_code == 400
    assert sb.calls == []


ROLLBACK = [
    # the exhausted counter, the refusal (and its reason), the counters taken before it (all must be given back)
    (ANONIP, 401, "signin_required", "network", [GATE]),
    (FAIRIP, 429, "fair_use_ip",     None,      [GATE, ANONIP]),
    (POOL,   401, "signin_required", "pool",    [GATE, ANONIP, FAIRIP]),
    (GLOBAL, 503, "busy_today",      None,      [GATE, ANONIP, FAIRIP, POOL]),
]


@pytest.mark.parametrize("full,status,code,reason,taken", ROLLBACK, ids=["anonip", "ip", "anon-pool", "global"])
def test_a_later_refusal_rolls_back_the_counters_already_taken(client, auth_on, sb, llm, full, status, code, reason, taken):
    sb.seed(full, 10 ** 6)
    r = _post_text(client)
    assert r.status_code == status and r.get_json()["code"] == code
    assert r.get_json().get("reason") == reason                # only the sign-in refusal carries a reason
    assert sb.keys("anon_refund") == taken                    # each one given back, once, in order
    assert sb.spent() == {full: 10 ** 6}                      # the free use included: it was not burned
    assert llm == []


def test_a_refusal_for_the_network_does_not_burn_a_free_use(client, auth_on, sb, llm):
    sb.seed(GLOBAL, 10 ** 6)                                  # the whole site is at capacity today
    for _ in range(5):
        assert _post_text(client).status_code == 503
    sb.rows.pop(GLOBAL)
    for _ in range(3):
        _done(_post_text(client))                             # tomorrow the visitor still has all three


def test_the_gate_is_the_first_counter_so_a_refused_visitor_touches_nothing_else(client, auth_on, sb, llm):
    sb.seed(GATE, 3)
    _refused(_post_text(client))
    assert sb.keys("anon_consume") == [GATE] and sb.keys("anon_refund") == []


# ── 7. fail open ─────────────────────────────────────────────────────────────────
def test_the_gate_fails_open_when_the_rpc_raises_and_says_so_in_the_log(client, auth_on, sb, llm, caplog):
    sb.raises[("anon_consume", GATE)] = RuntimeError("supabase 502")
    with caplog.at_level("ERROR", logger="app"):
        done = _done(_post_text(client))
    assert "failing open" in caplog.text
    assert DEV not in caplog.text and IP not in caplog.text   # the log names the counter, not the visitor
    assert "anon_remaining" not in done                       # unknown: the client is told nothing
    assert sb.spent() == {ANONIP: 1, FAIRIP: 1, POOL: 1, GLOBAL: 1}   # the readable counters still count
    assert GATE not in sb.keys("anon_refund")


def test_every_counter_failing_still_serves_the_visitor(client, auth_on, sb, llm):
    for k in ORDER:
        sb.raises[("anon_consume", k)] = Exception("Could not find the function public.anon_consume")
    for _ in range(5):
        _done(_post_text(client))
    assert sb.keys("anon_refund") == []


def test_no_database_fails_open(client, auth_on, llm, monkeypatch):
    monkeypatch.setattr(appmod, "_get_sb", lambda: None)
    for _ in range(4):
        assert "anon_remaining" not in _done(_post_text(client))


def test_a_failing_gate_does_not_hide_an_exhausted_ip_cap(sb):
    sb.raises[("anon_consume", GATE)] = RuntimeError("blip")
    sb.seed(ANONIP, 10 ** 6)
    charge, err = _charge()
    assert charge is None and err[1] == 401 and err[0].get_json()["code"] == "signin_required"
    assert err[0].get_json()["reason"] == "network"


# ── 8. the demo and existing guides are never gated ──────────────────────────────
def test_the_demo_is_never_gated_and_never_counted(client, auth_on, sb, llm):
    sb.seed(GATE, 3)
    sb.seed(ANONIP, 10 ** 6)
    sb.seed(POOL, 10 ** 6)
    first = _done(_post_demo(client))                         # a real run: one unit of the global budget only
    again = _done(_post_demo(client))                         # then copies from the cache: nothing at all
    assert sb.keys("anon_consume") == [GLOBAL]
    assert sb.count(GATE) == 3
    assert "anon_remaining" not in first and "anon_remaining" not in again
    _done(_post_demo(client, device=None))                    # with or without a device id


def test_the_demo_does_not_use_up_a_free_guide(client, auth_on, sb, llm):
    for _ in range(5):
        _done(_post_demo(client))
    assert sb.count(GATE) == 0 and sb.count(NOID) == 0
    for _ in range(3):
        _done(_post_text(client))                             # all three are still there


def test_the_demo_works_when_no_free_guides_are_offered_at_all(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "ANON_FREE_USES", 0)
    _done(_post_demo(client))
    _done(_post_demo(client, language="ar"))


def test_guides_already_made_stay_open_without_an_account(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "_GUIDE_KEY", b"k" * 32)
    jobs = [_done(_post_text(client))["job_id"] for _ in range(3)]
    _refused(_post_text(client))                              # no more NEW guides...
    before = len(sb.calls)
    job = jobs[0]
    g = client.get(f"/api/guide/{job}")                       # ...but the ones made are all still usable
    assert g.status_code == 200 and g.get_json()["sections"]
    pdf = client.get(f"/api/download/{job}")
    assert pdf.status_code == 200 and pdf.data[:4] == b"%PDF"
    assert client.get(f"/api/download/{job}?format=md").status_code == 200
    assert client.get(f"/api/export/anki/{job}").status_code == 200
    for view in ("md", "cards", "quiz"):
        assert client.get(f"/api/view/{view}/{job}").status_code == 200, view
    # restoring an expired guide from the browser's own signed copy is not "making a new guide"
    body = g.get_json()
    assert client.post(f"/api/delete/{job}").get_json()["deleted"] is True
    r = client.post("/api/rehydrate", json={"guide_blob": body["guide_blob"], "sig": body["sig"]},
                    headers={"X-Device-Id": DEV})
    assert r.status_code == 200 and client.get(f"/api/guide/{r.get_json()['job_id']}").status_code == 200
    assert len(sb.calls) == before                            # none of it touched a counter


# ── 9. anon_remaining on `done`, and /api/config ─────────────────────────────────
@pytest.mark.parametrize("name,post", ENDPOINTS, ids=EP_IDS)
def test_done_tells_the_client_how_many_free_guides_are_left(client, auth_on, sb, llm, name, post):
    assert [_done(post(client))["anon_remaining"] for _ in range(3)] == [2, 1, 0]
    _refused(post(client))


def test_done_keeps_its_shape(client, auth_on, sb, llm):
    for post in (_post_text, _post_file):
        done = _done(post(client))
        assert appmod._valid_job(done["job_id"])
        assert {"sections", "keywords", "flashcards", "mcqs", "anon_remaining"} <= set(done)
        assert done.get("tokens_remaining") is None           # free mode: there is no balance
        assert isinstance(done["anon_remaining"], int) and not isinstance(done["anon_remaining"], bool)


def test_no_device_id_gets_its_own_remainder(client, auth_on, sb, llm):
    assert _done(_post_text(client, device=None))["anon_remaining"] == 2


@pytest.mark.parametrize("reply", [{"ok": True}, {"ok": True, "remaining": "2"}, {"ok": True, "remaining": None},
                                   {"ok": True, "remaining": True}])
def test_an_odd_remaining_is_left_out_of_done(client, auth_on, llm, monkeypatch, reply):
    fake = MagicMock()
    fake.rpc.return_value.execute.return_value = SimpleNamespace(data=reply)
    monkeypatch.setattr(appmod, "_get_sb", lambda: fake)
    assert "anon_remaining" not in _done(_post_text(client))


def test_config_reports_the_gate(client):
    d = client.get("/api/config").get_json()
    assert d["free_mode"] is True
    assert d["anon_free_limit"] == 3 and d["anon_remaining"] == 3 and d["signin_after"] == 3
    assert d["fair_use"] == {"anon_free_uses": 3, "user_daily": 40, "device_daily": 3}
    for k in ("supabase_url", "supabase_anon_key", "stripe_publishable_key", "auth_enabled"):
        assert k in d


def test_config_anon_remaining_follows_the_device(client, auth_on, sb, llm):
    h = {"X-Device-Id": DEV}
    assert client.get("/api/config", headers=h).get_json()["anon_remaining"] == 3
    _done(_post_text(client))
    assert client.get("/api/config", headers=h).get_json()["anon_remaining"] == 2
    _done(_post_text(client))
    _done(_post_text(client))
    d = client.get("/api/config", headers=h).get_json()
    assert d["anon_remaining"] == 0 and d["anon_free_limit"] == 3 and d["signin_after"] == 3
    sb.advance(48)
    assert client.get("/api/config", headers=h).get_json()["anon_remaining"] == 0     # not a daily number
    assert client.get("/api/config", headers={"X-Device-Id": "device-bbbb-0002"}).get_json()["anon_remaining"] == 3


def test_config_reads_the_gate_key_with_the_long_window_and_consumes_nothing(client, sb):
    sb.seed(GATE, 1)
    d = client.get("/api/config", headers={"X-Device-Id": DEV}).get_json()
    assert d["anon_remaining"] == 2
    assert sb.calls == [("anon_remaining", {"p_key": GATE, "p_limit": 3, "p_window_hours": LONG})]
    assert sb.count(GATE) == 1


def test_config_without_a_device_id_reads_the_per_ip_gate(client, sb):
    sb.seed(NOID, 2)
    assert client.get("/api/config").get_json()["anon_remaining"] == 1
    assert sb.calls == [("anon_remaining", {"p_key": NOID, "p_limit": 3, "p_window_hours": 24})]


def test_config_falls_back_to_the_limit_when_the_rpc_fails(client, sb):
    sb.raises[("anon_remaining", GATE)] = RuntimeError("supabase 502")
    d = client.get("/api/config", headers={"X-Device-Id": DEV})
    assert d.status_code == 200 and d.get_json()["anon_remaining"] == 3


def test_config_never_reports_more_than_the_allowance_or_less_than_zero(client, monkeypatch):
    monkeypatch.setattr(appmod, "_get_sb", lambda: MagicMock())
    for raw, shown in ((99, 3), (-4, 0), (2, 2)):
        monkeypatch.setattr(appmod, "_anon_gate_remaining", lambda gate, raw=raw: raw)
        assert client.get("/api/config", headers={"X-Device-Id": DEV}).get_json()["anon_remaining"] == shown


def test_config_follows_the_knobs(client, monkeypatch):
    monkeypatch.setattr(appmod, "ANON_FREE_USES", 5)
    monkeypatch.setattr(appmod, "FAIR_USER_DAILY", 55)
    monkeypatch.setattr(appmod, "FAIR_DEVICE_DAILY", 77)          # retired: must not leak into free mode
    d = client.get("/api/config").get_json()
    assert d["anon_free_limit"] == d["anon_remaining"] == d["signin_after"] == 5
    assert d["fair_use"] == {"anon_free_uses": 5, "user_daily": 55, "device_daily": 5}


# ── 10. the words ────────────────────────────────────────────────────────────────
def test_the_refusal_is_bilingual_and_carries_the_real_number(client, auth_on, sb, llm, monkeypatch):
    sb.seed(GATE, 10 ** 6)
    en = _refused(_post_text(client))
    ar = _refused(_post_text(client, language="ar"))
    assert en["error"] == EN_TEXT and not _has_arabic(en["error"])
    assert _has_arabic(ar["error"])
    assert "حساب" in ar["error"] and "مجاني" in ar["error"] and "الثلاثة" in ar["error"]
    monkeypatch.setattr(appmod, "ANON_FREE_USES", 5)
    en5, ar5 = _refused(_post_text(client), 5), _refused(_post_text(client, language="ar"), 5)
    assert en5["error"] == "You've used your 5 free guides. Create a free account to keep going - it's still free."
    assert "الخمسة" in ar5["error"] and "الثلاثة" not in ar5["error"]
    monkeypatch.setattr(appmod, "ANON_FREE_USES", 12)
    assert "12" in _refused(_post_text(client), 12)["error"]
    assert "12" in _refused(_post_text(client, language="ar"), 12)["error"]


def test_a_single_free_guide_is_worded_in_the_singular(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "ANON_FREE_USES", 1)
    sb.seed(GATE, 1)
    en = _refused(_post_text(client), 1)["error"]
    assert en == "You've used your free guide. Create a free account to keep going - it's still free."
    assert _has_arabic(_refused(_post_text(client, language="ar"), 1)["error"])


def test_the_refusal_language_follows_the_request(client, auth_on, sb, llm):
    sb.seed(GATE, 3)
    # a file upload (multipart) and an Accept-Language header pick the language too
    r = _post_file(client, language="auto", headers={"Accept-Language": "ar"})
    assert _has_arabic(_refused(r)["error"])
    assert not _has_arabic(_refused(_post_file(client, language="auto", headers={"Accept-Language": "en"}))["error"])
    assert _has_arabic(_refused(_post_youtube(client, language="ar"))["error"])


@pytest.mark.parametrize("n", [0, 1, 2, 3, 5, 10, 11, 40])
def test_the_refusal_never_promises_too_much(monkeypatch, n):
    monkeypatch.setattr(appmod, "ANON_FREE_USES", n)
    with appmod.app.test_request_context("/"):
        for ar in (False, True):
            text = appmod._fair_refusal("signin_required", ar)[0].get_json()["error"]
            assert _has_arabic(text) is ar
            low = text.lower()
            for banned in ("unlimited", "غير محدود", "بلا حدود", "بدون حدود", "no sign-up", "no account needed",
                           "token", "upgrade", "subscribe", "اشتراك"):
                assert banned not in low, (n, banned)
            assert ("free account" in low) or ("حساب" in text and "مجاني" in text)


def test_every_sign_in_refusal_is_logged_for_the_funnel(client, auth_on, sb, llm, caplog):
    sb.seed(GATE, 3)
    with caplog.at_level("INFO", logger="app"):
        _refused(_post_text(client))
    assert "fair-use refusal" in caplog.text and "signin_required" in caplog.text


# ── 13. WHY: device / network / pool, each with its own true words ───────────────
REASONS = [
    # the exhausted counter, the reason, the English text
    (GATE,   "device",  EN_TEXT),
    (ANONIP, "network", EN_NETWORK),
    (POOL,   "pool",    EN_POOL),
]


@pytest.mark.parametrize("full,reason,text", REASONS, ids=[r[1] for r in REASONS])
@pytest.mark.parametrize("name,post", ENDPOINTS, ids=EP_IDS)
def test_the_refusal_says_why_on_every_endpoint(client, auth_on, sb, llm, name, post, full, reason, text):
    sb.seed(full, 10 ** 6)
    d = _refused(post(client), reason=reason)
    assert d["error"] == text
    assert llm == [] and sb.spent() == {full: 10 ** 6}


def test_a_visitor_who_made_no_guides_is_never_told_they_used_their_own(client, auth_on, sb, llm):
    """The false text the reviewers found: the network's (or the whole anonymous pool's) allowance
    is gone, this browser has made nothing, and it was told "You've used your 3 free guides"."""
    for full, reason in ((ANONIP, "network"), (POOL, "pool")):
        sb.rows.clear()
        sb.seed(full, 10 ** 6)
        for lang in ("en", "ar"):
            d = _refused(_post_text(client, device="device-new-00001", language=lang), reason=reason)
            for false_claim in ("You've used your", "your 3 free guides", "لقد استخدمت", "أدلتك المجانية"):
                assert false_claim not in d["error"], (reason, lang, d["error"])
            assert _has_arabic(d["error"]) is (lang == "ar")
        assert sb.count("gate:dev:device-new-00001") == 0     # and it still has all three for another day / network


def test_all_three_refusals_end_with_the_same_call_to_action():
    with appmod.app.test_request_context("/"):
        en = [appmod._fair_refusal("signin_required", False, r)[0].get_json() for r in ("device", "network", "pool")]
        ar = [appmod._fair_refusal("signin_required", True, r)[0].get_json() for r in ("device", "network", "pool")]
    assert [d["error"] for d in en] == [EN_TEXT, EN_NETWORK, EN_POOL]
    assert [d["reason"] for d in en] == [d["reason"] for d in ar] == ["device", "network", "pool"]
    assert all(d["error"].endswith(" " + CTA) for d in en)
    assert all(d["error"].endswith(" " + AR_CTA) and _has_arabic(d["error"]) for d in ar)
    assert len({d["error"] for d in en}) == 3 and len({d["error"] for d in ar}) == 3
    assert "شبكتك" in ar[1]["error"] and "شبكتك" not in ar[2]["error"] and "اليوم" in ar[1]["error"] and "اليوم" in ar[2]["error"]
    assert "network" in en[1]["error"] and "network" not in en[2]["error"]
    for d in en + ar:
        assert d["code"] == "signin_required" and d["free_uses"] == 3


def test_the_reason_is_always_one_of_the_three(monkeypatch):
    with appmod.app.test_request_context("/"):
        for odd in (None, "", "nonsense", 7):
            d = appmod._fair_refusal("signin_required", False, odd)[0].get_json()
            assert d["reason"] == "device" and d["error"] == EN_TEXT
        # the other refusals carry no reason at all
        for code in ("fair_use_ip", "fair_use_user", "busy_today"):
            assert "reason" not in appmod._fair_refusal(code)[0].get_json()
            assert "reason" not in appmod._fair_refusal(code, False, "network")[0].get_json()


@pytest.mark.parametrize("n", [0, 1, 2, 3, 5, 11])
@pytest.mark.parametrize("reason", ["device", "network", "pool"])
def test_no_reason_text_promises_too_much(monkeypatch, n, reason):
    monkeypatch.setattr(appmod, "ANON_FREE_USES", n)
    with appmod.app.test_request_context("/"):
        for ar in (False, True):
            text = appmod._fair_refusal("signin_required", ar, reason)[0].get_json()["error"]
            assert _has_arabic(text) is ar
            low = text.lower()
            for banned in ("unlimited", "غير محدود", "بلا حدود", "بدون حدود", "no sign-up", "no account needed",
                           "token", "upgrade", "subscribe", "اشتراك", "tomorrow", "غدًا"):
                assert banned not in low, (n, reason, banned)
            assert ("free account" in low) or ("حساب" in text and "مجاني" in text)
            if reason != "device":
                assert "you've used" not in low and "استخدمت" not in text


def test_zero_free_uses_is_the_device_reason_with_its_own_words(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "ANON_FREE_USES", 0)
    d = _refused(_post_text(client), 0, reason="device")
    assert d["error"] == "Create a free account to make study guides - it's free."
    assert "used" not in d["error"]                               # nobody "used" anything: there were none


def test_the_refusal_log_line_names_the_reason_for_the_funnel(client, auth_on, sb, llm, caplog):
    sb.seed(ANONIP, 10 ** 6)
    with caplog.at_level("INFO", logger="app"):
        _refused(_post_text(client), reason="network")
    assert "fair-use refusal code=signin_required status=401 reason=network" in caplog.text
    assert DEV not in caplog.text and IP not in caplog.text       # the counter's name, never the visitor


def test_config_anon_remaining_stays_the_device_counter(client, auth_on, sb, llm):
    """A used-up network or anonymous pool is not this device's count: /api/config keeps reporting
    what the DEVICE has left, so the client never tells a visitor their own guides are gone."""
    sb.seed(ANONIP, 10 ** 6)
    sb.seed(POOL, 10 ** 6)
    d = client.get("/api/config", headers={"X-Device-Id": DEV}).get_json()
    assert d["anon_remaining"] == 3 and d["anon_free_limit"] == 3 and d["signin_after"] == 3
    assert "reason" not in d


# ── 14. the client says the same three things ────────────────────────────────────
APP_JSX = os.path.join(ROOT, "frontend", "src", "App_dev.jsx")


def _same_spelling(text):
    """One spelling for comparing the server's sentence with the client's. The two files differ only
    in typography: the dash (" - " / " — ") and where the Arabic tanwin sits around the alef."""
    return text.replace("ً", "").replace("—", "-")


def _client_line(lang, key):
    """The source line of T.<lang>.<key> in the React client."""
    with open(APP_JSX, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("\nconst T = {")
    pack = src[start: src.index("\n}\n", start)]
    en, ar = pack.index("\n  en: {"), pack.index("\n  ar: {")
    block = pack[en:ar] if lang == "en" else pack[ar:]
    lines = [l for l in block.splitlines() if l.startswith(f"    {key}:")]
    assert len(lines) == 1, (lang, key, len(lines))
    return _same_spelling(lines[0])


def _server_text(ar, reason, n=3):
    old = appmod.ANON_FREE_USES
    appmod.ANON_FREE_USES = n
    try:
        with appmod.app.test_request_context("/"):
            return _same_spelling(appmod._fair_refusal("signin_required", ar, reason)[0].get_json()["error"])
    finally:
        appmod.ANON_FREE_USES = old


@pytest.mark.parametrize("lang", ["en", "ar"])
def test_the_client_words_the_network_and_pool_reasons_exactly_as_the_server(lang):
    for reason, key in (("network", "signinNetwork"), ("pool", "signinPool")):
        server = _server_text(lang == "ar", reason)
        line = _client_line(lang, key)
        quote = '"' if lang == "en" else "'"
        assert line == f"    {key}: {quote}{server}{quote},", (lang, reason, line)


@pytest.mark.parametrize("lang", ["en", "ar"])
def test_the_client_words_the_device_reason_as_the_server_does(lang):
    """The device text carries the number, so the client has a template: every fixed part of it is the
    server's, for the plural, the singular, the Arabic dual and "no free guide at all"."""
    ar = lang == "ar"
    quote = "'" if ar else '"'
    line = _client_line(lang, "signinRequired")
    assert f"n === 0 ? {quote}{_server_text(ar, 'device', 0)}{quote} : `" in line
    cta = _same_spelling(AR_CTA if ar else CTA)
    assert line.endswith(f". {cta}`,"), line[-90:]
    if ar:
        for n, piece in ((1, "دليلك المجاني"), (2, "دليلَيك المجانيَّين"), (3, "أدلتك المجانية الثلاثة"), (12, "أدلتك المجانية الـ12")):
            assert _server_text(True, "device", n) == f"لقد استخدمت {piece}. {cta}", n
        for piece in ("`لقد استخدمت ${", "'دليلك المجاني'", "'دليلَيك المجانيَّين'", "`أدلتك المجانية ${AR_THE_COUNT[n] || `الـ${n}`}`"):
            assert piece in line, piece
        # the count words (3 to 10) are the server's own table
        with open(APP_JSX, encoding="utf-8") as fh:
            table = re.search(r"^const AR_THE_COUNT = \{([^}]*)\}", fh.read(), re.M).group(1)
        assert {int(k): v for k, v in re.findall(r"(\d+): '([^']+)'", table)} == appmod._AR_THE_COUNT
    else:
        for n, piece in ((1, "free guide"), (3, "3 free guides"), (12, "12 free guides")):
            assert _server_text(False, "device", n) == f"You've used your {piece}. {cta}", n
        assert "`You've used your ${n === 1 ? 'free guide' : `${n} free guides`}. " in line


# ── 11. ALIMNE_FREE_MODE=0 is exactly the old token system ───────────────────────
def test_legacy_anonymous_is_the_old_402_and_never_meets_the_gate(client, auth_on, sb, llm, legacy_tokens, monkeypatch):
    monkeypatch.setattr(appmod, "_anon_durable_consume", lambda dev: (False, 0))
    r = _post_text(client)
    assert r.status_code == 402
    assert r.get_json() == {"error": "You've used your free previews. Sign up free to get more.",
                            "code": "signin_for_more", "tokens_remaining": 0}
    assert sb.calls == []


def test_legacy_anonymous_previews_use_the_old_device_key_and_limit(client, auth_on, sb, llm, legacy_tokens):
    done = _done(_post_text(client))
    assert "anon_remaining" not in done and done["tokens_remaining"] == appmod.ANON_FREE_LIMIT - 1
    assert sb.calls == [("anon_consume", {"p_key": f"dev:{DEV}", "p_limit": appmod.ANON_FREE_LIMIT,
                                          "p_window_hours": appmod._ANON_WINDOW_HOURS})]
    _done(_post_text(client))
    r = _post_text(client)                                    # the old 2 previews, then the old 402
    assert r.status_code == 402 and r.get_json()["code"] == "signin_for_more"


def test_legacy_signed_in_spends_a_token_and_no_counter(client, auth_on, sb, llm, legacy_tokens, monkeypatch):
    monkeypatch.setattr(appmod, "_consume_token", lambda uid: (True, 2, ""))
    done = _done(_post_text(client, headers=_bearer()))
    assert done["tokens_remaining"] == 2 and "anon_remaining" not in done
    assert list(done)[:3] == ["step", "job_id", "sections"] and sb.calls == []


def test_legacy_config_is_exactly_the_old_payload(client, sb, legacy_tokens, monkeypatch):
    monkeypatch.setattr(appmod, "ANON_FREE_USES", 9)              # the gate knob means nothing here
    sb.seed(f"dev:{DEV}", 1)
    d = client.get("/api/config", headers={"X-Device-Id": DEV}).get_json()
    assert d == {"supabase_url": appmod.SUPABASE_URL, "supabase_anon_key": appmod.SUPABASE_ANON_KEY,
                 "stripe_publishable_key": appmod.STRIPE_PUBLISHABLE_KEY, "auth_enabled": appmod._AUTH_ENABLED,
                 "anon_free_limit": appmod.ANON_FREE_LIMIT, "anon_remaining": appmod.ANON_FREE_LIMIT - 1,
                 "free_mode": False, "fair_use": {"device_daily": 10, "user_daily": 40}}
    assert sb.calls == [("anon_remaining", {"p_key": f"dev:{DEV}", "p_limit": appmod.ANON_FREE_LIMIT,
                                            "p_window_hours": appmod._ANON_WINDOW_HOURS})]


def test_legacy_demo_is_unchanged(client, auth_on, sb, llm, legacy_tokens):
    done = _done(_post_demo(client))
    assert done["tokens_remaining"] == 0 and "anon_remaining" not in done and sb.calls == []


# ── 12. the knobs ────────────────────────────────────────────────────────────────
def test_zero_free_uses_means_sign_in_from_the_first_guide(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "ANON_FREE_USES", 0)
    for _name, post in ENDPOINTS:
        d = _refused(post(client), 0)
        assert d["error"] == "Create a free account to make study guides - it's free."
    assert _has_arabic(_refused(_post_text(client, language="ar"), 0)["error"])
    assert sb.calls == [] and llm == []                       # decided without the database: it cannot fail open
    _done(_post_text(client, headers=_bearer("user-7")))      # accounts are unaffected
    d = client.get("/api/config", headers={"X-Device-Id": DEV}).get_json()
    assert d["anon_free_limit"] == d["anon_remaining"] == d["signin_after"] == 0
    assert d["fair_use"] == {"anon_free_uses": 0, "user_daily": 40, "device_daily": 0}


def test_zero_free_uses_holds_even_without_a_database(client, auth_on, llm, monkeypatch):
    monkeypatch.setattr(appmod, "ANON_FREE_USES", 0)
    monkeypatch.setattr(appmod, "_get_sb", lambda: None)
    _refused(_post_text(client), 0)


def test_the_gate_follows_the_knob(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "ANON_FREE_USES", 1)
    assert _done(_post_text(client))["anon_remaining"] == 0
    _refused(_post_text(client), 1)


_KNOB_PROBE = r"""
import json, os, sys
sys.path.insert(0, os.environ["APP_ROOT"]); os.chdir(os.environ["APP_ROOT"])
import app as A
print(json.dumps({k: getattr(A, k) for k in ("ANON_FREE_USES", "ANON_USES_WINDOW_HOURS", "FAIR_ANON_IP_DAILY",
                                               "FAIR_DEVICE_DAILY", "FAIR_USER_DAILY", "FREE_MODE")}))
"""
_GATE_ENV = ("ANON_FREE_USES", "ANON_USES_WINDOW_HOURS", "FAIR_ANON_IP_DAILY")


def _import_knobs(**env):
    """The knobs as a FRESH interpreter reads them at import (that is how production reads them)."""
    base = {k: v for k, v in os.environ.items()
            if k not in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "GROQ_API_KEY", "RENDER", "PRODUCTION",
                         "SUPABASE_URL", "SUPABASE_JWT_SECRET", "SUPABASE_SERVICE_ROLE_KEY",
                         "FAIR_DEVICE_DAILY", "FAIR_USER_DAILY", "ALIMNE_FREE_MODE") + _GATE_ENV}
    base.update(APP_ROOT=ROOT, **env)
    out = subprocess.run([sys.executable, "-c", _KNOB_PROBE], env=base, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_knob_defaults_and_overrides_at_import():
    assert _import_knobs() == {"ANON_FREE_USES": 3, "ANON_USES_WINDOW_HOURS": LONG, "FAIR_ANON_IP_DAILY": 10,
                               "FAIR_DEVICE_DAILY": 10, "FAIR_USER_DAILY": 40, "FREE_MODE": True}
    # the retired device knob is still read, harmlessly: it changes nothing about the gate
    k = _import_knobs(ANON_FREE_USES=" 5 ", ANON_USES_WINDOW_HOURS="720", FAIR_ANON_IP_DAILY="12",
                      FAIR_DEVICE_DAILY="7")
    assert k == {"ANON_FREE_USES": 5, "ANON_USES_WINDOW_HOURS": 720, "FAIR_ANON_IP_DAILY": 12,
                 "FAIR_DEVICE_DAILY": 7, "FAIR_USER_DAILY": 40, "FREE_MODE": True}


def _knobs(monkeypatch, **env):
    """(ANON_FREE_USES, ANON_USES_WINDOW_HOURS, FAIR_ANON_IP_DAILY) as the import-time parser
    reads them from this environment (the same function the module constants come from)."""
    for name in _GATE_ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return appmod._anon_gate_knobs()


def test_the_module_constants_come_from_the_knob_parser(monkeypatch):
    assert _knobs(monkeypatch) == (3, LONG, 10)
    assert _knobs(monkeypatch, ANON_FREE_USES="4", ANON_USES_WINDOW_HOURS="48", FAIR_ANON_IP_DAILY="9") == (4, 48, 9)


@pytest.mark.parametrize("uses,window,per_ip", [
    ("  ", "", " "),                       # blank
    ("three", "forever", "lots"),          # garbage
    ("2.5", "1e5", "0x10"),                # not whole numbers
    ("-1", "-24", "-5"),                   # negative: never "minus three free guides", never a window in the future
], ids=["blank", "garbage", "not-integers", "negative"])
def test_knob_nonsense_falls_back_to_the_safe_defaults(monkeypatch, uses, window, per_ip):
    assert _knobs(monkeypatch, ANON_FREE_USES=uses, ANON_USES_WINDOW_HOURS=window,
                  FAIR_ANON_IP_DAILY=per_ip) == (3, LONG, 10)


def test_knob_zero_is_meaningful_only_where_it_is_safe(monkeypatch):
    uses, window, per_ip = _knobs(monkeypatch, ANON_FREE_USES="0", ANON_USES_WINDOW_HOURS="0", FAIR_ANON_IP_DAILY="0")
    assert uses == 0                           # sign-in required from the very first guide
    assert window == LONG                      # a zero-hour window would hand the free guides back at once
    assert per_ip == 0                         # like every FAIR_*_DAILY knob: 0 = none


def test_an_absurd_window_is_capped_so_the_database_never_chokes_on_it(monkeypatch):
    # A window Postgres cannot subtract from now() would make the RPC raise, and a raising
    # RPC fails OPEN: the gate would silently vanish. So the knob is capped (100 years).
    assert _knobs(monkeypatch, ANON_USES_WINDOW_HOURS="99999999999999")[1] == 876000
    assert _knobs(monkeypatch, ANON_USES_WINDOW_HOURS="876000")[1] == 876000
    assert _knobs(monkeypatch, ANON_USES_WINDOW_HOURS="24")[1] == 24      # a daily allowance, if the owner wants one
