"""
Nightly debug run: POST /api/lead did `request.get_json(silent=True) or {}` and
then data.get(...), so a JSON array, string or number body raised AttributeError
and this public, unauthenticated endpoint answered an HTML 500 page instead of
the JSON 400 it gives for any other bad input. Nothing is stored either way.
"""
import pytest

import app as appmod


@pytest.mark.parametrize("body", [[1], "s", 3, True])
def test_non_object_lead_body_is_json_400(monkeypatch, body):
    monkeypatch.setattr(appmod, "_check_rate_limit", lambda *a, **k: True)
    monkeypatch.setattr(appmod, "_get_sb", lambda: None)
    appmod.app.config["TESTING"] = False   # a real 500 page, not a raised exception
    try:
        r = appmod.app.test_client().post("/api/lead", json=body)
    finally:
        appmod.app.config["TESTING"] = True
    assert r.status_code == 400, r.status_code
    assert r.is_json and "error" in r.get_json()


def test_valid_lead_still_accepted(monkeypatch):
    monkeypatch.setattr(appmod, "_check_rate_limit", lambda *a, **k: True)
    monkeypatch.setattr(appmod, "_get_sb", lambda: None)
    r = appmod.app.test_client().post("/api/lead", json={"email": "a@example.com"})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
