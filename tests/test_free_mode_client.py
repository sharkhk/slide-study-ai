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

Sign-in gate (owner's rule, 2026-10-07): an anonymous device may make 3 guides
(ANON_FREE_USES, read from /api/config: anon_free_limit / anon_remaining /
signin_after); after those it must sign in (free) to make more. The server refuses
with 401 {"code": "signin_required", "free_uses": n}. The client must:

  * show a signed-out visitor "N free guides left" in the nav ("Sign in to
    continue - free" at 0) and nothing of the kind to a signed-in user;
  * NOT send a generation (file, YouTube, text/URL) when 0 are left: it opens the
    sign-in modal in sign-up mode with the notice instead. The sample lecture is
    never gated;
  * on the 401 (or the older fair_use_device) hold the item in a non-error "sign in
    to continue" state with its file / URL / text kept, and clear that on sign-in;
  * follow anon_remaining from the SSE done event (else count down locally) and
    refetch /api/config after sign-out;
  * never say "no sign-up needed" / "no account needed" without the qualifier that
    it is true for the first N guides only - in English and in Arabic.

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


# The same rule in Arabic: no token / credit / plan / price / preview / "unlimited" claim in the
# free-mode pack. (It keeps "اشتراكك" = "your subscription": people who already pay can still cancel.)
BANNED_AR = re.compile(r"رمز|رموز|رصيد|اشترك(?!ا)|الخطة الاحترافية|2[.,]99|30 دليل|معاينة|معاينات|"
                       r"غير محدود|بلا حدود|بدون حدود|ترقية")


def test_free_mode_pack_has_no_paywall_copy():
    src = _src()
    banned = re.compile(r"Free trial used|previews? left|\bSubscribe\b|10 (free )?tokens?|\btokens?\b|\bcredits?\b|"
                        r"Go Pro|\$2\.99|30 guides|unlimited|Loved it\?", re.I)
    for lang in ("en", "ar"):
        for ln, line in enumerate(_pack(src, "T", lang).splitlines(), 1):
            m = banned.search(line)
            assert not m, f"T.{lang} line +{ln}: {m.group(0)!r}: {line.strip()[:100]}"
    # Arabic is scanned here too: the node check below is skipped on a machine without node_modules.
    for ln, line in enumerate(_pack(src, "T", "ar").splitlines(), 1):
        m = BANNED_AR.search(line)
        assert not m, f"T.ar line +{ln}: {m.group(0)!r}: {line.strip()[:100]}"


def test_arabic_paywall_patterns_catch_each_old_claim():
    for phrase in ["اشترك بـ 2.99$ لـ 30 دليلاً", "لديك 3 رموز", "رصيدك", "غير محدود", "بلا حدود", "بدون حدود",
                   "معاينة مجانية", "الخطة الاحترافية", "ترقية"]:
        assert BANNED_AR.search(f"xx {phrase} xx"), phrase
    for fine in ["ألغِ اشتراكك من صفحة الفوترة", "إدارة / إلغاء الاشتراك", "مجاني وبدون بطاقة"]:
        assert not BANNED_AR.search(fine), fine


def test_the_in_app_terms_say_the_same_things_in_both_languages():
    """The Arabic Terms used to lack the opt-in sharing disclosure and the usage-counter disclosure
    that the English ones (and the /privacy page) have, and misspelled Whisper."""
    src = _src()
    en = _block(src, r"^const TERMS_EN_TAIL = `", r"`")
    ar = _block(src, r"^const TERMS_AR_TAIL = `", r"`")
    assert "Optional sharing" in en and "المشاركة الاختيارية" in ar
    assert "Only guides you explicitly share are stored" in en and "لا يُخزَّن إلا الأدلة التي تشاركها صراحةً" in ar
    assert "Usage counters" in en and "عدّادات الاستخدام" in ar
    for text in (en, ar):
        assert "Supabase" in text and "IP" in text
    assert "authentication and usage counters" in en and "للمصادقة وعدّادات الاستخدام" in ar
    assert "Whisker" not in ar and "Whisper" in ar


def test_legacy_pack_keeps_the_old_copy_for_the_kill_switch():
    legacy = _pack(_src(), "LEGACY", "en")
    for must in ("upgradeBtn", "freeLeft", "signInForMore", "referSub", "emailCaptureTitle", "usesCredit", "guidesLeft"):
        assert re.search(r"^    %s:" % must, legacy, re.M), f"LEGACY.en lost {must}"


# ── 5. the bundle that is actually served ─────────────────────────────────────
def test_served_bundle_is_the_free_client():
    name, js = _served()
    for marker in ("fair_use_device", "fair_use_ip", "fair_use_user", "busy_today", "alimne_join_dismissed",
                   # the sign-in gate
                   "signin_required", "signin_after", "anon_remaining", "free_uses", "alimne_gate_v1",
                   "guides need no account.", "Create a free account to keep going", "free guides left",
                   "أنشئ حساباً مجانياً للمتابعة"):
        assert marker in js, f"{name} is missing {marker!r} - rebuild: cd frontend && npm run build"
    for stale in ("No sign-up needed", "no sign-up needed", "Try free, no sign-up", "no account needed ·",
                  "لا حاجة إلى حساب", "مجاني · بدون تسجيل", "come back tomorrow"):
        assert stale not in js, f"{name} still ships the unqualified claim {stale!r} - rebuild: cd frontend && npm run build"
    assert re.search(r"\.free_mode\s*!==\s*(?:!1|false)", js), f"{name} does not read free_mode from /api/config"
    assets = os.path.join(DIST, "assets")
    js_files = sorted(f for f in os.listdir(assets) if f.endswith(".js"))
    assert js_files == [os.path.basename(name)], f"stale bundles in dist/assets: {js_files}"
    css_files = [f for f in os.listdir(assets) if f.endswith(".css")]
    with open(os.path.join(DIST, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    assert len(css_files) == 1 and f"/assets/{css_files[0]}" in html, f"index.html must load the one css file: {css_files}"


# ── 6. the sign-in gate: N guides without an account, then a free account ─────
GATE_KEYS = ["anonLeft", "anonNone", "signinRequired", "signInToContinue", "gateCleared", "generateNow", "dropFreeUser"]


@pytest.mark.parametrize("key", GATE_KEYS)
def test_gate_keys_exist_in_both_languages(key):
    src = _src()
    for lang in ("en", "ar"):
        assert key in _keys(_pack(src, "T", lang)), f"T.{lang} is missing {key}"


def test_gate_strings_are_present_in_english_and_arabic():
    src = _src()
    en, ar = _pack(src, "T", "en"), _pack(src, "T", "ar")
    for must in ("Create a free account to keep going — it's still free.", "free guides left", "'Sign in to continue — free'",
                 "'Sign in to continue (free)'", "guides need no account.", "without an account · then a free sign-in"):
        assert must in en, f"T.en lost the gate string {must!r}"
    for must in ("أنشئ حساباً مجانياً للمتابعة", "أدلة مجانية", "سجّل الدخول للمتابعة — مجاناً", "سجّل الدخول للمتابعة (مجاناً)",
                 "لا تحتاج إلى حساب", "دون حساب · ثم تسجيل دخول مجاني"):
        assert must in ar, f"T.ar lost the gate string {must!r}"
    for lang, pack in (("en", en), ("ar", ar)):
        line = next(l for l in pack.splitlines() if l.startswith("    signinRequired:"))
        assert "${n}" in line, f"T.{lang}.signinRequired must quote the real number, not a hard-coded 3"
    # the old device message promised a daily refill ("come back tomorrow"): the allowance is not daily any more
    assert "errFairDevice" not in src and "come back tomorrow" not in en and "عُد غداً" not in ar


def test_gate_numbers_come_from_config_with_default_three():
    src = _src()
    assert re.search(r"^const FREE_USES_DEFAULT = 3$", src, re.M), "defaults are 3 / 3 / 3 when /api/config has no numbers"
    body = _block(src, r"^const gateFromConfig = ", r"^\}\n")
    for field in ("signin_after", "anon_free_limit", "anon_remaining"):
        assert field in body, f"gateFromConfig must read {field} from /api/config"
    assert "FREE_USES_DEFAULT" in body
    assert "gateFromConfig(cfg)" in src, "/api/config must feed the gate"
    assert re.search(r"useState\(\(\) => gateFromConfig\(null\)\)", src), "before /api/config answers the gate is 3 of 3"


def test_signin_required_is_mapped_stops_the_batch_and_offers_sign_in():
    src = _src()
    body = _block(src, r"^function friendlyErr\(", r"^\}\n")
    assert "'signin_required'" in body and "t.signinRequired(" in body and "free_uses" in body
    assert body.index("'signin_required'") < body.index("status === 0"), "the gate text must win over the generic texts"
    assert re.search(r"const GATE_CODES = new Set\(\['signin_required', 'fair_use_device'\]\)", src)
    assert re.search(r"const STOP_CODES = new Set\(\[[^\]]*'signin_required'", src), "a sign-in refusal stops the batch"
    assert re.search(r"const offersSignIn = \(item, session\) => .*GATE_CODES\.has\(item\.errCode\).*!session", src)


def test_every_generation_entry_point_checks_the_gate_before_sending():
    src = _src()
    gate = _block(src, r"const gateBlocks = ", r"\n  \}\n")
    assert "anonGated(" in gate and "openGate(" in gate, "0 guides left + signed out -> open the sign-in modal, send nothing"
    assert re.search(r"const openGate = .*\n(?:.*\n){0,6}?.*openLogin\('signup', null, ", src), "the gate opens the modal in sign-up mode with the notice"
    bodies = {
        "processAll": _block(src, r"const processAll = ", r"\n  // ── YouTube SSE"),
        "processYoutube": _block(src, r"const processYoutube = ", r"\n  // ── Paste text"),
        "processText": _block(src, r"const processText = ", r"\n  // ── Zero-friction demo"),
        "regenerate": _block(src, r"const regenerate = ", r"\n  const recoverItem"),
    }
    for name, body in bodies.items():
        assert "gateBlocks()" in body, f"{name} must check the sign-in gate before it sends a generation"
    assert bodies["processAll"].index("gateBlocks()") < bodies["processAll"].index("setRunning(true)")
    for name in ("processYoutube", "processText"):
        assert bodies[name].index("gateBlocks()") < bodies[name].index("setQueue("), \
            f"{name}: the gate must stop before an item is queued (the URL / text stays in its box)"
    assert bodies["regenerate"].index("gateBlocks()") < bodies["regenerate"].index("updateItem(")
    assert re.search(r"src\.type !== 'sample' && gateBlocks\(\)", bodies["regenerate"]), "retrying the sample is never gated"
    # a batch that uses the last free guide stops before the next file instead of sending it
    assert bodies["processAll"].count("gateBlocks()") >= 2


def test_the_sample_lecture_is_never_gated():
    src = _src()
    sample = _block(src, r"const runSample = ", r"\n  // Expired / failed item")
    assert "gateBlocks" not in sample and "openGate" not in sample and "demo: true" in sample
    assert re.search(r"<button onClick=\{startSample\} disabled=\{running\}", src), "the sample button stays usable at 0 guides left"
    # a demo stream never moves the counter, and a demo refusal never opens the sign-in modal
    done = _block(src, r"const onGenEvent = ", r"\n  // One generation for item")
    assert re.search(r"if \(!demo && freeRef\.current && !hadBearer\) setGate\(g => gateAfterDone\(g, ev\)\)", done)
    run = _block(src, r"const runGeneration = ", r"\n  const genOpts")
    assert re.search(r"if \(!demo && !sessionRef\.current && GATE_CODES\.has\(code\)\)", run)


def test_the_401_holds_the_item_without_losing_its_source_and_sign_in_clears_it():
    src = _src()
    auth = _block(src, r"const handleAuthError = ", r"\n  const addFiles")
    assert re.search(r"if \(!sessionRef\.current && GATE_CODES\.has\(code\)\) \{ holdForSignIn\(id, data\); return true \}", auth)
    assert auth.index("holdForSignIn(id, data)") < auth.index("openLogin('signin')"), "the gate branch comes before the plain 401"
    hold = _block(src, r"const holdForSignIn = ", r"\n  \}\n")
    assert "status: 'queued'" in hold and "errCode: 'signin_required'" in hold and "error: null" in hold, "a held item is not an error"
    assert "remaining: 0" in hold and "openGate(" in hold
    for lost in ("file:", "source:", "name:"):
        assert lost not in hold, f"holding an item for sign-in must not touch its {lost[:-1]}"
    after = _block(src, r"const afterSignIn = ", r"\n  \}\n")
    assert "errCode: null" in after and "tRef.current.gateCleared" in after and "setShowLogin(false)" in after
    assert re.search(r"setTimeout\(\(\) => \{ fetchUserInfo\(\); fetchRefStats\(\); afterSignIn\(\) \}, 0\)", src), \
        "a new sign-in clears the gate (outside the auth lock)"
    # the held row: a sign-in button while signed out, a Generate button for a link / text once signed in
    assert "t.signInToContinue" in src and "t.generateNow" in src and "badgeKey(item, session)" in src


def test_the_counter_follows_the_stream_and_sign_out_refetches_config():
    src = _src()
    assert "countInt(ev?.anon_remaining)" in _block(src, r"^const gateAfterDone = ", r"^\}\n")
    out = _block(src, r"const signOut = async ", r"\n  // Explicit sign-out")
    assert "loadConfig(" in out, "after sign-out the anonymous allowance is read again from /api/config"
    assert re.search(r"\{freeMode && gateKnown && <AnonCounter ", src), \
        "signed-out visitors see the counter in free mode, once a real number is known"
    assert "setAnonGate(next); setGateKnown(true)" in src and re.search(r"if \(live\(\)\) setGateKnown\(true\)", src), \
        "the counter appears with the first real number, or with the default when /api/config never answers"
    nav = _block(src, r"\{/\* Auth controls \*/\}", r"<Globe size=\{13\} />")
    signed_in, signed_out = nav.split("{/* Anonymous free-preview counter", 1)
    assert "<AnonCounter" in signed_out and "<AnonCounter" not in signed_in, "signed-in users see no counter"
    assert re.search(r"!freeMode && anonInfo && anonInfo\.limit > 0", signed_out), "token mode keeps its own badge"


# "No sign-up needed" is only true for the first N guides. A line that claims it must carry the qualifier.
CLAIM_EN = re.compile(r"\bno sign-?up\b|\bno account\b|\bwithout an account\b|\bno registration\b|\bwithout (?:signing|registering)\b", re.I)
QUAL_EN = re.compile(r"\bfirst\b|guides?`?\}? (?:left )?without an account|\{FREE_GUIDES\}|\bsample\b", re.I)
CLAIM_AR = re.compile(r"(?:بدون|دون|بلا|من غير) (?:تسجيل|حساب)|لا حاجة إلى (?:حساب|تسجيل)|(?:يحتاج|تحتاج|يحتاجان) إلى (?:حساب|تسجيل)")
QUAL_AR = re.compile(r"أول|الأول|أدلة|\{FREE_GUIDES\}|النموذجية")


def _unqualified(text, lang):
    claim, qual = (CLAIM_AR, QUAL_AR) if lang == "ar" else (CLAIM_EN, QUAL_EN)
    return [l.strip()[:120] for l in text.splitlines() if claim.search(l) and not qual.search(l)]


def test_no_sign_up_patterns_catch_each_old_claim_and_accept_the_new_copy():
    for old in ["heroFree: 'Free. No card. No sign-up needed.',", "dropFree: 'Free to use · no account needed · fair-use daily limits apply',",
                "freeTry: 'Try free, no sign-up',", "trust: ['Free · no sign-up needed', 'Files wiped in 15 min'],",
                "• Alimne is free to use. No payment is needed, and you can try it without an account."]:
        assert _unqualified(old, "en"), old
    for old in ["heroFree: 'مجاني. بدون بطاقة. لا حاجة إلى حساب.',", "dropFree: 'مجاني للاستخدام · بدون حساب · تُطبَّق حدود يومية',",
                "freeTry: 'جرّب مجاناً، بدون تسجيل',", "trust: ['مجاني · بدون تسجيل'],", "• علّمني مجاني للاستخدام، ويمكنك تجربته دون حساب."]:
        assert _unqualified(old, "ar"), old
    assert not _unqualified("Free. No card. Your first 3 guides need no account.", "en")
    assert not _unqualified("sampleCtaSub: 'No file needed. Watch a real study guide build in seconds.',", "en")
    assert not _unqualified("noAccount: 'New here? Create a free account',", "en")
    assert not _unqualified("مجاني. بدون بطاقة. أول 3 أدلة لا تحتاج إلى حساب.", "ar")
    assert not _unqualified("loginSub: 'سجّل الدخول إلى حسابك',", "ar")


def test_free_mode_copy_makes_no_unqualified_no_sign_up_claim():
    src = _src()
    for lang in ("en", "ar"):
        bad = _unqualified(_pack(src, "T", lang), lang)
        assert not bad, f"T.{lang} claims 'no sign-up / no account needed' without the first-N-guides qualifier: {bad}"
    bad = _unqualified(_block(src, r"^const TERMS_EN = `", r"^`|`\n"), "en") + _unqualified(_block(src, r"^const TERMS_EN_TAIL = `", r"`"), "en")
    assert not bad, f"in-app Terms (EN): {bad}"
    bad = _unqualified(_block(src, r"^const TERMS_AR = `", r"^`|`\n"), "ar") + _unqualified(_block(src, r"^const TERMS_AR_TAIL = `", r"`"), "ar")
    assert not bad, f"in-app Terms (AR): {bad}"
    for stale in ("No sign-up needed", "no sign-up needed", "no account needed ·", "Try free, no sign-up", "freeTry",
                  "لا حاجة إلى حساب", "مجاني · بدون تسجيل", "جرّب مجاناً، بدون تسجيل", "ويمكنك تجربته دون حساب"):
        assert stale not in src, f"stale unqualified claim still in App_dev.jsx: {stale!r}"


def test_the_in_app_terms_state_the_gate_in_both_languages():
    src = _src()
    en = _block(src, r"^const TERMS_EN = `", r"^`|`\n")
    ar = _block(src, r"^const TERMS_AR = `", r"^`|`\n")
    assert "Without an account you can make your first {FREE_GUIDES}" in en and "a free account is required" in en
    assert "Fair-use limits apply to accounts" in en
    assert "{FREE_GUIDES} دون حساب" in ar and "يلزم حساب مجاني" in ar and "حدود الاستخدام العادل على الحسابات" in ar
    # the number is filled in from /api/config when the Terms are shown, never left as a placeholder
    assert re.search(r"const termsText = \(lang, freeMode, n\) =>", src) and "termsText(lang, freeMode, freeUses)" in src
    assert "higher daily allowance than anonymous" not in en and "الزوّار بلا حساب" not in ar


def test_token_mode_copy_is_untouched_by_the_gate():
    """ALIMNE_FREE_MODE=0 must read exactly as before: the legacy pack and legacy Terms keep their words."""
    src = _src()
    legacy_en, legacy_ar = _pack(src, "LEGACY", "en"), _pack(src, "LEGACY", "ar")
    assert "trust: ['No sign-up to try', 'Files wiped in 15 min', 'English & العربية']," in legacy_en
    assert "heroFree: ''," in legacy_en and "dropFree: ''," in legacy_en
    assert "trust: ['بدون تسجيل للتجربة', 'تُمسح الملفات خلال 15 دقيقة', 'الإنجليزية والعربية']," in legacy_ar
    assert "• Free: 2 anonymous previews (no account needed), then 3 free guides on sign-up and 3 free guides every month." \
        in _block(src, r"^const TERMS_EN_LEGACY = `", r"^`|`\n")
    for key in GATE_KEYS:
        assert key not in _keys(legacy_en) and key not in _keys(legacy_ar), f"{key} belongs to the free-mode pack only"


def test_token_mode_never_runs_the_gate():
    """Every gate path is switched on free mode: the counter, the pre-flight check, the count-down,
    the numbers from /api/config and the config refetch after sign-out."""
    src = _src()
    assert re.search(r"const anonGated = \(\{ freeMode, authEnabled, authLoading, session, remaining \}\) =>\s*\n\s*!!\(freeMode && ", src)
    assert "anonGated({ freeMode: freeRef.current, " in _block(src, r"const gateBlocks = ", r"\n  \}\n")
    assert re.search(r"if \(cfg\.free_mode !== false\) setGate\(\(\) => gateFromConfig\(cfg\)\)", src)
    # token mode keeps reading its own preview counter exactly as before
    assert "if (cfg.anon_free_limit !== undefined)\n          setAnonInfo({ limit: cfg.anon_free_limit, remaining: cfg.anon_remaining ?? cfg.anon_free_limit })" in src
    assert "if (freeRef.current) loadConfig(2)" in _block(src, r"const signOut = async ", r"\n  // Explicit sign-out")
    assert re.search(r"const gateText = freeMode && posInt\(gateUses\) \? ", src), "the modal notice is a free-mode thing"
    assert re.search(r"const dropLine\s+= freeMode && session \? t\.dropFreeUser : say\(t\.dropFree, anonGate\.limit\)", src)
    # the token-mode strings are plain '' there, so the hero / dropzone lines stay hidden as before
    assert "const say = (v, ...args) => typeof v === 'function' ? v(...args) : v" in src


@pytest.mark.parametrize("rel", ["frontend/index.html", "dist/index.html"])
def test_index_metadata_makes_no_unqualified_no_sign_up_claim(rel):
    with open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8") as fh:
        html = fh.read()
    texts = re.findall(r"<title>(.*?)</title>", html, re.S) + re.findall(r'<meta\s[^>]*?content="([^"]*)"', html)
    assert len(texts) > 8, "title / meta tags not found"
    qualified = re.compile(r"\bfirst (?:\d+|three) (?:free |study )?guides\b", re.I)
    for text in texts:
        assert not CLAIM_EN.search(text) or qualified.search(text), f"{rel}: unqualified claim in metadata: {text!r}"
        assert not CLAIM_AR.search(text), f"{rel}: unqualified claim in metadata: {text!r}"
        assert "unlimited" not in text.lower()


# ── 7. behaviour: bundle the real source and render it (needs node + npm ci) ──
_HAVE_NODE = shutil.which("node") and os.path.isdir(os.path.join(ROOT, "frontend", "node_modules", "esbuild"))


@pytest.mark.skipif(not _HAVE_NODE, reason="node or frontend/node_modules (npm ci) not available")
def test_free_mode_behaviour_script_passes():
    r = subprocess.run(["node", VERIFY], cwd=os.path.join(ROOT, "frontend"), capture_output=True, text=True, timeout=240)
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, "verify-free-mode.mjs failed:\n" + out[-4000:]
    assert " failed" in out and "0 failed" in out, out[-500:]
