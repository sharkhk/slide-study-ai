"""
Alimne is FREE (ALIMNE_FREE_MODE, default on): no tokens, no credits, no paywall.
Generation is limited only by FAIR USE — daily counters kept in the existing
anon_consume / anon_refund RPCs under 'fair:*' keys — plus a process-wide cap on
simultaneous generations (a small queue, then 'busy') and a per-IP per-minute rate
limit. This file pins the SERVER side of that:

  A. a generation spends NO token and never answers 402 (anonymous or signed in);
     the demo stays free and unmetered
  B. the sign-in gate (anonymous) and the user / ip / global caps refuse with the right
     code and status, tell an anonymous visitor to create a free account, and roll back
     the counters already taken (the gate itself is pinned in tests/test_signin_gate.py)
  C. every counter FAILS OPEN (no database, RPC missing / raising / odd reply)
  D. exactly-once refunds: failure, hollow guide, client disconnect, success
  E. the generation semaphore: wait + 'queued' events, 'busy' + refund on timeout,
     the slot is released on EVERY path (and youtube takes exactly one)
  F. RATE_SUMMARIZE_PER_MIN replaces the hard-coded 5
  G. /api/config, /api/auth/me, checkout 410, the referral token reward is off
  H. ALIMNE_FREE_MODE=0 restores the old token system (no fair-use RPC, no queue, 5/min)
  I. the env knobs

EVERYTHING IS OFFLINE: Supabase is an in-memory fake, Groq / yt-dlp are faked.
"""
import io
import json
import os
import subprocess
import sys
import threading
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


# ── fakes + helpers ──────────────────────────────────────────────────────────────
class FakeSb:
    """In-memory anon_consume / anon_remaining / anon_refund (migrations 009 + 012)."""
    def __init__(self):
        self.counts = {}
        self.calls = []                  # (rpc name, key), in order
        self.consume_raises = {}         # key -> exception raised by anon_consume
        self.consume_reply = None        # a fixed (odd) reply for every anon_consume
        self.refund_raises = {}          # key -> exception raised by anon_refund

    def rpc(self, name, params):
        sb, key = self, params.get("p_key")

        class _Call:
            def execute(self_):
                sb.calls.append((name, key))
                if name == "anon_consume":
                    if key in sb.consume_raises:
                        raise sb.consume_raises[key]
                    if sb.consume_reply is not None:
                        return SimpleNamespace(data=sb.consume_reply)
                    n, lim = sb.counts.get(key, 0), params["p_limit"]
                    if n >= lim:
                        return SimpleNamespace(data={"ok": False, "remaining": 0})
                    sb.counts[key] = n + 1
                    return SimpleNamespace(data={"ok": True, "remaining": max(0, lim - n - 1)})
                if name == "anon_refund":
                    if key in sb.refund_raises:
                        raise sb.refund_raises[key]
                    sb.counts[key] = max(0, sb.counts.get(key, 0) - 1)
                    return SimpleNamespace(data=None)
                if name == "anon_remaining":
                    return SimpleNamespace(data=max(0, params["p_limit"] - sb.counts.get(key, 0)))
                raise AssertionError(f"unexpected rpc {name}")
        return _Call()

    def names(self, which):
        return [k for n, k in self.calls if n == which]


@pytest.fixture
def sb(monkeypatch):
    fake = FakeSb()
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


@pytest.fixture
def no_tokens(monkeypatch):
    """Anything that touches the old token system is a failure (and is recorded)."""
    calls = []
    def boom(name):
        def _f(*a, **k):
            calls.append(name)
            raise AssertionError(f"{name}: the token system was used in free mode")
        return _f
    for n in ("_consume_token", "_refund_token", "_anon_durable_consume", "_anon_consume",
              "_anon_durable_refund", "_anon_refund", "_add_tokens"):
        monkeypatch.setattr(appmod, n, boom(n))
    return calls


def _tok(sub="user-1"):
    now = int(time.time())
    return pyjwt.encode({"sub": sub, "aud": "authenticated", "exp": now + 3600, "iat": now},
                        SECRET, algorithm="HS256")


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
    """Offline generation: a real (fast) pipeline over a fake Groq."""
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "_call_ollama", _llm)
    monkeypatch.setattr(appmod, "_ensure_arabic_font", lambda: False)
    monkeypatch.setattr(appmod, "_yt_duration", lambda vid: 60)
    monkeypatch.setattr(appmod, "_fetch_captions", lambda vid: "lecture words " * 50)


def _fake_llm(monkeypatch, bullets=True, pass1_raises=False, started=None, gate=None):
    """pass1..pass4 replaced one by one, so a test can hold generation open (gate)."""
    def p1(slides, language, dcfg=None):
        if started is not None:
            started.set()
        if gate is not None:
            gate.wait(10)
        if pass1_raises:
            raise RuntimeError("groq down")
        return {"title": "T", "subtitle": "", "objectives": ["o"],
                "sections": [{"title": "S1", "slide_nums": [1]}],
                "keywords": [{"term": "k", "definition": "d"}]}
    def p2(title, sl, language, dcfg=None):
        if not bullets:
            raise RuntimeError("pass2 failed")
        return {"bullets": ["b1", "b2"]}
    monkeypatch.setattr(appmod, "pass1_overview", p1)
    monkeypatch.setattr(appmod, "pass2_section", p2)
    monkeypatch.setattr(appmod, "pass3_flashcards", lambda g, l, d=None: {"flashcards": [{"q": "q", "a": "a"}]})
    monkeypatch.setattr(appmod, "pass4_mcq", lambda g, l, d=None: {"mcqs": [{"q": "q", "options": ["A) x"], "answer": "A"}]})
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)


def _sse_events(resp):
    return [json.loads(line[len("data: "):]) for line in resp.get_data(as_text=True).splitlines()
            if line.startswith("data: ")]


def _events(gen):
    return [json.loads(chunk[len("data: "):].strip()) for chunk in gen]


def _spawn(gen):
    out = []
    def run():
        for chunk in gen:
            out.append(json.loads(chunk[len("data: "):].strip()))
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, out


def _wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def _has_arabic(s):
    return any("؀" <= ch <= "ۿ" for ch in s or "")


def _keys(dev=DEV, ip=IP):
    """Every counter an ANONYMOUS generation takes one unit from, in charge order:
    the sign-in gate (the device's free guides), anonymous guides from this IP today,
    the IP, the anonymous slice of the global budget, the global budget."""
    return [f"gate:dev:{dev}", f"fair:anonip:{ip}", f"fair:ip:{ip}", "fair:global:anon", "fair:global"]


def _post_text(client, device=DEV, headers=None, **body):
    h = {"X-Device-Id": device} if device else {}
    h.update(headers or {})
    return client.post("/api/summarize-text", json={"text": TEXT, "language": "en", **body}, headers=h)


def _post_file(client, device=DEV, headers=None, **form):
    h = {"X-Device-Id": device} if device else {}
    h.update(headers or {})
    data = {"file": (io.BytesIO(TEXT.encode()), "lecture.txt"), "language": "en", **form}
    return client.post("/api/summarize-stream", data=data, content_type="multipart/form-data", headers=h)


def _post_youtube(client, device=DEV, headers=None, **body):
    h = {"X-Device-Id": device} if device else {}
    h.update(headers or {})
    return client.post("/api/youtube", json={"url": "https://youtu.be/dQw4w9WgXcQ", "language": "en", **body},
                       headers=h)


ENDPOINTS = [("text", _post_text), ("file", _post_file), ("youtube", _post_youtube)]


# ── A. no token, no 402 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,post", ENDPOINTS, ids=[e[0] for e in ENDPOINTS])
def test_anonymous_generation_spends_no_token(client, auth_on, sb, llm, no_tokens, name, post):
    evs = _sse_events(post(client))
    done = evs[-1]
    assert done["step"] == "done"
    assert done.get("tokens_remaining") is None          # omitted: there is no balance
    assert sb.counts == {k: 1 for k in _keys()}          # gate + ip + global counters, nothing else
    assert no_tokens == []


@pytest.mark.parametrize("name,post", ENDPOINTS, ids=[e[0] for e in ENDPOINTS])
def test_signed_in_generation_spends_no_token(client, auth_on, sb, llm, no_tokens, name, post):
    r = post(client, headers={"Authorization": f"Bearer {_tok('user-7')}"})
    assert _sse_events(r)[-1]["step"] == "done"
    # the ACCOUNT counter replaces the device one; a signed-in user is never charged both
    assert sb.counts == {"fair:user:user-7": 1, f"fair:ip:{IP}": 1, "fair:global": 1}
    assert no_tokens == []


def test_no_402_is_ever_returned_in_free_mode(client, auth_on, sb, llm, no_tokens):
    # An anonymous device makes its free guides and is then asked to sign in: a 401
    # 'signin_required', never the token system's 402 (and never a token touched).
    for _ in range(appmod.ANON_FREE_USES):
        r = _post_text(client)
        assert r.status_code == 200 and _sse_events(r)[-1]["step"] == "done"
    r = _post_text(client)
    assert r.status_code == 401 and r.get_json()["code"] == "signin_required"
    assert no_tokens == []


def test_file_and_text_done_events_keep_their_shape(client, auth_on, sb, llm):
    for post in (_post_text, _post_file):
        done = _sse_events(post(client))[-1]
        assert done["step"] == "done" and appmod._valid_job(done["job_id"])
        assert {"sections", "keywords", "flashcards", "mcqs"} <= set(done)


def test_demo_is_free_for_the_visitor(client, auth_on, sb, llm, no_tokens, monkeypatch):
    # The visitor's own counters (the sign-in gate, the IP ones, the anonymous slice) are all
    # exhausted — the demo does not care and takes none of them. A real (uncached) run costs real
    # AI money, so it takes one unit from the GLOBAL budget only (see J2: cached copies cost nothing).
    for k in _keys()[:4]:
        sb.counts[k] = 10 ** 6
    before = dict(sb.counts)
    r = client.post("/api/summarize-text", json={"demo": True, "language": "en"}, headers={"X-Device-Id": DEV})
    assert r.status_code == 200
    assert _sse_events(r)[-1]["step"] == "done"
    assert sb.counts == {**before, "fair:global": 1} and sb.names("anon_consume") == ["fair:global"]
    assert no_tokens == []


def test_anonymous_without_a_device_id_is_counted_per_ip_at_the_gate(client, auth_on, sb, llm):
    r = _post_text(client, device=None)
    assert _sse_events(r)[-1]["step"] == "done"
    assert sb.counts == {f"gate:noid:{IP}": 1, f"fair:anonip:{IP}": 1, f"fair:ip:{IP}": 1,
                         "fair:global:anon": 1, "fair:global": 1}


def test_a_malformed_device_id_counts_as_none(client, auth_on, sb, llm):
    r = _post_text(client, device="bad id!")
    assert _sse_events(r)[-1]["step"] == "done"
    assert f"gate:noid:{IP}" in sb.counts


def test_unknown_ip_is_not_lumped_into_one_shared_counter(monkeypatch, sb):
    monkeypatch.setattr(appmod, "_client_ip", lambda: "unknown")
    with appmod.app.test_request_context("/", headers={"X-Device-Id": DEV}):
        charge, err = appmod._charge_credit(None, appmod.request)
    assert err is None and charge.fair_keys == (f"gate:dev:{DEV}", "fair:global:anon", "fair:global")


