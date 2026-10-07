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
    "In-app" for the sign-in dialog is GOOGLE_BLOCKED: every browser IN_APP knows, other apps' own
    browsers known by name, and any iPhone / iPad page that is not in a real browser (no "Safari/"
    in its user agent). IN_APP itself, which the downloads decide by, is unchanged. An Android web
    view of an app that is not known by name gets no intent:// address (a plain web view shows its
    own error page for one): the manual way shows at once there.
  * The link handed to the real browser is https://<origin>/?join=1 (plus the invite code, nothing
    else). On load ?join=1 comes off the address and, with nobody signed in, the sign-up modal opens.
    The OAuth return, the recovery / confirmation links and the referral code are left alone.

And every place that says how an account is made says the same: the in-app Terms, /terms, /privacy
(which must stay true to what the server really stores), the operator manual.

There is no JS test runner. These are static checks of the source and of the bundle in dist/, plus
the Flask pages through the test client (offline). The rendered modal (both browsers, both
languages) is checked by frontend/scripts/verify-free-mode.mjs, section 13, which
tests/test_free_mode_client.py runs. What only a browser can show (the dialog opening on ?join=1,
where a click and a key press lead, where the keyboard focus is, which address the page asks for)
is driven in a local headless Chrome by frontend/scripts/verify-login-flows.mjs, offline, against
the bundle in dist/: the last test here runs it, and is skipped on a machine without such a browser.
"""
import os
import re
import shutil
import subprocess

import pytest

import app as appmod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JSX = os.path.join(ROOT, "frontend", "src", "App_dev.jsx")
DIST = os.path.join(ROOT, "dist")
VERIFY = os.path.join(ROOT, "frontend", "scripts", "verify-free-mode.mjs")
FLOWS = os.path.join(ROOT, "frontend", "scripts", "verify-login-flows.mjs")
MANUAL = os.path.join(ROOT, "docs", "FREE-MODE.md")

# The copy this change added or reworded (the same list the node script checks in both languages)
LOGIN_KEYS = ["loginSub", "loginTitleSignup", "loginSubSignup", "emailSignInLink", "emailSignInTitle", "emailSignInSub",
              "backToGoogle", "inAppGoogle", "openInBrowser", "openManual", "orEmailSignup", "orEmailSignin", "wrongPassword",
              "wrongPasswordInApp", "inAppBanner"]


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
    """The modal's bodies: (another app's browser, email sign-in view, the default view, what follows all three).
    The marks are whole lines at the branch's own indent (14 spaces)."""
    def at(mark, start=0):
        m = re.compile("^" + re.escape(mark) + "$", re.M).search(modal, start)
        assert m, f"LoginModal: {mark.strip()!r} not found"
        return m.start()
    a = at("              {GOOGLE_BLOCKED ? (")
    b = at("              ) : emailOnly ? (", a)
    c = at("              ) : (", b)
    d = at("              )}", c)
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
    assert "const emailOnly = !GOOGLE_BLOCKED && byEmail" in modal
    # one way into the email view and one way out, both through showEmail (the only place that sets it)
    assert "  const showEmail = (on) => { switchedAt.current = Date.now(); setByEmail(on); setMsg(null); setNeedConfirm(false) }\n" in modal
    assert modal.count("setByEmail(") == 1, "nothing but showEmail opens or closes the email view"
    assert modal.count("onClick={google}") == 1 and modal.count("showEmail(true)") == 1
    assert "onClick={() => showEmail(true)}" in default and "{t.emailSignInLink}" in default, "the quiet link for the accounts made with an email"
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
    assert "!GOOGLE_BLOCKED ? (isSignup ? t.loginSubSignup : t.loginSub)" in sub and "(isSignup && !freeMode) ? t.loginSubSignup : null" in sub


def test_the_email_view_signs_in_and_can_create_no_account():
    modal = _modal(_src())
    in_app, email_view, default, _ = _views(modal)
    assert "{emailForm}" in email_view and "{t.backToGoogle}" in email_view and "onClick={() => showEmail(false)}" in email_view
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
    assert "  const creating = GOOGLE_BLOCKED && isSignup\n" in modal, "an email account is created inside another app's browser only"
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


