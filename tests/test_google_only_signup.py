"""
Google-only sign-up (owner's decision, 2026-10-07): "Make it sign up with Google only. Easier for
registration." One exception, also the owner's: inside an in-app browser (Instagram, TikTok, ...),
where Google refuses to sign anyone in, the visitor gets an "Open in browser" button AND email
sign-up as a fallback.

What the client (frontend/src/App_dev.jsx, LoginModal) must do:

  * NORMAL BROWSER, sign-up and sign-in mode alike: ONE primary action, "Continue with Google"
    (the same google() call, with its sign-in stash hooks). No email / password field, no "or"
    divider and no sign-up toggle by default. The gate's reason box, the perks note, the notice
    (expired link, session expired, OAuth error) and the Terms line stay. A quiet link opens an
    email SIGN-IN-ONLY view for the accounts that were made with an email and a password (email,
    password, forgot password, resend confirmation, back to Google). Nothing in a normal browser
    can ever call supabase.auth.signUp.
  * IN-APP BROWSER: a notice that Google sign-in is not allowed inside this app, a primary "Open
    in browser" button (Android: intent:// with scheme=https, so the default browser; iPhone / iPad:
    x-safari-https://), the manual way when the page is still in front about 1.8 s later, the
    Copy link button, and under a divider the email form with its sign-up / sign-in toggle exactly
    as it worked before. No Google button there.
  * The link handed to the real browser is https://<origin>/?join=1 (plus the invite code, nothing
    else). On load ?join=1 comes off the address and, with nobody signed in, the sign-up modal opens.
    The OAuth return, the recovery / confirmation links and the referral code are left alone.

And every place that says how an account is made says the same: the in-app Terms, /terms, /privacy
(which must stay true to what the server really stores), the operator manual.

There is no JS test runner. These are static checks of the source and of the bundle in dist/, plus
the Flask pages through the test client (offline). The rendered modal (both browsers, both
languages) is checked by frontend/scripts/verify-free-mode.mjs, section 13, which
tests/test_free_mode_client.py runs.
"""
import os
import re

import pytest

import app as appmod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JSX = os.path.join(ROOT, "frontend", "src", "App_dev.jsx")
DIST = os.path.join(ROOT, "dist")
VERIFY = os.path.join(ROOT, "frontend", "scripts", "verify-free-mode.mjs")
MANUAL = os.path.join(ROOT, "docs", "FREE-MODE.md")

# The copy this change added or reworded (the same list the node script checks in both languages)
LOGIN_KEYS = ["loginSub", "loginTitleSignup", "loginSubSignup", "emailSignInLink", "emailSignInTitle", "emailSignInSub",
              "backToGoogle", "inAppGoogle", "openInBrowser", "openManual", "orEmailSignup", "orEmailSignin", "wrongPassword"]


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _src():
    return _read(APP_JSX)


def _block(src, start_pat, end_pat):
    m = re.search(start_pat, src, re.M)
    assert m, f"{start_pat!r} not found"
    e = re.search(end_pat, src[m.end():], re.M)
    assert e, f"{end_pat!r} not found after {start_pat!r}"
    return src[m.end(): m.end() + e.start()]


def _pack(src, lang):
    """Body of T.<lang> (4-space keys; en then ar)."""
    start = re.search(r"^const T = \{", src, re.M)
    body = src[start.end():]
    body = body[: re.search(r"^\}\n", body, re.M).start()]
    en, ar = re.search(r"^  en: \{", body, re.M), re.search(r"^  ar: \{", body, re.M)
    return body[en.end(): ar.start()] if lang == "en" else body[ar.end():]


def _line(pack, key):
    lines = [l for l in pack.splitlines() if l.startswith(f"    {key}:")]
    assert len(lines) == 1, (key, len(lines))
    return lines[0]


def _modal(src):
    return _block(src, r"^function LoginModal\(", r"^\}\n")


