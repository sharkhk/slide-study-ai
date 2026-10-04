"""
Nightly debug run: /api/summarize-text with a URL decoded pages wrongly.
  - A UTF-8 page whose Content-Type header has no charset (it is declared only
    in <meta charset>) was decoded as ISO-8859-1 by requests' default, so Arabic
    pages became mojibake ("Ø§ÙØ¨..."), language detection said English and the
    student was charged for a nonsense guide.
  - An unknown charset name in the header (e.g. "utf8mb4") raised LookupError
    outside the fetch guard → an HTML 500 page instead of a guide.
"""
import io
import socket

import pytest
import requests
from urllib3.response import HTTPResponse

import app as appmod

AR_TEXT = "البناء الضوئي هو العملية التي تحوّل بها النباتات الخضراء طاقة الضوء إلى طاقة كيميائية"


def _serve(monkeypatch, body, content_type):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])

    def send(self, request, **kw):
        raw = HTTPResponse(body=io.BytesIO(body), headers={"Content-Type": content_type},
                           status=200, preload_content=False)
        return self.build_response(request, raw)   # a real requests.Response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)


def test_utf8_page_with_meta_charset_only(monkeypatch):
    html = f"<html><head><meta charset='utf-8'></head><body><p>{AR_TEXT}</p></body></html>"
    _serve(monkeypatch, html.encode("utf-8"), "text/html")
    txt = appmod._fetch_url_text("https://example.com/ar")
    assert AR_TEXT in txt
    assert appmod._detect_language(txt) == "ar"


def test_utf8_page_with_no_charset_anywhere(monkeypatch):
    _serve(monkeypatch, f"<p>{AR_TEXT}</p>".encode("utf-8"), "text/html")
    assert AR_TEXT in appmod._fetch_url_text("https://example.com/ar")


def test_header_charset_still_wins(monkeypatch):
    text = "Les cellules produisent de l'énergie dans les mitochondries."
    _serve(monkeypatch, f"<p>{text}</p>".encode("cp1252"), "text/html; charset=windows-1252")
    assert text in appmod._fetch_url_text("https://example.com/fr")


def test_legacy_latin_page_without_charset(monkeypatch):
    text = "Les cellules produisent de l'énergie dans les mitochondries."
    _serve(monkeypatch, f"<p>{text}</p>".encode("cp1252"), "text/html")
    assert text in appmod._fetch_url_text("https://example.com/fr")


@pytest.mark.parametrize("cs", ["utf8mb4", "x-user-defined", "none"])
def test_unknown_header_charset_does_not_crash(monkeypatch, cs):
    text = "Cells make energy in mitochondria through respiration."
    _serve(monkeypatch, f"<p>{text}</p>".encode("utf-8"), f"text/html; charset={cs}")
    assert text in appmod._fetch_url_text("https://example.com/x")


# A codec that is not a text encoding ("base64", "hex", "rot13"…) passed
# codecs.lookup but bytes.decode() then raised LookupError → refund + HTML 500.
@pytest.mark.parametrize("cs", ["base64", "hex", "rot13", "zip"])
def test_non_text_codec_charset_does_not_crash(monkeypatch, cs):
    text = "Cells make energy in mitochondria through respiration."
    _serve(monkeypatch, f"<p>{text}</p>".encode("utf-8"), f"text/html; charset={cs}")
    assert text in appmod._fetch_url_text("https://example.com/x")


def test_non_text_codec_meta_charset_does_not_crash(monkeypatch):
    html = f"<html><head><meta charset='base64'></head><body><p>{AR_TEXT}</p></body></html>"
    _serve(monkeypatch, html.encode("utf-8"), "text/html")
    assert AR_TEXT in appmod._fetch_url_text("https://example.com/ar")


# A <meta> can't truly declare UTF-16/32 (the meta itself was read as ASCII
# bytes); browsers treat such a page as UTF-8. Decoding it as UTF-16 turned an
# Arabic page into CJK-looking garbage and charged for a nonsense guide.
@pytest.mark.parametrize("cs", ["utf-16", "UTF-16LE", "utf-32"])
def test_meta_utf16_is_read_as_utf8(monkeypatch, cs):
    html = f'<html><head><meta charset="{cs}"></head><body><p>{AR_TEXT}</p></body></html>'
    _serve(monkeypatch, html.encode("utf-8"), "text/html")
    assert AR_TEXT in appmod._fetch_url_text("https://example.com/ar")