def test_validation_errors_spend_nothing_and_never_wait_for_a_slot(client, auth_on, sb, monkeypatch):
    sem = threading.BoundedSemaphore(1)
    sem.acquire()                                           # every slot is taken
    monkeypatch.setattr(appmod, "_gen_sem", sem)
    monkeypatch.setattr(appmod, "GEN_QUEUE_WAIT_S", 5.0)
    t0 = time.monotonic()
    r1 = client.post("/api/summarize-text", json={"text": 123}, headers={"X-Device-Id": DEV})
    r2 = client.post("/api/summarize-stream", data={"file": (io.BytesIO(b"x"), "evil.exe")},
                     content_type="multipart/form-data", headers={"X-Device-Id": DEV})
    r3 = client.post("/api/summarize-text", json={"url": "http://localhost/x"}, headers={"X-Device-Id": DEV})
    try:
        assert (r1.status_code, r2.status_code, r3.status_code) == (400, 400, 400)
        assert time.monotonic() - t0 < 2.0
        assert sb.calls == []                               # validated first, then charged
    finally:
        sem.release()


# ── B. the caps ──────────────────────────────────────────────────────────────────
ANON_CASES = [
    # exhausted counter, refusal code, status, counters already taken that must be rolled back
    ("gate",   "signin_required", 401, []),                         # the device's free guides are used
    ("anonip", "signin_required", 401, ["gate"]),                   # anonymous guides from this IP today
    ("ip",     "fair_use_ip",     429, ["gate", "anonip"]),
    ("anon",   "signin_required", 401, ["gate", "anonip", "ip"]),   # the anonymous slice of the global budget
    ("global", "busy_today",      503, ["gate", "anonip", "ip", "anon"]),
]
# WHY a sign-in refusal was given (the 401 body's `reason`): each cause has its own, true, text
SIGNIN_REASON = {"gate": "device", "anonip": "network", "anon": "pool"}


@pytest.mark.parametrize("which,code,status,taken_before", ANON_CASES, ids=[c[0] for c in ANON_CASES])
def test_exhausted_counter_refuses_and_rolls_back_the_ones_already_taken(
        client, auth_on, sb, llm, no_tokens, which, code, status, taken_before):
    key = {"gate": f"gate:dev:{DEV}", "anonip": f"fair:anonip:{IP}", "ip": f"fair:ip:{IP}",
           "anon": "fair:global:anon", "global": "fair:global"}
    sb.counts[key[which]] = 10 ** 6                          # far past any cap
    r = _post_text(client)
    assert r.status_code == status
    d = r.get_json()
    assert d["code"] == code and d["error"]
    assert d["code"] not in ("no_tokens", "signin_for_more", "fair_use_device")
    assert d.get("free_uses") == (appmod.ANON_FREE_USES if code == "signin_required" else None)
    assert d.get("reason") == SIGNIN_REASON.get(which)       # None for the refusals that are not about signing in
    # the exhausted counter was not touched; every one taken before it was given back
    assert sb.counts[key[which]] == 10 ** 6
    assert all(sb.counts.get(key[w], 0) == 0 for w in key if w != which)
    assert sb.names("anon_refund") == [key[w] for w in taken_before]
    assert no_tokens == []


def test_user_counter_refusal_and_rollback(client, auth_on, sb, llm, no_tokens):
    sb.counts["fair:user:user-7"] = 10 ** 6
    r = _post_text(client, headers={"Authorization": f"Bearer {_tok('user-7')}"})
    assert r.status_code == 429 and r.get_json()["code"] == "fair_use_user"
    assert sb.names("anon_refund") == [] and sb.counts == {"fair:user:user-7": 10 ** 6}
    # ...and when the IP is the exhausted one, the account unit taken first is returned
    sb.counts = {f"fair:ip:{IP}": 10 ** 6}
    sb.calls.clear()
    r = _post_text(client, headers={"Authorization": f"Bearer {_tok('user-7')}"})
    assert r.status_code == 429 and r.get_json()["code"] == "fair_use_ip"
    assert sb.names("anon_refund") == ["fair:user:user-7"] and sb.counts.get("fair:user:user-7") == 0


@pytest.mark.parametrize("name,post", ENDPOINTS, ids=[e[0] for e in ENDPOINTS])
def test_every_generation_endpoint_enforces_the_caps(client, auth_on, sb, llm, name, post):
    sb.counts[f"gate:dev:{DEV}"] = 10 ** 6
    r = post(client)
    assert r.status_code == 401 and r.get_json()["code"] == "signin_required"
    sb.counts = {f"fair:ip:{IP}": 10 ** 6}
    r = post(client)
    assert r.status_code == 429 and r.get_json()["code"] == "fair_use_ip"


def _status(resp):
    """Status of a response after its stream was read to the end (a stream that is
    never read is closed at its first event and refunds itself — see D)."""
    resp.get_data()
    return resp.status_code


def test_caps_are_the_configured_knobs(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "ANON_FREE_USES", 2)
    assert [_status(_post_text(client)) for _ in range(3)] == [200, 200, 401]
    monkeypatch.setattr(appmod, "FAIR_USER_DAILY", 1)
    h = {"Authorization": f"Bearer {_tok('user-9')}"}
    assert [_status(_post_text(client, headers=h)) for _ in range(2)] == [200, 429]
    sb.counts = {}
    monkeypatch.setattr(appmod, "ANON_FREE_USES", 3)
    monkeypatch.setattr(appmod, "FAIR_ANON_IP_DAILY", 2)
    assert [_status(_post_text(client, device=f"device-cccc-000{i}")) for i in range(3)] == [200, 200, 401]
    sb.counts = {}
    monkeypatch.setattr(appmod, "FAIR_ANON_IP_DAILY", 10)
    monkeypatch.setattr(appmod, "FAIR_IP_DAILY", 1)
    assert [_status(_post_text(client, device=f"device-bbbb-000{i}")) for i in range(2)] == [200, 429]
    sb.counts = {}
    monkeypatch.setattr(appmod, "FAIR_IP_DAILY", 250)
    monkeypatch.setattr(appmod, "FAIR_GLOBAL_DAILY", 1)
    r1 = _post_text(client)
    r2 = _post_text(client, headers={"Authorization": f"Bearer {_tok('user-9')}"})   # signed in: no anonymous slice
    r1.get_data()
    assert r1.status_code == 200 and r2.status_code == 503 and r2.get_json()["code"] == "busy_today"


def test_counters_use_the_documented_rpc_and_window(monkeypatch, sb):
    seen = []
    real = sb.rpc
    def spy(name, params):
        seen.append((name, dict(params)))
        return real(name, params)
    sb.rpc = spy
    with appmod.app.test_request_context("/", headers={"X-Device-Id": DEV}):
        charge, err = appmod._charge_credit(None, appmod.request)
    assert err is None
    assert seen == [("anon_consume", {"p_key": f"gate:dev:{DEV}", "p_limit": 3, "p_window_hours": 87600}),
                    ("anon_consume", {"p_key": f"fair:anonip:{IP}", "p_limit": 10, "p_window_hours": 24}),
                    ("anon_consume", {"p_key": f"fair:ip:{IP}", "p_limit": 250, "p_window_hours": 24}),
                    ("anon_consume", {"p_key": "fair:global:anon", "p_limit": 1200, "p_window_hours": 24}),
                    ("anon_consume", {"p_key": "fair:global", "p_limit": 2000, "p_window_hours": 24})]
    assert charge.tok_left is None and charge.fair_keys == tuple(_keys())


def test_refusal_text_is_bilingual_and_never_says_unlimited(client, auth_on, sb, llm):
    for code, key in (("signin_required", f"gate:dev:{DEV}"), ("fair_use_ip", f"fair:ip:{IP}"),
                      ("busy_today", "fair:global")):
        sb.counts = {key: 10 ** 6}
        en = _post_text(client).get_json()
        ar = _post_text(client, language="ar").get_json()
        assert en["code"] == ar["code"] == code
        assert not _has_arabic(en["error"]) and _has_arabic(ar["error"])
        assert "unlimited" not in en["error"].lower()
    sb.counts = {f"gate:dev:{DEV}": 10 ** 6}
    assert "create a free account" in _post_text(client).get_json()["error"].lower()
    assert "أنشئ حسابًا مجانيًا" in _post_text(client, language="ar").get_json()["error"]
    # a file upload (multipart) and an Accept-Language header pick the language too
    r = _post_file(client, language="auto", headers={"Accept-Language": "ar"})
    assert r.status_code == 401 and _has_arabic(r.get_json()["error"])


def test_a_signed_in_user_is_not_held_to_the_anonymous_device_cap(client, auth_on, sb, llm):
    sb.counts[f"gate:dev:{DEV}"] = 10 ** 6                    # the device's free guides are used up…
    r = _post_text(client, headers={"Authorization": f"Bearer {_tok('user-3')}"})
    assert _sse_events(r)[-1]["step"] == "done"               # …but the account has its own allowance


# ── C. fail open ─────────────────────────────────────────────────────────────────
def test_rpc_raising_fails_open_and_logs(client, auth_on, sb, llm, no_tokens, caplog):
    for k in _keys():
        sb.consume_raises[k] = RuntimeError("supabase 502")
    with caplog.at_level("ERROR", logger="app"):
        r = _post_text(client)
    assert r.status_code == 200 and _sse_events(r)[-1]["step"] == "done"
    assert "failing open" in caplog.text
    assert sb.names("anon_refund") == []                      # nothing was taken, nothing to give back


def test_missing_rpc_fails_open(client, auth_on, sb, llm):
    err = Exception("Could not find the function public.anon_consume in the schema cache")
    for k in _keys():
        sb.consume_raises[k] = err
    assert _sse_events(_post_text(client))[-1]["step"] == "done"


@pytest.mark.parametrize("reply", [[{"ok": True}], "ok", None, {"remaining": 3}])
def test_odd_rpc_reply_fails_open(client, auth_on, sb, llm, reply):
    sb.consume_reply = reply if reply is not None else ["x"]
    assert _sse_events(_post_text(client))[-1]["step"] == "done"


def test_no_database_fails_open_silently(client, auth_on, llm, monkeypatch, caplog):
    monkeypatch.setattr(appmod, "_get_sb", lambda: None)
    with caplog.at_level("WARNING", logger="app"):
        r = _post_text(client)
    assert _sse_events(r)[-1]["step"] == "done"
    assert "failing open" not in caplog.text                  # nothing broke: there is simply no DB


def test_one_counter_failing_still_charges_the_others_and_refunds_only_those(sb, monkeypatch):
    sb.consume_raises["fair:global"] = RuntimeError("timeout")
    with appmod.app.test_request_context("/", headers={"X-Device-Id": DEV}):
        charge, err = appmod._charge_credit(None, appmod.request)
    assert err is None and charge.fair_keys == tuple(_keys()[:4])
    assert charge.refund() is True
    assert sb.names("anon_refund") == _keys()[:4]             # never the unknown one
    assert sb.counts == {k: 0 for k in _keys()[:4]}


def test_a_failing_counter_does_not_hide_an_exhausted_one(sb):
    sb.consume_raises[f"gate:dev:{DEV}"] = RuntimeError("blip")
    sb.counts[f"fair:ip:{IP}"] = 10 ** 6
    with appmod.app.test_request_context("/", headers={"X-Device-Id": DEV}):
        charge, err = appmod._charge_credit(None, appmod.request)
    assert charge is None and err[1] == 429 and err[0].get_json()["code"] == "fair_use_ip"


# ── D. refunds, exactly once ─────────────────────────────────────────────────────
def test_failed_generation_refunds_every_counter_once(client, auth_on, sb, monkeypatch):
    _fake_llm(monkeypatch, pass1_raises=True)
    evs = _sse_events(_post_text(client))
    assert evs[-1]["error"] and not any(e.get("step") == "done" for e in evs)
    assert sb.counts == {k: 0 for k in _keys()}
    assert sb.names("anon_refund") == _keys()                 # one refund per counter, no more


