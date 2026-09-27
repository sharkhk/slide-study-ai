"""
Copy-truth guard for Alimne (WO-2026-09-26-52).

Alimne keeps shared guides and deletes other guides after 15 minutes, so
absolute claims like "never stored" are false. This test fails if any banned
storage claim comes back into the user-facing sources or the served bundle.

Offline, no imports of the app: it only reads files.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BANNED = re.compile(r"never stored|nothing stored|no data stored|no storage", re.IGNORECASE)

SCAN_DIRS = ["frontend", "dist"]
SCAN_FILES = ["app.py"]
SKIP_DIRS = {"node_modules", ".vite"}
TEXT_EXT = {".html", ".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".txt", ".md", ".py", ".svg"}


def _files():
    for rel in SCAN_FILES:
        yield os.path.join(ROOT, rel)
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [n for n in dirnames if n not in SKIP_DIRS]
            for name in filenames:
                if os.path.splitext(name)[1].lower() in TEXT_EXT:
                    yield os.path.join(dirpath, name)


def test_no_banned_storage_claims():
    hits = []
    for path in _files():
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for lineno, line in enumerate(fh, 1):
                m = BANNED.search(line)
                if m:
                    hits.append(f"{os.path.relpath(path, ROOT)}:{lineno}: {m.group(0)!r}")
    assert not hits, "Banned storage claims found:\n" + "\n".join(hits)


def test_privacy_page_has_one_retention_window():
    with open(os.path.join(ROOT, "app.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert "90-minute" not in src, "privacy page must not mention a 90-minute window"
    assert "15 minutes" in src


@pytest.mark.parametrize("phrase", ["never stored", "Nothing stored", "No data stored", "NO STORAGE"])
def test_pattern_catches_each_banned_phrase(phrase):
    assert BANNED.search(f"xx {phrase} xx")
