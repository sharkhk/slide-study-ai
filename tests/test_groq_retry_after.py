"""
Nightly debug run: on a Groq 429 _call_groq slept for whatever Retry-After said,
with no upper bound, up to 5 times per model across the primary and fallback
models. When Groq's daily limit runs out it answers with Retry-After in the
thousands of seconds, so a generation stream went silent for hours while holding
one of gunicorn's 8 threads (a few users could block the whole site). A wait
longer than _GROQ_MAX_WAIT_S now moves straight to the next model, and the call
fails fast (the stream's refund-and-error path runs) once every model is busy.
Short waits (the usual per-minute limit) still sleep and retry as before.

EVERYTHING IS OFFLINE: http.post and time.sleep are faked.
"""
import pytest

import app as appmod


class _Resp429:
    status_code = 429
    text = "rate limit"

    def __init__(self, retry_after):
        self.headers = {"retry-after": retry_after}


@pytest.fixture
def groq(monkeypatch):
    monkeypatch.setattr(appmod, "GROQ_API_KEY", "x")
    monkeypatch.setattr(appmod, "_groq_pace", lambda n: None)
    state = {"sleeps": [], "posts": []}
    monkeypatch.setattr(appmod.time, "sleep", lambda s: state["sleeps"].append(s))
    return state


def test_long_retry_after_fails_fast_instead_of_sleeping_for_hours(groq, monkeypatch):
    def post(url, json=None, **k):
        groq["posts"].append(json["model"])
        return _Resp429("3600")
    monkeypatch.setattr(appmod.http, "post", post)

    with pytest.raises(Exception):
        appmod._call_groq("p", retries=5)

    assert sum(groq["sleeps"]) <= 60, groq["sleeps"]
    # every model was still tried once (each has its own limits)
    models = [appmod.GROQ_MODEL] + [m for m in appmod.GROQ_FALLBACK_MODELS if m != appmod.GROQ_MODEL]
    assert groq["posts"] == models


def test_long_retry_after_on_primary_falls_back_to_next_model(groq, monkeypatch):
    if not [m for m in appmod.GROQ_FALLBACK_MODELS if m != appmod.GROQ_MODEL]:
        pytest.skip("no fallback model configured")
    ok = {"choices": [{"message": {"content": '{"ok": 1}'}}]}

    class _Ok:
        status_code = 200
        headers = {}
        text = ""
        def raise_for_status(self): pass
        def json(self): return ok

    def post(url, json=None, **k):
        groq["posts"].append(json["model"])
        return _Resp429("7200") if json["model"] == appmod.GROQ_MODEL else _Ok()
    monkeypatch.setattr(appmod.http, "post", post)

    assert appmod._call_groq("p", retries=5) == {"ok": 1}
    assert groq["sleeps"] == []


def test_short_retry_after_still_waits_and_retries(groq, monkeypatch):
    ok = {"choices": [{"message": {"content": '{"ok": 1}'}}]}
    calls = []

    class _Ok:
        status_code = 200
        headers = {}
        text = ""
        def raise_for_status(self): pass
        def json(self): return ok

    def post(url, json=None, **k):
        calls.append(1)
        return _Resp429("7") if len(calls) == 1 else _Ok()
    monkeypatch.setattr(appmod.http, "post", post)

    assert appmod._call_groq("p", retries=5) == {"ok": 1}
    assert groq["sleeps"] == [7]