def test_hollow_guide_refunds_and_never_talks_about_credits(client, auth_on, sb, monkeypatch):
    _fake_llm(monkeypatch, bullets=False)
    last = _sse_events(_post_text(client))[-1]
    assert last["code"] == "no_notes" and last["refunded"] is False
    assert "credit" not in last["error"].lower() and not _has_arabic(last["error"])
    assert sb.counts == {k: 0 for k in _keys()}
    ar = _sse_events(_post_text(client, language="ar"))[-1]
    assert ar["code"] == "no_notes" and _has_arabic(ar["error"])


def test_ai_not_configured_refunds(client, auth_on, sb, monkeypatch):
    monkeypatch.setattr(appmod, "ollama_running", lambda: False)
    r = _post_file(client)
    assert r.status_code == 503
    assert sb.counts == {k: 0 for k in _keys()} and sb.names("anon_refund") == _keys()


def test_unusable_url_after_the_charge_refunds(client, auth_on, sb, monkeypatch):
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "_fetch_url_text", lambda url: (_ for _ in ()).throw(ValueError("nope")))
    r = client.post("/api/summarize-text", json={"url": "https://example.com/x"}, headers={"X-Device-Id": DEV})
    assert r.status_code == 400
    assert sb.counts == {k: 0 for k in _keys()}


def test_success_keeps_the_units_spent_and_never_refunds(client, auth_on, sb, llm):
    assert _sse_events(_post_text(client))[-1]["step"] == "done"
    assert sb.counts == {k: 1 for k in _keys()} and sb.names("anon_refund") == []


def test_client_disconnect_refunds_exactly_once(sb, monkeypatch):
    _fake_llm(monkeypatch)
    with appmod.app.test_request_context("/", headers={"X-Device-Id": DEV}):
        charge, err = appmod._charge_credit(None, appmod.request)
    assert err is None and sb.counts == {k: 1 for k in _keys()}
    gen = appmod._stream_text_as_sse(TEXT, "en", "x", "text", charge=charge)()
    next(gen)                                                  # first event delivered…
    gen.close()                                                # …then the client goes away
    assert sb.counts == {k: 0 for k in _keys()} and sb.names("anon_refund") == _keys()
    gen.close()
    assert len(sb.names("anon_refund")) == len(_keys())        # a second close refunds nothing


def test_disconnect_in_the_file_stream_refunds_and_releases_the_slot(client, auth_on, sb, llm):
    r = _post_file(client)                                     # not read: closing it = the client left
    next(iter(r.response))
    r.close()
    assert sb.counts == {k: 0 for k in _keys()}


def test_charge_refund_is_idempotent_and_settle_wins(sb):
    sb.counts = {"fair:ip:1.2.3.4": 1, "fair:global": 1}
    ch = appmod._Charge(ip="1.2.3.4", fair_keys=("fair:ip:1.2.3.4", "fair:global"))
    assert ch.refund() is True and ch.refunded is True
    assert ch.refund() is False
    assert sb.names("anon_refund") == ["fair:ip:1.2.3.4", "fair:global"]
    settled = appmod._Charge(fair_keys=("fair:global",))
    settled.settle()
    assert settled.refund() is False and len(sb.names("anon_refund")) == 2
    assert appmod._Charge(fair_keys=()).refund() is True       # nothing was taken: nothing to do


def test_a_refund_that_partly_fails_is_not_reported_as_returned(sb):
    sb.counts = {"fair:ip:1.2.3.4": 1, "fair:global": 1}
    sb.refund_raises["fair:ip:1.2.3.4"] = RuntimeError("rpc down")
    ch = appmod._Charge(fair_keys=("fair:ip:1.2.3.4", "fair:global"))
    assert ch.refund() is True
    assert ch.refunded is False
    assert sb.counts == {"fair:ip:1.2.3.4": 1, "fair:global": 0}   # the other one still went back


# ── E. the generation semaphore ──────────────────────────────────────────────────
@pytest.fixture
def tiny_sem(monkeypatch):
    """One generation slot, a fast 'queued' tick and a short wait."""
    sem = threading.BoundedSemaphore(1)
    monkeypatch.setattr(appmod, "_gen_sem", sem)
    monkeypatch.setattr(appmod, "_GEN_QUEUE_TICK_S", 0.05)
    monkeypatch.setattr(appmod, "GEN_QUEUE_WAIT_S", 0.4)
    monkeypatch.setattr(appmod, "_GEN_WAIT_MAX", 8)         # the seat limit has its own tests (section J)
    return sem


def test_a_second_generation_waits_in_line_then_proceeds(tiny_sem, monkeypatch):
    monkeypatch.setattr(appmod, "GEN_QUEUE_WAIT_S", 10.0)
    started, gate = threading.Event(), threading.Event()
    _fake_llm(monkeypatch, started=started, gate=gate)
    ta, ea = _spawn(appmod._stream_text_as_sse(TEXT, "en", "a", "text")())
    assert started.wait(5)                                     # A holds the only slot
    tb, eb = _spawn(appmod._stream_text_as_sse(TEXT, "en", "b", "text")())
    assert _wait_for(lambda: any(e.get("step") == "queued" for e in eb))
    queued = [e for e in eb if e.get("step") == "queued"][0]
    assert queued["position"] == 1 and "1" in queued["msg"] and eb[0] is queued   # told at once
    assert tiny_sem._value == 0 and len(appmod._gen_waiting) == 1
    assert not any(e.get("step") in ("extract", "done") for e in eb)               # not started yet
    assert _wait_for(lambda: len([e for e in eb if e.get("step") == "queued"]) >= 2)  # and again, later
    gate.set()
    ta.join(10), tb.join(10)
    assert ea[-1]["step"] == "done" and eb[-1]["step"] == "done"
    steps = [e.get("step") for e in eb]
    assert steps.index("extract") > max(i for i, s in enumerate(steps) if s == "queued")
    assert tiny_sem._value == 1 and appmod._gen_waiting == []


def test_never_more_than_the_cap_generate_at_once(monkeypatch):
    monkeypatch.setattr(appmod, "_gen_sem", threading.BoundedSemaphore(2))
    monkeypatch.setattr(appmod, "_GEN_QUEUE_TICK_S", 0.05)
    monkeypatch.setattr(appmod, "GEN_QUEUE_WAIT_S", 30.0)
    monkeypatch.setattr(appmod, "_GEN_WAIT_MAX", 10)
    _fake_llm(monkeypatch)
    lock, live, peak = threading.Lock(), [0], [0]
    def slow_pass1(slides, language, dcfg=None):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.15)
        with lock:
            live[0] -= 1
        return {"title": "T", "subtitle": "", "objectives": ["o"],
                "sections": [{"title": "S1", "slide_nums": [1]}], "keywords": []}
    monkeypatch.setattr(appmod, "pass1_overview", slow_pass1)
    runs = [_spawn(appmod._stream_text_as_sse(TEXT, "en", f"r{i}", "text")()) for i in range(6)]
    for t, _ in runs:
        t.join(30)
    assert peak[0] == 2                                        # the cap was reached, never exceeded
    assert all(out[-1]["step"] == "done" for _, out in runs)   # and everybody got served in the end
    assert sum(1 for _, out in runs if out[0].get("step") == "queued") >= 3


def test_the_queue_reports_each_waiters_place(tiny_sem, monkeypatch):
    monkeypatch.setattr(appmod, "GEN_QUEUE_WAIT_S", 10.0)
    started, gate = threading.Event(), threading.Event()
    _fake_llm(monkeypatch, started=started, gate=gate)
    ta, ea = _spawn(appmod._stream_text_as_sse(TEXT, "en", "a", "text")())
    assert started.wait(5)
    tb, eb = _spawn(appmod._stream_text_as_sse(TEXT, "en", "b", "text")())
    assert _wait_for(lambda: len(appmod._gen_waiting) == 1)
    tc, ec = _spawn(appmod._stream_text_as_sse(TEXT, "en", "c", "text")())
    assert _wait_for(lambda: len(appmod._gen_waiting) == 2)
    assert _wait_for(lambda: any(e.get("step") == "queued" for e in ec))
    assert [e for e in ec if e.get("step") == "queued"][0]["position"] == 2
    gate.set()
    for t in (ta, tb, tc):
        t.join(10)
    assert all(e[-1]["step"] == "done" for e in (ea, eb, ec))
    assert tiny_sem._value == 1 and appmod._gen_waiting == []


@pytest.mark.parametrize("ar", [False, True])
def test_queue_timeout_is_busy_refunds_and_never_starts(tiny_sem, sb, monkeypatch, ar):
    _fake_llm(monkeypatch)
    sb.counts = {k: 1 for k in _keys()}
    charge = appmod._Charge(ip=IP, dev=DEV, fair_keys=tuple(_keys()))
    tiny_sem.acquire()                                         # somebody else is generating
    try:
        evs = _events(appmod._stream_text_as_sse(TEXT, "ar" if ar else "en", "x", "text", charge=charge)())
    finally:
        tiny_sem.release()
    assert evs[-1]["code"] == "busy" and evs[-1]["retry_after_s"] > 0 and evs[-1]["error"]
    assert _has_arabic(evs[-1]["error"]) is ar
    assert all(e.get("step") == "queued" for e in evs[:-1]) and len(evs) >= 2
    assert not any(e.get("step") in ("extract", "overview", "done") for e in evs)
    assert sb.counts == {k: 0 for k in _keys()} and sb.names("anon_refund") == _keys()
    assert tiny_sem._value == 1 and appmod._gen_waiting == []


def test_no_wait_configured_means_an_immediate_busy(tiny_sem, sb, monkeypatch):
    monkeypatch.setattr(appmod, "GEN_QUEUE_WAIT_S", 0)
    _fake_llm(monkeypatch)
    sb.counts = {k: 1 for k in _keys()}
    charge = appmod._Charge(fair_keys=tuple(_keys()))
    tiny_sem.acquire()
    try:
        evs = _events(appmod._stream_text_as_sse(TEXT, "en", "x", "text", charge=charge)())
    finally:
        tiny_sem.release()
    assert [e.get("code") for e in evs] == ["busy"]            # no 'queued' events at all
    assert sb.counts == {k: 0 for k in _keys()}


def test_slot_is_released_after_an_exception(tiny_sem, monkeypatch):
    _fake_llm(monkeypatch, pass1_raises=True)
    evs = _events(appmod._stream_text_as_sse(TEXT, "en", "x", "text")())
    assert "error" in evs[-1] and tiny_sem._value == 1
    # …and again, so a leaked slot would show up as 'busy' here
    evs = _events(appmod._stream_text_as_sse(TEXT, "en", "x", "text")())
    assert "error" in evs[-1] and evs[-1].get("code") != "busy"


def test_slot_is_released_after_success_and_hollow_guides(tiny_sem, monkeypatch):
    _fake_llm(monkeypatch)
    assert _events(appmod._stream_text_as_sse(TEXT, "en", "x", "text")())[-1]["step"] == "done"
    assert tiny_sem._value == 1
    _fake_llm(monkeypatch, bullets=False)
    assert _events(appmod._stream_text_as_sse(TEXT, "en", "x", "text")())[-1]["code"] == "no_notes"
    assert tiny_sem._value == 1


def test_slot_is_released_when_the_client_disconnects_mid_generation(tiny_sem, monkeypatch):
    _fake_llm(monkeypatch)
    gen = appmod._stream_text_as_sse(TEXT, "en", "x", "text")()
    next(gen)
    assert tiny_sem._value == 0                                # held while generating
    gen.close()
    assert tiny_sem._value == 1
    gen.close()
    assert tiny_sem._value == 1                                # exactly once: BoundedSemaphore would raise


