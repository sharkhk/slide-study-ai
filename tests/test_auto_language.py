"""
Auto language must never be overwritten by a guide's detected language.

Bug (frontend/src/App_dev.jsx, onGenEvent): with the language selector on Auto,
the SSE event that carries the detected language ran `setLang(ev.language)`.
One Arabic guide then switched the whole site UI to Arabic for the rest of the
visit AND sent language="ar" with every later generation, so an English lecture
came out in Arabic.

The fix: in Auto mode nothing a guide says changes `lang`. A guide's own
direction comes from guide.language inside the views that show guide content
(Cards / Quiz / Overview modals; the PDF is built server-side from the guide).
User-supplied text that sits inside the English/Arabic UI chrome (queue item
name, chat messages) takes its direction from its own text (dir="auto").

There is no JS test runner, so these are offline static checks of the source
and of the bundle that is actually served (dist/). No imports of the app.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JSX = os.path.join(ROOT, "frontend", "src", "App_dev.jsx")
DIST = os.path.join(ROOT, "dist")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _src():
    return _read(APP_JSX)


def _component(src, name):
    """Body of a top-level `function <name>(` up to the next top-level function."""
    m = re.search(r"^function %s\(" % re.escape(name), src, re.M)
    assert m, f"{name} not found in App_dev.jsx"
    nxt = re.search(r"^(?:export default )?function \w+\(", src[m.end():], re.M)
    return src[m.start(): m.end() + (nxt.start() if nxt else len(src))]


def _served_js():
    """The JS bundle dist/index.html actually loads."""
    html = _read(os.path.join(DIST, "index.html"))
    refs = re.findall(r'src="/?(assets/index-[\w-]+\.js)"', html)
    assert len(refs) == 1, f"dist/index.html should load exactly one bundle, found {refs}"
    path = os.path.join(DIST, *refs[0].split("/"))
    assert os.path.exists(path), f"dist/index.html loads {refs[0]} but the file is missing"
    return refs[0], _read(path)


# ── 1. no guide → lang feedback in the source ─────────────────────────────────
def test_source_only_sets_lang_from_an_explicit_choice():
    src = _src()
    calls = re.findall(r"\bsetLang\(([^)]*)\)", src)
    # The one and only call site is chooseLang(v): the user's own pick.
    assert calls == ["v"], f"setLang must only be called by chooseLang, found setLang({calls})"
    assert "ev.language" not in src, "the detected guide language must not be read back into the UI"


def test_explicit_choice_still_persists_and_reaches_the_api():
    src = _src()
    assert re.search(r"const chooseLang = v => \{ setLang\(v\); ls\.set\('alimne_lang', v\) \}", src), \
        "chooseLang must still set and persist the explicit choice"
    assert "ls.get('alimne_lang')" in src, "the saved choice must still be restored on load"
    # Auto stays 'auto' on the wire, so the server detects each upload on its own.
    assert re.search(r"const genOpts = \(\) => \(\{ language: lang,", src), \
        "generations must send the selector value (auto/en/ar) unchanged"
    assert "const uiLang = lang === 'auto' ? (NAV_AR ? 'ar' : 'en') : lang" in src, \
        "in Auto the UI language must come from the browser, not from a guide"


# ── 2. the served bundle was rebuilt without the feedback ─────────────────────
_DIST_FEEDBACK = [
    # minified `if (!demo && ev.language && langRef.current === 'auto') setLang(ev.language)`
    re.compile(r'[\w$]+\.language&&[\w$]+\.current==="auto"'),
    re.compile(r'==="auto"&&[\w$]+\([\w$]+\.language\)'),
]


def test_served_bundle_has_no_lang_feedback():
    name, js = _served_js()
    for pat in _DIST_FEEDBACK:
        hit = pat.search(js)
        assert not hit, f"{name} still switches lang from a guide: ...{hit.group(0)}..."


def test_dist_has_no_stale_bundles():
    name, _ = _served_js()
    assets = os.path.join(DIST, "assets")
    js = sorted(f for f in os.listdir(assets) if f.endswith(".js"))
    assert js == [os.path.basename(name)], f"stale bundles left in dist/assets: {js}"


# ── 3. guide content keeps the guide's direction while the UI stays put ───────
def test_study_modals_take_direction_from_the_guide():
    src = _src()
    for comp, expr in (("FlashCardModal", "(g?.language || lang) === 'ar'"),
                       ("QuizModal", "(g?.language || lang) === 'ar'"),
                       ("OverviewModal", "(guide?.language || lang) === 'ar'")):
        body = _component(src, comp)
        assert f"const isAr = {expr}" in body, f"{comp} must follow the guide's language"
        assert "direction:isAr?'rtl':'ltr'" in body, f"{comp} must set its direction from isAr"
    # ...and they are handed the cached guide (with .language) plus the UI language as fallback
    assert re.search(r"guide: it\.guide, loadGuide: \(\) => loadGuide\(it\.id\), lang: uiLang", src)
    # the guide object always carries its language
    assert "language: d?.language || 'en'" in src


def test_queue_item_name_follows_its_own_script():
    src = _src()
    m = re.search(r'<div className="queue-name"[^>]*>\{item\.name\}</div>', src)
    assert m, "queue item name not found"
    assert 'dir="auto"' in m.group(0), "an Arabic file name must render RTL inside the English queue row"


def test_chat_messages_follow_their_own_script():
    body = _component(_src(), "ChatModal")
    assert re.search(r'className="chat-bubble"[^>]*dir="auto"', body), \
        "an Arabic answer must render RTL inside an English chat box"
    # (only once there is text: an empty auto input would knock the placeholder out of the UI's direction)
    assert re.search(r'className="chat-input"\s+dir=(?:"auto"|\{input \? \'auto\' : undefined\})', body), \
        "an Arabic question must type RTL inside an English chat box"
