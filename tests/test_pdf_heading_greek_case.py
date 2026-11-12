"""
Nightly debug run: the English PDF prints the guide title and each section
heading in capitals with str.upper(). That also capitalised Greek letters, which
changes their meaning in a STEM lecture: "β-oxidation" printed as "Β-OXIDATION"
(capital beta looks exactly like "B"), "α-helix" as "Α-HELIX", "π bonds" as
"Π BONDS" (the product sign) and "µm" as "ΜM". Greek letters (and the micro sign)
now keep their case; Latin letters are still capitalised. Arabic guides are not
upper-cased at all and are unchanged.
"""
import io

from pypdf import PdfReader

import app as appmod

_CAP_GREEK = set("ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ")


def _pdf_text(guide, lang="en"):
    pdf = appmod.build_pdf(guide, lang).read()
    return "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)


def _guide():
    return {
        "title": "β-oxidation and π bonds",
        "subtitle": "Biochemistry",
        "language": "en",
        "sections": [
            {"title": "The α-helix at the µm scale", "bullets": ["A coiled protein structure."]},
            {"title": "Δ and δ notation", "bullets": ["Capital delta stays capital."]},
        ],
    }


def test_title_and_section_headings_keep_greek_lowercase():
    txt = _pdf_text(_guide())
    # Latin letters are still capitalised in the header and section bars.
    assert "OXIDATION AND" in txt
    assert "HELIX AT THE" in txt
    assert "NOTATION" in txt
    # Greek letters keep their case: no capital Greek appears that the guide
    # didn't contain (Δ was already capital in the source).
    assert not (set(txt) & (_CAP_GREEK - {"Δ"})), sorted(set(txt) & _CAP_GREEK)
    assert "δ" in txt.split("NOTATION")[0]          # the section bar's δ stayed lowercase
    for word in ("B-OXIDATION", "A-HELIX", " MM "):
        assert word not in txt


def test_arabic_guide_headings_unchanged():
    g = _guide()
    g["language"] = "ar"
    g["title"] = "أكسدة β"
    txt = _pdf_text(g, "ar")
    assert "β" in txt and "Β" not in txt