def test_the_dialog_is_named_takes_the_focus_and_keeps_the_keyboard_inside():
    """Found by driving the bundle in a browser (verify-login-flows.mjs repeats it): the link that opened the email
    view was unmounted with the focus on it, so the focus fell to <body> and Tab walked the page behind the dialog;
    and "Back to Google sign-in" and "Continue with Google" were the same DOM button (unkeyed siblings), so a
    second Enter on Back started the Google redirect."""
    modal = _modal(_src())
    in_app, email_view, default, _ = _views(modal)
    # no control of one view is ever reused as a control of another
    assert '<Fragment key="in-app">' in in_app and '<Fragment key="email">' in email_view and '<Fragment key="google">' in default
    assert "<>" not in in_app + email_view + default, "the three views are keyed, not bare fragments"
    assert "import { useState, useRef, useCallback, useEffect, useMemo, Fragment } from 'react'" in _src()
    # the focus follows the visitor: into the email field, and back to the link that leads there (not the Google button)
    assert "ref={emailRef} type=\"email\"" in modal and "ref={emailLinkRef} onClick={() => showEmail(true)}" in default
    follow = _block(modal, r"  useEffect\(\(\) => \{\n    if \(!switchedAt\.current\) return", r"\n  \}, \[emailOnly\]\)")
    assert "const to = emailOnly ? emailRef : emailLinkRef" in follow and "to.current?.focus?.()" in follow
    # a second tap or Enter meant for the link just used does not act on what took its place
    assert "  const holdStray = (e) => { if (Date.now() - switchedAt.current < 400) { e.preventDefault(); e.stopPropagation() } }\n" in modal
    assert "onClickCapture={holdStray} onSubmitCapture={holdStray}>\n              {GOOGLE_BLOCKED ? (" in modal, "it guards all three views"
    # the dialog: named by its title, focused when it opens, Tab kept inside
    assert 'role="dialog" aria-modal="true" aria-labelledby="login-title" ref={boxRef}' in modal
    assert '<div id="login-title" tabIndex={-1} ref={titleRef} ' in modal and "onKeyDown={keepTabInside}" in modal
    # the focus goes to the title: not to a button (a stray Enter would start a sign-in), not to the box itself
    assert "  useEffect(() => { titleRef.current?.focus?.() }, [])\n" in modal
    assert "boxRef.current?.focus" not in modal and "autoFocus" not in modal
    assert "useEscapeKey(onClose)" in modal
    trap = _block(modal, r"  const keepTabInside = \(e\) => \{", r"\n  \}\n")
    assert "if (e.key !== 'Tab' || !boxRef.current) return" in trap and "e.preventDefault(); (e.shiftKey ? last : first).focus()" in trap
    assert "if (e.shiftKey ? at === first : at === last)" in trap
    # the quiet link can be read: it was var(--text-muted), 2.8:1 on the dark dialog
    link = default[default.index("ref={emailLinkRef}"):]
    assert "color:'var(--text-secondary)'" in link and "var(--text-muted)" not in link and "padding:'0.5rem 0.25rem'" in link
    # a wrong password inside another app's browser does not point at a Google button that is not there
    assert ("  const errText = (err) => { const text = authErrText(t, err); "
            "return GOOGLE_BLOCKED && text === t.wrongPassword ? t.wrongPasswordInApp : text }\n") in modal
    assert "catch (err) { setMsg({ type: 'error', text: errText(err) }) }" in _block(modal, r"  const guarded = async \(fn\) => \{", r"\n  \}\n")


# ── 2. an in-app browser: the notice, the way out, the email form ─────────────
def test_in_app_detection_is_unchanged():
    assert ("const IN_APP = (() => { try { return /Instagram|FBAN|FBAV|FB_IAB|TikTok|musical_ly|Snapchat|Line\\/|; wv\\)/i"
            ".test(navigator.userAgent || '') } catch { return false } })()") in _src()


