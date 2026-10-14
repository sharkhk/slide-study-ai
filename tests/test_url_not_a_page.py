"""
Nightly debug run: /api/summarize-text with a link to a FILE (a lecture PDF, an
image, a .pptx…) instead of a web page read the raw bytes as if they were HTML:
"%PDF-1.3 … obj endobj …" became the "text", the visitor was charged and Groq
built a nonsense guide from it. A response whose Content-Type is not a web page
or text is now refused before any AI work (400, in the request's language) and
the charge is refunded. Web pages and plain-text links behave exactly as before.
"""
import io
import socket

import pytest
import requests
from urllib3.response import HTTPResponse

import app as appmod

PDF_BYTES = b"%PDF-1.3\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"


def _has_arabic(s):
    return any("؀" <= ch <= "ۿ" for ch in s or "")


def _serve(monkeypatch, body, content_type):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])

    def send(self, request, **kw):
        raw = HTTPResponse(body=io.BytesIO(body), headers={"Content-Type": content_type},
                           status=200, preload_content=False)
        return self.build_response(request, raw)

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)


@pytest.mark.parametrize("ct", ["application/pdf", "image/png", "application/octet-stream",
                                "application/vnd.openxmlformats-officedocument.presentationml.presentation"])
def test_file_link_is_refused(monkeypatch, ct):
    _serve(monkeypatch, PDF_BYTES, ct)
    with pytest.raises(ValueError):
        appmod._fetch_url_text("https://example.com/lecture.pdf")


@pytest.mark.parametrize("ct", ["text/html; charset=utf-8", "text/plain", "application/xhtml+xml", ""])
def test_pages_and_text_still_fetch(monkeypatch, ct):
    text = "Cells make energy in mitochondria through respiration."
    _serve(monkeypatch, f"<p>{text}</p>".encode("utf-8"), ct)
    assert text in appmod._fetch_url_text("https://example.com/page")


@pytest.mark.parametrize("lang,arabic", [("ar", True), ("en", False)])
def test_pdf_link_is_a_400_with_no_ai_work_and_a_refund(monkeypatch, lang, arabic):
    _serve(monkeypatch, PDF_BYTES, "application/pdf")
    monkeypatch.setattr(appmod, "ollama_running", lambda: True)
    calls = []
    monkeypatch.setattr(appmod, "_call_ollama", lambda *a, **k: calls.append(1) or {})
    refunds = []
    real_refund = appmod._Charge.refund
    monkeypatch.setattr(appmod._Charge, "refund", lambda self: refunds.append(1) or real_refund(self))
    r = appmod.app.test_client().post(
        "/api/summarize-text",
        json={"url": "https://example.com/lecture.pdf", "language": lang},
        headers={"X-Device-Id": "dev-url-not-a-page-%s" % lang})
    assert r.status_code == 400, r.get_data(as_text=True)
    err = r.get_json()["error"]
    assert _has_arabic(err) is arabic, err
    assert "%PDF" not in err
    assert calls == [], "no AI work may run on a file link"
    assert refunds, "the charge must be refunded"
