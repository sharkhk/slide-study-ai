"""
Bug 1 (nightly debug run): /api/summarize-text CHARGED a credit and then crashed
(500, never refunded) when a JSON field had the wrong type — {"text": 123}, or a
number / list url, filename, language or detail. Every field is now type-checked
BEFORE _charge_credit: a bad type is a 400 {error, code:'bad_request'} (English or
Arabic) and nothing is spent. /api/youtube had the same crashes (500 before the
charge) and /api/summarize-stream charged, then refunded, an unsupported file type.
Valid payloads (exactly what the React client sends) and the free demo are unchanged.

EVERYTHING IS OFFLINE: Groq, yt-dlp and URL fetches are all faked.
"""
import io
import json

import pytest

import app as appmod


# ── shared fakes ─────────────────────────────────────────────────────────────────
def _llm(prompt, retries=3, num_predict=4096):
    """Offline stand-in for _call_ollama covering every generation pass."""
    if "Create a study guide overview" in prompt:
        return {"title": "Topic", "subtitle": "s", "objectives": ["o"],
                "sections": [{"title": "A", "slide_nums": [1]}],
                "keywords": [{"term": "t", "definition": "d"}]}
    if "Extract detailed exam study notes" in prompt:
        return {"bullets": ["Fact one", "Fact two"]}
    return {"flashcards": [{"q": "Q", "a": "A"}],
            "mcqs": [{"q": "Q", "options": ["A) x", "B) y"], "answer": "A", "explanation": "e"}]}


@pytest.fixture
def client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


@pytest.fixture
def ledger(monkeypatch):
    """Count credits spent / refunded; keep every external call offline."""
    led = {"consumed": 0, "refunded": 0, "yt": 0, "fetched": []}

    def consume(uid):
        led["consumed"] += 1
        return True, 5, ""

    def refund(uid):
        led["refunded"] += 1
        return True

    def yt_duration(vid):
        led["yt"] += 1
        return 60

    def fetch(url):
        led["fetched"].append(url)
        return "Fetched lecture words about cells and energy. " * 30

    monkeypatch.setattr(appmod, "_consume_token", consume)
    monkeypatch.setattr(appmod, "_refund_token", refund)
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "_log_usage_async", lambda *a, **k: None)
    monkeypatch.setattr(appmod, "_call_ollama", _llm)
    monkeypatch.setattr(appmod, "_ensure_arabic_font", lambda: False)   # no font download
    monkeypatch.setattr(appmod, "_fetch_url_text", fetch)
    monkeypatch.setattr(appmod, "_yt_duration", yt_duration)
    monkeypatch.setattr(appmod, "_fetch_captions", lambda vid: "lecture words " * 50)
    return led


def _events(resp):
    return [json.loads(line[len("data: "):]) for line in resp.get_data(as_text=True).splitlines()
            if line.startswith("data: ")]


def _has_arabic(s):
    return any("؀" <= ch <= "ۿ" for ch in s or "")


TEXT = "Photosynthesis turns light into chemical energy in the chloroplast. " * 12


# ── 1. input types are validated BEFORE any credit is spent ─────────────────────
BAD_TEXT_BODIES = [
    {"text": 123},
    {"text": ["a list", "of strings"]},
    {"text": {"nested": "object"}},
    {"text": True},
    {"url": 123},
    {"url": ["https://example.com"]},
    {"text": TEXT, "url": {"href": "x"}},
    {"text": TEXT, "language": 5},
    {"text": TEXT, "language": ["ar"]},
    {"text": TEXT, "filename": 42},
    {"text": TEXT, "filename": ["notes"]},
    {"text": TEXT, "detail": ["brief"]},
    {"text": TEXT, "detail": {"level": "brief"}},
    {"text": TEXT, "mode": 7},
    {"text": TEXT, "quiz": [True]},
]


@pytest.mark.parametrize("body", BAD_TEXT_BODIES)
def test_summarize_text_bad_types_are_400_and_never_charged(client, ledger, body):
    r = client.post("/api/summarize-text", json=body)
    assert r.status_code == 400, r.get_data(as_text=True)[:300]
    d = r.get_json()
    assert d["code"] == "bad_request" and d["error"]
    assert ledger["consumed"] == 0 and ledger["refunded"] == 0
    assert ledger["fetched"] == []                      # never reached the URL fetch


@pytest.mark.parametrize("body", [[1, 2, 3], "just a string", 42, True])
def test_summarize_text_non_object_body_is_400_not_500(client, ledger, body):
    r = client.post("/api/summarize-text", data=json.dumps(body), content_type="application/json")
    assert r.status_code == 400
    assert r.get_json()["code"] == "bad_request"
    assert ledger["consumed"] == 0