def test_disconnect_while_waiting_leaks_neither_slot_nor_place_in_line(tiny_sem, sb, monkeypatch):
    _fake_llm(monkeypatch)
    sb.counts = {k: 1 for k in _keys()}
    charge = appmod._Charge(fair_keys=tuple(_keys()))
    tiny_sem.acquire()
    try:
        gen = appmod._stream_text_as_sse(TEXT, "en", "x", "text", charge=charge)()
        assert json.loads(next(gen)[len("data: "):])["step"] == "queued"
        assert len(appmod._gen_waiting) == 1
        gen.close()                                            # the visitor gave up
        assert appmod._gen_waiting == []
        assert tiny_sem._value == 0                            # still the other request's slot
        assert sb.counts == {k: 0 for k in _keys()}            # and their units came back
    finally:
        tiny_sem.release()
    assert tiny_sem._value == 1


def test_gen_slot_release_is_idempotent():
    sem = threading.BoundedSemaphore(2)
    sem.acquire()
    slot = appmod._GenSlot(sem)
    assert slot.release() is True and slot.release() is False
    assert sem._value == 2


def test_the_semaphore_wait_does_not_swallow_the_slot_it_wins(tiny_sem):
    """_gen_slot_acquire takes the slot on the way out: the caller owns it."""
    gen = appmod._gen_slot_acquire()
    with pytest.raises(StopIteration) as stop:
        next(gen)
    slot = stop.value.value
    assert isinstance(slot, appmod._GenSlot) and tiny_sem._value == 0
    slot.release()
    assert tiny_sem._value == 1


def test_endpoint_waits_in_line_and_then_serves(client, auth_on, sb, llm, tiny_sem, monkeypatch):
    monkeypatch.setattr(appmod, "GEN_QUEUE_WAIT_S", 10.0)
    tiny_sem.acquire()
    threading.Timer(0.3, tiny_sem.release).start()             # the other generation finishes
    evs = _sse_events(_post_text(client))
    assert evs[0]["step"] == "queued" and evs[0]["position"] == 1
    assert evs[-1]["step"] == "done"
    assert sb.counts == {k: 1 for k in _keys()}                # charged once, kept
    assert _wait_for(lambda: tiny_sem._value == 1)


@pytest.mark.parametrize("name,post", ENDPOINTS, ids=[e[0] for e in ENDPOINTS])
def test_endpoint_busy_after_the_wait_refunds(client, auth_on, sb, llm, tiny_sem, monkeypatch, name, post):
    monkeypatch.setattr(appmod, "_fetch_captions", lambda vid: (_ for _ in ()).throw(AssertionError("heavy phase ran")))
    tiny_sem.acquire()
    try:
        r = post(client)
        evs = _sse_events(r)
    finally:
        tiny_sem.release()
    assert r.status_code == 200 and evs[-1]["code"] == "busy"      # in-stream: the response had begun
    assert any(e.get("step") == "queued" for e in evs)
    assert sb.counts == {k: 0 for k in _keys()}
    assert sb.names("anon_refund") == _keys()


def test_youtube_takes_exactly_one_slot_and_gives_it_back(client, auth_on, sb, llm, tiny_sem, monkeypatch):
    # With ONE slot, a youtube request that took a second one (its own + the text
    # pipeline's) would deadlock into 'busy'. It must simply finish.
    evs = _sse_events(_post_youtube(client))
    assert evs[-1]["step"] == "done" and not any(e.get("step") == "queued" for e in evs)
    assert tiny_sem._value == 1
    # the heavy caption phase is inside the slot too, and a failure there releases it
    monkeypatch.setattr(appmod, "_fetch_captions", lambda vid: (_ for _ in ()).throw(RuntimeError("boom")))
    evs = _sse_events(_post_youtube(client))
    assert "error" in evs[-1] and evs[-1].get("code") != "busy"
    assert tiny_sem._value == 1
    assert sb.counts == {k: 1 for k in _keys()}                # first run kept, second refunded


def test_youtube_disconnect_during_captions_releases_slot_and_refunds(client, auth_on, sb, llm, tiny_sem):
    r = _post_youtube(client)
    next(iter(r.response))
    r.close()
    assert tiny_sem._value == 1 and sb.counts == {k: 0 for k in _keys()}


def test_the_demo_takes_a_slot_and_only_the_global_unit(client, auth_on, sb, llm, tiny_sem):
    evs = _sse_events(client.post("/api/summarize-text", json={"demo": True, "language": "en"}))
    assert evs[-1]["step"] == "done" and tiny_sem._value == 1
    assert sb.calls == [("anon_consume", "fair:global")]       # no device, IP or user counter


def test_queue_messages_are_bilingual(tiny_sem, monkeypatch):
    _fake_llm(monkeypatch)
    tiny_sem.acquire()
    try:
        en = _events(appmod._stream_text_as_sse(TEXT, "en", "x", "text")())
        ar = _events(appmod._stream_text_as_sse(TEXT, "en", "x", "text", ar=True)())
        # no explicit `ar`: the guide's own language decides
        guess = _events(appmod._stream_text_as_sse(TEXT, "ar", "x", "text")())
    finally:
        tiny_sem.release()
    assert not _has_arabic(en[0]["msg"]) and "number 1" in en[0]["msg"]
    assert _has_arabic(ar[0]["msg"]) and _has_arabic(ar[-1]["error"])
    assert _has_arabic(guess[0]["msg"])


# ── F. RATE_SUMMARIZE_PER_MIN ────────────────────────────────────────────────────
@pytest.mark.parametrize("path", ["/api/summarize-text", "/api/youtube"])
def test_rate_limit_comes_from_the_knob_per_endpoint(client, monkeypatch, path):
    monkeypatch.setattr(appmod, "RATE_SUMMARIZE_PER_MIN", 3)
    codes = [client.post(path, json={}).status_code for _ in range(5)]
    assert codes == [400, 400, 400, 429, 429]                  # 400 = got past the limiter


def test_rate_limit_on_the_file_endpoint(client, monkeypatch):
    monkeypatch.setattr(appmod, "RATE_SUMMARIZE_PER_MIN", 2)
    codes = [client.post("/api/summarize-stream", data={}, content_type="multipart/form-data").status_code
             for _ in range(4)]
    assert codes == [400, 400, 429, 429]


def test_default_rate_limit_lets_a_whole_class_behind_one_ip_through(client):
    assert appmod.RATE_SUMMARIZE_PER_MIN == 30
    codes = [client.post("/api/summarize-text", json={}).status_code for _ in range(31)]
    assert codes[:30] == [400] * 30 and codes[30] == 429       # the old hard-coded 5 stopped at 6


# ── G. config, auth/me, checkout, referral ───────────────────────────────────────
def test_config_reports_free_mode_and_the_allowances(client):
    d = client.get("/api/config").get_json()
    assert d["free_mode"] is True
    # device_daily is kept only for an older cached client: it mirrors the free guides before sign-in
    assert d["fair_use"] == {"anon_free_uses": 3, "user_daily": 40, "device_daily": 3}
    assert d["anon_free_limit"] == 3 and d["anon_remaining"] == 3 and d["signin_after"] == 3
    for k in ("supabase_url", "supabase_anon_key", "stripe_publishable_key", "auth_enabled"):
        assert k in d


def test_config_anon_remaining_is_the_free_guides_left_on_the_device(client, sb):
    sb.counts[f"gate:dev:{DEV}"] = 2
    d = client.get("/api/config", headers={"X-Device-Id": DEV}).get_json()
    assert d["anon_remaining"] == 1 and d["anon_free_limit"] == 3
    assert sb.calls == [("anon_remaining", f"gate:dev:{DEV}")]           # read-only: nothing consumed


def test_config_never_waits_on_a_slow_db_in_free_mode(client, monkeypatch):
    monkeypatch.setattr(appmod, "_get_sb", lambda: MagicMock())
    monkeypatch.setattr(appmod, "_anon_gate_remaining", lambda gate: time.sleep(2.5) or 0)
    t0 = time.time()
    d = client.get("/api/config", headers={"X-Device-Id": DEV}).get_json()
    assert time.time() - t0 < 2.2 and d["anon_remaining"] == 3           # falls back to the full allowance


def test_config_knobs_show_up(client, monkeypatch):
    monkeypatch.setattr(appmod, "ANON_FREE_USES", 7)
    monkeypatch.setattr(appmod, "FAIR_USER_DAILY", 55)
    d = client.get("/api/config").get_json()
    assert d["fair_use"] == {"anon_free_uses": 7, "user_daily": 55, "device_daily": 7}
    assert d["anon_free_limit"] == 7 and d["signin_after"] == 7


def test_auth_me_adds_free_mode_and_keeps_every_field(client, auth_on, monkeypatch):
    row = {"id": "user-1", "email": "s@x.com", "name": "S", "avatar_url": "a",
           "tokens_remaining": 2, "tokens_month": time.strftime("%Y-%m", time.gmtime()),
           "subscription_status": "free", "subscription_period_end": None,
           "stripe_customer_id": "cus_1", "referral_code": "ABC"}
    monkeypatch.setattr(appmod, "_get_user", lambda uid: dict(row))
    monkeypatch.setattr(appmod, "_get_sb", lambda: MagicMock())
    d = client.get("/api/auth/me", headers={"Authorization": f"Bearer {_tok()}"}).get_json()
    assert d["free_mode"] is True
    for k in ("id", "email", "name", "avatar_url", "tokens_remaining", "plan", "subscription_status",
              "subscription_period_end", "has_billing", "referral_code"):
        assert k in d
    assert d["has_billing"] is True and d["referral_code"] == "ABC"


def test_auth_me_dev_mode_has_free_mode_too(client):
    assert client.get("/api/auth/me").get_json()["free_mode"] is True


def _stripe_double(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(appmod, "_stripe", fake)
    monkeypatch.setattr(appmod, "STRIPE_PRICE_ID", "price_test")
    monkeypatch.setattr(appmod, "_get_user", lambda uid: {"email": "s@x.com", "stripe_customer_id": "cus_1",
                                                          "subscription_status": "active"})
    monkeypatch.setattr(appmod, "_get_sb", lambda: MagicMock())
    return fake


def test_checkout_is_gone_in_free_mode(client, monkeypatch):
    fake = _stripe_double(monkeypatch)
    r = client.post("/api/stripe/checkout")
    assert r.status_code == 410
    assert r.get_json() == {"error": "Alimne is free now - no subscription needed.", "code": "free_now"}
    assert not fake.mock_calls                                  # not one Stripe call, no session
    ar = client.post("/api/stripe/checkout", headers={"Accept-Language": "ar"}).get_json()
    assert ar["code"] == "free_now" and _has_arabic(ar["error"])


def test_checkout_is_gone_for_signed_out_callers_too(client, auth_on, monkeypatch):
    fake = _stripe_double(monkeypatch)
    assert client.post("/api/stripe/checkout").status_code == 410
    assert not fake.mock_calls


def test_portal_and_webhook_are_untouched_in_free_mode(client, monkeypatch):
    fake = _stripe_double(monkeypatch)
    fake.billing_portal.Session.create.return_value = SimpleNamespace(url="https://billing.stripe.com/p/x")
    r = client.post("/api/stripe/portal")
    assert r.status_code == 200 and r.get_json()["url"] == "https://billing.stripe.com/p/x"
    # an existing subscriber's cancellation still reaches the users table
    class _Evt:                                                 # stripe v13: not a dict
        pass
    fake.Webhook.construct_event.return_value = _Evt()
    fake.error = SimpleNamespace(SignatureVerificationError=type("SigErr", (Exception,), {}))
    sb = MagicMock()
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)
    event = {"id": "evt_free_mode_cancel_1", "type": "customer.subscription.deleted",
             "data": {"object": {"id": "sub_1", "customer": "cus_1", "status": "canceled"}}}
    w = client.post("/api/stripe/webhook", data=json.dumps(event).encode(), headers={"Stripe-Signature": "s"})
    assert w.status_code == 200
    assert sb.table.return_value.update.call_args[0][0]["subscription_status"] == "canceled"