def _views(modal):
    """The modal's bodies: (in-app browser, email sign-in view, the default view, what follows all three).
    The marks are whole lines at the branch's own indent (12 spaces)."""
    def at(mark, start=0):
        m = re.compile("^" + re.escape(mark) + "$", re.M).search(modal, start)
        assert m, f"LoginModal: {mark.strip()!r} not found"
        return m.start()
    a = at("            {IN_APP ? (")
    b = at("            ) : emailOnly ? (", a)
    c = at("            ) : (", b)
    d = at("            )}", c)
    return modal[a:b], modal[b:c], modal[c:d], modal[d:]


def _served():
    html = _read(os.path.join(DIST, "index.html"))
    refs = re.findall(r'src="/?(assets/index-[\w-]+\.js)"', html)
    assert len(refs) == 1, f"dist/index.html should load exactly one bundle, found {refs}"
    return refs[0], _read(os.path.join(DIST, *refs[0].split("/")))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("ALIMNE_FREE_MODE", raising=False)   # default = free mode
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def _page(client, path):
    r = client.get(path)
    assert r.status_code == 200, path
    return re.sub(r"\s+", " ", r.get_data(as_text=True))


# ── 1. a normal browser: one Google button ────────────────────────────────────
def test_the_default_view_is_one_google_button_and_no_email_form():
    modal = _modal(_src())
    in_app, email_view, default, _ = _views(modal)
    assert "onClick={google}" in default and "{t.loginBtn}" in default, "the default view is the Google button"
    assert default.count('className="submit-btn"') == 1, "ONE primary action"
    for gone in ("{emailForm}", "<form", "<input", "t.noAccount", "t.haveAccount", "t.emailBtnSignup", "setMode(", "t.forgotPw"):
        assert gone not in default, f"the default view must not show {gone}"
    assert "{alertBox}" in default, "a notice (expired link, session expired, OAuth error) still shows"
    assert default.index("{alertBox}") < default.index("onClick={google}")
    # the email view is closed by default: only the link, or an email link that came back expired, opens it
    assert re.search(r"const \[byEmail, setByEmail\]\s*= useState\(!!notice\?\.byEmail\)", modal)
    assert "const emailOnly = !IN_APP && byEmail" in modal
    assert modal.count("onClick={google}") == 1 and modal.count("setByEmail(true)") == 1
    assert "setByEmail(true)" in default and "{t.emailSignInLink}" in default, "the quiet link for the accounts made with an email"
    assert default.index("onClick={google}") < default.index("{t.emailSignInLink}"), "the link sits under the button"


def test_the_gate_reason_the_perks_note_and_the_terms_line_stay():
    modal = _modal(_src())
    assert "const gateText = freeMode && gate ? signinText(t, gate.reason, gate.uses, gate.text) : null" in modal
    assert "{gateText && !sentTo && (" in modal and "<span>{gateText}</span>" in modal
    assert "<span>{t.perksNote(perksOf(t, fair))}</span>" in modal
    after = _views(modal)[3]
    assert "By continuing, you agree to our Terms & Conditions" in after and "بالمتابعة، أنت توافق على شروطنا وأحكامنا" in after, \
        "the Terms line is under every view"
    # short titles for both modes; the line under them comes from the pack (token mode keeps its own promise)
    assert "{sentTo ? t.checkInboxTitle : emailOnly ? t.emailSignInTitle : isSignup ? t.loginTitleSignup : t.signIn}" in modal
    sub = _block(modal, r"  const sub = ", r"\n  const later")
    assert "!IN_APP ? (isSignup ? t.loginSubSignup : t.loginSub)" in sub and "(isSignup && !freeMode) ? t.loginSubSignup : null" in sub


def test_the_email_view_signs_in_and_can_create_no_account():
    modal = _modal(_src())
    in_app, email_view, default, _ = _views(modal)
    assert "{emailForm}" in email_view and "{t.backToGoogle}" in email_view and "setByEmail(false)" in email_view
    for gone in ("setMode(", "t.noAccount", "t.haveAccount", "onClick={google}", "t.orEmailSignup"):
        assert gone not in email_view, f"the email view is sign-in only: found {gone}"
    form = _block(modal, r"  const emailForm = \(", r"\n  \)\n")
    for must in ('type="email"', 'type="password"', "onClick={forgot}", "{t.forgotPw}", "{alertBox}", "{needConfirm && (",
                 "resend(email.trim())", "{t.resendConfirm}", "onSubmit={emailAuth}"):
        assert must in form, f"the email form lost {must}"
    # what the form does is decided by `creating` alone: a new password and "Create free account" only then
    assert "autoComplete={creating ? 'new-password' : 'current-password'}" in form
    assert "(creating ? t.emailBtnSignup : t.emailBtn)" in form and "{!creating && (" in form
    assert "isSignup" not in form


