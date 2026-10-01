"""
Guard: _debullet strips a leading list marker ("- ", "1. ", "• ") from every fact
before it reaches the guide, the PDF and the markdown. It used to treat a leading
decimal or minus sign as a marker, silently changing facts:
"3.5 billion" -> "5 billion", "0.9% saline" -> "9% saline", "-273.15" -> "273.15".
"""
import pytest

import app as appmod


@pytest.mark.parametrize("text", [
    "3.5 billion years ago life appeared",
    "0.9% saline is isotonic",
    "12.5% of the population",
    "-273.15 °C is absolute zero",
    "-5 is a negative integer",
    "–2 is the oxidation state of oxygen",
])
def test_leading_numbers_are_kept(text):
    assert appmod._debullet(text) == text


@pytest.mark.parametrize("text,expected", [
    ("1. First item", "First item"),
    ("2) Second item", "Second item"),
    ("10. Tenth item", "Tenth item"),
    ("- dash bullet", "dash bullet"),
    ("—em dash bullet", "em dash bullet"),
    ("* star bullet", "star bullet"),
    ("• glyph bullet", "glyph bullet"),
    ("• 3.5 billion years", "3.5 billion years"),
    ("- 0.9% saline", "0.9% saline"),
])
def test_list_markers_are_still_stripped(text, expected):
    assert appmod._debullet(text) == expected
