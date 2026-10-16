"""
Nightly debug run: the YouTube timedtext fallback in _fetch_captions asks for
fmt=srv3, whose captions are <p> lines (often split into <s> words), but
_parse_caption_xml read only the srv1 <text> elements. So a video whose
captions only came through that fallback was treated as having none, and the
app downloaded the audio for the paid, slower Whisper transcription instead.
"""
import app as appmod

SRV3 = ('<?xml version="1.0" encoding="utf-8" ?><timedtext format="3"><body>'
        '<p t="0" d="1500" w="1"><s ac="0">the</s><s t="200" ac="0"> mitochondria</s></p>'
        '<p t="1500" d="10" w="1" a="1">\n</p>'
        '<p t="1600" d="900">is the powerhouse &amp; more</p>'
        '</body></timedtext>')

SRV1 = ('<?xml version="1.0" encoding="utf-8" ?><transcript>'
        '<text start="0" dur="1.5">the mitochondria</text>'
        '<text start="1.6" dur="0.9">is the powerhouse &amp;amp; more</text>'
        '</transcript>')


def test_srv3_captions_are_read():
    assert appmod._parse_caption_xml(SRV3) == "the mitochondria is the powerhouse & more"


def test_srv1_captions_still_read():
    assert appmod._parse_caption_xml(SRV1) == "the mitochondria is the powerhouse & more"


def test_empty_or_bad_xml_is_none():
    assert appmod._parse_caption_xml('<timedtext format="3"><body></body></timedtext>') is None
    assert appmod._parse_caption_xml("not xml") is None


class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        pass


def test_timedtext_fallback_finds_srv3_captions(monkeypatch):
    def fake_get(url, params=None, **kw):
        if "timedtext" in url:
            return _Resp(SRV3)
        return _Resp("<html>no caption tracks here</html>")
    monkeypatch.setattr(appmod.http, "get", fake_get)
    assert appmod._fetch_captions("abcdefghijk") == "the mitochondria is the powerhouse & more"
