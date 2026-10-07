"""
Copy-truth guard for Alimne (WO-2026-09-26-52).

Alimne keeps shared guides and deletes other guides after 15 minutes, so
absolute claims like "never stored" are false. This test fails if any banned
storage claim comes back into the user-facing sources or the served bundle.

The storage-claim checks are offline and import nothing from the app: they only
read files. The free-mode page checks further down use the Flask test client, also
fully offline (see the block comment there).
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


# ══════════════════════════════════════════════════════════════════════════════
# Free-mode copy truth (the product decision: Alimne is free, fair use applies)
#
# Intent is the same as above: the pages and metadata must never make a claim
# the app does not keep. Alimne is now free (ALIMNE_FREE_MODE, default on), so
# the old plan claims (free trial / 3 tokens a month / Pro US$2.99 / 30 guides)
# are false, and so is "unlimited" (daily fair-use caps apply). When free mode is
# switched off (ALIMNE_FREE_MODE=0) the token plans come back, and the legal
# pages must say THAT again - checked below too.
#
# The static checks only read files. The page checks use the Flask test client,
# fully offline (conftest blanks every secret; the shared-guide row is a stub).
# ══════════════════════════════════════════════════════════════════════════════
import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import app as appmod

# Claims that were true for the token/Pro system and are false for a free product.
# "3 guides" was the old Free plan (3 a month). The one true use of the number today is the
# sign-in gate - "your FIRST 3 guides need no account" - so only that form is let through.
STALE_PRICING = re.compile(
    r"free trial|free preview|\b30 guides\b|(?<!first )\b3 guides\b|\$\s?2\.99|\b2\.99\b|"
    r"\b(?:3|30) (?:processing )?tokens\b|tokens/mo|tokens per month|"
    r"\bfree plan\b|\bpro plan\b|\b3 a month\b|\b2 free\b|one free try|"
    r"upgrade to continue|no_tokens",
    re.IGNORECASE,
)
# "Unlimited" is never promised (daily fair-use caps). Saying we do NOT promise it is fine.
UNLIMITED = re.compile(r"(?<!not promise )\bunlimited\b|غير محدود|بلا حدود|بدون حدود", re.IGNORECASE)

# "No sign-up needed" stopped being true on its own (the sign-in gate): only the first
# ANON_FREE_USES guides need no account, after that a free account is required. A page may say
# that - with the number - but it must never make the unqualified claim again. These are the
# unqualified forms, English and Arabic.
NO_ACCOUNT_UNQUALIFIED = re.compile(
    r"without signing[ -]?(?:in|up)|without (?:an? )?(?:account|login|sign-?up)|"
    r"no sign-?(?:up|in)\b|no (?:account|login|registration) (?:is )?(?:needed|required|necessary)|"
    r"دون تسجيل|بدون تسجيل|بلا تسجيل|دون حساب|بدون حساب|بلا حساب|لا حاجة (?:إلى|ل)\s?حساب|لا حاجة (?:إلى|ل)\s?(?:ال)?تسجيل",
    re.IGNORECASE,
)

# sha256 of the og.png that shipped before the free launch: it had "Free plan - 3
# tokens/mo, Pro $2.99/mo - 30 tokens" painted into the picture (shown on every
# WhatsApp / X / LinkedIn share). The picture must never silently come back.
STALE_OG_SHA256 = "e37562d1a2c581d03789b90239444127dd2c5d2504a64bfa933818e7b85a7b1f"

# The privacy promises, word for word as they were before the free launch. The
# free-mode rewrite must leave every one of them exactly as accurate.
PRIVACY_PROMISES = [
    "processed\n<strong>in memory only</strong>",
    "<strong>never written to disk or seen by any human</strong>",
    "<strong>automatically deleted within 15 minutes</strong>",
    '"Delete now". We do not sell your data and we do not show ads.',
    "are held in server memory only for the length of your\nsession (maximum 15 minutes)",
    "They are never persisted to disk, logged in full, or reviewed by a person.",
    '<strong>Shared guides:</strong> if you press "Share" on a guide, that generated guide (not your original\nfile) is stored',
    "We do not retain your study material beyond the 15-minute processing window, except guides you choose to Share",
    "Study jobs: deleted within 15 minutes (or on demand).",
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("ALIMNE_FREE_MODE", raising=False)   # default = free mode
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def _page(client, path):
    r = client.get(path)
    assert r.status_code == 200, path
    return r.get_data(as_text=True).replace("\r\n", "\n")


def _shared_html(client, monkeypatch, language="en"):
    sb = MagicMock()
    row = {"slug": "abc123", "title": "T", "language": language,
           "guide": {"title": "Cells", "sections": [{"title": "S", "bullets": ["b"]}]}}
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = \
        SimpleNamespace(data=row)
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)
    r = client.get("/s/abc123")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _flat(html):
    """The page with every run of whitespace as one space (the source wraps its lines)."""
    return re.sub(r"\s+", " ", html)


# ── /terms ───────────────────────────────────────────────────────────────────
def test_terms_say_alimne_is_free_with_fair_use(client):
    html = _page(client, "/terms")
    assert "Alimne is free" in html
    assert "No paid plan, subscription or credit card is required" in html
    assert "<strong>Fair use:</strong>" in html and "daily limits" in html
    assert "may change" in html
    assert "We do not promise unlimited use." in html
    assert "queue" in html           # busy-time behaviour is disclosed


def test_terms_say_when_a_free_account_is_required(client):
    # The product rule (the sign-in gate): the first 3 guides need no account, after that a free
    # account is required, and the fair-use daily limits are limits on accounts.
    html = _flat(_page(client, "/terms"))
    assert "<strong>Free account:</strong>" in html
    assert "Your first 3 study guides need no account; after that, a free account is required to make more." in html
    assert "Creating an account is free" in html
    assert "never need an account" in html              # the sample lecture, and guides already made
    assert "daily limits on how many study guides an account can generate" in html
    assert "try it without signing in" not in html      # the old, now unqualified, claim


def test_terms_arabic_summary_states_the_account_rule(client):
    html = _flat(_page(client, "/terms"))
    assert "أول 3 أدلة دراسة لا تحتاج إلى حساب، وبعدها يلزم إنشاء حساب مجاني لإنشاء المزيد." in html
    assert "تُطبَّق على الحسابات حدود" in html           # fair use applies to accounts
    assert "دون تسجيل الدخول" not in html                # the old, now unqualified, claim


@pytest.mark.parametrize("n,en,ar", [
    (5, "Your first 5 study guides need no account; after that, a free account is required to make more.",
        "أول 5 أدلة دراسة لا تحتاج إلى حساب"),
    (12, "Your first 12 study guides need no account;", "أول 12 دليلًا دراسيًا لا تحتاج إلى حساب"),
    (2, "Your first 2 study guides need no account;", "أول دليلين دراسيين لا يحتاجان إلى حساب"),
    (1, "Your first study guide needs no account; after that, a free account is required to make more.",
        "دليلك الدراسي الأول لا يحتاج إلى حساب"),
    (0, "A free account is required to make study guides.", "يلزم إنشاء حساب مجاني لإنشاء أدلة الدراسة."),
], ids=["5", "12", "2", "1", "0"])
def test_the_account_rule_on_the_terms_page_is_the_real_allowance(client, monkeypatch, n, en, ar):
    # The number is not typed into the page: it is the ANON_FREE_USES the charge logic enforces,
    # so the page cannot go stale when the knob changes.
    monkeypatch.setattr(appmod, "ANON_FREE_USES", n)
    html = _flat(_page(client, "/terms"))
    assert en in html and ar in html
    assert "first 3 study guides" not in html and "أول 3 أدلة" not in html
    assert not STALE_PRICING.findall(html) and not UNLIMITED.findall(html)
    assert not NO_ACCOUNT_UNQUALIFIED.findall(html)


@pytest.mark.parametrize("path", ["/terms", "/privacy"])
def test_legal_pages_never_say_no_account_is_needed_without_the_qualifier(client, path):
    html = _page(client, path)
    assert not NO_ACCOUNT_UNQUALIFIED.findall(html), NO_ACCOUNT_UNQUALIFIED.findall(html)


def test_terms_keep_legacy_subscribers_able_to_cancel(client):
    html = _page(client, "/terms")
    assert "<strong>Existing subscribers:</strong>" in html
    assert "manage\nor cancel your subscription at any time from within the app" in html
    assert "processed by Stripe" in html


def test_terms_have_no_stale_claims(client):
    html = _page(client, "/terms")
    assert not STALE_PRICING.findall(html), STALE_PRICING.findall(html)
    assert not UNLIMITED.findall(html), UNLIMITED.findall(html)


def test_terms_have_an_arabic_summary(client):
    html = _page(client, "/terms")
    assert 'lang="ar" dir="rtl"' in html
    assert "مجاني" in html and "استخدام عادل" in html and "Stripe" in html


def test_terms_acceptable_use_forbids_evading_limits(client):
    html = _flat(_page(client, "/terms"))
    assert "Do not try to get around the usage limits or the account requirement" in html


# ── /privacy ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("promise", PRIVACY_PROMISES)
def test_privacy_promises_are_unchanged(client, promise):
    assert promise in _page(client, "/privacy")


def test_privacy_has_no_stale_claims(client):
    html = _page(client, "/privacy")
    assert not STALE_PRICING.findall(html), STALE_PRICING.findall(html)
    assert not UNLIMITED.findall(html), UNLIMITED.findall(html)
    assert "monthly token balance" not in html
    assert "90-minute" not in html


def test_privacy_discloses_usage_counters_and_free_payments(client):
    html = _page(client, "/privacy")
    flat = _flat(html)
    assert "<strong>Usage counters:</strong>" in html
    # every identifier a counter is kept against is still named...
    assert "random device identifier stored in your browser" in flat
    assert "your IP address, or your account ID if you are signed in" in flat
    # ...and the page no longer calls the device counter a daily one: it is what decides when a
    # free account becomes required, and it is kept
    assert "when a free account becomes required" in flat and "is not reset daily" in flat
    assert "never your files, text or study guides" in html
    assert "Alimne is free and takes no payments" in html
    assert "processed by <strong>Stripe, Inc.</strong>" in html
    assert "usage counters" in html.split("<h2>6. Third-party services</h2>")[1]


def test_privacy_has_an_arabic_summary_that_keeps_the_promises(client):
    html = _page(client, "/privacy")
    assert 'lang="ar" dir="rtl"' in html
    for fragment in ("في الذاكرة فقط", "15 دقيقة", "لا نبيع بياناتك", "مشاركة"):
        assert fragment in html, fragment


# ── rollback: ALIMNE_FREE_MODE=0 brings the token plans back, so the pages must too ──
@pytest.mark.parametrize("value", ["0", " 0 ", "false", "FALSE", "no", "off", "Off"])
def test_terms_and_privacy_describe_the_token_plans_when_free_mode_is_off(client, monkeypatch, value):
    # The legal pages follow the FREE_MODE constant — the very value the credit logic uses, parsed
    # once at import by ONE parser. So every natural way to switch free mode off turns the pages
    # back to the token plans too (they used to say "free" for anything but a literal 0).
    monkeypatch.setenv("ALIMNE_FREE_MODE", value)
    monkeypatch.setattr(appmod, "FREE_MODE", appmod._env_switch("ALIMNE_FREE_MODE"))
    assert appmod.FREE_MODE is False and appmod._legal_free_mode() is False
    terms = _page(client, "/terms")
    assert "<h2>2. Plans &amp; billing</h2>" in terms
    assert "<strong>Free plan:</strong>" in terms and "<strong>Pro plan:</strong>" in terms
    assert "Alimne is free" not in terms
    assert 'lang="ar" dir="rtl"' not in terms          # the Arabic "free" summary would be false now
    # ...and nothing of the free-mode sign-in gate leaks into the token-mode pages
    assert "<strong>Free account:</strong>" not in terms and "need no account" not in terms
    assert ("Do not try to get around the usage limits (for example with automated tools, "
            "or by rotating devices or networks).") in _flat(terms)
    priv = _page(client, "/privacy")
    assert "track your monthly token balance" in priv
    assert "Alimne is free and takes no payments" not in priv
    assert "to keep the free previews fair, we count how many are used per device" in _flat(priv)
    assert "when a free account becomes required" not in _flat(priv)
    for promise in PRIVACY_PROMISES:                    # privacy promises hold in both modes
        assert promise in priv, promise


@pytest.mark.parametrize("value", [None, "1", "", "true", "yes", "on"])
def test_free_mode_is_the_default(client, monkeypatch, value):
    if value is not None:
        monkeypatch.setenv("ALIMNE_FREE_MODE", value)
    monkeypatch.setattr(appmod, "FREE_MODE", appmod._env_switch("ALIMNE_FREE_MODE"))
    assert appmod.FREE_MODE is True and appmod._legal_free_mode() is True
    assert "Alimne is free" in _page(client, "/terms")


# ── /s/<slug> (shared guide) ─────────────────────────────────────────────────
def test_shared_guide_has_a_truthful_bilingual_growth_cta(client, monkeypatch):
    en = _shared_html(client, monkeypatch, "en")
    assert "Make your own study guide — free" in en
    assert "Free, no credit card needed." in en
    assert 'href="%s/?utm_source=shared_guide&utm_medium=share&utm_campaign=share_cta"' % appmod.APP_URL in en
    assert ">Start free</a>" in en and ">Try it free</a>" in en
    ar = _shared_html(client, monkeypatch, "ar")
    assert 'dir="rtl"' in ar
    assert "أنشئ دليل دراستك مجاناً" in ar and "مجاني، دون بطاقة ائتمان" in ar and "ابدأ مجاناً" in ar
    assert "utm_campaign=share_cta" in ar


def test_shared_guide_and_404_have_no_stale_claims(client, monkeypatch):
    pages = [_shared_html(client, monkeypatch, "en"), _shared_html(client, monkeypatch, "ar")]
    monkeypatch.setattr(appmod, "_get_sb", lambda: None)
    r = client.get("/s/abc123")
    assert r.status_code == 404
    pages.append(r.get_data(as_text=True))
    assert "Make your own study guide — free" in pages[-1]
    for html in pages:
        assert not STALE_PRICING.findall(html), STALE_PRICING.findall(html)
        assert not UNLIMITED.findall(html), UNLIMITED.findall(html)
        # the growth CTA promises "free" and "no credit card", never "no sign-up"
        assert not NO_ACCOUNT_UNQUALIFIED.findall(html), NO_ACCOUNT_UNQUALIFIED.findall(html)


# ── index.html metadata + static files ───────────────────────────────────────
def _head_tags(html):
    return re.findall(r"<title>.*?</title>|<meta [^>]*?>", html, re.DOTALL)


def _meta(html, attr, name):
    m = re.search(r'<meta\s+%s="%s"\s+content="([^"]*)"' % (attr, re.escape(name)), html)
    assert m, f"{attr}={name} missing"
    return m.group(1)


@pytest.mark.parametrize("rel", ["frontend/index.html", "dist/index.html"])
def test_index_metadata_is_free_and_truthful(rel):
    html = _read(rel)
    title = re.search(r"<title>(.*?)</title>", html).group(1)
    assert "Free" in title and "علّمني" in title
    for attr, name in [("name", "description"), ("property", "og:description"),
                       ("name", "twitter:description")]:
        assert "free" in _meta(html, attr, name).lower(), name
    for attr, name in [("property", "og:title"), ("name", "twitter:title")]:
        assert "Free" in _meta(html, attr, name), name
    assert "No credit card" in _meta(html, "property", "og:description")
    assert _meta(html, "property", "og:image").startswith("https://alimne.app/og.png")
    assert _meta(html, "name", "twitter:image").startswith("https://alimne.app/og.png")
    assert not STALE_PRICING.findall(html), STALE_PRICING.findall(html)
    assert not UNLIMITED.findall(html), UNLIMITED.findall(html)
    # the privacy claim the metadata already made stays exactly as it was
    assert "Processed in memory and deleted automatically." in _meta(html, "name", "description")


def test_built_index_metadata_matches_the_source():
    """dist/ is committed and Render does not build it: its head must carry the same
    title/meta tags as frontend/index.html (only the hashed asset tags differ)."""
    assert _head_tags(_read("frontend/index.html")) == _head_tags(_read("dist/index.html"))


def test_og_image_is_the_free_one_in_both_places():
    with open(os.path.join(ROOT, "dist", "og.png"), "rb") as fh:
        built = fh.read()
    with open(os.path.join(ROOT, "frontend", "public", "og.png"), "rb") as fh:
        source = fh.read()
    assert built == source, "frontend/public/og.png and dist/og.png must be the same picture"
    assert hashlib.sha256(built).hexdigest() != STALE_OG_SHA256, \
        "og.png is the old picture that advertises the 3-token / Pro US$2.99 plans"
    assert built[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize("rel", ["frontend/public/robots.txt", "frontend/public/sitemap.xml",
                                 "dist/robots.txt", "dist/sitemap.xml"])
def test_static_seo_files_have_no_stale_claims(rel):
    assert not STALE_PRICING.findall(_read(rel))


def test_stale_claim_patterns_catch_each_old_claim():
    for phrase in ["Free trial", "30 guides", "US$2.99", "Pro $2.99/mo", "3 tokens/mo", "30 tokens per month",
                   "Free plan", "Pro plan", "3 a month", "2 free guides", "You have no tokens left. Upgrade to continue."]:
        assert STALE_PRICING.search(f"xx {phrase} xx"), phrase
    assert UNLIMITED.search("Unlimited study guides")
    assert not UNLIMITED.search("We do not promise unlimited use.")
    # the old plan claim is still caught; the sign-in gate's own sentence is not
    for phrase in ["3 guides a month", "Free: 3 guides", "get 3 guides free every month"]:
        assert STALE_PRICING.search(f"xx {phrase} xx"), phrase
    for fine in ["Your first 3 guides need no account.", "your first 3 study guides need no account",
                 "You've used your 3 free guides."]:
        assert not STALE_PRICING.search(fine), fine


def test_no_account_pattern_catches_each_unqualified_claim_and_allows_the_qualified_one():
    for phrase in ["and you can try it without signing in.", "Free. No card. No sign-up needed.", "no signup",
                   "No account needed", "no login required", "use it without an account", "without sign-up",
                   "ويمكنك تجربته دون تسجيل الدخول", "مجاني للاستخدام · بدون حساب", "لا حاجة إلى حساب",
                   "بلا حساب", "دون حساب"]:
        assert NO_ACCOUNT_UNQUALIFIED.search(f"xx {phrase} xx"), phrase
    for fine in ["Your first 3 study guides need no account; after that, a free account is required to make more.",
                 "never need an account", "Create a free account to keep going - it's still free.",
                 "أول 3 أدلة دراسة لا تحتاج إلى حساب، وبعدها يلزم إنشاء حساب مجاني لإنشاء المزيد.",
                 "We store a counter against your account ID if you are signed in."]:
        assert not NO_ACCOUNT_UNQUALIFIED.search(fine), fine
