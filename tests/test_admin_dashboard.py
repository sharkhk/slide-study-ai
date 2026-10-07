"""
Offline tests for the /admin dashboard of the free, sign-up-first product.

WHAT THIS GUARDS
    1. The pure data helpers (no Flask, no Supabase): sign-ups today / yesterday /
       last 7 days / total and the 14-day series across a UTC day boundary; the
       funnel numbers and the gate -> sign-up rate, including division by zero;
       the daily AI budget (24 h window, 80% warning); the live generation gate.
    2. The page: it renders with no Supabase, with an empty database and when any
       single query fails (a small "could not load" note, everything else stays);
       every read is bounded, read-only and goes through the service-role client.
    3. Escaping: hostile e-mails / names / user agents / paths / statuses never
       reach the page as markup or script, and no secret is ever rendered.
    4. Free mode has no Tokens column, no "+ Tokens" action and no MRR card; legacy
       mode (ALIMNE_FREE_MODE=0) gets them back exactly.
    5. /admin still needs the cookie or the X-Admin-Token header.

EVERYTHING IS OFFLINE: Supabase is an in-memory fake that really applies the
filters, the order and the limit of each query. The token is a dummy test value.
Run:  python -m pytest -q
"""
import re
import threading
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest

import app as appmod

UTC = timezone.utc
TOKEN = "test-admin-token-not-a-real-secret-0077"
HDR = {"X-Admin-Token": TOKEN}
NOW = datetime(2026, 10, 7, 0, 30, 0, tzinfo=UTC)    # a Wednesday, 30 minutes after a UTC midnight
DB_ERROR_CANARY = "boom-db-detail-must-not-be-rendered"


# ── an in-memory Supabase that applies filters / order / limit for real ──────────
def _cmp(v):
    """Comparable form of a stored or filter value (ISO timestamps as datetimes)."""
    if isinstance(v, str):
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00").replace(" ", "T", 1))
            return d if d.tzinfo else d.replace(tzinfo=UTC)
        except ValueError:
            return v
    return v


def _match(row, op, col, val):
    v = row.get(col)
    if op == "like":
        rx = "^" + ".*".join(re.escape(p) for p in str(val).split("%")) + "$"
        return isinstance(v, str) and re.match(rx, v, re.S) is not None
    if op == "in":
        return v in val
    a, b = _cmp(v), _cmp(val)
    try:
        if op == "eq":
            return a == b
        if op == "gte":
            return a >= b
        if op == "gt":
            return a > b
        if op == "lte":
            return a <= b
        if op == "lt":
            return a < b
    except TypeError:
        return False
    raise AssertionError(f"unknown filter {op}")


class _Query:
    def __init__(self, sb, table):
        self.sb, self.table = sb, table
        self.cols, self.count_mode = "*", None
        self.filters, self.orders, self.lim = [], [], None

    def select(self, cols="*", count=None, **_):
        self.cols, self.count_mode = cols, count
        return self

    def _f(self, op, col, val):
        self.filters.append((op, col, val))
        return self

    def eq(self, c, v):   return self._f("eq", c, v)
    def gte(self, c, v):  return self._f("gte", c, v)
    def gt(self, c, v):   return self._f("gt", c, v)
    def lte(self, c, v):  return self._f("lte", c, v)
    def lt(self, c, v):   return self._f("lt", c, v)
    def like(self, c, p): return self._f("like", c, p)
    def in_(self, c, vs): return self._f("in", c, list(vs))

    def order(self, col, desc=False, **_):
        self.orders.append((col, bool(desc)))
        return self

    def limit(self, n, **_):
        self.lim = n
        return self

    def execute(self):
        self.sb.queries.append(self)
        if self.table in self.sb.fail:
            raise RuntimeError(f"{DB_ERROR_CANARY}: relation {self.table} is unavailable")
        cols = None if self.cols == "*" else [c.strip() for c in self.cols.split(",")]
        gone = self.sb.missing.get(self.table, set())
        if cols and gone & set(cols):
            raise RuntimeError(f"{DB_ERROR_CANARY}: column {sorted(gone & set(cols))[0]} does not exist")
        rows = [r for r in self.sb.tables.get(self.table, [])
                if all(_match(r, op, c, v) for op, c, v in self.filters)]
        total = len(rows)
        for col, desc in reversed(self.orders):
            rows.sort(key=lambda r: str(r.get(col) or ""), reverse=desc)
        cap = self.sb.max_rows if self.lim is None else min(self.lim, self.sb.max_rows)
        rows = rows[:cap]
        if cols:
            rows = [{c: r.get(c) for c in cols} for r in rows]
        else:
            rows = [{k: v for k, v in r.items() if k not in gone} for r in rows]
        return SimpleNamespace(data=rows, count=total if self.count_mode else None)


class FakeSB:
    """tables: {name: [row dicts]}; fail: tables whose queries raise; missing:
    {table: {columns that do not exist}}; max_rows: PostgREST's response cap."""
    def __init__(self, tables=None, fail=(), missing=None, max_rows=10**9):
        self.tables = {"users": [], "anon_usage": [], "visit_stats": [], "usage_events": [], "leads": []}
        self.tables.update(tables or {})
        self.fail, self.missing, self.max_rows = set(fail), dict(missing or {}), max_rows
        self.queries = []

    def table(self, name):
        return _Query(self, name)

    def rpc(self, name, params=None):
        raise AssertionError(f"the dashboard is read-only and must not call an RPC ({name})")


# ── data builders ────────────────────────────────────────────────────────────────
def _iso(dt):
    return dt.isoformat()


def _uid(i):
    return f"00000000-0000-4000-8000-{i:012d}"


def _user(i, created, **kw):
    u = {"id": _uid(i), "email": f"user{i}@example.com", "name": f"User {i}",
         "created_at": created if isinstance(created, str) or created is None else _iso(created),
         "generations_count": 0, "last_used_at": None, "referred_by": None,
         "referral_code": f"REF{i:04d}", "referral_paid": False,
         "subscription_status": "free", "subscription_id": None,
         "subscription_period_end": None, "tokens_remaining": 3}
    u.update(kw)
    return u


def _counter(key, count, last_at, window_start=None):
    return {"key": key, "count": count,
            "window_start": _iso(window_start if window_start is not None else last_at),
            "last_at": _iso(last_at)}


