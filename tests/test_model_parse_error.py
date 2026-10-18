"""
Nightly debug run: when the AI answered something that isn't JSON on every retry
(e.g. output cut off at the token limit — temperature 0 repeats it), the visitor
saw the internal parser text "Cannot parse model output (length=N). Model may
have returned incomplete JSON." or "No JSON found in model output". That is a
server-side failure: it now shows the generic "Processing failed" text and the
details stay in the server log. The credit is still refunded.
"""
import io
import json

import pytest

import app as appmod


class _Resp:
    status_code = 200
    headers = {}
    text = ""

    def __init__(self, content):
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _errors(resp):
    out = []
    for line in resp.get_data(as_text=True).splitlines():
        if line.startswith("data:"):
            evt = json.loads(line[5:].strip())
            if "error" in evt:
                out.append(evt["error"])
    return out


@pytest.mark.parametrize("content", [
    '{"title": "Cell biology" "sections": [{"title": "Mitosis"}]}',        # malformed
    "Sorry, I can't help with that.",                                    # no JSON at all
])
def test_unparseable_model_output_is_not_shown_raw(monkeypatch, content):
    monkeypatch.setattr(appmod, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(appmod.http, "post", lambda *a, **k: _Resp(content))
    monkeypatch.setattr(appmod.time, "sleep", lambda s: None)
    monkeypatch.setattr(appmod, "_groq_pace", lambda n: None)
    client = appmod.app.test_client()
    resp = client.post("/api/summarize-stream",
                       data={"file": (io.BytesIO(b"Mitosis has four phases. " * 20), "notes.txt"),
                             "language": "en"},
                       content_type="multipart/form-data",
                       headers={"X-Device-Id": "dev-model-parse-%d" % len(content)})
    errs = _errors(resp)
    assert len(errs) == 1, errs
    for raw in ("model output", "length=", "JSON"):
        assert raw not in errs[0], errs[0]


def test_extract_json_still_raises_value_error():
    # Callers that catch ValueError around _extract_json keep working.
    with pytest.raises(ValueError):
        appmod._extract_json("no json here")
    assert appmod._extract_json('{"a": 1}') == {"a": 1}