def test_the_sign_in_dialog_decides_by_where_google_is_blocked_not_by_the_named_apps_alone():
    """IN_APP knows iPhone apps by name only. The dialog used it alone to choose between the Google button and the
    in-app view, so a link opened inside LinkedIn, X, WeChat or any other iPhone app's own web view got a Google
    button that Google refuses (403 disallowed_useragent) and no way to make an account at all. Before Google-only
    sign-up that visitor still had the email form."""
    src = _src()
    modal = _modal(src)
    blocked = _block(src, r"^function googleBlockedIn\(ua, standalone = false\) \{", r"^\}\n")
    assert "if (EMBEDDED_RE.test(s)) return true" in blocked
    assert "return /iPhone|iPad|iPod/i.test(s) && !/Safari\\//i.test(s) && !standalone" in blocked, \
        "an iPhone / iPad page with no Safari/ in its user agent is an app's own web view (a Home Screen page is not)"
    named = re.search(r"^const EMBEDDED_RE = /(.+)/i$", src, re.M)
    assert named, "EMBEDDED_RE not found"
    # everything IN_APP knows, and the apps it does not
    for token in ("Instagram", "FBAN", "FBAV", "FB_IAB", "TikTok", "musical_ly", "Snapchat", "Line\\/", "; wv\\)",
                  "LinkedInApp", "Twitter", "MicroMessenger", "Barcelona", "BytedanceWebview", "trill_", "KAKAOTALK", "Pinterest"):
        assert token in named.group(1).split("|"), f"EMBEDDED_RE lost {token}"
    # a superset of IN_APP by construction, read once at load
    assert ("const GOOGLE_BLOCKED = IN_APP || (() => { try { return googleBlockedIn(navigator.userAgent, navigator.standalone === true) } "
            "catch { return false } })()") in src
    # the dialog decides by it everywhere, and by IN_APP nowhere
    assert not re.search(r"\bIN_APP\b", modal), "LoginModal still decides something by IN_APP"
    for must in ("  const creating = GOOGLE_BLOCKED && isSignup\n", "  const emailOnly = !GOOGLE_BLOCKED && byEmail\n",
                 "    if (!GOOGLE_BLOCKED) return\n", "              {GOOGLE_BLOCKED ? (\n"):
        assert must in modal, f"LoginModal lost {must.strip()!r}"
    # ...and the downloads decide by IN_APP as before: nothing outside the dialog reads the wider test
    after = src[src.index("function SetPasswordModal("):]
    assert "GOOGLE_BLOCKED" not in after
    for must in ("if (IN_APP && typeof navigator.canShare === 'function') prefetchPdf(id, jobId)", "if (IN_APP && cur.pdfBlob) {",
                 "if (IN_APP) { inAppDownload(`/api/export/anki/${jobId}`); return }", "            {IN_APP && (\n"):
        assert must in after, f"the download paths changed: {must.strip()}"


def test_the_in_app_view_keeps_email_sign_up_and_offers_open_in_browser():
    modal = _modal(_src())
    in_app, email_view, default, _ = _views(modal)
    for must in ("{t.inAppGoogle}", 'className="submit-btn" onClick={openInBrowser}', "{t.openInBrowser}",
                 "{stayed ? t.openManual : ''}", "onClick={copyLink}", "t.copyLink", "{emailForm}", "isSignup ? t.orEmailSignup : t.orEmailSignin",
                 "{isSignup ? t.haveAccount : t.noAccount}"):
        assert must in in_app, f"the in-app view lost {must}"
    # the way by hand is said by a live region that is there from the start: one that arrives together with its
    # text is not reliably announced by a screen reader
    assert ("<div role=\"status\" style={stayed ? {marginTop:'0.6rem', fontWeight:600, color:'var(--text-primary)'} : undefined}>"
            "{stayed ? t.openManual : ''}</div>") in in_app
    assert "{stayed && (" not in in_app
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
    # a page that another app's browser opened with ?join=1 is a hand-off that came back into the same app:
    # the way by hand is on screen from the start there, instead of the same button alone
    assert re.search(r"const \[stayed, setStayed\]\s*= useState\(GOOGLE_BLOCKED && JOIN_IN_URL\)", modal)
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
    assert "if (/Android/i.test(ua || '')) return HANDOFF_APPS_RE.test(ua) ? `intent://${m[1]}#Intent;scheme=https;end` : ''" in hand, \
        "Android: an intent with scheme=https (the default browser), inside the named apps only"
    # an Android web view of an unknown app gets NO address: a plain web view loads intent: as a page, which is its
    # own error page in place of Alimne. The generic '; wv)' mark is therefore not in the list.
    apps = re.search(r"^const HANDOFF_APPS_RE = /(.+)/i$", src, re.M)
    assert apps and "wv" not in apps.group(1), "the list of apps that are handed an intent:// address"
    assert set(apps.group(1).split("|")) == {"Instagram", "FBAN", "FBAV", "FB_IAB", "TikTok", "musical_ly", "trill_", "BytedanceWebview", "Snapchat", "Line\\/"}
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
    assert "if (!JOIN_IN_URL) return" in block
    # the decision is one pure function (verify-free-mode.mjs runs it; verify-login-flows.mjs watches it happen)
    assert ("const open = joinAnswer({ join: JOIN_IN_URL, authLoading, asked: joinAsked.current, session, authEnabled, "
            "urlErr: AUTH_URL_ERR, recovery: RECOVERY_IN_URL })") in block
    assert block.index("if (open === null) return") < block.index("joinAsked.current = true") < block.index("if (open) openLogin('signup')"), \
        "nothing to answer yet -> wait; then answered once per page load; then open or not"
    assert block.count("openLogin(") == 1
    assert "}, [authLoading])" in block, "it waits for the session restore to answer"
    answer = _block(src, r"^function joinAnswer\(\{ join, authLoading, asked, session, authEnabled, urlErr, recovery \}\) \{", r"^\}\n")
    assert "if (!join || authLoading || asked) return null" in answer
    assert "return !session && !!authEnabled && !urlErr && !recovery" in answer, \
        "only with nobody signed in, and never over a link that came back with an error or for a password reset"
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


