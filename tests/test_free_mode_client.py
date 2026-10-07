"""
Free-mode CLIENT guards (product decision 2026-10-07: Alimne is free for everyone).

The server stops charging tokens (ALIMNE_FREE_MODE, default on) and answers a
visitor who is over a fair-use cap with 429 fair_use_device / fair_use_ip /
fair_use_user, a full service with 503 busy_today / busy, and a waiting request
with SSE {"step": "queued", "position": n}. The client must:

  * read free_mode from /api/config (default TRUE when the field is missing) and,
    in free mode, show no token pill, no "N previews left", no upgrade modal, no
    email-before-paywall modal, no Subscribe button and no token-reward referral copy;
  * keep the paywall code reachable ONLY through the token-mode (LEGACY) language
    pack, so ALIMNE_FREE_MODE=0 still works and nothing is left stuck on a 402;
  * keep "Manage / cancel subscription" for people who still pay;
  * show a friendly, localized, per-item message (with Retry) for each refusal, a
    sign-in button on the device refusal, and "You are in line - position N" for
    the queued step;
  * ship every new string in English AND Arabic.

There is no JS test runner. These are static checks of the source and of the
bundle in dist/, plus (when node and frontend/node_modules exist) the behavioural
checks of frontend/scripts/verify-free-mode.mjs, which bundles App_dev.jsx and
server-renders the real components. No imports of the app.
"""
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JSX = os.path.join(ROOT, "frontend", "src", "App_dev.jsx")
DIST = os.path.join(ROOT, "dist")
VERIFY = os.path.join(ROOT, "frontend", "scripts", "verify-free-mode.mjs")


def _src():
    with open(APP_JSX, encoding="utf-8") as fh:
        return fh.read()