def test_sign_up_is_reachable_only_inside_an_in_app_browser():
    src = _src()
    modal = _modal(src)
    assert src.count("auth.signUp(") == 1 and modal.count("auth.signUp(") == 1, "one sign-up call, in the modal"
    assert "  const creating = IN_APP && isSignup\n" in modal, "an email account is created inside an in-app browser only"
    auth = _block(modal, r"  const emailAuth = \(e\) => \{", r"\n  \}\n")
    assert "isSignup" not in auth, "nothing but `creating` may decide between sign-up and sign-in"
    assert auth.index("if (creating) {") < auth.index("sbClient.auth.signUp(") < auth.index("} else {") < auth.index("sbClient.auth.signInWithPassword(")
    # the mode can only become 'signup' through the toggle, and the toggle exists in the in-app view only
    in_app, email_view, default, _ = _views(modal)
    toggle = "setMode(isSignup ? 'signin' : 'signup')"
    assert modal.count(toggle) == 1 and toggle in in_app
    others = [m for m in re.findall(r"setMode\([^)]*\)", modal) if m != toggle]
    assert others and set(others) == {"setMode('signin')"}, others
    # ...and a normal browser never renders the form in sign-up shape, whatever mode the gate opened the modal in
    assert "{emailForm}" not in default


# ── 2. an in-app browser: the notice, the way out, the email form ─────────────
def test_in_app_detection_is_unchanged():
    assert ("const IN_APP = (() => { try { return /Instagram|FBAN|FBAV|FB_IAB|TikTok|musical_ly|Snapchat|Line\\/|; wv\\)/i"
            ".test(navigator.userAgent || '') } catch { return false } })()") in _src()


def test_the_in_app_view_keeps_email_sign_up_and_offers_open_in_browser():
    modal = _modal(_src())
    in_app, email_view, default, _ = _views(modal)
    for must in ("{t.inAppGoogle}", 'className="submit-btn" onClick={openInBrowser}', "{t.openInBrowser}", "{stayed && (",
                 "{t.openManual}", "onClick={copyLink}", "t.copyLink", "{emailForm}", "isSignup ? t.orEmailSignup : t.orEmailSignin",
                 "{isSignup ? t.haveAccount : t.noAccount}"):
        assert must in in_app, f"the in-app view lost {must}"
    assert "onClick={google}" not in in_app and "t.loginBtn" not in in_app, "no Google button where Google refuses to work"
    order = [in_app.index(x) for x in ("{t.inAppGoogle}", "onClick={openInBrowser}", "onClick={copyLink}", "t.orEmailSignup", "{emailForm}", "t.haveAccount")]
    assert order == sorted(order), "notice, Open in browser, Copy link, the divider, the form, the toggle"
    # the sign-up flow behind the form is the one it always was
    auth = _block(modal, r"  const emailAuth = \(e\) => \{", r"\n  \}\n")
    assert "sbClient.auth.signUp({ email: em, password, options: { emailRedirectTo: window.location.origin } })" in auth
    assert "if (!data?.session) { setSentTo(em); return }" in auth and "data.user.identities.length === 0" in auth
    for must in ("{t.checkInbox(sentTo)}", "onClick={() => resend(sentTo)}", "{t.resendEmail}", "{t.backToSignIn}"):
        assert must in modal, f"the check-your-inbox panel lost {must}"
    assert "sbClient.auth.resend({ type: 'signup', email: em, options: { emailRedirectTo: window.location.origin } })" in modal
    assert "sbClient.auth.resetPasswordForEmail(em, { redirectTo: window.location.origin })" in modal