def sample_db(now=NOW, gate_limit=3):
    """A realistic week: ~40 accounts over 14 days, ~120 anonymous devices (some at
    the sign-in gate), 14 days of visits, the AI budget at 61%, a few generations.
    Also used to render the visual preview of the dashboard."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    per_day = [1, 0, 2, 1, 3, 2, 4, 2, 3, 5, 4, 6, 4, 3]      # oldest -> today; 40 in all
    users, i = [], 0
    for back, n in zip(range(13, -1, -1), per_day):
        for k in range(n):
            i += 1
            # day 0 (today) is only 30 minutes old at NOW: keep its sign-ups inside it
            minute = k * 7 if back == 0 else 60 + k * 97
            created = today - timedelta(days=back) + timedelta(minutes=minute)
            users.append(_user(i, created, name=["Aisha Khan", "Omar Said", "Lina Haddad", "Yusuf Ali",
                                                 "Sara Nasser", "Hamad Saleh"][i % 6]))
    for u in users[:6]:                                         # token-era accounts with a lifetime count
        u["generations_count"] = 3 + int(u["id"][-2:]) % 5
        u["last_used_at"] = _iso(today - timedelta(days=9, hours=3))
    users[1].update(subscription_status="active", subscription_id="sub_legacy_1",
                    subscription_period_end=_iso(today + timedelta(days=19)), tokens_remaining=27)
    users[3].update(subscription_status="canceling", subscription_id="sub_legacy_2",
                    subscription_period_end=_iso(today + timedelta(days=6)), tokens_remaining=11)
    users[30]["referred_by"] = users[2]["id"]
    users[33]["referred_by"] = users[2]["id"]
    users[36]["referred_by"] = users[20]["id"]

    anon = []
    for d in range(120):                                        # anonymous devices of the last 7 days
        count = gate_limit if d % 3 == 0 else (1 if d % 3 == 1 else 2)
        last = now - timedelta(minutes=5 + d * 71)              # 5 min .. ~5.9 days ago
        anon.append(_counter(f"gate:dev:{d:032x}", count, last, window_start=last - timedelta(hours=2)))
    for d in range(15):                                         # older than the 7-day window
        anon.append(_counter(f"gate:dev:old{d:029x}", gate_limit, now - timedelta(days=9, hours=d)))
    for d in range(30):                                         # the daily fair-use device counters: not gate rows
        anon.append(_counter(f"fair:dev:{d:032x}", 4, now - timedelta(hours=d)))
    anon.append(_counter("fair:global", 1220, now - timedelta(minutes=1), window_start=now - timedelta(hours=5)))
    anon.append(_counter("fair:global:anon", 700, now - timedelta(minutes=2), window_start=now - timedelta(hours=5)))
    for u in users[-12:-2]:                                     # accounts active since Alimne went free
        anon.append(_counter(f"fair:user:{u['id']}", 2, now - timedelta(hours=3),
                             window_start=now - timedelta(hours=6)))

    visits = [{"day": (today - timedelta(days=b)).strftime("%Y-%m-%d"), "count": 180 + 23 * ((13 - b) % 5) + 9 * (13 - b)}
              for b in range(13, -1, -1)]
    visits.append({"day": "2026-08-01", "count": 5000})        # old traffic: all-time only

    events = []
    for n, (kind, source, city, country) in enumerate([
            ("user", "file", "Dubai", "United Arab Emirates"), ("anon", "youtube", "Riyadh", "Saudi Arabia"),
            ("anon", "file", "Cairo", "Egypt"), ("demo", "demo", "", ""), ("user", "text", "Amman", "Jordan"),
            ("anon", "file", "Doha", "Qatar"), ("user", "file", "Abu Dhabi", "United Arab Emirates")]):
        events.append({"kind": kind, "source": source, "city": city, "country": country, "title": "Lecture",
                       "created_at": _iso(now - timedelta(minutes=10 + n * 47))})
    leads = [{"email": "old.lead@example.com", "source": "paywall", "created_at": _iso(now - timedelta(days=20))}]
    return FakeSB({"users": users, "anon_usage": anon, "visit_stats": visits,
                   "usage_events": events, "leads": leads})


# ── page helpers ─────────────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch):
    appmod.app.config["TESTING"] = True
    monkeypatch.setattr(appmod, "ADMIN_TOKEN", TOKEN)
    monkeypatch.setattr(appmod, "_rate_limit", {})
    monkeypatch.setattr(appmod, "_visitors", [])
    monkeypatch.setattr(appmod, "_blocked_ips", set())
    monkeypatch.setattr(appmod, "_admin_now", lambda: NOW)
    return appmod.app.test_client()


def _use(monkeypatch, sb):
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)
    return sb


def _page(client):
    r = client.get("/admin", headers=HDR)
    assert r.status_code == 200
    return r.get_data(as_text=True)


def _page_of(client, monkeypatch, sb):
    """The page rendered from the database `sb`."""
    _use(monkeypatch, sb)
    return _page(client)


def _num(html, key):
    """Text of the element carrying data-num="<key>"."""
    m = re.search(r'data-num="%s"[^>]*>([^<]*)<' % re.escape(key), html)
    assert m, f'no data-num="{key}" on the page'
    return m.group(1).strip()


class _Doc(HTMLParser):
    """The page as a browser sees it: tags, decoded attributes, decoded text."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.attrs, self.text, self.rows = [], [], [], []
        self._script = False
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        d = dict(attrs)
        self.attrs.append((tag, d))
        if tag == "tr" and "subrow" in (d.get("class") or "").split():
            self.rows.append(d)
        if tag == "script":
            self._script = True
            self.scripts.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self._script = False

    def handle_data(self, data):
        if self._script:
            self.scripts[-1] += data
        else:
            self.text.append(data)


def _doc(html):
    d = _Doc()
    d.feed(html)
    d.close()
    return d


SECTIONS = ["sec-signups", "sec-funnel", "sec-budget", "sec-users", "sec-visitors"]


# ═════════════════════════ 1. pure helpers ═══════════════════════════════════════
BOUNDARY_USERS = [
    {"created_at": "2026-10-07T00:00:00+00:00"},           # today: the first second of the UTC day
    {"created_at": "2026-10-07T00:29:59.123456+00:00"},    # today
    {"created_at": "2026-10-06T19:10:00-05:00"},           # = 00:10 UTC on the 7th: today, though its own date says the 6th
    {"created_at": "2026-10-06T23:59:59.999999+00:00"},    # yesterday: the last instant of it
    {"created_at": "2026-10-07T01:30:00+03:00"},           # = 22:30 UTC on the 6th: yesterday, though its own date says the 7th
    {"created_at": "2026-10-06 12:00:00+00"},              # yesterday, in Postgres' text form
    {"created_at": "2026-10-01T00:00:00Z"},                # 6 days ago: the oldest day of "last 7 days"
    {"created_at": "2026-09-30T23:59:59Z"},                # 7 days ago: outside "last 7 days", inside the chart
    {"created_at": "2026-09-24T00:00:00Z"},                # the first bar of the 14-day chart
    {"created_at": "2026-09-23T23:59:59Z"},                # one second too old for the chart
    {"created_at": None}, {"created_at": "not a date"}, {},  # undated: they count in the total only
]


def test_signup_stats_across_a_utc_day_boundary():
    s = appmod._admin_signup_stats(BOUNDARY_USERS, NOW)
    assert (s["today"], s["yesterday"], s["last7"], s["total"]) == (3, 3, 7, 13)
    series = s["series"]
    assert [p["day"] for p in series] == [(datetime(2026, 9, 24) + timedelta(days=i)).strftime("%Y-%m-%d")
                                          for i in range(14)]
    counts = {p["day"]: p["count"] for p in series if p["count"]}
    assert counts == {"2026-09-24": 1, "2026-09-30": 1, "2026-10-01": 1, "2026-10-06": 3, "2026-10-07": 3}
    assert [p["today"] for p in series] == [False] * 13 + [True]
    assert series[-1]["label"] == "Wed 7 Oct" and series[0]["label"] == "Thu 24 Sep"
    assert sum(p["count"] for p in series[-7:]) == s["last7"]      # the card and the last 7 bars agree


def test_signup_stats_one_minute_before_midnight_utc():
    s = appmod._admin_signup_stats(BOUNDARY_USERS, datetime(2026, 10, 6, 23, 59, tzinfo=UTC))
    # "today" is now the 6th; the three sign-ups stamped on the 7th are not in any day yet
    assert (s["today"], s["yesterday"]) == (3, 0)
    assert s["series"][-1]["day"] == "2026-10-06" and s["series"][-1]["today"] is True
    assert s["last7"] == 3 + 1 + 1                                   # the 6th, the 1st, and the 30th


def test_signup_stats_total_prefers_the_exact_database_count():
    assert appmod._admin_signup_stats(BOUNDARY_USERS, NOW, total=5000)["total"] == 5000
    assert appmod._admin_signup_stats(BOUNDARY_USERS, NOW, total=2)["total"] == 13     # never below what we hold
    assert appmod._admin_signup_stats([], NOW)["total"] == 0
    assert appmod._admin_signup_stats(None, NOW)["series"][-1]["count"] == 0


def test_signup_stats_accepts_a_naive_now_as_utc():
    a = appmod._admin_signup_stats(BOUNDARY_USERS, datetime(2026, 10, 7, 0, 30))
    assert (a["today"], a["yesterday"]) == (3, 3)


@pytest.mark.parametrize("junk", [
    None, "", "not a date", 0, 12345, 3.5, [], {}, object(), "9" * 5000, "2026-13-45T99:99:99Z",
    "0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00", '2026-10-06"><script>alert(1)</script>',
])
def test_timestamp_parser_never_raises(junk):
    assert appmod._admin_ts(junk) is None
    assert appmod._admin_date(junk) == "" and appmod._admin_when(junk) == "—"


