"""
Nightly debug run: the model sometimes answers section bullets as objects
({"text": "..."} or {"fact": "..."}) instead of plain strings. pass2_section
stored str(dict), so the guide, PDF and Markdown showed Python reprs like
"{'text': 'Mitosis has four phases'}". Such a bullet is now its text.
"""
import app as appmod


def test_dict_bullets_become_their_text(monkeypatch):
    monkeypatch.setattr(appmod, "_call_ollama", lambda *a, **k: {"bullets": [
        {"text": "Mitosis has four phases"},
        {"fact": "Prophase comes first"},
        "Plain fact",
        42,
        {"other": "x"},
        [],
    ]})
    slides = [{"slide_num": 1, "title": "Cells", "content": "Mitosis..."}]
    out = appmod.pass2_section("Cells", slides, "en")
    assert out["bullets"] == ["Mitosis has four phases", "Prophase comes first", "Plain fact", "42"]
    assert not any("{" in b for b in out["bullets"])
