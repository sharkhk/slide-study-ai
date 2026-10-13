"""
Two near-simultaneous Share requests for ONE guide must create ONE public link.

The idempotency check (job["share_slug"]) used to run before the database insert
without holding anything across it, so a second tap that arrived while the first
insert was still in flight also inserted: two shared_guides rows and two
different links for the same guide. Offline: Supabase is a mock.
Run:  python -m pytest -q
"""
import threading
import time
from unittest.mock import MagicMock

import app as appmod


def _store():
    jid = appmod.uuid.uuid4().hex
    guide = {"title": "T", "subtitle": "", "language": "en",
             "sections": [{"title": "S", "bullets": ["b"]}],
             "flashcards": [], "mcqs": [], "keywords": [], "objectives": []}
    appmod.store_job(jid, b"%PDF-1.4 test", "# T\n", guide, None, "t_study_guide.pdf")
    return jid


def test_two_simultaneous_shares_make_one_link(monkeypatch):
    appmod.app.config["TESTING"] = True
    inserted, entered, release = [], threading.Event(), threading.Event()

    def _insert(row):
        inserted.append(row["slug"])
        if len(inserted) == 1:          # hold the first insert open, as a slow DB would
            entered.set()
            release.wait(3)
        return MagicMock()

    sb = MagicMock()
    sb.table.return_value.insert.side_effect = _insert
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)
    jid = _store()

    out = {}
    def _share(name):
        r = appmod.app.test_client().post(f"/api/share/{jid}")
        out[name] = (r.status_code, r.get_json())

    a = threading.Thread(target=_share, args=("a",))
    a.start()
    assert entered.wait(3)
    b = threading.Thread(target=_share, args=("b",))
    b.start()
    time.sleep(0.3)                     # the second tap arrives while the first insert is open
    release.set()
    a.join(5); b.join(5)

    assert out["a"][0] == 200 and out["b"][0] == 200
    assert len(inserted) == 1
    assert out["a"][1]["slug"] == out["b"][1]["slug"] == inserted[0]


def test_share_after_failed_insert_can_retry(monkeypatch):
    """A failed share leaves no slug behind, so the next tap tries again."""
    appmod.app.config["TESTING"] = True
    sb = MagicMock()
    sb.table.return_value.insert.side_effect = [Exception("db down"), MagicMock()]
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)
    jid = _store()
    c = appmod.app.test_client()
    assert c.post(f"/api/share/{jid}").status_code == 500
    r = c.post(f"/api/share/{jid}")
    assert r.status_code == 200 and r.get_json()["slug"]