def test_open_in_browser_tries_once_and_fails_gracefully():
    src = _src()
    modal = _modal(src)
    go = _block(modal, r"  const openInBrowser = \(\) => \{", r"\n  \}\n")
    assert "const to = browserHandoff(outLink(), navigator.userAgent)" in go
    assert "try { window.location.href = to } catch" in go, "an address the browser refuses must not throw"
    assert "setStayed(!to)" in go and "if (!to) return" in go, "no such address on this device: straight to the manual way"
    wait = re.search(r"later\(\(\) => \{ if \(!wentAway\.current\) setStayed\(true\) \}, (\d+)\)", go)
    assert wait and 1500 <= int(wait.group(1)) <= 2000, "still in front about 1.5 to 2 s later -> the manual instruction"
    # whether the page left is seen, not guessed: hidden since the tap means the phone followed
    assert "document.addEventListener('visibilitychange', away)" in modal and "document.removeEventListener('visibilitychange', away)" in modal
    assert "if (document.visibilityState === 'hidden') wentAway.current = true" in modal
    # one try per tap and nothing that could loop or blank the page
    assert modal.count("window.location.href = ") == 1 and "openInBrowser()" not in src
    for risky in ("location.reload", "location.replace", "location.assign", "window.open(", "setInterval(", "browser_fallback_url"):
        assert risky not in modal, f"the modal must not {risky}"
    # Copy link hands out the same link
    assert "const outLink = () => joinLink(window.location.origin, window.location.search, ls.get('alimne_ref'))" in modal
    assert "const link = outLink()" in _block(modal, r"  const copyLink = async \(\) => \{", r"\n  \}\n")


def test_the_handoff_addresses_and_the_link_they_carry():
    src = _src()
    hand = _block(src, r"^function browserHandoff\(link, ua\) \{", r"^\}\n")
    assert "if (/Android/i.test(ua || '')) return `intent://${m[1]}#Intent;scheme=https;end`" in hand, \
        "Android: an intent with scheme=https (the default browser)"
    assert "if (/iPhone|iPad|iPod/i.test(ua || '')) return `x-safari-https://${m[1]}`" in hand
    assert "package=" not in hand and "chrome" not in hand.lower(), "no hard dependency on Chrome"
    assert r"/^https:\/\/(.+)$/" in hand and "if (!m) return ''" in hand, "only an https link has such an address"
    link = _block(src, r"^function joinLink\(origin, search, keptRef\) \{", r"^\}\n")
    assert "return `${origin}/?join=1${REF_CODE_RE.test(ref) ? `&ref=${ref.toUpperCase()}` : ''}`" in link
    assert "new URLSearchParams(search || '').get('ref')" in link
    for leak in ("hash", "href", "window", "access_token", "location"):
        assert leak not in link, f"the link must carry ?join=1 and the invite code only: found {leak}"
    assert re.search(r"^const REF_CODE_RE = /\^\[A-Za-z0-9\]\{4,32\}\$/$", src, re.M), "an invite code is a plain code or it does not travel"


# ── 3. ?join=1 on arrival ─────────────────────────────────────────────────────
def test_join_opens_the_sign_up_modal_once_and_comes_off_the_address():
    src = _src()
    assert ("const JOIN_IN_URL = (() => { try { return new URLSearchParams(window.location.search).get('join') === '1' } "
            "catch { return false } })()") in src, "?join=1 is read once, at load"
    block = _block(src, r'^  // ── Arrived from "Open in browser"', r"^  // ── /api/config")
    assert "window.history.replaceState(window.history.state, '', withoutJoin(window.location))" in block
    assert "if (!JOIN_IN_URL) return" in block and "if (!JOIN_IN_URL || authLoading || joinAsked.current) return" in block
    assert "joinAsked.current = true" in block, "the modal opens once per page load"
    assert "if (!session && authEnabled && !AUTH_URL_ERR && !RECOVERY_IN_URL) openLogin('signup')" in block, \
        "only with nobody signed in, and never over a link that came back with an error or for a password reset"
    assert "}, [authLoading])" in block, "it waits for the session restore to answer"
    for leak in ("signinStash", "gateNote", "openGate(", "setSession", "sb.auth"):
        assert leak not in block, f"?join=1 must not touch {leak}"
    without = _block(src, r"^function withoutJoin\(loc\) \{", r"^\}\n")
    assert "q.delete('join')" in without and "return loc.pathname + (qs ? `?${qs}` : '') + loc.hash" in without, \
        "only ?join=1 goes: other query data and the hash (the OAuth return lives there) stay"