def _served():
    with open(os.path.join(DIST, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    refs = re.findall(r'src="/?(assets/index-[\w-]+\.js)"', html)
    assert len(refs) == 1, f"dist/index.html should load exactly one bundle, found {refs}"
    with open(os.path.join(DIST, *refs[0].split("/")), encoding="utf-8") as fh:
        return refs[0], fh.read()


def _block(src, start_pat, end_pat):
    m = re.search(start_pat, src, re.M)
    assert m, f"{start_pat!r} not found"
    e = re.search(end_pat, src[m.end():], re.M)
    assert e, f"{end_pat!r} not found after {start_pat!r}"
    return src[m.end(): m.end() + e.start()]


def _pack(src, name, lang):
    """Body of `<lang>: {` inside `const <name> = {` (4-space keys; en then ar)."""
    start = re.search(r"^const %s = \{" % name, src, re.M)
    assert start, f"const {name} not found"
    body = src[start.end():]
    end = re.search(r"^\}\n", body, re.M)
    body = body[: end.start()]
    en = re.search(r"^  en: \{", body, re.M)
    ar = re.search(r"^  ar: \{", body, re.M)
    assert en and ar, f"{name}: en/ar blocks not found"
    return body[en.end(): ar.start()] if lang == "en" else body[ar.end():]


def _keys(block):
    return re.findall(r"^    (\w+):", block, re.M)


# ── 1. config + gating ────────────────────────────────────────────────────────
def test_free_mode_is_read_from_config_and_defaults_on():
    src = _src()
    assert re.search(r"useState\(true\)", _block(src, r"const \[freeMode, setFreeMode\]\s*= ", r"\n")), \
        "freeMode must default to TRUE (the field may be missing / config may not have loaded)"
    assert "cfg.free_mode !== false" in src, "only an explicit free_mode:false turns the token UI back on"
    assert "cfg.fair_use" in src, "the fair-use numbers come from /api/config"


def test_paywall_surfaces_are_gated_on_free_mode():
    src = _src()
    # the token pill, the anonymous preview badge, both paywall modals
    assert re.search(r"\{!freeMode && showUpgrade && \(", src), "UpgradeModal must not render in free mode"
    assert re.search(r"\{!freeMode && showEmailCapture && \(", src), "email-before-paywall modal must not render in free mode"
    assert re.search(r"!freeMode && anonInfo && anonInfo\.limit > 0", src), "'N previews left' badge must be hidden in free mode"
    assert re.search(r"!freeMode && \(\(\) => \{\s*const rem", src), "the token pill must be hidden in free mode"
    # Account: Subscribe only in token mode; manage/cancel stays for payers
    assert re.search(r"\{!freeMode && !liveSub && \(", src), "Account must not offer Subscribe in free mode"
    assert "const canManage = liveSub || !!userInfo?.has_billing" in src, "payers must still be able to manage/cancel"
    # the credit confirmation before a retry is a token-mode thing
    assert re.search(r"!freeMode && !window\.confirm\(t\.usesCredit\)", src)


def test_unexpected_402_falls_back_to_the_token_flow_instead_of_sticking():
    body = _block(_src(), r"const handleAuthError = ", r"\n  const addFiles")
    assert "status === 402" in body and "setFreeMode(false)" in body, \
        "a 402 means the server is in token mode: switch the client to the token flow"
    assert "tFor(" in body, "the token copy must come from the LEGACY pack, not the free-mode t"


def test_checkout_410_free_now_is_handled():
    body = _block(_src(), r"const goToStripe = ", r"\n  const handleCheckout")
    assert "free_now" in body and "410" in body


def test_portal_and_webhook_routes_untouched():
    src = _src()
    assert "'/api/stripe/portal'" in src, "the billing portal call must stay"
    assert "/api/stripe/webhook" not in src


# ── 2. refusals + queue ───────────────────────────────────────────────────────
@pytest.mark.parametrize("code", ["fair_use_device", "fair_use_ip", "fair_use_user", "busy_today", "busy"])
def test_each_refusal_code_is_mapped(code):
    body = _block(_src(), r"^function friendlyErr\(", r"^\}\n")
    assert f"'{code}'" in body, f"friendlyErr must map {code}"


def test_refusal_mapping_precedes_the_generic_status_text():
    body = _block(_src(), r"^function friendlyErr\(", r"^\}\n")
    assert body.index("'fair_use_device'") < body.index("status === 429"), "fair-use text must win over the generic 429"
    assert body.index("'busy_today'") < body.index("status === 503"), "busy text must win over the generic 503"


def test_queued_step_is_shown_not_treated_as_an_error():
    src = _src()
    body = _block(src, r"const onGenEvent = ", r"\n  // One generation for item")
    assert "ev.step === 'queued'" in body and "queuePos" in body
    assert "t.queuePos" in src and "t.queueWait" in src


def test_stuck_batches_stop_and_per_item_retry_remains():
    src = _src()
    assert re.search(r"const STOP_CODES = new Set\(\[[^\]]*'fair_use_device'[^\]]*'busy'", src)
    assert "errCode" in src, "the item keeps the refusal code so the sign-in button can show"
    assert "t.signInFreeCta" in src
    body = _block(src, r"const processAll = ", r"\n  // ── YouTube SSE")
    assert "'stop'" in body, "a fair-use / busy refusal must stop the batch (the rest stays queued)"


# ── 3. growth without dark patterns ───────────────────────────────────────────
def test_join_card_dismissal_is_remembered_safely():
    src = _src()
    assert "alimne_join_dismissed" in src
    assert re.search(r"ls\.set\('alimne_join_dismissed'", src), "dismissal must go through the try/catch storage helper"
    assert "showJoinCard(" in src


def test_referral_in_free_mode_is_a_plain_invite_link():
    assert "refStats.total" in _src() or "stats.total" in _src(), "show friends joined from the stats endpoint's total"


def test_terms_rewritten_for_free_mode_and_privacy_sections_shared():
    src = _src()
    for name in ("TERMS_EN", "TERMS_AR"):
        assert re.search(r"^const %s = `" % name, src, re.M)
        assert re.search(r"^const %s_LEGACY = `" % name, src, re.M)
    assert "2 anonymous previews" not in _block(src, r"^const TERMS_EN = `", r"^`|`\n")
    assert "TERMS_EN_TAIL" in src and "TERMS_AR_TAIL" in src, "sections 3-10 are one shared string in both modes"


# ── 4. language packs ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("pack", ["T", "LEGACY"])
def test_english_and_arabic_have_the_same_keys(pack):
    src = _src()
    en, ar = _keys(_pack(src, pack, "en")), _keys(_pack(src, pack, "ar"))
    assert en, f"{pack}.en has no keys?"
    assert sorted(en) == sorted(ar), f"{pack}: only EN {set(en) - set(ar)}; only AR {set(ar) - set(en)}"
    assert len(en) == len(set(en)), f"{pack}.en has a duplicated key"


def test_free_mode_pack_has_no_paywall_copy():
    src = _src()
    banned = re.compile(r"Free trial used|previews? left|\bSubscribe\b|10 (free )?tokens?|\btokens?\b|\bcredits?\b|"
                        r"Go Pro|\$2\.99|30 guides|unlimited|Loved it\?", re.I)
    for lang in ("en", "ar"):
        for ln, line in enumerate(_pack(src, "T", lang).splitlines(), 1):
            m = banned.search(line)
            assert not m, f"T.{lang} line +{ln}: {m.group(0)!r}: {line.strip()[:100]}"


def test_legacy_pack_keeps_the_old_copy_for_the_kill_switch():
    legacy = _pack(_src(), "LEGACY", "en")
    for must in ("upgradeBtn", "freeLeft", "signInForMore", "referSub", "emailCaptureTitle", "usesCredit", "guidesLeft"):
        assert re.search(r"^    %s:" % must, legacy, re.M), f"LEGACY.en lost {must}"


# ── 5. the bundle that is actually served ─────────────────────────────────────
def test_served_bundle_is_the_free_client():
    name, js = _served()
    for marker in ("fair_use_device", "fair_use_ip", "fair_use_user", "busy_today", "alimne_join_dismissed",
                   "Free. No card. No sign-up needed."):
        assert marker in js, f"{name} is missing {marker!r} - rebuild: cd frontend && npm run build"
    assert re.search(r"\.free_mode\s*!==\s*(?:!1|false)", js), f"{name} does not read free_mode from /api/config"
    assets = os.path.join(DIST, "assets")
    js_files = sorted(f for f in os.listdir(assets) if f.endswith(".js"))
    assert js_files == [os.path.basename(name)], f"stale bundles in dist/assets: {js_files}"
    css_files = [f for f in os.listdir(assets) if f.endswith(".css")]
    with open(os.path.join(DIST, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    assert len(css_files) == 1 and f"/assets/{css_files[0]}" in html, f"index.html must load the one css file: {css_files}"


# ── 6. behaviour: bundle the real source and render it (needs node + npm ci) ──
_HAVE_NODE = shutil.which("node") and os.path.isdir(os.path.join(ROOT, "frontend", "node_modules", "esbuild"))


@pytest.mark.skipif(not _HAVE_NODE, reason="node or frontend/node_modules (npm ci) not available")
def test_free_mode_behaviour_script_passes():
    r = subprocess.run(["node", VERIFY], cwd=os.path.join(ROOT, "frontend"), capture_output=True, text=True, timeout=240)
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, "verify-free-mode.mjs failed:\n" + out[-4000:]
    assert " failed" in out and "0 failed" in out, out[-500:]
