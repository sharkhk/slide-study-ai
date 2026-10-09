"""
Nightly debug run: /admin/block and /admin/unblock called
request.json.get("ip", "").strip(), and /admin/user/grant and /admin/user/cancel
did `request.get_json(silent=True) or {}` then .get(...). A non-object JSON body,
or a null / non-string "ip", raised and answered an HTML 500 page instead of a
JSON 400. Admin-only; nothing was changed by the failing requests.
"""
import pytest

import app as appmod

TOKEN = "t" * 40


@pytest.fixture
def post(monkeypatch):
    monkeypatch.setattr(appmod, "ADMIN_TOKEN", TOKEN)
    monkeypatch.setattr(appmod, "_get_sb", lambda: None)
    def _post(path, body):
        appmod.app.config["TESTING"] = False   # a real 500 page, not a raised exception
        try:
            return appmod.app.test_client().post(path, json=body, headers={"X-Admin-Token": TOKEN})
        finally:
            appmod.app.config["TESTING"] = True
    return _post


@pytest.mark.parametrize("path", ["/admin/block", "/admin/unblock"])
@pytest.mark.parametrize("body", [[1], "s", 3, {"ip": None}, {"ip": 5}, {"ip": []}])
def test_block_bad_body_is_json_400(post, path, body):
    r = post(path, body)
    assert r.status_code == 400, r.status_code
    assert r.is_json and "error" in r.get_json()


@pytest.mark.parametrize("path", ["/admin/user/grant", "/admin/user/cancel"])
@pytest.mark.parametrize("body", [[1], "s", 3])
def test_user_action_bad_body_is_json_400(post, path, body):
    r = post(path, body)
    assert r.status_code == 400, r.status_code
    assert r.is_json and r.get_json() == {"error": "invalid user_id"}


def test_block_and_unblock_still_work(post):
    ip = "203.0.113.77"
    r = post("/admin/block", {"ip": " %s " % ip})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "blocked": ip}
    assert ip in appmod._blocked_ips
    r = post("/admin/unblock", {"ip": ip})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "unblocked": ip}
    assert ip not in appmod._blocked_ips
