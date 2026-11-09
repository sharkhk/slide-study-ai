"""
Nightly debug run: a pasted link whose host name resolves to a private / internal
address (e.g. a campus intranet name that public DNS maps to 10.x) is refused by
_fetch_url_text with "URL points to a private/internal address — not allowed.".
That was a plain ValueError with no Arabic text, so /api/summarize-text answered
an Arabic visitor in English. It now has an Arabic text; the English text, the
400 status and the refund are unchanged.
"""
import socket

import pytest

import app as appmod

EN = "URL points to a private/internal address — not allowed."


def _has_arabic(s):
    return any("؀" <= ch <= "ۿ" for ch in s or "")


@pytest.mark.parametrize("lang,arabic", [("ar", True), ("en", False)])
def test_private_host_refusal_is_localised(monkeypatch, lang, arabic):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 443))])
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    r = appmod.app.test_client().post(
        "/api/summarize-text",
        json={"url": "https://intranet.example.edu/notes", "language": lang},
        headers={"X-Device-Id": "dev-url-private-%s" % lang})
    assert r.status_code == 400, r.get_data(as_text=True)
    err = r.get_json()["error"]
    assert _has_arabic(err) is arabic, err
    if not arabic:
        assert err == EN
    assert "10.0.0.5" not in err
