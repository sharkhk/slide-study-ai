"""
Alimne is FREE (ALIMNE_FREE_MODE, default on): no tokens, no credits, no paywall.
Generation is limited only by FAIR USE — daily counters kept in the existing
anon_consume / anon_refund RPCs under 'fair:*' keys — plus a process-wide cap on
simultaneous generations (a small queue, then 'busy') and a per-IP per-minute rate
limit. This file pins the SERVER side of that:

  A. a generation spends NO token and never answers 402 (anonymous or signed in);
     the demo stays free and unmetered
  B. device / user / ip / global caps refuse with the right code and status, say
     "sign in free" to an anonymous visitor, and roll back the counters already taken
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
    return [f"fair:dev:{dev}", f"fair:ip:{ip}", "fair:global"]


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
    assert sb.counts == {k: 1 for k in _keys()}          # device + ip + global, nothing else
    assert no_tokens == []


@pytest.mark.parametrize("name,post", ENDPOINTS, ids=[e[0] for e in ENDPOINTS])
def test_signed_in_generation_spends_no_token(client, auth_on, sb, llm, no_tokens, name, post):
    r = post(client, headers={"Authorization": f"Bearer {_tok('user-7')}"})
    assert _sse_events(r)[-1]["step"] == "done"
    # the ACCOUNT counter replaces the device one; a signed-in user is never charged both
    assert sb.counts == {"fair:user:user-7": 1, f"fair:ip:{IP}": 1, "fair:global": 1}
    assert no_tokens == []


def test_no_402_is_ever_returned_in_free_mode(client, auth_on, sb, llm, no_tokens):
    # An anonymous device that used to hit 'signin_for_more' after 2 previews now
    # just keeps going until its fair-use allowance, with no 402 on the way.
    for _ in range(appmod.FAIR_DEVICE_DAILY):
        r = _post_text(client)
        assert r.status_code == 200 and _sse_events(r)[-1]["step"] == "done"
    r = _post_text(client)
    assert r.status_code == 429 and r.get_json()["code"] == "fair_use_device"


def test_file_and_text_done_events_keep_their_shape(client, auth_on, sb, llm):
    for post in (_post_text, _post_file):
        done = _sse_events(post(client))[-1]
        assert done["step"] == "done" and appmod._valid_job(done["job_id"])
        assert {"sections", "keywords", "flashcards", "mcqs"} <= set(done)


def test_demo_is_free_and_unmetered(client, auth_on, sb, llm, no_tokens, monkeypatch):
    # Every counter is already exhausted — the demo does not care, and takes no unit.
    for k in _keys():
        sb.counts[k] = 10 ** 6
    before = dict(sb.counts)
    r = client.post("/api/summarize-text", json={"demo": True, "language": "en"}, headers={"X-Device-Id": DEV})
    assert r.status_code == 200
    assert _sse_events(r)[-1]["step"] == "done"
    assert sb.counts == before and sb.calls == [] and no_tokens == []


def test_anonymous_without_a_device_id_is_counted_per_ip_at_the_device_allowance(client, auth_on, sb, llm):
    r = _post_text(client, device=None)
    assert _sse_events(r)[-1]["step"] == "done"
    assert sb.counts == {f"fair:dev:noid-{IP}": 1, f"fair:ip:{IP}": 1, "fair:global": 1}


def test_a_malformed_device_id_counts_as_none(client, auth_on, sb, llm):
    r = _post_text(client, device="bad id!")
    assert _sse_events(r)[-1]["step"] == "done"
    assert f"fair:dev:noid-{IP}" in sb.counts


def test_unknown_ip_is_not_lumped_into_one_shared_counter(monkeypatch, sb):
    monkeypatch.setattr(appmod, "_client_ip", lambda: "unknown")
    with appmod.app.test_request_context("/", headers={"X-Device-Id": DEV}):
        charge, err = appmod._charge_credit(None, appmod.request)
    assert err is None and charge.fair_keys == (f"fair:dev:{DEV}", "fair:global")


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
    ("dev",    "fair_use_device", 429, []),
    ("ip",     "fair_use_ip",     429, ["dev"]),
    ("global", "busy_today",      503, ["dev", "ip"]),
]


@pytest.mark.parametrize("which,code,status,taken_before", ANON_CASES, ids=[c[0] for c in ANON_CASES])
def test_exhausted_counter_refuses_and_rolls_back_the_ones_already_taken(
        client, auth_on, sb, llm, no_tokens, which, code, status, taken_before):
    key = {"dev": f"fair:dev:{DEV}", "ip": f"fair:ip:{IP}", "global": "fair:global"}
    sb.counts[key[which]] = 10 ** 6                          # far past any cap
    r = _post_text(client)
    assert r.status_code == status
    d = r.get_json()
    assert d["code"] == code and d["error"]
    assert d["code"] not in ("no_tokens", "signin_for_more")
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
    sb.counts[f"fair:dev:{DEV}"] = 10 ** 6
    r = post(client)
    assert r.status_code == 429 and r.get_json()["code"] == "fair_use_device"


def _status(resp):
    """Status of a response after its stream was read to the end (a stream that is
    never read is closed at its first event and refunds itself — see D)."""
    resp.get_data()
    return resp.status_code


def test_caps_are_the_configured_knobs(client, auth_on, sb, llm, monkeypatch):
    monkeypatch.setattr(appmod, "FAIR_DEVICE_DAILY", 2)
    assert [_status(_post_text(client)) for _ in range(3)] == [200, 200, 429]
    monkeypatch.setattr(appmod, "FAIR_USER_DAILY", 1)
    h = {"Authorization": f"Bearer {_tok('user-9')}"}
    assert [_status(_post_text(client, headers=h)) for _ in range(2)] == [200, 429]
    sb.counts = {}
    monkeypatch.setattr(appmod, "FAIR_DEVICE_DAILY", 10)
    monkeypatch.setattr(appmod, "FAIR_IP_DAILY", 1)
    assert [_status(_post_text(client, device=f"device-bbbb-000{i}")) for i in range(2)] == [200, 429]
    sb.counts = {}
    monkeypatch.setattr(appmod, "FAIR_IP_DAILY", 250)
    monkeypatch.setattr(appmod, "FAIR_GLOBAL_DAILY", 1)
    r1, r2 = _post_text(client), _post_text(client, device="device-cccc-0001")
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
    assert seen == [("anon_consume", {"p_key": f"fair:dev:{DEV}", "p_limit": 10, "p_window_hours": 24}),
                    ("anon_consume", {"p_key": f"fair:ip:{IP}", "p_limit": 250, "p_window_hours": 24}),
                    ("anon_consume", {"p_key": "fair:global", "p_limit": 2000, "p_window_hours": 24})]
    assert charge.tok_left is None and charge.fair_keys == tuple(_keys())


def test_refusal_text_is_bilingual_and_never_says_unlimited(client, auth_on, sb, llm):
    for code, key in (("fair_use_device", f"fair:dev:{DEV}"), ("fair_use_ip", f"fair:ip:{IP}"),
                      ("busy_today", "fair:global")):
        sb.counts = {key: 10 ** 6}
        en = _post_text(client).get_json()
        ar = _post_text(client, language="ar").get_json()
        assert en["code"] == ar["code"] == code
        assert not _has_arabic(en["error"]) and _has_arabic(ar["error"])
        assert "unlimited" not in en["error"].lower()
    sb.counts = {f"fair:dev:{DEV}": 10 ** 6}
    assert "sign in free" in _post_text(client).get_json()["error"].lower()
    assert "سجّل الدخول" in _post_text(client, language="ar").get_json()["error"]
    # a file upload (multipart) and an Accept-Language header pick the language too
    r = _post_file(client, language="auto", headers={"Accept-Language": "ar"})
    assert r.status_code == 429 and _has_arabic(r.get_json()["error"])


def test_a_signed_in_user_is_not_held_to_the_anonymous_device_cap(client, auth_on, sb, llm):
    sb.counts[f"fair:dev:{DEV}"] = 10 ** 6                    # the device is used up…
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
    assert err is None and charge.fair_keys == tuple(_keys()[:2])
    assert charge.refund() is True
    assert sb.names("anon_refund") == _keys()[:2]             # never the unknown one
    assert sb.counts == {k: 0 for k in _keys()[:2]}


def test_a_failing_counter_does_not_hide_an_exhausted_one(sb):
    sb.consume_raises[f"fair:dev:{DEV}"] = RuntimeError("blip")
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
    assert len(sb.names("anon_refund")) == 3                   # a second close refunds nothing


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


def test_the_demo_takes_a_slot_but_no_counter(client, auth_on, sb, llm, tiny_sem):
    evs = _sse_events(client.post("/api/summarize-text", json={"demo": True, "language": "en"}))
    assert evs[-1]["step"] == "done" and tiny_sem._value == 1 and sb.calls == []


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
    assert d["fair_use"] == {"device_daily": 10, "user_daily": 40}
    assert d["anon_free_limit"] == 10 and d["anon_remaining"] == 10     # kept for older clients
    for k in ("supabase_url", "supabase_anon_key", "stripe_publishable_key", "auth_enabled"):
        assert k in d


def test_config_anon_remaining_is_the_device_daily_remainder(client, sb):
    sb.counts[f"fair:dev:{DEV}"] = 4
    d = client.get("/api/config", headers={"X-Device-Id": DEV}).get_json()
    assert d["anon_remaining"] == 6 and d["anon_free_limit"] == 10
    assert sb.calls == [("anon_remaining", f"fair:dev:{DEV}")]           # read-only: nothing consumed


def test_config_never_waits_on_a_slow_db_in_free_mode(client, monkeypatch):
    monkeypatch.setattr(appmod, "_get_sb", lambda: MagicMock())
    monkeypatch.setattr(appmod, "_fair_device_remaining", lambda dev: time.sleep(2.5) or 0)
    t0 = time.time()
    d = client.get("/api/config", headers={"X-Device-Id": DEV}).get_json()
    assert time.time() - t0 < 2.2 and d["anon_remaining"] == 10          # falls back to the full allowance


def test_config_knobs_show_up(client, monkeypatch):
    monkeypatch.setattr(appmod, "FAIR_DEVICE_DAILY", 7)
    monkeypatch.setattr(appmod, "FAIR_USER_DAILY", 55)
    d = client.get("/api/config").get_json()
    assert d["fair_use"] == {"device_daily": 7, "user_daily": 55} and d["anon_free_limit"] == 7


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
    "GEN_MAX_CONCURRENT", "GEN_QUEUE_WAIT_S", "RATE_SUMMARIZE_PER_MIN")}))
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
                        "FAIR_GLOBAL_DAILY": 2000, "GEN_MAX_CONCURRENT": 3, "GEN_QUEUE_WAIT_S": 45.0,
                        "RATE_SUMMARIZE_PER_MIN": 30}
    k = _knobs(ALIMNE_FREE_MODE="0", FAIR_DEVICE_DAILY="7", FAIR_IP_DAILY="99", FAIR_USER_DAILY="5",
               FAIR_GLOBAL_DAILY="123", GEN_MAX_CONCURRENT="2", GEN_QUEUE_WAIT_S="9.5", RATE_SUMMARIZE_PER_MIN="12")
    assert k == {"FREE_MODE": False, "FAIR_DEVICE_DAILY": 7, "FAIR_IP_DAILY": 99, "FAIR_USER_DAILY": 5,
                 "FAIR_GLOBAL_DAILY": 123, "GEN_MAX_CONCURRENT": 2, "GEN_QUEUE_WAIT_S": 9.5,
                 "RATE_SUMMARIZE_PER_MIN": 12}
    # nonsense falls back to the defaults; a zero slot count / rate would lock everyone out
    k = _knobs(ALIMNE_FREE_MODE="1", FAIR_DEVICE_DAILY="lots", GEN_MAX_CONCURRENT="0", GEN_QUEUE_WAIT_S="soon",
               RATE_SUMMARIZE_PER_MIN="0")
    assert k["FREE_MODE"] is True and k["FAIR_DEVICE_DAILY"] == 10 and k["GEN_MAX_CONCURRENT"] == 3
    assert k["GEN_QUEUE_WAIT_S"] == 45.0 and k["RATE_SUMMARIZE_PER_MIN"] == 30


def test_the_free_mode_code_adds_no_import_time_threads_or_lazy_imports():
    import re
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    start = src.index("# ── Free mode: fair use instead of tokens")
    block = src[start:src.index("def _refund_credit", start)]
    assert "Thread(" not in block and "submit(" not in block and "\nimport " not in block
    assert "threading.Thread" not in src[src.index("_gen_sem          ="):src.index("_gen_sem          =") + 400]