def test_timestamp_parser_reads_what_supabase_sends():
    want = datetime(2026, 10, 6, 21, 30, tzinfo=UTC)
    for text in ("2026-10-06T21:30:00+00:00", "2026-10-06T21:30:00Z", "2026-10-06 21:30:00+00",
                 "2026-10-06T21:30:00.000000+00:00", "2026-10-07T00:30:00+03:00", "2026-10-06T21:30:00"):
        assert appmod._admin_ts(text) == want, text
    assert appmod._admin_ts("2026-10-06") == datetime(2026, 10, 6, tzinfo=UTC)
    assert appmod._admin_ts(want) == want
    assert appmod._admin_date("2026-10-07T00:30:00+03:00") == "2026-10-06"      # shown as a UTC day
    assert appmod._admin_when("2026-10-07T00:30:00+03:00") == "2026-10-06 21:30"


def test_count_text_is_a_dash_for_a_block_that_was_not_loaded():
    assert appmod._admin_n(1234567) == "1,234,567"
    assert appmod._admin_n(0, {"gate": "RuntimeError"}, "users") == "0"
    assert appmod._admin_n(0, {"gate": "RuntimeError"}, "users", "gate") == "-"


GATE_ROWS = [
    _counter("gate:dev:a", 1, NOW - timedelta(hours=1)),
    _counter("gate:dev:b", 3, NOW - timedelta(days=2)),
    _counter("gate:dev:c", 4, datetime(2026, 10, 1, 0, 0, tzinfo=UTC)),       # first instant of the window, over the limit
    _counter("gate:dev:d", 3, datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)),  # one second too old
    _counter("gate:dev:e", 0, NOW),                                          # charged then refunded: no guide
    _counter("fair:dev:x", 9, NOW),                                          # the daily fair-use counter, not the gate
    _counter("dev:y", 3, NOW),                                               # the old token-mode preview counter
    {"key": "gate:dev:f", "count": "2", "last_at": _iso(NOW)},               # a count that arrives as text
    {"key": "gate:dev:g", "count": None, "last_at": _iso(NOW)},
    {"key": "gate:dev:h", "count": 3, "last_at": None},
    {"key": "gate:dev:i", "count": "<script>", "last_at": "<script>"},
    "garbage", None,
]


@pytest.mark.parametrize("limit,expected", [(3, (4, 2)), (1, (4, 4)), (5, (4, 0)), (0, (4, 4)), (None, (4, 2))])
def test_gate_devices_counts_devices_and_those_at_the_gate(limit, expected):
    g = appmod._admin_gate_devices(GATE_ROWS, limit, NOW)
    assert (g["devices"], g["at_gate"]) == expected


def _funnel_fixture():
    visits = [{"day": f"2026-10-0{d}", "count": 100} for d in range(1, 8)]
    visits += [{"day": "2026-09-30", "count": 999}, {"day": "garbage", "count": 5}, {"day": "2026-10-05", "count": "x"}]
    gate = [_counter(f"gate:dev:{i}", 3 if i < 10 else 1, NOW - timedelta(hours=i)) for i in range(40)]
    users = [
        _user(1, NOW - timedelta(hours=1)),
        _user(2, NOW - timedelta(days=1), generations_count=2),
        _user(3, NOW - timedelta(days=3), generations_count=1),
        _user(4, NOW - timedelta(days=5)),                       # active in free mode only (see activity)
        _user(5, datetime(2026, 10, 1, 0, 0, tzinfo=UTC)),
        _user(6, datetime(2026, 9, 30, 23, 59, tzinfo=UTC), generations_count=9),   # too old to be "new"
        _user(7, None, generations_count=4),
    ]
    activity = {_uid(4): {"last_at": NOW, "recent": 1}, _uid(6): {"last_at": NOW, "recent": 2}}
    return visits, gate, users, activity


def test_funnel_numbers_and_conversion_rates():
    visits, gate, users, activity = _funnel_fixture()
    f = appmod._admin_funnel(visits, gate, users, NOW, 3, activity=activity)
    assert [s["key"] for s in f["steps"]] == ["visits", "devices", "gate", "accounts", "activated"]
    assert [s["value"] for s in f["steps"]] == [700, 40, 10, 5, 3]
    rates = [s["rate"] for s in f["steps"]]
    assert rates[0] is None
    assert rates[1:] == pytest.approx([40 / 700, 10 / 40, 5 / 10, 3 / 5])
    assert f["gate_signup_rate"] == pytest.approx(0.5)
    assert f["gate_live"] is True
    # without the free-mode activity signal only the lifetime counter counts
    assert appmod._admin_funnel(visits, gate, users, NOW, 3)["steps"][-1]["value"] == 2


def test_funnel_with_no_data_never_divides_by_zero():
    f = appmod._admin_funnel([], [], [], NOW, 3)
    assert [s["value"] for s in f["steps"]] == [0, 0, 0, 0, 0]
    assert [s["rate"] for s in f["steps"]] == [None] * 5
    assert f["gate_signup_rate"] is None and f["gate_live"] is False
    assert appmod._admin_pct(f["gate_signup_rate"]) == "-"
    f2 = appmod._admin_funnel(None, None, None, NOW, None)
    assert f2["gate_signup_rate"] is None


def test_funnel_gate_rate_when_accounts_exist_but_no_device_reached_the_gate():
    _, _, users, _ = _funnel_fixture()
    f = appmod._admin_funnel([], [], users, NOW, 3)
    assert f["steps"][3]["value"] == 5 and f["gate_signup_rate"] is None     # 5 / 0 is "no data", not a crash


def test_funnel_uses_exact_device_counts_when_the_row_sample_was_cut():
    visits, gate, users, activity = _funnel_fixture()
    f = appmod._admin_funnel(visits, gate[:5], users, NOW, 3, device_counts=(4000, 900))
    assert [s["value"] for s in f["steps"]][1:3] == [4000, 900]
    assert f["gate_signup_rate"] == pytest.approx(5 / 900)


@pytest.mark.parametrize("limit", [0, -3, "0"])
def test_funnel_when_sign_in_is_required_from_the_first_guide(limit):
    """ANON_FREE_USES=0 is a supported setting: no anonymous guide exists, so the two
    device steps do not apply and new accounts are measured against visits."""
    visits, gate, users, activity = _funnel_fixture()
    f = appmod._admin_funnel(visits, gate, users, NOW, limit, activity=activity)
    by = {s["key"]: s for s in f["steps"]}
    assert f["gate_from_first"] is True
    assert [s["key"] for s in f["steps"] if s["na"]] == ["devices", "gate"]
    for key in ("devices", "gate"):
        assert (by[key]["value"], by[key]["rate"], by[key]["base"]) == (0, None, None)   # old gate rows are not counted
    assert (by["visits"]["value"], by["accounts"]["value"], by["activated"]["value"]) == (700, 5, 3)
    assert by["accounts"]["base"] == "visits" and by["accounts"]["rate"] == pytest.approx(5 / 700)
    assert by["activated"]["base"] == "accounts" and by["activated"]["rate"] == pytest.approx(3 / 5)
    assert f["gate_signup_rate"] is None


def test_funnel_steps_name_the_step_their_rate_is_measured_from():
    visits, gate, users, activity = _funnel_fixture()
    f = appmod._admin_funnel(visits, gate, users, NOW, 3, activity=activity)
    assert f["gate_from_first"] is False and not any(s["na"] for s in f["steps"])
    assert [s["base"] for s in f["steps"]] == [None, "visits", "devices", "gate", "accounts"]


@pytest.mark.parametrize("rate,cap,text", [
    (None, None, "-"), (0, None, "0%"), (0.004, None, "0.4%"), (0.05, None, "5%"), (0.0951, None, "9.5%"),
    (0.61, None, "61%"), (1.0, None, "100%"), (1.0, 1.0, "100%"), (4.5, 1.0, "100%+"), (4.5, None, "450%"),
])
def test_percent_text(rate, cap, text):
    assert appmod._admin_pct(rate, cap=cap) == text


def test_rate_guards_division_by_zero():
    assert appmod._admin_rate(5, 0) is None and appmod._admin_rate(0, 0) is None
    assert appmod._admin_rate(5, -1) is None
    assert appmod._admin_rate(1, 4) == 0.25 and appmod._admin_rate(0, 4) == 0.0


