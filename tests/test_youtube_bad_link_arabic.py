"""
Nightly debug run: /api/youtube refused a link it can't read (not a YouTube
link, a typo) or an empty one with the English "Could not extract video ID from
URL" / "No URL provided", even on an Arabic request. The client sends any link
in the YouTube box and shows the text as sent, so an Arabic visitor who pasted
the wrong link got English. They now follow the request's language; English is
unchanged. Nothing is charged on either path.
"""
import pytest

import app as appmod


def _has_arabic(s):
    return any("؀" <= ch <= "ۿ" for ch in s or "")


@pytest.mark.parametrize("url,en", [
    ("https://example.com/lecture", "Could not extract video ID from URL"),
    ("", "No URL provided"),
])
@pytest.mark.parametrize("lang,arabic", [("ar", True), ("en", False)])
def test_bad_youtube_link_in_request_language(monkeypatch, lang, arabic, url, en):
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    charged = []
    monkeypatch.setattr(appmod, "_charge_credit", lambda *a, **k: charged.append(1))
    r = appmod.app.test_client().post("/api/youtube", json={"url": url, "language": lang})
    assert r.status_code == 400
    msg = r.get_json()["error"]
    assert _has_arabic(msg) is arabic, msg
    if not arabic:
        assert msg == en
    assert not charged