def test_the_referral_capture_the_oauth_return_and_recovery_are_as_they_were():
    src = _src()
    ref = _block(src, r"^  // ── Capture referral code from URL", r"^  // ── OAuth / email-link errors")
    for must in ("const ref = params.get('ref')", "if (!ref) return", "ls.set('alimne_ref', ref.toUpperCase())", "params.delete('ref')",
                 "window.history.replaceState(window.history.state, '', window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash)"):
        assert must in ref, f"the referral capture changed: {must}"
    assert "join" not in ref.lower()
    assert "const RECOVERY_IN_URL = (() => { try { return /(^#|&)type=recovery(&|$)/.test(window.location.hash) } catch { return false } })()" in src
    assert "if (event === 'PASSWORD_RECOVERY' || (event === 'INITIAL_SESSION' && sess && RECOVERY_IN_URL)) setShowSetPw(true)" in src
    assert "const sb = (() => { try { return createClient(SB_URL, SB_ANON) }" in src
    assert "sbClient.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: window.location.origin } })" in src
    assert "await sbClient.auth.updateUser({ password: pw })" in _block(src, r"^function SetPasswordModal\(", r"^\}\n")
    # an email link that came back expired opens the modal on the view where a password can be typed
    err = _block(src, r"^  // ── OAuth / email-link errors", r'^  // ── Arrived from "Open in browser"')
    assert "openLogin('signin', { type: 'error', text: expired ? t.linkExpired : t.authLinkError, byEmail: expired })" in err


# ── 4. the words ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("key", LOGIN_KEYS)
def test_sign_in_copy_exists_in_both_languages(key):
    src = _src()
    en, ar = _line(_pack(src, "en"), key), _line(_pack(src, "ar"), key)
    assert re.search(r"[؀-ۿ]", ar), f"T.ar.{key} is not Arabic: {ar}"
    for line in (en, ar):
        assert "—" not in line, f"no em dash in new copy: {line.strip()}"
        assert not re.search(r"unlimited|one[- ]tap|\binstant|غير محدود|بلا حدود|بنقرة واحدة|فوراً", line, re.I), line.strip()


def test_the_title_and_sub_are_short_and_true():
    src = _src()
    en, ar = _pack(src, "en"), _pack(src, "ar")
    assert _line(en, "loginTitleSignup") == "    loginTitleSignup: 'Create your free account',"
    assert _line(en, "loginSubSignup") == "    loginSubSignup: 'Continue with Google. No password, no card.',"
    assert _line(en, "loginSub").startswith("    loginSub: 'Continue with the Google account you signed up with.")
    assert _line(en, "emailSignInLink") == "    emailSignInLink: 'Signed up with email? Sign in with email',"
    assert _line(ar, "loginTitleSignup") == "    loginTitleSignup: 'أنشئ حسابك المجاني',"
    assert _line(ar, "loginSubSignup") == "    loginSubSignup: 'تابِع عبر Google. بدون كلمة مرور وبدون بطاقة.',"
    # the notice names no app that was not detected (and no browser the phone may not have)
    for pack in (en, ar):
        for key in ("inAppGoogle", "openManual"):
            assert not re.search(r"Instagram|Facebook|TikTok|Snapchat|Safari|Chrome", _line(pack, key)), key
    assert "not allowed inside this app" in _line(en, "inAppGoogle") and "غير مسموح به داخل هذا التطبيق" in _line(ar, "inAppGoogle")
    assert _line(en, "orEmailSignup") == "    orEmailSignup: 'or sign up with email here',"