def test_budget_reads_the_current_24h_window():
    rows = [_counter("fair:global", 1220, NOW - timedelta(minutes=1), window_start=NOW - timedelta(hours=5)),
            _counter("fair:global:anon", 700, NOW - timedelta(minutes=2), window_start=NOW - timedelta(hours=5)),
            _counter("fair:global:other", 5, NOW), "garbage"]
    b = appmod._admin_budget(rows, NOW, 2000, 1200)
    assert (b["used"], b["limit"], b["warn"]) == (1220, 2000, False)
    assert b["pct"] == pytest.approx(0.61)
    assert b["resets_in_s"] == 19 * 3600
    assert (b["anon"]["used"], b["anon"]["limit"], b["anon"]["warn"]) == (700, 1200, False)
    assert b["anon"]["pct"] == pytest.approx(700 / 1200)


@pytest.mark.parametrize("used,warn", [(1600, False), (1601, True), (2000, True), (2600, True)])
def test_budget_warns_over_80_percent(used, warn):
    b = appmod._admin_budget([_counter("fair:global", used, NOW, window_start=NOW)], NOW, 2000)
    assert b["warn"] is warn and b["anon"] is None


def test_budget_ignores_an_expired_window_and_missing_rows():
    stale = [_counter("fair:global", 1900, NOW - timedelta(hours=26), window_start=NOW - timedelta(hours=25))]
    b = appmod._admin_budget(stale, NOW, 2000, 1200)
    assert (b["used"], b["pct"], b["warn"], b["resets_in_s"]) == (0, 0.0, False, None)   # it resets on the next guide
    e = appmod._admin_budget([], NOW, 2000, 1200)
    assert (e["used"], e["pct"], e["anon"]["used"]) == (0, 0.0, 0)
    z = appmod._admin_budget([_counter("fair:global", 7, NOW)], NOW, 0)                   # a zero limit: no percentage
    assert z["pct"] is None and z["warn"] is False
    h = appmod._admin_budget([{"key": "fair:global", "count": "<b>", "window_start": "<i>"}], NOW, 2000)
    assert h["used"] == 0


def test_generation_gate_is_read_defensively():
    sem = threading.BoundedSemaphore(2)
    sem.acquire()
    try:
        g = appmod._admin_gen_gate({"_gen_sem": sem, "_GEN_SLOTS": 2, "_gen_waiting": [object()], "_GEN_WAIT_MAX": 1})
    finally:
        sem.release()
    assert g == {"running": 1, "slots": 2, "waiting": 1, "wait_max": 1}
    assert appmod._admin_gen_gate({}) is None
    assert appmod._admin_gen_gate({"_gen_sem": object(), "_GEN_SLOTS": 2}) is None
    assert appmod._admin_gen_gate({"_gen_sem": sem, "_GEN_SLOTS": "two"}) is None


def test_user_activity_from_the_per_user_fair_use_counters():
    rows = [_counter(f"fair:user:{_uid(1)}", 3, NOW - timedelta(hours=2), window_start=NOW - timedelta(hours=4)),
            _counter(f"fair:user:{_uid(2)}", 5, NOW - timedelta(days=3), window_start=NOW - timedelta(days=3)),
            _counter("fair:chat:user:" + _uid(3), 9, NOW), _counter("fair:user:", 1, NOW), "garbage"]
    a = appmod._admin_user_activity(rows, NOW)
    assert set(a) == {_uid(1), _uid(2)}
    assert a[_uid(1)]["recent"] == 3 and a[_uid(1)]["last_at"] == NOW - timedelta(hours=2)
    assert a[_uid(2)]["recent"] == 0                    # its 24 h window is over, the date of last use stays


def test_user_activity_needs_a_counted_guide_not_just_a_counter_row():
    """anon_consume creates the row before it knows whether the guide is allowed,
    and anon_refund only takes the unit back: an account whose one attempt was
    refused or failed keeps a 'fair:user:<uid>' row with count 0. That is not a guide."""
    t = NOW - timedelta(hours=1)
    rows = [_counter(f"fair:user:{_uid(1)}", 0, t),                                    # charged, then refunded
            {"key": f"fair:user:{_uid(2)}", "count": None, "window_start": _iso(t), "last_at": _iso(t)},
            {"key": f"fair:user:{_uid(3)}", "count": "0", "window_start": _iso(t), "last_at": _iso(t)},
            {"key": f"fair:user:{_uid(4)}", "count": -1, "window_start": _iso(t), "last_at": _iso(t)},
            {"key": f"fair:user:{_uid(5)}", "count": "<b>", "window_start": _iso(t), "last_at": _iso(t)},
            {"key": f"fair:user:{_uid(6)}", "window_start": _iso(t), "last_at": _iso(t)},
            _counter(f"fair:user:{_uid(7)}", 1, t),                                    # one real guide
            {"key": f"fair:user:{_uid(8)}", "count": "2", "window_start": _iso(t), "last_at": _iso(t)}]
    a = appmod._admin_user_activity(rows, NOW)
    assert set(a) == {_uid(7), _uid(8)}
    assert (a[_uid(7)]["recent"], a[_uid(8)]["recent"]) == (1, 2)
    assert appmod._admin_made_guide(_user(1, NOW), a) is False
    assert appmod._admin_made_guide(_user(7, NOW), a) is True
    assert appmod._admin_made_guide(_user(1, NOW, generations_count=4), a) is True     # the token-era counter still counts
    # ... and so the funnel's last step does not count the refused account either
    users = [_user(1, NOW - timedelta(hours=2)), _user(7, NOW - timedelta(hours=2))]
    assert appmod._admin_funnel([], [], users, NOW, 3, activity=a)["steps"][-1]["value"] == 1


# ═════════════════════════ 2. the page ═══════════════════════════════════════════
def test_admin_still_needs_the_cookie_or_the_header(client, monkeypatch):
    _use(monkeypatch, sample_db())
    for kw in ({}, {"headers": {"X-Admin-Token": "wrong"}}, {"headers": {"X-Admin-Token": ""}}):
        r = client.get("/admin", **kw)
        assert r.status_code == 401
        body = r.get_data(as_text=True)
        assert "sec-signups" not in body and "@example.com" not in body and 'id="subTable"' not in body
    client.set_cookie("alimne_admin", "v2.1.99999999.abcd.deadbeef", path="/admin")
    assert client.get("/admin").status_code == 401
    for path in ("/admin/block", "/admin/unblock", "/admin/clear", "/admin/user/cancel", "/admin/user/grant"):
        assert client.post(path, json={}).status_code == 401


def test_renders_fully_without_supabase(client, monkeypatch):
    _use(monkeypatch, None)
    html = _page(client)
    pos = [html.index(f'id="{s}"') for s in SECTIONS]
    assert pos == sorted(pos)
    assert "Supabase is not configured" in html
    for key in ("signups-today", "signups-yesterday", "signups-7d", "signups-total", "funnel-visits",
                "funnel-devices", "funnel-gate", "funnel-accounts", "funnel-activated", "visits-total", "gens-total"):
        assert _num(html, key) == "0", key
    assert _num(html, "gate-signup-rate") == "-"
    assert "No users yet." in html and "Recent visitors" in html
    assert len(re.findall(r'class="bar[ "]', html)) == 14


def test_renders_when_the_client_factory_itself_raises(client, monkeypatch):
    def boom():
        raise RuntimeError(DB_ERROR_CANARY)
    monkeypatch.setattr(appmod, "_get_sb", boom)
    html = _page(client)
    assert DB_ERROR_CANARY not in html and 'id="sec-users"' in html


def test_empty_database_shows_zeros_and_the_gate_note(client, monkeypatch):
    sb = _use(monkeypatch, FakeSB())
    html = _page(client)
    assert [_num(html, k) for k in ("signups-today", "signups-total", "funnel-devices", "funnel-gate")] == ["0"] * 4
    assert _num(html, "gate-signup-rate") == "-"
    assert "sign-in gate data starts when the 3-guide gate goes live" in html
    assert "No users yet." in html and "could not load" not in html.lower()
    assert _num(html, "budget-pct") == "0%"
    assert sb.queries, "the dashboard never asked the database"


