"""
Nightly debug run: a wrong or unknown shared-guide link (/s/<slug>) answered
with the English "This guide isn't here" page even to an Arabic browser. The
page now follows the browser's Accept-Language (Arabic, RTL); the English page
is unchanged and it is still a 404.
"""
import app as appmod

_EN_H1 = "This guide isn't here"


def _has_arabic(s):
    return any("؀" <= ch <= "ۿ" for ch in s or "")


def _get(lang=None):
    hdr = {"Accept-Language": lang} if lang else {}
    return appmod.app.test_client().get("/s/!bad", headers=hdr)


def test_arabic_browser_gets_arabic_404():
    r = _get("ar,en;q=0.5")
    html = r.get_data(as_text=True)
    assert r.status_code == 404
    assert _EN_H1 not in html
    assert 'lang="ar" dir="rtl"' in html
    h1 = html.split("<h1>", 1)[1].split("</h1>", 1)[0]
    assert _has_arabic(h1)


def test_english_404_unchanged():
    for lang in (None, "en-US,en;q=0.9"):
        r = _get(lang)
        html = r.get_data(as_text=True)
        assert r.status_code == 404
        assert _EN_H1 in html and 'lang="en" dir="ltr"' in html
        assert not _has_arabic(html.split("<body>", 1)[1])
