"""
Nightly debug run: /api/summarize-stream refused an upload with no file or a
file type it can't read with the English "No file uploaded" / "Unsupported file
type. Supported: ..." even on an Arabic request. The client shows that text as
sent, so an Arabic visitor got English. Both now follow the request's language;
English is unchanged. Nothing is charged on either path.
"""
import io

import pytest

import app as appmod


def _has_arabic(s):
    return any("؀" <= ch <= "ۿ" for ch in s or "")


_UNSUPPORTED_EN = "Unsupported file type. Supported: .pptx, .ppt, .pdf, .docx, .doc, .txt"


@pytest.mark.parametrize("with_file,en", [
    (False, "No file uploaded"),
    (True, _UNSUPPORTED_EN),
])
@pytest.mark.parametrize("lang,arabic", [("ar", True), ("en", False)])
def test_precharge_upload_refusal_in_request_language(monkeypatch, lang, arabic, with_file, en):
    monkeypatch.setattr(appmod, "_auth_optional", lambda req: None)
    charged = []
    monkeypatch.setattr(appmod, "_charge_credit", lambda *a, **k: charged.append(1))
    data = {"language": lang}
    if with_file:
        data["file"] = (io.BytesIO(b"x"), "lecture.key")
    r = appmod.app.test_client().post("/api/summarize-stream", data=data,
                                      content_type="multipart/form-data")
    assert r.status_code == 400
    msg = r.get_json()["error"]
    assert _has_arabic(msg) is arabic, msg
    if not arabic:
        assert msg == en
    assert not charged


def test_arabic_browser_without_language_field(monkeypatch):
    monkeypatch.setattr(appmod, "_auth_optional", lambda req: None)
    r = appmod.app.test_client().post("/api/summarize-stream", data={},
                                      content_type="multipart/form-data",
                                      headers={"Accept-Language": "ar"})
    assert r.status_code == 400
    assert _has_arabic(r.get_json()["error"])
