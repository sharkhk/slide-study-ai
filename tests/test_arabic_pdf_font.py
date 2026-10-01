"""
Arabic PDF font (reported 2026-10-01).

_ensure_arabic_font() used to download NotoNaskhArabic from GitHub into /tmp on
the first Arabic build. Any network hiccup, GitHub rate limit or cold /tmp made
the WHOLE Arabic PDF silently fall back to Helvetica, which has no Arabic glyphs
(every letter a box), and the download ran under a global lock, so concurrent
builds queued behind it for up to 30 s.

The font now ships in fonts/ and is registered from there with no network. The
GitHub download is only a last resort: it runs outside the lock and a failure is
remembered for 5 minutes. Registration stays lazy (first Arabic build), never at
import time. Everything here runs offline: the network is monkeypatched to fail.
"""
import io
import json
import os
import struct
import subprocess
import sys
import threading

import pytest
from pypdf import PdfReader
from reportlab.pdfbase import pdfmetrics

import app as appmod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = os.path.join(ROOT, "fonts", "NotoNaskhArabic-Regular.ttf")
AR_GUIDE = {
    "title": "اختبار",                     # اختبار
    "sections": [{"title": "قسم",                          # قسم
                  "bullets": ["الخلية وحدة الحياة"]}],
    "keywords": [], "flashcards": [], "mcqs": [], "language": "ar",
}


@pytest.fixture
def no_network(monkeypatch, tmp_path):
    """Fail every HTTP call, hide any font a previous run downloaded to /tmp and
    forget that the font was registered. Returns the list of attempted calls."""
    calls = []

    def _offline(*a, **k):
        calls.append(a)
        raise OSError("network disabled in tests")

    monkeypatch.setattr(appmod.http, "get", _offline)
    monkeypatch.setattr(appmod, "_ARABIC_FONT_PATH", str(tmp_path / "not-downloaded.ttf"))
    monkeypatch.setattr(appmod, "_arabic_font_ok", False)
    # reportlab keeps the first font registered under a name/face for the life of
    # the process; drop it (restored afterwards) so registration really reruns.
    monkeypatch.delitem(pdfmetrics._fonts, appmod._ARABIC_FONT, raising=False)
    monkeypatch.delitem(pdfmetrics._dynFaceNames, b"NotoNaskhArabic-Regular", raising=False)
    monkeypatch.setattr(appmod, "_arabic_font_fail_at", None, raising=False)
    monkeypatch.setattr(appmod, "_arabic_font_downloading", False, raising=False)
    return calls


def _pdf_base_fonts(pdf_bytes):
    names = set()
    for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
        fonts = page["/Resources"].get("/Font", {})
        for ref in fonts.values():
            names.add(str(ref.get_object()["/BaseFont"]))
    return names


def test_font_and_licence_ship_in_the_repo():
    assert os.path.isfile(BUNDLED), "fonts/NotoNaskhArabic-Regular.ttf must be committed"
    face = appmod._TTFont("BundledProbe", BUNDLED).face
    assert face.name == b"NotoNaskhArabic-Regular"
    lic = open(os.path.join(ROOT, "fonts", "OFL.txt"), encoding="utf-8").read()
    assert "SIL OPEN FONT LICENSE Version 1.1" in lic


def _font_name_record(path, name_id):
    """A Windows-platform (3) record of the TTF 'name' table, decoded."""
    data = open(path, "rb").read()
    num_tables = struct.unpack(">H", data[4:6])[0]
    for i in range(num_tables):
        tag, _, offset, _ = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
        if tag == b"name":
            _, count, str_off = struct.unpack(">HHH", data[offset:offset + 6])
            for j in range(count):
                rec = data[offset + 6 + 12 * j: offset + 18 + 12 * j]
                pid, _, _, nid, length, off = struct.unpack(">HHHHHH", rec)
                if pid == 3 and nid == name_id:
                    start = offset + str_off + off
                    return data[start:start + length].decode("utf-16-be")
    return None


def test_licence_names_the_bundled_fonts_own_copyright_holder():
    # OFL condition 2: the copyright notice travels with the font. The standalone
    # OFL.txt must carry the SAME notice as the font file itself (the hinted
    # googlefonts/noto-fonts build, v2.012), not another Noto release's.
    notice = _font_name_record(BUNDLED, 0)
    version = _font_name_record(BUNDLED, 5)
    assert notice == "Copyright 2019-2021 Google LLC. All Rights Reserved."
    assert version.startswith("Version 2.012")
    lic = open(os.path.join(ROOT, "fonts", "OFL.txt"), encoding="utf-8").read()
    assert lic.startswith(notice), "OFL.txt must open with the font's own copyright notice"
    assert "Noto Naskh Arabic 2.012" in lic and "github.com/googlefonts/noto-fonts" in lic
    assert "notofonts/arabic" not in lic and "Copyright 2022 The Noto Project Authors" not in lic


