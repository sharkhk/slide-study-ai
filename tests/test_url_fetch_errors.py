"""
Nightly debug run: when /api/summarize-text could not fetch a URL, the visitor saw
the raw library error, always in English, e.g.
  "Could not fetch URL: 404 Client Error: Not Found for url: https://93.184.216.34/x"
  "Could not fetch URL: HTTPSConnectionPool(host='93.184.216.34', … object at 0x7f…>"
(the pinned server-side IP and Python object reprs included). Every fetch failure
now has a short, friendly text in the request's language; status codes (400) and
the refund are unchanged.
"""
import io
import socket

import pytest
import requests
from urllib3.response import HTTPResponse

import app as appmod


def _has_arabic(s):
    return any("؀" <= ch <= "ۿ" for ch in s or "")


def _resolve(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])


def _status(monkeypatch, code, headers=None):
    _resolve(monkeypatch)

    def send(self, request, **kw):
        raw = HTTPResponse(body=io.BytesIO(b"<p>x</p>"), headers=headers or {"Content-Type": "text/html"},
                           status=code, preload_content=False, reason="Not Found")
        return self.build_response(request, raw)

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)


def _conn_error(monkeypatch):
    _resolve(monkeypatch)

    def send(self, request, **kw):
        raise requests.exceptions.ConnectionError(
            "HTTPSConnectionPool(host='93.184.216.34', port=443): Max retries exceeded "
            "(Caused by NewConnectionError('<urllib3.connection.HTTPSConnection object at 0x7f>'))")

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)


def _no_dns(monkeypatch):
    def gai(*a, **k):
        raise socket.gaierror("Name or service not known")
    monkeypatch.setattr(socket, "getaddrinfo", gai)


SETUPS = {
    "404": lambda mp: _status(mp, 404),
    "503": lambda mp: _status(mp, 503),
    "redirect": lambda mp: _status(mp, 301, {"Location": "https://example.com/y"}),
    "conn": _conn_error,
    "dns": _no_dns,
}


@pytest.mark.parametrize("case", sorted(SETUPS))
@pytest.mark.parametrize("lang,arabic", [("ar", True), ("en", False)])
def test_fetch_failure_is_friendly_and_localised(monkeypatch, case, lang, arabic):
    SETUPS[case](monkeypatch)
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    monkeypatch.setattr(appmod, "_url_precheck", lambda u: True)
    r = appmod.app.test_client().post(
        "/api/summarize-text",
        json={"url": "https://example.com/x", "language": lang},
        headers={"X-Device-Id": "dev-url-fetch-%s-%s" % (case, lang)})
    assert r.status_code == 400, r.get_data(as_text=True)
    err = r.get_json()["error"]
    assert _has_arabic(err) is arabic, err
    for leak in ("93.184.216.34", "Client Error", "Pool", "object at", "0x7f", "Errno"):
        assert leak not in err, err