def test_summarize_text_empty_input_is_rejected_before_charging(client, ledger):
    r = client.post("/api/summarize-text", json={"text": "   ", "url": ""})
    assert r.status_code == 400
    assert r.get_json()["error"] == "No text or URL provided"
    assert ledger["consumed"] == 0 and ledger["refunded"] == 0


def test_bad_request_text_is_localized(client, ledger):
    en = client.post("/api/summarize-text", json={"text": 123}).get_json()["error"]
    ar_field = client.post("/api/summarize-text", json={"text": 123, "language": "ar"}).get_json()["error"]
    ar_header = client.post("/api/summarize-text", json={"text": 123},
                            headers={"Accept-Language": "ar-AE,ar;q=0.9,en;q=0.5"}).get_json()["error"]
    assert not _has_arabic(en)
    assert _has_arabic(ar_field) and _has_arabic(ar_header)
    assert ledger["consumed"] == 0


def test_summarize_text_null_fields_fall_back_to_defaults(client, ledger):
    r = client.post("/api/summarize-text", json={
        "text": TEXT, "url": None, "language": None, "filename": None,
        "detail": None, "mode": None, "quiz": None})
    assert r.status_code == 200
    ev = _events(r)
    assert ev[-1].get("step") == "done", ev[-1]
    assert ledger["consumed"] == 1 and ledger["refunded"] == 0


def test_summarize_text_valid_frontend_payload_unchanged(client, ledger):
    # Exactly what the React client sends (runText).
    r = client.post("/api/summarize-text", json={
        "text": TEXT, "url": "", "language": "auto", "filename": "Pasted text",
        "detail": "brief", "mode": "full", "quiz": False})
    ev = _events(r)
    done = ev[-1]
    assert done.get("step") == "done", done
    assert done["mcqs"] == 0 and done["flashcards"] == 1      # quiz:false honoured
    assert done["tokens_remaining"] == 5
    assert ledger["consumed"] == 1 and ledger["refunded"] == 0


def test_summarize_text_url_path_still_works(client, ledger):
    r = client.post("/api/summarize-text", json={"url": "  https://example.com/lecture  ", "language": "en"})
    assert _events(r)[-1].get("step") == "done"
    assert ledger["fetched"] == ["https://example.com/lecture"]
    assert ledger["consumed"] == 1 and ledger["refunded"] == 0


# A URL that can never be fetched used to be CHARGED first and refunded after the
# fetch failed. For an anonymous visitor on the durable device quota the refund
# can fail (before migration 012), so the free preview was simply lost. The
# syntactic checks (public http(s), a host, no literal private address) now run
# BEFORE the charge; _fetch_url_text still re-checks the resolved IPs.
UNUSABLE_URLS = [
    "en.wikipedia.org/wiki/Photosynthesis",      # typed without https:// (the URL box doesn't add it)
    "www.example.com",
    "ftp://example.com/lecture.txt",
    "javascript:alert(1)",
    "file:///etc/passwd",
    "https:///no-host",
    "http://127.0.0.1/admin",
    "http://localhost:5000/",
    "http://api.localhost/",
    "http://[::1]/",
    "http://10.0.0.5/notes",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data",
    "http://0.0.0.0/",
    "http://example.com:99999/",                 # invalid port
]


@pytest.fixture
def charges(monkeypatch):
    calls = []
    real = appmod._charge_credit

    def spy(*a, **k):
        calls.append(1)
        return real(*a, **k)
    monkeypatch.setattr(appmod, "_charge_credit", spy)
    return calls


@pytest.mark.parametrize("url", UNUSABLE_URLS)
def test_summarize_text_unusable_url_is_rejected_before_charging(client, ledger, charges, url):
    r = client.post("/api/summarize-text", json={"url": url, "language": "auto"},
                    headers={"X-Device-Id": "dev-test-0001"})
    assert r.status_code == 400, r.get_data(as_text=True)[:300]
    d = r.get_json()
    assert d["code"] == "bad_request" and d["error"]
    assert charges == [], "a URL that can never be fetched must not be charged"
    assert ledger["consumed"] == 0 and ledger["refunded"] == 0
    assert ledger["fetched"] == []


def test_unusable_url_message_is_bilingual(client, ledger, charges):
    en = client.post("/api/summarize-text", json={"url": "en.wikipedia.org/wiki/X"}).get_json()["error"]
    ar = client.post("/api/summarize-text", json={"url": "en.wikipedia.org/wiki/X", "language": "ar"}).get_json()["error"]
    assert "https://" in en and not _has_arabic(en)
    assert "https://" in ar and _has_arabic(ar)
    assert charges == []


