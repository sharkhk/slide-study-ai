"""
Nightly debug run: a section table cell holding a "|" (e.g. "P(A|B)" in a
statistics lecture) or a line break was written into the Markdown table as-is.
The .md download then had a row with an extra column (or a row cut in two), and
the print view (/api/view/md, rendered from that Markdown) showed the cell split
across columns and the rest of the row as a stray paragraph under the table.
Cells are now escaped ("\\|", line breaks as spaces) and the print view reads
an escaped pipe back as a plain "|".
"""
import re

import app as appmod

GUIDE = {
    "title": "Probability", "subtitle": "", "language": "en",
    "sections": [{"title": "Rules", "bullets": ["Bayes links conditionals."],
                  "table": {"headers": ["Rule", "Formula"],
                            "rows": [["Bayes", "P(A|B) = P(B|A)P(A)/P(B)"],
                                     ["Product", "P(A and B)\n= P(A)P(B|A)"]]}}],
    "flashcards": [], "mcqs": [], "keywords": [], "objectives": [],
}


def _cells(line):
    return re.split(r"(?<!\\)\|", line.strip()[1:-1])


def test_markdown_table_rows_keep_their_columns():
    md = appmod.build_markdown(GUIDE)
    lines = md.split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith("| Rule"))
    table = lines[start:start + 4]
    assert all(l.startswith("|") and l.endswith("|") for l in table), table
    assert all(len(_cells(l)) == 2 for l in table), table
    assert lines[start + 4] == ""


def test_print_view_shows_cell_text_in_one_cell(monkeypatch):
    job_id = "a" * 32
    appmod.store_job(job_id, b"%PDF", appmod.build_markdown(GUIDE), GUIDE, None, "p.pdf")
    html = appmod.app.test_client().get(f"/api/view/md/{job_id}").get_data(as_text=True)
    assert "<td>P(A|B) = P(B|A)P(A)/P(B)</td>" in html
    assert "<td>P(A and B) = P(A)P(B|A)</td>" in html
    assert "\\|" not in html
    assert "<p>= P(A)P(B|A) |</p>" not in html