def test_only_an_expired_email_link_opens_the_email_view_a_failed_google_return_keeps_the_google_button():
    """The error a sign-in comes back with was called "an expired link" whenever its description said "invalid" or
    "expired". Supabase answers a Google sign-in whose state went stale (a visitor who took a few minutes at
    Google) with error_code=bad_oauth_state, "OAuth callback with invalid state": that opened the email-only view,
    with "that link has expired... try signing in with your password", for someone who has no password and whose
    only way to an account is the Google button that view does not have."""
    src = _src()
    err = _block(src, r"^  // ── OAuth / email-link errors", r'^  // ── Arrived from "Open in browser"')
    assert "const { key, byEmail } = authUrlNotice(e)" in err
    assert "openLogin('signin', { type: 'error', text: t[key], byEmail })" in err
    assert "const expired" not in err and "t.linkExpired" not in err, "no second opinion on what the error was"
    notice = _block(src, r"^function authUrlNotice\(e\) \{", r"^\}\n")
    assert "const emailLink = e?.code === 'otp_expired' || /email link/i.test(e?.desc || '')" in notice
    assert "return { key: emailLink ? 'linkExpired' : 'authLinkError', byEmail: emailLink }" in notice
    assert "/expired|invalid/i" not in src, "the test that took any 'invalid' for an email link"
    # both texts exist, in both languages
    for lang in ("en", "ar"):
        for key in ("linkExpired", "authLinkError"):
            _line(_pack(src, lang), key)


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
    # the notice names no app that was not detected (and no browser the phone may not have); nor does the
    # downloads banner on the same page, nor the wrong-password line of the in-app view
    for pack in (en, ar):
        for key in ("inAppGoogle", "openManual", "inAppBanner", "wrongPasswordInApp"):
            assert not re.search(r"Instagram|Facebook|TikTok|Snapchat|Safari|Chrome", _line(pack, key)), key
    assert "inside this app" in _line(en, "inAppBanner") and "داخل هذا التطبيق" in _line(ar, "inAppBanner")
    assert "open Alimne in your browser and sign in with Google." in _line(en, "wrongPasswordInApp")
    assert "فافتح علّمني في متصفحك وسجّل الدخول عبر Google." in _line(ar, "wrongPasswordInApp")
    assert "not allowed inside this app" in _line(en, "inAppGoogle") and "غير مسموح به داخل هذا التطبيق" in _line(ar, "inAppGoogle")
    assert _line(en, "orEmailSignup") == "    orEmailSignup: 'or sign up with email here',"


def test_the_copy_of_the_old_email_first_modal_is_gone():
    src = _src()
    for dead in ("orDivider", "Free, no card needed — create your account in a minute.", "مجاني وبدون بطاقة — أنشئ حسابك خلال دقيقة.",
                 "or use email below", "أو استخدم البريد الإلكتروني بالأسفل", "Use Continue with Google.", "'Create your account'",
                 "'Sign in to your account'", "doesn't work inside this app", "inside Instagram/TikTok", "داخل Instagram/TikTok"):
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
    # section 7 ("This service relies on") names Google, as /privacy does: it is the way an account is made.
    # It is in the part both modes share, where it is equally true (the sign-in dialog is the same one).
    en_tail, ar_tail = _block(src, r"^const TERMS_EN_TAIL = `", r"`"), _block(src, r"^const TERMS_AR_TAIL = `", r"`")
    en_line = "• Google: for sign-in with your Google account (subject to Google's terms at policies.google.com)."
    ar_line = "• Google: لتسجيل الدخول بحسابك في Google (خاضع لشروط Google على policies.google.com)."
    assert en_line in en_tail[en_tail.index("7. THIRD-PARTY SERVICES"):en_tail.index("8. LIMITATION OF LIABILITY")]
    assert ar_line in ar_tail[ar_tail.index("٧. الخدمات الخارجية"):ar_tail.index("٨. تحديد المسؤولية")]


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
                   "Accounts are created with Google", "We never see your Google password",
                   # after review: the wider test for an embedded browser, the named dialog, the reworded lines
                   "LinkedInApp", "MicroMessenger", "login-title", "open Alimne in your browser and sign in with Google.",
                   "Downloads may not work inside this app.", "Google: for sign-in with your Google account"):
        assert marker in js, f"{name} is missing {marker!r} - rebuild: cd frontend && npm run build"
    for stale in ("create your account in a minute", "or use email below", "Use Continue with Google.", "doesn't work inside this app",
                  "inside Instagram/TikTok"):
        assert stale not in js, f"{name} still ships the old sign-up copy {stale!r} - rebuild: cd frontend && npm run build"
    assert js.count(".auth.signUp(") == 1, "one sign-up call in the bundle"