def test_font_registers_from_the_repo_with_no_network(no_network):
    assert appmod._ensure_arabic_font() is True
    assert no_network == [], "the bundled font must be used before any download"
    face = pdfmetrics.getFont(appmod._ARABIC_FONT).face
    assert face.name == b"NotoNaskhArabic-Regular"
    assert os.path.normcase(os.path.abspath(face.filename)) == os.path.normcase(BUNDLED)


def test_arabic_pdf_embeds_the_arabic_font_with_no_network(no_network):
    pdf = appmod.build_pdf(json.loads(json.dumps(AR_GUIDE)), "ar", "t").read()
    fonts = _pdf_base_fonts(pdf)
    assert any("NotoNaskhArabic" in f for f in fonts), fonts


def test_last_resort_download_runs_outside_the_lock_and_failure_is_cached(no_network, monkeypatch, tmp_path):
    monkeypatch.setattr(appmod, "_ARABIC_FONT_BUNDLED", str(tmp_path / "missing.ttf"), raising=False)
    held = []

    def _offline(*a, **k):
        held.append(appmod._arabic_font_lock.locked())
        raise OSError("network disabled in tests")

    monkeypatch.setattr(appmod.http, "get", _offline)
    assert appmod._ensure_arabic_font() is False
    assert held == [False], "the download must not hold the global font lock"
    # A second build inside the 5-minute window does not try (and wait) again.
    assert appmod._ensure_arabic_font() is False
    assert len(held) == 1
    # After 5 minutes it retries.
    monkeypatch.setattr(appmod, "_arabic_font_fail_at", appmod._arabic_font_fail_at - 301)
    assert appmod._ensure_arabic_font() is False
    assert len(held) == 2


def test_last_resort_download_still_works_when_the_bundled_file_is_missing(no_network, monkeypatch, tmp_path):
    monkeypatch.setattr(appmod, "_ARABIC_FONT_BUNDLED", str(tmp_path / "missing.ttf"), raising=False)
    font_bytes = open(BUNDLED, "rb").read()

    class _Resp:
        content = font_bytes

        def raise_for_status(self):
            pass

    monkeypatch.setattr(appmod.http, "get", lambda *a, **k: _Resp())    # fake "GitHub", no network
    assert appmod._ensure_arabic_font() is True
    cached = appmod._ARABIC_FONT_PATH
    assert os.path.getsize(cached) == len(font_bytes)
    assert os.path.normcase(pdfmetrics.getFont(appmod._ARABIC_FONT).face.filename) == os.path.normcase(cached)
    assert [p for p in os.listdir(tmp_path) if p.endswith(".part")] == []


def test_concurrent_build_does_not_wait_for_a_download_in_progress(no_network, monkeypatch, tmp_path):
    monkeypatch.setattr(appmod, "_ARABIC_FONT_BUNDLED", str(tmp_path / "missing.ttf"), raising=False)
    started, release = threading.Event(), threading.Event()

    def _slow_offline(*a, **k):
        started.set()
        release.wait(10)
        raise OSError("network disabled in tests")

    monkeypatch.setattr(appmod.http, "get", _slow_offline)
    first = threading.Thread(target=appmod._ensure_arabic_font, daemon=True)
    first.start()
    try:
        assert started.wait(5), "first build never reached the download"
        done = []
        second = threading.Thread(target=lambda: done.append(appmod._ensure_arabic_font()), daemon=True)
        second.start()
        second.join(2)
        assert done == [False], "a second build must not queue behind a running download"
    finally:
        release.set()
        first.join(5)


def test_font_is_not_registered_at_import_time():
    probe = (
        "import json, os, sys; sys.path.insert(0, os.environ['APP_ROOT']); "
        "os.chdir(os.environ['APP_ROOT']); import app as A; "
        "from reportlab.pdfbase import pdfmetrics as M; "
        "print(json.dumps([A._arabic_font_ok, A._ARABIC_FONT in M.getRegisteredFontNames()]))"
    )
    env = {k: v for k, v in os.environ.items()
           if k not in ("SUPABASE_URL", "RENDER", "PRODUCTION", "STRIPE_SECRET_KEY", "GROQ_API_KEY")}
    env["APP_ROOT"] = ROOT
    out = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert json.loads(out.stdout.strip().splitlines()[-1]) == [False, False]