def test_gate_note_follows_the_configured_limit_and_goes_away_with_data(client, monkeypatch):
    monkeypatch.setattr(appmod, "ANON_FREE_USES", 5, raising=False)
    _use(monkeypatch, FakeSB())
    assert "sign-in gate data starts when the 5-guide gate goes live" in _page(client)
    _use(monkeypatch, sample_db(gate_limit=5))
    html = _page(client)
    assert "gate data starts when" not in html
    assert (_num(html, "funnel-devices"), _num(html, "funnel-gate")) == ("120", "40")


@pytest.mark.parametrize("setting", [0, -1, "0"])
def test_gate_set_to_zero_reads_as_sign_in_from_the_first_guide(client, monkeypatch, setting):
    monkeypatch.setattr(appmod, "ANON_FREE_USES", setting, raising=False)
    sb = sample_db()
    html = _page_of(client, monkeypatch, sb)
    assert 'data-note="gate-from-first"' in html
    assert "sign-in required from the first guide" in html
    # not the "the gate is not live yet" note, and never a made-up 1-guide gate
    assert "gate data starts when" not in html and 'data-note="gate-not-live"' not in html
    for wrong in ("1-guide gate", "0-guide gate", "all 1 free guides", "all 0 free guides"):
        assert wrong not in html, wrong
    # the two device steps and the gate rate are "not applicable", not a real 0
    assert [_num(html, k) for k in ("funnel-devices", "funnel-gate", "gate-signup-rate")] == ["n/a"] * 3
    assert 'data-conv="devices"' not in html and 'data-conv="gate"' not in html
    assert html.count("not applicable") >= 3
    # the rest of the funnel stands; new accounts are measured against visits
    assert (_num(html, "funnel-visits"), _num(html, "funnel-accounts"), _num(html, "funnel-activated")) ==         ("2,235", "27", "10")
    assert re.search(r'data-conv="accounts">1\.2% of visits<', html)            # 27 / 2,235
    assert re.search(r'data-conv="activated">37% of new accounts<', html)       # 10 / 27
    assert "Gate → sign-up is an estimate" not in html
    # nothing is asked of the gate counters, so a failure there cannot show up either
    assert not any(q.table == "anon_usage" and ("like", "key", "gate:dev:%") in q.filters for q in sb.queries)
    for s in SECTIONS:
        assert f'id="{s}"' in html


def test_gate_set_to_zero_on_an_empty_or_failing_database(client, monkeypatch):
    monkeypatch.setattr(appmod, "ANON_FREE_USES", 0, raising=False)
    html = _page_of(client, monkeypatch, FakeSB())
    assert 'data-note="gate-from-first"' in html and "gate data starts when" not in html
    assert (_num(html, "funnel-devices"), _num(html, "funnel-accounts")) == ("n/a", "0")
    assert re.search(r'data-conv="accounts">-<', html)                          # 0 visits: nothing to divide by
    sb = sample_db()
    sb.fail.add("anon_usage")
    html = _page_of(client, monkeypatch, sb)
    assert 'data-err="gate"' not in html and 'data-err="budget"' in html
    assert (_num(html, "funnel-devices"), _num(html, "funnel-gate")) == ("n/a", "n/a")
    assert re.search(r'data-conv="accounts">1\.2% of visits<', html)            # visits and accounts did load
    sb = sample_db()
    sb.fail.add("visit_stats")
    html = _page_of(client, monkeypatch, sb)
    assert _num(html, "funnel-visits") == "-" and re.search(r'data-conv="accounts">-<', html)


def test_a_one_guide_gate_is_still_a_gate(client, monkeypatch):
    monkeypatch.setattr(appmod, "ANON_FREE_USES", 1, raising=False)
    html = _page_of(client, monkeypatch, FakeSB())
    assert "sign-in gate data starts when the 1-guide gate goes live" in html
    assert 'data-note="gate-from-first"' not in html and _num(html, "funnel-devices") == "0"
    html = _page_of(client, monkeypatch, sample_db(gate_limit=1))
    assert (_num(html, "funnel-devices"), _num(html, "funnel-gate")) == ("120", "120")


def test_sample_week_numbers(client, monkeypatch):
    sb = _use(monkeypatch, sample_db())
    html = _page(client)
    assert [_num(html, k) for k in ("signups-today", "signups-yesterday", "signups-7d", "signups-total")] == \
        ["3", "4", "27", "40"]
    week_visits = sum(r["count"] for r in sb.tables["visit_stats"] if "2026-10-01" <= r["day"] <= "2026-10-07")
    assert _num(html, "funnel-visits") == f"{week_visits:,}"
    assert (_num(html, "funnel-devices"), _num(html, "funnel-gate")) == ("120", "40")
    assert _num(html, "funnel-accounts") == "27"
    assert _num(html, "funnel-activated") == "10"                # the ten accounts with a free-mode counter
    assert _num(html, "gate-signup-rate") == "68%"               # 27 new accounts / 40 devices at the gate
    assert "counted separately" in html and "estimate" in html
    assert _num(html, "visits-total") == f"{sum(r['count'] for r in sb.tables['visit_stats']):,}"
    assert _num(html, "gens-total") == "7"
    assert (_num(html, "budget-used"), _num(html, "budget-pct")) == ("1,220", "61%")
    assert _num(html, "budget-anon-pct") == "58%"
    assert 'data-meter="global"' in html and "meter warn" not in html
    # order: sign-ups, funnel (+ the all-time cards under it), budget, users, generations, leads, visitors
    order = ['id="sec-signups"', 'id="sec-funnel"', 'data-num="visits-total"', 'data-num="gens-total"',
             'id="sec-budget"', 'id="sec-users"', 'id="sec-gens"', 'id="sec-leads"', 'id="sec-visitors"']
    pos = [html.index(m) for m in order]
    assert pos == sorted(pos), list(zip(order, pos))


def test_chart_has_14_bars_with_hover_text_and_today_highlighted(client, monkeypatch):
    _use(monkeypatch, sample_db())
    d = _doc(_page(client))
    bars = [a for t, a in d.attrs if "bar" in (a.get("class") or "").split()]
    assert len(bars) == 14
    assert [b["data-day"] for b in bars] == [(datetime(2026, 9, 24) + timedelta(days=i)).strftime("%Y-%m-%d")
                                             for i in range(14)]
    assert bars[-1]["title"] == "Wed 7 Oct: 3 sign-ups" and bars[0]["title"] == "Thu 24 Sep: 1 sign-up"
    assert ["today" in b["class"].split() for b in bars] == [False] * 13 + [True]
    assert "UTC" in " ".join(d.text)


def test_budget_warning_style_over_80_percent(client, monkeypatch):
    sb = sample_db()
    for r in sb.tables["anon_usage"]:
        if r["key"] == "fair:global":
            r["count"] = 1700
    _use(monkeypatch, sb)
    html = _page(client)
    assert _num(html, "budget-pct") == "85%"
    assert re.search(r'class="meter warn[^"]*" data-meter="global"', html)


def test_live_generation_gate_is_shown(client, monkeypatch):
    _use(monkeypatch, sample_db())
    html = _page(client)
    assert _num(html, "gen-running") == f"0 / {appmod._GEN_SLOTS}"
    assert _num(html, "gen-waiting") == "0"