def test_the_copy_of_the_old_email_first_modal_is_gone():
    src = _src()
    for dead in ("orDivider", "Free, no card needed — create your account in a minute.", "مجاني وبدون بطاقة — أنشئ حسابك خلال دقيقة.",
                 "or use email below", "أو استخدم البريد الإلكتروني بالأسفل", "Use Continue with Google.", "'Create your account'",
                 "'Sign in to your account'", "doesn't work inside this app"):
        assert dead not in src, f"stale sign-up copy still in App_dev.jsx: {dead!r}"
    # every key the modal reads exists in the pack (a typo would render nothing, silently)
    modal = _modal(src)
    keys = set(re.findall(r"^    (\w+):", _pack(src, "en"), re.M))
    used = set(re.findall(r"\bt\.(\w+)", modal))
    assert used and used <= keys, f"the modal reads keys T.en does not have: {sorted(used - keys)}"


# ── 5. the in-app Terms ───────────────────────────────────────────────────────
def test_the_in_app_terms_say_how_an_account_is_made_and_what_it_keeps():
    src = _src()
    en = _block(src, r"^const TERMS_EN = `", r"^`|`\n")
    ar = _block(src, r"^const TERMS_AR = `", r"^`|`\n")
    assert '• Accounts are created with Google ("Continue with Google"). Inside an in-app browser' in en
    assert "where Google does not allow its sign-in, you can open Alimne in your browser, or create the account with an email address and a password." in en
    assert "• يُنشأ الحساب عبر Google («المتابعة عبر Google»)." in ar and "إنشاء الحساب ببريد إلكتروني وكلمة مرور." in ar
    account = _block(src, r"^const TERMS_ACCOUNT = \{", r"^\}\n")
    for must in ("your name, your email address and your profile picture", "an identifier for your Google account",
                 "We never see your Google password", "never to Alimne's own server",
                 "باسمك وبريدك الإلكتروني وصورة ملفك الشخصي", "لا نرى كلمة مرور Google", "لا إلى خادم علّمني"):
        assert must in account, f"TERMS_ACCOUNT lost {must!r}"
    assert "—" not in account
    text = _block(src, r"^const termsText = ", r"^\}\n")
    assert "TERMS_ACCOUNT.ar : TERMS_ACCOUNT.en" in text and text.index("TERMS_ACCOUNT") < text.index("TERMS_STASH")
    # token mode keeps its old Terms
    for legacy in ("TERMS_EN_LEGACY", "TERMS_AR_LEGACY", "TERMS_EN_TAIL", "TERMS_AR_TAIL"):
        body = _block(src, r"^const %s = `" % legacy, r"^`|`\n")
        assert "Accounts are created with Google" not in body and "يُنشأ الحساب عبر Google" not in body


# ── 6. /terms and /privacy ────────────────────────────────────────────────────
def test_privacy_says_what_google_sign_in_gives_and_it_is_what_the_server_stores(client):
    html = _page(client, "/privacy")
    assert "<strong>Your account:</strong> an account is created by continuing with Google." in html
    assert ("Google then gives us your <strong>email address</strong>, your name and your profile picture, "
            "with an identifier for your Google account.") in html
    assert "We never see your Google password, and we ask Google for nothing else." in html
    assert "to identify your account, to show it to you when you are signed in, and to apply the fair-use daily limits to your account." in html
    # ...and that is the whole of what the server takes from a sign-in: email, name, picture
    ident = appmod._identity_from_payload({"email": "s@uni.example", "sub": "google-oauth2|1",
                                           "user_metadata": {"full_name": "Sara", "avatar_url": "https://lh3.example/p.png",
                                                             "locale": "ar", "hd": "uni.example"}})
    assert ident == {"email": "s@uni.example", "name": "Sara", "avatar": "https://lh3.example/p.png"}
    assert "Google (sign-in)" in html.split("<h2>6. Third-party services</h2>")[1]
    # the old sentence described an account as "if you sign in" with an optional Google
    assert "If you sign in, we store your" not in html and "display name/avatar (when provided by" not in html


