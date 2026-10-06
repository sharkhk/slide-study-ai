"""
Nightly debug run: POST /api/referral/apply called .strip() on the "code" field
without checking its type, so {"code": null}, {"code": 123} or a JSON array body
answered an HTML 500 page instead of the JSON 400 'no_code'. Nothing was changed
in the database.
"""
import pytest

import app as appmod


@pytest.mark.parametrize("body", [
    {"code": None}, {"code": 123}, {"code": ["ABC"]}, {"code": {"x": 1}}, ["ABC"], "ABC",
])
def test_bad_referral_code_is_400_json(monkeypatch, body):
    monkeypatch.setattr(appmod, "_auth_check", lambda req: ("user-1", None))
    monkeypatch.setattr(appmod, "_get_sb", lambda: None)
    appmod.app.config["TESTING"] = False   # a real 500 page, not a raised exception
    try:
        r = appmod.app.test_client().post("/api/referral/apply", json=body)
    finally:
        appmod.app.config["TESTING"] = True
    assert r.status_code == 400, r.status_code
    assert r.is_json and r.get_json() == {"success": False, "reason": "no_code"}


def test_string_code_still_reaches_lookup(monkeypatch):
    monkeypatch.setattr(appmod, "_auth_check", lambda req: ("user-1", None))
    monkeypatch.setattr(appmod, "_get_sb", lambda: None)
    r = appmod.app.test_client().post("/api/referral/apply", json={"code": " abc "})
    assert r.status_code == 200
    assert r.get_json() == {"success": False, "reason": "unavailable"}