@pytest.mark.parametrize("down", ["anon_usage", "users", "visit_stats", "usage_events", "leads"])
def test_one_failing_query_never_takes_the_page_down(client, monkeypatch, down):
    sb = sample_db()
    sb.fail.add(down)
    _use(monkeypatch, sb)
    html = _page(client)
    for s in SECTIONS:
        assert f'id="{s}"' in html
    assert "could not load" in html.lower()
    assert DB_ERROR_CANARY not in html                           # the raw database error never reaches the page
    # What could not be loaded shows "-": an unknown number must never look like a real 0.
    all_visits = f"{sum(r['count'] for r in sb.tables['visit_stats']):,}"
    assert _num(html, "visits-total") == ("-" if down == "visit_stats" else all_visits)
    assert _num(html, "funnel-visits") == ("-" if down == "visit_stats" else "2,235")
    assert _num(html, "gens-total") == ("-" if down == "usage_events" else "7")
    if down == "users":
        for key in ("signups-today", "signups-yesterday", "signups-7d", "signups-total",
                    "funnel-accounts", "funnel-activated", "gate-signup-rate", "accounts-active"):
            assert _num(html, key) == "-", key
        assert 'data-err="users"' in html and "Not loaded." in html and "No users yet." not in html
    else:
        assert _num(html, "signups-total") == "40" and "user1@example.com" in html
        assert _num(html, "signups-7d") == "27" and _num(html, "funnel-accounts") == "27"
    if down == "anon_usage":
        # the device steps, the rate and the budget say so; sign-ups, users and visits are untouched
        for block in ("gate", "budget", "activity"):
            assert f'data-err="{block}"' in html, block
        for key in ("funnel-devices", "funnel-gate", "gate-signup-rate", "budget-used", "budget-pct",
                    "funnel-activated", "accounts-active"):       # "made a guide" needs the per-account counters
            assert _num(html, key) == "-", key
        assert "gate data starts when" not in html               # "could not load" is not "the gate is not live"
        assert re.search(r'data-conv="devices">-<', html) and re.search(r'data-conv="accounts">-<', html)
    else:
        assert _num(html, "funnel-devices") == "120" and _num(html, "budget-pct") == "61%"
    if down == "leads":
        assert 'data-err="leads"' in html


def test_a_slow_database_stops_the_reads_instead_of_pinning_the_thread(client, monkeypatch):
    sb = _use(monkeypatch, sample_db())
    monkeypatch.setattr(appmod, "_ADMIN_LOAD_BUDGET_S", -1.0)    # the shared time budget is already spent
    html = _page(client)
    assert sb.queries == []
    assert "the database is slow" in html
    for key in ("signups-today", "signups-total", "funnel-visits", "funnel-devices", "funnel-accounts",
                "gate-signup-rate", "visits-total", "gens-total", "budget-used", "budget-pct"):
        assert _num(html, key) == "-", key
    for s in SECTIONS:
        assert f'id="{s}"' in html


def test_users_query_falls_back_when_a_column_is_missing(client, monkeypatch):
    sb = sample_db()
    sb.missing["users"] = {"last_used_at", "referral_paid"}
    _use(monkeypatch, sb)
    html = _page(client)
    assert _num(html, "signups-total") == "40" and "user1@example.com" in html
    assert 'data-err="users"' not in html


def test_counts_stay_right_when_the_database_caps_the_rows(client, monkeypatch):
    sb = sample_db()
    sb.max_rows = 25                                            # like PostgREST's max-rows
    _use(monkeypatch, sb)
    html = _page(client)
    assert _num(html, "signups-total") == "40"                   # the exact count, not the 25 rows we hold
    assert (_num(html, "funnel-devices"), _num(html, "funnel-gate")) == ("120", "40")
    assert "newest 25 of 40" in html


def test_every_read_is_bounded_and_read_only(client, monkeypatch):
    sb = _use(monkeypatch, sample_db())
    _page(client)
    assert 0 < len(sb.queries) <= 10
    for q in sb.queries:
        assert q.table in {"users", "anon_usage", "visit_stats", "usage_events", "leads"}
        assert isinstance(q.lim, int) and 0 < q.lim <= 5000, (q.table, q.lim)
        if q.table != "users":
            assert q.cols != "*", q.table
        if q.table == "anon_usage":
            assert any(op == "like" and c == "key" for op, c, _ in q.filters), "an unfiltered scan of the counters"
            assert set(q.cols.split(",")) <= {"key", "count", "window_start", "last_at"}


def test_queries_work_on_the_real_postgrest_builder(client, monkeypatch):
    """The fake accepts anything; make sure every call the dashboard chains also
    exists on the real client (no network: execute() is replaced)."""
    postgrest = pytest.importorskip("postgrest")
    rb = pytest.importorskip("postgrest._sync.request_builder")
    if not hasattr(rb, "SyncQueryRequestBuilder"):
        pytest.skip("unknown postgrest layout")
    seen = []

    def fake_execute(self):
        seen.append(str(self.request.params))
        return SimpleNamespace(data=[], count=0)
    monkeypatch.setattr(rb.SyncQueryRequestBuilder, "execute", fake_execute)
    pg = postgrest.SyncPostgrestClient("https://example.invalid/rest/v1", headers={})
    _use(monkeypatch, SimpleNamespace(table=pg.from_))
    html = _page(client)
    assert "could not load" not in html.lower(), seen
    assert len(seen) >= 6
    assert all("limit=" in s for s in seen), seen
    assert any("key=like.gate%3Adev%3A%25" in s and "last_at=gte.2026-10-01T00%3A00%3A00Z" in s for s in seen), seen


# ═════════════════════════ 3. escaping and secrets ═══════════════════════════════
XSS_EMAIL = '"><script>alert(1)</script>@x.com'
XSS_NAME = "</td><img src=x onerror=alert(2)> \\ ' \" `"
XSS_UA = 'Mozilla/5.0 <script>alert(3)</script> "q" \'a\' \\b'
XSS_PATH = "/<svg onload=alert(4)>"
XSS_IP = "1.2.3.4');alert(5);//"
XSS_STATUS = 'free"><script>alert(6)</script>'
XSS_DATE = '2026-10-06"><script>alert(7)</script>'
XSS_CODE = "<b onmouseover=alert(8)>c</b>"
XSS_CITY = "<iframe src=javascript:alert(9)>"
XSS_UID = "u\\');alert(10);//"
ALLOWED_HANDLERS = [
    r"(blockIp|unblock)\('(?:[^'\\]|\\.)*'\)",
    r"(grantTokens|cancelSub)\('(?:[^'\\]|\\.)*','(?:[^'\\]|\\.)*'\)",
    r"subSort\('[a-z]+',[01]\)", r"location\.reload\(\)", r"clearLog\(\)", r"signOut\(\)",
    r"subFilter\(\)", r"subExportCSV\(\)",
]


def _hostile_db():
    sb = sample_db()
    sb.tables["users"].insert(0, _user(
        900, _iso(NOW - timedelta(minutes=5)), id=XSS_UID, email=XSS_EMAIL, name=XSS_NAME,
        subscription_status="active", subscription_id="sub_x", subscription_period_end=XSS_DATE,
        referral_code=XSS_CODE, last_used_at=XSS_DATE, generations_count="<script>alert(11)</script>",
        tokens_remaining="<script>alert(12)</script>"))
    sb.tables["users"].insert(1, _user(901, XSS_DATE, email="b@x.com", name=XSS_NAME, referred_by=XSS_UID,
                                       subscription_status=XSS_STATUS))
    sb.tables["leads"].append({"email": XSS_EMAIL, "source": XSS_NAME, "created_at": XSS_DATE})
    sb.tables["usage_events"].append({"kind": XSS_STATUS, "source": XSS_NAME, "city": XSS_CITY,
                                      "country": XSS_CODE, "created_at": XSS_DATE})
    sb.tables["visit_stats"].append({"day": XSS_DATE, "count": "<script>alert(13)</script>"})
    sb.tables["anon_usage"].append({"key": "gate:dev:<script>alert(14)</script>", "count": "<b>",
                                    "window_start": XSS_DATE, "last_at": XSS_DATE})
    sb.tables["anon_usage"].append({"key": f"fair:user:{XSS_UID}", "count": 2, "window_start": XSS_DATE,
                                    "last_at": XSS_DATE})
    return sb


