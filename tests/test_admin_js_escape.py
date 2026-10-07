"""
Stored XSS on the admin dashboard through onclick="...('<value>')" (review, 2026-10-01).

Bug: the dashboard's JS-string escaper HTML-escaped FIRST (' -> &#39;) and only
then tried to backslash-escape ', which by then never matched. Inside an
onclick="..." attribute the browser decodes &#39; back to ' before the JS runs,
so an attacker-controlled visitor IP (CF-Connecting-IP / X-Forwarded-For) or a
subscriber e-mail (' and ` are legal in an e-mail local part) could close the JS
string and run script with full admin power (adminPost sends the cookie and the
CSRF header).

These tests decode each onclick attribute exactly like a browser does (HTML
entity decoding) and then parse the JS call like a JS engine: every argument
must be ONE string literal whose value is the original data, with nothing else
in the handler.

EVERYTHING IS OFFLINE (Supabase is faked). The token is a dummy test value.
"""
import re
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app as appmod

TOKEN = "test-admin-token-not-a-real-secret-0005"
HDR = {"X-Admin-Token": TOKEN}

IP_PAYLOAD = "1.2.3.4');alert(document.domain);//"
EMAIL_PAYLOAD = "x'-alert`1`-'@x.com"
UID_PAYLOAD = "u\\');alert(1);//"
NASTY = [IP_PAYLOAD, "a\\'b", "line\nbreak", "</script><script>alert(1)</script>",
         'dq"); alert(1); //', "\u2028sep\u2029", "x&#39;y", "\\"]


class _Onclicks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.handlers = []

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:              # html.parser decodes entities like a browser
            if k == "onclick" and v:
                self.handlers.append(v)


def _onclicks(html):
    p = _Onclicks()
    p.feed(html)
    return p.handlers


_JS_STR = r"'((?:[^'\\\n\r\u2028\u2029]|\\.)*)'"


def _js_unescape(lit):
    out, i = [], 0
    while i < len(lit):
        ch = lit[i]
        if ch != "\\":
            out.append(ch); i += 1; continue
        nxt = lit[i + 1]
        if nxt == "x":
            out.append(chr(int(lit[i + 2:i + 4], 16))); i += 4
        elif nxt == "u":
            out.append(chr(int(lit[i + 2:i + 6], 16))); i += 6
        else:
            out.append({"n": "\n", "r": "\r", "t": "\t"}.get(nxt, nxt)); i += 2
    # re-join UTF-16 surrogate pairs written as two \\u escapes
    return "".join(out).encode("utf-16", "surrogatepass").decode("utf-16")


def _call_args(handler, fn):
    """Parse `fn('a','b')` strictly; returns the decoded string arguments."""
    m = re.fullmatch(r"%s\(%s(?:,%s)?\)" % (re.escape(fn), _JS_STR, _JS_STR), handler)
    assert m, f"handler is not a single {fn}('...') call: {handler!r}"
    return [_js_unescape(g) for g in m.groups() if g is not None]


@pytest.fixture
def client(monkeypatch):
    appmod.app.config["TESTING"] = True
    monkeypatch.setattr(appmod, "ADMIN_TOKEN", TOKEN)
    monkeypatch.setattr(appmod, "_rate_limit", {})
    return appmod.app.test_client()


@pytest.fixture
def visitors(monkeypatch):
    def put(ips, blocked=()):
        monkeypatch.setattr(appmod, "_visitors", [
            {"ip": ip, "time": "t", "path": "/", "ua": "ua", "country": "", "city": "", "region": ""}
            for ip in ips])
        monkeypatch.setattr(appmod, "_blocked_ips", set(blocked))
    return put


def _fake_users(monkeypatch, users):
    sb = MagicMock()

    def table(name):
        t = MagicMock()
        q = t.select.return_value
        data = users if name == "users" else []
        q.limit.return_value.execute.return_value = SimpleNamespace(data=data, count=len(data))
        q.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=data, count=len(data))
        return t
    sb.table.side_effect = table
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)


@pytest.mark.parametrize("ip", NASTY)
def test_block_button_passes_the_visitor_ip_as_one_string(client, visitors, ip):
    visitors([ip])
    html = client.get("/admin", headers=HDR).get_data(as_text=True)
    calls = [h for h in _onclicks(html) if h.startswith("blockIp(")]
    # (the test client's own /admin visit is tracked too, so there is a second row)
    args = [_call_args(h, "blockIp") for h in calls]
    assert args.count([ip]) == 1, args


@pytest.mark.parametrize("ip", NASTY)
def test_unblock_buttons_pass_the_ip_as_one_string(client, visitors, ip):
    visitors([ip], blocked=[ip])
    html = client.get("/admin", headers=HDR).get_data(as_text=True)
    calls = [h for h in _onclicks(html) if h.startswith("unblock(")]
    args = [_call_args(h, "unblock") for h in calls]
    assert args.count([ip]) == 2, args     # the visitor row + the blocked-IPs panel


def test_subscriber_buttons_pass_uid_and_email_as_strings(client, visitors, monkeypatch, legacy_tokens):
    # Token mode (ALIMNE_FREE_MODE=0): the "+ Tokens" and the Cancel button are both there.
    visitors([])
    _fake_users(monkeypatch, [{"id": UID_PAYLOAD, "email": EMAIL_PAYLOAD, "name": "n",
                               "subscription_status": "active", "subscription_id": "sub_x",
                               "tokens_remaining": 1, "created_at": "2026-10-01"}])
    html = client.get("/admin", headers=HDR).get_data(as_text=True)
    handlers = _onclicks(html)
    for fn in ("grantTokens", "cancelSub"):
        calls = [h for h in handlers if h.startswith(fn + "(")]
        assert len(calls) == 1, (fn, handlers)
        assert _call_args(calls[0], fn) == [UID_PAYLOAD, EMAIL_PAYLOAD]


def test_free_mode_cancel_button_passes_uid_and_email_as_strings(client, visitors, monkeypatch):
    # Free mode: no "+ Tokens" action at all; Cancel stays for a legacy active subscriber.
    visitors([])
    _fake_users(monkeypatch, [{"id": UID_PAYLOAD, "email": EMAIL_PAYLOAD, "name": "n",
                               "subscription_status": "active", "subscription_id": "sub_x",
                               "tokens_remaining": 1, "created_at": "2026-10-01"}])
    html = client.get("/admin", headers=HDR).get_data(as_text=True)
    handlers = _onclicks(html)
    assert not [h for h in handlers if h.startswith("grantTokens(")]
    calls = [h for h in handlers if h.startswith("cancelSub(")]
    assert len(calls) == 1, handlers
    assert _call_args(calls[0], "cancelSub") == [UID_PAYLOAD, EMAIL_PAYLOAD]


def test_plain_values_still_render_readably(client, visitors):
    visitors(["203.0.113.9"])
    html = client.get("/admin", headers=HDR).get_data(as_text=True)
    assert "blockIp('203.0.113.9')" in _onclicks(html)
