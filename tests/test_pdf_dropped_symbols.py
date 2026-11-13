"""
Guard: characters that neither Helvetica nor the Symbol font can draw used to be
DROPPED from the English PDF when they had no Unicode decomposition, so their
meaning vanished: "N2 + 3H2 ⇌ 2NH3" printed as "N2 + 3H2  2NH3", "₹500" as "500",
"ħω" as "ω", "Łukasiewicz" as "ukasiewicz", "a ∥ b" as "a  b". They now get a
WinAnsi stand-in (still never a missing-glyph box).
"""
import io

from pypdf import PdfReader

import app as appmod

_CASES = {
    "N2 + 3H2 ⇌ 2NH3": "N2 + 3H2 <=> 2NH3",
    "costs ₹500": "costs Rs500",
    "₦200, ₩900, ₱50, ₽10, ₺5, ₪3, ₫1, ₴2": "N200, W900, P50, RUB10, TL5, ILS3, VND1, UAH2",
    "E = ħω": "E = h",
    "ℏ = h/2π": "h = h/2",
    "Łukasiewicz, Đorđe, ı": "Lukasiewicz, Dorde, i",
    "a ∥ b, a ∣ b": "a || b, a | b",
    "x ∓ y": "x -/+ y",
}


def _plain(markup):
    return markup.replace('<font face="Symbol">', "").replace("</font>", "").replace("&lt;", "<").replace("&gt;", ">")


def test_undrawable_symbols_get_a_stand_in_not_dropped():
    for src, want in _CASES.items():
        got = _plain(appmod._pdf_latin_markup(src))
        assert want in got, (src, got)
        for ch in got:
            assert appmod._enc_ok(ch, "cp1252") or appmod._enc_ok(ch, "symbol"), repr(ch)


def test_english_pdf_keeps_equilibrium_arrow_and_currency():
    g = {"title": "Chem", "sections": [{"title": "Haber", "bullets": [
        "N2 + 3H2 ⇌ 2NH3", "A plant costs ₹500 crore"]}],
         "keywords": [], "flashcards": [], "mcqs": [], "language": "en"}
    pdf = appmod.build_pdf(g, "en", "t").read()
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "■" not in text
    assert "<=>" in text and "Rs500" in text, text