@pytest.mark.parametrize("url", ["https://example.com/lecture", "http://example.com/a?b=c",
                                 "https://en.wikipedia.org/wiki/Photosynthesis", "HTTPS://Example.COM/x",
                                 "http://93.184.216.34/page", "https://example.com:8443/x"])
def test_public_urls_still_reach_the_fetch(client, ledger, charges, url):
    r = client.post("/api/summarize-text", json={"url": url, "language": "en"})
    assert _events(r)[-1].get("step") == "done"
    assert ledger["fetched"] == [url]
    assert charges == [1] and ledger["consumed"] == 1 and ledger["refunded"] == 0


def test_url_is_not_checked_when_text_is_given(client, ledger, charges):
    # text wins over url (unchanged): a junk url next to pasted text is ignored
    r = client.post("/api/summarize-text", json={"text": TEXT, "url": "not a url", "language": "en"})
    assert _events(r)[-1].get("step") == "done"
    assert ledger["fetched"] == [] and ledger["consumed"] == 1


@pytest.mark.parametrize("lang", ["en", "ar", None, 5])
def test_demo_path_stays_free_and_working(client, ledger, lang):
    body = {"demo": True}
    if lang is not None:
        body["language"] = lang
    r = client.post("/api/summarize-text", json=body)
    assert r.status_code == 200
    assert _events(r)[-1].get("step") == "done"
    assert ledger["consumed"] == 0


BAD_YT_BODIES = [
    {"url": 123},
    {"url": ["https://youtu.be/dQw4w9WgXcQ"]},
    {"url": {"v": "dQw4w9WgXcQ"}},
    {"url": "https://youtu.be/dQw4w9WgXcQ", "language": 5},
    {"url": "https://youtu.be/dQw4w9WgXcQ", "language": ["en"]},
    {"url": "https://youtu.be/dQw4w9WgXcQ", "detail": ["standard"]},
    {"url": "https://youtu.be/dQw4w9WgXcQ", "detail": 3},
    {"url": "https://youtu.be/dQw4w9WgXcQ", "mode": ["summary"]},
    {"url": "https://youtu.be/dQw4w9WgXcQ", "quiz": {"on": True}},
]


@pytest.mark.parametrize("body", BAD_YT_BODIES)
def test_youtube_bad_types_are_400_before_yt_dlp_or_charge(client, ledger, body):
    r = client.post("/api/youtube", json=body)
    assert r.status_code == 400, r.get_data(as_text=True)[:300]
    assert r.get_json()["code"] == "bad_request"
    assert ledger["consumed"] == 0 and ledger["yt"] == 0


def test_youtube_non_object_body_is_400(client, ledger):
    r = client.post("/api/youtube", data="[\"https://youtu.be/dQw4w9WgXcQ\"]", content_type="application/json")
    assert r.status_code == 400 and r.get_json()["code"] == "bad_request"
    assert ledger["consumed"] == 0 and ledger["yt"] == 0


def test_youtube_valid_payload_unchanged(client, ledger):
    r = client.post("/api/youtube", json={"url": "https://youtu.be/dQw4w9WgXcQ", "language": "en",
                                          "detail": "standard", "mode": "full", "quiz": True})
    assert _events(r)[-1].get("step") == "done"
    assert ledger["consumed"] == 1 and ledger["refunded"] == 0


def test_youtube_null_fields_fall_back_to_defaults(client, ledger):
    r = client.post("/api/youtube", json={"url": "https://youtu.be/dQw4w9WgXcQ", "language": None,
                                          "detail": None, "mode": None, "quiz": None})
    assert _events(r)[-1].get("step") == "done"
    assert ledger["consumed"] == 1


@pytest.mark.parametrize("name", ["lecture.exe", "notes", "slides.pptx.zip", ""])
def test_file_upload_unsupported_type_is_rejected_before_charging(client, ledger, name):
    r = client.post("/api/summarize-stream", data={"file": (io.BytesIO(b"hello"), name)},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    assert ledger["consumed"] == 0 and ledger["refunded"] == 0


def test_file_upload_valid_still_charges_once(client, ledger):
    r = client.post("/api/summarize-stream", data={
        "file": (io.BytesIO(TEXT.encode()), "lecture.txt"), "language": "en", "detail": "brief",
        "mode": "full", "quiz": "true"}, content_type="multipart/form-data")
    assert _events(r)[-1].get("step") == "done"
    assert ledger["consumed"] == 1 and ledger["refunded"] == 0
