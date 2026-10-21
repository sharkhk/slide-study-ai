"""
Nightly debug run: the public page of a shared Arabic guide (/s/<slug>) ended
with the English footer "Made with alimne.app — turn any lecture into a study
guide." in the middle of an RTL Arabic page. The footer now follows the page's
language; the English page is unchanged.
"""
import app as appmod

_EN_FOOT = "Made with alimne.app — turn any lecture into a study guide."


def _page(lang):
    return appmod._render_shared_guide({"slug": "abcdefgh", "language": lang,
                                        "guide": {"title": "T", "language": lang}})


def test_arabic_shared_page_footer_is_arabic():
    html = _page("ar")
    assert _EN_FOOT not in html
    foot = html.split('<div class="foot">', 1)[1].split("</div>", 1)[0]
    assert "alimne.app" in foot and any("؀" <= ch <= "ۿ" for ch in foot)


def test_english_shared_page_footer_unchanged():
    assert _EN_FOOT in _page("en")