def test_the_node_script_checks_the_rendered_modal_in_both_browsers():
    script = _read(VERIFY)
    for must in ("13. Google-only sign-up: the modal in a normal browser", "13b. Google-only sign-up: the way out of an in-app browser",
                 "13c. Google-only sign-up: the Terms say how an account is made", "'?in-app'", "MI.IN_APP === true",
                 "13d. Google-only sign-up: where Google is blocked", "'?ios-webview'", "MW.IN_APP === false && MW.GOOGLE_BLOCKED === true",
                 "'?in-app-join'", "bad_oauth_state", "M.joinAnswer", "M.authUrlNotice", "M.googleBlockedIn"):
        assert must in script, f"verify-free-mode.mjs lost its check: {must}"
    keys = re.search(r"const LOGIN_KEYS = \[(.*?)\]", script, re.S).group(1)
    assert sorted(re.findall(r"'(\w+)'", keys)) == sorted(LOGIN_KEYS), "the node script and this file check the same copy"


def test_the_manual_describes_google_only_sign_up():
    doc = _read(MANUAL)
    for must in ("Continue with Google", "in-app browser", "`?join=1`", "Open in browser", "x-safari-https"):
        assert must in doc, f"docs/FREE-MODE.md does not mention {must!r}"


def test_the_manual_does_not_overstate_what_the_client_side_rule_holds():
    """The rule "email sign-up only inside an in-app browser" lives in the shipped client alone: Supabase's email
    sign-up stays open (the fallback needs it), and its address and public key are in the bundle. The manual said an
    email account "can only be created" in-app and that email confirmation "only matters" for those accounts, which
    invites turning confirmation off: the one check on scripted email accounts (40 guides a day each)."""
    doc = re.sub(r"\s+", " ", _read(MANUAL))
    for gone in ("It only matters for accounts made inside in-app browsers now", "An email account can only be created inside an in-app browser",
                 "Email sign-ups now come from in-app browsers only",
                 # ...and the sentence about a case the client no longer produces
                 "An email confirmation link opens a new tab: the file stays in the first tab, which becomes signed in too"):
        assert gone not in doc, f"docs/FREE-MODE.md still says: {gone!r}"
    for must in ("enforced by the shipped client only", "Keep email confirmation ON", "`GOOGLE_BLOCKED`", "`bad_oauth_state`",
                 "verify-login-flows.mjs", "presents itself as a normal browser"):
        assert must in doc, f"docs/FREE-MODE.md does not mention {must!r}"
    # true because the sign-up endpoint is reachable from anywhere with what the bundle ships
    src = _src()
    assert "const SB_URL  = 'https://" in src and "const SB_ANON = '" in src
    assert re.search(r'^FAIR_USER_DAILY\s*=\s*_env_num\("FAIR_USER_DAILY", 40\)', _read(os.path.join(ROOT, "app.py")), re.M), "40 guides a day per account"


# ── 8. the dialog in a real browser ───────────────────────────────────────────
_HAVE_NODE = shutil.which("node")


@pytest.mark.skipif(not _HAVE_NODE, reason="node not available")
def test_the_login_flows_in_a_real_browser():
    """Drives the bundle in dist/ in a local headless Chrome / Edge, offline (the script answers every request
    itself): ?join=1 on arrival, a failed Google return, the keyboard focus, a double tap, which Supabase call a
    normal browser and an in-app one can make, and "Open in browser". Skipped where no such browser is installed."""
    r = subprocess.run(["node", FLOWS], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=420)
    if r.returncode == 77:
        pytest.skip((r.stdout.strip().splitlines() or ["no browser"])[-1])
    assert r.returncode == 0, "verify-login-flows.mjs failed:\n" + "\n".join(
        [l for l in r.stdout.splitlines() if "FAIL" in l or "passed" in l][-40:]) + "\n" + r.stderr[-2000:]
    assert re.search(r"^\d+ passed, 0 failed$", r.stdout.strip().splitlines()[-1])