def test_privacy_covers_the_email_fallback_truthfully(client):
    html = _page(client, "/privacy")
    assert "<strong>Email accounts:</strong> inside an in-app browser (a page opened inside another app), where Google does not allow its sign-in," in html
    assert "an account can be created with an email address and a password instead, and accounts created that way earlier still work." in html
    assert "The password goes directly to our authentication provider (Supabase) and is never sent to Alimne's own server." in html
    # true because the server has no route that takes one: the only password field it serves is the admin token's
    src = _read(os.path.join(ROOT, "app.py"))
    assert not re.search(r"""get\(\s*["']password["']""", src) and "signInWithPassword" not in src and "sign_in_with_password" not in src
    assert "يُنشأ الحساب عبر Google، أو ببريد إلكتروني وكلمة مرور داخل متصفحات التطبيقات" in html


def test_terms_say_how_an_account_is_created(client):
    html = _page(client, "/terms")
    assert '<strong>Creating an account:</strong> accounts are created with Google ("Continue with Google").' in html
    assert ("Inside an in-app browser (a page opened inside another app), where Google does not allow its sign-in, "
            "you can open Alimne in your browser, or create the account with an email address and a password.") in html
    assert "يُنشأ الحساب عبر Google، أو ببريد إلكتروني وكلمة مرور داخل متصفحات التطبيقات حيث لا يسمح Google بتسجيل الدخول." in html
    assert html.index("<strong>Free account:</strong>") < html.index("<strong>Creating an account:</strong>") < html.index("<strong>Fair use:</strong>")


def test_token_mode_pages_keep_their_plans_and_the_same_account_facts(client, monkeypatch):
    monkeypatch.setenv("ALIMNE_FREE_MODE", "0")
    monkeypatch.setattr(appmod, "FREE_MODE", appmod._env_switch("ALIMNE_FREE_MODE"))
    terms, priv = _page(client, "/terms"), _page(client, "/privacy")
    assert "<h2>2. Plans &amp; billing</h2>" in terms and "Creating an account:" not in terms
    # the sign-in dialog is the same one in token mode, so the account facts are the same
    assert "<strong>Your account:</strong> an account is created by continuing with Google." in priv
    assert "and to track your monthly token balance." in priv and "<strong>Email accounts:</strong>" in priv


# ── 7. the bundle that is served, and the manual ──────────────────────────────
def test_the_served_bundle_is_the_google_only_client():
    name, js = _served()
    for marker in ("Create your free account", "Continue with Google. No password, no card.", "Signed up with email? Sign in with email",
                   "Back to Google sign-in", "Google sign-in is not allowed inside this app.", "Open in browser",
                   "or sign up with email here", "#Intent;scheme=https;end", "x-safari-https://", "/?join=1",
                   "أنشئ حسابك المجاني", "فتح في المتصفح", "أو أنشئ حسابك بالبريد الإلكتروني هنا",
                   "Accounts are created with Google", "We never see your Google password"):
        assert marker in js, f"{name} is missing {marker!r} - rebuild: cd frontend && npm run build"
    for stale in ("create your account in a minute", "or use email below", "Use Continue with Google.", "doesn't work inside this app"):
        assert stale not in js, f"{name} still ships the old sign-up copy {stale!r} - rebuild: cd frontend && npm run build"
    assert js.count(".auth.signUp(") == 1, "one sign-up call in the bundle"


def test_the_node_script_checks_the_rendered_modal_in_both_browsers():
    script = _read(VERIFY)
    for must in ("13. Google-only sign-up: the modal in a normal browser", "13b. Google-only sign-up: the way out of an in-app browser",
                 "13c. Google-only sign-up: the Terms say how an account is made", "'?in-app'", "MI.IN_APP === true"):
        assert must in script, f"verify-free-mode.mjs lost its check: {must}"
    keys = re.search(r"const LOGIN_KEYS = \[(.*?)\]", script, re.S).group(1)
    assert sorted(re.findall(r"'(\w+)'", keys)) == sorted(LOGIN_KEYS), "the node script and this file check the same copy"


def test_the_manual_describes_google_only_sign_up():
    doc = _read(MANUAL)
    for must in ("Continue with Google", "in-app browser", "`?join=1`", "Open in browser", "x-safari-https"):
        assert must in doc, f"docs/FREE-MODE.md does not mention {must!r}"