def test_referral_token_reward_is_not_awarded_in_free_mode(monkeypatch):
    added = []
    monkeypatch.setattr(appmod, "_add_tokens", lambda *a, **k: added.append(a))
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = \
        SimpleNamespace(data={"referred_by": "referrer-1", "referral_paid": False})
    appmod._award_referral("new-sub", sb)
    assert added == [] and not sb.table.called                 # nothing awarded, nothing marked paid


def test_referral_stats_do_not_promise_tokens_in_free_mode(client, auth_on, monkeypatch):
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[{"referral_paid": True}, {"referral_paid": True}, {"referral_paid": False}])
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)
    d = client.get("/api/referral/stats", headers={"Authorization": f"Bearer {_tok()}"}).get_json()
    assert d == {"total": 3, "paid": 2, "tokens_earned": 0}


def test_referral_apply_still_records_the_referral(client, auth_on, monkeypatch):
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.neq.return_value.execute.return_value = \
        SimpleNamespace(data=[{"id": "referrer-1"}])
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)
    r = client.post("/api/referral/apply", json={"code": "abc"}, headers={"Authorization": f"Bearer {_tok()}"})
    assert r.get_json() == {"success": True}
    sb.table.return_value.update.assert_called_with({"referred_by": "referrer-1"})


# ── H. ALIMNE_FREE_MODE=0 restores the old system, exactly ───────────────────────
@pytest.fixture
def legacy(legacy_tokens):
    return None


def test_legacy_anonymous_still_gets_402_and_never_touches_fair_use(client, auth_on, sb, llm, legacy, monkeypatch):
    monkeypatch.setattr(appmod, "_anon_durable_consume", lambda dev: (False, 0))
    r = _post_text(client)
    assert r.status_code == 402
    assert r.get_json() == {"error": "You've used your free previews. Sign up free to get more.",
                            "code": "signin_for_more", "tokens_remaining": 0}
    assert sb.calls == []                                      # no fair-use RPC in the old system


def test_legacy_signed_in_spends_one_token_and_reports_the_balance(client, auth_on, sb, llm, legacy, monkeypatch):
    spent = []
    monkeypatch.setattr(appmod, "_consume_token", lambda uid: spent.append(uid) or (True, 2, ""))
    for post in (_post_text, _post_file):
        evs = _sse_events(post(client, headers={"Authorization": f"Bearer {_tok('user-1')}"}))
        assert evs[-1]["step"] == "done" and evs[-1]["tokens_remaining"] == 2
    assert spent == ["user-1", "user-1"] and sb.calls == []
    # the file endpoint's 'done' keeps its exact old key order
    assert list(evs[-1])[:4] == ["step", "job_id", "tokens_remaining", "sections"]


def test_legacy_no_tokens_is_still_402(client, auth_on, legacy, monkeypatch):
    monkeypatch.setattr(appmod, "_consume_token", lambda uid: (False, 0, "no_tokens"))
    r = _post_text(client, headers={"Authorization": f"Bearer {_tok()}"})
    assert r.status_code == 402 and r.get_json()["code"] == "no_tokens"


def test_legacy_charge_is_the_old_charge(legacy, monkeypatch):
    monkeypatch.setattr(appmod, "_consume_token", lambda uid: (True, 5, ""))
    with appmod.app.test_request_context("/"):
        charge, err = appmod._charge_credit("user-1", appmod.request)
    assert err is None and charge.fair_keys is None and charge.tok_left == 5 and charge.uid == "user-1"


def test_legacy_has_no_queue_no_busy_and_leaves_the_semaphore_alone(client, auth_on, llm, legacy, tiny_sem, monkeypatch):
    monkeypatch.setattr(appmod, "_anon_durable_consume", lambda dev: (True, 1))
    tiny_sem.acquire()                                         # "full" — must make no difference
    try:
        evs = _sse_events(_post_text(client))
    finally:
        tiny_sem.release()
    assert evs[-1]["step"] == "done" and not any(e.get("step") == "queued" for e in evs)


def test_legacy_rate_limit_is_the_old_hard_coded_5(client, legacy, monkeypatch):
    monkeypatch.setattr(appmod, "RATE_SUMMARIZE_PER_MIN", 30)  # the knob is ignored in the old system
    codes = [client.post("/api/summarize-text", json={}).status_code for _ in range(7)]
    assert codes == [400] * 5 + [429] * 2


def test_legacy_checkout_is_not_gone(client, legacy, monkeypatch):
    monkeypatch.setattr(appmod, "_stripe", None)
    assert client.post("/api/stripe/checkout").status_code == 503      # the old 'not configured', not 410


def test_legacy_config_keeps_the_old_numbers(client, legacy):
    d = client.get("/api/config").get_json()
    assert d["free_mode"] is False
    assert d["anon_free_limit"] == appmod.ANON_FREE_LIMIT
    assert d["fair_use"] == {"device_daily": 10, "user_daily": 40} and "signin_after" not in d


def test_legacy_referral_reward_is_still_awarded(legacy, monkeypatch):
    added = []
    monkeypatch.setattr(appmod, "_add_tokens", lambda sb, uid, n: added.append((uid, n)))
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = \
        SimpleNamespace(data={"referred_by": "referrer-1", "referral_paid": False})
    appmod._award_referral("new-sub", sb)
    assert added == [("referrer-1", 10)]


def test_legacy_no_notes_text_is_unchanged(legacy):
    ev = appmod._gen_error_event(appmod._NoNotes("x"), SimpleNamespace(refunded=True))
    assert ev == {"error": appmod._NO_NOTES_REFUNDED, "code": "no_notes", "refunded": True}


# ── I. the env knobs ─────────────────────────────────────────────────────────────
def test_env_num_parsing():
    f = appmod._env_num
    os.environ["_T_KNOB"] = " 12 "
    try:
        assert f("_T_KNOB", 5) == 12
        os.environ["_T_KNOB"] = "abc"
        assert f("_T_KNOB", 5) == 5
        os.environ["_T_KNOB"] = "-3"
        assert f("_T_KNOB", 5) == 5
        os.environ["_T_KNOB"] = "0"
        assert f("_T_KNOB", 5, minimum=1) == 5 and f("_T_KNOB", 5) == 0
        os.environ["_T_KNOB"] = "2.5"
        assert f("_T_KNOB", 5) == 5 and f("_T_KNOB", 5.0, cast=float) == 2.5
        os.environ["_T_KNOB"] = "  "
        assert f("_T_KNOB", 5) == 5
    finally:
        del os.environ["_T_KNOB"]
    assert f("_T_KNOB_NOT_SET", 7) == 7


_KNOB_PROBE = r"""
import json, os, sys
sys.path.insert(0, os.environ["APP_ROOT"]); os.chdir(os.environ["APP_ROOT"])
import app as A
print(json.dumps({k: getattr(A, k) for k in (
    "FREE_MODE", "FAIR_DEVICE_DAILY", "FAIR_IP_DAILY", "FAIR_USER_DAILY", "FAIR_GLOBAL_DAILY",
    "FAIR_ANON_SHARE_PCT", "FAIR_CHAT_DAILY", "WEB_THREADS", "GEN_MAX_CONCURRENT", "GEN_MAX_WAITING",
    "GEN_QUEUE_WAIT_S", "RATE_SUMMARIZE_PER_MIN", "RATE_PRECHECK_PER_MIN",
    "ANON_FREE_USES", "ANON_USES_WINDOW_HOURS", "FAIR_ANON_IP_DAILY")}))
"""