@pytest.mark.parametrize("free", [True, False])
def test_hostile_strings_are_escaped_everywhere(client, monkeypatch, free):
    monkeypatch.setattr(appmod, "FREE_MODE", free)
    _use(monkeypatch, _hostile_db())
    monkeypatch.setattr(appmod, "_visitors", [
        {"ip": XSS_IP, "time": "2026-10-07 00:20:00 UTC", "path": XSS_PATH, "ua": XSS_UA, "country": XSS_CODE,
         "city": XSS_CITY, "region": XSS_NAME, "isp": XSS_NAME, "lat": '"><script>alert(15)</script>',
         "lon": "1", "method": "GET"}])
    monkeypatch.setattr(appmod, "_blocked_ips", {XSS_IP})
    html = _page(client)

    # 1. nothing hostile survives as markup
    low = html.lower()
    for raw in ("<script>alert", "<img", "<svg", "<iframe", "<b onmouseover", "</td><img"):
        assert raw not in low, raw
    d = _doc(html)
    assert d.tags.count("script") == 2                            # the page's own two, nothing injected
    assert not {"img", "svg", "iframe", "object", "embed", "link", "base", "form"} & set(d.tags)
    for script in d.scripts:
        assert "alert(" not in script

    # 2. every event handler is one of the page's own calls
    for tag, attrs in d.attrs:
        for name, value in attrs.items():
            if name.startswith("on"):
                assert name in ("onclick", "oninput", "onchange"), (tag, name)
                assert any(re.fullmatch(p, value or "") for p in ALLOWED_HANDLERS), value
            if name in ("href", "src", "action"):
                assert not (value or "").strip().lower().startswith("javascript:"), value

    # 3. the data is still shown, as text (decoded exactly like a browser does)
    text = " ".join(d.text)
    for shown in (XSS_EMAIL, XSS_NAME, XSS_UA, XSS_PATH, XSS_IP, XSS_CITY):
        assert shown in text, shown
    row = next(r for r in d.rows if r.get("data-email") == XSS_EMAIL.lower())
    assert row["data-name"] == XSS_NAME.lower()                   # quotes did not end the attribute
    assert row["data-used"].isdigit() and row["data-joined"] == "2026-10-07"
    # a "date" that is not a date is never echoed back, as text or inside an attribute
    assert XSS_DATE not in text
    assert all(XSS_DATE not in (v or "") for _, a in d.attrs for v in a.values())


def test_no_secret_reaches_the_page(client, monkeypatch):
    for name in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_JWT_SECRET", "STRIPE_WEBHOOK_SECRET",
                 "GROQ_API_KEY", "CF_ORIGIN_SECRET"):
        monkeypatch.setattr(appmod, name, f"canary-secret-{name.lower()}", raising=False)
    _use(monkeypatch, sample_db())
    by_header = _page(client)
    fresh = appmod.app.test_client()
    assert fresh.post("/admin/login", json={"token": TOKEN, "remember": True}).status_code == 200
    by_cookie = fresh.get("/admin")
    assert by_cookie.status_code == 200
    for html in (by_header, by_cookie.get_data(as_text=True)):
        assert TOKEN not in html and "canary-secret-" not in html
        assert "X-Admin-Token" not in html and "localStorage.setItem" not in html
        assert not re.search(r"sub_legacy_\d", html)              # Stripe ids stay on the server
    assert by_cookie.headers.get("Cache-Control") == "no-store"


# ═════════════════════════ 4. free mode / legacy mode ════════════════════════════
def _headers(html):
    table = html[html.index('id="subTable"'):]
    thead = table[:table.index("</thead>")]
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>|⇅", "", th)).strip() for th in re.findall(r"<th\b.*?</th>", thead, re.S)]


def test_free_mode_users_table(client, monkeypatch):
    _use(monkeypatch, sample_db())
    html = _page(client)
    assert _headers(html) == ["Email", "Name", "Joined", "Guides made", "Last used", "Invited by", "Invites", "Plan"]
    assert "Tokens" not in html and "grantTokens" not in html and "/admin/user/grant" not in html
    assert "MRR" not in html and 'data-num="active-subs"' not in html
    assert "Subscribers" not in html
    assert "Users" in re.search(r'id="sec-users".*?<h3[^>]*>(.*?)</h3>', html, re.S).group(1)
    assert "Legacy subscribers only" in html and "Paying only" not in html
    assert "Leads (old paywall emails)" in html
    d = _doc(html)
    rows = {r["data-email"]: r for r in d.rows}
    assert len(rows) == 40
    assert [r["data-joined"] for r in d.rows] == sorted((r["data-joined"] for r in d.rows), reverse=True)  # newest first
    # legacy badge: only the active and the canceling subscriber, each with its date
    assert html.count("legacy subscriber<") == 2
    assert "renews 2026-10-26" in html and "ends 2026-10-13" in html
    assert [r["data-email"] for r in d.rows if r["data-legacy"] == "1"] == ["user4@example.com", "user2@example.com"]
    # Cancel: every legacy subscriber, the one that is already set to end included
    assert _cancels(d) == sorted([f"cancelSub('{_uid(2)}','user2@example.com')",
                                  f"cancelSub('{_uid(4)}','user4@example.com')"])
    assert rows["user2@example.com"]["data-plan"] == "legacy subscriber (active)"
    assert rows["user4@example.com"]["data-plan"] == "legacy subscriber (canceling)"
    assert rows["user40@example.com"]["data-plan"] == ""
    # invites + invited-by
    assert rows["user3@example.com"]["data-invites"] == "2" and rows["user31@example.com"]["data-refby"] == "user3@example.com"
    # guides made: the lifetime counter, or "active since free mode" from the per-user counter
    assert rows["user1@example.com"]["data-used"] == "4"
    assert rows["user35@example.com"]["data-used"] == "2" and rows["user35@example.com"]["data-lastused"] == "2026-10-06"
    assert rows["user40@example.com"]["data-used"] == "0" and rows["user40@example.com"]["data-lastused"] == ""


def _cancels(doc):
    return sorted(a["onclick"] for t, a in doc.attrs if (a.get("onclick") or "").startswith("cancelSub("))


def _user_row_html(html, email):
    return re.search(r'<tr class="subrow" data-email="%s".*?</tr>' % re.escape(email), html, re.S).group(0)


def _subscribers_db():
    """The sample week plus one account in every subscription state the Stripe
    webhook (or an operator) can leave behind. users[k] is user{k+1}."""
    sb = sample_db()
    u = sb.tables["users"]
    u[10].update(subscription_status="past_due", subscription_id="sub_legacy_3",
                 subscription_period_end=_iso(NOW - timedelta(days=2)))
    u[11].update(subscription_status="unpaid", subscription_id="sub_legacy_4")
    u[12].update(subscription_status="Past_Due", subscription_id="sub_legacy_5")        # any letter case
    u[13].update(subscription_status="trialing", subscription_id="sub_legacy_6",
                 subscription_period_end=_iso(NOW + timedelta(days=3)))
    u[14].update(subscription_status="free", subscription_id="sub_legacy_7")            # a subscription on file, state unknown
    u[15].update(subscription_status="canceled", subscription_id="sub_legacy_8",        # over: nothing left to cancel
                 subscription_period_end=_iso(NOW - timedelta(days=30)))
    u[16].update(subscription_status="past_due")                                         # no Stripe id: Cancel sets it to free
    u[17].update(subscription_status="incomplete", subscription_id="sub_legacy_9")      # a state the webhook never writes
    return sb


BILLABLE = (2, 4, 11, 12, 13, 14, 15, 17, 18)          # user numbers that may still be paying


def test_free_mode_every_subscriber_who_may_still_pay_keeps_badge_filter_and_cancel(client, monkeypatch):
    """The owner must always be able to find and cancel a paying legacy subscriber:
    'past_due' / 'unpaid' / 'canceling' are still Stripe subscriptions that bill."""
    html = _page_of(client, monkeypatch, _subscribers_db())
    d = _doc(html)
    rows = {r["data-email"]: r for r in d.rows}
    want = sorted(f"user{i}@example.com" for i in BILLABLE)
    # the 'Legacy subscribers only' filter reads data-legacy
    assert sorted(e for e, r in rows.items() if r["data-legacy"] == "1") == want
    assert '"payAttr": "legacy"' in html
    # the Cancel action
    assert _cancels(d) == sorted(f"cancelSub('{_uid(i)}','user{i}@example.com')" for i in BILLABLE)
    # the badge, with the status in words
    assert html.count("legacy subscriber<") == len(BILLABLE)
    assert f"{len(BILLABLE)} legacy subscribers" in html
    for i, words in ((2, "renews 2026-10-26"), (4, "canceling"), (4, "ends 2026-10-13"), (11, "past due"),
                     (11, "2026-10-05"), (12, "unpaid"), (13, "past due"), (14, "trialing"),
                     (14, "2026-10-10"), (15, "Stripe subscription on file"), (17, "past due"),
                     (18, "incomplete")):
        cell = _user_row_html(html, f"user{i}@example.com")
        assert "legacy subscriber<" in cell and words in cell, (i, words)
    # ... and in the CSV / sort key
    assert rows["user11@example.com"]["data-plan"] == "legacy subscriber (past due)"
    assert rows["user12@example.com"]["data-plan"] == "legacy subscriber (unpaid)"
    assert rows["user13@example.com"]["data-plan"] == "legacy subscriber (past due)"
    assert rows["user15@example.com"]["data-plan"] == "legacy subscriber (free)"
    # a subscription that is over has nothing left to cancel
    ended = _user_row_html(html, "user16@example.com")
    assert "legacy subscriber" not in ended and "cancelSub" not in ended
    assert rows["user16@example.com"]["data-legacy"] == "0" and rows["user16@example.com"]["data-plan"] == ""
    # everyone else has no badge and no action
    assert rows["user40@example.com"]["data-legacy"] == "0"
    assert not re.search(r"sub_legacy_\d", html)                  # Stripe ids stay on the server


