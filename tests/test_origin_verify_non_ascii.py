"""
Nightly debug run: with CF_ORIGIN_SECRET set, _via_cloudflare compared the
X-Origin-Verify header with secrets.compare_digest, which raises TypeError on a
non-ASCII str. Werkzeug decodes header bytes as latin-1, so any request carrying
a non-ASCII X-Origin-Verify answered a 500 from the before_request hook (every
page and API route). It now simply fails verification.
"""
import app as appmod


def test_non_ascii_origin_header_is_not_a_500(monkeypatch):
    monkeypatch.setattr(appmod, "CF_ORIGIN_SECRET", "s3cret-value")
    appmod.app.config["TESTING"] = False   # a real 500 page, not a raised exception
    try:
        r = appmod.app.test_client().get(
            "/api/config", headers={"X-Origin-Verify": "été", "CF-Connecting-IP": "203.0.113.9"})
    finally:
        appmod.app.config["TESTING"] = True
    assert r.status_code == 200, r.status_code


def test_origin_verify_still_checks_the_secret(monkeypatch):
    monkeypatch.setattr(appmod, "CF_ORIGIN_SECRET", "s3cret-value")
    with appmod.app.test_request_context(headers={"X-Origin-Verify": "s3cret-value"}):
        assert appmod._via_cloudflare() is True
    with appmod.app.test_request_context(headers={"X-Origin-Verify": "wrong"}):
        assert appmod._via_cloudflare() is False
    with appmod.app.test_request_context(headers={"X-Origin-Verify": "é"}):
        assert appmod._via_cloudflare() is False
    with appmod.app.test_request_context():
        assert appmod._via_cloudflare() is False
