"""
Nightly debug run: /api/youtube with a malformed URL (an unclosed IPv6 bracket,
e.g. "https://[youtube.com/watch?v=...") made urlparse raise ValueError inside
_extract_video_id and answered an HTML 500 page instead of the JSON 400 the app
shows as "Could not extract video ID". No credit was involved.
"""
import pytest

import app as appmod


@pytest.mark.parametrize("url", [
    "https://[youtube.com/watch?v=abcdefghijk",
    "https://youtube.com]/watch?v=abcdefghijk",
    "http://[::1/watch?v=abcdefghijk",
])
def test_malformed_youtube_url_is_400_json(monkeypatch, url):
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    appmod.app.config["TESTING"] = False   # a real 500 page, not a raised exception
    try:
        r = appmod.app.test_client().post("/api/youtube", json={"url": url})
    finally:
        appmod.app.config["TESTING"] = True
    assert r.status_code == 400, r.status_code
    assert r.is_json and r.get_json().get("error")


def test_extract_video_id_still_works():
    assert appmod._extract_video_id("https://www.youtube.com/watch?v=abcdefghijk") == "abcdefghijk"
    assert appmod._extract_video_id("https://[youtube.com/watch?v=abcdefghijk") is None