def test_token_mode_cancel_is_offered_exactly_as_before(client, monkeypatch, legacy_tokens):
    """ALIMNE_FREE_MODE=0 is untouched: Cancel for active, canceling, and any row
    with a Stripe subscription id; 'Paying only' still means status == active."""
    html = _page_of(client, monkeypatch, _subscribers_db())
    d = _doc(html)
    rows = {r["data-email"]: r for r in d.rows}
    assert _cancels(d) == sorted(f"cancelSub('{_uid(i)}','user{i}@example.com')"
                                 for i in (2, 4, 11, 12, 13, 14, 15, 16, 18))
    assert sorted(e for e, r in rows.items() if r["data-active"] == "1") == ["user2@example.com"]
    assert '"payAttr": "active"' in html and "legacy subscriber" not in html
    assert rows["user11@example.com"]["data-plan"] == "past_due" and rows["user16@example.com"]["data-plan"] == "canceled"
    assert _num(html, "active-subs") == "1"


def test_an_account_whose_only_attempt_was_refused_has_not_made_a_guide(client, monkeypatch):
    sb = sample_db()
    base = _page_of(client, monkeypatch, sb)
    refused = _user(41, NOW - timedelta(minutes=20), email="refused@example.com")     # signed up today, one refused try
    sb.tables["users"].append(refused)
    sb.tables["anon_usage"].append(_counter(f"fair:user:{refused['id']}", 0, NOW - timedelta(minutes=10)))
    html = _page_of(client, monkeypatch, sb)
    assert (_num(base, "funnel-accounts"), _num(html, "funnel-accounts")) == ("27", "28")
    assert _num(html, "funnel-activated") == _num(base, "funnel-activated") == "10"
    assert _num(html, "accounts-active") == _num(base, "accounts-active") == "16"
    row = {r["data-email"]: r for r in _doc(html).rows}["refused@example.com"]
    assert (row["data-used"], row["data-recent"], row["data-lastused"]) == ("0", "0", "")
    cell = re.search(r'data-email="refused@example\.com".*?</tr>', html, re.S).group(0)
    assert ">0</b>" in cell and "0+" not in cell                  # no "made guides since free mode" mark


def test_refused_attempts_cannot_crowd_real_activity_out_of_the_capped_read(client, monkeypatch):
    """The per-account counters are read newest first with a row cap: rows of
    refused attempts (count 0) must not take the places of real activity."""
    sb = sample_db()
    for i in range(50, 60):                                       # ten newer rows that are not guides
        sb.tables["anon_usage"].append(_counter(f"fair:user:{_uid(i)}", 0, NOW - timedelta(minutes=1)))
    monkeypatch.setattr(appmod, "_ADMIN_ACTIVITY_MAX", 10)       # room for exactly the ten real ones
    html = _page_of(client, monkeypatch, sb)
    assert _num(html, "funnel-activated") == "10" and _num(html, "accounts-active") == "16"
    reads = [q for q in sb.queries if q.table == "anon_usage" and ("like", "key", "fair:user:%") in q.filters]
    assert len(reads) == 1 and ("gte", "count", 1) in reads[0].filters


def test_free_mode_sort_filter_and_csv_cover_the_new_columns(client, monkeypatch):
    _use(monkeypatch, sample_db())
    html = _page(client)
    d = _doc(html)
    sorts = [a["onclick"] for t, a in d.attrs if t == "th" and a.get("onclick")]
    assert sorts == ["subSort('email',0)", "subSort('name',0)", "subSort('joined',0)", "subSort('used',1)",
                     "subSort('lastused',0)", "subSort('refby',0)", "subSort('invites',1)", "subSort('plan',0)"]
    js = "\n".join(d.scripts)
    for fn in ("function subSort", "function subFilter", "function subExportCSV", "function cancelSub",
               "function blockIp", "function unblock", "function clearLog", "function signOut"):
        assert fn in js, fn
    assert '["Email","Name","Joined","Guides made","Guides in last 24 h","Last used","Invited by","Invites","Plan","Renews / ends"]' in js.replace(", ", ",")
    assert "alimne-users.csv" in js
    for k in ("email", "name", "joined", "used", "recent", "lastused", "refby", "invites", "plan", "renews"):
        assert all(f"data-{k}" in r for r in d.rows), k
    for label in ("Export CSV", "Refresh", "Clear Log", "Sign out"):
        assert label in html, label
    assert "on every device" in html


def test_legacy_mode_brings_tokens_and_revenue_back(client, monkeypatch, legacy_tokens):
    _use(monkeypatch, sample_db())
    html = _page(client)
    assert _headers(html) == ["Email", "Name", "Joined", "Guides made", "Last used", "Invited by", "Invites",
                              "Plan", "Tokens", "Actions"]
    assert "MRR (est.)" in html and _num(html, "active-subs") == "1"
    assert "Paying only" in html and "Legacy subscribers only" not in html
    assert "Leads (old paywall emails)" not in html
    d = _doc(html)
    rows = {r["data-email"]: r for r in d.rows}
    assert rows["user2@example.com"]["data-tokens"] == "27" and rows["user40@example.com"]["data-tokens"] == "3"
    grants = [a["onclick"] for t, a in d.attrs if (a.get("onclick") or "").startswith("grantTokens(")]
    assert len(grants) == 40 and f"grantTokens('{_uid(2)}','user2@example.com')" in grants
    assert html.count("＋ Tokens") == 40
    cancels = sorted(a["onclick"] for t, a in d.attrs if (a.get("onclick") or "").startswith("cancelSub("))
    assert cancels == sorted([f"cancelSub('{_uid(2)}','user2@example.com')", f"cancelSub('{_uid(4)}','user4@example.com')"])
    js = "\n".join(d.scripts)
    assert "function grantTokens" in js and "/admin/user/grant" in js and '"Tokens"' in js
    assert "subSort('tokens',1)" in html
    # the old status badges are back for everyone
    assert "● active" in html and "● canceling" in html


def test_admin_actions_still_work(client, monkeypatch):
    _use(monkeypatch, sample_db())
    assert client.post("/admin/block", json={"ip": "203.0.113.9"}, headers=HDR).get_json()["ok"] is True
    monkeypatch.setattr(appmod, "_visitors", [{"ip": "203.0.113.9", "time": "t", "path": "/", "ua": "ua"}])
    html = _page(client)
    assert "unblock('203.0.113.9')" in html and "Blocked IPs (1)" in html
    assert client.post("/admin/unblock", json={"ip": "203.0.113.9"}, headers=HDR).get_json()["ok"] is True
    assert "blockIp('203.0.113.9')" in _page(client)
    assert client.post("/admin/clear", headers=HDR).get_json()["ok"] is True


def test_leads_section_is_short_when_empty(client, monkeypatch):
    sb = sample_db()
    sb.tables["leads"] = []
    _use(monkeypatch, sb)
    html = _page(client)
    assert "Leads (old paywall emails)" in html and "none" in html[html.index('id="sec-leads"'):][:600]
    assert "Captured (UTC)" not in html                          # no empty table