def _knobs(**env):
    base = {k: v for k, v in os.environ.items()
            if k not in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "GROQ_API_KEY", "RENDER", "PRODUCTION",
                         "SUPABASE_URL", "SUPABASE_JWT_SECRET", "SUPABASE_SERVICE_ROLE_KEY")}
    base.update(APP_ROOT=ROOT, **env)
    out = subprocess.run([sys.executable, "-c", _KNOB_PROBE], env=base, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_knob_defaults_and_overrides_at_import():
    assert _knobs() == {"FREE_MODE": True, "FAIR_DEVICE_DAILY": 10, "FAIR_IP_DAILY": 250, "FAIR_USER_DAILY": 40,
                        "FAIR_GLOBAL_DAILY": 2000, "FAIR_ANON_SHARE_PCT": 60, "FAIR_CHAT_DAILY": 100,
                        "WEB_THREADS": 4, "GEN_MAX_CONCURRENT": 2, "GEN_MAX_WAITING": 1, "GEN_QUEUE_WAIT_S": 45.0,
                        "RATE_SUMMARIZE_PER_MIN": 30, "RATE_PRECHECK_PER_MIN": 5,
                        "ANON_FREE_USES": 3, "ANON_USES_WINDOW_HOURS": 87600, "FAIR_ANON_IP_DAILY": 10}
    k = _knobs(ALIMNE_FREE_MODE="0", FAIR_DEVICE_DAILY="7", FAIR_IP_DAILY="99", FAIR_USER_DAILY="5",
               FAIR_GLOBAL_DAILY="123", FAIR_ANON_SHARE_PCT="40", FAIR_CHAT_DAILY="9", WEB_THREADS="8",
               GEN_MAX_CONCURRENT="5", GEN_MAX_WAITING="2", GEN_QUEUE_WAIT_S="9.5", RATE_SUMMARIZE_PER_MIN="12",
               RATE_PRECHECK_PER_MIN="3", ANON_FREE_USES="5", ANON_USES_WINDOW_HOURS="720", FAIR_ANON_IP_DAILY="12")
    assert k == {"FREE_MODE": False, "FAIR_DEVICE_DAILY": 7, "FAIR_IP_DAILY": 99, "FAIR_USER_DAILY": 5,
                 "FAIR_GLOBAL_DAILY": 123, "FAIR_ANON_SHARE_PCT": 40, "FAIR_CHAT_DAILY": 9, "WEB_THREADS": 8,
                 "GEN_MAX_CONCURRENT": 5, "GEN_MAX_WAITING": 2, "GEN_QUEUE_WAIT_S": 9.5,
                 "RATE_SUMMARIZE_PER_MIN": 12, "RATE_PRECHECK_PER_MIN": 3,
                 "ANON_FREE_USES": 5, "ANON_USES_WINDOW_HOURS": 720, "FAIR_ANON_IP_DAILY": 12}
    # nonsense falls back to the defaults; a zero slot count / rate / thread count would lock everyone out,
    # and a zero-hour gate window would hand the free guides back at once
    k = _knobs(ALIMNE_FREE_MODE="1", FAIR_DEVICE_DAILY="lots", GEN_MAX_CONCURRENT="0", GEN_QUEUE_WAIT_S="soon",
               RATE_SUMMARIZE_PER_MIN="0", WEB_THREADS="1", RATE_PRECHECK_PER_MIN="0", FAIR_ANON_SHARE_PCT="0",
               ANON_FREE_USES="-2", ANON_USES_WINDOW_HOURS="0", FAIR_ANON_IP_DAILY="many")
    assert k["FREE_MODE"] is True and k["FAIR_DEVICE_DAILY"] == 10 and k["GEN_MAX_CONCURRENT"] == 2
    assert k["GEN_QUEUE_WAIT_S"] == 45.0 and k["RATE_SUMMARIZE_PER_MIN"] == 30
    assert k["WEB_THREADS"] == 4 and k["RATE_PRECHECK_PER_MIN"] == 5 and k["FAIR_ANON_SHARE_PCT"] == 60
    assert (k["ANON_FREE_USES"], k["ANON_USES_WINDOW_HOURS"], k["FAIR_ANON_IP_DAILY"]) == (3, 87600, 10)


def test_the_free_mode_code_adds_no_import_time_threads_or_lazy_imports():
    import re
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    start = src.index("# ── Free mode: fair use instead of tokens")
    block = src[start:src.index("def _refund_credit", start)]
    assert "Thread(" not in block and "submit(" not in block and "\nimport " not in block
    assert "threading.Thread" not in src[src.index("_gen_sem          ="):src.index("_gen_sem          =") + 400]


# ══════════════════════════════════════════════════════════════════════════════════
# J. Launch-review hardening. Each test below pins one thing a review of the free
#    launch found: free generations a script could get by closing the socket, the
#    unmetered demo and chat, the generation line that held every web thread, the
#    shared global counter, and a few cheap-to-abuse paths.
# ══════════════════════════════════════════════════════════════════════════════════
import uuid
from concurrent.futures import ThreadPoolExecutor


def _charged(sb_fake):
    """A real charge for the fixed device, taken through the real counters."""
    with appmod.app.test_request_context("/", headers={"X-Device-Id": DEV}):
        charge, err = appmod._charge_credit(None, appmod.request)
    assert err is None
    return charge


def _ev(chunk):
    return json.loads(chunk[len("data: "):].strip())


def _close_at(gen, step, msg_prefix=None):
    """Read events until `step` (and, if given, a message prefix) arrives, then drop the
    stream: the client socket is gone. Returns that event."""
    for chunk in gen:
        ev = _ev(chunk)
        if ev.get("step") == step and (msg_prefix is None or str(ev.get("msg", "")).startswith(msg_prefix)):
            gen.close()
            return ev
    raise AssertionError(f"step {step!r} never came")


def _store_job(language="en"):
    jid = uuid.uuid4().hex
    appmod.store_job(jid, b"%PDF-1.4 t", "# T\n", {"title": "T", "language": language,
                     "sections": [{"title": "S", "bullets": ["fact one"]}]}, None, "g_study_guide.pdf")
    return jid


def _read_until(resp, marker):
    """Read a streamed response chunk by chunk until `marker` (bytes) shows up."""
    for chunk in resp.response:
        raw = chunk if isinstance(chunk, bytes) else chunk.encode()
        if marker in raw:
            return True
    return False


# ── J1. closing the socket after the AI work started must not refund it ──────────
@pytest.mark.parametrize("step,msg", [("section", None), ("flashcards", None), ("mcq", "Quiz ready"), ("pdf", None)])
def test_disconnect_after_the_ai_work_started_keeps_the_units_spent(sb, monkeypatch, step, msg):
    _fake_llm(monkeypatch)
    charge = _charged(sb)
    gen = appmod._stream_text_as_sse(TEXT, "en", "x", "text", charge=charge)()
    _close_at(gen, step, msg)                                   # the paid passes ran; now the client leaves
    assert sb.counts == {k: 1 for k in _keys()}
    assert sb.names("anon_refund") == []


@pytest.mark.parametrize("step", ["extract", "overview"])
def test_disconnect_before_any_ai_work_still_refunds(sb, monkeypatch, step):
    _fake_llm(monkeypatch)
    charge = _charged(sb)
    gen = appmod._stream_text_as_sse(TEXT, "en", "x", "text", charge=charge)()
    _close_at(gen, step)                                        # nothing has cost anything yet
    assert sb.counts == {k: 0 for k in _keys()} and sb.names("anon_refund") == _keys()


def test_a_script_that_closes_the_socket_after_every_paid_run_hits_the_cap(client, auth_on, sb, monkeypatch):
    """The reviewed exploit: read until 'Quiz ready', drop the socket, repeat. The counters
    must keep counting, so the sign-in gate stops it exactly where it stops a normal client."""
    _fake_llm(monkeypatch)
    for _ in range(appmod.ANON_FREE_USES):
        r = _post_text(client)
        assert _read_until(r, b"Quiz ready")
        r.close()
    assert sb.counts[f"gate:dev:{DEV}"] == appmod.ANON_FREE_USES
    assert sb.counts["fair:global"] == appmod.ANON_FREE_USES
    r = _post_text(client)
    assert r.status_code == 401 and r.get_json()["code"] == "signin_required"


def test_file_stream_disconnect_after_paid_work_keeps_the_units(client, auth_on, sb, llm):
    r = _post_file(client)
    assert _read_until(r, b'"step": "pdf"')
    r.close()
    assert sb.counts == {k: 1 for k in _keys()} and sb.names("anon_refund") == []


def test_youtube_disconnect_after_the_whisper_call_keeps_the_units(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(appmod, "_fetch_captions", lambda vid: (_ for _ in ()).throw(ValueError("no_captions")))
    whisper = []
    monkeypatch.setattr(appmod, "_transcribe_with_whisper", lambda vid: whisper.append(vid) or "lecture words " * 50)
    r = _post_youtube(client)
    assert _read_until(r, b"Audio transcribed")
    r.close()
    assert whisper == ["dQw4w9WgXcQ"]
    assert sb.counts == {k: 1 for k in _keys()} and sb.names("anon_refund") == []


def test_youtube_disconnect_before_the_whisper_call_refunds(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(appmod, "_fetch_captions", lambda vid: (_ for _ in ()).throw(ValueError("no_captions")))
    whisper = []
    monkeypatch.setattr(appmod, "_transcribe_with_whisper", lambda vid: whisper.append(vid) or "x " * 50)
    r = _post_youtube(client)
    assert _read_until(r, b"downloading audio")
    r.close()                                                   # the client left BEFORE the paid call
    assert whisper == [] and sb.counts == {k: 0 for k in _keys()}


def test_a_server_side_failure_after_paid_work_still_refunds(client, auth_on, sb, monkeypatch):
    # the visitor did nothing wrong: an exception (or a hollow guide) gives the units back
    _fake_llm(monkeypatch, bullets=False)
    assert _sse_events(_post_text(client))[-1]["code"] == "no_notes"
    assert sb.counts == {k: 0 for k in _keys()}


def test_charge_abandon_unit_behaviour(sb, monkeypatch):
    refunds = []
    monkeypatch.setattr(appmod, "_refund_token", lambda uid: refunds.append(uid) or True)
    # token mode keeps its old behaviour exactly: a disconnect always refunds
    old = appmod._Charge(uid="u1")
    old.begin_work()
    assert old.abandon() is True and refunds == ["u1"]
    # free mode: before the work -> refund; after -> kept, and a later refund() is a no-op
    sb.counts = {"fair:global": 1}
    early = appmod._Charge(fair_keys=("fair:global",))
    assert early.abandon() is True and sb.counts == {"fair:global": 0}
    sb.counts = {"fair:global": 1}
    late = appmod._Charge(fair_keys=("fair:global",))
    late.begin_work()
    assert late.abandon() is False and late.refund() is False and sb.counts == {"fair:global": 1}


# ── J2. the demo is cached, and a real run is counted against the global budget ──
def _post_demo(client, **body):
    return client.post("/api/summarize-text", json={"demo": True, "language": "en", **body},
                       headers={"X-Device-Id": DEV})


@pytest.fixture
def ai_calls(monkeypatch):
    calls = []
    inner = appmod._call_ollama
    def counting(*a, **k):
        calls.append(1)
        return inner(*a, **k)
    monkeypatch.setattr(appmod, "_call_ollama", counting)
    return calls


def test_demo_is_made_once_then_served_from_the_cache_at_no_cost(client, auth_on, sb, llm, ai_calls):
    first = _sse_events(_post_demo(client))
    assert first[-1]["step"] == "done"
    n = len(ai_calls)
    assert n >= 4 and sb.counts == {"fair:global": 1}            # the one real run is counted
    for _ in range(3):
        again = _sse_events(_post_demo(client))
        assert again[-1]["step"] == "done"
        assert again[-1]["job_id"] != first[-1]["job_id"]        # a fresh, independent job each time
        assert {k: again[-1][k] for k in ("sections", "keywords", "flashcards", "mcqs")} == \
               {k: first[-1][k] for k in ("sections", "keywords", "flashcards", "mcqs")}
    assert len(ai_calls) == n and sb.counts == {"fair:global": 1}   # zero AI calls, zero units
    job = again[-1]["job_id"]
    g = client.get(f"/api/guide/{job}").get_json()
    assert g["sections"] and g["language"] == "en"
    pdf = client.get(f"/api/download/{job}")
    assert pdf.status_code == 200 and pdf.data[:4] == b"%PDF"
    assert client.post(f"/api/delete/{job}").get_json()["deleted"] is True      # copies are independent jobs
    assert client.get(f"/api/guide/{first[-1]['job_id']}").status_code == 200


def test_each_demo_language_is_made_once(client, auth_on, sb, llm, ai_calls):
    _sse_events(_post_demo(client))
    _sse_events(_post_demo(client, language="ar"))
    assert sb.counts == {"fair:global": 2}
    n = len(ai_calls)
    assert _sse_events(_post_demo(client, language="ar"))[-1]["step"] == "done"
    assert _sse_events(_post_demo(client))[-1]["step"] == "done"
    assert len(ai_calls) == n and sb.counts == {"fair:global": 2}


def test_a_cached_demo_still_works_after_the_breaker_trips(client, auth_on, sb, llm):
    _sse_events(_post_demo(client))
    sb.counts["fair:global"] = 10 ** 6
    r = _post_demo(client)
    assert r.status_code == 200 and _sse_events(r)[-1]["step"] == "done"


@pytest.mark.parametrize("ar", [False, True])
def test_an_uncached_demo_is_refused_once_the_breaker_has_tripped(client, auth_on, sb, llm, monkeypatch, ar):
    monkeypatch.setattr(appmod, "_call_ollama", lambda *a, **k: (_ for _ in ()).throw(AssertionError("paid call")))
    sb.counts["fair:global"] = 10 ** 6
    r = _post_demo(client, language="ar" if ar else "en")
    assert r.status_code == 503 and r.get_json()["code"] == "busy_today"
    assert _has_arabic(r.get_json()["error"]) is ar
    assert sb.counts["fair:global"] == 10 ** 6


def test_a_failed_demo_build_gives_the_unit_back_and_is_not_cached(client, auth_on, sb, monkeypatch):
    _fake_llm(monkeypatch, pass1_raises=True)
    evs = _sse_events(_post_demo(client))
    assert evs[-1]["error"] and sb.counts == {"fair:global": 0}
    assert appmod._demo_cache == {}


def test_a_partial_demo_is_not_cached(client, auth_on, sb, monkeypatch):
    _fake_llm(monkeypatch)
    monkeypatch.setattr(appmod, "pass3_flashcards", lambda g, l, d=None: {"flashcards": []})
    assert _sse_events(_post_demo(client))[-1].get("partial") is True
    assert appmod._demo_cache == {}


def test_the_demo_cache_expires(client, auth_on, sb, llm, monkeypatch):
    _sse_events(_post_demo(client))
    monkeypatch.setattr(appmod, "_DEMO_CACHE_TTL_S", 0)
    _sse_events(_post_demo(client))
    assert sb.counts == {"fair:global": 2}


def test_a_cached_demo_takes_no_slot_and_never_waits(client, auth_on, sb, llm, tiny_sem):
    _sse_events(_post_demo(client))
    tiny_sem.acquire()
    try:
        evs = _sse_events(_post_demo(client))
    finally:
        tiny_sem.release()
    assert evs[-1]["step"] == "done" and not any(e.get("step") == "queued" for e in evs)


def test_an_uncached_demo_with_a_full_house_is_busy_before_anything_is_charged(client, auth_on, sb, llm, tiny_sem, monkeypatch):
    monkeypatch.setattr(appmod, "_GEN_WAIT_MAX", 0)
    tiny_sem.acquire()
    try:
        r = _post_demo(client)
    finally:
        tiny_sem.release()
    assert r.status_code == 503 and r.get_json()["code"] == "busy" and sb.calls == []


def test_the_token_mode_demo_is_unchanged(client, auth_on, sb, llm, legacy_tokens, ai_calls):
    for _ in range(2):
        assert _sse_events(_post_demo(client))[-1]["step"] == "done"
    assert sb.calls == [] and appmod._demo_cache == {}          # no counters, no cache: exactly the old demo
    assert len(ai_calls) >= 8


# ── J3. chat is metered ──────────────────────────────────────────────────────────
def _chat(client, jid, uid="user-7", q="why?", **body):
    return client.post(f"/api/chat/{jid}", json={"question": q, **body},
                       headers={"Authorization": f"Bearer {_tok(uid)}"})


@pytest.fixture
def chat_llm(monkeypatch):
    calls = []
    monkeypatch.setattr(appmod, "_call_ollama", lambda *a, **k: calls.append(1) or {"answer": "because"})
    return calls


def test_chat_has_a_per_user_daily_cap(client, auth_on, sb, chat_llm, monkeypatch):
    monkeypatch.setattr(appmod, "FAIR_CHAT_DAILY", 3)
    jid = _store_job()
    rs = [_chat(client, jid) for _ in range(5)]
    assert [r.status_code for r in rs] == [200, 200, 200, 429, 429] and len(chat_llm) == 3
    assert rs[3].get_json()["code"] == "fair_use_user"
    assert sb.counts["fair:chat:user:user-7"] == 3
    assert _chat(client, jid, uid="user-8").status_code == 200   # another account has its own allowance


def test_chat_default_allowance_is_a_documented_knob():
    assert appmod.FAIR_CHAT_DAILY == 100


def test_chat_has_a_per_user_per_minute_cap(client, auth_on, sb, chat_llm, monkeypatch):
    monkeypatch.setattr(appmod, "_CHAT_USER_PER_MIN", 2)
    jid = _store_job()
    assert [_chat(client, jid).status_code for _ in range(3)] == [200, 200, 429]
    assert _chat(client, jid, uid="user-8").status_code == 200
    assert len(chat_llm) == 3


def test_chat_stops_when_the_global_budget_is_used_up(client, auth_on, sb, chat_llm):
    jid = _store_job()
    sb.counts["fair:global"] = 10 ** 6
    r = _chat(client, jid)
    assert r.status_code == 503 and r.get_json()["code"] == "busy_today" and chat_llm == []
    assert "fair:chat:user:user-7" not in sb.counts            # refused before anything was taken
    ar = _chat(client, jid, language="ar").get_json()
    assert ar["code"] == "busy_today" and _has_arabic(ar["error"])


def test_chat_refusal_is_bilingual(client, auth_on, sb, chat_llm, monkeypatch):
    monkeypatch.setattr(appmod, "FAIR_CHAT_DAILY", 1)
    jid = _store_job()
    assert _chat(client, jid).status_code == 200
    en, ar = _chat(client, jid).get_json(), _chat(client, jid, language="ar").get_json()
    assert not _has_arabic(en["error"]) and _has_arabic(ar["error"]) and en["code"] == ar["code"] == "fair_use_user"


def test_a_failed_chat_gives_its_unit_back(client, auth_on, sb, monkeypatch):
    monkeypatch.setattr(appmod, "_call_ollama", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("groq down")))
    jid = _store_job()
    assert _chat(client, jid).status_code == 500
    assert sb.counts == {"fair:chat:user:user-7": 0}


def test_chat_fails_open_when_the_counter_cannot_be_read(client, auth_on, sb, chat_llm):
    sb.consume_raises["fair:chat:user:user-7"] = RuntimeError("supabase 502")
    assert _chat(client, _store_job()).status_code == 200


def test_chat_input_errors_cost_nothing(client, auth_on, sb, chat_llm):
    jid = _store_job()
    assert _chat(client, jid, q="   ").status_code == 400
    assert _chat(client, uuid.uuid4().hex).status_code == 404
    assert sb.calls == [] and chat_llm == []


def test_token_mode_chat_is_untouched(client, auth_on, sb, chat_llm, legacy_tokens):
    assert _chat(client, _store_job()).status_code == 200 and sb.calls == []


# ── J4. a reserved pool for signed-in users ──────────────────────────────────────
def test_anonymous_requests_are_also_charged_to_the_anonymous_pool(client, auth_on, sb, llm):
    assert _sse_events(_post_text(client))[-1]["step"] == "done"
    assert sb.counts == {f"gate:dev:{DEV}": 1, f"fair:anonip:{IP}": 1, f"fair:ip:{IP}": 1,
                         "fair:global:anon": 1, "fair:global": 1}


def test_signed_in_requests_never_touch_the_anonymous_pool(client, auth_on, sb, llm):
    r = _post_text(client, headers={"Authorization": f"Bearer {_tok('user-7')}"})
    assert _sse_events(r)[-1]["step"] == "done" and "fair:global:anon" not in sb.counts


def test_anonymous_traffic_cannot_use_up_the_signed_in_reserve(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "FAIR_GLOBAL_DAILY", 5)          # the anonymous pool is 60%: 3
    codes = [_status(_post_text(client, device=f"device-aaaa-000{i}")) for i in range(5)]
    assert codes == [200, 200, 200, 401, 401]
    refused = _post_text(client, device="device-aaaa-0009")
    assert refused.get_json()["code"] == "signin_required"            # a free account is the way to the reserve
    assert "create a free account" in refused.get_json()["error"].lower()
    assert sb.counts.get("gate:dev:device-aaaa-0009", 0) == 0         # and the refusal did not burn a free guide
    h = {"Authorization": f"Bearer {_tok('user-7')}"}
    assert [_status(_post_text(client, headers=h)) for _ in range(2)] == [200, 200]   # the reserve is intact
    r = _post_text(client, headers=h)
    assert r.status_code == 503 and r.get_json()["code"] == "busy_today"               # the whole budget is spent


def test_anonymous_pool_share_is_a_percentage_of_the_budget(monkeypatch):
    assert appmod._fair_anon_limit() == 1200                       # 60% of 2000
    monkeypatch.setattr(appmod, "FAIR_GLOBAL_DAILY", 100)
    assert appmod._fair_anon_limit() == 60
    monkeypatch.setattr(appmod, "FAIR_ANON_SHARE_PCT", 100)
    assert appmod._fair_anon_limit() == 100
    monkeypatch.setattr(appmod, "FAIR_GLOBAL_DAILY", 1)
    monkeypatch.setattr(appmod, "FAIR_ANON_SHARE_PCT", 5)
    assert appmod._fair_anon_limit() == 1                          # never zero: anonymous visitors can always try


def test_a_tripped_global_budget_gives_the_anonymous_pool_unit_back(client, auth_on, sb, llm):
    sb.counts["fair:global"] = 10 ** 6
    r = _post_text(client)
    assert r.status_code == 503 and r.get_json()["code"] == "busy_today"
    assert sb.counts.get("fair:global:anon", 0) == 0 and sb.counts[f"gate:dev:{DEV}"] == 0


def test_a_global_counter_logs_when_it_passes_80_percent(sb, caplog):
    sb.counts["fair:global"] = 6
    with caplog.at_level("WARNING", logger="app"):
        appmod._fair_consume("fair:global", 10)                    # 7 of 10
    assert "80%" not in caplog.text
    with caplog.at_level("WARNING", logger="app"):
        appmod._fair_consume("fair:global", 10)                    # 8 of 10
    assert "80%" in caplog.text and "fair:global" in caplog.text
    caplog.clear()
    with caplog.at_level("WARNING", logger="app"):
        sb.counts["fair:dev:abc12345"] = 7
        appmod._fair_consume("fair:dev:abc12345", 10)              # per-device counters stay quiet
    assert "80%" not in caplog.text


# ── J5. admission control: the line can never hold every web thread ──────────────
_LIMITS_PROBE = r"""
import json, os, sys
sys.path.insert(0, os.environ["APP_ROOT"]); os.chdir(os.environ["APP_ROOT"])
import app as A
print(json.dumps({"threads": A.WEB_THREADS, "slots": A._GEN_SLOTS, "wait": A._GEN_WAIT_MAX,
                  "sem": A._gen_sem._value, "legal": A._legal_free_mode(), "free": A.FREE_MODE}))
"""


def _limits(**env):
    base = {k: v for k, v in os.environ.items()
            if k not in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "GROQ_API_KEY", "RENDER", "PRODUCTION",
                         "SUPABASE_URL", "SUPABASE_JWT_SECRET", "SUPABASE_SERVICE_ROLE_KEY")}
    base.update(APP_ROOT=ROOT, **env)
    out = subprocess.run([sys.executable, "-c", _LIMITS_PROBE], env=base, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_default_limits_fit_the_live_four_threads():
    assert appmod.WEB_THREADS == 4
    assert (appmod._GEN_SLOTS, appmod._GEN_WAIT_MAX) == (2, 1)
    assert appmod._GEN_SLOTS + appmod._GEN_WAIT_MAX <= appmod.WEB_THREADS - 1
    assert appmod.GEN_MAX_CONCURRENT == 2 and appmod.GEN_MAX_WAITING == 1


@pytest.mark.parametrize("env", [
    {"GEN_MAX_CONCURRENT": "9", "GEN_MAX_WAITING": "9"},
    {"GEN_MAX_CONCURRENT": "3", "GEN_MAX_WAITING": "5"},
    {"WEB_THREADS": "8", "GEN_MAX_CONCURRENT": "5", "GEN_MAX_WAITING": "9"},
    {"WEB_THREADS": "2", "GEN_MAX_CONCURRENT": "4", "GEN_MAX_WAITING": "4"},
    {"WEB_THREADS": "8"},
], ids=["huge", "3+5", "8-threads", "2-threads", "8-threads-defaults"])
def test_running_plus_waiting_never_reaches_the_thread_count(env):
    k = _limits(**env)
    assert k["slots"] >= 1 and k["slots"] + k["wait"] <= k["threads"] - 1, k
    assert k["sem"] == k["slots"]


def test_a_full_line_is_busy_at_once_instead_of_waiting(tiny_sem, sb, monkeypatch):
    monkeypatch.setattr(appmod, "_GEN_WAIT_MAX", 1)
    monkeypatch.setattr(appmod, "GEN_QUEUE_WAIT_S", 10.0)
    _fake_llm(monkeypatch)
    tiny_sem.acquire()                                           # the slot is taken
    t1, e1 = _spawn(appmod._stream_text_as_sse(TEXT, "en", "a", "text")())
    assert _wait_for(lambda: len(appmod._gen_waiting) == 1)      # the one seat is taken
    sb.counts = {k: 1 for k in _keys()}
    charge = appmod._Charge(fair_keys=tuple(_keys()))
    t0 = time.monotonic()
    evs = _events(appmod._stream_text_as_sse(TEXT, "en", "b", "text", charge=charge)())
    assert [e.get("code") for e in evs] == ["busy"] and time.monotonic() - t0 < 1.0   # no seat: no wait, no 'queued'
    assert sb.counts == {k: 0 for k in _keys()}                  # refunded
    assert len(appmod._gen_waiting) == 1
    tiny_sem.release()
    t1.join(10)
    assert e1[-1]["step"] == "done" and appmod._gen_waiting == []


@pytest.mark.parametrize("name,post", ENDPOINTS, ids=[e[0] for e in ENDPOINTS])
def test_when_every_slot_and_seat_is_taken_the_endpoint_says_busy_before_charging(
        client, auth_on, sb, llm, tiny_sem, monkeypatch, name, post):
    monkeypatch.setattr(appmod, "_GEN_WAIT_MAX", 0)
    monkeypatch.setattr(appmod, "_yt_duration", lambda v: (_ for _ in ()).throw(AssertionError("probed YouTube")))
    tiny_sem.acquire()
    try:
        r = post(client)
        ar = post(client, language="ar")
    finally:
        tiny_sem.release()
    d = r.get_json()
    assert r.status_code == 503 and d["code"] == "busy" and d["retry_after_s"] > 0 and d["error"]
    assert not _has_arabic(d["error"]) and _has_arabic(ar.get_json()["error"])
    assert sb.calls == []                                        # nothing charged, nothing to refund


def test_a_bad_request_is_still_a_400_when_the_house_is_full(client, auth_on, sb, tiny_sem, monkeypatch):
    monkeypatch.setattr(appmod, "_GEN_WAIT_MAX", 0)
    tiny_sem.acquire()
    try:
        r = client.post("/api/summarize-stream", data={"file": (io.BytesIO(b"x"), "evil.exe")},
                        content_type="multipart/form-data", headers={"X-Device-Id": DEV})
    finally:
        tiny_sem.release()
    assert r.status_code == 400


def test_the_line_serves_waiters_in_the_order_they_arrived(monkeypatch):
    """A waiter is told 'number 1' and must BE served first: later arrivals may not pass it."""
    sem = threading.BoundedSemaphore(1)
    monkeypatch.setattr(appmod, "_gen_sem", sem)
    monkeypatch.setattr(appmod, "_GEN_QUEUE_TICK_S", 0.3)
    monkeypatch.setattr(appmod, "GEN_QUEUE_WAIT_S", 10.0)
    monkeypatch.setattr(appmod, "_GEN_WAIT_MAX", 8)
    holder = appmod._gen_slot_acquire()
    with pytest.raises(StopIteration) as stop:
        next(holder)
    held = stop.value.value
    order, lock = [], threading.Lock()

    def waiter(name):
        gen = appmod._gen_slot_acquire()
        try:
            while True:
                next(gen)
        except StopIteration as done:
            slot = done.value
        with lock:
            order.append(name)
        slot.release()

    threads = []
    for i, name in enumerate(("w1", "w2", "w3")):
        t = threading.Thread(target=waiter, args=(name,), daemon=True)
        t.start()
        threads.append(t)
        assert _wait_for(lambda n=i + 1: len(appmod._gen_waiting) == n)
        time.sleep(0.1)
    time.sleep(0.15)                                             # t = 0.35 s: w1's first tick (0.3 s) is behind it
    held.release()
    for t in threads:
        t.join(10)
    assert order == ["w1", "w2", "w3"]
    assert sem._value == 1 and appmod._gen_waiting == []


def test_a_new_arrival_cannot_jump_a_waiting_line(monkeypatch):
    sem = threading.BoundedSemaphore(1)
    monkeypatch.setattr(appmod, "_gen_sem", sem)
    monkeypatch.setattr(appmod, "_GEN_QUEUE_TICK_S", 5.0)
    monkeypatch.setattr(appmod, "GEN_QUEUE_WAIT_S", 10.0)
    monkeypatch.setattr(appmod, "_GEN_WAIT_MAX", 8)
    sem.acquire()
    waiting = appmod._gen_slot_acquire()
    assert _ev(next(waiting))["position"] == 1
    sem.release()                                                # a slot frees up while somebody waits...
    late = appmod._gen_slot_acquire()
    assert _ev(next(late))["position"] == 2                      # ...the newcomer queues behind them
    late.close()
    waiting.close()
    assert appmod._gen_waiting == []


def test_a_full_house_of_generations_leaves_healthz_answerable(auth_on, sb, monkeypatch):
    """The live service is ONE pool of 4 web threads. Two generations run, one waits, a fourth is
    turned away at once: the thread that is left must still answer /healthz (Render restarts a
    service whose health check goes unanswered, and a restart wipes every in-memory guide)."""
    gate = threading.Event()
    _fake_llm(monkeypatch, gate=gate)
    monkeypatch.setattr(appmod, "GEN_QUEUE_WAIT_S", 20.0)

    def generation(i):
        c = appmod.app.test_client()
        r = c.post("/api/summarize-text", json={"text": TEXT, "language": "en"},
                   headers={"X-Device-Id": f"device-aaaa-00{i:02d}"})
        if r.mimetype == "application/json":
            return r.get_json().get("code")
        evs = _sse_events(r)
        return evs[-1].get("code") or evs[-1].get("step")

    def health():
        return appmod.app.test_client().get("/healthz").status_code

    with ThreadPoolExecutor(max_workers=appmod.WEB_THREADS) as pool:
        gens = [pool.submit(generation, i) for i in range(4)]
        assert _wait_for(lambda: appmod._gen_sem._value == 0 and len(appmod._gen_waiting) == 1)
        assert _wait_for(lambda: sum(f.done() for f in gens) == 1)          # the 4th was refused straight away
        t0 = time.monotonic()
        assert pool.submit(health).result(timeout=3) == 200
        assert time.monotonic() - t0 < 1.5
        gate.set()
        results = sorted(f.result(timeout=30) for f in gens)
    assert results == ["busy", "done", "done", "done"]


# ── J6. the pre-slot work gets its own, lower per-IP limit ───────────────────────
def test_youtube_probe_rate_limit_is_its_own_lower_knob(client, monkeypatch):
    assert appmod.RATE_PRECHECK_PER_MIN == 5
    codes = [client.post("/api/youtube", json={}).status_code for _ in range(7)]
    assert codes == [400] * 5 + [429] * 2                       # the yt-dlp probe runs before any slot: it stays at 5/min


def test_url_fetch_has_the_lower_limit_but_pasted_text_keeps_the_class_limit(client, auth_on, sb, monkeypatch):
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    fetched = []
    monkeypatch.setattr(appmod, "_fetch_url_text", lambda u: fetched.append(u) or (_ for _ in ()).throw(ValueError("nope")))
    codes = [client.post("/api/summarize-text", json={"url": "https://example.com/x"},
                         headers={"X-Device-Id": DEV}).status_code for _ in range(7)]
    assert codes == [400] * 5 + [429] * 2 and len(fetched) == 5
    # a paste has no pre-slot network work: the whole class behind one IP can still use it
    monkeypatch.setattr(appmod, "_rate_limit", {})
    assert [client.post("/api/summarize-text", json={}).status_code for _ in range(8)] == [400] * 8


def test_the_lower_limit_never_exceeds_the_general_knob(client, monkeypatch):
    monkeypatch.setattr(appmod, "RATE_SUMMARIZE_PER_MIN", 2)
    assert appmod._precheck_rate_limit() == 2 and appmod.RATE_PRECHECK_PER_MIN == 5


# ── J7. the counters share one time budget ───────────────────────────────────────
def test_the_counters_share_one_time_budget_then_fail_open(sb, monkeypatch, caplog):
    monkeypatch.setattr(appmod, "_FAIR_BUDGET_S", 0.25)
    real = appmod._fair_take
    def slow(key, limit, window_hours=24):
        time.sleep(0.2)
        return real(key, limit, window_hours)
    monkeypatch.setattr(appmod, "_fair_take", slow)
    t0 = time.monotonic()
    with caplog.at_level("WARNING", logger="app"):
        charge = _charged(sb)
    assert time.monotonic() - t0 < 0.7                           # five 0.2 s lookups would take 1.0 s
    assert charge.fair_keys == tuple(_keys()[:2]) and "time budget" in caplog.text


# ── J8. refusals leave a trace the operator can alert on ─────────────────────────
def test_every_fair_use_refusal_is_logged(client, auth_on, sb, llm, caplog):
    sb.counts[f"gate:dev:{DEV}"] = 10 ** 6
    with caplog.at_level("INFO", logger="app"):
        assert _post_text(client).status_code == 401
    assert "fair-use refusal" in caplog.text and "signin_required" in caplog.text
    caplog.clear()
    sb.counts = {"fair:global": 10 ** 6}
    with caplog.at_level("INFO", logger="app"):
        assert _post_text(client).status_code == 503
    assert "fair-use refusal" in caplog.text and "busy_today" in caplog.text


def test_busy_is_logged(tiny_sem, monkeypatch, caplog):
    _fake_llm(monkeypatch)
    tiny_sem.acquire()
    try:
        with caplog.at_level("INFO", logger="app"):
            _events(appmod._stream_text_as_sse(TEXT, "en", "x", "text")())
    finally:
        tiny_sem.release()
    assert "generation busy" in caplog.text


# ── J9. one parser for the free-mode switch ──────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    (None, True), ("", True), ("  ", True), ("1", True), ("true", True), ("yes", True), ("on", True), ("whatever", True),
    ("0", False), (" 0 ", False), ("false", False), ("FALSE", False), ("False", False),
    ("no", False), ("No", False), ("off", False), ("OFF", False),
])
def test_env_switch_parsing(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("_T_SWITCH", raising=False)
    else:
        monkeypatch.setenv("_T_SWITCH", raw)
    assert appmod._env_switch("_T_SWITCH") is expected


def test_the_legal_pages_use_the_same_switch_as_the_credit_logic(monkeypatch):
    monkeypatch.setattr(appmod, "FREE_MODE", False)
    assert appmod._legal_free_mode() is False
    monkeypatch.setattr(appmod, "FREE_MODE", True)
    assert appmod._legal_free_mode() is True


def test_a_natural_off_value_turns_the_credit_logic_and_the_legal_pages_off_together():
    k = _limits(ALIMNE_FREE_MODE="off")
    assert k["free"] is False and k["legal"] is False


# ── J10. IPv6 clients are counted per /64, and the limiter table cannot grow forever ──
def test_ipv6_addresses_are_bucketed_per_64():
    f = appmod._ip_bucket
    assert f("203.0.113.5") == "203.0.113.5"
    assert f("2001:db8:1:2::1") == f("2001:db8:1:2:ffff:ffff:ffff:ffff") == "2001:db8:1:2::/64"
    assert f("2001:db8:1:3::1") != f("2001:db8:1:2::1")
    assert f("::ffff:203.0.113.5") == "203.0.113.5"
    assert f("not-an-ip") == "not-an-ip" and f("unknown") == "unknown"
    assert len(f("x" * 500)) <= 64


def test_rate_limit_buckets_an_ipv6_range_together():
    assert appmod._check_rate_limit("2001:db8:5::1", "t6", 2) is True
    assert appmod._check_rate_limit("2001:db8:5::2", "t6", 2) is True
    assert appmod._check_rate_limit("2001:db8:5:0:aaaa::ffff", "t6", 2) is False     # same /64, third request
    assert appmod._check_rate_limit("2001:db8:6::1", "t6", 2) is True               # another /64
    assert appmod._check_rate_limit("::1", "t6", 1) is True and appmod._check_rate_limit("::1", "t6", 1) is True


def test_the_fair_ip_counter_uses_the_64(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "_client_ip", lambda: "2001:db8:1:2::abcd")
    assert _sse_events(_post_text(client))[-1]["step"] == "done"
    assert "fair:ip:2001:db8:1:2::/64" in sb.counts


def test_the_rate_limit_table_drops_stale_entries(monkeypatch):
    monkeypatch.setattr(appmod, "_RATE_TABLE_MAX", 10)
    old = time.time() - 3600
    table = {f"t:198.51.100.{i}": [old] for i in range(50)}
    monkeypatch.setattr(appmod, "_rate_limit", table)
    assert appmod._check_rate_limit("203.0.113.77", "t", 5) is True
    assert len(table) == 1 and "t:203.0.113.77" in table


# ── J11. sharing is idempotent per guide ─────────────────────────────────────────
def test_sharing_a_guide_twice_returns_the_same_link_and_stores_one_row(client, monkeypatch):
    sbm = MagicMock()
    monkeypatch.setattr(appmod, "_get_sb", lambda: sbm)
    jid = _store_job()
    r1, r2 = client.post(f"/api/share/{jid}"), client.post(f"/api/share/{jid}")
    assert r1.status_code == r2.status_code == 200 and r1.get_json() == r2.get_json()
    assert sbm.table.return_value.insert.call_count == 1
    assert client.post(f"/api/share/{_store_job()}").get_json()["slug"] != r1.get_json()["slug"]
