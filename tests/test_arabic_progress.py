"""
Nightly debug run: while a guide generates, the app shows the server's progress
line (`msg` of each SSE step event) exactly as sent. Every one of those lines was
English, so an Arabic visitor watched "Extracting content…", "Section 1/3: …",
"Generating quiz…" in an Arabic interface. They now follow the request's
language (the same `ar` that already picks the queue / busy / error texts).
English requests get exactly the same English lines as before.
"""
import pytest

import app as appmod
from tests.test_free_mode import (  # noqa: F401  (fixtures)
    ENDPOINTS, _fixed_ip, _has_arabic, _sse_events, auth_on, client, llm, sb,
)


def _msgs(resp):
    return [e["msg"] for e in _sse_events(resp) if e.get("step") and e.get("msg")]


@pytest.mark.parametrize("name,post", ENDPOINTS, ids=[e[0] for e in ENDPOINTS])
def test_progress_lines_are_arabic_for_an_arabic_request(client, auth_on, sb, llm, name, post):
    r = post(client, language="ar")
    assert r.status_code == 200, r.get_data(as_text=True)
    events = _sse_events(r)
    assert any(e.get("step") == "done" for e in events), events
    msgs = _msgs(r)
    assert len(msgs) >= 5, msgs
    english = [m for m in msgs if not _has_arabic(m)]
    assert not english, english


@pytest.mark.parametrize("name,post", ENDPOINTS, ids=[e[0] for e in ENDPOINTS])
def test_progress_lines_stay_english_for_an_english_request(client, auth_on, sb, llm, name, post):
    r = post(client, language="en")
    assert r.status_code == 200
    msgs = _msgs(r)
    assert "Analysing structure and keywords…" in msgs
    assert "Generating quiz…" in msgs
    assert not [m for m in msgs if _has_arabic(m)], msgs


def test_demo_progress_lines_follow_the_language_live_and_cached(client, llm, monkeypatch):
    monkeypatch.setattr(appmod, "_demo_cache", {})
    for _ in range(2):   # first run is generated, the second replays the cache
        r = client.post("/api/summarize-text", json={"demo": True, "language": "ar"})
        assert r.status_code == 200
        msgs = _msgs(r)
        assert msgs and all(_has_arabic(m) for m in msgs), msgs
    assert "ar" in appmod._demo_cache
    r = client.post("/api/summarize-text", json={"demo": True, "language": "en"})
    assert "Preparing content…" in _msgs(r)


def test_translation_keeps_numbers_and_titles():
    ev = appmod._progress_ar({"step": "section", "msg": "Section 2/5: Cell Biology…"})
    assert "2/5" in ev["msg"] and "Cell Biology" in ev["msg"] and _has_arabic(ev["msg"])
    ev = appmod._progress_ar({"step": "extract", "msg": "Found 12 content slides (Arabic) — analysing…",
                              "language": "ar"})
    assert "12" in ev["msg"] and _has_arabic(ev["msg"]) and ev["language"] == "ar"
    # An unknown line is passed through untouched rather than dropped.
    assert appmod._progress_ar({"step": "x", "msg": "Hello"})["msg"] == "Hello"
