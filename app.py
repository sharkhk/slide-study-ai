import io
import copy
import re
import sys
import uuid
import json
import os
import time
import hmac
import hashlib
import secrets
import threading
import traceback as _tb
import logging
import ipaddress as _ipaddress
import requests as http
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import OrderedDict
from urllib.parse import urlparse as _urlparse

# ── Logger ─────────────────────────────────────────────────────────────────────
# Stream to stdout so the hosting platform (Render) captures app errors/warnings
# in its live log feed. Also keep a best-effort file log for local debugging.
_LOG_FILE = os.path.join(os.path.dirname(__file__), "debug.log")
_log_handlers = [logging.StreamHandler(sys.stdout)]
try:
    _log_handlers.append(logging.FileHandler(_LOG_FILE))
except Exception:
    pass  # read-only FS — stdout handler is enough
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=_log_handlers,
)
_log = logging.getLogger("app")
from flask import Flask, request, jsonify, send_file, send_from_directory, Response, stream_with_context, redirect, has_request_context
from flask import g as _req_g   # per-request scratch (auth reason/payload); aliased so local `g` vars can't shadow it
from flask_cors import CORS
# Import jwt (and supabase, which imports jwt) HERE, in the main thread, before any
# background thread or request thread can race the import. On Python 3.14 a lazy
# `import jwt` racing between threads left the module half-initialised for the life
# of the process: every token check crashed/hung and Supabase never connected
# (production incident 2026-10-01, rolled back in ffc0b3d).
import jwt as _pyjwt
try:
    from supabase import create_client as _sb_create_client
except Exception:      # dev without supabase installed
    _sb_create_client = None
try:
    from supabase import ClientOptions as _SbClientOptions
except Exception:      # older supabase-py without ClientOptions
    _SbClientOptions = None
from pptx import Presentation
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics as _pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont as _TTFont

DIST         = os.path.join(os.path.dirname(__file__), "dist")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
# Primary model — gpt-oss-120b is far more faithful to the source (fewer
# hallucinations / changed names) and stronger in Arabic than the 20b. Needs the
# Groq Developer tier for its rate limits (which this account has).
GROQ_MODEL   = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
# Fallbacks tried automatically if the primary model is unavailable to the key.
GROQ_FALLBACK_MODELS = [
    m.strip() for m in os.environ.get(
        "GROQ_FALLBACK_MODELS", "openai/gpt-oss-20b,llama-3.3-70b-versatile"
    ).split(",") if m.strip()
]
OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral")

# ── Supabase / Auth ────────────────────────────────────────────────────────────
SUPABASE_URL              = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY         = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_JWT_SECRET       = os.environ.get("SUPABASE_JWT_SECRET", "")

# ── Stripe ─────────────────────────────────────────────────────────────────────
STRIPE_SECRET_KEY    = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID      = os.environ.get("STRIPE_PRICE_ID", "")
# Monthly Pro price in USD — used only to estimate MRR on the admin dashboard.
# Override with the PRO_MONTHLY_USD env var if the price changes.
try:
    PRO_MONTHLY_USD = float(os.environ.get("PRO_MONTHLY_USD", "2.99"))
except (TypeError, ValueError):
    PRO_MONTHLY_USD = 2.99
APP_URL              = os.environ.get("APP_URL", "https://alimne.app")
# Shared secret Cloudflare injects (via a Transform Rule adding header
# X-Origin-Verify) so the origin can tell real Cloudflare traffic from requests
# sent straight to the Render origin. When set, CF-Connecting-IP is only trusted
# on verified requests. Leave unset to keep the old (trust-CF) behaviour.
CF_ORIGIN_SECRET     = os.environ.get("CF_ORIGIN_SECRET", "")

_AUTH_ENABLED = bool(SUPABASE_URL)  # verify via JWKS (asymmetric) or HS256 shared secret

# FAIL CLOSED: with auth disabled every caller becomes a "dev" user with 999
# tokens and an active subscription. That is fine for local dev, but if it ever
# happened in production (SUPABASE_URL unset on a deploy) the whole app — paid
# features included — would be wide open. On Render, refuse to start instead.
_IS_PRODUCTION = bool(os.environ.get("RENDER") or os.environ.get("PRODUCTION"))
if _IS_PRODUCTION and not _AUTH_ENABLED:
    raise RuntimeError(
        "SUPABASE_URL is not set but this is a production environment — refusing "
        "to start in open (no-auth) dev mode. Set SUPABASE_URL and the Supabase keys."
    )

DETAIL = {
    "brief":    {"slide_chars": 400,  "max_slides": 30,  "keywords": "8-10",  "bullets": "2-4",  "n_flash": 6,  "n_mcq": 5,  "num_predict": 1200},
    "standard": {"slide_chars": 700,  "max_slides": 60,  "keywords": "18-25", "bullets": "3-8",  "n_flash": 14, "n_mcq": 10, "num_predict": 2200},
    "detailed": {"slide_chars": 1200, "max_slides": 120, "keywords": "25-35", "bullets": "5-12", "n_flash": 20, "n_mcq": 15, "num_predict": 3200},
}

# ── Arabic PDF support ─────────────────────────────────────────────────────────
# The font ships in the repo (fonts/, SIL OFL 1.1 - see fonts/OFL.txt). It used to
# be downloaded from GitHub on the first Arabic build: any network hiccup, rate
# limit or cold /tmp silently turned the whole Arabic PDF into Helvetica boxes.
_ARABIC_FONT         = "NotoNaskhArabic"
_ARABIC_FONT_BUNDLED = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "fonts", "NotoNaskhArabic-Regular.ttf")
_ARABIC_FONT_PATH    = "/tmp/NotoNaskhArabic.ttf"   # last-resort download cache only
_ARABIC_FONT_URL     = ("https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/"
                        "NotoNaskhArabic/NotoNaskhArabic-Regular.ttf")
_ARABIC_FONT_RETRY_S = 300      # after a failed download, don't try again for 5 min
_arabic_font_ok          = False
_arabic_font_fail_at     = None # time.monotonic() of the last failed download
_arabic_font_downloading = False
_arabic_font_lock        = threading.Lock()   # guards the state above; never held over I/O

def _register_arabic_font_file(path):
    """Register `path` as the Arabic font. Caller holds _arabic_font_lock."""
    global _arabic_font_ok
    _pdfmetrics.registerFont(_TTFont(_ARABIC_FONT, path))
    _arabic_font_ok = True

def _ensure_arabic_font():
    """Register the Arabic PDF font on first use (never at import). True when usable.

    1. the copy bundled in fonts/ (no network - the normal path),
    2. a copy a previous last-resort download left in /tmp,
    3. a last-resort GitHub download: short timeout, OUTSIDE the lock, and a
       failure is remembered for 5 minutes so concurrent builds never queue behind
       it (they render with Helvetica instead of waiting)."""
    global _arabic_font_fail_at, _arabic_font_downloading
    if _arabic_font_ok:
        return True
    with _arabic_font_lock:
        if _arabic_font_ok:
            return True
        for path in (_ARABIC_FONT_BUNDLED, _ARABIC_FONT_PATH):
            if os.path.isfile(path):
                try:
                    _register_arabic_font_file(path)
                    return True
                except Exception as exc:
                    _log.error("Arabic font %s unusable: %s", path, exc)
        if _arabic_font_downloading:
            return False
        if _arabic_font_fail_at is not None and time.monotonic() - _arabic_font_fail_at < _ARABIC_FONT_RETRY_S:
            return False
        _arabic_font_downloading = True
    _log.warning("Arabic font not bundled - downloading it as a last resort")
    tmp_path = None
    try:
        r = http.get(_ARABIC_FONT_URL, timeout=8, allow_redirects=True)
        r.raise_for_status()
        tmp_path = f"{_ARABIC_FONT_PATH}.{uuid.uuid4().hex}.part"
        with open(tmp_path, "wb") as fh:
            fh.write(r.content)
        _TTFont(_ARABIC_FONT, tmp_path)          # parse it before anyone can use it
        os.replace(tmp_path, _ARABIC_FONT_PATH)
        tmp_path = None
        with _arabic_font_lock:
            _register_arabic_font_file(_ARABIC_FONT_PATH)
            _arabic_font_downloading = False
        return True
    except Exception as exc:
        _log.error("Arabic font download failed (retry in %ss): %s", _ARABIC_FONT_RETRY_S, exc)
        with _arabic_font_lock:
            _arabic_font_fail_at = time.monotonic()
            _arabic_font_downloading = False
        return False
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

def _ar_shape(text):
    """Arabic PDF text, step 1: join the letters (arabic_reshaper), still in LOGICAL
    order. Wrap this text, then reorder its lines with _ar_display_lines()
    (_ArabicParagraph)."""
    if not text:
        return text
    try:
        import arabic_reshaper
    except ImportError:
        return str(text)
    s = str(text)
    # A hyphen directly between two Arabic letters gets swallowed by the
    # reshaper and merges the words (e.g. النمسا-المجر → النمساالمجر). Pad it
    # with spaces so the two words stay separate, and draw it as U+2010 HYPHEN:
    # the bundled Noto Naskh Arabic has no glyph for U+002D (it printed a box).
    # Hyphens next to digits or Latin letters are left alone (2-3 stays a range).
    s = re.sub(r'(?<=[؀-ۿ])\s*-\s*(?=[؀-ۿ])', ' \N{HYPHEN} ', s)
    return arabic_reshaper.reshape(s)

def _ar_display(shaped, base_dir=None):
    """Arabic PDF text, step 2: bidi-reorder ONE line of _ar_shape() text into
    drawing (left-to-right) order. base_dir 'R'/'L' fixes the paragraph direction;
    None takes it from the line's first strong letter."""
    if not shaped:
        return shaped
    return _ar_display_lines([shaped], base_dir)[0]

def _ar_display_lines(lines, base_dir=None):
    """_ar_display() for the lines of ONE wrapped paragraph. UAX#9 resolves the
    levels over the whole paragraph and only reorders line by line (L1-L4), so
    each line still sees its neighbours: a "(" that ends one line stays paired
    with the ")" that starts the next. The lines are rejoined with the space the
    wrap broke them at.

    python-bidi's pure-Python algorithm, run step by step so bracket pairs can be
    resolved (_ar_bidi_n0) and the lines cut out before reordering."""
    try:
        from bidi.algorithm import (
            PARAGRAPH_LEVELS, get_empty_storage, get_base_level, get_embedding_levels,
            explicit_embed_and_overrides, resolve_weak_types, resolve_neutral_types,
            resolve_implicit_levels, reorder_resolved_levels, apply_mirroring)
    except ImportError:
        return list(lines)
    text = " ".join(lines)
    st = get_empty_storage()
    st["base_level"] = PARAGRAPH_LEVELS[base_dir] if base_dir else get_base_level(text)
    st["base_dir"] = "LR"[st["base_level"]]
    get_embedding_levels(text, st)
    for i, ch in enumerate(st["chars"]):
        ch["idx"] = i                  # X9 drops formatting characters: keep positions
    explicit_embed_and_overrides(st)
    resolve_weak_types(st)
    _ar_bidi_n0(st)
    resolve_neutral_types(st, False)
    resolve_implicit_levels(st, False)
    out, pos = [], 0
    for ln in lines:
        line = dict(st, chars=[c for c in st["chars"] if pos <= c["idx"] < pos + len(ln)])
        reorder_resolved_levels(line, False)
        apply_mirroring(line, False)
        out.append("".join(c["ch"] for c in line["chars"]))
        pos += len(ln) + 1
    return out

_AR_BRACKETS = None

def _ar_brackets():
    """{bracket: (is_opening, pair id)}, Unicode's Bidi_Paired_Bracket derived the
    way BidiBrackets.txt is: a Ps and a Pe character, both bidi class ON, that are
    each other's mirror glyph. The id is the opening bracket's NFC form, so the
    canonically equivalent U+2329/U+3008 angle brackets pair with each other."""
    global _AR_BRACKETS
    if _AR_BRACKETS is None:
        from bidi.mirror import MIRRORED
        table = {}
        for o, c in MIRRORED.items():
            if (_ud.category(o) == "Ps" and _ud.category(c) == "Pe" and MIRRORED.get(c) == o
                    and _ud.bidirectional(o) == _ud.bidirectional(c) == "ON"):
                pid = _ud.normalize("NFC", o)
                table[o], table[c] = (True, pid), (False, pid)
        _AR_BRACKETS = table
    return _AR_BRACKETS

def _ar_bidi_n0(storage):
    """UAX#9 BD16 + N0, which python-bidi's pure-Python algorithm predates: both
    brackets of a pair take one direction, from the text they enclose (or, when
    that is all of the other direction, from the text before them). Resolved one
    by one from their neighbours, "ATP (adenosine triphosphate)" in Arabic text
    got an LTR "(" and an RTL ")" that was mirrored and moved to the other end:
    "(ATP (adenosine triphosphate". Runs between W7 and N1 on each level run
    (there are no isolates, so those are the isolating run sequences)."""
    brackets = _ar_brackets()
    chars = storage["chars"]

    def strong(t):                     # N0 counts EN and AN as R
        return "L" if t == "L" else "R" if t in ("R", "EN", "AN") else None

    for run in storage["runs"]:
        start, end = run["start"], run["start"] + run["length"]
        # BD16: each closing bracket closes the nearest open bracket of its kind.
        stack, pairs = [], []
        for i in range(start, end):
            b = brackets.get(chars[i]["ch"]) if chars[i]["type"] == "ON" else None
            if b is None:
                continue
            if b[0]:
                if len(stack) == 63:
                    break
                stack.append((b[1], i))
                continue
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][0] == b[1]:
                    pairs.append((stack[k][1], i))
                    del stack[k:]
                    break
        e = "LR"[chars[start]["level"] % 2]          # embedding direction
        for o, c in sorted(pairs):
            inside = {strong(chars[i]["type"]) for i in range(o + 1, c)} - {None}
            if not inside:
                continue               # N0 d: nothing strong inside, N1/N2 decide
            if e in inside:
                d = e                  # N0 b
            else:                      # N0 c: the other direction, if the text before is too
                d = run["sor"]
                for i in range(o - 1, start - 1, -1):
                    if strong(chars[i]["type"]):
                        d = strong(chars[i]["type"])
                        break
            for i in (o, c):
                chars[i]["type"] = d
                j = i + 1              # marks on a bracket follow it (W1 gave them ON)
                while j < end and chars[j]["orig"] == "NSM":
                    chars[j]["type"] = d
                    j += 1

def _ar(text):
    """Reshape + bidi-flip a ONE-LINE Arabic string for reportlab (which is LTR-only).
    Text that may wrap must go through _ArabicParagraph instead: reordering the
    whole string before wrapping lays its lines out in reverse order."""
    return _ar_display(_ar_shape(text))

# ── Supabase client (lazy, uses service-role key → bypasses RLS) ───────────────
_sb_client = None
_sb_lock   = threading.Lock()

def _get_sb():
    global _sb_client
    if _sb_client:
        return _sb_client
    with _sb_lock:
        if _sb_client:
            return _sb_client
        if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY and _sb_create_client:
            try:
                # postgrest's default timeout is 120s — a slow Supabase would pin a
                # gunicorn thread (and /api/auth/me) for minutes. Cap it at 10s.
                try:
                    _opts = _SbClientOptions(postgrest_client_timeout=10) if _SbClientOptions else None
                except Exception:
                    _opts = None
                client = None
                if _opts is not None:
                    try:
                        client = _sb_create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, options=_opts)
                    except Exception as e:
                        # A supabase-py release that rejects these options must not leave
                        # _sb_client None (that fails OPEN: free, unlimited generations).
                        _log.error("Supabase init with options failed, retrying without: %s", e)
                if client is None:
                    client = _sb_create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
                _sb_client = client
            except Exception as e:
                print(f"Supabase init error: {e}", flush=True)
    return _sb_client

# Build the client now, in the main thread, so any lazy submodule imports inside
# supabase-py happen here and not in racing request/pool threads. No network I/O.
if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
    _get_sb()

# ── Stripe setup ───────────────────────────────────────────────────────────────
if STRIPE_SECRET_KEY:
    try:
        import stripe as _stripe
        _stripe.api_key = STRIPE_SECRET_KEY
    except ImportError:
        _stripe = None
else:
    _stripe = None

# ── JWT helpers ────────────────────────────────────────────────────────────────
def _get_bearer(req):
    auth = req.headers.get("Authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else None

_jwks_client     = None
_jwks_lock       = threading.Lock()
_jwks_last_good  = {}   # kid -> key; used ONLY while the JWKS endpoint is unreachable
_JWT_LEEWAY      = 10   # seconds of clock skew tolerated on iat/exp

def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None and SUPABASE_URL:
        with _jwks_lock:
            if _jwks_client is None:
                # 10-min JWK-set cache, 5s fetch timeout (default 30s blocks a thread).
                # cache_keys stays False so a revoked kid is never trusted forever.
                _jwks_client = _pyjwt.PyJWKClient(
                    SUPABASE_URL.rstrip("/") + "/auth/v1/.well-known/jwks.json",
                    lifespan=600, timeout=5)
    return _jwks_client

if SUPABASE_URL:
    # No import-time JWKS warm-up thread (see the import note at the top): the
    # first sign-in fetches the key set (5s timeout) and seeds _jwks_last_good.
    _log.info("JWT: JWKS verification on; HS256 fallback %s",
              "configured" if SUPABASE_JWT_SECRET else "NOT configured")

def _jwt_verify(token):
    """Verify a Supabase-issued JWT → (payload, reason). reason is "" on success,
    else "missing" | "expired" | "invalid" | "unavailable" (JWKS unreachable and no
    cached key — a server problem, not a sign-out). Asymmetric (ES/RS/PS/Ed)
    tokens verify against the project JWKS; HS256 against the shared secret."""
    if not token:
        return None, "missing"
    try:
        hdr = _pyjwt.get_unverified_header(token)
        alg = hdr.get("alg", "")
        if alg.startswith(("ES", "RS", "PS", "Ed")):
            client = _get_jwks_client()
            if client is None:
                return None, "invalid"
            kid = hdr.get("kid")
            try:
                key = client.get_signing_key_from_jwt(token).key
                if kid:
                    _jwks_last_good[kid] = key
            except _pyjwt.PyJWKClientConnectionError:
                key = _jwks_last_good.get(kid)
                if key is None:
                    raise
                _log.warning("JWKS unreachable — verifying with last-good key %s", kid)
            payload = _pyjwt.decode(token, key, algorithms=[alg], audience="authenticated",
                                    leeway=_JWT_LEEWAY)
        elif SUPABASE_JWT_SECRET:
            payload = _pyjwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"],
                                    audience="authenticated", leeway=_JWT_LEEWAY)
        else:
            if alg.startswith("HS"):
                _log.error("JWT alg %s but SUPABASE_JWT_SECRET unset — rejecting", alg)
            return None, "invalid"
        if not isinstance(payload, dict) or not payload.get("sub"):
            return None, "invalid"
        return payload, ""
    except (_pyjwt.ExpiredSignatureError, _pyjwt.ImmatureSignatureError) as e:
        reason, ename = "expired", type(e).__name__
    except _pyjwt.PyJWKClientConnectionError as e:
        reason, ename = "unavailable", type(e).__name__
    except Exception as e:
        reason, ename = "invalid", type(e).__name__
    _log.warning("JWT verify failed: %s on %s", ename,
                 request.path if has_request_context() else "-")
    return None, reason

def _jwt_payload(token):
    """Verified payload dict or None (see _jwt_verify for the failure reason)."""
    return _jwt_verify(token)[0]

def _verify_jwt(token):
    """Return the verified user_id (str) or None."""
    payload = _jwt_payload(token)
    return payload.get("sub") if payload else None

def _identity_from_jwt(token):
    """Pull email / display name / avatar from a Google (or other) OAuth JWT."""
    return _identity_from_payload(_jwt_payload(token))

def _identity_from_payload(p):
    """Supabase puts these under user_metadata (full_name/name, avatar_url/picture)."""
    p = p or {}
    meta = p.get("user_metadata") or {}
    return {
        "email":  p.get("email") or meta.get("email") or "",
        "name":   meta.get("full_name") or meta.get("name") or "",
        "avatar": meta.get("avatar_url") or meta.get("picture") or "",
    }

# ── Token helpers ──────────────────────────────────────────────────────────────
def _consume_token(user_id):
    """
    Atomically consume one token via Supabase RPC.
    Returns (ok: bool, tokens_remaining: int, reason: str)
    """
    sb = _get_sb()
    if not sb:
        return True, 999, ""   # Supabase not configured → dev mode, always allow
    try:
        r = sb.rpc("consume_token", {"p_user_id": user_id}).execute()
        d = r.data if isinstance(r.data, dict) else {}
        if "success" not in d:
            _log.error("consume_token: unexpected RPC response %r", r.data)
            return False, 0, "db_error"   # never report a malformed reply as 'no tokens'
        ok = d.get("success", False)
        return ok, d.get("tokens_remaining", 0), d.get("reason", "")
    except Exception as exc:
        print(f"consume_token error: {exc}", flush=True)
        return False, 0, "db_error"

# Flips to False once PostgREST says the add_tokens RPC isn't installed (see
# migrations/001) — and ONLY then; a timeout or 5xx never flips it.
_add_tokens_rpc = True

# PostgREST's answers for "this RPC does not exist": PGRST202 ("Could not find the
# function … in the schema cache"; older PostgREST: "Could not find the
# public.fn(…) function …"), a bare HTTP 404 (postgrest-py puts the status in
# .code when the body isn't JSON) and Postgres 42883 "function … does not exist".
_RPC_MISSING_CODES = {"PGRST202", "42883", "404"}
_RPC_MISSING_RE    = re.compile(r"could not find the\b.*\bfunction\b|\bfunction\b.*\bdoes not exist\b",
                                re.I | re.S)

def _rpc_missing(exc):
    """True only when the error PROVES the RPC is not installed (so the call
    changed nothing). Timeouts, connection resets and 5xx are ambiguous: the RPC
    may have run and only the reply was lost → False."""
    code = getattr(exc, "code", None)
    if code is not None and str(code).strip().upper() in _RPC_MISSING_CODES:
        return True
    msg = getattr(exc, "message", None)
    if not isinstance(msg, str) or not msg:
        msg = str(exc)
    return bool(_RPC_MISSING_RE.search(msg))

def _add_tokens(sb, user_id, delta):
    """Atomically add (or subtract) `delta` tokens and return the new balance,
    or None when it failed or its outcome is unknown.
    Uses the add_tokens SQL RPC when available — a plain read-modify-write here
    races with the atomic consume_token RPC and loses concurrent decrements.
    Falls back to read-modify-write ONLY when the RPC is definitively missing:
    after a timeout / reset / 5xx the RPC may already have been applied, and a
    second (fallback) update would credit the user twice."""
    global _add_tokens_rpc
    if not sb or not user_id:
        return None
    if _add_tokens_rpc:
        try:
            r = sb.rpc("add_tokens", {"p_user_id": user_id, "p_delta": delta}).execute()
            if isinstance(r.data, int):
                return r.data
            if isinstance(r.data, list) and r.data:
                return r.data[0]
            return r.data
        except Exception as exc:
            if not _rpc_missing(exc):
                _log.error("add_tokens RPC failed for %s (delta %+d) — outcome unknown, NOT "
                           "retried (a second update could double-apply): %s: %s",
                           user_id, delta, type(exc).__name__, exc)
                return None
            _add_tokens_rpc = False
            _log.warning("add_tokens RPC not installed — using read-modify-write: %s", exc)
    try:
        row = sb.table("users").select("tokens_remaining").eq("id", user_id).single().execute()
        cur = (row.data or {}).get("tokens_remaining")
        if cur is None:
            return None
        new_bal = cur + delta
        sb.table("users").update({"tokens_remaining": new_bal}).eq("id", user_id).execute()
        return new_bal
    except Exception as exc:
        _log.error("_add_tokens fallback error: %s", exc)
        return None

def _refund_token(user_id):
    """Best-effort: give a token back when a job fails after consuming it,
    so users are only charged for a study guide they actually receive.
    → True when the token was given back."""
    sb = _get_sb()
    if not sb or not user_id:
        return False
    new_bal = _add_tokens(sb, user_id, 1)
    if new_bal is not None:
        _log.info("Refunded 1 token to %s (-> %s)", user_id, new_bal)
    return new_bal is not None

def _get_user(user_id):
    """Fetch the full user row → dict, or None when the row does NOT exist.
    A DB error RAISES (callers answer 503 retry) — it must never look like a
    missing row, or a paying user is shown '0 tokens, Free'."""
    sb = _get_sb()
    if not sb:
        return None
    r = sb.table("users").select("*").eq("id", user_id).limit(1).execute()
    rows = r.data if isinstance(r.data, list) else []
    return rows[0] if rows else None

def _ensure_user_row(user_id, payload=None):
    """Create a missing users row from the JWT identity (INSERT … ON CONFLICT DO
    NOTHING — never overwrites an existing row). → True if the insert ran."""
    sb = _get_sb()
    if not sb or not user_id:
        return False
    if payload is None:
        payload = getattr(_req_g, "auth_payload", None) if has_request_context() else None
    ident = _identity_from_payload(payload)
    try:
        sb.table("users").upsert({
            "id": user_id, "email": ident["email"],
            "name": ident["name"] or None, "avatar_url": ident["avatar"] or None,
        }, ignore_duplicates=True).execute()
        return True
    except Exception as exc:
        _log.error("ensure user row failed for %s: %s", user_id, exc)
        return False

def _get_or_create_referral_code(user_id):
    """Return this user's referral code, generating one if not yet set."""
    sb = _get_sb()
    if not sb:
        return None
    try:
        r = sb.table("users").select("referral_code").eq("id", user_id).limit(1).execute()
        code = ((r.data or [{}])[0] or {}).get("referral_code")
        if code:
            return code
        code = hashlib.sha256(user_id.encode()).hexdigest()[:8].upper()
        res = sb.table("users").update({"referral_code": code}).eq("id", user_id).execute()
        if not res.data:   # nothing was stored — don't hand out a code that doesn't exist
            _log.warning("referral code not stored for %s", user_id)
            return None
        return code
    except Exception as exc:
        _log.error("referral code error for %s: %s", user_id, exc)
        return None

def _award_referral(new_subscriber_id, sb):
    """Award 10 tokens to the referrer when their referee first subscribes.
    Free mode has no tokens to give: nothing is awarded (or marked paid)."""
    if FREE_MODE:
        return
    try:
        r = sb.table("users").select("referred_by, referral_paid").eq("id", new_subscriber_id).single().execute()
        if not r.data:
            return
        referrer_id  = r.data.get("referred_by")
        already_paid = r.data.get("referral_paid", False)
        if not referrer_id or already_paid:
            return
        # Mark paid FIRST so a redelivered/duplicate event can't double-award,
        # then grant atomically.
        sb.table("users").update({"referral_paid": True}).eq("id", new_subscriber_id).execute()
        _add_tokens(sb, referrer_id, 10)
        _log.info(f"Referral reward: 10 tokens → {referrer_id} (subscriber={new_subscriber_id})")
    except Exception as exc:
        _log.error(f"_award_referral error: {exc}")

# Distinct auth failure codes so the client can refresh its session silently
# (token_expired / token_invalid), retry later (auth_unavailable) or ask the user
# to sign in (auth_required) — instead of treating every failure as a sign-out.
_AUTH_ERRORS = {
    "missing":     ("Sign in required", "auth_required", 401),
    "expired":     ("Your session expired — please sign in again.", "token_expired", 401),
    "invalid":     ("Your session is no longer valid — please sign in again.", "token_invalid", 401),
    "unavailable": ("Sign-in check is temporarily unavailable — please try again in a moment.",
                    "auth_unavailable", 503),
}

def _auth_error(reason):
    msg, code, status = _AUTH_ERRORS.get(reason) or _AUTH_ERRORS["invalid"]
    return jsonify({"error": msg, "code": code}), status

def _auth_payload(req):
    """Verify the request's JWT ONCE → (user_id, payload, error_response | None).
    When _AUTH_ENABLED is False (local dev), returns ('dev', {}, None)."""
    if not _AUTH_ENABLED:
        return "dev", {}, None
    payload, reason = _jwt_verify(_get_bearer(req))
    if not payload:
        return None, None, _auth_error(reason or "invalid")
    return payload["sub"], payload, None

def _auth_check(req):
    """
    Extract + verify JWT from request.
    Returns (user_id, error_response_tuple | None).
    When _AUTH_ENABLED is False (local dev), always returns ('dev', None).
    """
    uid, _payload, err = _auth_payload(req)
    return uid, err

def _auth_optional(req):
    """Tri-state, for endpoints that also allow signed-out users a free quota:
      user id → token verified;  None → NO token sent (anonymous);
      False   → a token WAS sent but failed verification. Callers must answer
                _auth_rejected() — never silently downgrade a signed-in user to
                the anonymous quota (that showed paying users the sign-up wall)."""
    if not _AUTH_ENABLED:
        return "dev"
    tok = _get_bearer(req)
    if not tok:
        return None
    payload, reason = _jwt_verify(tok)
    if has_request_context():
        _req_g.auth_reason, _req_g.auth_payload = reason, payload
    return payload["sub"] if payload else False

def _auth_rejected():
    """Response for a Bearer token that _auth_optional rejected (uid is False)."""
    return _auth_error(getattr(_req_g, "auth_reason", "") or "invalid")

# ── Anonymous (no-login) free credits ──────────────────────────────────────────
# Let visitors try the product a few times without an account. Tracked per-IP in
# memory over a rolling window; tune with ANON_FREE_LIMIT (0 disables anon use).
ANON_FREE_LIMIT = int(os.environ.get("ANON_FREE_LIMIT", "2"))
_ANON_WINDOW    = int(os.environ.get("ANON_WINDOW_SEC", str(24 * 3600)))
_anon_lock      = threading.Lock()
_anon_usage     = {}  # ip -> [timestamps]

def _anon_remaining(ip):
    now = time.time()
    with _anon_lock:
        times = [t for t in _anon_usage.get(ip, []) if now - t < _ANON_WINDOW]
        _anon_usage[ip] = times
        return max(0, ANON_FREE_LIMIT - len(times))

def _anon_consume(ip):
    """Consume one anonymous free credit. Returns (ok, remaining)."""
    now = time.time()
    with _anon_lock:
        times = [t for t in _anon_usage.get(ip, []) if now - t < _ANON_WINDOW]
        if len(times) >= ANON_FREE_LIMIT:
            _anon_usage[ip] = times
            return False, 0
        times.append(now)
        _anon_usage[ip] = times
        return True, max(0, ANON_FREE_LIMIT - len(times))

def _anon_refund(ip):
    with _anon_lock:
        times = _anon_usage.get(ip)
        if times:
            times.pop()
            _anon_usage[ip] = times
            return True
    return False

# ── Durable per-device anonymous quota (survives restart + IP change) ───────────
# A persistent browser device id (X-Device-Id, from localStorage) is counted in
# Supabase, so the same device can't reset its free previews by restarting the
# server or hopping networks. Everything here FAILS OPEN: no device id, Supabase
# down, or the migration not yet run → returns None so the caller falls back to
# the in-memory per-IP check. A DB hiccup must never block a real student.
_DEV_ID_RE          = re.compile(r'^[A-Za-z0-9_-]{8,64}$')
_ANON_WINDOW_HOURS  = int(os.environ.get("ANON_WINDOW_HOURS", str(24 * 3650)))  # ~permanent

def _device_id(req):
    d = (req.headers.get("X-Device-Id") or "").strip()
    return d if _DEV_ID_RE.match(d) else None

def _anon_durable_consume(dev):
    """Durable device-keyed consume → (ok, remaining), or None to fall back."""
    if not dev:
        return None
    sb = _get_sb()
    if sb is None:
        return None
    try:
        res = sb.rpc("anon_consume", {"p_key": f"dev:{dev}", "p_limit": ANON_FREE_LIMIT,
                                      "p_window_hours": _ANON_WINDOW_HOURS}).execute()
        d = res.data if isinstance(res.data, dict) else {}
        if "ok" not in d:
            return None
        return bool(d.get("ok")), int(d.get("remaining", 0))
    except Exception as exc:
        _log.error("anon durable consume failed: %s", exc)
        return None  # fail open

def _anon_durable_remaining(dev):
    """Durable remaining for the badge → int, or None to fall back."""
    if not dev:
        return None
    sb = _get_sb()
    if sb is None:
        return None
    try:
        res = sb.rpc("anon_remaining", {"p_key": f"dev:{dev}", "p_limit": ANON_FREE_LIMIT,
                                        "p_window_hours": _ANON_WINDOW_HOURS}).execute()
        return int(res.data) if res.data is not None else None
    except Exception:
        return None

def _anon_durable_refund(dev):
    """Give back one durable device preview (anon_refund, migration 012).
    Best-effort: if the RPC isn't installed yet, log and carry on — a refund
    failure must never break the error path that called it. → True on success."""
    if not dev:
        return False
    sb = _get_sb()
    if sb is None:
        return False
    try:
        sb.rpc("anon_refund", {"p_key": f"dev:{dev}"}).execute()
        return True
    except Exception as exc:
        _log.warning("anon durable refund failed (migration 012 applied?): %s", exc)
        return False

# ── Free mode: fair use instead of tokens ──────────────────────────────────────
# ALIMNE_FREE_MODE (default ON; "0" restores the old token system exactly) makes
# Alimne free for everyone. Generation is then limited only by the SIGN-IN GATE (an
# anonymous visitor's first ANON_FREE_USES guides need no account; after those a
# free account is required), FAIR-USE counters (24 h windows that start at a key's
# first use), a process-wide cap on simultaneous generations (a small queue instead
# of an error), and a per-IP per-minute rate limit. Gate and counters live in the
# existing durable anon_consume / anon_refund RPCs from migrations 009 + 012, under
# 'gate:*' and 'fair:*' keys — no new SQL. All knobs are plain env reads, done once
# at import.
def _env_num(name, default, cast=int, minimum=0):
    """Plain os.environ read; unset, blank, malformed or below `minimum` → default."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        v = cast(raw.strip())
    except (TypeError, ValueError):
        return default
    return v if v >= minimum else default

def _env_switch(name, default=True):
    """A boolean env switch: unset or blank → `default`; "0", "false", "no", "off"
    (any case) → False; anything else → True. The ONE parser for ALIMNE_FREE_MODE,
    so the credit logic and the legal pages can never disagree about it."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")

FREE_MODE              = _env_switch("ALIMNE_FREE_MODE")
FAIR_DEVICE_DAILY      = _env_num("FAIR_DEVICE_DAILY", 10)      # RETIRED for anonymous visitors (the sign-in gate below replaced it). Still read, only so the legacy /api/config payload stays what it was
FAIR_IP_DAILY          = _env_num("FAIR_IP_DAILY", 250)         # per IP (campuses / carriers share one)
FAIR_USER_DAILY        = _env_num("FAIR_USER_DAILY", 40)        # signed-in, per user id
FAIR_GLOBAL_DAILY      = _env_num("FAIR_GLOBAL_DAILY", 2000)    # everyone — the daily budget breaker
FAIR_ANON_SHARE_PCT    = _env_num("FAIR_ANON_SHARE_PCT", 60, minimum=1)   # % of that budget anonymous visitors may use; the rest is reserved for signed-in users
FAIR_CHAT_DAILY        = _env_num("FAIR_CHAT_DAILY", 100)       # chat questions per signed-in user
WEB_THREADS            = _env_num("WEB_THREADS", 4, minimum=2)  # gunicorn --threads. The LIVE service runs 4; raise it together with the two knobs below
GEN_MAX_CONCURRENT     = _env_num("GEN_MAX_CONCURRENT", 2, minimum=1)   # generations running at once (each holds a web thread)
GEN_MAX_WAITING        = _env_num("GEN_MAX_WAITING", 1)         # requests allowed to WAIT for a slot (each holds a web thread too)
GEN_QUEUE_WAIT_S       = _env_num("GEN_QUEUE_WAIT_S", 45, cast=float)
RATE_SUMMARIZE_PER_MIN = _env_num("RATE_SUMMARIZE_PER_MIN", 30, minimum=1)
RATE_PRECHECK_PER_MIN  = _env_num("RATE_PRECHECK_PER_MIN", 5, minimum=1)   # the yt-dlp probe / URL fetch run BEFORE a slot is taken
_FAIR_WINDOW_HOURS     = 24
_FAIR_BUDGET_S         = 3.0    # all the counter lookups of one request share this much time, then fail open
_CHAT_USER_PER_MIN     = 10     # chat questions per signed-in user per minute

# The sign-in gate: an anonymous visitor may make ANON_FREE_USES guides without an
# account; after those they must sign in (a free account) to make more. It is a
# LIFETIME allowance per device, not a daily one: its counter is read with the long
# ANON_USES_WINDOW_HOURS window instead of 24 h. A device is only an id the browser
# keeps, so a private window, cleared site data or another browser is a NEW device
# with its own free guides. FAIR_ANON_IP_DAILY is what bounds that: anonymous guides
# per IP a day across ALL devices (default 10, about three browsers' worth).
_ANON_USES_WINDOW_MAX_H = 876000   # 100 years. A window Postgres cannot subtract from now() makes the RPC raise, and a raising RPC fails OPEN

def _anon_gate_knobs():
    """The sign-in gate's knobs from the environment → (ANON_FREE_USES,
    ANON_USES_WINDOW_HOURS, FAIR_ANON_IP_DAILY). Blank, malformed or negative →
    the default. ANON_FREE_USES=0 is meaningful (sign in from the very first
    guide); a zero window is not (it would hand the free guides back at once)."""
    return (_env_num("ANON_FREE_USES", 3),
            min(_env_num("ANON_USES_WINDOW_HOURS", 87600, minimum=1), _ANON_USES_WINDOW_MAX_H),
            _env_num("FAIR_ANON_IP_DAILY", 10))

ANON_FREE_USES, ANON_USES_WINDOW_HOURS, FAIR_ANON_IP_DAILY = _anon_gate_knobs()

# Running + waiting generations can never reach the web-thread count, whatever the
# knobs say: a waiting request holds a gunicorn thread exactly like a running one, and
# at least one thread must stay free for /healthz, /api/config and the static files
# (Render restarts a service whose health check goes unanswered, which wipes every
# in-memory guide). Defaults on 4 threads: 2 running + 1 waiting.
_GEN_SLOTS    = max(1, min(GEN_MAX_CONCURRENT, WEB_THREADS - 1))
_GEN_WAIT_MAX = max(0, min(GEN_MAX_WAITING, WEB_THREADS - 1 - _GEN_SLOTS))

def _counter_label(key):
    """A counter's name for the logs — never the device id, IP or user id it is
    keyed by: 'dev', 'ip', 'global', … for fair:* keys, 'gate:dev' / 'gate:noid'
    for the sign-in gate."""
    parts = key.split(":")
    return parts[1] if parts[0] == "fair" else ":".join(parts[:2])

def _fair_take(key, limit, window_hours=_FAIR_WINDOW_HOURS):
    """Take one unit from a counter → (taken, remaining). `taken` is True, False
    (exhausted) or None (unknown: no database, RPC missing/erroring/odd reply).
    None FAILS OPEN — a DB hiccup must never block a real student — but it is
    logged, and nothing is refunded for it (the RPC may or may not have counted).
    `remaining` is the units left after this one, or None when the reply had no
    usable number."""
    sb = _get_sb()
    if sb is None:
        return None, None
    try:
        res = sb.rpc("anon_consume", {"p_key": key, "p_limit": limit,
                                      "p_window_hours": window_hours}).execute()
        d = res.data if isinstance(res.data, dict) else {}
        if "ok" not in d:
            _log.error("fair-use %s counter: unexpected RPC reply %r — failing open",
                       _counter_label(key), res.data)
            return None, None
        ok = bool(d["ok"])
        left = d.get("remaining")
        if not isinstance(left, int) or isinstance(left, bool):
            left = None
        if ok and key.startswith("fair:global"):
            _fair_watch(key, limit, left)
        return ok, left
    except Exception as exc:
        _log.error("fair-use %s counter failed — failing open: %s: %s",
                   _counter_label(key), type(exc).__name__, exc)
        return None, None

def _fair_consume(key, limit):
    """Take one unit from a 24 h fair-use counter → True (taken), False (exhausted)
    or None (unknown — fails open, see _fair_take)."""
    return _fair_take(key, limit)[0]

def _fair_watch(key, limit, remaining):
    """One log line (warning level, so it shows in Render's logs) when a daily
    GLOBAL pool crosses 80% of its limit, and one when it is used up — the owner's
    cue to look at the Groq bill before the breaker starts refusing everyone."""
    if not isinstance(remaining, int) or isinstance(remaining, bool) or limit < 1:
        return
    used = limit - remaining
    if used == (limit * 4 + 4) // 5:
        _log.warning("fair-use counter %s passed 80%% of its daily limit (%d of %d used)", key, used, limit)
    elif used == limit:
        _log.warning("fair-use counter %s is used up (%d of %d) — new guides are refused until it resets",
                     key, used, limit)

def _fair_refund_key(key):
    """Give one unit back to a counter (anon_refund). Best-effort; → True on success."""
    sb = _get_sb()
    if sb is None:
        return False
    try:
        sb.rpc("anon_refund", {"p_key": key}).execute()
        return True
    except Exception as exc:
        _log.warning("fair-use %s refund failed: %s: %s", _counter_label(key), type(exc).__name__, exc)
        return False

def _fair_refund(keys):
    """Refund every counter in `keys` → True when ALL went back."""
    ok = True
    for k in keys or ():
        if not _fair_refund_key(k):
            ok = False
    return ok

def _fair_remaining_key(key, limit, window_hours=_FAIR_WINDOW_HOURS):
    """Units left on a counter, read-only (anon_remaining) → int, or None when unknown."""
    sb = _get_sb()
    if sb is None:
        return None
    try:
        res = sb.rpc("anon_remaining", {"p_key": key, "p_limit": limit,
                                        "p_window_hours": window_hours}).execute()
        return int(res.data) if res.data is not None else None
    except Exception:
        return None

def _anon_gate(dev, ip):
    """The sign-in gate counter of an anonymous request → (key, window hours).
    A device id: that device's lifetime allowance. No (valid) device id — a script,
    or a browser with storage switched off: the allowance is counted per IP, per
    24 h, so leaving the header out can never dodge the gate."""
    if dev:
        return f"gate:dev:{dev}", ANON_USES_WINDOW_HOURS
    ipk = _ip_bucket(ip) if ip and ip != "unknown" else ""
    return f"gate:noid:{ipk or 'unknown'}", _FAIR_WINDOW_HOURS

def _anon_gate_remaining(gate):
    """Free guides left on a gate counter (`gate` = _anon_gate(...)), read-only →
    int, or None when unknown."""
    key, window = gate
    return _fair_remaining_key(key, ANON_FREE_USES, window)

# fair-use refusal code → (HTTP status, English, Arabic). Never says "unlimited".
# ('fair_use_device' is retired: the sign-in gate answers 'signin_required' instead.)
_FAIR_REFUSALS = {
    "fair_use_user": (429,
        "You've reached today's fair-use limit for your account. It resets within 24 hours — please try again later.",
        "لقد وصلت إلى حد الاستخدام العادل اليومي لحسابك. يُعاد ضبطه خلال 24 ساعة — يُرجى المحاولة لاحقًا."),
    "fair_use_ip": (429,
        "Many study guides have been made from your network today, so new ones are paused for now. Please try again later.",
        "أُنشئ عدد كبير من الدلائل الدراسية من شبكتك اليوم، لذا أُوقف إنشاء المزيد مؤقتًا. يُرجى المحاولة لاحقًا."),
    "busy_today": (503,
        "Alimne has reached its free capacity for today. Please try again later.",
        "وصل الموقع إلى طاقته المجانية لهذا اليوم. يُرجى المحاولة لاحقًا."),
}

_AR_THE_COUNT = {3: "الثلاثة", 4: "الأربعة", 5: "الخمسة", 6: "الستة", 7: "السبعة",
                 8: "الثمانية", 9: "التسعة", 10: "العشرة"}

# WHY a sign-in refusal was given: the 401 body's `reason`. Each has its own words,
# because only one of them is about what THIS visitor did:
#   device   this browser's own free guides are used (the gate counter)
#   network  the anonymous allowance of this network is used up for today (the per-IP
#            cap across all devices, or the per-IP allowance of a request without a
#            device id)
#   pool     the guides everyone may make without an account are used up for today
#            (the anonymous slice of the global budget)
_SIGNIN_REASONS = ("device", "network", "pool")

def _signin_required_text(ar=False, reason="device"):
    """The sign-in refusal in words. Only 'device' says "you've used your N free
    guides" (with the REAL allowance, ANON_FREE_USES, so the number can never go
    stale): a visitor refused because the network's or the whole anonymous pool's
    allowance is gone may have made nothing at all, and is told what really
    happened. All three end with the same call to action. Signing in is free and
    stays free: no text mentions a price, a plan or "unlimited"."""
    n = ANON_FREE_USES
    if ar:
        tail = "أنشئ حسابًا مجانيًا للمتابعة — ما زال الاستخدام مجانيًا."
        if n <= 0:
            return "أنشئ حسابًا مجانيًا لإنشاء أدلة الدراسة — الاستخدام مجاني."
        if reason == "network":
            return "استُنفدت اليوم الأدلة المجانية المتاحة على شبكتك دون حساب. " + tail
        if reason == "pool":
            return "استُنفدت اليوم الأدلة المجانية المتاحة دون حساب. " + tail
        if n == 1:
            return "لقد استخدمت دليلك المجاني. " + tail
        if n == 2:
            return "لقد استخدمت دليلَيك المجانيَّين. " + tail
        return "لقد استخدمت أدلتك المجانية %s. " % _AR_THE_COUNT.get(n, "الـ%d" % n) + tail
    tail = "Create a free account to keep going - it's still free."
    if n <= 0:
        return "Create a free account to make study guides - it's free."
    if reason == "network":
        return "Today's free guides without an account are used up on your network. " + tail
    if reason == "pool":
        return "Today's free guides without an account are used up. " + tail
    if n == 1:
        return "You've used your free guide. " + tail
    return "You've used your %d free guides. " % n + tail

def _anon_rule_text():
    """The account rule in words, for the legal pages → (English, Arabic): how many
    guides need no account, from the REAL allowance (ANON_FREE_USES). Never the
    bare "no sign-up needed": that is only true for those first guides."""
    n = ANON_FREE_USES
    if n <= 0:
        return ("A free account is required to make study guides.",
                "يلزم إنشاء حساب مجاني لإنشاء أدلة الدراسة.")
    if n == 1:
        return ("Your first study guide needs no account; after that, a free account is required to make more.",
                "دليلك الدراسي الأول لا يحتاج إلى حساب، وبعده يلزم إنشاء حساب مجاني لإنشاء المزيد.")
    if n == 2:
        ar = "أول دليلين دراسيين لا يحتاجان إلى حساب، وبعدهما يلزم إنشاء حساب مجاني لإنشاء المزيد."
    elif n <= 10:
        ar = "أول %d أدلة دراسة لا تحتاج إلى حساب، وبعدها يلزم إنشاء حساب مجاني لإنشاء المزيد." % n
    else:
        ar = "أول %d دليلًا دراسيًا لا تحتاج إلى حساب، وبعدها يلزم إنشاء حساب مجاني لإنشاء المزيد." % n
    return ("Your first %d study guides need no account; after that, a free account is required to make more." % n, ar)

def _fair_refusal(code, ar=False, reason=None):
    """A fair-use refusal as (JSON response, status). 'signin_required' is the
    sign-in gate: 401 (an account is needed — nothing is "too many") with
    `free_uses` and `reason` (one of _SIGNIN_REASONS: why the account is needed),
    so the client can word its own prompt truthfully. The other refusals carry no
    reason."""
    extra, tail = {}, ""
    if code == "signin_required":
        reason = reason if reason in _SIGNIN_REASONS else "device"
        status, msg = 401, _signin_required_text(ar, reason)
        extra, tail = {"free_uses": max(0, ANON_FREE_USES), "reason": reason}, " reason=" + reason
    else:
        status, en, ar_msg = _FAIR_REFUSALS[code]
        msg = ar_msg if ar else en
    # so 'many refusals' can be alerted on; the reason tells the device's own gate from a used-up network
    _log.info("fair-use refusal code=%s status=%s%s", code, status, tail)
    return jsonify({"error": msg, "code": code, **extra}), status

def _ip_bucket(ip):
    """The key an address is counted under: IPv4 as is; an IPv6 address by its /64
    (one subscriber or household: rotating inside a /64 buys nothing); an
    IPv4-mapped IPv6 address as the IPv4 one; anything that is not an address as
    a truncated string."""
    s = str(ip or "")[:64]
    try:
        addr = _ipaddress.ip_address(s.strip())
        if addr.version == 6:
            if addr.ipv4_mapped:
                return str(addr.ipv4_mapped)
            return str(_ipaddress.ip_network(f"{addr}/64", strict=False))
        return str(addr)
    except ValueError:
        return s

def _fair_anon_limit():
    """The slice of the global daily budget anonymous visitors may use. The rest is
    reserved for signed-in users, so anonymous traffic (or a script rotating
    device ids) can never lock out the people the sign-up funnel is built for."""
    return max(1, FAIR_GLOBAL_DAILY * min(100, FAIR_ANON_SHARE_PCT) // 100)

def _fair_charge(uid, req, data=None):
    """Free-mode stand-in for the token charge → (_Charge, None) or (None, response).
    Takes one unit from EVERY applicable counter and rolls the ones already taken
    back when a later one is exhausted.
      signed in: the account, the IP, the global daily budget.
      anonymous: the SIGN-IN GATE (ANON_FREE_USES guides per device, for good — see
                 _anon_gate), anonymous guides from this IP today, the IP, the
                 anonymous slice of the global budget, the global daily budget.
    An anonymous visitor past the gate — or on a network, or on a day, whose
    anonymous allowance is used up — is answered 401 'signin_required': a free
    account is the way forward in each of those cases, and the body's `reason`
    says which one it was (device / network / pool, see _SIGNIN_REASONS). A
    signed-in request never touches a gate key.
    A counter that can't be read fails open (see _fair_take), and all the lookups
    of one request share _FAIR_BUDGET_S: a slow database costs a request a few
    seconds at most, never a pinned web thread."""
    ip  = (_client_ip() or "")[:64]
    ipk = _ip_bucket(ip)
    dev = _device_id(req)
    has_ip = bool(ip) and ip != "unknown"
    day = _FAIR_WINDOW_HOURS
    gate_key = None
    plan = []                            # (counter key, limit, window hours, refusal code, sign-in reason)
    if uid:
        plan.append((f"fair:user:{uid}", FAIR_USER_DAILY, day, "fair_use_user", None))
    else:
        if ANON_FREE_USES <= 0:
            # No free guides at all: decided here, without the database, so a DB
            # hiccup can never fail this one open.
            return None, _fair_refusal("signin_required", _wants_ar(data), "device")
        gate_key, gate_window = _anon_gate(dev, ip)
        # A device id: the visitor's OWN free guides. No device id: the allowance is the
        # IP's, shared by everyone on it who sends none, so its refusal is about the network.
        plan.append((gate_key, ANON_FREE_USES, gate_window, "signin_required", "device" if dev else "network"))
        if has_ip:
            plan.append((f"fair:anonip:{ipk}", FAIR_ANON_IP_DAILY, day, "signin_required", "network"))
    if has_ip:
        plan.append((f"fair:ip:{ipk}", FAIR_IP_DAILY, day, "fair_use_ip", None))
    if not uid:
        plan.append(("fair:global:anon", _fair_anon_limit(), day, "signin_required", "pool"))
    plan.append(("fair:global", FAIR_GLOBAL_DAILY, day, "busy_today", None))
    taken, anon_left = [], None
    t0 = time.monotonic()
    for i, (key, limit, window, code, reason) in enumerate(plan):
        if i and time.monotonic() - t0 > _FAIR_BUDGET_S:
            _log.warning("fair-use counters over their %.1fs time budget — failing open for %s and the rest",
                         _FAIR_BUDGET_S, _counter_label(key))
            break
        got, left = _fair_take(key, limit, window)
        if got is False:
            _fair_refund(taken)          # an exhausted counter must not cost the others (the free use included)
            return None, _fair_refusal(code, _wants_ar(data), reason)
        if got is True:
            taken.append(key)
            if key == gate_key and left is not None:
                anon_left = max(0, left)
    return _Charge(uid=uid, ip=ip, dev=dev, fair_keys=tuple(taken), anon_left=anon_left), None

def _gen_rate_limit():
    """Per-IP per-minute cap on the generation endpoints: RATE_SUMMARIZE_PER_MIN in
    free mode; with ALIMNE_FREE_MODE=0 the old hard-coded 5."""
    return RATE_SUMMARIZE_PER_MIN if FREE_MODE else _RATE_MAX

def _precheck_rate_limit():
    """Per-IP per-minute cap for work that runs BEFORE a generation slot is taken
    (the yt-dlp duration probe, a server-side URL fetch). It holds a web thread
    outside the generation gate, so it keeps the old strict figure: never above
    the general limit, and RATE_PRECHECK_PER_MIN (default 5) in free mode."""
    return min(_gen_rate_limit(), RATE_PRECHECK_PER_MIN)

def _refund_credit(uid, ip, dev=None):
    """Refund one credit to the store that was charged: the account (uid), the
    durable device quota (dev) or the in-memory per-IP quota (ip).
    → True when the credit really went back (the error text may then say so)."""
    if uid:
        return _refund_token(uid)
    if dev:
        return _anon_durable_refund(dev)   # the per-IP list was never charged — leave it
    if ip:
        return _anon_refund(ip)
    return False

class _Charge:
    """One credit spent before a generation, and the store it came from.
    refund() is idempotent, so an exception plus a client disconnect (or the
    youtube → text delegation) can never refund the same credit twice.
    In free mode `fair_keys` lists the fair-use counters that were charged (an
    empty tuple when none could be read); None means a legacy token/preview
    charge. Either way, refund() gives back exactly what was taken, exactly once."""
    def __init__(self, uid=None, ip=None, dev=None, tok_left=None, fair_keys=None, anon_left=None):
        self.uid, self.ip, self.dev, self.tok_left = uid, ip, dev, tok_left
        self.fair_keys = fair_keys
        self.anon_left = anon_left   # free mode, anonymous: free guides left after this one (None: unknown, or not anonymous)
        self.refunded = False   # True once the credit really went back
        self.work_started = False   # paid AI work (Groq / Whisper) has begun
        self._settled = False
        self._lock = threading.Lock()

    def settle(self):
        """The guide was delivered — the credit stays spent."""
        with self._lock:
            self._settled = True

    def begin_work(self):
        """Paid AI work is about to start. From here on a free-mode unit is spent
        for good: the money is gone whether or not the client stays to read it."""
        with self._lock:
            self.work_started = True

    def abandon(self):
        """The client went away mid-stream (GeneratorExit). Before any paid AI work
        the unit goes back, as for any failure. After it, a free-mode unit STAYS
        spent — otherwise a script could run unlimited full-cost generations by
        closing the socket just before the last event, with every fair-use counter
        (the global breaker included) still at zero. Token mode keeps its old
        behaviour exactly. → True when a refund was made."""
        with self._lock:
            keep = self.fair_keys is not None and self.work_started and not self._settled
            if keep:
                self._settled = True
        if keep:
            _log.info("client left after the AI work started — the fair-use units stay spent")
            return False
        return self.refund()

    def refund(self):
        with self._lock:
            if self._settled:
                return False
            self._settled = True
        if self.fair_keys is not None:
            self.refunded = _fair_refund(self.fair_keys) is not False
        else:
            self.refunded = _refund_credit(self.uid, self.ip, self.dev) is not False
        return True

def _charge_credit(uid, req, data=None):
    """Spend one credit before a generation → (_Charge, None) or (None, response).
    Free mode: no credit at all — fair-use counters only (_fair_charge); `data`
    (the request's form / JSON body) just picks the language of a refusal.
    Signed-in: one account token — a DB error is 503 'retry' (never a fake
    'no tokens'), a missing users row is created and the charge retried once,
    and only a real 'no_tokens' is 402. Anonymous: the durable device quota,
    falling back to the in-memory per-IP quota."""
    if FREE_MODE:
        return _fair_charge(uid, req, data)
    if uid:
        ok, tok_left, reason = _consume_token(uid)
        if not ok and reason == "user_not_found":
            _ensure_user_row(uid)
            ok, tok_left, reason = _consume_token(uid)
            if not ok and reason == "user_not_found":
                reason = "db_error"   # row still missing → retryable, not 'pay up'
        if ok:
            return _Charge(uid=uid, tok_left=tok_left), None
        if reason == "no_tokens":
            return None, (jsonify({
                "error": "You have no tokens left. Upgrade to continue.",
                "code": "no_tokens", "tokens_remaining": 0
            }), 402)
        return None, (jsonify({
            "error": "Couldn't reach your account — please try again in a moment.",
            "code": "retry"
        }), 503)
    ip  = _client_ip()
    dev = _device_id(req)
    dur = _anon_durable_consume(dev)
    if dur is not None:
        ok, tok_left = dur
    else:
        dev = None    # durable store unavailable → the per-IP list is what gets charged
        ok, tok_left = _anon_consume(ip)
    if not ok:
        return None, (jsonify({
            "error": "You've used your free previews. Sign up free to get more.",
            "code": "signin_for_more", "tokens_remaining": 0
        }), 402)
    return _Charge(ip=ip, dev=dev, tok_left=tok_left), None

app = Flask(__name__, static_folder=DIST, static_url_path="")
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB upload limit
CORS(app, origins=[APP_URL, "http://localhost:5173", "http://127.0.0.1:5173"])

@app.errorhandler(413)
def _too_large(_e):
    # Werkzeug's default is an HTML page the client shows as "Server error 413".
    return jsonify({"error": "File is over 50 MB — compress or split it.", "code": "too_large"}), 413

# Security headers on every response
@app.after_request
def _security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.is_secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https":
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.path.startswith("/api/") or request.path == "/admin" or request.path.startswith("/admin/"):
        # Admin pages carry subscriber PII and set the session cookie: never cache.
        resp.headers.setdefault("Cache-Control", "no-store")
    # Content-Security-Policy — defence-in-depth backstop behind the output
    # escaping. The React SPA loads an external bundle (no inline JS), so it gets
    # a strict script-src; the server-rendered pages (/admin, /api/view/*) use
    # inline <script>/onclick, so only those routes relax script-src.
    _p = request.path
    _inline_html = _p == "/admin" or _p.startswith("/admin/") or _p.startswith("/api/view/") or _p.startswith("/s/")
    _script_src = "script-src 'self' 'unsafe-inline'" if _inline_html else "script-src 'self'"
    resp.headers.setdefault("Content-Security-Policy", (
        "default-src 'self'; "
        f"{_script_src}; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://*.supabase.co; "
        "frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'"
    ))
    return resp

# Per-IP rate limiting
_rate_limit_lock = threading.Lock()
_rate_limit      = {}
_RATE_WINDOW     = 60
_RATE_MAX        = 5
_RATE_TABLE_MAX  = 5000    # past this many keys, entries that expired are dropped (a spoofed-IP flood must not grow memory forever)

def _check_rate_limit(ip, scope="main", limit=_RATE_MAX):
    # Exempt ONLY genuine loopback (local dev). A blanket _is_private() exemption
    # let an attacker send CF-Connecting-IP: 10.0.0.1 to disable rate limiting
    # entirely — private-but-not-loopback client IPs must still be limited.
    if ip in ("127.0.0.1", "::1"):
        return True
    key = f"{scope}:{_ip_bucket(ip)}"     # an IPv6 client is one bucket per /64
    now = time.time()
    with _rate_limit_lock:
        if len(_rate_limit) > _RATE_TABLE_MAX:
            for k in [k for k, ts in _rate_limit.items() if not ts or now - ts[-1] >= _RATE_WINDOW]:
                del _rate_limit[k]
        times = [t for t in _rate_limit.get(key, []) if now - t < _RATE_WINDOW]
        if len(times) >= limit:
            _rate_limit[key] = times
            return False
        times.append(now)
        _rate_limit[key] = times
    return True

# ── Visitor tracking ──────────────────────────────────────────────────────────
ADMIN_TOKEN  = os.environ.get("ADMIN_TOKEN") or secrets.token_urlsafe(24)
_visitors    = []
_vis_lock    = threading.Lock()
_blocked_ips = set()   # IPs that are blocked from using the app

# Geo-enrichment cache + concurrency guard: without this, every non-asset
# request spawns a thread doing a 5s HTTP call to ip-api.com (which caps at
# 45/min), so a burst would exhaust threads and hammer the API.
_geo_cache        = {}
_geo_cache_order  = []
_geo_inflight     = set()
_geo_lock         = threading.Lock()
_GEO_MAX_INFLIGHT = 6

_PRIVATE_RANGES = (
    "127.", "::1", "10.", "192.168.", "172.16.", "172.17.", "172.18.",
    "172.19.", "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
    "172.25.", "172.26.", "172.27.", "172.28.", "172.29.", "172.30.",
    "172.31.", "0.0.0.0",
)

def _is_private(ip):
    return any(ip.startswith(p) for p in _PRIVATE_RANGES)

# ── Admin authentication ───────────────────────────────────────────────────────
# The admin token is NEVER read from the query string (query strings end up in
# Render's / Cloudflare's request logs), never rendered into a page and never
# kept in localStorage. A browser signs in once via POST /admin/login and gets an
# HttpOnly cookie "v2.<issued-ms>.<lifetime-s>.<nonce>.<sig>", signed with a key *derived*
# from ADMIN_TOKEN (never the token), so rotating ADMIN_TOKEN invalidates every
# cookie. The server enforces the lifetime itself (a copied cookie stops working
# after 30 days with "Remember", 12 hours without) and Sign out revokes every
# cookie issued before it (_admin_not_before). Scripts send X-Admin-Token.
ADMIN_COOKIE         = "alimne_admin"
_ADMIN_COOKIE_PATH   = "/admin"
_ADMIN_REMEMBER_SECS = 30 * 24 * 3600     # "Remember on this device" = 30 days
_ADMIN_SESSION_SECS  = 12 * 3600          # without "Remember": a browser-session cookie, and 12 h max on the server
_ADMIN_CSRF_HEADER   = "X-Requested-With"
_ADMIN_CSRF_VALUE    = "alimne-admin"
_ADMIN_LOGIN_PER_MIN = 10
_ADMIN_CLOCK_SKEW_MS = 60 * 1000
# Sessions issued at or before this time (ms since the epoch) are revoked. Sign
# out moves it to "now". In memory: the single gunicorn worker shares it across
# its threads; a restart forgets it, and the signed lifetime still caps the cookie.
_admin_not_before    = [0]
_admin_session_lock  = threading.Lock()

def _ct_eq(a, b):
    """Constant-time string compare that never raises. secrets.compare_digest
    raises TypeError on non-ASCII str (a 500 for a stray 'é' header)."""
    if not isinstance(a, str) or not isinstance(b, str) or not a or not b:
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))

def _admin_session_sig(body):
    # Keyed by ADMIN_TOKEN at call time: a new token => a new key, so every
    # previously issued cookie stops verifying automatically.
    key = hmac.new(ADMIN_TOKEN.encode("utf-8"), b"alimne-admin-session-v2", hashlib.sha256).digest()
    return hmac.new(key, body.encode("ascii"), hashlib.sha256).hexdigest()

def _admin_session_value(ttl):
    """A fresh cookie value for a session that lasts `ttl` seconds from now."""
    with _admin_session_lock:
        # Strictly after any Sign out, even within the same millisecond.
        iat_ms = max(int(time.time() * 1000), _admin_not_before[0] + 1)
    body = f"v2.{iat_ms}.{int(ttl)}.{secrets.token_hex(8)}"   # nonce: every login is unique
    return f"{body}.{_admin_session_sig(body)}"

def _admin_session_ok(value):
    """True for an untampered, unexpired, unrevoked cookie from _admin_session_value."""
    if not isinstance(value, str) or not value or len(value) > 160 or not ADMIN_TOKEN:
        return False
    parts = value.split(".")
    if len(parts) != 5 or parts[0] != "v2":
        return False
    _, iat_s, ttl_s, nonce, sig = parts
    if not (iat_s.isascii() and iat_s.isdigit() and ttl_s.isascii() and ttl_s.isdigit()
            and nonce.isascii() and nonce.isalnum()):
        return False
    if not _ct_eq(sig, _admin_session_sig(f"v2.{iat_s}.{ttl_s}.{nonce}")):
        return False
    iat_ms, ttl = int(iat_s), int(ttl_s)
    now_ms = int(time.time() * 1000)
    if iat_ms <= _admin_not_before[0] or iat_ms > now_ms + _ADMIN_CLOCK_SKEW_MS:
        return False
    return now_ms - iat_ms < min(ttl, _ADMIN_REMEMBER_SECS) * 1000

def _admin_revoke_sessions():
    """Sign out everywhere: every cookie issued up to now stops working."""
    with _admin_session_lock:
        _admin_not_before[0] = max(_admin_not_before[0], int(time.time() * 1000))

def _admin_auth():
    """How this request is authenticated as admin: 'header' (X-Admin-Token, for
    scripts), 'cookie' (browser session from /admin/login) or None."""
    if _ct_eq(request.headers.get("X-Admin-Token", ""), ADMIN_TOKEN):
        return "header"
    if _admin_session_ok(request.cookies.get(ADMIN_COOKIE, "")):
        return "cookie"
    return None

def _admin_ok():
    how = _admin_auth()
    if how is None:
        return False
    if how == "cookie" and request.method not in ("GET", "HEAD", "OPTIONS"):
        # CSRF defence in depth on top of SameSite=Strict: a cross-site page
        # can't attach a custom header without a CORS preflight, and credentialed
        # CORS is never granted here. Header (script) auth needs no such check.
        return request.headers.get(_ADMIN_CSRF_HEADER, "") == _ADMIN_CSRF_VALUE
    return True

def _safe_err(e):
    if isinstance(e, ValueError):
        return str(e)
    _log.error("internal error: %s\n%s", e, _tb.format_exc())
    return "Processing failed — please try again."

def _via_cloudflare():
    """True if we can trust this request's CF-Connecting-IP header. When
    CF_ORIGIN_SECRET is configured, a Cloudflare Transform Rule stamps it as
    X-Origin-Verify; a request that reaches the Render origin directly (bypassing
    Cloudflare) won't have it, so its CF-Connecting-IP must NOT be trusted.
    Without the secret configured we can't tell, so we trust it as before."""
    if not CF_ORIGIN_SECRET:
        return True
    # _ct_eq: a non-ASCII header made secrets.compare_digest raise (a 500 on every route).
    return _ct_eq(request.headers.get("X-Origin-Verify", ""), CF_ORIGIN_SECRET)

def _client_ip():
    ra = request.remote_addr or "unknown"
    # CF-Connecting-IP is set by Cloudflare's edge, but ONLY trustworthy for
    # traffic that actually transited Cloudflare (see _via_cloudflare) — the
    # Render origin is reachable directly, where the header is attacker-controlled.
    cf = (request.headers.get("CF-Connecting-IP") or "").strip()
    if cf and _via_cloudflare():
        return cf
    if not _is_private(ra):
        return ra
    # No trusted CF header and remote_addr is a private proxy hop. Fall back to
    # the LAST X-Forwarded-For entry (appended by the nearest trusted proxy) —
    # NOT the first, which is client-supplied and trivially spoofable.
    parts = [p.strip() for p in request.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
    return parts[-1] if parts else ra

def _cache_geo(ip, geo):
    with _geo_lock:
        _geo_cache[ip] = geo
        _geo_cache_order.append(ip)
        if len(_geo_cache_order) > 2000:
            _geo_cache.pop(_geo_cache_order.pop(0), None)
        _geo_inflight.discard(ip)

def _enrich_geo(entry, ip):
    """Background thread: full geolocation via ip-api.com. Result is cached so
    repeat visitors don't re-spawn a thread / re-hit the API."""
    if _is_private(ip):
        geo = {"country": "Local / LAN", "region": "", "city": "localhost",
               "isp": "private network", "lat": "", "lon": ""}
        with _vis_lock:
            entry.update(geo)
        _cache_geo(ip, geo)
        return
    try:
        r = http.get(
            f"http://ip-api.com/json/{ip}"
            f"?fields=status,country,countryCode,regionName,city,isp,org,lat,lon",
            timeout=5
        )
        d = r.json()
        if d.get("status") != "success":
            with _geo_lock:
                _geo_inflight.discard(ip)
            return
        geo = {
            "country": d.get("country", ""),
            "region":  d.get("regionName", ""),
            "city":    d.get("city", ""),
            "isp":     d.get("org") or d.get("isp", ""),
            "lat":     d.get("lat", ""),
            "lon":     d.get("lon", ""),
        }
        with _vis_lock:
            entry.update(geo)
        _cache_geo(ip, geo)
    except Exception:
        with _geo_lock:
            _geo_inflight.discard(ip)

def _log_usage_async(kind, source, title=""):
    """Record one generation event (signed-in / anon / demo) so the admin reflects
    REAL usage that survives restarts. Best-effort, non-blocking: geo is read from
    the already-warm cache (populated by track_visitor on earlier requests) and the
    insert runs on a daemon thread so it never delays the stream."""
    ip = _client_ip()
    with _geo_lock:
        geo = dict(_geo_cache.get(ip) or {})
    country, city = geo.get("country", ""), geo.get("city", "")
    def _do():
        sb = _get_sb()
        if sb is None:
            return
        try:
            sb.table("usage_events").insert({
                "kind": kind, "source": source,
                "country": (country or "")[:80], "city": (city or "")[:80],
                "title": (title or "")[:200],
            }).execute()
        except Exception as exc:
            _log.error("usage log failed: %s", exc)
    threading.Thread(target=_do, daemon=True).start()

def _bump_visit_async():
    """Increment today's durable page-view counter (best-effort, non-blocking).
    Uncapped and survives restarts — unlike the in-memory _visitors buffer."""
    day = time.strftime("%Y-%m-%d", time.gmtime())
    def _do():
        sb = _get_sb()
        if sb is None:
            return
        try:
            sb.rpc("bump_visit", {"p_day": day}).execute()
        except Exception as exc:
            _log.error("visit bump failed: %s", exc)
    threading.Thread(target=_do, daemon=True).start()

_CANONICAL_ORIGIN   = "https://alimne.app"
# Escape hatch: CANONICAL_REDIRECT=0 turns the redirect off without a code change.
_CANONICAL_REDIRECT = os.environ.get("CANONICAL_REDIRECT", "1") != "0"

@app.before_request
def _canonical_host():
    # The raw Render origin must not serve the app: its session/localStorage is
    # separate from alimne.app's and OAuth returns to a different origin. Only
    # GET/HEAD page loads move (a 301 would turn API POSTs into GETs); /healthz
    # stays reachable for Render's probe. Registered first so it runs first.
    if not _CANONICAL_REDIRECT or request.method not in ("GET", "HEAD") \
            or request.path == "/healthz" or request.path.startswith("/api/"):
        return None
    host = (request.host or "").split(":")[0].lower()
    if host.endswith(".onrender.com"):
        from urllib.parse import quote
        qs = request.query_string.decode("latin-1")
        if request.path == "/admin" or request.path.startswith("/admin/"):
            qs = ""   # never carry an old ?token= across — query strings get logged
        path = quote(request.path, safe="/%:@!$&'()*+,;=-._~")
        return redirect(_CANONICAL_ORIGIN + path + ("?" + qs if qs else ""), 301)
    return None

@app.before_request
def track_visitor():
    # Render's health probe hits /healthz every few seconds — never log, geo-look-
    # up, or block it, or it would flood the visitor feed and could fail checks.
    if request.path == "/healthz":
        return
    skip = ("/assets/", "/favicon", "/admin")
    if any(request.path.startswith(s) for s in skip):
        # still enforce block on non-admin paths
        pass
    ip = _client_ip()

    # Block check — return 403 immediately for blocked IPs (except admin itself)
    if ip in _blocked_ips and not request.path.startswith("/admin"):
        from flask import abort
        abort(403)

    if any(request.path.startswith(s) for s in ("/assets/", "/favicon")):
        return

    entry = {
        "time":    time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "ip":      ip,
        "country": request.headers.get("CF-IPCountry", ""),
        "region":  "",
        "city":    "",
        "isp":     "",
        "lat":     "",
        "lon":     "",
        "path":    request.path,      # path only, never the query string (secrets)
        "method":  request.method,
        "ua":      (request.headers.get("User-Agent") or "")[:160],
    }
    with _vis_lock:
        _visitors.insert(0, entry)
        if len(_visitors) > 1000:
            _visitors.pop()
    # Durable, uncapped visit counter — count only real page loads (the app root
    # or a shared /s/ guide), not API calls, assets, or admin.
    if request.method == "GET" and (request.path == "/" or request.path.startswith("/s/")):
        _bump_visit_async()
    # Enrich geo (CF headers don't give city/ISP/coords), but reuse the cache,
    # dedupe in-flight lookups per IP, and cap concurrent threads so a burst
    # can't exhaust threads or exceed ip-api.com's rate limit.
    do_enrich = False
    with _geo_lock:
        cached = _geo_cache.get(ip)
        if cached is not None:
            entry.update(cached)
        elif ip not in _geo_inflight and len(_geo_inflight) < _GEO_MAX_INFLIGHT:
            _geo_inflight.add(ip)
            do_enrich = True
    if do_enrich:
        threading.Thread(target=_enrich_geo, args=(entry, ip), daemon=True).start()


@app.route("/admin/block", methods=["POST"])
def admin_block():
    if not _admin_ok():
        return jsonify({"error": "Unauthorized"}), 401
    ip = request.json.get("ip", "").strip()
    if not ip:
        return jsonify({"error": "No IP"}), 400
    with _vis_lock:
        _blocked_ips.add(ip)
    return jsonify({"ok": True, "blocked": ip})


@app.route("/admin/unblock", methods=["POST"])
def admin_unblock():
    if not _admin_ok():
        return jsonify({"error": "Unauthorized"}), 401
    ip = request.json.get("ip", "").strip()
    with _vis_lock:
        _blocked_ips.discard(ip)
    return jsonify({"ok": True, "unblocked": ip})


@app.route("/admin/clear", methods=["POST"])
def admin_clear_log():
    if not _admin_ok():
        return jsonify({"error": "Unauthorized"}), 401
    with _vis_lock:
        _visitors.clear()
    return jsonify({"ok": True})


# Effective monthly price (USD) of the Pro plan, read from the live Stripe price
# and cached for an hour so the admin dashboard doesn't hit Stripe on every load.
# Any recurring interval (year/month/week/day + interval_count) is normalised to
# a monthly figure. Falls back to PRO_MONTHLY_USD when Stripe is unavailable.
_price_cache = {"amount": None, "ts": 0.0}
_price_lock  = threading.Lock()

def _monthly_price_usd():
    now = time.time()
    with _price_lock:
        if _price_cache["amount"] is not None and now - _price_cache["ts"] < 3600:
            return _price_cache["amount"]
    amount = PRO_MONTHLY_USD  # fallback
    if STRIPE_PRICE_ID and STRIPE_SECRET_KEY:
        try:
            import stripe as _stripe
            _stripe.api_key = STRIPE_SECRET_KEY
            p = _stripe.Price.retrieve(STRIPE_PRICE_ID).to_dict()
            cents = p.get("unit_amount")
            if cents is not None:
                val = cents / 100.0
                rec = p.get("recurring") or {}
                interval = rec.get("interval")
                count = rec.get("interval_count", 1) or 1
                if interval == "year":
                    val = val / (12.0 * count)
                elif interval == "week":
                    val = val * (52.0 / 12.0) / count
                elif interval == "day":
                    val = val * (365.0 / 12.0) / count
                elif interval == "month":
                    val = val / count
                amount = round(val, 2)
        except Exception as exc:
            _log.warning("Stripe price fetch failed, using fallback $%.2f: %s", amount, exc)
    with _price_lock:
        _price_cache["amount"] = amount
        _price_cache["ts"] = now
    return amount


# Matches a canonical UUID (the Supabase user id). Used to validate admin
# action targets so a caller can't inject arbitrary values.
_UUID_RE = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')


@app.route("/admin/user/grant", methods=["POST"])
def admin_user_grant():
    """Grant (or deduct) tokens for one user. Admin-only, header-authenticated."""
    if not _admin_ok():
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    uid = str(data.get("user_id", "")).strip()
    try:
        amount = int(data.get("amount", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be an integer"}), 400
    if not _UUID_RE.match(uid):
        return jsonify({"error": "invalid user_id"}), 400
    if amount == 0 or amount < -1000 or amount > 1000:
        return jsonify({"error": "amount must be a non-zero integer in [-1000, 1000]"}), 400
    sb = _get_sb()
    if sb is None:
        return jsonify({"error": "Supabase not configured"}), 500
    new_bal = _add_tokens(sb, uid, amount)
    if new_bal is None:
        return jsonify({"error": "user not found or update failed"}), 404
    _log.info("ADMIN grant %+d tokens -> user %s (new balance %s)", amount, uid, new_bal)
    return jsonify({"ok": True, "tokens_remaining": new_bal})


@app.route("/admin/user/cancel", methods=["POST"])
def admin_user_cancel():
    """Cancel a user's subscription. If they have a Stripe subscription it is set
    to cancel at period end (they keep access until then; the webhook finalises
    the status). Otherwise the local status is downgraded to free. Admin-only."""
    if not _admin_ok():
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    uid = str(data.get("user_id", "")).strip()
    if not _UUID_RE.match(uid):
        return jsonify({"error": "invalid user_id"}), 400
    sb = _get_sb()
    if sb is None:
        return jsonify({"error": "Supabase not configured"}), 500
    try:
        row = sb.table("users").select("subscription_id").eq("id", uid).single().execute()
    except Exception as exc:
        return jsonify({"error": f"lookup failed: {exc}"}), 500
    sub_id = (row.data or {}).get("subscription_id") or ""
    if sub_id and STRIPE_SECRET_KEY:
        try:
            import stripe as _stripe
            _stripe.api_key = STRIPE_SECRET_KEY
            _stripe.Subscription.modify(sub_id, cancel_at_period_end=True)
        except Exception as exc:
            _log.error("ADMIN cancel: Stripe error for %s: %s", uid, exc)
            return jsonify({"error": f"Stripe cancel failed: {exc}"}), 502
        _log.info("ADMIN cancel: Stripe sub %s set to cancel at period end (user %s)", sub_id, uid)
        return jsonify({"ok": True, "canceled_at_period_end": True})
    # No Stripe subscription on file — downgrade locally.
    try:
        sb.table("users").update({"subscription_status": "free",
                                  "subscription_period_end": None}).eq("id", uid).execute()
    except Exception as exc:
        return jsonify({"error": f"update failed: {exc}"}), 500
    _log.info("ADMIN cancel: user %s downgraded to free (no Stripe sub)", uid)
    return jsonify({"ok": True, "canceled_at_period_end": False})


# Sign-in gate for /admin. The token is POSTed once to /admin/login, which sets
# an HttpOnly session cookie; the token never goes into a URL, is not kept in
# the browser, and is never rendered back into a page. On load the gate also
# deletes the token older versions left in localStorage (migration).
ADMIN_GATE_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin — Alimne</title>
<style>
 *{box-sizing:border-box;margin:0;padding:0}
 body{font-family:'Segoe UI',system-ui,sans-serif;background:#050d1a;color:#e8f0ff;
      min-height:100vh;display:flex;align-items:center;justify-content:center;padding:1rem}
 .card{background:#0a1628;border:1px solid #1a3a6e;border-radius:14px;padding:1.8rem;max-width:420px;width:100%}
 h2{font-size:1.1rem;margin:0 0 .4rem;display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}
 p{color:#8aa0c8;font-size:.88rem;margin:0 0 .6rem;line-height:1.5}
 p.ar{margin-bottom:1.1rem}
 .ar{font-family:'Segoe UI',Tahoma,'Noto Naskh Arabic',system-ui,sans-serif}
 input[type=password]{width:100%;padding:.7rem;border-radius:8px;border:1px solid #1a3a6e;
      background:#050d1a;color:#e8f0ff;font-size:.9rem;margin-bottom:.75rem}
 button{width:100%;padding:.72rem;border-radius:8px;border:none;background:#4f8ef7;color:#fff;
      font-weight:600;font-size:.9rem;cursor:pointer}
 button:hover{opacity:.9}
 button[disabled]{opacity:.6;cursor:wait}
 .err{color:#f87171;font-size:.85rem;margin-bottom:.75rem;display:none;line-height:1.5}
 label{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;color:#8aa0c8;font-size:.82rem;margin:0 0 1rem;cursor:pointer}
</style></head><body>
<div class="card">
  <h2>🔒 Alimne Admin <span class="ar" lang="ar" dir="rtl">لوحة الإدارة</span></h2>
  <p>Enter your admin token. With &ldquo;Remember&rdquo; ticked, this device stays signed in for 30 days &mdash; the token itself is never saved in the browser.</p>
  <p class="ar" lang="ar" dir="rtl">أدخل رمز المشرف. عند تفعيل «تذكّرني» يبقى هذا الجهاز مسجَّل الدخول لمدة 30 يومًا، ولا يُحفظ الرمز نفسه في المتصفح أبدًا.</p>
  <div class="err" id="err" role="alert"><div id="err-en"></div><div id="err-ar" class="ar" lang="ar" dir="rtl"></div></div>
  <input id="tok" type="password" placeholder="Admin token · رمز المشرف" autocomplete="off" autofocus>
  <label><input type="checkbox" id="remember" checked> Remember on this device (30 days) · <span class="ar" lang="ar" dir="rtl">تذكّرني على هذا الجهاز (30 يومًا)</span></label>
  <button id="go" type="button">Open dashboard · <span class="ar" lang="ar" dir="rtl">فتح لوحة التحكم</span></button>
</div>
<script>
(function () {
 // Migration: older versions kept the raw admin token in localStorage. Delete
 // it — sign-in now lives in an HttpOnly cookie that page scripts can't read.
 try { localStorage.removeItem("alimne_admin_token"); } catch (e) {}
 var MSG = {
   bad:  ["That token was rejected — check it and try again.",
          "تم رفض هذا الرمز — تحقّق منه وحاول مرة أخرى."],
   rate: ["Too many attempts — wait a minute and try again.",
          "محاولات كثيرة جدًا — انتظر دقيقة ثم حاول مرة أخرى."],
   net:  ["Couldn't reach the server — check your connection and try again.",
          "تعذّر الوصول إلى الخادم — تحقّق من اتصالك وحاول مرة أخرى."],
   oops: ["Something went wrong on the server — try again in a moment.",
          "حدث خطأ في الخادم — حاول مرة أخرى بعد قليل."]
 };
 function showErr(k) {
   document.getElementById("err-en").textContent = MSG[k][0];
   document.getElementById("err-ar").textContent = MSG[k][1];
   document.getElementById("err").style.display = "block";
 }
 // A link from another site (email, chat app) doesn't carry the SameSite=Strict
 // cookie, so we can land here while still signed in. Ask same-origin and, if
 // the session is valid, forward once (time-guarded so it can never loop).
 try {
   var last = +(sessionStorage.getItem("alimne_admin_fwd") || 0);
   if (Date.now() - last > 10000) {
     fetch("/admin/session", {credentials: "same-origin"}).then(function (r) {
       if (r.status === 204) {
         try { sessionStorage.setItem("alimne_admin_fwd", String(Date.now())); } catch (e) {}
         location.replace("/admin");
       }
     }).catch(function () {});
   }
 } catch (e) {}
 var btn = document.getElementById("go"), tok = document.getElementById("tok");
 function go() {
   var v = tok.value.trim();
   if (!v || btn.disabled) return;
   btn.disabled = true;
   fetch("/admin/login", {
     method: "POST", credentials: "same-origin",
     headers: {"Content-Type": "application/json", "X-Requested-With": "alimne-admin"},
     body: JSON.stringify({token: v, remember: document.getElementById("remember").checked})
   }).then(function (r) {
     btn.disabled = false;
     if (r.ok) { tok.value = ""; location.replace("/admin"); return; }
     showErr(r.status === 429 ? "rate" : (r.status === 401 ? "bad" : "oops"));
   }).catch(function () { btn.disabled = false; showErr("net"); });
 }
 btn.addEventListener("click", go);
 tok.addEventListener("keydown", function (e) { if (e.key === "Enter") go(); });
})();
</script>
</body></html>"""


@app.route("/admin/login", methods=["POST"])
def admin_login():
    """Exchange the admin token (JSON body, never the URL) for an HttpOnly
    session cookie. Rate limited per IP; the supplied value is never logged."""
    ip = _client_ip()
    if not _check_rate_limit(ip, scope="admin-login", limit=_ADMIN_LOGIN_PER_MIN):
        _log.warning("ADMIN login rate-limited for %s", ip)
        return jsonify({"ok": False, "error": "Too many attempts — wait a minute and try again.",
                        "code": "rate_limited"}), 429
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    supplied = data.get("token")
    if not (isinstance(supplied, str) and len(supplied) <= 512 and _ct_eq(supplied, ADMIN_TOKEN)):
        _log.warning("ADMIN login failed from %s", ip)
        return jsonify({"ok": False, "error": "Invalid admin token.", "code": "bad_token"}), 401
    remember = data.get("remember") is True
    resp = jsonify({"ok": True})
    resp.set_cookie(ADMIN_COOKIE,
                    _admin_session_value(_ADMIN_REMEMBER_SECS if remember else _ADMIN_SESSION_SECS),
                    max_age=_ADMIN_REMEMBER_SECS if remember else None,   # None = session cookie
                    path=_ADMIN_COOKIE_PATH, secure=True, httponly=True, samesite="Strict")
    _log.info("ADMIN login from %s (remember=%s)", ip, remember)
    return resp


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    """Sign out: clear this browser's cookie and, when the signed-in admin asks
    (cookie + CSRF header, or X-Admin-Token), revoke every session on every
    device. An unauthenticated caller only clears its own cookie - it can never
    sign the admin out."""
    if _admin_ok():
        _admin_revoke_sessions()
        _log.info("ADMIN sign out (all sessions revoked) from %s", _client_ip())
    resp = jsonify({"ok": True})
    resp.delete_cookie(ADMIN_COOKIE, path=_ADMIN_COOKIE_PATH,
                       secure=True, httponly=True, samesite="Strict")
    return resp


@app.route("/admin/session")
def admin_session():
    """204 if this request is signed in as admin, else 401. Lets the gate page
    forward to the dashboard when a cross-site link arrived without the
    SameSite=Strict cookie. Reveals nothing beyond yes/no to the caller."""
    if not _admin_ok():
        return jsonify({"ok": False}), 401
    return "", 204


# ── Admin dashboard: data helpers ──────────────────────────────────────────────
# Alimne is free and the goal is sign-ups, so the dashboard leads with sign-ups,
# then the funnel (visit → anonymous guide → sign-in gate → account → first guide)
# and today's AI budget. The helpers below are PURE: plain lists/dicts in, plain
# dicts out, no Flask and no Supabase, so they are unit-tested directly
# (tests/test_admin_dashboard.py). _admin_load() does every database read;
# admin_page() only renders. Every value they are handed may be junk or hostile:
# the helpers are TOTAL (they skip a row they cannot read, they never raise), and
# admin_page guards every block a second time (_admin_safe, _admin_section), so
# no row, whatever is in it, can take the page down.
import datetime as _admin_dt     # module level on purpose: never a lazy import inside a request thread

_ADMIN_USERS_MAX     = 2000   # newest accounts loaded (table + day counts); the total is an exact count
_ADMIN_GATE_MAX      = 5000   # anonymous-device rows of the last 7 days
_ADMIN_ACTIVITY_MAX  = 2000   # per-account fair-use counters (who made a guide since free mode)
_ADMIN_LOAD_BUDGET_S = 12.0   # all the dashboard's reads share this; past it the rest say "could not load"
_ADMIN_USER_COLS = ("id,email,name,created_at,generations_count,last_used_at,referred_by,"
                    "referral_code,referral_paid,subscription_status,subscription_id,"
                    "subscription_period_end,tokens_remaining")
_ADMIN_DOW = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_ADMIN_MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# Sanity bounds for what a row may hold. A row is skipped past them, never trusted:
# one '9999-12-31' in a timestamp column would overflow the first sum made with it.
_ADMIN_TS_MIN  = _admin_dt.datetime(2000, 1, 1, tzinfo=_admin_dt.timezone.utc)   # no row of Alimne is older ...
_ADMIN_TS_MAX  = _admin_dt.datetime(2100, 1, 1, tzinfo=_admin_dt.timezone.utc)   # ... or this far ahead
_ADMIN_SKEW    = _admin_dt.timedelta(days=1)   # how far ahead of this server's clock a database time is still believed
_ADMIN_INT_MAX = 10 ** 15                      # no count of anything here is bigger

def _admin_now():
    """The dashboard's clock: aware UTC 'now' (one place, so tests can pin it)."""
    return _admin_dt.datetime.now(_admin_dt.timezone.utc)

def _admin_utc(now):
    """`now` as an aware UTC datetime (a naive one is taken as UTC)."""
    if now.tzinfo is None:
        return now.replace(tzinfo=_admin_dt.timezone.utc)
    return now.astimezone(_admin_dt.timezone.utc)

def _admin_ts(v):
    """A Supabase timestamp (or a 'YYYY-MM-DD' day) → aware UTC datetime, or None.
    Never raises, whatever it is given. A date outside 2000-2099 is not a date a
    row of Alimne can carry (corrupt, or edited by hand), so it is None as well:
    whoever asked then skips the row instead of doing sums with it."""
    try:
        if isinstance(v, _admin_dt.datetime):
            d = _admin_utc(v)
        elif not isinstance(v, str) or len(v) > 40:
            return None
        else:
            d = _parse_ts(v)
            d = d.astimezone(_admin_dt.timezone.utc) if d else None
        return d if (d is not None and _ADMIN_TS_MIN <= d < _ADMIN_TS_MAX) else None
    except (ValueError, OverflowError, OSError, TypeError):
        return None

def _admin_int(v, default=0):
    """A database number as an int; anything else (None, text, a mock, inf / nan, a
    value too big to be a count of anything) → default. Never raises."""
    if isinstance(v, bool):
        return default
    try:
        if isinstance(v, float):
            v = int(v)                    # inf and nan raise
        elif isinstance(v, str):
            v = int(v.strip())            # so does a number with thousands of digits
        elif not isinstance(v, int):
            return default
    except (ValueError, OverflowError):
        return default
    return v if -_ADMIN_INT_MAX <= v <= _ADMIN_INT_MAX else default

def _admin_is_count(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0

def _admin_rows(res):
    """The row dicts of a Supabase response ([] for anything unexpected)."""
    data = getattr(res, "data", None)
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []

def _admin_exact(res):
    """The exact row count of a response made with count='exact', or None."""
    c = getattr(res, "count", None)
    return c if _admin_is_count(c) else None

def _admin_day_label(d):
    return f"{_ADMIN_DOW[d.weekday()]} {d.day} {_ADMIN_MON[d.month - 1]}"

def _admin_window_start(now, days):
    """Midnight UTC that opens the `days`-day window ending today (today included)."""
    first = _admin_utc(now).date() - _admin_dt.timedelta(days=max(1, days) - 1)
    return _admin_dt.datetime(first.year, first.month, first.day, tzinfo=_admin_dt.timezone.utc)

def _admin_rate(num, den):
    """num / den, or None when there is nothing to divide by (or nothing that
    divides). Never raises."""
    try:
        return (num / den) if den and den > 0 else None
    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        return None

def _admin_pct(rate, cap=None):
    """A rate as text: '-' for no data (or for anything that is not a finite
    number), one decimal under 10%, and '100%+' past `cap` (a conversion between
    two separately counted things can pass 100%)."""
    if rate is None or isinstance(rate, bool):
        return "-"
    try:
        rate = float(rate)
    except (TypeError, ValueError, OverflowError):
        return "-"
    if rate != rate or rate in (float("inf"), float("-inf")):
        return "-"
    if cap is not None and rate > cap:
        return f"{int(cap * 100 + 0.5)}%+"
    p = max(0.0, rate) * 100
    if 0 < p < 10:
        t = f"{p:.1f}"
        return (t[:-2] if t.endswith(".0") else t) + "%"
    return f"{int(p + 0.5):,}%"

def _admin_signup_stats(users, now, days=14, total=None):
    """Sign-ups from users.created_at, by UTC day → {"today", "yesterday", "last7",
    "total", "series": [{"day", "label", "count", "today"}, ...] oldest first}.
    "last7" is today plus the six days before it (the last 7 bars of the series).
    `total` is the exact database count when known (the row list may be capped)."""
    today = _admin_utc(now).date()
    one = _admin_dt.timedelta(days=1)
    per_day, held = {}, 0
    for u in users or ():
        held += 1
        ts = _admin_ts(u.get("created_at")) if isinstance(u, dict) else None
        if ts is not None:
            per_day[ts.date()] = per_day.get(ts.date(), 0) + 1
    series = []
    for i in range(days - 1, -1, -1):
        d = today - one * i
        series.append({"day": d.isoformat(), "label": _admin_day_label(d),
                       "count": per_day.get(d, 0), "today": i == 0})
    return {"today": per_day.get(today, 0), "yesterday": per_day.get(today - one, 0),
            "last7": sum(per_day.get(today - one * i, 0) for i in range(7)),
            "total": max(held, total) if _admin_is_count(total) else held,
            "series": series}

def _admin_counter_now(row, now, window_hours=24):
    """(units used in the counter row's CURRENT window, seconds until it resets or
    None). anon_consume only zeroes a counter on its next use, so a row whose
    window is over still holds the old count: that is 0 now. A row whose window
    cannot be real (no start, a start that is not a date, a start well ahead of
    the clock) counts nothing. Never raises."""
    if not isinstance(row, dict):
        return 0, None
    start = _admin_ts(row.get("window_start"))
    if start is None:
        return 0, None
    now = _admin_utc(now)
    if start > now + _ADMIN_SKEW:
        return 0, None
    used = max(0, _admin_int(row.get("count")))
    try:
        left = (start + _admin_dt.timedelta(hours=window_hours) - now).total_seconds()
    except (OverflowError, TypeError, ValueError):
        return used, None             # a window the calendar cannot hold never ends: the count stands
    if left <= 0:
        return 0, None
    return used, int(left)

def _admin_gate_devices(rows, limit, now, days=7):
    """anon_usage rows 'gate:dev:<device>' → {"devices": anonymous devices that made
    at least 1 guide in the window, "at_gate": those that used all `limit` free
    guides, i.e. were shown the sign-in gate}. A row with count 0 was charged and
    refunded (no guide), so it is not a device that made one; a row last used at a
    time that is not one (or is ahead of the clock) is not in the window. A `limit`
    below 1 is read as 1 here; the funnel never asks when there is no free guide."""
    now = _admin_utc(now)
    start, ahead = _admin_window_start(now, days), now + _ADMIN_SKEW
    limit = max(1, _admin_int(limit, 3))
    devices = at_gate = 0
    for r in rows or ():
        if not isinstance(r, dict) or not str(r.get("key") or "").startswith("gate:dev:"):
            continue
        n, ts = _admin_int(r.get("count")), _admin_ts(r.get("last_at"))
        if n < 1 or ts is None or ts < start or ts > ahead:
            continue
        devices += 1
        if n >= limit:
            at_gate += 1
    return {"devices": devices, "at_gate": at_gate}

def _admin_user_activity(rows, now, window_hours=24):
    """Per-account fair-use counters (anon_usage rows 'fair:user:<uid>') →
    {uid: {"last_at": datetime or None, "recent": guides in the running 24 h window}}.
    In free mode nothing increments users.generations_count (only the old
    consume_token RPC did), so these counters are the one sign that an account
    has made a guide since Alimne went free.
    Only a row with count >= 1 is that sign. anon_consume creates the row before it
    knows whether the guide is allowed and anon_refund only takes the unit back, so
    an account whose one attempt was refused or failed keeps a row with count 0."""
    now, out = _admin_utc(now), {}
    ahead = now + _ADMIN_SKEW
    for r in rows or ():
        if not isinstance(r, dict):
            continue
        key = str(r.get("key") or "")
        uid = key[len("fair:user:"):] if key.startswith("fair:user:") else ""
        if uid and _admin_int(r.get("count")) >= 1:
            last = _admin_ts(r.get("last_at"))
            out[uid] = {"last_at": last if (last is not None and last <= ahead) else None,   # never a "last used" in the future
                        "recent": _admin_counter_now(r, now, window_hours)[0]}
    return out

def _admin_made_guide(user, activity):
    """True when this account has made at least one guide: the lifetime counter
    (token era) or a counted guide on its own fair-use counter (free mode)."""
    if not isinstance(user, dict):
        return False
    try:
        return (_admin_int(user.get("generations_count")) > 0
                or str(user.get("id") or "") in (activity or {}))
    except TypeError:
        return False

# Subscription states in which Stripe can still charge the customer → the words
# shown for them. The webhook writes 'active' (for active and trialing), 'past_due'
# and 'unpaid'; 'canceling' is a subscription set to end with its period.
# 'canceled' is over: there is nothing left to cancel.
_ADMIN_SUB_BILLING = {"active": "active", "trialing": "trialing", "canceling": "canceling",
                      "past_due": "past due", "unpaid": "unpaid"}

def _admin_legacy_sub(user):
    """The old paid plan of an account → {"status", "active", "legacy", "label"}.
    "legacy" is True for every account that may still be paying, so the owner can
    always find it and cancel it: a billing state (_ADMIN_SUB_BILLING), or a Stripe
    subscription id on file whose state is anything but 'canceled' (unknown is
    treated as live). "label" is the state in words, for the badge."""
    user = user if isinstance(user, dict) else {}
    status = str(user.get("subscription_status") or "free").strip().lower() or "free"
    legacy = status in _ADMIN_SUB_BILLING or (bool(user.get("subscription_id")) and status != "canceled")
    return {"status": status, "active": status == "active", "legacy": legacy,
            "label": _ADMIN_SUB_BILLING.get(status, status)}

def _admin_visits(visit_rows, now, days=7):
    """visit_stats rows ({"day": 'YYYY-MM-DD', "count": n}) → all-time, today, and
    the `days`-day window ending today."""
    today = _admin_utc(now).date()
    first = _admin_window_start(now, days).date()
    total = today_n = window = 0
    for r in visit_rows or ():
        if not isinstance(r, dict):
            continue
        c = max(0, _admin_int(r.get("count")))
        ts = _admin_ts(r.get("day"))
        total += c
        if ts is None:
            continue
        if ts.date() == today:
            today_n += c
        if first <= ts.date() <= today:
            window += c
    return {"total": total, "today": today_n, "window": window}

_ADMIN_FUNNEL_STEPS = (("visits", "Visits"), ("devices", "Anonymous devices"),
                       ("gate", "Reached the sign-in gate"), ("accounts", "New accounts"),
                       ("activated", "Made a guide"))

def _admin_funnel_blank(days=7):
    """The funnel with nothing in it: what the page falls back to (and shows as
    '-') if the funnel could not be computed. Static, so it cannot fail in turn."""
    return {"days": days, "gate_signup_rate": None, "gate_live": True, "gate_from_first": False,
            "steps": [{"key": key, "label": label, "value": 0, "na": False, "base": None, "rate": None}
                      for key, label in _ADMIN_FUNNEL_STEPS]}

def _admin_funnel(visit_rows, gate_rows, users, now, gate_limit, activity=None, days=7,
                  device_counts=None):
    """The sign-up funnel of the last `days` UTC days (today included):
    visits → anonymous devices that made a guide → devices that reached the sign-in
    gate → new accounts → new accounts that made a guide. Each step carries "rate",
    its conversion from the step named in "base" (the step before; None when that
    step is 0), and "gate_signup_rate" = new accounts / devices at the gate (None:
    no data). Devices and accounts are counted separately, so the rate is an estimate.
    `device_counts` = exact (devices, at_gate) when the row sample was cut short.
    A `gate_limit` of 0 (ANON_FREE_USES=0: sign in from the very first guide) sets
    "gate_from_first": nobody can make a guide without an account, so the two
    device steps are "na" (not applicable, no rate) and new accounts are measured
    against visits. A row with a date that is not one is in no window."""
    start = _admin_window_start(now, days)
    today = _admin_utc(now).date()
    visits = _admin_visits(visit_rows, now, days)["window"]
    from_first = _admin_int(gate_limit, 3) <= 0
    devices = at_gate = 0
    if not from_first:
        gate = _admin_gate_devices(gate_rows, gate_limit, now, days)
        devices, at_gate = gate["devices"], gate["at_gate"]
        try:
            exact_devices, exact_gate = device_counts
        except (TypeError, ValueError):   # None, or not a pair
            exact_devices = exact_gate = 0
        devices = max(devices, _admin_int(exact_devices))
        at_gate = max(at_gate, _admin_int(exact_gate))
    accounts = activated = 0
    for u in users or ():
        ts = _admin_ts(u.get("created_at")) if isinstance(u, dict) else None
        # the very days the sign-up cards count: the window's first day up to today
        if ts is None or ts < start or ts.date() > today:
            continue
        accounts += 1
        if _admin_made_guide(u, activity):
            activated += 1
    values = (visits, devices, at_gate, accounts, activated)
    steps, prev = [], None            # prev: (key, value) of the last step that applies
    for (key, label), value in zip(_ADMIN_FUNNEL_STEPS, values):
        na = from_first and key in ("devices", "gate")
        measured = prev is not None and not na
        steps.append({"key": key, "label": label, "value": value, "na": na,
                      "base": prev[0] if measured else None,
                      "rate": _admin_rate(value, prev[1]) if measured else None})
        if not na:
            prev = (key, value)
    return {"days": days, "steps": steps,
            "gate_signup_rate": None if from_first else _admin_rate(accounts, at_gate),
            "gate_live": devices > 0, "gate_from_first": from_first}

def _admin_budget(rows, now, global_limit, anon_limit=None, window_hours=24):
    """Today's AI budget from the 'fair:global' (and 'fair:global:anon') counter
    rows → {"used", "limit", "pct", "warn" (over 80%), "resets_in_s", "window_hours",
    "anon": the same for the anonymous slice, or None when there is no such cap}."""
    now = _admin_utc(now)
    by_key = {r["key"]: r for r in rows or () if isinstance(r, dict) and isinstance(r.get("key"), str)}
    def meter(key, limit):
        used, left = _admin_counter_now(by_key.get(key), now, window_hours)
        limit = max(0, _admin_int(limit))
        pct = _admin_rate(used, limit)
        return {"used": used, "limit": limit, "pct": pct,
                "warn": pct is not None and pct > 0.8, "resets_in_s": left}
    out = meter("fair:global", global_limit)
    out["anon"] = meter("fair:global:anon", anon_limit) if anon_limit is not None else None
    out["window_hours"] = window_hours
    return out

def _admin_gen_gate(g):
    """The live generation gate, read from whatever the module exposes (`g` is its
    globals) → {"running", "slots", "waiting", "wait_max"}, or None."""
    slots = g.get("_GEN_SLOTS")
    free = getattr(g.get("_gen_sem"), "_value", None)
    if not _admin_is_count(slots) or not _admin_is_count(free):
        return None
    waiting, wait_max = g.get("_gen_waiting"), g.get("_GEN_WAIT_MAX")
    return {"running": max(0, min(slots, slots - free)), "slots": slots,
            "waiting": len(waiting) if isinstance(waiting, (list, tuple)) else 0,
            "wait_max": wait_max if _admin_is_count(wait_max) else None}

def _admin_log_failure(what, exc):
    """Log a dashboard failure by type and place only. An exception's message can
    quote the value that broke it (an e-mail, a name): that stays out of the log."""
    tb, where = getattr(exc, "__traceback__", None), "?"
    while tb is not None:
        where = f"{os.path.basename(tb.tb_frame.f_code.co_filename)} line {tb.tb_lineno}"
        tb = tb.tb_next
    _log.warning("admin dashboard: could not compute %s: %s (%s)", what, type(exc).__name__, where)

def _admin_safe(errors, name, fn, fallback):
    """One block's computation, guarded a second time. The helpers skip bad rows
    themselves; if one raises all the same, the block is named in `errors` (the
    page then shows '-' and a small note for it, exactly as for a failed read),
    `fallback` is used, and everything else renders. Never raises."""
    try:
        return fn()
    except Exception as exc:
        _admin_log_failure(name, exc)
        errors.setdefault(name, type(exc).__name__)
        return fallback

def _admin_load(sb, now, gate_limit):
    """Every database read of the dashboard, through the service-role client `sb`.
    Read-only, column- and row-bounded, each in its own try/except (a failed block
    is named in "errors" and the page renders the rest), and all of them share
    _ADMIN_LOAD_BUDGET_S so a slow database cannot pin a web thread for long.
    The rows are taken out of each response inside the same guard."""
    out = {"users": [], "users_total": None, "activity_rows": [], "gate_rows": [], "gate_exact": None,
           "fair_rows": [], "visit_rows": [], "gens": [], "gens_total": 0, "leads": [], "errors": {}}
    if sb is None:
        return out
    t0 = time.monotonic()
    since = _admin_window_start(now, 7).strftime("%Y-%m-%dT%H:%M:%SZ")

    def read(name, fn):
        if time.monotonic() - t0 > _ADMIN_LOAD_BUDGET_S:
            out["errors"][name] = "the database is slow"
            return None
        try:
            return fn()
        except Exception as exc:
            _log.warning("admin dashboard: could not load %s: %s: %s", name, type(exc).__name__, exc)
            out["errors"][name] = type(exc).__name__
            return None

    def both(res):
        return _admin_rows(res), _admin_exact(res)

    def users():
        def run(cols):
            return (sb.table("users").select(cols, count="exact")
                      .order("created_at", desc=True).limit(_ADMIN_USERS_MAX).execute())
        try:
            return run(_ADMIN_USER_COLS)
        except Exception as exc:
            # Most likely a column of a later migration is missing: take what the table has.
            _log.info("admin dashboard: users column list refused (%s), reading all columns", type(exc).__name__)
            return run("*")
    res = read("users", lambda: both(users()))
    if res is not None:
        out["users"], out["users_total"] = res

    # count >= 1: a row left at 0 by a refused or refunded attempt is not a guide,
    # and must not take a place under the row cap either.
    res = read("activity", lambda: _admin_rows(
        sb.table("anon_usage").select("key,count,window_start,last_at")
          .like("key", "fair:user:%").gte("count", 1)
          .order("last_at", desc=True).limit(_ADMIN_ACTIVITY_MAX).execute()))
    if res is not None:
        out["activity_rows"] = res

    def gate():
        res = (sb.table("anon_usage").select("key,count,last_at", count="exact")
                 .like("key", "gate:dev:%").gte("last_at", since).gte("count", 1)
                 .order("last_at", desc=True).limit(_ADMIN_GATE_MAX).execute())
        rows, total = both(res)
        exact = None
        if total is not None and total > len(rows):
            # The response was capped (PostgREST max-rows): count the gate devices exactly.
            hit = (sb.table("anon_usage").select("key", count="exact")
                     .like("key", "gate:dev:%").gte("last_at", since).gte("count", gate_limit)
                     .limit(1).execute())
            exact = (total, _admin_exact(hit) or 0)
        return rows, exact
    # ANON_FREE_USES=0: no anonymous guide exists and the funnel shows the device
    # steps as not applicable, so there is nothing to read (and nothing that can fail).
    res = read("gate", gate) if gate_limit > 0 else None
    if res is not None:
        out["gate_rows"], out["gate_exact"] = res

    res = read("budget", lambda: _admin_rows(
        sb.table("anon_usage").select("key,count,window_start,last_at")
          .like("key", "fair:global%").limit(10).execute()))
    if res is not None:
        out["fair_rows"] = res

    res = read("visits", lambda: _admin_rows(
        sb.table("visit_stats").select("day,count").order("day", desc=True).limit(400).execute()))
    if res is not None:
        out["visit_rows"] = res

    res = read("generations", lambda: both(
        sb.table("usage_events").select("kind,source,country,city,created_at", count="exact")
          .order("created_at", desc=True).limit(1000).execute()))
    if res is not None:
        out["gens"], exact = res
        out["gens_total"] = exact if exact is not None else len(out["gens"])

    res = read("leads", lambda: _admin_rows(
        sb.table("leads").select("email,source,created_at")
          .order("created_at", desc=True).limit(500).execute()))
    if res is not None:
        out["leads"] = res
    return out

# ── Admin dashboard: rendering ─────────────────────────────────────────────────
# Static CSS / JS (no data in them). Everything dynamic is escaped where it is
# written: _he() for HTML text and attributes, _js() for onclick string arguments.
_ADMIN_CSS = r"""
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',system-ui,sans-serif;background:#050d1a;color:#e8f0ff;min-height:100vh}
  .topbar{display:flex;align-items:center;justify-content:space-between;gap:.6rem;flex-wrap:wrap;padding:1rem 2rem;
          background:#0a1628;border-bottom:1px solid #1a3a6e;position:sticky;top:0;z-index:10}
  .topbar h1{font-size:1rem;font-weight:700;display:flex;align-items:center;gap:.6rem;flex-wrap:wrap}
  .badge{background:#4f8ef7;color:#fff;padding:2px 10px;border-radius:20px;font-size:12px}
  .badge.red{background:#dc2626}
  .actions{display:flex;gap:.5rem;flex-wrap:wrap}
  .btn{padding:6px 14px;border-radius:8px;border:none;cursor:pointer;font-size:13px;font-weight:600;transition:opacity .2s}
  .btn:hover{opacity:.8}
  .btn-red{background:#dc2626;color:#fff}
  .btn-green{background:#16a34a;color:#fff}
  .btn-gray{background:#1e3a5f;color:#cfe0ff}
  .wrap{overflow-x:auto}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{background:#0f2040;padding:10px 12px;text-align:left;font-weight:600;color:#8aa0c8;
     border-bottom:1px solid #1a3a6e;white-space:nowrap}
  th.sort{cursor:pointer;user-select:none}
  th.sort span{opacity:.35;font-size:10px}
  th.c,td.c{text-align:center}
  td{padding:9px 12px;border-bottom:1px solid #0d1e35;vertical-align:middle}
  tr:hover td{background:#0a1e38}
  .empty{padding:3rem;text-align:center;color:#4a5f80;font-size:0.9rem}
  #toast{position:fixed;bottom:1.5rem;right:1.5rem;background:#16a34a;color:#fff;
         padding:.6rem 1.2rem;border-radius:8px;font-size:13px;display:none;z-index:100}
  .sec{margin:1.5rem 2rem}
  .sec>h3{margin:0 0 .6rem;color:#e8f0ff;font-size:1rem;display:flex;align-items:center;gap:.5rem;flex-wrap:wrap}
  .sec>h3 small{font-weight:400;color:#6b7fa8;font-size:.78rem}
  .pill{padding:2px 10px;border-radius:20px;font-size:12px;font-weight:400;background:#0f2040;color:#8aa0c8}
  .pill.blue{background:#4f8ef7;color:#fff}
  .pill.green{background:#065f46;color:#6ee7b7}
  .pill.amber{background:#78350f;color:#fcd34d}
  .pill.violet{background:#4c1d95;color:#ddd6fe}
  .pill.pink{background:#831843;color:#fbcfe8}
  .cards{display:flex;gap:.75rem;flex-wrap:wrap;align-items:stretch}
  .card{background:#0a1628;border:1px solid #1a3a6e;border-radius:12px;padding:.75rem 1.1rem;min-width:140px}
  .card .lbl{color:#8aa0c8;font-size:11px;font-weight:700;letter-spacing:.6px;text-transform:uppercase}
  .card .num{font-size:1.7rem;font-weight:800;color:#e8f0ff;line-height:1.2}
  .card .sub{color:#8aa0c8;font-size:11px;line-height:1.45}
  .card.hero{background:linear-gradient(135deg,#0a2f3f,#07213a);border-color:#16556b}
  .card.hero .lbl{color:#6ee7b7}
  .card.sky .num{color:#7cc4ff}
  .card.mint .num{color:#6ee7b7}
  .card.cyan{background:linear-gradient(135deg,#04283a,#062033);border-color:#0e7490}
  .card.cyan .lbl{color:#67e8f9}
  .card.violet{background:linear-gradient(135deg,#1a1035,#0f0a28);border-color:#6d28d9}
  .card.violet .lbl{color:#c4b5fd}
  .card.lilac .num{color:#a78bfa}
  .card.pink .num{color:#f472b6}
  .card.na{border-style:dashed}
  .card.na .num,.card.na .lbl{color:#6b7fa8}
  .note{color:#8aa0c8;font-size:12px;line-height:1.5;margin-top:.55rem;max-width:900px}
  .note.err{color:#fca5a5}
  .muted{color:#6b7fa8}
  .kpis{display:grid;grid-template-columns:repeat(2,minmax(140px,1fr));gap:.75rem;flex:1 1 320px;max-width:460px}
  .chart{flex:2 1 420px;max-width:720px;min-width:280px;display:flex;flex-direction:column}
  .bars{display:flex;align-items:flex-end;gap:5px;flex:1 1 auto;min-height:118px;margin:.35rem 0}
  .bar{flex:1 1 0;min-width:0;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center}
  .bar .n{font-size:10px;color:#8aa0c8;line-height:1;margin-bottom:3px;min-height:10px}
  .bar .fill{display:block;width:100%;max-width:34px;background:#4f8ef7;border-radius:4px 4px 0 0}
  .bar .d{font-size:10px;color:#6b7fa8;line-height:1;margin-top:4px}
  .bar.zero .fill{background:#1a3a6e}
  .bar.today .fill{background:#6ee7b7}
  .bar.today .n,.bar.today .d{color:#6ee7b7;font-weight:700}
  .funnel{display:flex;gap:.4rem;flex-wrap:wrap;align-items:stretch}
  .funnel .card{flex:1 1 170px;max-width:250px}
  .funnel .arrow{align-self:center;color:#3b5b8c;font-size:1.1rem}
  .conv{display:inline-block;margin-top:.4rem;padding:1px 8px;border-radius:20px;background:#0f2040;
        color:#7cc4ff;font-size:11px;font-weight:600}
  .stepno{display:inline-block;min-width:16px;height:16px;line-height:16px;text-align:center;border-radius:50%;
          background:#1a3a6e;color:#cfe0ff;font-size:10px;margin-right:5px;letter-spacing:0}
  .meter{height:12px;background:#0f2040;border:1px solid #1a3a6e;border-radius:8px;overflow:hidden;margin:.45rem 0 .35rem}
  .meter .fill{display:block;height:100%;background:#4f8ef7}
  .meter.warn .fill{background:#f59e0b}
  .meter.full .fill{background:#dc2626}
  .card.wide{flex:2 1 380px;max-width:640px}
  .card.mid{flex:1 1 260px;max-width:400px}
  .row{display:flex;align-items:baseline;justify-content:space-between;gap:.75rem;flex-wrap:wrap}
  .row .num{display:inline-block}
  .card .warntxt,.warntxt{color:#fcd34d;font-weight:600}
  .card .num.warntxt{font-weight:800}
  .tools{display:flex;gap:.6rem;margin-bottom:.6rem;flex-wrap:wrap;align-items:center}
  .tools input[type=text]{background:#050d1a;border:1px solid #1a3a6e;color:#e8f0ff;padding:.45rem .7rem;
        border-radius:8px;font-size:13px;min-width:220px}
  .tools label{display:flex;gap:.4rem;align-items:center;color:#8aa0c8;font-size:13px;cursor:pointer}
  .box{overflow-x:auto;border:1px solid #16233f;border-radius:10px}
  td.clip{max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .mini{background:#7f1d1d;color:#fecaca;border:none;padding:3px 9px;border-radius:6px;cursor:pointer;font-size:12px}
  .mini.blue{background:#1e3a5f;color:#cfe0ff}
  @media (max-width:720px){
    .sec{margin:1rem .75rem}
    .topbar{padding:.75rem}
    .funnel .arrow{display:none}
    .card{flex:1 1 140px}
    .kpis{max-width:none}
  }
"""

_ADMIN_JS = r"""
// Auth rides on the HttpOnly session cookie, which the browser attaches to these
// same-origin requests by itself; the admin token never reaches this page. The
// server requires the fixed X-Requested-With header on every cookie-authed POST.
try { localStorage.removeItem("alimne_admin_token"); } catch (e) {}   // legacy copy
const ADMIN_HEADERS = {"Content-Type":"application/json","X-Requested-With":"alimne-admin"};
function toast(msg, color="#16a34a"){
  const t = document.getElementById("toast");
  t.textContent = msg; t.style.background = color; t.style.display = "block";
  setTimeout(()=>t.style.display="none", 2500);
}
// POST an admin action. Resolves to the Response, or null when the session has
// expired (cookie cleared, or the admin token was rotated) — then it sends you to sign in.
async function adminPost(url, body){
  const r = await fetch(url, {method:"POST", credentials:"same-origin", headers:ADMIN_HEADERS,
                               body: JSON.stringify(body || {})});
  if (r.status === 401) {
    toast("Session expired — sign in again. · انتهت الجلسة — سجّل الدخول مرة أخرى.", "#dc2626");
    setTimeout(()=>{ location.href = "/admin"; }, 1800);
    return null;
  }
  return r;
}
async function blockIp(ip){
  if(!confirm("Block " + ip + "?\nThis will 403 all their requests immediately.")) return;
  const r = await adminPost("/admin/block", {ip});
  if(r && r.ok){ toast("⛔ Blocked: " + ip, "#dc2626"); setTimeout(()=>location.reload(),1200); }
}
async function unblock(ip){
  const r = await adminPost("/admin/unblock", {ip});
  if(r && r.ok){ toast("✓ Unblocked: " + ip); setTimeout(()=>location.reload(),1200); }
}
async function clearLog(){
  if(!confirm("Clear all visitor log entries?")) return;
  const r = await adminPost("/admin/clear");
  if(r && r.ok){ toast("🗑 Log cleared"); setTimeout(()=>location.reload(),1200); }
}

// ── Users: search / filter / sort / CSV / actions ────────────────────────────
function subFilter(){
  var q = (document.getElementById("subSearch").value || "").toLowerCase().trim();
  var only = document.getElementById("payingOnly").checked;
  var rows = document.querySelectorAll("#subBody tr.subrow");
  var shown = 0;
  rows.forEach(function(r){
    var okQ = !q || r.dataset.email.indexOf(q) >= 0 || r.dataset.name.indexOf(q) >= 0 || (r.dataset.refby||"").indexOf(q) >= 0;
    var okP = !only || r.dataset[ADMIN_CFG.payAttr] === "1";
    var vis = okQ && okP;
    r.style.display = vis ? "" : "none";
    if (vis) shown++;
  });
  var el = document.getElementById("subShown");
  if (el) el.textContent = shown + " shown";
}
var _subSort = {joined: -1};   // the server sends the newest account first
function subSort(key, numeric){
  // Numbers and dates start with the biggest / newest; text starts at A.
  var first = (numeric || key === "joined" || key === "lastused") ? -1 : 1;
  var dir = _subSort[key] ? -_subSort[key] : first; _subSort = {}; _subSort[key] = dir;
  var body = document.getElementById("subBody");
  var rows = Array.prototype.slice.call(body.querySelectorAll("tr.subrow"));
  rows.sort(function(a,b){
    var va = a.dataset[key] || "", vb = b.dataset[key] || "";
    if (numeric) return ((parseFloat(va)||0) - (parseFloat(vb)||0)) * dir;
    return (va < vb ? -1 : (va > vb ? 1 : 0)) * dir;
  });
  rows.forEach(function(r){ body.appendChild(r); });
}
function csvCell(c){
  c = String(c == null ? "" : c);
  if (/^[=+\-@\t\r]/.test(c)) c = "'" + c;   // a spreadsheet must never run a cell as a formula
  return '"' + c.replace(/"/g,'""') + '"';
}
function subExportCSV(){
  var rows = document.querySelectorAll("#subBody tr.subrow");
  var out = [ADMIN_CFG.csvHead.map(csvCell).join(",")];
  rows.forEach(function(r){
    if (r.style.display === "none") return;
    out.push(ADMIN_CFG.csvKeys.map(function(k){
      // data-name is the lower-cased search key: export the name as it is shown (2nd cell)
      return csvCell(k === "name" ? r.cells[1].textContent : r.dataset[k]);
    }).join(","));
  });
  var blob = new Blob([out.join("\n")], {type:"text/csv"});
  var a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "alimne-users.csv";
  document.body.appendChild(a); a.click(); a.remove();
  toast("⬇ Exported " + (out.length - 1) + " rows");
}
async function cancelSub(uid, email){
  if (!confirm("Cancel subscription for " + email + "?\nStripe subscriptions cancel at period end (they keep access until then).")) return;
  var r = await adminPost("/admin/user/cancel", {user_id: uid});
  if (!r) return;
  var d = await r.json().catch(function(){ return {}; });
  if (r.ok) { toast(d.canceled_at_period_end ? "✓ Cancels at period end" : "✓ Set to free"); setTimeout(function(){ location.reload(); }, 900); }
  else { toast("✗ " + (d.error || "failed"), "#dc2626"); }
}
async function signOut(){
  // Server clears the HttpOnly cookie (page JS can't); then back to the sign-in gate.
  try { await fetch("/admin/logout", {method:"POST", credentials:"same-origin", headers:ADMIN_HEADERS, body:"{}"}); } catch(e) {}
  try { localStorage.removeItem("alimne_admin_token"); } catch(e) {}
  location.href = "/admin";
}
subFilter();
"""

# Legacy (token) mode only: the "+ Tokens" action. Left out of the page in free mode.
_ADMIN_JS_TOKENS = r"""
async function grantTokens(uid, email){
  var v = prompt("Grant tokens to " + email + "\n(use a negative number to deduct):", "30");
  if (v === null) return;
  var amount = parseInt(v, 10);
  if (!amount) { toast("Enter a non-zero number", "#dc2626"); return; }
  var r = await adminPost("/admin/user/grant", {user_id: uid, amount: amount});
  if (!r) return;
  var d = await r.json().catch(function(){ return {}; });
  if (r.ok) { toast("✓ " + email + ": " + d.tokens_remaining + " tokens"); setTimeout(function(){ location.reload(); }, 900); }
  else { toast("✗ " + (d.error || "failed"), "#dc2626"); }
}
"""

def _admin_card(label, value, sub="", key="", cls="", extra=""):
    """One stat card. label / value / sub are escaped here; `extra` is trusted
    markup built by the caller (already escaped)."""
    k = f' data-num="{_he(key)}"' if key else ""
    return (f'<div class="card{" " + cls if cls else ""}"><div class="lbl">{_he(label)}</div>'
            f'<div class="num"{k}>{_he(value)}</div>'
            + (f'<div class="sub">{_he(sub)}</div>' if sub else "") + extra + "</div>")

def _admin_err_note(errors, name, what):
    """A small inline 'could not load' note for one block, or ''. Only the error's
    type name is shown: the message itself stays in the server log."""
    if name not in errors:
        return ""
    return (f'<p class="note err" data-err="{_he(name)}">Could not load {_he(what)} '
            f'({_he(errors[name])}). The rest of the page is unaffected; details are in the server log.</p>')

def _admin_skipped_note(errors, skipped, name, what="row"):
    """A small note for the rows of one table that could not be shown, or ''."""
    n = skipped.get(name, 0)
    if not n:
        return ""
    return (f'<p class="note err" data-err="{_he(name)}">{n:,} {_he(what)}{"" if n == 1 else "s"} could not be shown '
            f'({_he(errors.get(name, "error"))}). The rest of the page is unaffected; details are in the server log.</p>')

def _admin_section(sec_id, title, build):
    """One section's markup, guarded a second time: if building it raises, a short
    note takes its place (same id, so the page keeps its shape) and the rest of
    the page renders. Never raises."""
    try:
        return build()
    except Exception as exc:
        _admin_log_failure(f"section {sec_id}", exc)
        return (f'\n<section class="sec" id="{_he(sec_id)}">\n  <h3>{_he(title)}</h3>\n'
                f'  <p class="note err" data-err="{_he(sec_id)}">Could not show this section '
                f'({_he(type(exc).__name__)}). The rest of the page is unaffected; details are in the server log.</p>\n'
                f'</section>')

def _admin_n(n, errors=(), *blocks):
    """A count as text ('1,234'), or '-' when a block it is made from could not
    be loaded: an unknown number must never look like a real 0."""
    return "-" if any(b in errors for b in blocks) else f"{n:,}"

def _admin_date(v):
    """'YYYY-MM-DD' (UTC) for a timestamp, or '' when it is not one."""
    ts = _admin_ts(v)
    return ts.strftime("%Y-%m-%d") if ts else ""

def _admin_when(v):
    """'YYYY-MM-DD HH:MM' (UTC) for a timestamp, or '—'."""
    ts = _admin_ts(v)
    return ts.strftime("%Y-%m-%d %H:%M") if ts else "—"

def _admin_duration(seconds):
    """'5 h 12 min' for a number of seconds ('—' for anything that is not one)."""
    try:
        m = max(0, int(seconds)) // 60
    except (TypeError, ValueError, OverflowError):
        return "—"
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"

def _admin_signups_html(stats, errors, lead_cards=""):
    """Section 1: the sign-up headline cards and the 14-day bar chart (plain
    HTML/CSS bars; the day and the count are in each bar's title)."""
    series = stats["series"]
    peak = max([p["count"] for p in series] + [1])
    bars = ""
    for p in series:
        n = p["count"]
        cls = "bar" + ("" if n else " zero") + (" today" if p["today"] else "")
        title = f'{p["label"]}: {n:,} sign-up{"" if n == 1 else "s"}'
        bars += (f'<div class="{cls}" data-day="{_he(p["day"])}" title="{_he(title)}">'
                 f'<span class="n">{n if n else ""}</span>'
                 f'<span class="fill" style="height:{max(2, int(n * 80 / peak + 0.5))}px"></span>'
                 f'<span class="d">{_he(p["day"][8:].lstrip("0"))}</span></div>')
    span = f'{series[0]["label"]} to {series[-1]["label"]}' if series else ""
    def n(key):
        return _admin_n(stats[key], errors, "users", "signups")
    cards = (lead_cards
             + _admin_card("Sign-ups today", n("today"), "since 00:00 UTC", "signups-today", "hero")
             + _admin_card("Yesterday", n("yesterday"), "the full UTC day", "signups-yesterday", "sky")
             + _admin_card("Last 7 days", n("last7"), "today + the 6 days before", "signups-7d", "sky")
             + _admin_card("Total accounts", n("total"), "all time", "signups-total"))
    return f"""
<section class="sec" id="sec-signups">
  <h3>🚀 Sign-ups <small>days are UTC days</small></h3>
  {_admin_err_note(errors, "users", "the accounts")}
  {_admin_err_note(errors, "signups", "the sign-up counts")}
  <div class="cards">
    <div class="kpis">{cards}</div>
    <div class="card chart">
      <div class="lbl">Sign-ups per day · last {len(series)} days (UTC)</div>
      <div class="bars">{bars}</div>
      <div class="sub">{_he(span)} · today is the green bar · hover a bar for the day and the count</div>
    </div>
  </div>
</section>"""

_ADMIN_STEP_SUBS = {
    "visits":    "page loads (home page + shared guides)",
    "devices":   "made at least 1 guide without an account",
    "gate":      "devices that used all {limit} free guides",
    "accounts":  "signed up",
    "activated": "new accounts that made at least 1 guide",
}
# how a step's conversion reads, by the step it is measured from (its "base")
_ADMIN_STEP_OF = {"visits": "of visits", "devices": "of those devices",
                  "gate": "of gate devices", "accounts": "of new accounts"}
_ADMIN_GATE_FROM_FIRST = "sign-in required from the first guide"
# the blocks each step is made from: the funnel computation itself, and the
# database reads behind it (see "errors" in _admin_load and _admin_safe)
_ADMIN_STEP_BLOCKS = {"visits": ("funnel", "visits"), "devices": ("funnel", "gate"), "gate": ("funnel", "gate"),
                      "accounts": ("funnel", "users"), "activated": ("funnel", "users", "activity")}

def _admin_funnel_html(funnel, gate_limit, errors, totals_cards):
    """Section 2: the 7-day funnel, the gate → sign-up rate with its caveat, and
    the all-time cards under it. A step whose data could not be loaded shows '-';
    a step that does not apply (ANON_FREE_USES=0, see _admin_funnel) shows 'n/a'."""
    steps, steps_html = funnel["steps"], ""
    from_first = funnel["gate_from_first"]
    # a step that does not apply is made from no data, so it cannot be "not loaded"
    lost = {s["key"]: not s["na"] and any(b in errors for b in _ADMIN_STEP_BLOCKS[s["key"]]) for s in steps}
    for i, s in enumerate(steps):
        key, conv = s["key"], ""
        if i:
            steps_html += '<span class="arrow">→</span>'
        if s["na"]:
            num, sub, cls = "n/a", f"not applicable: {_ADMIN_GATE_FROM_FIRST}", " na"
        else:
            num = "-" if lost[key] else format(s["value"], ",")
            sub = _ADMIN_STEP_SUBS[key].format(limit=gate_limit)
            cls = " hero" if key == "accounts" else ""
            if i:
                # conversion from the step it is measured from; "-" alone when there is nothing to divide by
                base = s["base"]
                rate = None if (lost[key] or lost.get(base, False)) else s["rate"]
                of = f' {_ADMIN_STEP_OF[base]}' if (rate is not None and base in _ADMIN_STEP_OF) else ""
                conv = (f'<div class="conv" data-conv="{_he(key)}">'
                        f'{_he(_admin_pct(rate, cap=1.0) + of)}</div>')
        steps_html += (f'<div class="card{cls}">'
                       f'<div class="lbl"><span class="stepno">{i + 1}</span>{_he(s["label"])}</div>'
                       f'<div class="num" data-num="funnel-{_he(key)}">{num}</div>'
                       f'<div class="sub">{_he(sub)}</div>'
                       f'{conv}</div>')
    if from_first:
        gate_note = (f'<p class="note" data-note="gate-from-first">The gate is set to <b>{_ADMIN_GATE_FROM_FIRST}</b> '
                     f'(ANON_FREE_USES=0): a visitor cannot make a guide without an account, so the two '
                     f'anonymous-device steps do not apply and new accounts are measured against visits.</p>')
        rate_card = _admin_card("Gate → sign-up", "n/a", f"not applicable: {_ADMIN_GATE_FROM_FIRST}",
                                "gate-signup-rate", "na")
        estimate_note = ""
    else:
        gate_note = _admin_err_note(errors, "gate", "the anonymous-device counters, so the two device steps and "
                                                    "the gate → sign-up rate show no data")
        if not gate_note and not funnel["gate_live"]:
            gate_note = (f'<p class="note" data-note="gate-not-live">No anonymous device has been counted in the last '
                         f'{funnel["days"]} days: sign-in gate data starts when the {gate_limit}-guide gate goes live.</p>')
        rate = None if (lost["gate"] or lost["accounts"]) else funnel["gate_signup_rate"]
        rate_card = _admin_card("Gate → sign-up", _admin_pct(rate, cap=1.0),
                                f'{_admin_n(steps[3]["value"], errors, "users", "funnel")} new accounts ÷ '
                                f'{_admin_n(steps[2]["value"], errors, "gate", "funnel")} devices at the gate',
                                "gate-signup-rate", "hero")
        estimate_note = ('<p class="note">Gate → sign-up is an estimate: devices and accounts are counted separately '
                         '(one person can use several devices, and people also sign up without ever reaching the '
                         'gate), so it is capped at 100% on screen.</p>')
    return f"""
<section class="sec" id="sec-funnel">
  <h3>🔻 Funnel <small>last {funnel["days"]} days (UTC days, today included)</small></h3>
  {_admin_err_note(errors, "funnel", "the funnel")}
  {_admin_err_note(errors, "visits", "the visit counts")}
  <div class="funnel">{steps_html}</div>
  {gate_note}
  <div class="cards" style="margin-top:.75rem">
    {rate_card}
    {totals_cards}
  </div>
  {estimate_note}
</section>"""

def _admin_budget_html(budget, gen_gate, errors, free):
    """Section 3: today's AI budget (the fair:global counter against
    FAIR_GLOBAL_DAILY), the anonymous slice, and the live generation gate."""
    lost = "budget" in errors
    def meter(m, name, label, about):
        pct = None if lost else m["pct"]
        full = pct is not None and pct >= 1
        warn = m["warn"] and not lost
        width = 0 if pct is None else max(0.0, min(100.0, pct * 100))
        cls = "meter" + (" warn" if warn else "") + (" full" if full else "")
        state = ""
        if full:
            state = '<div class="sub warntxt">Used up: new guides are refused until the window resets.</div>'
        elif warn:
            state = '<div class="sub warntxt">Over 80% of the limit.</div>'
        if lost:
            resets = "not loaded"
        elif m["resets_in_s"] is not None:
            resets = f'window resets in {_admin_duration(m["resets_in_s"])}'
        else:
            resets = "no guide counted in the current window"
        key = "budget" if name == "global" else "budget-anon"
        return (f'<div class="lbl">{_he(label)}</div>'
                f'<div class="row"><div><span class="num" data-num="{key}-used">{_admin_n(m["used"], errors, "budget")}</span> '
                f'<span class="sub">of {m["limit"]:,}</span></div>'
                f'<div class="num{" warntxt" if warn else ""}" data-num="{key}-pct">{_he(_admin_pct(pct))}</div></div>'
                f'<div class="{cls}" data-meter="{name}"><span class="fill" style="width:{width:.1f}%"></span></div>'
                f'<div class="sub">{_he(resets)} · {_he(about)}</div>{state}')
    wh = budget["window_hours"]
    main = meter(budget, "global", f"Guides in the current {wh} h window", "the limit is FAIR_GLOBAL_DAILY")
    anon = ""
    if budget["anon"] is not None:
        anon = ('<div class="card mid">'
                + meter(budget["anon"], "anon", "Anonymous share of it", "visitors without an account")
                + "</div>")
    live = ""
    if gen_gate is not None:
        busy = gen_gate["running"] >= gen_gate["slots"] > 0
        wait_max = f' (room for {gen_gate["wait_max"]})' if gen_gate["wait_max"] is not None else ""
        live = (f'<div class="card mid"><div class="lbl">Generating right now</div>'
                f'<div class="row"><div><span class="num{" warntxt" if busy else ""}" data-num="gen-running">'
                f'{gen_gate["running"]} / {gen_gate["slots"]}</span> <span class="sub">slots running</span></div>'
                f'<div><span class="num" data-num="gen-waiting">{gen_gate["waiting"]}</span> '
                f'<span class="sub">waiting{_he(wait_max)}</span></div></div>'
                f'<div class="sub">Live, this server only. When every slot is busy a new request waits, then gets "busy".</div></div>')
    mode_note = "" if free else ('<p class="note">Token mode is on (ALIMNE_FREE_MODE=0): the fair-use counters and '
                                 'the generation queue are switched off, so these meters do not move.</p>')
    return f"""
<section class="sec" id="sec-budget">
  <h3>🔋 Today's AI budget + capacity <small>a {wh} h window that starts with its first guide</small></h3>
  {_admin_err_note(errors, "budget", "the budget counters")}
  {_admin_err_note(errors, "capacity", "the live generation slots")}
  <div class="cards">
    <div class="card wide">{main}</div>
    {anon}
    {live}
  </div>
  {mode_note}
</section>"""


@app.route("/admin")
def admin_page():
    if request.query_string:
        # Old bookmarks and the old gate put the token in ?token=. Never honour
        # it (query strings are logged) and drop it from the address bar/history.
        return redirect("/admin", 302)
    if not _admin_ok():
        return ADMIN_GATE_HTML, 401
    with _vis_lock:
        vis_copy     = list(_visitors)
        blocked_copy = set(_blocked_ips)

    def flag(cc):
        # Convert 2-letter country code to emoji flag
        if not cc or len(cc) != 2:
            return ""
        return "".join(chr(0x1F1E6 + ord(c) - ord('A')) for c in cc.upper())

    # Escaper for values dropped into onclick="fn('x')". The browser HTML-decodes
    # the attribute BEFORE the JS parser sees it, so HTML-escaping first (the old
    # way: ' -> &#39;) handed JS a real ' that closed the string. Now JS-escape
    # first: everything but ASCII letters/digits and " .:-_@+" becomes \xHH or
    # \uHHHH, so no quote, backslash, line break or markup survives; the final
    # HTML-escape is then a no-op kept as a belt.
    def _js(s):
        out = []
        for ch in str(s):
            o = ord(ch)
            if (o < 0x80 and ch.isalnum()) or ch in " .:-_@+":
                out.append(ch)
            elif o < 0x100:
                out.append("\\x%02x" % o)
            elif o < 0x10000:
                out.append("\\u%04x" % o)
            else:                      # astral: a UTF-16 surrogate pair, as JS strings are
                o -= 0x10000
                out.append("\\u%04x\\u%04x" % (0xD800 + (o >> 10), 0xDC00 + (o & 0x3FF)))
        return _he("".join(out))

    rows = ""
    for v in vis_copy:
        blocked = v["ip"] in blocked_copy
        # All visitor fields below are attacker-controlled (UA/path/headers, or
        # geo derived from a spoofable IP) — escape every one to prevent stored XSS.
        ip_h    = _he(v.get("ip", ""))
        ip_js   = _js(v.get("ip", ""))
        loc_parts = [p for p in [v.get("city",""), v.get("region",""), v.get("country","")] if p]
        location  = _he(", ".join(loc_parts)) if loc_parts else "—"
        map_link  = ""
        if v.get("lat") and v.get("lon"):
            map_link = f'<a href="https://maps.google.com/?q={_he(v["lat"])},{_he(v["lon"])}" target="_blank" rel="noopener noreferrer" style="color:#4f8ef7;font-size:11px">📍 map</a>'
        block_btn = (
            f'<button onclick="unblock(\'{ip_js}\')" '
            f'style="background:#16a34a;color:#fff;border:none;padding:3px 10px;border-radius:6px;cursor:pointer;font-size:12px">✓ Unblock</button>'
            if blocked else
            f'<button onclick="blockIp(\'{ip_js}\')" '
            f'style="background:#dc2626;color:#fff;border:none;padding:3px 10px;border-radius:6px;cursor:pointer;font-size:12px">⛔ Block</button>'
        )
        row_style = "background:#1a0a0a" if blocked else ""
        rows += f"""
          <tr style="{row_style}">
            <td style="color:#8aa0c8;white-space:nowrap">{_he(v.get('time',''))}</td>
            <td><b style="{'color:#f87171' if blocked else ''}">{ip_h}</b>
                {'<span style="background:#7f1d1d;color:#fca5a5;padding:1px 6px;border-radius:4px;font-size:10px;margin-left:4px">BLOCKED</span>' if blocked else ''}
            </td>
            <td>{_he(v.get('country','—'))}</td>
            <td>{location} {map_link}</td>
            <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#8aa0c8">{_he(v.get('isp','—'))}</td>
            <td style="color:#6b7fa8">{_he(v.get('path',''))}</td>
            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;color:#4a5f80">{_he(v.get('ua',''))}</td>
            <td>{block_btn}</td>
          </tr>"""

    blocked_section = ""
    if blocked_copy:
        blocked_rows = "".join(
            f'<tr><td style="color:#f87171;padding:6px 12px">{_he(ip)}</td>'
            f'<td><button onclick="unblock(\'{_js(ip)}\')" style="background:#16a34a;color:#fff;border:none;padding:2px 10px;border-radius:6px;cursor:pointer;font-size:12px">Unblock</button></td></tr>'
            for ip in sorted(blocked_copy)
        )
        blocked_section = f"""
        <div style="margin:1.5rem 2rem;background:#1a0a0a;border:1px solid #7f1d1d;border-radius:10px;padding:1rem">
          <h3 style="margin:0 0 0.75rem;color:#f87171;font-size:0.95rem">⛔ Blocked IPs ({len(blocked_copy)})</h3>
          <table style="border-collapse:collapse;font-size:13px"><tbody>{blocked_rows}</tbody></table>
        </div>"""

    # ── Data: every Supabase read is in _admin_load (bounded, each in its own try) ──
    now    = _admin_now()
    g      = globals()
    free   = bool(FREE_MODE)
    # Knobs of the sign-in gate / fair use, read defensively: the gate ships separately.
    # 0 is a real setting (sign in from the very first guide), never rounded up to 1.
    gate_limit = max(0, _admin_int(g.get("ANON_FREE_USES", 3), 3))
    sb_note = ""
    try:
        sb = _get_sb()
        if sb is None:
            sb_note = ('<p class="note" style="margin:0">Supabase is not configured on this server (dev mode): '
                       'the numbers below are empty.</p>')
    except Exception as exc:
        _log.warning("admin dashboard: Supabase client unavailable: %s: %s", type(exc).__name__, exc)
        sb = None
        sb_note = ('<p class="note err" style="margin:0">Could not load anything from the database: its client '
                   'did not start (details are in the server log).</p>')
    data   = _admin_load(sb, now, gate_limit)
    errors = data["errors"]
    skipped = {}                       # table → how many of its rows could not be shown
    today  = _admin_utc(now).date()

    def row_failed(name, exc):
        """One row of a table could not be rendered: leave it out, count it, say so."""
        if name not in skipped:
            _admin_log_failure(name, exc)
            errors.setdefault(name, type(exc).__name__)
        skipped[name] = skipped.get(name, 0) + 1

    # ── Numbers. The helpers are total over bad rows (they skip them); every call is
    # guarded a second time all the same (_admin_safe), so a row that slips through
    # costs one block its numbers ("-" and a small note), never the page.
    users = data["users"]
    _epoch = _admin_dt.datetime(1970, 1, 1, tzinfo=_admin_dt.timezone.utc)
    _admin_safe({}, "the account order",                      # newest first; the query already sends them so
                lambda: users.sort(key=lambda u: _admin_ts(u.get("created_at")) or _epoch, reverse=True), None)
    window_h = max(1, _admin_int(g.get("_FAIR_WINDOW_HOURS", 24), 24))   # the fair-use counters' window
    activity = _admin_safe(errors, "activity",
                           lambda: _admin_user_activity(data["activity_rows"], now, window_h), {})
    stats    = _admin_safe(errors, "signups",
                           lambda: _admin_signup_stats(users, now, total=data["users_total"]),
                           {"today": 0, "yesterday": 0, "last7": 0, "total": len(users), "series": []})
    funnel   = _admin_safe(errors, "funnel",
                           lambda: _admin_funnel(data["visit_rows"], data["gate_rows"], users, now, gate_limit,
                                                 activity=activity, device_counts=data["gate_exact"]),
                           _admin_funnel_blank())
    visits   = _admin_safe(errors, "visits", lambda: _admin_visits(data["visit_rows"], now),
                           {"total": 0, "today": 0, "window": 0})

    def budget_now():
        try:
            anon_limit = g["_fair_anon_limit"]() if callable(g.get("_fair_anon_limit")) else None
        except Exception:
            anon_limit = None
        return _admin_budget(data["fair_rows"], now, g.get("FAIR_GLOBAL_DAILY", 2000), anon_limit, window_h)
    budget   = _admin_safe(errors, "budget", budget_now,
                           {"used": 0, "limit": 0, "pct": None, "warn": False, "resets_in_s": None,
                            "anon": None, "window_hours": window_h})
    gen_gate = _admin_safe(errors, "capacity", lambda: _admin_gen_gate(g), None)

    # ── Users (the Supabase `users` table) ────────────────────────────────────────
    def referral_tallies():
        """How many people each user invited, how many of those paid, and id → e-mail."""
        invited, paid, emails = {}, {}, {}
        for u in users:
            emails[str(u.get("id") or "")] = u.get("email") or ""
            rb = str(u.get("referred_by") or "")
            if rb:
                invited[rb] = invited.get(rb, 0) + 1
                if u.get("referral_paid"):
                    paid[rb] = paid.get(rb, 0) + 1
        return invited, paid, emails
    _invited, _invited_paid, _id_to_email = _admin_safe(errors, "referrals", referral_tallies, ({}, {}, {}))

    def user_row(u):
        """One row of the Users table → (markup, active subscriber?, legacy
        subscriber?, made a guide?)."""
        uid_u  = str(u.get("id") or "")
        plan   = _admin_legacy_sub(u)
        status, active, legacy_sub = plan["status"], plan["active"], plan["legacy"]
        email  = str(u.get("email") or "—")
        name   = str(u.get("name") or "—")
        toks_i = _admin_int(u.get("tokens_remaining"))
        renews = _admin_date(u.get("subscription_period_end"))
        joined = _admin_date(u.get("created_at"))
        code   = str(u.get("referral_code") or "")
        inv    = _invited.get(uid_u, 0)
        inv_p  = _invited_paid.get(uid_u, 0)
        refby  = str(_id_to_email.get(str(u.get("referred_by") or ""), "") or "")
        # Guides made: the lifetime counter only moved in token mode (consume_token).
        # Since free mode an account's own fair-use counter says it is active, and
        # how many guides it made in the running fair-use window (24 h).
        gens   = max(0, _admin_int(u.get("generations_count")))
        act    = activity.get(uid_u)
        recent = act["recent"] if act else 0
        made   = max(gens, recent, 1 if act else 0)
        seen = [t for t in (_admin_ts(u.get("last_used_at")), act["last_at"] if act else None) if t]
        last_used = max(seen).strftime("%Y-%m-%d") if seen else ""
        made_html = f'<b style="color:{"#6ee7b7" if made else "#4a5f80"}">{made:,}{"+" if act else ""}</b>'
        if recent:
            made_html += f'<div class="muted" style="font-size:11px">{recent:,} in last {window_h} h</div>'
        code_title = f' title="Referral code: {_he(code)}"' if code else ""
        inv_html = f'<b style="color:#6ee7b7">{inv:,}</b>' if inv else '<span class="muted">0</span>'
        if inv_p and not free:
            inv_html += f' <span class="muted">({inv_p:,} paid)</span>'
        cancel_btn = (f'<button class="mini" onclick="cancelSub(\'{_js(uid_u)}\',\'{_js(email)}\')">Cancel</button>')
        if free:
            # Free mode: no plan for anyone, except a badge (with the state Stripe has it
            # in) and Cancel for everyone who may still be paying: past due, unpaid and
            # already-ending subscriptions are still subscriptions.
            plan_txt = f'legacy subscriber ({plan["label"]})' if legacy_sub else ""
            plan_html = ""
            if legacy_sub:
                if active:
                    when = f"renews {renews}" if renews else "active"
                elif status == "canceling":
                    when = f"canceling · ends {renews}" if renews else "canceling"
                elif status in _ADMIN_SUB_BILLING:
                    when = plan["label"] + (f" · period end {renews}" if renews else "")
                else:
                    when = f'Stripe subscription on file · status: {plan["label"]}'
                plan_html = (f'<span class="pill {"green" if active else "amber"}">legacy subscriber</span> '
                             f'<span class="muted" style="font-size:12px;white-space:nowrap">{_he(when)}</span>'
                             f' {cancel_btn}')
            tail = tok_attr = ""
        else:
            plan_txt = status
            if active:
                plan_html = '<span style="background:#065f46;color:#6ee7b7;padding:2px 9px;border-radius:5px;font-size:11px;font-weight:600">● active</span>'
            elif status == "canceling":
                plan_html = '<span style="background:#78350f;color:#fcd34d;padding:2px 9px;border-radius:5px;font-size:11px">● canceling</span>'
            else:
                plan_html = f'<span style="background:#16233f;color:#8aa0c8;padding:2px 9px;border-radius:5px;font-size:11px">{_he(status)}</span>'
            if renews:
                plan_html += f' <span class="muted" style="font-size:12px;white-space:nowrap">{_he(renews)}</span>'
            actions = (f'<button onclick="grantTokens(\'{_js(uid_u)}\',\'{_js(email)}\')" '
                       'style="background:#1e3a5f;color:#cfe0ff;border:none;padding:3px 9px;border-radius:6px;cursor:pointer;font-size:12px">＋ Tokens</button>')
            if active or status == "canceling" or u.get("subscription_id"):
                actions += (f' <button onclick="cancelSub(\'{_js(uid_u)}\',\'{_js(email)}\')" '
                            'style="background:#7f1d1d;color:#fecaca;border:none;padding:3px 9px;border-radius:6px;cursor:pointer;font-size:12px">Cancel</button>')
            tail = (f'<td style="text-align:center;font-weight:600">{toks_i}</td>'
                    f'<td style="white-space:nowrap">{actions}</td>')
            tok_attr = f' data-tokens="{toks_i}"'
        row_html = f"""
          <tr class="subrow" data-email="{_he(email.lower())}" data-name="{_he(name.lower())}" data-joined="{_he(joined)}" data-used="{made}" data-recent="{recent}" data-lastused="{_he(last_used)}" data-refby="{_he(refby.lower())}" data-invites="{inv}" data-plan="{_he(plan_txt)}" data-renews="{_he(renews)}" data-legacy="{1 if legacy_sub else 0}" data-active="{1 if active else 0}"{tok_attr}>
            <td class="clip"><b>{_he(email)}</b></td>
            <td class="clip" style="color:#b9c9e6">{_he(name)}</td>
            <td style="color:#8aa0c8;white-space:nowrap">{_he(joined or "—")}</td>
            <td class="c">{made_html}</td>
            <td style="color:#8aa0c8;white-space:nowrap">{_he(last_used or "—")}</td>
            <td style="color:#8aa0c8;font-size:12px">{_he(refby or "—")}</td>
            <td class="c"{code_title}>{inv_html}</td>
            <td>{plan_html}</td>{tail}
          </tr>"""
        return row_html, active, legacy_sub, bool(made)

    subs_rows = ""
    subs_active = subs_legacy = used_count = 0
    for u in users:
        try:
            row_html, is_active, is_legacy, has_made = user_row(u)
        except Exception as exc:
            row_failed("user-rows", exc)
            continue
        subs_rows   += row_html
        subs_active += 1 if is_active else 0
        subs_legacy += 1 if is_legacy else 0
        used_count  += 1 if has_made else 0

    def _sth(label, key, numeric=False):
        return (f'<th class="sort{" c" if numeric else ""}" onclick="subSort(\'{key}\',{1 if numeric else 0})">'
                f'{label} <span>⇅</span></th>')
    head = (_sth("Email", "email") + _sth("Name", "name") + _sth("Joined", "joined")
            + _sth("Guides made", "used", True) + _sth("Last used", "lastused")
            + _sth("Invited by", "refby") + _sth("Invites", "invites", True) + _sth("Plan", "plan"))
    csv_head = ["Email", "Name", "Joined", "Guides made", f"Guides in last {window_h} h", "Last used",
                "Invited by", "Invites", "Plan", "Renews / ends"]
    csv_keys = ["email", "name", "joined", "used", "recent", "lastused", "refby", "invites", "plan", "renews"]
    if not free:
        head += _sth("Tokens", "tokens", True) + "<th>Actions</th>"
        csv_head.append("Tokens")
        csv_keys.append("tokens")
    empty_row = (f'<tr><td colspan="{8 if free else 10}" style="padding:2rem;text-align:center;color:#4a5f80">'
                 + ("Not loaded." if "users" in errors else
                    "No row could be shown." if skipped.get("user-rows") else "No users yet.") + "</td></tr>")
    shown_note = ""
    if stats["total"] > len(users) and users:
        shown_note = (f'<p class="note">Showing the newest {len(users):,} of {stats["total"]:,} accounts. '
                      f'The day counts above are made from these rows.</p>')
    made_note = ""
    if free:
        made_note = ('<p class="note">Guides made is the lifetime counter on the account, and only the old token '
                     'system adds to it: free mode keeps no per-account total. A "+" means the account has made '
                     f'guides since Alimne went free; "in last {window_h} h" is its running fair-use window.</p>')
    users_pills = f'<span class="pill blue">{_admin_n(stats["total"], errors, "users", "signups")} users</span>'
    if free and subs_legacy:
        users_pills += f'<span class="pill green">{subs_legacy:,} legacy subscribers</span>'
    if not free:
        users_pills += f'<span class="pill green">{subs_active:,} active</span>'
    users_section = f"""
<section class="sec" id="sec-users">
  <h3>👥 Users {users_pills}</h3>
  {_admin_err_note(errors, "users", "the accounts")}
  {_admin_err_note(errors, "activity", "the per-account activity since free mode, so 'Guides made' and 'Last used' only show the older counters")}
  {_admin_err_note(errors, "referrals", "the invite counts, so 'Invited by' and 'Invites' are empty")}
  {_admin_skipped_note(errors, skipped, "user-rows", "account row")}
  <div class="tools">
    <input id="subSearch" type="text" placeholder="🔎 Search email or name…" oninput="subFilter()">
    <label><input type="checkbox" id="payingOnly" onchange="subFilter()"> {"Legacy subscribers only" if free else "Paying only"}</label>
    <button class="btn btn-gray" onclick="subExportCSV()">⬇ Export CSV</button>
    <span id="subShown" style="color:#4a5f80;font-size:12px"></span>
  </div>
  <div class="box">
    <table id="subTable">
      <thead><tr>{head}</tr></thead>
      <tbody id="subBody">{subs_rows or empty_row}</tbody>
    </table>
  </div>
  {shown_note}
  {made_note}
</section>"""

    # ── Generations (durable usage events — counts anon + demo, survives restarts) ─
    gens_total = data["gens_total"]

    def gen_tallies():
        today_n = anon = signed = demo = 0
        for G in data["gens"]:
            k = G.get("kind") or ""
            if k == "anon":   anon += 1
            elif k == "demo": demo += 1
            else:             signed += 1
            ts = _admin_ts(G.get("created_at"))
            if ts is not None and ts.date() == today:
                today_n += 1
        return today_n, anon, signed, demo
    gens_today, gens_anon, gens_user, gens_demo = _admin_safe(errors, "generation-tally", gen_tallies, (0, 0, 0, 0))

    def gen_row(G):
        k      = str(G.get("kind") or "")
        loc    = ", ".join([str(x) for x in [G.get("city"), G.get("country")] if x]) or "—"
        kcolor = {"user": "#6ee7b7", "anon": "#7cc4ff", "demo": "#a78bfa"}.get(k, "#8aa0c8")
        return f"""
          <tr>
            <td style="color:#8aa0c8;white-space:nowrap">{_he(_admin_when(G.get("created_at")))}</td>
            <td><span style="color:{kcolor};font-weight:700">{_he(k or '—')}</span></td>
            <td style="color:#8aa0c8;font-size:12px">{_he(G.get('source') or '—')}</td>
            <td>{_he(loc)}</td>
          </tr>"""
    gens_rows = ""
    for G in data["gens"][:200]:
        try:
            gens_rows += gen_row(G)
        except Exception as exc:
            row_failed("generation-rows", exc)
    gens_section = ""
    if gens_rows or "generations" in errors or skipped.get("generation-rows"):
        gens_table = ""
        if gens_rows:
            gens_table = f"""<div class="box"><table>
    <thead><tr><th>Time (UTC)</th><th>Who</th><th>Source</th><th>Location</th></tr></thead>
    <tbody>{gens_rows}</tbody>
  </table></div>"""
        gens_section = f"""
<section class="sec" id="sec-gens">
  <h3>⚡ Recent generations <span class="pill violet">{gens_total:,} total</span><span class="pill">{_admin_n(gens_today, errors, "generation-tally")} today</span></h3>
  {_admin_err_note(errors, "generations", "the generation log")}
  {_admin_err_note(errors, "generation-tally", "the split of the generations by day and by who made them")}
  {_admin_skipped_note(errors, skipped, "generation-rows")}
  {gens_table}
</section>"""

    # ── Leads (emails captured at the old paywall) ───────────────────────────────
    leads_count = len(data["leads"])

    def lead_row(L):
        return f"""
          <tr>
            <td><b>{_he(L.get('email') or '')}</b></td>
            <td style="color:#8aa0c8;font-size:12px">{_he(L.get('source') or '—')}</td>
            <td style="color:#8aa0c8;white-space:nowrap">{_he(_admin_when(L.get("created_at")))}</td>
          </tr>"""
    leads_rows = ""
    for L in data["leads"]:
        try:
            leads_rows += lead_row(L)
        except Exception as exc:
            row_failed("lead-rows", exc)
    leads_title = "Leads (old paywall emails)" if free else "Leads"
    leads_section = ""
    if leads_count:
        leads_section = f"""
<section class="sec" id="sec-leads">
  <h3>✉️ {leads_title} <span class="pill pink">{leads_count:,} emails</span></h3>
  {_admin_skipped_note(errors, skipped, "lead-rows")}
  <div class="box"><table>
    <thead><tr><th>Email</th><th>Source</th><th>Captured (UTC)</th></tr></thead>
    <tbody>{leads_rows}</tbody>
  </table></div>
</section>"""
    elif free or "leads" in errors:
        # Nothing to list: one short line instead of an empty table.
        leads_section = f"""
<section class="sec" id="sec-leads">
  <p class="note" style="margin:0">✉️ {leads_title}: {"none" if "leads" not in errors else "not loaded"}.</p>
  {_admin_err_note(errors, "leads", "the leads")}
</section>"""

    # ── Top of the page: sign-ups, funnel (+ the all-time cards), AI budget ───────
    lead_cards = ""
    if not free:
        # Token mode keeps its revenue cards. (Free mode never asks Stripe for the price.)
        monthly_price = _monthly_price_usd()  # live Stripe price (cached ~1h), USD/month
        mrr = subs_active * monthly_price
        lead_cards = (_admin_card("MRR (est.)", f"${mrr:,.2f}",
                                  f"{subs_active} active × ${monthly_price:.2f}/mo · ARR ${mrr * 12:,.0f}", "mrr", "hero")
                      + _admin_card("Active", f"{subs_active:,}", f"of {stats['total']:,} users", "active-subs", "mint"))
    totals_cards = (
        _admin_card("Visits (all-time)", _admin_n(visits["total"], errors, "visits"),
                    "not loaded" if "visits" in errors else
                    f"{visits['today']:,} today · {visits['window']:,} in the last 7 days", "visits-total", "cyan")
        + _admin_card("Generations (all)", _admin_n(gens_total, errors, "generations"),
                      "not loaded" if ("generations" in errors or "generation-tally" in errors) else
                      f"{gens_today:,} today · {gens_anon:,} anon · {gens_demo:,} demo · {gens_user:,} signed-in",
                      "gens-total", "violet")
        + _admin_card("Accounts that made a guide", _admin_n(used_count, errors, "users", "activity", "user-rows"),
                      "not loaded" if any(b in errors for b in ("users", "activity", "user-rows")) else
                      f"of {len(users):,} accounts, all time", "accounts-active", "lilac"))
    if not free:
        totals_cards += _admin_card("Leads", f"{leads_count:,}", "emails captured", "leads-total", "pink")

    cfg = json.dumps({"payAttr": "legacy" if free else "active", "csvHead": csv_head, "csvKeys": csv_keys})
    cfg = cfg.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    visits_badge = f"{visits['total']:,}" if (sb is not None and "visits" not in errors) else str(len(vis_copy))
    sec_signups = _admin_section("sec-signups", "🚀 Sign-ups",
                                 lambda: _admin_signups_html(stats, errors, lead_cards))
    sec_funnel  = _admin_section("sec-funnel", "🔻 Funnel",
                                 lambda: _admin_funnel_html(funnel, gate_limit, errors, totals_cards))
    sec_budget  = _admin_section("sec-budget", "🔋 Today's AI budget + capacity",
                                 lambda: _admin_budget_html(budget, gen_gate, errors, free))
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin — Alimne</title>
<style>{_ADMIN_CSS}</style></head>
<body>
<div class="topbar">
  <h1>📊 Alimne — Admin
    <span class="badge">{visits_badge} visits</span>
    {f'<span class="badge red">⛔ {len(blocked_copy)} blocked</span>' if blocked_copy else ''}
  </h1>
  <div class="actions">
    <button class="btn btn-gray" onclick="location.reload()">↻ Refresh</button>
    <button class="btn btn-red" onclick="clearLog()">🗑 Clear Log</button>
    <button class="btn btn-gray" onclick="signOut()" title="Sign out of the admin dashboard on every device · تسجيل الخروج من لوحة الإدارة على جميع الأجهزة">⎋ Sign out</button>
  </div>
</div>
{f'<div class="sec" style="margin-bottom:0">{sb_note}</div>' if sb_note else ''}
{sec_signups}
{sec_funnel}
{sec_budget}
{users_section}
{gens_section}
{leads_section}
{blocked_section}
<section id="sec-visitors">
<h3 style="margin:1.5rem 2rem .5rem;color:#8aa0c8;font-size:.95rem">🌐 Recent visitors <span style="font-weight:400;color:#4a5f80;font-size:.8rem">(last 1000, in-memory — resets on restart; totals above are durable)</span></h3>
<div class="wrap">
<table>
  <thead><tr>
    <th>Time (UTC)</th><th>IP Address</th><th>Country</th>
    <th>Location</th><th>ISP / Org</th><th>Path</th><th>User Agent</th><th>Action</th>
  </tr></thead>
  <tbody>
  {rows if rows else '<tr><td colspan="8" class="empty">No visitors recorded yet.</td></tr>'}
  </tbody>
</table>
</div>
</section>
<div id="toast"></div>
<script>var ADMIN_CFG = {cfg};</script>
<script>{_ADMIN_JS}{"" if free else _ADMIN_JS_TOKENS}</script>
</body></html>"""
    # A lone surrogate in a row's text cannot be written as UTF-8, and the response
    # would fail on it after this function has returned: replace what cannot be encoded.
    return page.encode("utf-8", "replace").decode("utf-8")

_SAFE_NAME = re.compile(r'[^\w\-. ]')
_JOB_ID_RE = re.compile(r'^[0-9a-f]{32}$')

def _safe_name(s, maxlen=80):
    return _SAFE_NAME.sub('_', str(s))[:maxlen]

def _valid_job(job_id):
    return bool(_JOB_ID_RE.match(str(job_id)))

def _he(s):
    return (str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
            .replace('"','&quot;').replace("'","&#39;"))

# ── Job store (memory ONLY — uploads and guides are never written to disk)
_JOB_TTL   = 900  # 15 minutes

# Purge any job files left on disk by older versions that persisted to /tmp
import shutil as _shutil
_shutil.rmtree(os.path.join(os.sep, "tmp", "slide-study-jobs"), ignore_errors=True)

_jobs      = OrderedDict()
_jobs_lock = threading.RLock()  # reentrant — get_job may acquire while route holds it

# Ollama can only run one inference at a time locally. Serialise all calls so
# the ThreadPoolExecutor doesn't flood it, which causes truncated JSON output.
_ollama_sem      = threading.Semaphore(1)
_DEBUG_RAW = os.environ.get("DEBUG_RAW") == "1"
_ollama_raw_lock = threading.Lock()  # protect concurrent debug-file writes

# ── Groq token-per-minute pacer ────────────────────────────────────────────────
# Groq's free tier caps tokens-per-minute (default 8000). Rather than fire calls
# and eat 30s "retry-after" waits on every 429, proactively pace: track tokens
# used in a rolling 60s window and sleep just enough to stay under the limit.
# Raise GROQ_TPM_LIMIT if you upgrade your Groq tier (Dev tier is ~250k).
GROQ_TPM_LIMIT   = int(os.environ.get("GROQ_TPM_LIMIT", "7000"))  # headroom under 8000
_groq_tpm_lock   = threading.Lock()
_groq_tpm_events = []  # list of (timestamp, tokens)

def _groq_pace(est_tokens):
    """Block until sending `est_tokens` keeps the rolling-minute total under the
    limit. A single call larger than the limit is allowed through on its own."""
    for _ in range(120):  # safety bound (~2 min max wait)
        with _groq_tpm_lock:
            now = time.time()
            while _groq_tpm_events and now - _groq_tpm_events[0][0] > 60:
                _groq_tpm_events.pop(0)
            used = sum(t for _, t in _groq_tpm_events)
            if not _groq_tpm_events or used + est_tokens <= GROQ_TPM_LIMIT:
                _groq_tpm_events.append((now, est_tokens))
                return
            wait = 60 - (now - _groq_tpm_events[0][0]) + 0.5
        time.sleep(max(1.0, min(wait, 35)))

# Memory cap for the in-memory job store. /api/rehydrate makes jobs for free, so
# past the cap the oldest RESTORED jobs go first (their owners can restore them
# again for free), then the oldest of any kind. The job just stored always stays.
_JOBS_MAX_BYTES = int(os.environ.get("JOBS_MAX_MB", "150")) * 1024 * 1024
_JOBS_MAX_COUNT = int(os.environ.get("JOBS_MAX_COUNT", "1500"))

def _enforce_job_cap(keep):
    """Evict until under the cap. Caller holds _jobs_lock."""
    total = sum(j.get("size", 0) for j in _jobs.values())
    if total <= _JOBS_MAX_BYTES and len(_jobs) <= _JOBS_MAX_COUNT:
        return
    order = sorted((k for k in _jobs if k != keep),
                   key=lambda k: (not _jobs[k].get("rehydrated"), _jobs[k]["ts"]))
    for k in order:
        if total <= _JOBS_MAX_BYTES and len(_jobs) <= _JOBS_MAX_COUNT:
            break
        total -= _jobs.pop(k).get("size", 0)

def store_job(job_id, pdf_bytes, md_text, guide, slides, filename, rehydrated=False):
    # `slides` (the raw extracted upload text) is never read back — don't keep
    # it in memory at all. The parameter stays for call-site compatibility.
    ts = time.time()
    size = len(pdf_bytes or b"") + 2 * len(md_text or "")   # + the guide dict ≈ the markdown again
    with _jobs_lock:
        _jobs[job_id] = {
            "pdf": pdf_bytes, "md": md_text,
            "guide": guide,   "slides": None,
            "filename": filename, "ts": ts,
            "size": size, "rehydrated": bool(rehydrated),
        }
        _enforce_job_cap(job_id)
    _purge_expired_jobs()

def get_job(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job and time.time() - job["ts"] > _JOB_TTL:
            del _jobs[job_id]
            return None
    return job

def _job_expires_in(job):
    """Seconds left before this job is purged (TTL counts from creation)."""
    return max(0, int(_JOB_TTL - (time.time() - job["ts"])))

def _purge_expired_jobs():
    now = time.time()
    with _jobs_lock:
        for k in [k for k, v in _jobs.items() if now - v["ts"] > _JOB_TTL]:
            _jobs.pop(k, None)

def _job_sweeper():
    # Without traffic nothing called store_job/get_job, so expired guides sat in
    # RAM long past the promised 15 minutes. Sweep every minute.
    while True:
        time.sleep(60)
        try:
            _purge_expired_jobs()
        except Exception:
            _log.error("job sweeper error:\n%s", _tb.format_exc())

# Started on the first request, never at import time (see the import note at the top).
_sweeper_started = False
_sweeper_lock    = threading.Lock()

def _ensure_job_sweeper():
    global _sweeper_started
    if _sweeper_started:
        return
    with _sweeper_lock:
        if not _sweeper_started:
            threading.Thread(target=_job_sweeper, daemon=True, name="job-sweeper").start()
            _sweeper_started = True

@app.before_request
def _start_background_once():
    _ensure_job_sweeper()

def _job_expired_json():
    """Contract: every job-dependent JSON endpoint answers 404 code 'expired'."""
    return jsonify({"error": "This guide has expired (guides are kept for 15 minutes) — "
                             "restore or regenerate it.", "code": "expired"}), 404

# ── Signed guide copies (client-held restore) ───────────────────────────────────
# GET /api/guide returns the guide as a canonical JSON string (guide_blob) plus
# an HMAC (sig). The browser keeps that copy in its own tab; after the 15-minute
# job expires (or a deploy wipes memory) POST /api/rehydrate verifies the HMAC
# and rebuilds the PDF under a NEW job id — no LLM call, no credit, and nothing
# kept server-side beyond the usual in-memory 15-minute job.
_GUIDE_KEYS     = ("title", "subtitle", "sections", "flashcards", "mcqs",
                   "keywords", "objectives", "language")
_GUIDE_BLOB_MAX = 600 * 1024   # bytes (UTF-8)
_REHYDRATE_SLOTS = 2            # concurrent rehydrate PDF builds (of gunicorn's 8 threads)
_rehydrate_sem   = threading.BoundedSemaphore(_REHYDRATE_SLOTS)

def _guide_signing_key():
    k = os.environ.get("GUIDE_SIGNING_KEY", "")
    if k:
        return k.encode("utf-8")
    base = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_JWT_SECRET
    if base:   # stable across deploys without a new env var
        return hashlib.sha256(b"alimne-guide-v1|" + base.encode("utf-8")).digest()
    return b""   # no key → rehydrate disabled (503) and no sig is issued

_GUIDE_KEY = _guide_signing_key()

def _guide_public(guide):
    """The guide fields the client may hold (same defaults as /api/guide)."""
    guide = guide or {}
    return {
        "title":      guide.get("title", "") or "",
        "subtitle":   guide.get("subtitle", "") or "",
        "sections":   guide.get("sections",   []) or [],
        "flashcards": guide.get("flashcards", []) or [],
        "mcqs":       guide.get("mcqs",       []) or [],
        "keywords":   guide.get("keywords",   []) or [],
        "objectives": guide.get("objectives", []) or [],
        "language":   guide.get("language", "en") or "en",
    }

def _guide_blob(guide, filename):
    return json.dumps({"v": 1, "filename": filename, "guide": _guide_public(guide)},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))

def _guide_sig(blob):
    return hmac.new(_GUIDE_KEY, blob.encode("utf-8"), hashlib.sha256).hexdigest()

# ── Loose guide shapes ─────────────────────────────────────────────────────────
# Guide content comes from the LLM (and from older shared copies), so any field
# can arrive in the wrong shape: a keyword dict without 'term', one string where
# a list belongs, a number as the title. Readers (chat, share page, views) use
# these instead of assuming the ideal shape — a loose guide must never be a 500.
def _as_list(v):
    """A guide list field: a list stays; one non-blank string becomes [it];
    anything else (None, a number, a dict) is []."""
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip():
        return [v]
    return []

def _scalar_text(v):
    """Display text for a scalar guide value: a str as-is, a number as str();
    anything else (None, bool, list, dict) → ''."""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    return ""

# ── Palette ───────────────────────────────────────────────────────────────────
NAVY        = colors.HexColor('#0a1628')
NAVY_MID    = colors.HexColor('#1a3a6e')
NAVY_LIGHT  = colors.HexColor('#2e5ca8')
ACCENT      = colors.HexColor('#4f8ef7')
KW_BG       = colors.HexColor('#eef3ff')
ROW_ALT     = colors.HexColor('#f4f7ff')
BORDER      = colors.HexColor('#c5d8ff')
TEXT        = colors.HexColor('#0d1b2e')
TEXT_LIGHT  = colors.HexColor('#4a5f80')
WHITE       = colors.white
CARD_Q      = colors.HexColor('#1a3a6e')
CARD_A      = colors.HexColor('#f8faff')
GREEN       = colors.HexColor('#16a34a')
SECTION_BG  = colors.HexColor('#f0f5ff')


# ── Ollama helpers ─────────────────────────────────────────────────────────────

def ollama_running():
    if GROQ_API_KEY:
        return True
    try:
        return http.get(f"{OLLAMA_URL}/api/tags", timeout=3).status_code == 200
    except Exception:
        return False

def ollama_models():
    if GROQ_API_KEY:
        return [GROQ_MODEL]
    try:
        return [m["name"] for m in http.get(f"{OLLAMA_URL}/api/tags", timeout=3).json().get("models", [])]
    except Exception:
        return []

def _extract_json(text):
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.IGNORECASE)
    text = re.sub(r'\s*```$', '', text).strip()

    # ── Pass 1: try the whole text as-is ────────────────────────────────────
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # ── Find the start of the first JSON object or array ───────────────────
    obj_pos = text.find('{')
    arr_pos = text.find('[')
    if obj_pos == -1 and arr_pos == -1:
        raise ValueError("No JSON found in model output")
    if arr_pos != -1 and (obj_pos == -1 or arr_pos < obj_pos):
        start, open_c, close_c = arr_pos, '[', ']'
    else:
        start, open_c, close_c = obj_pos, '{', '}'

    # ── Pass 2: string-aware bracket scan ──────────────────────────────────
    # Tracks whether we're inside a JSON string so { } inside strings are ignored
    depth, in_str, escaped, end = 0, False, False, -1
    stack = []          # track every opening bracket for repair below
    for i, ch in enumerate(text[start:], start):
        if escaped:
            escaped = False
            continue
        if ch == '\\' and in_str:
            escaped = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in ('{', '['):
            depth += 1
            stack.append(ch)
        elif ch in ('}', ']'):
            depth -= 1
            if stack:
                stack.pop()
            if depth == 0:
                end = i
                break

    if end != -1:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    # ── Pass 3: JSON is truncated — repair by closing open brackets ─────────
    # Re-scan to find the deepest valid position and close everything open
    pairs = {'{': '}', '[': ']'}
    depth2, in_str2, escaped2 = 0, False, False
    open_stack = []
    last_good_pos = start  # last position where depth was 0 between top-level items
    for i, ch in enumerate(text[start:], start):
        if escaped2:
            escaped2 = False
            continue
        if ch == '\\' and in_str2:
            escaped2 = True
            continue
        if ch == '"':
            in_str2 = not in_str2
            continue
        if in_str2:
            continue
        if ch in ('{', '['):
            depth2 += 1
            open_stack.append(ch)
        elif ch in ('}', ']'):
            depth2 -= 1
            if open_stack:
                open_stack.pop()

    # Trim trailing incomplete entry: remove everything after the last comma
    # at depth==1 so the partial last entry is dropped
    snippet = text[start:].rstrip()
    # Remove trailing comma + anything after it (the cut-off entry)
    snippet = re.sub(r',\s*[^,\]\}]*$', '', snippet)
    # Close all still-open brackets
    closing = ''.join(pairs[c] for c in reversed(open_stack))
    # Make sure we haven't over-trimmed: if snippet is just the opening char, add empty body
    repaired = snippet + closing
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # ── Pass 4: nuclear fallback — try every possible closing combination ──
    for suffix in ['}', ']}', '}}', '"]}}', '"]}', '"}']:
        try:
            return json.loads(snippet + suffix)
        except json.JSONDecodeError:
            continue

    raise ValueError(f"Cannot parse model output (length={len(text)}). "
                     "Model may have returned incomplete JSON.")

def _call_ollama(prompt, retries=3, num_predict=4096):
    if GROQ_API_KEY:
        return _call_groq(prompt, retries=retries, max_tokens=num_predict)
    payload = {
        "model": OLLAMA_MODEL,
        "format": "json",
        "messages": [
            {"role": "system", "content": "You output only valid JSON. No markdown, no explanation."},
            {"role": "user",   "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0, "num_predict": num_predict},
    }
    last_err = None
    for attempt in range(retries):
        try:
            with _ollama_sem:
                r = http.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=300)
                r.raise_for_status()
                raw_content = r.json()["message"]["content"]

            if _DEBUG_RAW:
                with _ollama_raw_lock:
                    with open(os.path.join(os.path.dirname(__file__), "ollama_raw.txt"), "w", encoding="utf-8") as _f:
                        _f.write(raw_content)

            return _extract_json(raw_content)
        except Exception as e:
            last_err = e
            _log.warning("OLLAMA attempt %d/%d failed: %s", attempt + 1, retries, e)
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last_err


# Longest Groq Retry-After we sleep through; a longer one (daily limit) moves on.
_GROQ_MAX_WAIT_S = 60

def _call_groq(prompt, retries=5, max_tokens=2048):
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is not set — configure it in Render environment variables.")
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    # Try the primary model, then fall back to alternates if the model is
    # unavailable to this key (deprecated / re-tiered → 404/400 model_not_found).
    models = [GROQ_MODEL] + [m for m in GROQ_FALLBACK_MODELS if m != GROQ_MODEL]
    last_err = None
    for model in models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content":
                    "You are a precise study-guide generator. Output ONLY valid JSON — no markdown, no commentary. "
                    "Use ONLY the information the user provides. Never invent, guess, add, or rename facts, people, "
                    "places, terms, acronyms, symbols or numbers. Copy every name and technical term exactly as it "
                    "appears in the source; do not translate or alter names."},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        # Estimate this call's token cost (prompt ≈ chars/4, plus the reserved
        # output) and pace to stay under the per-minute limit before sending.
        est_tokens = len(prompt) // 4 + max_tokens + 120
        for attempt in range(retries):
            try:
                _groq_pace(est_tokens)
                r = http.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json=payload, headers=headers, timeout=120
                )
                if r.status_code == 429:
                    wait = int(r.headers.get("retry-after", 10))
                    last_err = RuntimeError(f"GROQ rate limited (429): {r.text[:200]}")
                    if wait > _GROQ_MAX_WAIT_S:
                        # Daily limit: don't hold a worker thread for hours —
                        # try the next model (own limits), else fail fast.
                        _log.warning("GROQ rate limited (429, model=%s) — retry-after %ds too long, trying next model. body=%s",
                                     model, wait, r.text[:300])
                        break
                    _log.warning("GROQ rate limited (429) — waiting %ds. body=%s", wait, r.text[:300])
                    time.sleep(wait)
                    continue
                if r.status_code in (400, 404):
                    # Model-level problem (unknown/deprecated/no-access) — don't
                    # burn retries; move on to the next fallback model.
                    _log.error("GROQ HTTP %s (model=%s) — trying next model. body=%s",
                               r.status_code, model, r.text[:400])
                    last_err = RuntimeError(f"GROQ {r.status_code} for model {model}: {r.text[:200]}")
                    break
                if r.status_code >= 400:
                    _log.error("GROQ HTTP %s (model=%s): %s", r.status_code, model, r.text[:400])
                r.raise_for_status()
                raw_content = r.json()["choices"][0]["message"]["content"]
                if model != GROQ_MODEL:
                    _log.warning("GROQ served by fallback model %s", model)
                return _extract_json(raw_content)
            except Exception as e:
                last_err = e
                _log.warning("GROQ attempt %d/%d (model=%s) failed: %s", attempt + 1, retries, model, e)
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
    if last_err is None:
        last_err = RuntimeError("GROQ call failed — all models/retries exhausted")
    raise last_err


# ── Three-pass AI processing ──────────────────────────────────────────────────

def _lang_rules(language):
    """Faithfulness + language rules injected into every prompt so the model
    stays true to the source and outputs cleanly in the requested language."""
    if language == "ar":
        lang_line = ("Write every text value in Modern Standard Arabic (العربية). "
                     "Use correct, natural Arabic grammar and spelling.")
    else:
        lang_line = "Write every text value in clear English."
    keep_lang = (
        "- Keep every word in the SAME script/language the source uses. If the source writes a "
        "name or place in Arabic, keep it in Arabic — never switch it to English (e.g. keep "
        "«فرنسا»، «بريطانيا»، «روسيا»، «ألمانيا»; do NOT write France/Britain/Russia/Germany). Only "
        "genuinely Latin-script terms in the source (acronyms/formulas like ATP, CO2, DNA) stay Latin.\n"
        if language == "ar" else ""
    )
    return (
        "- " + lang_line + " Keep all JSON keys in English exactly as shown.\n"
        "- ACCURACY IS CRITICAL: use ONLY facts that appear in the source above. "
        "Do NOT invent, assume, or add anything that is not stated in the source.\n"
        "- Copy every name, person, place, acronym, symbol (e.g. ATP, CO2, DNA) and number "
        "EXACTLY as written in the source. Never rename, translate, transliterate, or alter a "
        "proper noun, technical term, or formula.\n"
        + keep_lang +
        "- If the source does not cover something, leave it out rather than making it up."
    )


def _as_dict(result, list_key=None):
    """If the model returned a list instead of a dict, coerce it."""
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        # If list contains dicts, pick the first one
        first_dict = next((x for x in result if isinstance(x, dict)), None)
        if first_dict:
            return first_dict
        # Otherwise wrap under the given key
        if list_key:
            return {list_key: result}
    return {}


# Unambiguous list-bullet glyphs the model sometimes embeds inside a fact string.
# Deliberately EXCLUDES the middle dot "·" (U+00B7) and hyphen "-" — those are real
# characters in chemistry formulas (CuSO4·5H2O), ranges (1990-2000) and words
# (well-known), which must be preserved verbatim.
_BULLET_GLYPHS = "•◦▪▫‣⁃●○◉◆◇■□∙"

def _debullet(text):
    """Return a fact string as clean prose: no leading '- '/'• ' marker and no
    bullet glyph used as an INLINE separator (which is why bullets were showing up
    in the middle of PDF paragraphs). Inline glyphs become '; ' so the two facts
    stay readable; a leading marker is dropped outright. Runs on every renderer
    (PDF, markdown, web guide) so the output is consistent."""
    s = str(text).replace("\r", "\n")
    # Sub-lists the model split across lines → one flowing line
    s = re.sub(r"\s*\n+\s*", " ", s).strip()
    # Drop a leading list marker: bullet glyph, dash/asterisk, or "1." / "1)".
    # A dash or "N." directly followed by a digit is a number ("-273.15", "3.5"), not a marker.
    s = re.sub(r"^\s*(?:[" + _BULLET_GLYPHS + r"]+|[\-–—*]+(?!\d)|\d+[.)](?!\d))\s*", "", s)
    # Any bullet glyph still inside the text is an inline separator → "; "
    s = re.sub(r"\s*[" + _BULLET_GLYPHS + r"]+\s*", "; ", s)
    # Tidy: collapse spaces, drop a "; " that lands right before punctuation, and
    # never emit doubled separators or a trailing one.
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"\s*;\s*(?=[.!?,;:])", "", s)
    s = re.sub(r"(?:;\s*){2,}", "; ", s)
    return s.strip(" ;")


# ── PDF glyph safety ───────────────────────────────────────────────────────────
# English PDFs use Helvetica (WinAnsi only). Anything outside that set — the
# model's favourite non-breaking hyphen U+2011 ("client‑side"), Greek, arrows,
# ≤/≥, subscripts — rendered as a solid black box (■). Normalise lookalikes,
# draw Greek/maths with the PDF Symbol font, and drop whatever neither can draw.
import unicodedata as _ud
_PDF_CHAR_MAP = {
    "‐": "-", "‑": "-", "‒": "-", "⁃": "-", "−": "-",
    "﹣": "-", "－": "-", "―": "—",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    " ": " ", "　": " ",
    "​": "", "⁠": "", "﻿": "", "­": "",
}
_PDF_CHAR_RE = re.compile("[" + "".join(_PDF_CHAR_MAP) + "]")

def _pdf_normalize(s):
    """Lookalike punctuation/spaces → plain ones. Safe for Arabic text too."""
    return _PDF_CHAR_RE.sub(lambda m: _PDF_CHAR_MAP[m.group(0)], s)

def _enc_ok(ch, codec):
    try:
        ch.encode(codec)
        return True
    except Exception:
        return False

def _pdf_winansi_alt(ch):
    """WinAnsi stand-in for a character neither Helvetica nor Symbol can draw:
    H₂O → H2O, ﬁ → fi, full-width → ASCII, then accents stripped (ā → a).
    Emoji etc. become "" - dropped, never boxed."""
    alt = _ud.normalize("NFKC", ch)
    if not all(_enc_ok(c, "cp1252") for c in alt):
        alt = "".join(c for c in _ud.normalize("NFKD", ch) if not _ud.combining(c))
    return "".join(c for c in alt if _enc_ok(c, "cp1252"))

def _pdf_latin_markup(s):
    """Escaped reportlab Paragraph markup for Helvetica text: every character is
    either WinAnsi (Helvetica) or wrapped in the Symbol font; nothing else
    survives, so the PDF can never show a missing-glyph box."""
    from reportlab.pdfbase.rl_codecs import RL_Codecs
    RL_Codecs.register()
    out, sym = [], []

    def esc(t):
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def flush():
        if sym:
            out.append('<font face="Symbol">' + esc("".join(sym)) + "</font>")
            sym.clear()

    for ch in _pdf_normalize(s):
        if (ch < " " or ch == "\x7f") and not ch.isspace():
            continue                   # NUL/ESC/DEL...: no Helvetica glyph (■)
        if _enc_ok(ch, "cp1252"):
            flush(); out.append(esc(ch)); continue
        if _enc_ok(ch, "symbol"):
            sym.append(ch); continue
        flush(); out.append(esc(_pdf_winansi_alt(ch)))
    flush()
    return "".join(out)


def _pdf_xesc(s):
    """Plain text → literal reportlab Paragraph text (no markup is interpreted)."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ar_base_dir(s):
    """'R' or 'L': the paragraph direction bidi itself would pick for `s` (its first
    strong letter, UAX#9 rules P2/P3). Presentation forms count as Arabic (AL)."""
    for ch in s:
        d = _ud.bidirectional(ch)
        if d in ("R", "AL"):
            return "R"
        if d == "L":
            return "L"
    return "L"


# NotoNaskhArabic has no Latin letters and, below U+0600, only space ! , . 0-9 :
# NBSP « » - so English terms (DNA, H2O), % - ( ) ? · — in an Arabic PDF printed
# as missing-glyph boxes. Characters it lacks are drawn in Helvetica instead.
# Only call these once _ensure_arabic_font() has registered the font.

def _ar_font_has():
    """Codepoint → glyph id of the registered Arabic font; a missing codepoint or
    glyph 0 (.notdef, e.g. U+FFFF) means the font cannot draw it."""
    return _pdfmetrics.getFont(_ARABIC_FONT).face.charToGlyph


def _ar_pdf_text(s):
    """Arabic PDF plain text with each character the Arabic font lacks replaced by
    what Helvetica/Symbol will draw for it (H₂O → H2O, emoji dropped - the same
    choices as _pdf_latin_markup). Afterwards _ar_pdf_markup() draws every
    character as it is, so the text measures the same before and after the
    per-line bidi reordering."""
    from reportlab.pdfbase.rl_codecs import RL_Codecs
    RL_Codecs.register()
    has = _ar_font_has()
    out = []
    for ch in str(s):
        if has.get(ord(ch)):          # the Arabic font draws it as-is (e.g. U+2010)
            out.append(ch)
            continue
        for c in _pdf_normalize(ch):  # lookalike hyphens/spaces → plain ones
            out.append(c if (has.get(ord(c)) or _enc_ok(c, "cp1252") or _enc_ok(c, "symbol"))
                       else _pdf_winansi_alt(c))
    return "".join(out)


def _ar_pdf_markup(s):
    """Escaped Paragraph markup for _ar_pdf_text() output (any order): runs the
    Arabic font has stay in the paragraph's font, runs it lacks are wrapped in
    Helvetica via _pdf_latin_markup (WinAnsi, or Symbol for Greek/maths)."""
    has = _ar_font_has()
    out, run, run_has = [], [], None

    def flush():
        if run:
            t = "".join(run)
            out.append(_pdf_xesc(t) if run_has else
                       '<font face="Helvetica">' + _pdf_latin_markup(t) + "</font>")
            run.clear()

    for ch in s:
        ch_has = bool(has.get(ord(ch)))
        if ch_has != run_has:
            flush()
            run_has = ch_has
        run.append(ch)
    flush()
    return "".join(out)


def _para_line_texts(para):
    """Plain text of each line of a WRAPPED Paragraph. Simple lines are
    (extraSpace, [word, ...]) tuples; frag lines carry .words, a list of frags."""
    bl = getattr(para, "blPara", None)
    if bl is None:
        return []
    out = []
    for line in bl.lines:
        if isinstance(line, tuple):
            out.append(" ".join(str(w) for w in line[1]))
        else:
            out.append("".join(getattr(f, "text", "") for f in line.words))
    return out


_AR_LETTER_RE = re.compile("[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")


class _ArabicParagraph(Paragraph):
    """Paragraph for one Arabic plain-text field of build_pdf.

    reportlab here has no RTL support (no rlbidi/uharfbuzz), so Arabic has to be
    handed over already in visual order. Running bidi over the WHOLE string before
    reportlab wraps it (the old way) reverses the paragraph first, so reportlab
    breaks it into lines from the wrong end: a multi-line paragraph came out with
    its lines in reverse order, the first sentence on the last line.

    This wraps the reshaped LOGICAL text (itself, as a plain Paragraph), bidi-
    reorders the resulting lines (_ar_display_lines: levels resolved over the whole
    paragraph, then each line reordered with the paragraph's direction) and lays
    those lines out joined by <br/> in a second Paragraph (_real), which is what
    gets drawn. Tables wrap the same cell at several widths, and wrap it again and
    again at each (KeepTogether, splitting, drawing), so the layout and its size
    are built once per distinct width and reused (_layouts). `shaped` is
    _ar_shape() output: plain text, reshaped, not bidi-reordered and not escaped -
    markup is never interpreted. `base_dir` 'R'/'L' fixes the paragraph
    direction; None takes it from the first strong letter. build_pdf passes 'R'
    for Arabic text, so "DNA هو ..." still reads right-to-left.

    Characters the Arabic font lacks (Latin, % - ( ) ? ·) are drawn in Helvetica
    (_ar_pdf_text/_ar_pdf_markup). The probe (this flowable) uses that same mixed
    markup, so every line is measured in the fonts it is drawn in.
    """

    _MAX_LAYOUTS = 8      # distinct widths kept per paragraph (a table probes a few)

    def __init__(self, shaped, style, base_dir=None):
        self._shaped = _ar_pdf_text(shaped or "")
        self._base_dir = base_dir if base_dir in ("R", "L") else _ar_base_dir(self._shaped)
        self._real = None
        self._layouts = {}    # availWidth -> [real Paragraph, (w, h) or None]
        # The flowable itself holds the LOGICAL text: it is the line-breaking
        # probe. Same glyphs, fonts and word widths as the drawn lines.
        Paragraph.__init__(self, _ar_pdf_markup(self._shaped), style)

    def _layout(self, availWidth, availHeight):
        entry = self._layouts.get(availWidth)
        if entry is None:
            # Line breaking depends only on the width (availHeight matters to split()).
            Paragraph.wrap(self, availWidth, availHeight)
            lines = [ln.strip() for ln in _para_line_texts(self)]
            real = Paragraph(
                "<br/>".join(_ar_pdf_markup(ln) for ln in _ar_display_lines(lines, self._base_dir)),
                self.style)
            if len(self._layouts) >= self._MAX_LAYOUTS:
                self._layouts.clear()
            entry = self._layouts[availWidth] = [real, None]
        self._real = entry[0]
        return entry

    def wrap(self, availWidth, availHeight):
        entry = self._layout(availWidth, availHeight)
        if entry[1] is None:
            # A layout is only ever wrapped at its own width, so its size is fixed.
            entry[1] = entry[0].wrap(availWidth, availHeight)
        self.width, self.height = entry[1]
        return self.width, self.height

    def split(self, availWidth, availHeight):
        # The parts are plain Paragraphs of already-ordered lines.
        entry = self._layout(availWidth, availHeight)
        if entry[1] is None:
            entry[1] = entry[0].wrap(availWidth, availHeight)
        return entry[0].split(availWidth, availHeight)

    def draw(self):
        real = self._real
        real.canv = self.canv
        try:
            real.draw()
        finally:
            del real.canv


def _detect_language(content):
    """Detect 'ar' or 'en' from slides list or plain text. Based on Arabic char ratio."""
    if isinstance(content, list):
        sample = " ".join(
            f"{s.get('title', '')} {s.get('content', '')}" for s in content[:20]
        )
    else:
        sample = str(content)[:6000]
    arabic = sum(1 for c in sample if '؀' <= c <= 'ۿ')
    alpha  = sum(1 for c in sample if c.isalpha())
    return "ar" if alpha > 0 and arabic / alpha > 0.25 else "en"


def pass1_overview(slides, language, dcfg=None):
    """Get title, objectives, section groupings, and keywords."""
    dcfg = dcfg or DETAIL["standard"]
    lang = "in Arabic" if language == "ar" else "in English"
    # Include ALL slides for grouping; use title-only for slides beyond max_slides
    # to keep the LLM input within token limits for large presentations.
    outline = "".join(
        f"Slide {s['slide_num']}: {s['title']}\n{s['content'][:dcfg['slide_chars']]}\n\n"
        if i < dcfg["max_slides"] else
        f"Slide {s['slide_num']}: {s['title']}\n"
        for i, s in enumerate(slides)
    )
    result = _call_ollama(f"""Create a study guide overview {lang} from this source material.

{outline}

Return JSON:
{{
  "title": "TOPIC IN CAPS",
  "subtitle": "course/session description",
  "objectives": ["objective 1", "objective 2", "objective 3"],
  "sections": [
    {{"title": "SECTION NAME", "slide_nums": [1, 2, 3]}}
  ],
  "keywords": [
    {{"term": "Term", "definition": "Specific 1-sentence definition or role description"}}
  ]
}}

Rules:
- Group related slides into logical sections SIZED TO THE MATERIAL: use as few as 1 section for short material, up to 7 for long material, and NEVER more sections than there are slides. Each slide belongs to exactly ONE section (non-overlapping slide_nums) — never place the same slide, or the same content, in more than one section.
- objectives: take from a learning-objectives section if present, otherwise summarise the actual content (do not invent goals)
- keywords: {dcfg['keywords']} terms — only concepts, acronyms, roles and processes that actually appear in the source
{_lang_rules(language)}
- Output JSON only""", num_predict=dcfg["num_predict"])
    return _as_dict(result)


def pass2_section(title, section_slides, language, dcfg=None):
    """Get detailed bullets + optional comparison table for one section."""
    dcfg = dcfg or DETAIL["standard"]
    lang = "in Arabic" if language == "ar" else "in English"
    # Cap per-slide and total content so a crafted file can't blow up the Groq
    # token/cost bill (pass 1 caps slide count, but pass 2 sent full content).
    _per = dcfg.get("slide_chars", 700) * 3
    content = "".join(
        f"Slide {s['slide_num']}: {s['title']}\n{s['content'][:_per]}\n\n"
        for s in section_slides
    )[:60_000]
    result = _call_ollama(f"""Extract detailed exam study notes {lang} for the section "{title}".

{content}

Return JSON:
{{
  "bullets": [
    "Full specific fact, definition, or step from the content",
    "Another detailed point — include names, numbers, roles, processes"
  ],
  "table": {{
    "headers": ["Column 1", "Column 2"],
    "rows": [["value", "value"]]
  }}
}}

Rules:
- bullets: {dcfg['bullets']} specific, exam-worthy facts taken directly from the content above, focused ONLY on "{title}". Do NOT restate the whole overview or repeat generic intro facts that belong to other sections — cover only what is specific to THIS section. Start directly with facts specific to "{title}"; do NOT open with the overall time period or a one-line summary of the whole topic.
- table: include ONLY if content has roles/comparisons/structured lists; otherwise omit the table field entirely
{_lang_rules(language)}
- Output JSON only""", num_predict=dcfg["num_predict"])
    result = _as_dict(result, list_key="bullets")
    # If model returned a flat list of strings under "bullets", normalise each element
    # and strip any bullet glyphs the model embedded (leading OR inline) so facts
    # render as clean prose everywhere downstream.
    bullets = result.get("bullets", [])
    if isinstance(bullets, str):       # one fact as a bare string, not a list
        bullets = [bullets]
    elif not isinstance(bullets, list):
        bullets = []
    result["bullets"] = [c for b in bullets if b for c in (_debullet(b),) if c]
    return result


def _kw_sec_text(guide):
    """Prompt text for flash cards / quiz: key terms and section titles. A loose
    entry (a keyword without "term", a numeric term, a null section title) is
    skipped or stringified - a KeyError here used to drop the cards and quiz."""
    terms  = [_scalar_text(k.get("term")) for k in _as_list(guide.get("keywords"))[:20]
              if isinstance(k, dict)]
    titles = [_scalar_text(s.get("title")) for s in _as_list(guide.get("sections"))
              if isinstance(s, dict)]
    return ", ".join(t for t in terms if t), " | ".join(t for t in titles if t)


def pass3_flashcards(guide, language, dcfg=None):
    """Generate Q&A flash cards from the guide content."""
    dcfg = dcfg or DETAIL["standard"]
    lang = "in Arabic" if language == "ar" else "in English"
    kw_text, sec_text = _kw_sec_text(guide)
    bullets_ctx = ""
    for sec in _as_list(guide.get("sections")):
        if isinstance(sec, dict) and sec.get("bullets"):
            bullets_ctx += f"\n{sec.get('title','')}:\n" + "\n".join(f"- {b}" for b in sec["bullets"])
    result = _call_ollama(f"""Create exam flash cards {lang} for a study guide about: {guide.get('title', '')}.

Topics: {sec_text}
Key terms: {kw_text}
Study content:{bullets_ctx}

Return JSON:
{{
  "flashcards": [
    {{"q": "Question that tests a key concept?", "a": "Clear, concise answer"}},
    {{"q": "Define [term]?", "a": "Definition"}},
    {{"q": "What are the responsibilities of [role]?", "a": "Specific responsibilities"}}
  ]
}}

Rules:
- Create exactly {dcfg['n_flash']} flash cards
- Base EVERY question and answer directly on the study content provided above — no generic or invented questions
- Mix definition questions, "what is" questions, "name the" questions, and role/responsibility questions
- Answers must be specific and factually match the content
{_lang_rules(language)}
- Output JSON only""", num_predict=dcfg["num_predict"])
    # Model may return the array directly instead of wrapping it
    if isinstance(result, list):
        return {"flashcards": [x for x in result if isinstance(x, dict)]}
    return _as_dict(result, list_key="flashcards")


def pass4_mcq(guide, language, dcfg=None):
    """Generate multiple-choice quiz questions."""
    dcfg   = dcfg or DETAIL["standard"]
    lang   = "in Arabic" if language == "ar" else "in English"
    n      = dcfg["n_mcq"]
    kw_text, sec_text = _kw_sec_text(guide)
    bullets_ctx = ""
    for sec in _as_list(guide.get("sections")):
        if isinstance(sec, dict) and sec.get("bullets"):
            bullets_ctx += f"\n{sec.get('title','')}:\n" + "\n".join(f"- {b}" for b in sec["bullets"])
    result = _call_ollama(f"""Create {n} multiple-choice exam questions {lang} for: {guide.get('title','')}.

Topics: {sec_text}
Key terms: {kw_text}
Study content:{bullets_ctx}

Return JSON:
{{
  "mcqs": [
    {{
      "q": "Question text?",
      "options": ["A. option one", "B. option two", "C. option three", "D. option four"],
      "answer": "A",
      "explanation": "Why A is correct"
    }}
  ]
}}

Rules:
- Exactly {n} questions, 4 options each (A B C D)
- Every question, the correct option, and the explanation must be grounded in the study content above — do not invent facts or use outside knowledge
- answer: just the letter
- Mix easy and hard questions
{_lang_rules(language)}
- JSON only""", num_predict=dcfg["num_predict"])
    if isinstance(result, list):
        return {"mcqs": [x for x in result if isinstance(x, dict)]}
    return _as_dict(result, list_key="mcqs")


def _slide_nums(sec):
    """The section's slide numbers as a set of ints; the model sometimes sends a
    bare int, null or a nested list instead of a flat list."""
    raw = sec.get("slide_nums")
    if not isinstance(raw, list):
        raw = [raw]
    return {n for n in raw if isinstance(n, int)}


def _sections_parallel(sections, content_slides, language, dcfg):
    """Process sections sequentially (Groq rate limits prevent safe concurrency).
    Yields plain dicts. Flashcards+MCQ are parallelized separately."""
    n = len(sections)
    for i, sec in enumerate(sections):
        yield {"step": "section", "msg": f"Section {i+1}/{n}: {sec.get('title', '')}…"}
        nums = _slide_nums(sec)
        sl = [s for s in content_slides if s["slide_num"] in nums]
        if not sl:
            chunk = max(1, len(content_slides) // n)
            start = i * chunk
            end   = start + chunk if i < n - 1 else len(content_slides)
            sl    = content_slides[start:end] or content_slides
        try:
            det = pass2_section(sec.get("title", ""), sl, language, dcfg)
            sec["bullets"] = det.get("bullets", [])
            if isinstance(det.get("table"), dict):
                sec["table"] = det["table"]
        except Exception:
            _log.error("pass2 [%s] error:\n%s", sec.get("title", "?"), _tb.format_exc())
            sec["bullets"] = []
        yield {"step": "section", "msg": f"Sections: {i+1}/{n} done…"}

    # Safety net: on short inputs the model sometimes repeats the same bullets in
    # every section. Drop any section whose bullets duplicate an earlier one, so a
    # guide never shows 2-3 identical sections. Mutates in place (same list object
    # as overview["sections"]). Keep at least one section.
    seen, keep = set(), []
    for sec in sections:
        sig = tuple(str(b).strip() for b in sec.get("bullets", []) if str(b).strip())
        if sig and sig in seen:
            continue
        if sig:
            seen.add(sig)
        keep.append(sec)
    if keep and len(keep) != len(sections):
        sections[:] = keep


def _flashcards_mcq_parallel(overview, language, dcfg, include_quiz=True, include_mcq=True):
    """Run pass3 then pass4 sequentially (Groq free tier rate limits concurrent calls).
    Yields plain dicts. include_quiz=False → summary-only (no flashcards, no quiz).
    Otherwise flashcards are generated; the practice quiz (mcq) only if include_mcq."""
    if not include_quiz:
        overview["flashcards"] = []
        overview["mcqs"] = []
        yield {"step": "summary", "msg": "Summary-only mode — skipping flash cards and quiz…"}
        return
    yield {"step": "flashcards", "msg": "Generating flash cards…"}
    try:
        overview["flashcards"] = pass3_flashcards(overview, language, dcfg).get("flashcards", [])
    except Exception:
        _log.error("pass3 error:\n%s", _tb.format_exc())
        overview["flashcards"] = []
    yield {"step": "flashcards", "msg": "Flash cards ready…"}

    if not include_mcq:
        overview["mcqs"] = []
        yield {"step": "mcq", "msg": "Quiz skipped…"}
        return
    yield {"step": "mcq", "msg": "Generating quiz…"}
    try:
        overview["mcqs"] = pass4_mcq(overview, language, dcfg).get("mcqs", [])
    except Exception:
        _log.error("pass4 error:\n%s", _tb.format_exc())
        overview["mcqs"] = []
    yield {"step": "mcq", "msg": "Quiz ready…"}


def build_markdown(guide):
    """Convert guide dict to a Markdown string (labels follow the guide language)."""
    is_ar = guide.get("language") == "ar"
    L = {
        "title":      "دليل الدراسة" if is_ar else "Study Guide",
        "objectives": "الأهداف التعليمية" if is_ar else "Learning Objectives",
        "keywords":   "قاموس المصطلحات" if is_ar else "Keywords Cheatsheet",
        "flashcards": "بطاقات المراجعة" if is_ar else "Flash Cards",
        "quiz":       "أسئلة الاختيار من متعدد" if is_ar else "Multiple Choice Questions",
        "q":          "سؤال" if is_ar else "Q",
        "a":          "الإجابة" if is_ar else "A",
    }
    lines = [f"# {guide.get('title', L['title'])}", ""]
    if guide.get("subtitle"):
        lines += [f"*{guide['subtitle']}*", ""]
    objs = [o for o in _as_list(guide.get("objectives")) if isinstance(o, str)]
    if objs:
        lines += [f"## {L['objectives']}", ""]
        for o in objs: lines.append(f"- {o}")
        lines.append("")
    for sec in guide.get("sections", []):
        if not isinstance(sec, dict): continue
        lines += [f"## {sec.get('title', '')}", ""]
        for b in sec.get("bullets", []): lines.append(f"- {_debullet(b)}")
        tbl = sec.get("table")
        if isinstance(tbl, dict) and _as_list(tbl.get("headers")) and _as_list(tbl.get("rows")):
            headers = _as_list(tbl["headers"])
            lines.append("")
            lines.append("| " + " | ".join(str(h) for h in headers) + " |")
            lines.append("|" + "|".join(["---"] * len(headers)) + "|")
            for row in _as_list(tbl["rows"]):
                lines.append("| " + " | ".join(str(c) for c in (row if isinstance(row, list) else [row])) + " |")
        lines.append("")
    kws = [k for k in guide.get("keywords", []) if isinstance(k, dict)]
    if kws:
        lines += [f"## {L['keywords']}", ""]
        for k in kws: lines.append(f"**{k.get('term','')}** — {k.get('definition','')}")
        lines.append("")
    fcs = [f for f in guide.get("flashcards", []) if isinstance(f, dict)]
    if fcs:
        lines += [f"## {L['flashcards']}", ""]
        for i, fc in enumerate(fcs, 1):
            lines += [f"**{L['q']}{i}:** {fc.get('q','')}", f"**{L['a']}:** {fc.get('a','')}", ""]
    mcqs = [m for m in _as_list(guide.get("mcqs")) if isinstance(m, dict)]
    if mcqs:
        lines += [f"## {L['quiz']}", ""]
        for i, m in enumerate(mcqs, 1):
            lines.append(f"**{i}. {m.get('q','')}**")
            for opt in _as_list(m.get("options")): lines.append(f"   {opt}")
            lines += [f"   ✓ **{m.get('answer','')}** — {m.get('explanation','')}", ""]
    return "\n".join(lines)


def ask_ollama(slides, language, progress_cb=None):
    """Orchestrate three-pass processing with optional progress callback."""
    content_slides = [s for s in slides if s["content"].strip() or s["title"].strip()]

    if progress_cb: progress_cb("overview", f"Analysing structure ({len(content_slides)} slides)…")
    overview = pass1_overview(content_slides, language)

    # Normalize sections/keywords (mistral may return plain strings)
    raw_sec = overview.get("sections", [])
    overview["sections"] = [
        s if isinstance(s, dict) else {"title": str(s), "slide_nums": []}
        for s in (raw_sec if isinstance(raw_sec, list) else [])
    ]
    raw_kw = overview.get("keywords", [])
    overview["keywords"] = [
        k if isinstance(k, dict) else {"term": str(k), "definition": ""}
        for k in (raw_kw if isinstance(raw_kw, list) else [])
    ]
    if not overview["sections"]:
        overview["sections"] = [{"title": overview.get("title", "Overview"), "slide_nums": [s["slide_num"] for s in content_slides]}]

    sections = overview["sections"]
    n = len(sections)
    for i, sec in enumerate(sections):
        if progress_cb: progress_cb("section", f"Building section {i+1} of {n}: {sec.get('title','')}…")
        nums = _slide_nums(sec)
        sl = [s for s in content_slides if s["slide_num"] in nums]
        if not sl:
            chunk = max(1, len(content_slides) // n)
            start = i * chunk
            end   = start + chunk if i < n - 1 else len(content_slides)
            sl    = content_slides[start:end] or content_slides
        detail = pass2_section(sec.get("title", ""), sl, language)
        sec["bullets"] = detail.get("bullets", [])
        if isinstance(detail.get("table"), dict):
            sec["table"] = detail["table"]

    if progress_cb: progress_cb("flashcards", "Generating flash cards…")
    try:
        fc = pass3_flashcards(overview, language)
        overview["flashcards"] = fc.get("flashcards", [])
    except Exception:
        overview["flashcards"] = []

    return overview


# ── File extraction — PPTX, PPT binary, PDF ───────────────────────────────────

def _extract_pptx_raw(raw):
    """Open as pptx; on relationship errors fall back to raw ZIP XML walk."""
    try:
        prs = Presentation(io.BytesIO(raw))
    except Exception as e:
        if "officeDocument" not in str(e) and "relationship" not in str(e):
            raise ValueError(f"Cannot open PowerPoint file: {e}")
        # Fallback: read slide XML directly from the ZIP
        import zipfile, xml.etree.ElementTree as ET
        slides = []
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            slide_files = sorted(
                [n for n in z.namelist() if re.match(r'ppt/slides/slide\d+\.xml', n)],
                key=lambda x: int(re.findall(r'\d+', x)[-1])
            )
            for idx, sf in enumerate(slide_files, 1):
                parts = [
                    t.text.strip()
                    for t in ET.fromstring(z.read(sf)).iter(
                        '{http://schemas.openxmlformats.org/drawingml/2006/main}t'
                    )
                    if t.text and t.text.strip()
                ]
                if parts:
                    slides.append({"slide_num": idx, "title": parts[0][:80], "content": "\n".join(parts)})
        if not slides:
            raise ValueError("No readable content found in this file")
        return slides

    if len(prs.slides) > _MAX_PAGES:
        raise ValueError(f"Presentation has too many slides (max {_MAX_PAGES}).")
    slides = []
    for i, slide in enumerate(prs.slides, 1):
        ts    = slide.shapes.title
        title = ts.text.strip() if ts and ts.text.strip() else f"Slide {i}"
        body  = [
            shape.text.strip()
            for shape in slide.shapes
            if hasattr(shape, "text") and shape != ts and shape.text.strip()
        ]
        slides.append({"slide_num": i, "title": title, "content": "\n".join(body)})
    return slides


def _extract_ppt_binary(raw):
    """Extract text from old binary OLE2 .ppt via record-level parsing."""
    import struct
    try:
        import olefile
    except ImportError:
        raise ValueError("olefile not installed — run: pip install olefile")

    ole = olefile.OleFileIO(io.BytesIO(raw))
    if not ole.exists('PowerPoint Document'):
        raise ValueError("Not a valid binary PowerPoint file")

    stream = ole.openstream('PowerPoint Document').read()
    texts  = []

    def parse(buf, start, end):
        i = start
        while i + 8 <= end:
            rec_ver  = struct.unpack_from('<H', buf, i)[0] & 0x0F
            rec_type = struct.unpack_from('<H', buf, i + 2)[0]
            rec_len  = struct.unpack_from('<I', buf, i + 4)[0]
            data_end = i + 8 + rec_len
            if data_end > end:
                break
            if rec_type == 0x0FA0:       # TextCharsAtom — UTF-16LE
                t = buf[i+8:data_end].decode('utf-16-le', errors='ignore').strip()
                if t: texts.append(t)
            elif rec_type == 0x0FA8:     # TextBytesAtom — Latin-1
                t = buf[i+8:data_end].decode('latin-1', errors='ignore').strip()
                if t: texts.append(t)
            elif rec_ver == 0xF:         # Container — recurse into children
                parse(buf, i + 8, data_end)
            i = data_end

    parse(stream, 0, len(stream))

    if not texts:
        raise ValueError("No readable text found in the binary .ppt file")

    # Group into pseudo-slides of ~5 text blocks
    slides = []
    for n, chunk in enumerate([texts[j:j+5] for j in range(0, len(texts), 5)], 1):
        slides.append({"slide_num": n, "title": chunk[0][:80], "content": "\n".join(chunk)})
    return slides


def _extract_pdf(raw):
    """Extract text from PDF, one entry per page."""
    try:
        import pypdf
    except ImportError:
        raise ValueError("pypdf not installed — run: pip install pypdf")

    reader = pypdf.PdfReader(io.BytesIO(raw))
    if len(reader.pages) > _MAX_PAGES:
        raise ValueError(f"PDF has too many pages (max {_MAX_PAGES}).")
    slides = []
    for i, page in enumerate(reader.pages, 1):
        text  = (page.extract_text() or "").strip()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if lines:
            slides.append({"slide_num": i, "title": lines[0][:80], "content": "\n".join(lines)})

    if not slides:
        raise ValueError(
            "No readable text found in the PDF — it may be a scanned/image-based file."
        )
    return slides


def _extract_docx(raw):
    """Extract text from .docx (Open XML Word) files, grouped by headings."""
    try:
        from docx import Document
    except ImportError:
        raise ValueError("python-docx not installed — run: pip install python-docx")

    doc = Document(io.BytesIO(raw))
    slides, current_title, current_lines, slide_num = [], "Document", [], 1
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        if para.style.name.startswith('Heading'):
            if current_lines:
                slides.append({"slide_num": slide_num, "title": current_title, "content": "\n".join(current_lines)})
                slide_num += 1
                current_lines = []
            current_title = text[:80]
        else:
            current_lines.append(text)
    if current_lines:
        slides.append({"slide_num": slide_num, "title": current_title, "content": "\n".join(current_lines)})
    if not slides:
        raise ValueError("No readable text found in the Word document.")
    return slides


def _extract_doc_ole(raw):
    """Extract text from old binary .doc via OLE2 stream decoding."""
    import olefile
    ole = olefile.OleFileIO(io.BytesIO(raw))
    if not ole.exists('WordDocument'):
        raise ValueError("Not a valid binary Word (.doc) file.")
    stream = ole.openstream('WordDocument').read()
    # Word stores main text as UTF-16-LE; extract printable runs
    try:
        text = stream.decode('utf-16-le', errors='ignore')
    except Exception:
        text = stream.decode('latin-1', errors='ignore')
    # Keep only printable chars + Arabic/newlines, strip control chars
    text = re.sub(r'[^\x20-\x7E؀-ۿÀ-ɏ\n\r\t]+', ' ', text)
    text = re.sub(r'[ \t]{3,}', '  ', text).strip()
    lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 3]
    if not lines:
        raise ValueError(
            "Could not extract readable text from this .doc file. "
            "Try saving it as .docx and uploading again."
        )
    # Group lines into pseudo-slides of 15 lines each
    slides = []
    for n, chunk in enumerate([lines[i:i+15] for i in range(0, len(lines), 15)], 1):
        slides.append({"slide_num": n, "title": chunk[0][:80], "content": "\n".join(chunk)})
    return slides


def _extract_txt(raw):
    """Extract text from a plain-text file (.txt)."""
    for enc in ('utf-8', 'utf-16', 'latin-1', 'cp1256'):
        try:
            text = raw.decode(enc, errors='strict')
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        text = raw.decode('utf-8', errors='replace')
    text = text.strip()
    if not text:
        raise ValueError("The text file appears to be empty.")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # Group into pseudo-slides of 20 lines
    slides = []
    for n, chunk in enumerate([lines[i:i+20] for i in range(0, len(lines), 20)], 1):
        slides.append({"slide_num": n, "title": chunk[0][:80], "content": "\n".join(chunk)})
    return slides


# ── Upload-parsing DoS guards ──────────────────────────────────────────────────
_MAX_UNCOMPRESSED = 300 * 1024 * 1024   # total decompressed bytes (zip-bomb guard)
_MAX_ZIP_RATIO    = 200                 # per-entry compression-ratio ceiling
_MAX_PAGES        = 1200                # hard cap on PDF pages / PPTX slides parsed

def _check_zip_bomb(raw):
    """Reject OOXML/zip inputs that would decompress to an unreasonable size.
    MAX_CONTENT_LENGTH only bounds the COMPRESSED upload; a 50 MB zip bomb can
    expand to many GB and OOM the instance."""
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            total = 0
            for zi in z.infolist():
                total += zi.file_size
                if total > _MAX_UNCOMPRESSED:
                    raise ValueError("File is too large when decompressed — refusing to process.")
                if (zi.compress_size > 0 and zi.file_size > 1_000_000
                        and (zi.file_size / zi.compress_size) > _MAX_ZIP_RATIO):
                    raise ValueError("File has a suspicious compression ratio — refusing to process.")
    except zipfile.BadZipFile:
        pass  # not a real zip; the downstream parser will reject it


def extract_slides(file_stream, filename=""):
    """Detect format from magic bytes (and filename for .txt) and dispatch."""
    raw = file_stream.read()
    fname = (filename or "").lower()

    if raw[:4] == b'PK\x03\x04':                         # ZIP-based (pptx or docx)
        _check_zip_bomb(raw)
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                names = z.namelist()
            if any(n.startswith('word/') for n in names):
                return _extract_docx(raw)
        except Exception:
            pass
        return _extract_pptx_raw(raw)

    if raw[:8] == b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1':  # OLE2 (ppt or doc)
        try:
            import olefile
            with olefile.OleFileIO(io.BytesIO(raw)) as ole:
                if ole.exists('WordDocument'):
                    return _extract_doc_ole(raw)
        except Exception:
            pass
        return _extract_ppt_binary(raw)

    if raw[:4] == b'%PDF':                                # PDF
        return _extract_pdf(raw)

    if fname.endswith('.txt') or fname.endswith('.md'):   # Plain text
        return _extract_txt(raw)

    # Last resort: try decoding as plain text
    try:
        decoded = raw.decode('utf-8', errors='strict')
        if len(decoded.strip()) > 50:
            return _extract_txt(raw)
    except UnicodeDecodeError:
        pass

    raise ValueError(
        "Unrecognised file format. Supported: .pptx, .ppt, .pdf, .docx, .doc, .txt"
    )


# ── PDF builder ────────────────────────────────────────────────────────────────

def _st(name, parent, **kw):
    s = ParagraphStyle(name, parent=parent)
    for k, v in kw.items(): setattr(s, k, v)
    return s

def _page_num(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 7.5)
    canvas.setFillColor(TEXT_LIGHT)
    n = canvas.getPageNumber()
    canvas.drawRightString(doc.width + doc.leftMargin, 0.55*cm, f"{n}")
    # NB: the running footer uses Helvetica (no Arabic glyphs), so we do NOT draw
    # the guide title here — an Arabic title rendered as ▯▯▯ tofu. The title is
    # already on the cover. Keep only the page number + the Latin brand mark.
    # Brand mark on every page — a free viral loop when guides get shared.
    canvas.drawCentredString(doc.width/2 + doc.leftMargin, 0.55*cm, "Made with alimne.app")
    canvas.restoreState()


def build_pdf(guide, language, out_filename="study_guide"):
    if not isinstance(guide, dict):
        guide = {}
    guide["sections"]   = [s for s in _as_list(guide.get("sections"))   if isinstance(s, dict)]
    guide["keywords"]   = [k for k in _as_list(guide.get("keywords"))   if isinstance(k, dict)]
    guide["flashcards"] = [f for f in _as_list(guide.get("flashcards")) if isinstance(f, dict)]
    guide["mcqs"]       = [m for m in _as_list(guide.get("mcqs"))       if isinstance(m, dict)]
    guide["objectives"] = [o for o in _as_list(guide.get("objectives")) if isinstance(o, str)]

    is_ar = (language == "ar")
    ar_ok = is_ar and _ensure_arabic_font()
    AF    = _ARABIC_FONT if ar_ok else "Helvetica"
    AFB   = _ARABIC_FONT if ar_ok else "Helvetica-Bold"
    ALIGN = TA_RIGHT if is_ar else TA_LEFT

    def _xesc(s):
        # reportlab Paragraph parses an intra-paragraph mini-markup (<b>, <font>,
        # <img src=…>). Model/source text must be XML-escaped or an injected
        # <img src="http://169.254.169.254/…"> would make the PDF builder itself
        # perform a blind SSRF, and any literal "&" (e.g. "R&D") would break the
        # whole build. All app-added markup is added OUTSIDE this function.
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _clean(text):
        # Scrub any bullet glyph the model embedded in the text (leading or inline)
        # BEFORE Arabic reshaping/escaping, so no •/▪/■/… ever reaches the PDF from
        # any field — objectives, section titles, keywords, flashcards or quiz.
        # _debullet preserves hyphens, ranges and formula middle-dots (CuSO4·5H2O).
        return _pdf_normalize(_debullet(str(text)))

    def T(text):
        # Paragraph markup for one field. Arabic is reordered as ONE line here, so
        # use it only for text that never wraps or is mixed with tags (the footer);
        # everything else goes through P().
        s = _clean(text)
        if ar_ok:                      # what the Arabic font lacks is drawn in Helvetica
            return _ar_pdf_markup(_ar_display(_ar_pdf_text(_ar_shape(s))))
        if is_ar:                      # Arabic font unavailable: keep the text as-is
            return _xesc(s)
        return _pdf_latin_markup(s)    # escapes too; no glyph Helvetica can't draw

    def P(text, style, prefix=""):
        # Paragraph for one plain-text field (`prefix` is app text, e.g. "3.  ").
        # Arabic is wrapped in logical order and then reordered line by line
        # (_ArabicParagraph); reordering the whole string first put the lines of a
        # multi-line paragraph in reverse order. Every paragraph of an Arabic guide
        # runs right-to-left, even one that starts with a Latin term ("DNA هو ...").
        # English, and Arabic without its font, is exactly the old
        # Paragraph(prefix + T(text)).
        if ar_ok:
            shaped = prefix + _ar_shape(_clean(text))
            # Right-to-left whenever the text has Arabic in it ("DNA هو ..."); a purely
            # Latin field (an English key term "Term (EN)") keeps its own direction, or
            # forced RTL would move its closing bracket to the wrong end.
            return _ArabicParagraph(shaped, style,
                                    base_dir="R" if _AR_LETTER_RE.search(shaped) else None)
        return Paragraph(prefix + T(text), style)

    AR_GUIDE, AR_LUCK = "دليل الدراسة بالذكاء الاصطناعي", "حظ سعيد!"   # footer (logical order)
    L = {
        "objectives": T("الأهداف التعليمية") if is_ar else "LEARNING OBJECTIVES",
        "obj_bullet": "",
        "contents":   T("المحتويات") if is_ar else "CONTENTS",
        "kw_head":    T("قاموس المصطلحات") if is_ar else "KEY TERMS",
        "toc_extra":  ["قاموس المصطلحات", "بطاقات المراجعة"] if is_ar
                      else ["KEY TERMS", "FLASH CARDS"],
        "fc_head":    T("بطاقات المراجعة") if is_ar else "FLASH CARDS",
        "sec_bullet": "",
        "bul_bullet": "",
        "q_pre":      "" if is_ar else "Q. ",
        "guide":      T(AR_GUIDE) if is_ar else "AI Exam Study Guide",
        "luck":       T(AR_LUCK) if is_ar else "Good luck!",
    }

    buf = io.BytesIO()
    W   = 17.4*cm

    class Doc(BaseDocTemplate):
        pass

    doc = Doc(buf, pagesize=A4,
              leftMargin=1.8*cm, rightMargin=1.8*cm,
              topMargin=1.8*cm, bottomMargin=1.5*cm)
    doc.title_str = guide.get("title", "")

    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height - 0.3*cm,
                  id='main', leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id='main', frames=[frame], onPage=_page_num)])

    base = getSampleStyleSheet()["Normal"]
    ST = {
        "h_title":  _st("HT",  base, fontSize=20, fontName=AFB, textColor=WHITE,        alignment=TA_CENTER, leading=26),
        "h_sub":    _st("HS",  base, fontSize=9,  fontName=AF,  textColor=colors.HexColor("#a8c4e8"), alignment=TA_CENTER),
        "obj_head": _st("OH",  base, fontSize=11, fontName=AFB, textColor=NAVY,         spaceBefore=4, spaceAfter=4, alignment=ALIGN),
        "obj_item": _st("OI",  base, fontSize=9.5,fontName=AF,  textColor=TEXT,         leftIndent=0 if is_ar else 14, rightIndent=14 if is_ar else 0, spaceAfter=3, leading=16, alignment=ALIGN),
        "toc_title":_st("TOT", base, fontSize=11, fontName=AFB, textColor=NAVY,         spaceAfter=6, alignment=ALIGN),
        "toc_item": _st("TOI", base, fontSize=9.5,fontName=AF,  textColor=TEXT,         leftIndent=0 if is_ar else 10, rightIndent=10 if is_ar else 0, spaceAfter=2, alignment=ALIGN),
        "sec_title":_st("SCT", base, fontSize=11, fontName=AFB, textColor=WHITE,        alignment=ALIGN),
        "bullet":   _st("BL",  base, fontSize=9.5,fontName=AF,  textColor=TEXT,         leftIndent=0 if is_ar else 12, rightIndent=12 if is_ar else 0, spaceAfter=3, leading=16, alignment=ALIGN),
        "para":     _st("PARA",base, fontSize=9.5,fontName=AF,  textColor=TEXT,         spaceAfter=7, leading=16.5, alignment=(ALIGN if is_ar else TA_JUSTIFY)),
        "tbl_hdr":  _st("TH",  base, fontSize=9,  fontName=AFB, textColor=WHITE,        alignment=ALIGN),
        "tbl_cell": _st("TC",  base, fontSize=9,  fontName=AF,  textColor=TEXT,         leading=14, alignment=ALIGN),
        "kw_term":  _st("KT",  base, fontSize=9,  fontName=AFB, textColor=NAVY_MID,     alignment=ALIGN),
        "kw_def":   _st("KD",  base, fontSize=9,  fontName=AF,  textColor=TEXT,         leading=14, alignment=ALIGN),
        "kw_head":  _st("KH",  base, fontSize=11, fontName=AFB, textColor=WHITE,        alignment=TA_CENTER),
        "fc_q":     _st("FCQ", base, fontSize=9,  fontName=AFB, textColor=WHITE,        leading=14, alignment=ALIGN),
        "fc_a":     _st("FCA", base, fontSize=9,  fontName=AF,  textColor=TEXT,         leading=14, alignment=ALIGN),
        "fc_head":  _st("FCH", base, fontSize=11, fontName=AFB, textColor=WHITE,        alignment=TA_CENTER),
        "footer":   _st("FT",  base, fontSize=8,  fontName=AF,  textColor=TEXT_LIGHT,   alignment=TA_CENTER),
    }

    elems = []

    # ── Header ────────────────────────────────────────────────────────────────
    raw_title = str(guide.get("title") or "Study Guide")
    hdr = Table([
        [P(raw_title.upper() if not is_ar else raw_title, ST["h_title"])],
        [P(guide.get("subtitle", "Exam Study Guide"), ST["h_sub"])],
    ], colWidths=[W])
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), NAVY),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("TOPPADDING",    (0,0), (0,0),   16),
        ("BOTTOMPADDING", (0,1), (0,1),   14),
        ("TOPPADDING",    (0,1), (0,1),   2),
        ("LEFTPADDING",   (0,0), (-1,-1), 12),
        ("RIGHTPADDING",  (0,0), (-1,-1), 12),
    ]))
    elems.append(hdr)
    elems.append(Spacer(1, 0.3*cm))

    # ── Learning Objectives ───────────────────────────────────────────────────
    objectives = guide.get("objectives", [])
    if objectives:
        rows = [[Paragraph(L["objectives"], ST["obj_head"])]]
        for o in objectives:
            rows.append([P(o, ST["obj_item"], prefix=L["obj_bullet"])])
        t = Table(rows, colWidths=[W])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0),  SECTION_BG),
            ("BOX",           (0,0), (-1,-1), 0.8, BORDER),
            ("LINEBELOW",     (0,0), (-1,0),  0.8, BORDER),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("LEFTPADDING",   (0,0), (-1,-1), 10),
            ("RIGHTPADDING",  (0,0), (-1,-1), 10),
        ]))
        elems.append(t)
        elems.append(Spacer(1, 0.3*cm))

    # ── Table of Contents ─────────────────────────────────────────────────────
    sections = guide.get("sections", [])
    if sections:
        toc_rows = [[Paragraph(L["contents"], ST["toc_title"])]]
        toc_names = [s.get("title", "") for s in sections] + L["toc_extra"]
        for i, name in enumerate(toc_names, 1):
            dot_row = Table(
                [[P(name, ST["toc_item"], prefix=f"{i}.  "), Paragraph("", ST["toc_item"])]],
                colWidths=[W*0.85, W*0.15]
            )
            dot_row.setStyle(TableStyle([
                ("LINEBELOW",     (0,0), (-1,-1), 0.3, BORDER),
                ("TOPPADDING",    (0,0), (-1,-1), 3),
                ("BOTTOMPADDING", (0,0), (-1,-1), 3),
                ("LEFTPADDING",   (0,0), (-1,-1), 6),
                ("RIGHTPADDING",  (0,0), (-1,-1), 6),
            ]))
            toc_rows.append([dot_row])
        toc = Table(toc_rows, colWidths=[W])
        toc.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0),  SECTION_BG),
            ("BOX",           (0,0), (-1,-1), 0.8, BORDER),
            ("TOPPADDING",    (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("LEFTPADDING",   (0,0), (-1,-1), 0),
        ]))
        elems.append(toc)
        elems.append(Spacer(1, 0.35*cm))

    # ── Sections ──────────────────────────────────────────────────────────────
    for idx, sec in enumerate(sections, 1):
        block = []

        _st_raw = str(sec.get("title", ""))
        # Upper-case BEFORE T()/P(): T() returns markup (&amp;, <font face="Symbol">)
        # that must not be upper-cased.
        sec_hdr = Table(
            [[P(_st_raw if is_ar else _st_raw.upper(), ST["sec_title"],
                prefix=f"{L['sec_bullet']}{idx} · ")]],
            colWidths=[W]
        )
        sec_hdr.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), NAVY_MID),
            ("TOPPADDING",    (0,0), (-1,-1), 7),
            ("BOTTOMPADDING", (0,0), (-1,-1), 7),
            ("LEFTPADDING",   (0,0), (-1,-1), 10),
            ("RIGHTPADDING",  (0,0), (-1,-1), 10),
        ]))
        block.append(sec_hdr)

        bullets = sec.get("bullets", [])
        if bullets:
            # Clear prose paragraphs — no bullet glyphs, no separator lines between
            # points. Each point is a justified paragraph inside one soft panel.
            bdata = [[P(_debullet(b), ST["para"])] for b in bullets]
            bt = Table(bdata, colWidths=[W])
            bt.setStyle(TableStyle([
                ("TOPPADDING",    (0,0),  (0,0),   7),
                ("BOTTOMPADDING", (0,-1), (0,-1),  7),
                ("TOPPADDING",    (0,1),  (-1,-1), 1),
                ("BOTTOMPADDING", (0,0),  (-1,-2), 1),
                ("LEFTPADDING",   (0,0),  (-1,-1), 12),
                ("RIGHTPADDING",  (0,0),  (-1,-1), 12),
                ("BOX",           (0,0),  (-1,-1), 0.5, BORDER),
            ]))
            block.append(bt)

        tbl = sec.get("table")
        if isinstance(tbl, dict) and _as_list(tbl.get("headers")) and _as_list(tbl.get("rows")):
            headers = _as_list(tbl["headers"])
            n_cols  = len(headers)
            col_w   = W / n_cols
            # Arabic tables run right-to-left: the first column is drawn on the
            # right (like the key-terms table). Every column has the same width
            # and no column-specific style, so reversing the cells is enough.
            rtl = (lambda cells: cells[::-1]) if is_ar else (lambda cells: cells)
            tbl_rows = [rtl([P(h, ST["tbl_hdr"]) for h in headers])]
            for ri, row in enumerate(_as_list(tbl["rows"])):
                padded = ((row if isinstance(row, list) else [row]) + [""] * n_cols)[:n_cols]
                tbl_rows.append(rtl([P(str(c), ST["tbl_cell"]) for c in padded]))
            inner = Table(tbl_rows, colWidths=[col_w]*n_cols)
            ts = [
                ("BACKGROUND",    (0,0), (-1,0),  NAVY_LIGHT),
                ("TOPPADDING",    (0,0), (-1,-1), 5),
                ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                ("LEFTPADDING",   (0,0), (-1,-1), 7),
                ("GRID",          (0,0), (-1,-1), 0.4, BORDER),
            ]
            for ri in range(1, len(tbl_rows)):
                if ri % 2 == 0:
                    ts.append(("BACKGROUND", (0,ri), (-1,ri), ROW_ALT))
            inner.setStyle(TableStyle(ts))
            block.append(Spacer(1, 0.15*cm))
            block.append(inner)

        block.append(Spacer(1, 0.3*cm))
        elems.append(KeepTogether(block))

    # ── Keywords Cheatsheet ───────────────────────────────────────────────────
    keywords = guide.get("keywords", [])
    if keywords:
        kw_hdr = Table(
            [[Paragraph(L["kw_head"], ST["kw_head"])]],
            colWidths=[W]
        )
        kw_hdr.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), NAVY),
            ("TOPPADDING",    (0,0), (-1,-1), 8),
            ("BOTTOMPADDING", (0,0), (-1,-1), 8),
            ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ]))
        elems.append(kw_hdr)

        if is_ar:
            # Arabic: definition left, term right (visual RTL order)
            lc, rc = W*0.60, W*0.40
            kw_rows = [[
                P(k.get("definition", ""), ST["kw_def"]),
                P(k.get("term", ""),       ST["kw_term"]),
            ] for k in keywords]
        else:
            lc, rc = W*0.27, W*0.73
            kw_rows = [[
                P(k.get("term", ""),       ST["kw_term"]),
                P(k.get("definition", ""), ST["kw_def"]),
            ] for k in keywords]
        kw_t = Table(kw_rows, colWidths=[lc, rc])
        kts = [
            ("VALIGN",        (0,0), (-1,-1), "TOP"),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("LEFTPADDING",   (0,0), (-1,-1), 8),
            ("RIGHTPADDING",  (0,0), (-1,-1), 8),
            ("LINEBELOW",     (0,0), (-1,-2), 0.3, BORDER),
            ("BOX",           (0,0), (-1,-1), 0.5, BORDER),
        ]
        for ri in range(len(kw_rows)):
            if ri % 2 == 0:
                kts.append(("BACKGROUND", (0,ri), (-1,ri), KW_BG))
        kw_t.setStyle(TableStyle(kts))
        elems.append(kw_t)
        elems.append(Spacer(1, 0.35*cm))

    # ── Flash Cards ───────────────────────────────────────────────────────────
    flashcards = guide.get("flashcards", [])
    if flashcards:
        fc_hdr = Table(
            [[Paragraph(L["fc_head"], ST["fc_head"])]],
            colWidths=[W]
        )
        fc_hdr.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), NAVY),
            ("TOPPADDING",    (0,0), (-1,-1), 8),
            ("BOTTOMPADDING", (0,0), (-1,-1), 8),
            ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ]))
        elems.append(fc_hdr)
        elems.append(Spacer(1, 0.2*cm))

        # Full-width cards — one per row: a coloured question header over the
        # answer. Cleaner and far more readable than the old cramped 2-up grid
        # (mismatched heights + awkward mid-word wraps).
        for fc in flashcards:
            if not T(fc.get('q', '')) and not T(fc.get('a', '')):
                continue
            card = Table([
                [P(fc.get('q', ''), ST["fc_q"], prefix=L["q_pre"])],
                [P(fc.get('a', ''), ST["fc_a"])],
            ], colWidths=[W])
            card.setStyle(TableStyle([
                ("BACKGROUND",    (0,0), (-1,0),  CARD_Q),
                ("BACKGROUND",    (0,1), (-1,1),  CARD_A),
                ("TOPPADDING",    (0,0), (-1,-1), 8),
                ("BOTTOMPADDING", (0,0), (-1,-1), 8),
                ("LEFTPADDING",   (0,0), (-1,-1), 12),
                ("RIGHTPADDING",  (0,0), (-1,-1), 12),
                ("BOX",           (0,0), (-1,-1), 0.6, BORDER),
                ("LINEBELOW",     (0,0), (-1,0),  0.5, BORDER),
            ]))
            elems.append(card)
            elems.append(Spacer(1, 0.18*cm))

    # ── Footer ────────────────────────────────────────────────────────────────
    elems.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    elems.append(Spacer(1, 0.1*cm))
    made_with = "Made with <b>alimne.app</b> — turn any lecture into a study guide"
    if ar_ok:
        # One logical string through P(): reordering it as ONE line (T) put the
        # title last for a right-to-left reader and reversed its lines if it ever
        # wrapped. The separator is U+2010 because the Arabic font has no "·", and
        # the Latin line gets its own Helvetica paragraph because it has no Latin
        # letters either.
        sep = " \N{HYPHEN} "
        elems.append(P(f"{guide.get('title', '')}{sep}{AR_GUIDE}{sep}{AR_LUCK}", ST["footer"]))
        elems.append(Paragraph(made_with, _st("FTL", ST["footer"], fontName="Helvetica")))
    else:
        elems.append(Paragraph(
            f"{T(guide.get('title',''))}  ·  {L['guide']}  ·  {L['luck']}<br/>" + made_with,
            ST["footer"]
        ))

    doc.multiBuild(elems)
    buf.seek(0)
    return buf


# ── Public config endpoint ────────────────────────────────────────────────────
# /api/config gates the whole sign-in UI, so it must never wait on the DB. The
# durable anon counter runs on a small pool with a short deadline; a slow or
# down Supabase just falls back to the in-memory count (the free limit for a
# fresh visitor). In-flight lookups are capped so a hung DB can't pile up work.
_cfg_pool          = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cfg")
_cfg_inflight      = [0]
_cfg_inflight_lock = threading.Lock()
_CFG_RPC_TIMEOUT   = 1.5
_CFG_MAX_INFLIGHT  = 8

def _cfg_fast(lookup, dev):
    if not dev or _get_sb() is None:
        return None
    with _cfg_inflight_lock:
        if _cfg_inflight[0] >= _CFG_MAX_INFLIGHT:
            return None
        _cfg_inflight[0] += 1
    def _run():
        try:
            return lookup(dev)
        finally:
            with _cfg_inflight_lock:
                _cfg_inflight[0] -= 1
    try:
        fut = _cfg_pool.submit(_run)
    except Exception:
        with _cfg_inflight_lock:
            _cfg_inflight[0] -= 1
        return None
    try:
        return fut.result(timeout=_CFG_RPC_TIMEOUT)
    except Exception:
        return None   # timeout/error → caller falls back

def _anon_durable_remaining_fast(dev):
    return _cfg_fast(_anon_durable_remaining, dev)

def _anon_gate_remaining_fast(gate):
    return _cfg_fast(_anon_gate_remaining, gate)

@app.route("/api/config")
def api_config():
    """Return public keys the frontend needs to initialise Supabase and Stripe.
    Free mode also describes the sign-in gate: how many guides need no account
    (anon_free_limit / signin_after) and how many this device has left."""
    dev = _device_id(request)
    out = {
        "supabase_url":          SUPABASE_URL,
        "supabase_anon_key":     SUPABASE_ANON_KEY,
        "stripe_publishable_key": STRIPE_PUBLISHABLE_KEY,
        "auth_enabled":          _AUTH_ENABLED,
    }
    if FREE_MODE:
        anon_limit = max(0, ANON_FREE_USES)
        # Read-only and never blocking: a slow or missing database shows the full
        # allowance (the charge itself is what enforces the gate).
        d = _anon_gate_remaining_fast(_anon_gate(dev, _client_ip())) if anon_limit else None
        out.update({
            "anon_free_limit": anon_limit,
            "anon_remaining":  min(anon_limit, max(0, d)) if d is not None else anon_limit,
            "free_mode":       True,
            # device_daily is kept only so an older cached client does not break.
            "fair_use":        {"anon_free_uses": anon_limit, "user_daily": FAIR_USER_DAILY,
                                "device_daily": anon_limit},
            "signin_after":    anon_limit,
        })
    else:
        d = _anon_durable_remaining_fast(dev)
        out.update({
            "anon_free_limit": ANON_FREE_LIMIT,
            "anon_remaining":  d if d is not None else _anon_remaining(_client_ip()),
            "free_mode":       False,
            "fair_use":        {"device_daily": FAIR_DEVICE_DAILY, "user_daily": FAIR_USER_DAILY},
        })
    return jsonify(out)


# ── Auth — current user ────────────────────────────────────────────────────────
def _parse_ts(v):
    """ISO timestamp from Supabase → aware datetime (UTC if naive), or None."""
    from datetime import datetime, timezone
    if not v:
        return None
    s = str(v).strip().replace("Z", "+00:00").replace(" ", "T", 1)
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        try:   # Python < 3.11 only takes 3 or 6 fractional digits — drop them
            d = datetime.fromisoformat(re.sub(r"\.\d+", "", s, count=1))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def _effective_plan_tokens(user, now=None):
    """(plan, tokens) as the consume_token RPC would see them (migrations 006/010):
    Pro = status 'active' and period_end unset or in the future; on a new UTC
    month the balance resets to 30 (Pro) or 3 (free). auth_me only READS this —
    the RPC still owns the actual reset on the next generation."""
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc)
    pe = _parse_ts(user.get("subscription_period_end"))
    active = user.get("subscription_status") == "active" and (pe is None or pe > now)
    tokens = user.get("tokens_remaining") or 0
    if user.get("tokens_month") != now.strftime("%Y-%m"):
        tokens = 30 if active else 3
    return ("pro" if active else "free"), tokens

def _retry_503(msg="Couldn't load your account — please try again in a moment."):
    return jsonify({"error": msg, "code": "retry"}), 503

@app.route("/api/auth/me")
def auth_me():
    uid, payload, err = _auth_payload(request)   # verify the token once
    if err:
        return err
    if uid == "dev":
        return jsonify({"email": "dev@local", "name": "Dev", "tokens_remaining": 999,
                        "subscription_status": "active", "plan": "pro",
                        "referral_code": "DEVLOCAL", "free_mode": FREE_MODE})
    ident = _identity_from_payload(payload)
    sb    = _get_sb()
    try:
        user = _get_user(uid)
        if not user and sb:
            # Row missing (signup trigger didn't run) — create it from the token.
            # ON CONFLICT DO NOTHING: never overwrite a row we merely failed to read.
            sb.table("users").upsert({
                "id": uid, "email": ident["email"],
                "name": ident["name"] or None, "avatar_url": ident["avatar"] or None,
            }, ignore_duplicates=True).execute()
            user = _get_user(uid)
    except Exception as exc:
        _log.error("auth_me account read failed for %s: %s", uid, exc)
        return _retry_503()
    if not user:
        # Never answer with a field-less row (it showed paying users '0 · Free').
        return _retry_503()
    if sb:
        # Backfill name/avatar/email from Google if we don't have them yet.
        patch = {}
        if ident["name"]   and not user.get("name"):       patch["name"]       = ident["name"]
        if ident["avatar"] and not user.get("avatar_url"): patch["avatar_url"] = ident["avatar"]
        if ident["email"]  and not user.get("email"):      patch["email"]      = ident["email"]
        if patch:
            try:
                sb.table("users").update(patch).eq("id", uid).execute()
                user.update(patch)
            except Exception as exc:
                _log.error("auth_me backfill failed: %s", exc)
    ref_code = user.get("referral_code") or _get_or_create_referral_code(uid)
    plan, tokens = _effective_plan_tokens(user)
    return jsonify({
        "id":                      user["id"],
        "email":                   user.get("email") or "",
        "name":                    user.get("name") or "",
        "avatar_url":              user.get("avatar_url") or "",
        # Effective balance: applies the month-rollover reset the consume_token
        # RPC would apply, so the badge isn't '0' on the 1st of the month.
        "tokens_remaining":        tokens,
        "plan":                    plan,   # 'pro' only while the paid period is current
        "subscription_status":     user.get("subscription_status", "free"),
        "subscription_period_end": str(user.get("subscription_period_end") or ""),
        # Lets the Account panel offer "Manage / cancel subscription" to anyone
        # with a Stripe billing account, even while status is still catching up.
        "has_billing":             bool(user.get("stripe_customer_id")),
        "referral_code":           ref_code or "",
        # Free mode: tokens_remaining above is meaningless (the client hides it).
        "free_mode":               FREE_MODE,
    })


# ── Referral — apply code ─────────────────────────────────────────────────────
@app.route("/api/referral/apply", methods=["POST"])
def referral_apply():
    uid, err = _auth_check(request)
    if err:
        return err
    if uid == "dev":
        return jsonify({"success": False, "reason": "dev_mode"})
    # A non-object body or a non-string code ({"code": null}, a number…) used
    # to 500 on .get()/.strip(); it is the same 400 'no_code' as a blank code.
    data = request.get_json(silent=True)
    code = data.get("code") if isinstance(data, dict) else None
    code = code.strip().upper() if isinstance(code, str) else ""
    if not code:
        return jsonify({"success": False, "reason": "no_code"}), 400
    sb = _get_sb()
    if not sb:
        return jsonify({"success": False, "reason": "unavailable"})
    try:
        # Find referrer by code (cannot self-refer)
        ref = sb.table("users").select("id").eq("referral_code", code).neq("id", uid).execute()
        if not ref.data:
            return jsonify({"success": False, "reason": "invalid_code"})
        referrer_id = ref.data[0]["id"]
        # Apply only if not already referred
        sb.table("users").update({"referred_by": referrer_id}).eq("id", uid).is_("referred_by", "null").execute()
        # Remove stored code from client regardless (avoid re-tries)
        return jsonify({"success": True})
    except Exception as exc:
        _log.error(f"referral_apply error: {exc}")
        return jsonify({"success": False, "reason": "db_error"}), 500


# ── Referral — stats ───────────────────────────────────────────────────────────
@app.route("/api/referral/stats")
def referral_stats():
    uid, err = _auth_check(request)
    if err:
        return err
    if uid == "dev":
        return jsonify({"total": 0, "paid": 0, "tokens_earned": 0})
    sb = _get_sb()
    if not sb:
        return jsonify({"total": 0, "paid": 0, "tokens_earned": 0})
    try:
        rows = sb.table("users").select("referral_paid").eq("referred_by", uid).execute()
        total = len(rows.data) if rows.data else 0
        paid  = sum(1 for r in (rows.data or []) if r.get("referral_paid"))
        return jsonify({"total": total, "paid": paid,
                        "tokens_earned": 0 if FREE_MODE else paid * 10})
    except Exception:
        return jsonify({"total": 0, "paid": 0, "tokens_earned": 0})


# ── Stripe — create checkout session ──────────────────────────────────────────
def _has_live_subscription(customer_id, user):
    """Does this Stripe customer already have a running subscription? Stripe is
    the source of truth; if it can't answer, fall back to our stored status."""
    try:
        subs = _stripe.Subscription.list(customer=customer_id, status="all", limit=10)
        return any(getattr(s, "status", None) in ("active", "trialing", "past_due")
                   for s in (getattr(subs, "data", None) or []))
    except Exception as exc:
        _log.warning("checkout: subscription lookup failed for %s: %s", customer_id, exc)
        return user.get("subscription_status") == "active"

_FREE_NOW_EN = "Alimne is free now - no subscription needed."
_FREE_NOW_AR = "علّمني مجاني الآن — لا حاجة لأي اشتراك."

@app.route("/api/stripe/checkout", methods=["POST"])
def stripe_checkout():
    if FREE_MODE:
        # Nothing to buy: never create a Stripe session. (The billing portal and
        # the webhook are untouched — existing subscribers can still manage/cancel.)
        return jsonify({"error": _FREE_NOW_AR if _wants_ar() else _FREE_NOW_EN,
                        "code": "free_now"}), 410
    uid, err = _auth_check(request)
    if err:
        return err
    if not _stripe or not STRIPE_PRICE_ID:
        return jsonify({"error": "Payments not configured"}), 503

    try:
        user = _get_user(uid)
    except Exception as exc:
        _log.error("checkout account read failed for %s: %s", uid, exc)
        return _retry_503("Couldn't reach your account — please try again in a moment.")
    if not user:
        return jsonify({"error": "User not found"}), 404

    try:
        # Reuse existing Stripe customer or create a new one. IMPORTANT: validate a
        # stored id still exists in THIS Stripe account — if the account or API keys
        # were swapped, the old id is orphaned and checkout fails with
        # "No such customer". Verify (and recreate on miss) instead of blindly reusing.
        customer_id = user.get("stripe_customer_id")
        if customer_id:
            try:
                c = _stripe.Customer.retrieve(customer_id)
                if getattr(c, "deleted", False):
                    customer_id = None
            except Exception:
                customer_id = None          # stale/invalid id → recreate below
        if not customer_id:
            cust = _stripe.Customer.create(
                email=user["email"],
                name=user.get("name", ""),
                metadata={"supabase_id": uid},
            )
            customer_id = cust["id"]
            _get_sb().table("users").update(
                {"stripe_customer_id": customer_id}
            ).eq("id", uid).execute()
        elif _has_live_subscription(customer_id, user):
            # Already paying (e.g. a stale period_end shows them as Free) — a second
            # checkout would bill twice. Send them to the billing portal instead.
            portal = _stripe.billing_portal.Session.create(customer=customer_id, return_url=APP_URL)
            return jsonify({"url": portal.url, "code": "already_subscribed"})

        session = _stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            mode="subscription",
            # Collect address + phone: gives Stripe's fraud engine more legit
            # signals (AVS, verified contact) and cuts false-positive blocks.
            billing_address_collection="required",
            phone_number_collection={"enabled": True},
            customer_update={"address": "auto", "name": "auto"},
            success_url=f"{APP_URL}/?sub=success",
            cancel_url=f"{APP_URL}/?sub=canceled",
            metadata={"user_id": uid},
        )
        return jsonify({"url": session.url})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Stripe — customer billing portal ──────────────────────────────────────────
@app.route("/api/stripe/portal", methods=["POST"])
def stripe_portal():
    uid, err = _auth_check(request)
    if err:
        return err
    if not _stripe:
        return jsonify({"error": "Payments not configured"}), 503

    try:
        user = _get_user(uid)
    except Exception as exc:
        _log.error("portal account read failed for %s: %s", uid, exc)
        return _retry_503("Couldn't reach your account — please try again in a moment.")
    if not user or not user.get("stripe_customer_id"):
        return jsonify({"error": "No billing account found"}), 404

    try:
        portal = _stripe.billing_portal.Session.create(
            customer=user["stripe_customer_id"],
            return_url=APP_URL,
        )
        return jsonify({"url": portal.url})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Liveness probe ─────────────────────────────────────────────────────────────
# Render's Health Check Path points here. Deliberately trivial — no DB, network
# or auth — so it answers only "is this process serving requests?". When it stops
# answering, Render restarts/replaces the instance automatically instead of the
# site sitting on 502, and zero-downtime deploys only switch traffic to a new
# instance once it passes this check.
# Render sets RENDER_GIT_COMMIT on every deploy; exposing it lets the nightly
# debug routine confirm its own push is the version actually serving traffic.
_DEPLOY_VERSION = os.environ.get("RENDER_GIT_COMMIT", "")[:12]

@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "version": _DEPLOY_VERSION})


# ── Stripe — webhook ───────────────────────────────────────────────────────────
# Bounded in-memory idempotency guard: Stripe redelivers events (retries,
# manual resends), and our handlers overwrite token balances — replaying a
# checkout.completed would re-grant tokens the user already spent.
_processed_events       = set()
_processed_events_order = []
_proc_events_lock       = threading.Lock()

def _event_seen(eid):
    if not eid:
        return False
    with _proc_events_lock:
        return eid in _processed_events

def _mark_event_processed(eid):
    if not eid:
        return
    with _proc_events_lock:
        if eid in _processed_events:
            return
        _processed_events.add(eid)
        _processed_events_order.append(eid)
        if len(_processed_events_order) > 2000:
            _processed_events.discard(_processed_events_order.pop(0))

def _period_end_iso(sub):
    # current_period_end moved from the subscription top level onto its items
    # in recent Stripe API versions — fall back to the first item.
    period_end = sub.get("current_period_end")
    if not period_end:
        items = (sub.get("items") or {}).get("data") or []
        period_end = items[0].get("current_period_end") if items else None
    if not period_end:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(period_end, tz=timezone.utc).isoformat()

@app.route("/api/stripe/webhook", methods=["POST"])
def stripe_webhook():
    if not _stripe:
        return jsonify({"error": "Payments not configured"}), 503

    payload   = request.get_data()
    sig       = request.headers.get("Stripe-Signature", "")
    try:
        # construct_event is used only to VERIFY the signature. Since
        # stripe-python v13 its StripeObject is no longer a dict (no .get()),
        # which made every real event 500 — so read the verified payload as
        # plain JSON dicts instead.
        _stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        event = json.loads(payload)
    except ValueError:
        return jsonify({"error": "Invalid payload"}), 400
    except _stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400

    # Ack redelivered events without re-running side effects. An event is only
    # marked processed AFTER it succeeds, so a failed attempt can be retried.
    eid = event.get("id")
    if _event_seen(eid):
        return jsonify({"ok": True, "deduped": True})

    sb  = _get_sb()
    typ = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    try:
        if typ == "checkout.session.completed":
            user_id = (obj.get("metadata") or {}).get("user_id")
            if user_id and sb:
                update = {
                    "subscription_status": "active",
                    "tokens_remaining":    30,
                    "tokens_month":        time.strftime("%Y-%m"),
                }
                if obj.get("subscription"):
                    update["subscription_id"] = obj["subscription"]
                if obj.get("customer"):
                    update["stripe_customer_id"] = obj["customer"]
                sb.table("users").update(update).eq("id", user_id).execute()
                try:
                    _award_referral(user_id, sb)   # reward referrer if applicable
                except Exception:
                    _log.error("referral award failed for %s:\n%s", user_id, _tb.format_exc())

        elif typ in ("customer.subscription.created",
                     "customer.subscription.updated",
                     "customer.subscription.deleted"):
            cust_id = obj.get("customer")
            status  = obj.get("status", "")
            if sb and cust_id:
                update = {"subscription_id": obj.get("id", "")}
                if typ == "customer.subscription.deleted":
                    update["subscription_status"] = "canceled"
                elif status in ("active", "trialing"):
                    update["subscription_status"] = "active"
                    period_end = _period_end_iso(obj)
                    if period_end:
                        update["subscription_period_end"] = period_end
                elif status in ("canceled", "unpaid", "past_due"):
                    update["subscription_status"] = status
                sb.table("users").update(update).eq("stripe_customer_id", cust_id).execute()

        elif typ == "invoice.payment_succeeded":
            cust_id = obj.get("customer")
            if obj.get("billing_reason") == "subscription_cycle" and sb and cust_id:
                sb.table("users").update({
                    "tokens_remaining": 30,
                    "tokens_month":     time.strftime("%Y-%m"),
                }).eq("stripe_customer_id", cust_id).execute()
    except Exception:
        _log.error("stripe webhook %s (%s) failed:\n%s", typ, eid, _tb.format_exc())
        return jsonify({"error": "Webhook handler failed"}), 500   # Stripe retries

    _mark_event_processed(eid)
    return jsonify({"ok": True})


# ── Email lead capture (shown before the paywall) ─────────────────────────────
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

@app.route("/api/lead", methods=["POST"])
def capture_lead():
    """Store an email captured at the paywall. No auth (it's a lead); validated
    and rate-limited; written with the service role into the RLS-locked leads
    table."""
    if not _check_rate_limit(_client_ip(), scope="lead", limit=10):
        return jsonify({"error": "Too many requests. Please wait a moment."}), 429
    data   = request.get_json(silent=True) or {}
    email  = str(data.get("email", "")).strip().lower()
    source = str(data.get("source", "paywall"))[:40]
    if not email or len(email) > 254 or not _EMAIL_RE.match(email):
        return jsonify({"error": "Please enter a valid email address."}), 400
    sb = _get_sb()
    if sb is None:
        return jsonify({"ok": True})  # dev mode — nothing to store
    try:
        sb.table("leads").upsert({
            "email":      email,
            "source":     source,
            "ip":         _client_ip(),
            "user_agent": (request.headers.get("User-Agent") or "")[:400],
        }, on_conflict="email").execute()
    except Exception as exc:
        _log.error("lead capture failed: %s", exc)
        return jsonify({"error": "Could not save right now — please try again."}), 500
    _log.info("Lead captured: %s (source=%s)", email, source)
    return jsonify({"ok": True})


# ── Request-field validation ───────────────────────────────────────────────────
# Runs BEFORE _charge_credit: a malformed field is a cheap 400 'bad_request' —
# never a spent credit followed by a 500 (e.g. {"text": 123} on /api/summarize-text
# charged, crashed on .strip() and was never refunded).
class _BadField(ValueError):
    """A request field (or the whole JSON body) has the wrong type."""
    def __init__(self, field):
        super().__init__(field)
        self.field = field

def _json_object():
    """The JSON body as a dict: no / unparsable body → {} (callers then report
    what is missing); a JSON array, string, number or bool → _BadField('body')."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise _BadField("body")
    return data

def _str_field(data, key, default=""):
    """data[key] as a str. Missing or null → `default`; a number, bool, list or
    object → _BadField (never silently str()'d)."""
    v = data.get(key)
    if v is None:
        return default
    if not isinstance(v, str):
        raise _BadField(key)
    return v

def _flag_field(data, key, default=True):
    """An on/off option sent as a bool or a string. Keeps the historical rule
    str(v).lower() != 'false' for any scalar; null → `default`; a list or
    object → _BadField."""
    v = data.get(key)
    if v is None:
        return default
    if isinstance(v, (list, dict)):
        raise _BadField(key)
    return str(v).lower() != "false"

def _wants_ar(data=None):
    """Answer in Arabic? The request's own `language` field decides; otherwise
    (auto / missing / malformed) the browser's Accept-Language."""
    lang = data.get("language") if isinstance(data, dict) else None
    if lang in ("ar", "en"):
        return lang == "ar"
    try:
        return request.accept_languages.best_match(("en", "ar")) == "ar"
    except Exception:
        return False

def _bad_request(en, ar, data=None, **extra):
    """400 for malformed input: code 'bad_request', text in the caller's language."""
    body = {"error": ar if _wants_ar(data) else en, "code": "bad_request"}
    body.update(extra)
    return jsonify(body), 400

_BAD_FIELD_EN = "Something in this request was malformed — please refresh the page and try again."
_BAD_FIELD_AR = "بعض بيانات هذا الطلب غير صالحة — يُرجى تحديث الصفحة والمحاولة مرة أخرى."

def _bad_field(exc, data=None):
    """400 for a _BadField; `field` names the offending input (for debugging)."""
    return _bad_request(_BAD_FIELD_EN, _BAD_FIELD_AR, data, field=exc.field)

_NO_TEXT_EN = "No text or URL provided"
_NO_TEXT_AR = "لم يتم إدخال أي نص أو رابط."

_BAD_URL_EN = "Only public http(s) URLs are supported — paste the full link, starting with https://"
_BAD_URL_AR = "لا نقبل إلا الروابط العامة (http أو https) — الصق الرابط كاملًا بدءًا بـ https://"

def _url_precheck(url):
    """Cheap checks on a pasted URL BEFORE a credit is charged (no DNS, no I/O):
    http(s), a host and a valid port, and not localhost or a literal private /
    loopback / link-local address. _fetch_url_text still screens the resolved
    IPs (and pins the connection) when it actually fetches."""
    try:
        p = _urlparse(url)
        host = p.hostname
        p.port                       # raises ValueError for an invalid port
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        addr = _ipaddress.ip_address(host)
    except ValueError:
        return True                  # a host name: resolved and screened at fetch time
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or
                addr.is_reserved or addr.is_multicast or addr.is_unspecified)


# ── SSE streaming endpoint ─────────────────────────────────────────────────────

def _sse(data):
    return f"data: {json.dumps(data)}\n\n"

_NO_NOTES_REFUNDED = ("The AI couldn't build notes for this file right now — your credit was "
                      "returned, please try again.")
_NO_NOTES_PLAIN    = "The AI couldn't build notes right now — please try again."

class _NoNotes(ValueError):
    """Every section came back without notes (a hollow guide)."""

def _require_notes(sections, charged=True):
    """If every section came back without notes (pass2 failed throughout), the
    guide is hollow: raise a user-facing error so the caller refunds it instead
    of reporting a charged 'Ready'."""
    if not any(isinstance(s, dict) and s.get("bullets") for s in sections):
        raise _NoNotes(_NO_NOTES_REFUNDED if charged else _NO_NOTES_PLAIN)

_NO_NOTES_PLAIN_AR = "تعذّر على الذكاء الاصطناعي إعداد الملاحظات الآن — يُرجى المحاولة مرة أخرى."

def _gen_error_event(e, charge=None, ar=False):
    """SSE error event for a failed generation — build it AFTER the refund, so
    'your credit was returned' is only said when it really was (e.g. not while
    migration 012 is missing). `code` lets the client show localized text.
    Free mode has no credits: it never says one came back (refunded stays False)."""
    if isinstance(e, _NoNotes):
        if FREE_MODE:
            return {"error": _NO_NOTES_PLAIN_AR if ar else _NO_NOTES_PLAIN,
                    "code": "no_notes", "refunded": False}
        refunded = bool(charge is not None and charge.refunded)
        return {"error": _NO_NOTES_REFUNDED if refunded else _NO_NOTES_PLAIN,
                "code": "no_notes", "refunded": refunded}
    return {"error": _safe_err(e)}

def _is_partial(overview, include_quiz, include_mcq):
    """Flash cards / quiz were requested but came back empty."""
    return bool((include_quiz and not overview.get("flashcards")) or
                (include_quiz and include_mcq and not overview.get("mcqs")))

# ── Free mode: generation slots (a small queue instead of an error) ───────────
# Every generation holds a gunicorn thread for its whole stream, and the box is
# small, so only _GEN_SLOTS (GEN_MAX_CONCURRENT) run at once. A request that finds
# them all taken may WAIT, up to GEN_QUEUE_WAIT_S, while the stream tells it its
# place in line ('queued' events — older clients ignore unknown steps); then 'busy'
# (its fair-use units are refunded). A waiter holds a web thread too, so at most
# _GEN_WAIT_MAX (GEN_MAX_WAITING) wait; one more is turned away AT ONCE, before
# it is charged anything. Slots + seats stay below WEB_THREADS: the gate can never
# take every thread, so /healthz and the static files are always answered. The line
# is first come, first served. Process-wide, which is the whole fleet: render runs
# ONE gunicorn worker. Off entirely with ALIMNE_FREE_MODE=0.
_gen_sem          = threading.BoundedSemaphore(_GEN_SLOTS)
_gen_wait_lock    = threading.Lock()
_gen_cond         = threading.Condition(_gen_wait_lock)   # a released slot wakes the line
_gen_waiting      = []       # one token per request waiting for a slot, in arrival order
_GEN_QUEUE_TICK_S = 3.0      # how often a waiting stream reports its place
_GEN_BUSY_RETRY_S = 20

_QUEUED_EN = "Lots of people are studying right now — you're number {n} in line. Hang tight…"
_QUEUED_AR = "الكثيرون يدرسون الآن — ترتيبك {n} في الانتظار. لحظات من فضلك…"
_BUSY_EN   = "Alimne is very busy right now. Please try again in a minute."
_BUSY_AR   = "الموقع مشغول جدًا الآن. يُرجى المحاولة بعد دقيقة."

class _GenSlot:
    """One held slot of the generation semaphore. release() is idempotent, so a
    slot is given back exactly once however the stream ends. `cond` (when given)
    is notified so the head of the line takes the slot without waiting for its
    next tick."""
    def __init__(self, sem, cond=None):
        self._sem  = sem
        self._cond = cond
        self._held = True
        self._lock = threading.Lock()

    def release(self):
        with self._lock:
            if not self._held:
                return False
            self._held = False
        self._sem.release()
        if self._cond is not None:
            with self._cond:
                self._cond.notify_all()
        return True

def _busy_event(ar=False):
    """SSE error for a request that could not get a generation slot (no seat in line,
    or it waited out GEN_QUEUE_WAIT_S)."""
    _log.info("generation busy (no free slot or seat in line)")
    return {"error": _BUSY_AR if ar else _BUSY_EN, "code": "busy",
            "retry_after_s": _GEN_BUSY_RETRY_S}

def _gen_has_room():
    """True when a new generation request would run or get a seat in line right now.
    The routes ask this BEFORE they charge anything or do any slow pre-work, so a
    full house costs a refused request nothing but this check."""
    with _gen_wait_lock:
        if _gen_sem._value > len(_gen_waiting):      # a slot beyond those the line is about to take
            return True
        return GEN_QUEUE_WAIT_S > 0 and len(_gen_waiting) < _GEN_WAIT_MAX

def _busy_response(ar=False):
    """The refusal for a full house, as JSON (the response has not started yet)."""
    return jsonify(_busy_event(ar)), 503

def _gen_slot_acquire(ar=False):
    """Sub-generator: `slot = yield from _gen_slot_acquire(ar)` → a _GenSlot, or None
    when there is no seat in line or GEN_QUEUE_WAIT_S ran out. While it waits it
    yields SSE 'queued' chunks (position + message) right away and then about every
    3 s. Waiters are served strictly in arrival order, and a newcomer never jumps
    a non-empty line. The slot is only taken on the way OUT (no yield between taking
    it and returning it), so a client disconnecting mid-wait (GeneratorExit at a
    yield) never leaks one."""
    sem = _gen_sem
    with _gen_wait_lock:
        if not _gen_waiting and sem.acquire(blocking=False):
            return _GenSlot(sem, _gen_cond)
        if GEN_QUEUE_WAIT_S <= 0 or len(_gen_waiting) >= _GEN_WAIT_MAX:
            return None
        token = object()
        _gen_waiting.append(token)
    deadline = time.monotonic() + GEN_QUEUE_WAIT_S
    try:
        while True:
            with _gen_wait_lock:
                pos = _gen_waiting.index(token) + 1
            yield _sse({"step": "queued", "position": pos,
                        "msg": (_QUEUED_AR if ar else _QUEUED_EN).format(n=pos)})
            tick_end = min(deadline, time.monotonic() + _GEN_QUEUE_TICK_S)
            with _gen_cond:
                while True:
                    if _gen_waiting[0] is token and sem.acquire(blocking=False):
                        return _GenSlot(sem, _gen_cond)
                    left = tick_end - time.monotonic()
                    if left <= 0:
                        break
                    _gen_cond.wait(left)
            if time.monotonic() >= deadline:
                return None
    finally:
        with _gen_wait_lock:
            if token in _gen_waiting:
                _gen_waiting.remove(token)
                _gen_cond.notify_all()     # the next in line is now the head

@app.route("/api/summarize-stream", methods=["POST"])
def summarize_stream():
    if not _check_rate_limit(_client_ip(), scope="summarize", limit=_gen_rate_limit()):
        return jsonify({"error": "Too many requests. Please wait a minute before trying again."}), 429
    # Verify the token BEFORE parsing the (possibly long) upload, so a token that
    # was fresh at click time is judged now — and a rejected token is a 401, not
    # a silent downgrade to the anonymous quota.
    uid = _auth_optional(request)
    if uid is False:
        return _auth_rejected()
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f     = request.files["file"]
    fname = f.filename or ""
    # Validate BEFORE the charge: a rejected type used to be charged and then
    # refunded — and a refund can fail (e.g. the durable device quota before
    # migration 012), silently costing an anonymous visitor a free preview.
    # (Multipart form fields are always strings, so no type checks are needed.)
    _ALLOWED_EXT = (".pptx", ".ppt", ".pdf", ".docx", ".doc", ".txt")
    if not fname.lower().endswith(_ALLOWED_EXT):
        return jsonify({"error": "Unsupported file type. Supported: .pptx, .ppt, .pdf, .docx, .doc, .txt"}), 400

    # Free mode: no slot and no seat in line → busy NOW, before anything is charged.
    if FREE_MODE and not _gen_has_room():
        return _busy_response(_wants_ar(request.form))

    # ── Credit gate: signed-in users spend a token; anonymous users get a
    #    small free quota per device/IP so they can try without an account. ────
    charge, err = _charge_credit(uid, request, request.form)
    if err:
        return err
    tok_left = charge.tok_left

    _log_usage_async("user" if uid else "anon", "file")
    lang_param   = request.form.get("language", "auto")
    out_name     = _safe_name(request.form.get("filename", fname.rsplit(".", 1)[0]))
    detail_level = request.form.get("detail", "standard")
    dcfg         = DETAIL.get(detail_level, DETAIL["standard"])
    include_quiz = request.form.get("mode", "full") != "summary"
    include_mcq  = str(request.form.get("quiz", "true")).lower() != "false"

    if not ollama_running():
        charge.refund()
        return jsonify({"error": "AI service is not configured. Set GROQ_API_KEY."}), 503

    file_bytes = f.read()
    ar = _wants_ar(request.form) if FREE_MODE else False

    def generate():
        # Single-owner refund guard: every exit either delivers 'done' (settled)
        # or refunds exactly once — including a client disconnect, which arrives
        # as GeneratorExit (a BaseException the `except Exception` never sees).
        # The generation slot (free mode) is released in the `finally`, on every path.
        settled = False
        slot = None
        try:
            if FREE_MODE:
                slot = yield from _gen_slot_acquire(ar)
                if slot is None:
                    settled = True
                    charge.refund()
                    yield _sse(_busy_event(ar)); return
            yield _sse({"step": "extract", "msg": "Extracting content…"})
            slides = extract_slides(io.BytesIO(file_bytes), filename=f.filename)
            if not any(s["content"] or s["title"] for s in slides):
                settled = True
                charge.refund()
                yield _sse({"error": "No readable content in this file"}); return

            total = len([s for s in slides if s["content"].strip()])

            # Auto-detect language from slide content
            language = lang_param if lang_param in ("ar", "en") else _detect_language(slides)
            lang_label = "Arabic" if language == "ar" else "English"
            yield _sse({"step": "extract", "msg": f"Found {total} content slides ({lang_label}) — analysing…", "language": language})

            # Pass 1
            yield _sse({"step": "overview", "msg": "Analysing structure and keywords…"})
            charge.begin_work()   # the first paid AI call: from here a disconnect no longer refunds
            overview = pass1_overview(
                [s for s in slides if s["content"].strip() or s["title"].strip()],
                language, dcfg
            )

            # Normalize: mistral sometimes returns sections/keywords as plain strings
            raw_sections = overview.get("sections", [])
            overview["sections"] = [
                s if isinstance(s, dict) else {"title": str(s), "slide_nums": []}
                for s in (raw_sections if isinstance(raw_sections, list) else [])
            ]
            raw_keywords = overview.get("keywords", [])
            overview["keywords"] = [
                k if isinstance(k, dict) else {"term": str(k), "definition": ""}
                for k in (raw_keywords if isinstance(raw_keywords, list) else [])
            ]

            content_slides = [s for s in slides if s["content"].strip()]

            # Fallback: if no sections produced, wrap all content into one
            if not overview["sections"]:
                overview["sections"] = [{
                    "title": overview.get("title", "Content Overview"),
                    "slide_nums": [s["slide_num"] for s in content_slides]
                }]

            sections = overview["sections"]

            for evt in _sections_parallel(sections, content_slides, language, dcfg):
                yield _sse(evt)
            _require_notes(sections)   # no notes at all → refunded error, not a hollow 'Ready'

            for evt in _flashcards_mcq_parallel(overview, language, dcfg, include_quiz, include_mcq):
                yield _sse(evt)

            # Build PDF + Markdown
            overview["language"] = language   # so exports + the in-app viewer localise
            yield _sse({"step": "pdf", "msg": "Building PDF & Markdown…"})
            pdf_buf   = build_pdf(overview, language, out_name)
            pdf_bytes = pdf_buf.read()
            md_text   = build_markdown(overview)

            job_id = uuid.uuid4().hex
            store_job(job_id, pdf_bytes, md_text, overview, None, f"{out_name}_study_guide.pdf")

            done = {"step": "done", "job_id": job_id}
            if tok_left is not None:     # free mode: no token balance to report
                done["tokens_remaining"] = tok_left
            done.update({"sections":   len(sections),
                         "keywords":   len(overview.get("keywords",   [])),
                         "flashcards": len(overview.get("flashcards", [])),
                         "mcqs":       len(overview.get("mcqs",       []))})
            if charge.anon_left is not None:   # free mode, anonymous: free guides left before sign-in
                done["anon_remaining"] = charge.anon_left
            if _is_partial(overview, include_quiz, include_mcq):
                done["partial"] = True
            yield _sse(done)
            settled = True
            charge.settle()

        except Exception as e:
            settled = True
            _log.error("GENERATE_ERROR: %s\n%s", e, _tb.format_exc())
            charge.refund()
            yield _sse(_gen_error_event(e, charge, ar))
        finally:
            if slot is not None:
                slot.release()
            if not settled:
                _log.info("summarize stream closed early (client gone)")
                charge.abandon()   # refunds only if no paid AI work had started

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.route("/api/download/<job_id>")
def download_job(job_id):
    if not _valid_job(job_id):
        return jsonify({"error": "Invalid job ID"}), 400
    fmt      = request.args.get("format", "pdf")
    filename = _safe_name(request.args.get("filename", "study_guide"))
    job = get_job(job_id)
    if not job:
        return _job_expired_json()
    if fmt == "md":
        content = (job.get("md") or "").encode("utf-8")
        return send_file(io.BytesIO(content), mimetype="text/markdown",
                         as_attachment=True, download_name=f"{filename}.md")
    return send_file(io.BytesIO(job["pdf"]), mimetype="application/pdf",
                     as_attachment=True, download_name=job.get("filename", f"{filename}.pdf"))


@app.route("/api/delete/<job_id>", methods=["POST"])
def delete_job(job_id):
    """Immediately purge a job from memory (user-requested delete-now)."""
    if not _valid_job(job_id):
        return jsonify({"error": "Invalid job ID"}), 400
    with _jobs_lock:
        existed = _jobs.pop(job_id, None) is not None
    return jsonify({"ok": True, "deleted": existed})


@app.route("/api/guide/<job_id>")
def get_guide(job_id):
    if not _valid_job(job_id):
        return jsonify({"error": "Invalid job ID"}), 400
    with _jobs_lock:
        job = get_job(job_id)
    if not job:
        return _job_expired_json()
    guide    = job.get("guide", {})
    filename = job.get("filename") or "study_guide.pdf"
    out = {
        "title":      guide.get("title", ""),
        "subtitle":   guide.get("subtitle", ""),
        "sections":   guide.get("sections",   []),
        "flashcards": guide.get("flashcards", []),
        "mcqs":       guide.get("mcqs", []),
        "keywords":   guide.get("keywords",   []),
        "objectives": guide.get("objectives", []),
        "language":   guide.get("language", "en"),
        # Client-held, HMAC-signed copy for POST /api/rehydrate after expiry.
        "guide_blob": _guide_blob(guide, filename),
        "filename":   filename,
        "expires_in": _job_expires_in(job),
    }
    if _GUIDE_KEY:
        out["sig"] = _guide_sig(out["guide_blob"])
    return jsonify(out)


@app.route("/api/rehydrate", methods=["POST"])
def rehydrate_guide():
    """Rebuild an expired guide from the browser's own signed copy (see
    _guide_blob). Free — never consumes a credit — and it stores nothing beyond
    the usual 15-minute in-memory job, under a NEW job id."""
    if not _GUIDE_KEY:
        return jsonify({"error": "Restoring guides is unavailable right now.", "code": "unavailable"}), 503
    if not _check_rate_limit(_client_ip(), scope="rehydrate", limit=20):
        return jsonify({"error": "Too many requests. Please wait a moment.", "code": "rate_limited"}), 429
    # Cheap pre-check before parsing: JSON-escaping can at most ~double the blob.
    if (request.content_length or 0) > 3 * _GUIDE_BLOB_MAX:
        return jsonify({"error": "This guide is too large to restore.", "code": "too_large"}), 413
    data = request.get_json(silent=True)
    blob = data.get("guide_blob") if isinstance(data, dict) else None
    sig  = data.get("sig") if isinstance(data, dict) else None
    if not isinstance(blob, str) or not isinstance(sig, str) or not blob or not sig:
        return jsonify({"error": "Missing guide data.", "code": "bad_request"}), 400
    # A lone UTF-16 surrogate (JSON "\ud800") can't be UTF-8 encoded. A genuine
    # signed copy never holds one (signing would have failed), so it's bad input.
    try:
        raw = blob.encode("utf-8")
    except UnicodeEncodeError:
        return jsonify({"error": "Unreadable guide data.", "code": "bad_request"}), 400
    if len(raw) > _GUIDE_BLOB_MAX:
        return jsonify({"error": "This guide is too large to restore.", "code": "too_large"}), 413
    # HMAC over the EXACT received string; compare bytes so a non-ASCII sig
    # can't make compare_digest raise.
    expected = hmac.new(_GUIDE_KEY, raw, hashlib.sha256).hexdigest().encode("ascii")
    try:
        sig_raw = sig.encode("utf-8")
    except UnicodeEncodeError:
        sig_raw = b""
    if not sig_raw or not hmac.compare_digest(expected, sig_raw):
        return jsonify({"error": "This guide copy could not be verified.", "code": "bad_signature"}), 403
    try:
        obj = json.loads(blob)
        src = obj.get("guide") if isinstance(obj, dict) else None
        if obj.get("v") != 1 or not isinstance(src, dict):
            raise ValueError("bad shape")
    except Exception:
        return jsonify({"error": "Unreadable guide data.", "code": "bad_request"}), 400

    guide = _guide_public(src)
    for k in ("sections", "flashcards", "mcqs", "keywords", "objectives"):
        if not isinstance(guide[k], list):
            guide[k] = []
    lang = "ar" if guide.get("language") == "ar" else "en"
    guide["language"] = lang
    fname = _safe_name(str(obj.get("filename") or "study_guide.pdf"), 120)
    if not fname.lower().endswith(".pdf"):
        fname += ".pdf"
    # Free and unauthenticated, so bound the CPU it can take: at most
    # _REHYDRATE_SLOTS PDF builds at once, a short wait, then 503 'retry'.
    if not _rehydrate_sem.acquire(timeout=3):
        return jsonify({"error": "Busy restoring guides — please try again in a moment.",
                        "code": "retry"}), 503
    try:
        pdf_bytes = build_pdf(guide, lang).read()
        md_text   = build_markdown(guide)
    except Exception:
        _log.error("rehydrate rebuild failed:\n%s", _tb.format_exc())
        return jsonify({"error": "Couldn't restore this guide — please regenerate it.",
                        "code": "rebuild_failed"}), 500
    finally:
        _rehydrate_sem.release()
    job_id = uuid.uuid4().hex
    store_job(job_id, pdf_bytes, md_text, guide, None, fname, rehydrated=True)
    return jsonify({"job_id": job_id, "expires_in": _JOB_TTL, "filename": fname})


# ── Shareable public guides ────────────────────────────────────────────────────
# A guide is ephemeral by default (in-memory, wiped on the job TTL). When a user
# explicitly clicks "Share", that ONE guide's *content* (never the source file) is
# persisted to public.shared_guides and gets a public, mobile-first /s/<slug> page
# — a viral + SEO surface. See migration 007.
import secrets as _secrets
_SLUG_CHARS = "abcdefghijkmnpqrstuvwxyz23456789"   # no ambiguous 0/1/l/o
_SLUG_RE    = re.compile(r"^[a-z0-9]{6,16}$")

def _new_slug(n=8):
    return "".join(_secrets.choice(_SLUG_CHARS) for _ in range(n))

@app.route("/api/share/<job_id>", methods=["POST"])
def share_guide(job_id):
    if not _check_rate_limit(_client_ip(), scope="share", limit=20):
        return jsonify({"error": "Too many requests. Please wait a moment."}), 429
    if not _valid_job(job_id):
        return jsonify({"error": "Invalid job ID"}), 400
    with _jobs_lock:
        job = get_job(job_id)
    if not job:
        return _job_expired_json()
    # Sharing is idempotent per guide: a second tap (or a script) gets the SAME link
    # back and stores nothing new, so the shared_guides table cannot be filled from here.
    with _jobs_lock:
        known = job.get("share_slug")
    if known:
        return jsonify({"ok": True, "slug": known, "url": f"{APP_URL}/s/{known}"})
    sb = _get_sb()
    if sb is None:
        return jsonify({"error": "Sharing is temporarily unavailable."}), 503
    guide = job.get("guide")
    guide = guide if isinstance(guide, dict) else {}
    # Sharing works signed out too: a rejected token (False) just shares anonymously,
    # and created_by must never be False.
    uid   = _auth_optional(request) or None
    lang  = "ar" if guide.get("language") == "ar" else "en"
    payload = {
        "title":      guide.get("title", ""),      "subtitle":   guide.get("subtitle", ""),
        "sections":   guide.get("sections",   []), "flashcards": guide.get("flashcards", []),
        "mcqs":       guide.get("mcqs",       []), "keywords":   guide.get("keywords",   []),
        "objectives": guide.get("objectives", []), "language":   lang,
    }
    # The title column is text: a number title (1984) used to 500 on [:200], and a
    # list/object one was stored as-is. Numbers become text; others the default.
    t = guide.get("title")
    title = (t if isinstance(t, str) else _scalar_text(t)) or "Study Guide"
    base = {"guide": payload, "title": title[:200],
            "language": lang, "created_by": uid}
    for _ in range(6):
        slug = _new_slug()
        try:
            sb.table("shared_guides").insert({**base, "slug": slug}).execute()
            with _jobs_lock:
                job["share_slug"] = slug
            _log.info("Guide shared: /s/%s (by=%s)", slug, uid or "anon")
            return jsonify({"ok": True, "slug": slug, "url": f"{APP_URL}/s/{slug}"})
        except Exception as exc:
            msg = str(exc).lower()
            if "duplicate" in msg or "unique" in msg or "23505" in msg:
                continue
            _log.error("share failed: %s", exc)
            return jsonify({"error": "Could not create a share link right now."}), 500
    return jsonify({"error": "Could not create a share link right now."}), 500


def _sg_bullet(b):
    if isinstance(b, str):  return _debullet(b)
    if isinstance(b, dict): return _debullet(_scalar_text(b.get("text") or b.get("fact")))
    return _debullet(_scalar_text(b))   # a number → its text; None / list → "" (skipped, not "None")

def _sg_desc(g):
    parts = [o for o in _as_list(g.get("objectives")) if isinstance(o, str) and o.strip()]
    if not parts:
        for sec in _as_list(g.get("sections")):
            if not isinstance(sec, dict):
                continue
            for b in _as_list(sec.get("bullets")):
                t = _sg_bullet(b).strip()
                if t:
                    parts.append(t); break
            if parts: break
    d = " · ".join(parts) if parts else "A free study guide with key points, flashcards and a quiz."
    return d[:180]

def _mcq_correct(opt, ans):
    o, a = str(opt).strip(), str(ans).strip()
    if not a: return False
    if len(a) == 1 and o[:1].upper() == a.upper(): return True
    body = re.sub(r'^[A-Za-z][\).\-]\s*', '', o).strip().lower()
    return body == a.lower() or o.lower() == a.lower()

_SHARED_CSS = """
*{box-sizing:border-box}
:root{--bg:#f4f7fc;--card:#fff;--bd:#e2e8f2;--ink:#15202e;--soft:#495a70;--mut:#7b8798;
  --accent:#3b6fe0;--accent2:#7c5cff;--good:#12a35f;--good-bg:#e7f7ef}
@media(prefers-color-scheme:dark){:root{--bg:#0c1017;--card:#141b26;--bd:#28323f;--ink:#e9eef6;
  --soft:#aeb9c9;--mut:#7c899c;--accent:#6f9dff;--accent2:#9d80ff;--good:#33d191;--good-bg:rgba(51,209,145,.13)}}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.62;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,system-ui,sans-serif}
a{color:var(--accent)}
img{max-width:100%}
.bar{position:sticky;top:0;z-index:5;display:flex;align-items:center;justify-content:space-between;gap:1rem;
  padding:.7rem clamp(1rem,4vw,2rem);background:color-mix(in srgb,var(--bg) 90%,transparent);
  backdrop-filter:blur(10px);border-bottom:1px solid var(--bd)}
.brand{font-weight:800;font-size:1.05rem;letter-spacing:-.01em;text-decoration:none;color:var(--ink)}
.cta-btn{white-space:nowrap;font-weight:700;font-size:.85rem;text-decoration:none;color:#fff;
  background:linear-gradient(100deg,var(--accent),var(--accent2));padding:.5rem .95rem;border-radius:9px}
.wrap{max-width:760px;margin:0 auto;padding:clamp(1.2rem,4vw,2.4rem) clamp(1rem,4vw,1.6rem) 3rem}
.tag{font-size:.72rem;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--accent)}
h1{font-size:clamp(1.6rem,5.5vw,2.3rem);line-height:1.12;letter-spacing:-.02em;margin:.5rem 0 .35rem;text-wrap:balance}
.sub{font-size:1.06rem;color:var(--soft);margin:0 0 .55rem}
.meta{font-size:.82rem;color:var(--mut);margin:0 0 1.7rem}
.sec{margin:1.9rem 0}
.sec h2{font-size:1.2rem;letter-spacing:-.01em;margin:0 0 .6rem;padding-left:.6rem;border-left:3px solid var(--accent)}
.sec ul{margin:0;padding-left:1.2rem;display:flex;flex-direction:column;gap:.35rem}
.sec li{color:var(--soft)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:.7rem}
.fc{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:.85rem 1rem}
.fc-q{font-weight:700}.fc-a{color:var(--good);margin-top:.3rem;font-size:.95rem}
.qz{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:.9rem 1.05rem;margin-bottom:.7rem}
.qz-q{font-weight:700;margin-bottom:.55rem}
.opts{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:.35rem}
.opts .opt{font-size:.92rem;color:var(--soft);padding:.4rem .65rem;border-radius:8px;border:1px solid transparent}
.opts .opt.correct{color:var(--good);background:var(--good-bg);font-weight:600;border-color:color-mix(in srgb,var(--good) 32%,transparent)}
.expl{font-size:.85rem;color:var(--mut);margin-top:.55rem;padding-top:.5rem;border-top:1px solid var(--bd)}
.kw{padding:.5rem 0;border-bottom:1px solid var(--bd)}
.kw dt{font-weight:700}.kw dd{margin:.1rem 0 0;color:var(--soft);font-size:.93rem}
.promo{margin-top:2.4rem;background:linear-gradient(120deg,var(--accent),var(--accent2));color:#fff;
  border-radius:16px;padding:clamp(1.3rem,4vw,2rem);text-align:center}
.promo h3{margin:0 0 .4rem;font-size:clamp(1.2rem,4vw,1.5rem)}
.promo p{margin:0 0 1.1rem;opacity:.92}
.promo a{display:inline-block;background:#fff;color:var(--accent);font-weight:800;text-decoration:none;padding:.72rem 1.6rem;border-radius:10px}
.foot{margin-top:1.6rem;text-align:center;font-size:.8rem;color:var(--mut)}
[dir="rtl"] .sec h2{border-left:0;border-right:3px solid var(--accent);padding-left:0;padding-right:.6rem}
[dir="rtl"] .sec ul{padding-left:0;padding-right:1.2rem}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""

def _shared_shell(title_tag, head_extra, body_html, lang="en"):
    d = "rtl" if lang == "ar" else "ltr"
    return ("<!DOCTYPE html><html lang=\"%s\" dir=\"%s\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>%s</title>%s<style>%s</style></head><body>%s</body></html>"
            ) % (lang, d, title_tag, head_extra, _SHARED_CSS, body_html)

def _shared_404():
    body = ("<div class=\"bar\"><a class=\"brand\" href=\"%s/\">📖 Alimne</a>"
            "<a class=\"cta-btn\" href=\"%s/\">Try it free</a></div>"
            "<div class=\"wrap\" style=\"text-align:center;padding-top:3rem\">"
            "<h1>This guide isn't here</h1><p class=\"sub\">The link may be wrong, or the guide was never published.</p>"
            "<div class=\"promo\"><h3>Make your own study guide — free</h3>"
            "<p>Turn any lecture into notes, flashcards &amp; a quiz.</p>"
            "<a href=\"%s/?utm_source=shared_guide&utm_medium=share&utm_campaign=notfound\">Start free</a></div></div>"
            ) % (APP_URL, APP_URL, APP_URL)
    return _shared_shell("Guide not found · Alimne", "", body)

def _render_shared_guide(row):
    # Every field read here tolerates loose shapes (see _as_list / _scalar_text):
    # this is a PUBLIC page, and a stored guide with e.g. a number for bullets or
    # options, or a string section, used to answer 500.
    g      = row.get("guide")
    g      = g if isinstance(g, dict) else {}
    is_ar  = (row.get("language") or g.get("language")) == "ar"
    L = {
        "tag":   "دليل دراسة" if is_ar else "Study guide",
        "try":   "جرّب مجاناً" if is_ar else "Try it free",
        "learn": "ماذا ستتعلّم" if is_ar else "What you'll learn",
        "keys":  "مصطلحات أساسية" if is_ar else "Key terms",
        "cards": "بطاقات تعليمية" if is_ar else "Flashcards",
        "quiz":  "اختبار" if is_ar else "Quiz",
        "ptitle":"أنشئ دليل دراستك مجاناً" if is_ar else "Make your own study guide — free",
        "psub":  "ارفع محاضرة — PowerPoint أو PDF أو رابط YouTube — واحصل على ملخص وبطاقات واختبار خلال ثوانٍ. مجاني، دون بطاقة ائتمان."
                 if is_ar else "Upload a lecture — PowerPoint, PDF, or a YouTube link — and get notes, flashcards and a quiz in seconds. Free, no credit card needed.",
        "pbtn":  "ابدأ مجاناً" if is_ar else "Start free",
    }
    title_raw = _scalar_text(g.get("title")) or "Study Guide"
    title = _he(title_raw)
    desc  = _sg_desc(g)
    sub_raw = _scalar_text(g.get("subtitle"))
    sub   = ("<p class=\"sub\">%s</p>" % _he(sub_raw)) if sub_raw else ""

    flashcards = [f for f in _as_list(g.get("flashcards")) if isinstance(f, dict)]
    mcqs       = [m for m in _as_list(g.get("mcqs")) if isinstance(m, dict)]
    meta_bits = []
    if flashcards: meta_bits.append(("%d بطاقة" % len(flashcards)) if is_ar else "%d flashcards" % len(flashcards))
    if mcqs:       meta_bits.append(("%d سؤال" % len(mcqs)) if is_ar else "%d quiz questions" % len(mcqs))
    meta_bits.append("مجاناً عبر Alimne" if is_ar else "free · via Alimne")
    meta = "<div class=\"meta\">%s</div>" % _he(" · ".join(meta_bits))

    parts = []
    objs = [o for o in _as_list(g.get("objectives")) if isinstance(o, str) and o.strip()]
    if objs:
        parts.append("<section class=\"sec\"><h2>%s</h2><ul>%s</ul></section>" % (
            _he(L["learn"]), "".join("<li>%s</li>" % _he(o) for o in objs)))
    for sec in _as_list(g.get("sections")):
        if not isinstance(sec, dict): continue
        lis = "".join("<li>%s</li>" % _he(_sg_bullet(b).strip())
                      for b in _as_list(sec.get("bullets")) if _sg_bullet(b).strip())
        if lis:
            parts.append("<section class=\"sec\"><h2>%s</h2><ul>%s</ul></section>" % (_he(_scalar_text(sec.get("title"))), lis))
    kws = [k for k in _as_list(g.get("keywords")) if isinstance(k, dict) and _scalar_text(k.get("term")).strip()]
    if kws:
        dl = "".join("<div class=\"kw\"><dt>%s</dt><dd>%s</dd></div>" % (
            _he(_scalar_text(k.get("term"))), _he(_scalar_text(k.get("definition")))) for k in kws)
        parts.append("<section class=\"sec\"><h2>%s</h2>%s</section>" % (_he(L["keys"]), dl))
    if flashcards:
        cards = "".join("<div class=\"fc\"><div class=\"fc-q\">%s</div><div class=\"fc-a\">%s</div></div>" % (
            _he(f.get("q") or f.get("question") or ""), _he(f.get("a") or f.get("answer") or "")) for f in flashcards)
        parts.append("<section class=\"sec\"><h2>%s</h2><div class=\"grid\">%s</div></section>" % (_he(L["cards"]), cards))
    if mcqs:
        qz = []
        for m in mcqs:
            qt = _he(m.get("q") or m.get("question") or "")
            ans = m.get("answer", m.get("correct", ""))
            opts = "".join("<li class=\"opt%s\">%s%s</li>" % (
                " correct" if _mcq_correct(o, ans) else "",
                "✓ " if _mcq_correct(o, ans) else "",
                _he(o if isinstance(o, str) else str(o))) for o in _as_list(m.get("options")))
            expl = m.get("explanation") or m.get("rationale") or ""
            ex = ("<div class=\"expl\">%s</div>" % _he(expl)) if expl else ""
            qz.append("<div class=\"qz\"><div class=\"qz-q\">%s</div><ul class=\"opts\">%s</ul>%s</div>" % (qt, opts, ex))
        parts.append("<section class=\"sec\"><h2>%s</h2>%s</section>" % (_he(L["quiz"]), "".join(qz)))

    slug = row.get("slug", "")
    cta_q = "?utm_source=shared_guide&utm_medium=share&utm_campaign="
    body = (
        "<div class=\"bar\"><a class=\"brand\" href=\"%s/\">📖 Alimne</a>"
        "<a class=\"cta-btn\" href=\"%s/%sshare_bar\">%s</a></div>"
        "<div class=\"wrap\"><div class=\"tag\">%s</div><h1>%s</h1>%s%s%s"
        "<div class=\"promo\"><h3>%s</h3><p>%s</p>"
        "<a href=\"%s/%sshare_cta\">%s</a></div>"
        "<div class=\"foot\">Made with alimne.app — turn any lecture into a study guide.</div></div>"
    ) % (APP_URL, APP_URL, cta_q, _he(L["try"]), _he(L["tag"]), title, sub, meta,
         "".join(parts), _he(L["ptitle"]), _he(L["psub"]), APP_URL, cta_q, _he(L["pbtn"]))

    ld = {"@context": "https://schema.org", "@type": "LearningResource",
          "name": title_raw, "description": desc, "inLanguage": row.get("language", "en"),
          "url": f"{APP_URL}/s/{slug}", "isAccessibleForFree": True,
          "learningResourceType": "Study guide",
          "provider": {"@type": "Organization", "name": "Alimne", "url": APP_URL}}
    head = (
        "<meta name=\"description\" content=\"%s\">"
        "<link rel=\"canonical\" href=\"%s/s/%s\">"
        "<meta property=\"og:type\" content=\"article\"><meta property=\"og:site_name\" content=\"Alimne\">"
        "<meta property=\"og:title\" content=\"%s\"><meta property=\"og:description\" content=\"%s\">"
        "<meta property=\"og:url\" content=\"%s/s/%s\"><meta name=\"twitter:card\" content=\"summary\">"
        "<script type=\"application/ld+json\">%s</script>"
    ) % (_he(desc), APP_URL, _he(slug), title, _he(desc), APP_URL, _he(slug),
         json.dumps(ld).replace("<", "\\u003c"))
    page_title = "%s — %s · Alimne" % (title, _he(L["tag"]))
    return _shared_shell(page_title, head, body, "ar" if is_ar else "en")

@app.route("/s/<slug>")
def shared_guide_page(slug):
    if not _SLUG_RE.match(slug or ""):
        return _shared_404(), 404
    sb = _get_sb()
    if sb is None:
        return _shared_404(), 404
    try:
        res = sb.table("shared_guides").select("slug,guide,title,language").eq("slug", slug).single().execute()
        row = res.data
    except Exception:
        row = None
    if not row:
        return _shared_404(), 404
    try:
        sb.rpc("bump_shared_views", {"p_slug": slug}).execute()
    except Exception:
        pass
    return _render_shared_guide(row)


def _chat_context(guide):
    """The study material for the chat prompt (title, objectives, section notes,
    key terms) — rather than raw slide chunks. Tolerates loose guide shapes: a
    keyword dict without 'term', a string where a list belongs, non-string
    entries… are str()'d or skipped, never a 500."""
    guide = guide if isinstance(guide, dict) else {}
    parts = []
    title = _scalar_text(guide.get("title"))
    if title.strip():
        parts.append(f"Title: {title}")
    objs = [t for t in (_scalar_text(o) for o in _as_list(guide.get("objectives"))) if t.strip()]
    if objs:
        parts.append("Objectives:\n" + "\n".join(f"- {o}" for o in objs))
    for sec in _as_list(guide.get("sections")):
        if not isinstance(sec, dict):
            continue
        lines = []
        for b in _as_list(sec.get("bullets")):
            if isinstance(b, dict):
                b = b.get("text") or b.get("fact")
            t = _scalar_text(b)
            if t.strip():
                lines.append(f"- {t}")
        if lines:
            parts.append(f"\n[{_scalar_text(sec.get('title'))}]\n" + "\n".join(lines))
    kw_lines = []
    for k in _as_list(guide.get("keywords"))[:30]:
        if isinstance(k, dict):
            term, defn = _scalar_text(k.get("term")), _scalar_text(k.get("definition"))
            line = f"{term}: {defn}" if term.strip() else defn
        else:
            line = _scalar_text(k)
        if line.strip():
            kw_lines.append(line)
    if kw_lines:
        parts.append("Key terms:\n" + "\n".join(kw_lines))
    return "\n\n".join(parts) or "No material available."

def _chat_answer(result):
    """The model's answer as a string, whatever JSON shape came back: a list
    ([{"answer": …}]), a bare JSON string, an answer that is a list of lines…
    An unusable answer is '' (the client then shows its own localized
    'no answer' text, as it did for null); no 'answer' key at all keeps the
    historical default text."""
    if isinstance(result, str):
        return result.strip()
    res = _as_dict(result)
    if "answer" not in res:
        return "No answer found in the material."
    ans = res.get("answer")
    if isinstance(ans, list):
        ans = "\n".join(t for t in (_scalar_text(a) for a in ans) if t.strip())
    return _scalar_text(ans)

def _chat_fair_charge(uid, data=None):
    """Free-mode meter for ONE chat question (an LLM call over the whole guide) →
    (key | None, refusal | None). In order: a per-user per-minute cap (no database), the
    GLOBAL budget (read-only — chat stops when the breaker has tripped, it does not
    spend a guide's worth), then one unit of the user's own daily chat allowance
    (fair:chat:user:<id>, the existing anon_consume counter). Everything that can't be
    read fails open. `key` is what to give back if the question fails."""
    # (uid 'dev' = local development with auth switched off: exempt, like loopback in _check_rate_limit)
    if uid != "dev" and not _check_rate_limit(f"u:{uid}", scope="chatu", limit=_CHAT_USER_PER_MIN):
        return None, (jsonify({"error": "Too many requests. Please wait a minute.", "code": "rate_limited"}), 429)
    left = _fair_remaining_key("fair:global", FAIR_GLOBAL_DAILY)
    if left is not None and left <= 0:
        return None, _fair_refusal("busy_today", _wants_ar(data))
    key = f"fair:chat:user:{uid}"
    got = _fair_consume(key, FAIR_CHAT_DAILY)
    if got is False:
        return None, _fair_refusal("fair_use_user", _wants_ar(data))
    return (key if got else None), None

@app.route("/api/chat/<job_id>", methods=["POST"])
def chat_with_slides(job_id):
    if not _check_rate_limit(_client_ip(), scope="chat", limit=20):
        return jsonify({"error": "Too many requests. Please wait a minute."}), 429
    uid, err = _auth_check(request)
    if err:
        return err
    if not _valid_job(job_id):
        return jsonify({"error": "Invalid job ID"}), 400
    # A non-string question (a number, list, object, null) or a non-object body
    # used to 500 on [:500]; it is a 400 'bad_request' now.
    data = {}
    try:
        data     = _json_object()
        question = _str_field(data, "question")[:500].strip()
    except _BadField as e:
        return _bad_field(e, data)
    if not question:
        return _bad_request("No question provided",
                            "لم يتم إدخال أي سؤال — اكتب سؤالك أولاً.", data)
    with _jobs_lock:
        job = get_job(job_id)
    if not job:
        return _job_expired_json()

    # Free mode: a chat question is an LLM call too — metered after every input check.
    chat_key = None
    if FREE_MODE:
        chat_key, refusal = _chat_fair_charge(uid, data)
        if refusal:
            return refusal

    guide = job.get("guide")
    # An explicit en/ar choice wins. 'auto' (or nothing) answers in the guide's
    # own language: the client may not have the guide's language to send.
    req_lang = data.get("language")
    if req_lang in ("ar", "en"):
        language = req_lang
    else:
        language = "ar" if isinstance(guide, dict) and guide.get("language") == "ar" else "en"

    context = _chat_context(guide)

    lang = "in Arabic" if language == "ar" else "in English"
    try:
        result = _call_ollama(
            f"""Answer this question {lang} using ONLY the study material below.

Material:
{context}

Question: {question}

Return JSON: {{"answer": "your detailed answer"}}

Rules:
- Answer directly and specifically from the material
- If genuinely not covered, say so briefly
- Be helpful and detailed; include facts, definitions, examples from the material
- JSON only""", num_predict=1024)
        return jsonify({"answer": _chat_answer(result)})
    except Exception as e:
        if chat_key:
            _fair_refund_key(chat_key)       # the question failed: give its unit back
        return jsonify({"error": _safe_err(e)}), 500


# (/api/download-zip was removed: the shipped frontend never called it, and it
# read _jobs directly — serving expired guides past the 15-minute TTL.)

_VIEW_EXPIRED_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Guide expired · Alimne</title>
<style>
  body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:#f8faff;color:#0a1628;
       margin:0;padding:2rem 1.25rem;line-height:1.7}
  .box{max-width:560px;margin:3rem auto;background:#fff;border:1px solid #c5d8ff;border-radius:14px;padding:1.5rem 1.6rem}
  h1{font-size:1.25rem;color:#1a3a6e;margin:0 0 .4rem}
  p{margin:.2rem 0 1rem;color:#4a5f80}
  .ar{direction:rtl;text-align:right;border-top:1px solid #dde8ff;padding-top:1rem;margin-top:1rem}
  a.btn{display:inline-block;background:#4f8ef7;color:#fff;text-decoration:none;padding:.6rem 1.1rem;border-radius:10px;font-weight:600}
</style></head><body><div class="box">
<h1>This guide has expired</h1>
<p>For your privacy, guides are kept for 15 minutes. Go back to Alimne to restore or regenerate it.</p>
<div class="ar" lang="ar" dir="rtl">
<h1>انتهت صلاحية هذا الدليل</h1>
<p>حفاظًا على خصوصيتك نحتفظ بالأدلة لمدة 15 دقيقة فقط. ارجع إلى علّمني لاستعادته أو إنشائه من جديد.</p>
</div>
<p style="margin-top:1.2rem"><a class="btn" href="https://alimne.app/">Back to Alimne · العودة إلى علّمني</a></p>
</div></body></html>"""

@app.route("/api/view/md/<job_id>")
def view_md(job_id):
    if not _valid_job(job_id):
        return "<h2 style='font-family:sans-serif;padding:2rem'>Invalid job ID</h2>", 400
    with _jobs_lock:
        job = get_job(job_id)
    if not job:
        return _VIEW_EXPIRED_HTML, 404, {"Content-Type": "text/html; charset=utf-8"}
    guide = job.get("guide")
    guide = guide if isinstance(guide, dict) else {}
    is_ar = guide.get("language") == "ar"
    title = _he(_scalar_text(guide.get("title", "Study Guide")) or "Study Guide")
    md = job.get("md") or ""

    def _md_to_html(text):
        lines, out = text.split('\n'), []
        i = 0
        while i < len(lines):
            l = lines[i]
            if l.startswith('# '):
                out.append(f'<h1>{_inline(_he(l[2:]))}</h1>')
            elif l.startswith('## '):
                out.append(f'<h2>{_inline(_he(l[3:]))}</h2>')
            elif l.startswith('### '):
                out.append(f'<h3>{_inline(_he(l[4:]))}</h3>')
            elif l.startswith('- ') or l.startswith('* '):
                out.append(f'<li>{_inline(_he(l[2:]))}</li>')
            elif l.startswith('| ') and '|' in l[2:]:
                # Collect the whole table and wrap it — bare <tr> outside a
                # <table> is dropped by the HTML parser. th only for the header.
                rows = []
                while i < len(lines) and lines[i].startswith('|'):
                    if not re.match(r'^\|[-| :]+\|$', lines[i]):
                        cells = [c.strip() for c in lines[i].strip('|').split('|')]
                        tag = 'th' if not rows else 'td'
                        rows.append('<tr>' + ''.join(f'<{tag}>{_inline(_he(c))}</{tag}>' for c in cells) + '</tr>')
                    i += 1
                i -= 1
                if rows:
                    out.append('<table>' + ''.join(rows) + '</table>')
            elif l.strip() == '':
                out.append('<br>')
            else:
                out.append(f'<p>{_inline(_he(l))}</p>')
            i += 1
        return '\n'.join(out)

    def _inline(t):
        t = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
        t = re.sub(r'\*(.+?)\*',     r'<em>\1</em>',         t)
        t = re.sub(r'`(.+?)`',       r'<code>\1</code>',     t)
        return t

    body = _md_to_html(md)
    lang, dirn = ("ar", "rtl") if is_ar else ("en", "ltr")
    return f"""<!DOCTYPE html><html lang="{lang}" dir="{dirn}"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  body{{font-family:'Segoe UI',system-ui,sans-serif;max-width:820px;margin:0 auto;padding:2rem;
       background:#f8faff;color:#0a1628;line-height:1.7}}
  @media (max-width:600px){{body{{padding:1rem}} table{{display:block;overflow-x:auto}}}}
  h1{{font-size:1.7rem;color:#1a3a6e;border-bottom:2px solid #c5d8ff;padding-bottom:.5rem}}
  h2{{font-size:1.2rem;color:#2e5ca8;margin-top:1.8rem;border-left:4px solid #4f8ef7;padding-left:.75rem}}
  [dir=rtl] h2{{border-left:0;border-right:4px solid #4f8ef7;padding-left:0;padding-right:.75rem}}
  h3{{font-size:1rem;color:#1a3a6e}}
  li{{margin-bottom:.35rem}}
  table{{border-collapse:collapse;width:100%;margin:1rem 0}}
  th{{background:#1a3a6e;color:#fff;padding:8px 12px;text-align:start}}
  td{{padding:7px 12px;border-bottom:1px solid #dde8ff}}
  tr:nth-child(even) td{{background:#f0f5ff}}
  code{{background:#e8f0ff;padding:1px 5px;border-radius:4px;font-size:.9em}}
  strong{{color:#1a3a6e}}
  @media print{{body{{background:#fff}}}}
</style></head><body>
{body}
<hr style="margin-top:2rem;border-color:#c5d8ff">
<p style="font-size:.8rem;color:#8aa0c8;text-align:center">Generated by Alimne (علّمني) · {OLLAMA_MODEL}</p>
</body></html>"""


def _page_shell(title, body_css, body_html, script=""):
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>{title}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Segoe UI',system-ui,sans-serif;background:#050d1a;color:#e8f0ff;min-height:100vh}}
  .top{{background:#0a1628;border-bottom:1px solid #1a3a6e;padding:1rem 2rem;
        display:flex;align-items:center;justify-content:space-between}}
  .top h1{{font-size:1rem;font-weight:700;color:#e8f0ff}}
  .badge{{background:#4f8ef7;color:#fff;padding:2px 10px;border-radius:20px;font-size:12px}}
  .wrap{{max-width:760px;margin:0 auto;padding:2rem 1.25rem}}
  {body_css}
</style></head><body>
<div class="top"><h1>📖 {title}</h1></div>
<div class="wrap">{body_html}</div>
<script>{script}</script>
</body></html>"""


@app.route("/api/view/cards/<job_id>")
def view_cards(job_id):
    if not _valid_job(job_id):
        return "<h2 style='font-family:sans-serif;padding:2rem'>Invalid job ID</h2>", 400
    with _jobs_lock:
        job = get_job(job_id)
    if not job:
        return "<h2 style='font-family:sans-serif;padding:2rem'>Guide not found or expired</h2>", 404
    guide = job.get("guide")
    guide = guide if isinstance(guide, dict) else {}
    title = _he(_scalar_text(guide.get("title", "Flash Cards")) or "Flash Cards")
    cards = [f for f in _as_list(guide.get("flashcards")) if isinstance(f, dict)]
    if not cards:
        return _page_shell(title, "", "<p style='text-align:center;color:#4a5f80;padding:3rem'>No flash cards available.</p>")

    # Escape "<" so model-derived content can't break out of the <script> block
    # (json.dumps does NOT escape "</script>"). < is valid JSON and JS.
    cards_json = json.dumps(cards).replace("<", "\\u003c")
    css = """
  .fc-counter{text-align:center;color:#8aa0c8;font-size:.88rem;margin-bottom:1.2rem}
  .card{perspective:900px;height:220px;cursor:pointer;margin-bottom:1.5rem}
  .inner{position:relative;width:100%;height:100%;
         transition:transform .45s cubic-bezier(.4,0,.2,1);transform-style:preserve-3d}
  .card.flipped .inner{transform:rotateY(180deg)}
  .front,.back{position:absolute;inset:0;border-radius:14px;padding:1.5rem;
               backface-visibility:hidden;display:flex;flex-direction:column;justify-content:center}
  .front{background:linear-gradient(135deg,#1a3a6e,#2e5ca8);border:1px solid rgba(79,142,247,.3)}
  .back{background:rgba(255,255,255,.05);border:1px solid rgba(79,142,247,.2);
        transform:rotateY(180deg)}
  .front .q{font-size:1rem;font-weight:600;color:#e8f0ff;text-align:center}
  .front .hint{font-size:.75rem;color:#8aa0c8;margin-top:.75rem;text-align:center}
  .back .a{font-size:.95rem;color:#e8f0ff;line-height:1.6}
  .nav{display:flex;gap:.75rem;justify-content:center;margin-top:.5rem}
  .btn{padding:.55rem 1.4rem;border-radius:9px;border:1px solid rgba(79,142,247,.3);
       background:rgba(79,142,247,.1);color:#4f8ef7;font-size:.88rem;font-weight:600;
       cursor:pointer;font-family:inherit;transition:all .2s}
  .btn:hover{background:rgba(79,142,247,.2)}
  .btn.correct{background:rgba(34,197,94,.12);border-color:rgba(34,197,94,.4);color:#22c55e}
  .btn.wrong{background:rgba(239,68,68,.1);border-color:rgba(239,68,68,.35);color:#ef4444}
  .progress{height:4px;background:rgba(79,142,247,.15);border-radius:99px;margin-bottom:1.5rem;overflow:hidden}
  .progress-bar{height:100%;background:linear-gradient(90deg,#4f8ef7,#a78bfa);
                border-radius:99px;transition:width .4s}
  .done{text-align:center;padding:2rem;color:#22c55e;font-size:1.1rem;font-weight:600}
"""
    html = """<div class="fc-counter" id="ctr"></div>
<div class="progress"><div class="progress-bar" id="pb"></div></div>
<div id="cardWrap"></div>
<div class="nav">
  <button class="btn wrong" onclick="mark(false)">✗ Don't know</button>
  <button class="btn" onclick="flip()">Flip</button>
  <button class="btn correct" onclick="mark(true)">✓ Know it</button>
</div>"""
    script = f"""
const cards = {cards_json};
const esc = s => String(s ?? '').replace(/[&<>"']/g, m => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[m]));
let idx = 0, known = 0;
function render() {{
  if (idx >= cards.length) {{
    document.getElementById('cardWrap').innerHTML = '<div class="done">🎉 Done! ' + known + '/' + cards.length + ' known</div>';
    document.querySelector('.nav').style.display = 'none';
    document.getElementById('ctr').textContent = 'Complete';
    return;
  }}
  const c = cards[idx];
  document.getElementById('ctr').textContent = (idx+1) + ' / ' + cards.length;
  document.getElementById('pb').style.width = (idx/cards.length*100) + '%';
  document.getElementById('cardWrap').innerHTML = `
    <div class="card" id="card" onclick="flip()">
      <div class="inner">
        <div class="front"><div class="q">${{esc(c.q)}}</div><div class="hint">Click to reveal answer</div></div>
        <div class="back"><div class="a">${{esc(c.a)}}</div></div>
      </div>
    </div>`;
}}
function flip() {{ document.getElementById('card').classList.toggle('flipped'); }}
function mark(k) {{ if(k) known++; idx++; render(); }}
render();
"""
    return _page_shell(f"Flash Cards — {title}", css, html, script)


def _quiz_items(mcqs):
    """Quiz questions the view script can render: dicts whose `options` is a
    non-empty list of strings. q.options.map() crashed the page on a string or
    number, and a question with no options can never be answered (its Next
    button only appears after a pick), so such questions are left out."""
    out = []
    for m in _as_list(mcqs):
        if not isinstance(m, dict):
            continue
        opts = [t for t in (_scalar_text(o) for o in _as_list(m.get("options"))) if t.strip()]
        if opts:
            out.append({**m, "options": opts})
    return out

@app.route("/api/view/quiz/<job_id>")
def view_quiz(job_id):
    if not _valid_job(job_id):
        return "<h2 style='font-family:sans-serif;padding:2rem'>Invalid job ID</h2>", 400
    with _jobs_lock:
        job = get_job(job_id)
    if not job:
        return "<h2 style='font-family:sans-serif;padding:2rem'>Guide not found or expired</h2>", 404
    guide = job.get("guide")
    guide = guide if isinstance(guide, dict) else {}
    title = _he(_scalar_text(guide.get("title", "Quiz")) or "Quiz")
    mcqs = _quiz_items(guide.get("mcqs"))
    if not mcqs:
        return _page_shell(title, "", "<p style='text-align:center;color:#4a5f80;padding:3rem'>No quiz questions available.</p>")

    # Escape "<" so model-derived content can't break out of the <script> block.
    mcqs_json = json.dumps(mcqs).replace("<", "\\u003c")
    css = """
  .q-num{color:#8aa0c8;font-size:.82rem;margin-bottom:.4rem}
  .q-text{font-size:1rem;font-weight:600;color:#e8f0ff;margin-bottom:1rem;line-height:1.5}
  .opt{display:flex;align-items:center;gap:.6rem;width:100%;text-align:left;
       padding:.6rem .9rem;border-radius:9px;border:1px solid rgba(79,142,247,.2);
       background:rgba(255,255,255,.04);color:#8aa0c8;font-size:.88rem;cursor:pointer;
       font-family:inherit;margin-bottom:.45rem;transition:all .2s}
  .opt:hover:not(:disabled){border-color:#4f8ef7;color:#e8f0ff}
  .opt.correct{border-color:#22c55e;color:#22c55e;background:rgba(34,197,94,.1)}
  .opt.wrong{border-color:#ef4444;color:#ef4444;background:rgba(239,68,68,.08)}
  .explanation{margin-top:.75rem;padding:.75rem;border-radius:9px;
               background:rgba(79,142,247,.08);border:1px solid rgba(79,142,247,.2);
               font-size:.85rem;color:#8aa0c8;display:none}
  .nav{margin-top:1.25rem;display:flex;justify-content:flex-end}
  .next-btn{padding:.55rem 1.4rem;border-radius:9px;border:none;
            background:linear-gradient(135deg,#4f8ef7,#2e5ca8);color:#fff;
            font-size:.88rem;font-weight:600;cursor:pointer;font-family:inherit;display:none}
  .score-box{text-align:center;padding:2.5rem;background:rgba(79,142,247,.08);
             border:1px solid rgba(79,142,247,.2);border-radius:16px}
  .score-big{font-size:3rem;font-weight:700;color:#4f8ef7}
  .progress{height:4px;background:rgba(79,142,247,.15);border-radius:99px;margin-bottom:1.5rem;overflow:hidden}
  .progress-bar{height:100%;background:linear-gradient(90deg,#4f8ef7,#a78bfa);
                border-radius:99px;transition:width .4s}
"""
    html = """<div class="progress"><div class="progress-bar" id="pb"></div></div>
<div id="qWrap"></div>"""
    script = f"""
const qs = {mcqs_json};
const esc = s => String(s ?? '').replace(/[&<>"']/g, m => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[m]));
let idx=0, score=0, answered=false;
function render() {{
  if(idx>=qs.length){{
    document.getElementById('qWrap').innerHTML=`<div class="score-box">
      <div class="score-big">${{score}}/${{qs.length}}</div>
      <div style="color:#8aa0c8;margin-top:.5rem">Quiz complete!</div>
    </div>`;
    document.getElementById('pb').style.width='100%';
    return;
  }}
  const q=qs[idx]; answered=false;
  document.getElementById('pb').style.width=(idx/qs.length*100)+'%';
  const opts=q.options.map((o,i)=>`<button class="opt" id="o${{i}}" data-l="${{esc(o[0])}}" onclick="pick(this.dataset.l,this)">${{esc(o)}}</button>`).join('');
  document.getElementById('qWrap').innerHTML=`
    <div class="q-num">Question ${{idx+1}} of ${{qs.length}}</div>
    <div class="q-text">${{esc(q.q)}}</div>
    ${{opts}}
    <div class="explanation" id="exp">${{esc(q.explanation||'')}}</div>
    <div class="nav"><button class="next-btn" id="nxt" onclick="next()">Next →</button></div>`;
}}
function pick(letter,btn) {{
  if(answered) return; answered=true;
  const q=qs[idx];
  document.querySelectorAll('.opt').forEach(b=>b.disabled=true);
  if(letter===q.answer){{ btn.classList.add('correct'); score++; }}
  else {{ btn.classList.add('wrong');
    document.querySelectorAll('.opt').forEach(b=>{{if(b.textContent.startsWith(q.answer)) b.classList.add('correct');}});
  }}
  document.getElementById('exp').style.display='block';
  document.getElementById('nxt').style.display='inline-block';
}}
function next(){{ idx++; render(); }}
render();
"""
    return _page_shell(f"Quiz — {title}", css, html, script)


@app.route("/api/status")
def status():
    running = ollama_running()
    models  = ollama_models() if running else []
    active  = next((m for m in models if OLLAMA_MODEL in m), models[0] if models else None)
    return jsonify({"ollama": running, "model": active, "models": models})


# ── YouTube transcript endpoint ───────────────────────────────────────────────

def _parse_caption_xml(xml_text):
    """Parse YouTube caption XML and return joined transcript string."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return None
    texts = []
    for elem in root.iter("text"):
        t = (elem.text or "").strip()
        if t:
            t = t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"')
            texts.append(t)
    return " ".join(texts) if texts else None


def _fetch_captions(video_id):
    """Try multiple methods to get transcript from YouTube without downloading audio."""
    html = None

    # Method 1 — captionTracks from page source
    try:
        r = http.get(f"https://www.youtube.com/watch?v={video_id}", timeout=15,
                     headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        r.raise_for_status()
        html = r.text
    except Exception:
        pass

    if html:
        m = re.search(r'"captionTracks":\s*(\[.*?\])', html)
        if m:
            try:
                tracks = json.loads(m.group(1))
                # Prefer English ASR, then English, then any
                def track_priority(t):
                    lc = t.get("languageCode", "")
                    kind = t.get("kind", "")
                    if lc.startswith("en") and kind == "asr": return 0
                    if lc.startswith("en"): return 1
                    return 2
                tracks.sort(key=track_priority)
                for track in tracks:
                    track_url = track.get("baseUrl")
                    if not track_url:
                        continue
                    try:
                        tr = http.get(track_url, timeout=15)
                        result = _parse_caption_xml(tr.text)
                        if result:
                            return result
                    except Exception:
                        continue
            except Exception:
                pass

    # Method 2 — timedtext API (works for many videos without captionTracks in HTML)
    for kind in ("asr", ""):
        for lang in ("en", "en-US", "en-GB"):
            params = {"v": video_id, "lang": lang, "fmt": "srv3"}
            if kind:
                params["kind"] = kind
            try:
                tr = http.get("https://www.youtube.com/api/timedtext", params=params, timeout=10)
                if tr.status_code == 200 and tr.text.strip():
                    result = _parse_caption_xml(tr.text)
                    if result:
                        return result
            except Exception:
                continue

    raise ValueError("no_captions")


def _transcribe_with_whisper(video_id):
    """Download audio to a private temp dir, transcribe with Groq Whisper, delete
    immediately. A per-request mkdtemp avoids predictable /tmp names and the race
    where two concurrent requests for the same video clobber each other's files."""
    import glob, tempfile, shutil
    try:
        import yt_dlp
    except ImportError:
        raise ValueError("yt-dlp not installed — cannot transcribe audio.")

    workdir = tempfile.mkdtemp(prefix="yt_")
    prefix  = os.path.join(workdir, "audio")
    try:
        ydl_opts = {
            # Prefer smallest audio: opus<96k > m4a < 96k > any audio
            "format": "bestaudio[abr<=96][ext=webm]/bestaudio[abr<=96][ext=m4a]/bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
            "outtmpl": prefix + ".%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "max_filesize": 22 * 1024 * 1024,  # abort mid-download instead of filling disk
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

        files = glob.glob(prefix + ".*")
        if not files:
            raise ValueError("Audio download produced no file.")
        audio_path = files[0]

        size = os.path.getsize(audio_path)
        if size > 20 * 1024 * 1024:
            raise ValueError("Video audio exceeds 20 MB — try a shorter video (under ~15 minutes).")

        ext = os.path.splitext(audio_path)[1].lstrip(".")
        mime = "audio/mp4" if ext in ("m4a", "mp4") else "audio/webm"

        with open(audio_path, "rb") as af:
            r = http.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": (f"audio.{ext}", af, mime)},
                data={"model": "whisper-large-v3-turbo", "response_format": "text"},
                timeout=300,
            )
        if r.status_code == 413:
            raise ValueError("Audio file too large for Whisper — try a shorter video (under ~15 minutes).")
        r.raise_for_status()
        return r.text.strip()

    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _fetch_youtube_transcript(video_id):
    """Try captions first; fall back to Whisper audio transcription."""
    try:
        return _fetch_captions(video_id)
    except ValueError as e:
        if str(e) != "no_captions":
            raise
    if not GROQ_API_KEY:
        raise ValueError("No captions found and GROQ_API_KEY not set for Whisper fallback.")
    return _transcribe_with_whisper(video_id)


def _text_to_slides(text, chunk_size=500):
    """Split plain text into slide-like dicts."""
    words = text.split()
    chunks = []
    current = []
    current_len = 0
    for w in words:
        current.append(w)
        current_len += len(w) + 1
        if current_len >= chunk_size:
            chunks.append(" ".join(current))
            current = []
            current_len = 0
    if current:
        chunks.append(" ".join(current))
    return [
        {"slide_num": i + 1, "title": f"Segment {i + 1}", "content": c}
        for i, c in enumerate(chunks)
    ]


def _extract_video_id(url):
    """Extract YouTube video ID — only accepts youtube.com and youtu.be hostnames."""
    import urllib.parse
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:            # e.g. an unclosed "[" — was an HTML 500
        return None
    host = (parsed.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host  # strip prefix, not charset
    if host not in ("youtube.com", "youtu.be", "m.youtube.com"):
        return None
    patterns = [
        r'(?:v=|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def _stream_text_as_sse(text, language, out_name, job_source, dcfg=None, tok_left=None, include_quiz=True, include_mcq=True, uid=None, anon_ip=None, charge=None, ar=None, hold_slot=False, on_done=None):
    """Shared SSE generator for YouTube/text endpoints. `charge` is the credit
    spent for this run (None for the free demo); it is refunded exactly once on
    any failure or early disconnect (_Charge.refund is idempotent, so the
    youtube wrapper's own guard can never double-refund).
    Free mode: the run first takes a generation slot (queued events while it
    waits) and gives it back in the `finally`. `hold_slot=True` means the caller
    (youtube) already holds one — and releases it — so none is taken here.
    `ar` picks the language of the queue/busy/error texts (default: the guide's).
    `on_done(overview, pdf_bytes, md_text)`, when given, is called once the guide is
    built and stored (the demo cache uses it); it can never break the stream."""
    _dcfg = dcfg or DETAIL["standard"]
    _ar = (language == "ar") if ar is None else ar
    if charge is None and (uid or anon_ip):
        charge = _Charge(uid=uid, ip=anon_ip, tok_left=tok_left)
    def _refund():
        if charge is not None:
            charge.refund()
    def _abandon():
        if charge is not None:
            charge.abandon()
    def generate():
        settled = False
        slot = None
        try:
            if FREE_MODE and not hold_slot:
                slot = yield from _gen_slot_acquire(_ar)
                if slot is None:
                    settled = True
                    _refund()
                    yield _sse(_busy_event(_ar)); return
            yield _sse({"step": "extract", "msg": "Preparing content…"})
            slides = _text_to_slides(text)
            if not slides:
                settled = True
                _refund()
                yield _sse({"error": "No content extracted"}); return
            yield _sse({"step": "extract", "msg": f"Split into {len(slides)} segments — analysing…"})

            dcfg = _dcfg

            yield _sse({"step": "overview", "msg": "Analysing structure and keywords…"})
            if charge is not None:
                charge.begin_work()   # the first paid AI call: from here a disconnect no longer refunds
            overview = pass1_overview(slides, language, dcfg)

            raw_sections = overview.get("sections", [])
            overview["sections"] = [
                s if isinstance(s, dict) else {"title": str(s), "slide_nums": []}
                for s in (raw_sections if isinstance(raw_sections, list) else [])
            ]
            raw_keywords = overview.get("keywords", [])
            overview["keywords"] = [
                k if isinstance(k, dict) else {"term": str(k), "definition": ""}
                for k in (raw_keywords if isinstance(raw_keywords, list) else [])
            ]
            if not overview["sections"]:
                overview["sections"] = [{
                    "title": overview.get("title", "Content Overview"),
                    "slide_nums": [s["slide_num"] for s in slides]
                }]

            sections = overview["sections"]
            for evt in _sections_parallel(sections, slides, language, dcfg):
                yield _sse(evt)
            _require_notes(sections, charged=charge is not None)

            for evt in _flashcards_mcq_parallel(overview, language, dcfg, include_quiz, include_mcq):
                yield _sse(evt)

            overview["language"] = language   # so exports + the in-app viewer localise
            yield _sse({"step": "pdf", "msg": "Building PDF & Markdown…"})
            pdf_buf = build_pdf(overview, language, out_name)
            pdf_bytes = pdf_buf.read()
            md_text = build_markdown(overview)

            job_id = uuid.uuid4().hex
            store_job(job_id, pdf_bytes, md_text, overview, None, f"{out_name}_study_guide.pdf")
            if on_done is not None:
                try:
                    on_done(overview, pdf_bytes, md_text)
                except Exception:
                    _log.error("on_done hook failed:\n%s", _tb.format_exc())

            done_data = {"step": "done", "job_id": job_id,
                         "sections":   len(sections),
                         "keywords":   len(overview.get("keywords",   [])),
                         "flashcards": len(overview.get("flashcards", [])),
                         "mcqs":       len(overview.get("mcqs",       []))}
            if tok_left is not None:
                done_data["tokens_remaining"] = tok_left
            if charge is not None and charge.anon_left is not None:   # free mode, anonymous: free guides left before sign-in
                done_data["anon_remaining"] = charge.anon_left
            if _is_partial(overview, include_quiz, include_mcq):
                done_data["partial"] = True
            yield _sse(done_data)
            settled = True
            if charge is not None:
                charge.settle()

        except Exception as e:
            settled = True
            _log.error("STREAM_TEXT_ERROR: %s\n%s", e, _tb.format_exc())
            _refund()
            yield _sse(_gen_error_event(e, charge, _ar))
        finally:
            if slot is not None:
                slot.release()
            if not settled:
                _log.info("text stream closed early (client gone)")
                _abandon()   # refunds only if no paid AI work had started
    return generate


def _yt_blocked(e):
    """True for a yt-dlp DownloadError (bot check, age gate, region block…)."""
    try:
        from yt_dlp.utils import DownloadError
        return isinstance(e, DownloadError)
    except ImportError:
        return False

def _yt_friendly_err(e):
    """User-facing text for a YouTube-phase failure — never raw yt-dlp/HTTP text
    (it leaked internal URLs and 'sign in to confirm you're not a bot')."""
    if _yt_blocked(e):
        _log.warning("yt-dlp download error: %s", e)
        return ("YouTube blocked this video — try one with captions, or paste the "
                "transcript in the Text tab.")
    return _safe_err(e)

def _yt_error_event(e):
    """SSE error event for the YouTube phase; code 'yt_blocked' → localized text."""
    ev = {"error": _yt_friendly_err(e)}
    if _yt_blocked(e):
        ev["code"] = "yt_blocked"
    return ev


def _yt_duration(video_id):
    """Return video duration in seconds (or None if unknown)."""
    try:
        import yt_dlp
        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 20}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        return info.get("duration")
    except Exception:
        return None

@app.route("/api/youtube", methods=["POST"])
def youtube_transcript():
    # Rate-limit BEFORE the expensive yt-dlp scrape / Whisper path (this endpoint
    # had none, so anon callers could force unbounded yt-dlp + paid transcription).
    if not _check_rate_limit(_client_ip(), scope="youtube", limit=_precheck_rate_limit()):
        return jsonify({"error": "Too many requests — please wait a moment and try again."}), 429
    uid = _auth_optional(request)
    if uid is False:
        return _auth_rejected()   # a sent-but-rejected token is never 'anonymous'

    # Type-check every field first: a number/list url or a list detail used to
    # crash here with a 500 (.strip() / unhashable dict key).
    data = {}
    try:
        data = _json_object()
        url          = _str_field(data, "url").strip()
        lang_param   = _str_field(data, "language", "auto")
        detail_level = _str_field(data, "detail", "standard")
        include_quiz = _str_field(data, "mode", "full") != "summary"
        include_mcq  = _flag_field(data, "quiz", True)
    except _BadField as e:
        return _bad_field(e, data)
    yt_dcfg = DETAIL.get(detail_level, DETAIL["standard"])
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    if not ollama_running():
        return jsonify({"error": "AI service is not configured. Set GROQ_API_KEY."}), 503

    video_id = _extract_video_id(url)
    if not video_id:
        return jsonify({"error": "Could not extract video ID from URL"}), 400

    # Free mode: a full house is busy NOW — before the yt-dlp probe below (it holds a web
    # thread outside the generation gate) and before anything is charged.
    if FREE_MODE and not _gen_has_room():
        return _busy_response(_wants_ar(data))

    # Reject videos longer than 50 minutes (checked before consuming a token)
    _dur = _yt_duration(video_id)
    if _dur and _dur > 3000:
        return jsonify({"error": "This video is too long. Maximum supported length is 50 minutes."}), 400

    charge, err = _charge_credit(uid, request, data)
    if err:
        return err
    tok_left = charge.tok_left

    _log_usage_async("user" if uid else "anon", "youtube")
    out_name = _safe_name(f"youtube_{video_id}")
    ar = _wants_ar(data) if FREE_MODE else False

    def generate():
        # This guard owns the caption/Whisper phase only. Once the text pipeline
        # takes over (`yield from`, so close() reaches it) its own guard owns the
        # refund; the shared _Charge makes a double refund impossible anyway.
        # Free mode: the generation slot is taken HERE, before the heavy caption /
        # Whisper download, held through the text pipeline (hold_slot) and
        # released in this `finally` — one slot per request, never two.
        settled = delegated = False
        slot = None
        try:
            if FREE_MODE:
                slot = yield from _gen_slot_acquire(ar)
                if slot is None:
                    settled = True
                    charge.refund()
                    yield _sse(_busy_event(ar)); return
            yield _sse({"step": "transcript", "msg": "Looking for captions…"})
            try:
                transcript_text = _fetch_captions(video_id)
                yield _sse({"step": "transcript", "msg": "Captions found — processing…"})
            except ValueError as e:
                if str(e) != "no_captions":
                    settled = True
                    charge.refund()
                    yield _sse({"error": _safe_err(e)}); return
                if not GROQ_API_KEY:
                    settled = True
                    charge.refund()
                    yield _sse({"error": "No captions found and GROQ_API_KEY not set."}); return
                yield _sse({"step": "transcript", "msg": "No captions — downloading audio for Whisper transcription…"})
                try:
                    charge.begin_work()   # the paid Whisper call: from here a disconnect no longer refunds
                    transcript_text = _transcribe_with_whisper(video_id)
                    yield _sse({"step": "transcript", "msg": "Audio transcribed — processing…"})
                except ValueError as we:
                    settled = True
                    charge.refund()
                    yield _sse({"error": _safe_err(we)}); return

            language = lang_param if lang_param in ("ar", "en") else _detect_language(transcript_text)
            lang_label = "Arabic" if language == "ar" else "English"
            yield _sse({"step": "transcript", "msg": f"Transcript ready ({lang_label}) — building study guide…", "language": language})
            delegated = True
            yield from _stream_text_as_sse(transcript_text, language, out_name, "youtube", yt_dcfg, tok_left,
                                           include_quiz, include_mcq=include_mcq, charge=charge,
                                           ar=ar if FREE_MODE else None, hold_slot=slot is not None)()
            settled = True
        except Exception as ex:
            settled = True
            _log.error("youtube SSE error: %s\n%s", ex, _tb.format_exc())
            charge.refund()
            yield _sse(_yt_error_event(ex))
        finally:
            if slot is not None:
                slot.release()
            if not settled and not delegated:
                _log.info("youtube stream closed early (client gone)")
                charge.abandon()   # refunds only if no paid AI work had started

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ── URL / pasted text endpoint ─────────────────────────────────────────────────

class _PinnedIPAdapter(http.adapters.HTTPAdapter):
    """Pin the socket connection to a pre-validated IP so a DNS rebind can't
    swap in an internal address between our SSRF check and the actual request,
    while preserving TLS SNI + certificate hostname verification for the host."""
    def __init__(self, host, pinned_ip, is_https, *args, **kwargs):
        self._host      = host
        self._pinned_ip = pinned_ip
        self._is_https  = is_https
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        if self._is_https:
            kwargs["server_hostname"] = self._host   # SNI = real host
            kwargs["assert_hostname"] = self._host    # verify cert against real host
        return super().init_poolmanager(*args, **kwargs)

    def send(self, request, **kwargs):
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(request.url)
        request.headers["Host"] = parsed.netloc      # keep the original Host header
        ip = f"[{self._pinned_ip}]" if ":" in self._pinned_ip else self._pinned_ip
        netloc = f"{ip}:{parsed.port}" if parsed.port else ip
        request.url = urlunparse(parsed._replace(netloc=netloc))
        return super().send(request, **kwargs)


_META_CHARSET_RE = re.compile(rb'<meta[^>]+charset\s*=\s*["\']?\s*([A-Za-z0-9_.:-]+)', re.IGNORECASE)

def _decode_html(content, content_type):
    """Page bytes → str. Charset from the Content-Type header, else <meta charset>,
    else UTF-8 (cp1252 if the bytes aren't UTF-8). requests' own fallback for a
    header without charset is ISO-8859-1, which turned UTF-8 Arabic into mojibake;
    an unknown charset name falls through instead of raising LookupError."""
    import codecs
    m = re.search(r'charset\s*=\s*["\']?\s*([A-Za-z0-9_.:-]+)', content_type or "", re.IGNORECASE)
    declared = [m.group(1)] if m else []
    mm = _META_CHARSET_RE.search(content[:4096])
    if mm:
        meta_cs = mm.group(1).decode("ascii", "ignore")
        # A <meta> read as ASCII bytes can't be UTF-16/32; browsers use UTF-8.
        declared.append("utf-8" if meta_cs.lower().startswith(("utf-16", "utf-32")) else meta_cs)
    for cs in declared:
        try:
            info = codecs.lookup(cs)
        except LookupError:
            continue
        if not getattr(info, "_is_text_encoding", True):   # base64, hex, rot13…
            continue
        return content.decode(cs, "replace")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp1252", "replace")

def _fetch_url_text(url):
    """Fetch a PUBLIC webpage and extract readable text. SSRF guard: public
    http(s) only, no private/internal addresses, no redirects, 5 MB cap. The
    connection is pinned to the vetted IP to defeat DNS-rebinding attacks."""
    from urllib.parse import urlparse
    import socket, ipaddress
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Only public http(s) URLs are supported.")
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(p.hostname, port, proto=socket.IPPROTO_TCP)
    except OSError:
        raise ValueError("Could not resolve URL host.")
    pinned_ip = None
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if (addr.is_private or addr.is_loopback or addr.is_link_local or
                addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            raise ValueError("URL points to a private/internal address — not allowed.")
        if pinned_ip is None:
            pinned_ip = str(addr)
    if not pinned_ip:
        raise ValueError("Could not resolve URL host.")
    sess = http.Session()
    sess.mount(f"{p.scheme}://", _PinnedIPAdapter(p.hostname, pinned_ip, p.scheme == "https"))
    try:
        r = sess.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"},
                     allow_redirects=False, stream=True)
        if 300 <= r.status_code < 400:
            raise ValueError("URL redirects are not supported — paste the final URL.")
        r.raise_for_status()
        content = r.raw.read(5 * 1024 * 1024 + 1, decode_content=True)
        if len(content) > 5 * 1024 * 1024:
            raise ValueError("Page too large (max 5 MB).")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Could not fetch URL: {e}")
    finally:
        sess.close()
    html = _decode_html(content, r.headers.get("Content-Type", ""))
    # Remove script/style blocks
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    # Extract text from meaningful tags
    parts = []
    for m in re.finditer(r'<(h[1-6]|p|li)[^>]*>(.*?)</\1>', html, re.DOTALL | re.IGNORECASE):
        inner = re.sub(r'<[^>]+>', ' ', m.group(2))
        inner = inner.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&nbsp;', ' ').replace('&#39;', "'").replace('&quot;', '"')
        inner = ' '.join(inner.split())
        if len(inner) > 20:
            parts.append(inner)
    return ' '.join(parts) if parts else ' '.join(re.sub(r'<[^>]+>', ' ', html).split())


# Fixed sample lecture for the zero-friction "Try a sample" demo (no credit spent).
_DEMO_TEXT_EN = (
    "Photosynthesis is the process by which green plants, algae, and some bacteria convert "
    "light energy into chemical energy stored in glucose. It takes place mainly in the leaves, "
    "inside organelles called chloroplasts, which contain the green pigment chlorophyll. The "
    "overall equation is: six carbon dioxide molecules plus six water molecules, using light "
    "energy, produce one glucose molecule and six oxygen molecules. Photosynthesis has two main "
    "stages. The light-dependent reactions occur in the thylakoid membranes: chlorophyll absorbs "
    "sunlight, water is split to release oxygen, and the energy carriers ATP and NADPH are "
    "produced. The light-independent reactions, also called the Calvin cycle, take place in the "
    "stroma: ATP and NADPH are used to fix carbon dioxide into glucose. Several factors affect "
    "the rate of photosynthesis, including light intensity, carbon dioxide concentration, and "
    "temperature. Photosynthesis is essential to life on Earth because it releases oxygen and "
    "forms the base of most food chains."
)
_DEMO_TEXT_AR = (
    "البناء الضوئي هو العملية التي تحوّل بها النباتات الخضراء والطحالب وبعض البكتيريا طاقة الضوء "
    "إلى طاقة كيميائية مخزّنة في الجلوكوز. تحدث هذه العملية بشكل رئيسي في الأوراق داخل عُضيّات "
    "تُسمى البلاستيدات الخضراء التي تحتوي على صبغة الكلوروفيل الخضراء. المعادلة الإجمالية: ستة "
    "جزيئات من ثاني أكسيد الكربون مع ستة جزيئات ماء، وباستخدام طاقة الضوء، تنتج جزيء جلوكوز واحد "
    "وستة جزيئات أكسجين. للبناء الضوئي مرحلتان: التفاعلات المعتمدة على الضوء تحدث في أغشية "
    "الثايلاكويد حيث يمتص الكلوروفيل ضوء الشمس ويُشطر الماء لإطلاق الأكسجين وتُنتَج حاملات الطاقة "
    "ATP وNADPH؛ والتفاعلات غير المعتمدة على الضوء (دورة كالفن) تحدث في الحشوة حيث تُستخدَم ATP "
    "وNADPH لتثبيت ثاني أكسيد الكربون في الجلوكوز. تؤثر عدة عوامل في معدله منها شدة الضوء وتركيز "
    "ثاني أكسيد الكربون ودرجة الحرارة. وهو ضروري للحياة لأنه ينتج الأكسجين ويشكّل أساس السلاسل الغذائية."
)

# ── Free mode: the sample lecture is made ONCE per language ────────────────────
# The demo text is fixed and its answer does not depend on the visitor, so paying
# Groq for every tap would be money for nothing (and an unmetered way to burn the
# budget). The first run per language is a normal generation, counted against the
# global daily budget; the finished guide is kept for _DEMO_CACHE_TTL_S and every
# later demo is served as a fresh, independent job at ZERO AI cost. A failed or
# partial run is never cached. In-memory like every guide, so a restart clears it.
_DEMO_CACHE_TTL_S = 6 * 3600
_demo_cache       = {}                 # "en" / "ar" → {"at", "guide", "pdf", "md", "filename"}
_demo_lock        = threading.Lock()

def _demo_cache_get(lang):
    with _demo_lock:
        entry = _demo_cache.get(lang)
        if entry is not None and time.monotonic() - entry["at"] >= _DEMO_CACHE_TTL_S:
            _demo_cache.pop(lang, None)
            entry = None
        return entry

def _demo_cache_put(lang, overview, pdf_bytes, md_text):
    if _is_partial(overview, True, True):      # a guide missing its cards or quiz must not stick
        return
    with _demo_lock:
        _demo_cache[lang] = {"at": time.monotonic(), "guide": copy.deepcopy(overview),
                             "pdf": pdf_bytes, "md": md_text,
                             "filename": "sample_lecture_study_guide.pdf"}

def _demo_replay(entry):
    """The cached sample as an SSE generator function: the same kind of events as a real
    run, a NEW job id each time (own 15-minute life, own delete), no AI call."""
    def generate():
        yield _sse({"step": "extract", "msg": "Preparing content…"})
        yield _sse({"step": "overview", "msg": "Analysing structure and keywords…"})
        guide  = copy.deepcopy(entry["guide"])
        job_id = uuid.uuid4().hex
        store_job(job_id, entry["pdf"], entry["md"], guide, None, entry["filename"])
        yield _sse({"step": "done", "job_id": job_id,
                    "sections":   len(guide.get("sections",   [])),
                    "keywords":   len(guide.get("keywords",   [])),
                    "flashcards": len(guide.get("flashcards", [])),
                    "mcqs":       len(guide.get("mcqs",       [])),
                    "tokens_remaining": 0})
    return generate

def _demo_charge(ar=False):
    """A real (uncached) demo run costs real AI money, so it takes one unit from the
    GLOBAL daily budget — the breaker bounds it like any guide — and gives it back
    if the run fails. → (_Charge, None) or (None, refusal)."""
    got = _fair_consume("fair:global", FAIR_GLOBAL_DAILY)
    if got is False:
        return None, _fair_refusal("busy_today", ar)
    return _Charge(fair_keys=("fair:global",) if got else ()), None

@app.route("/api/summarize-text", methods=["POST"])
def summarize_text():
    # Zero-friction demo: a curious visitor (esp. on mobile, with no file to hand)
    # taps "Try a sample" → a real guide on a FIXED server-side lecture. No token or
    # visitor allowance is spent; a separate, tighter rate limit applies. In free mode
    # the guide is made once per language and then copied (see _demo_cache) — a real
    # run is counted against the global budget. This is the activation unlock: the
    # point is that they SEE it work.
    # The body is read ONCE, here, before anything can be spent. silent=True: a
    # non-JSON body is {} (→ "No text or URL" below); a JSON array/string/number
    # body is a 400 (it used to 500 on .get()).
    try:
        data = _json_object()
    except _BadField as e:
        return _bad_field(e)
    if data.get("demo"):
        if not _check_rate_limit(_client_ip(), scope="demo", limit=8):
            return jsonify({"error": "Too many demo runs — please wait a moment."}), 429
        d_lang = "ar" if data.get("language") == "ar" else "en"
        sse_headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        cached = _demo_cache_get(d_lang) if FREE_MODE else None
        if cached is not None:
            _log_usage_async("demo", "demo")
            return Response(stream_with_context(_demo_replay(cached)()), mimetype="text/event-stream",
                            headers=sse_headers)
        if not ollama_running():
            return jsonify({"error": "AI service is not configured. Set GROQ_API_KEY."}), 503
        d_text = _DEMO_TEXT_AR if d_lang == "ar" else _DEMO_TEXT_EN
        charge, on_done = None, None
        if FREE_MODE:
            if not _gen_has_room():
                return _busy_response(d_lang == "ar")
            charge, err = _demo_charge(d_lang == "ar")
            if err:
                return err
            on_done = lambda overview, pdf_bytes, md_text: _demo_cache_put(d_lang, overview, pdf_bytes, md_text)
        _log_usage_async("demo", "demo")
        gen = _stream_text_as_sse(d_text, d_lang, "sample_lecture", "text",
                                  DETAIL["standard"], 0, True, uid=None, anon_ip=None,
                                  charge=charge, on_done=on_done)
        return Response(stream_with_context(gen()), mimetype="text/event-stream", headers=sse_headers)

    # Rate-limit BEFORE the server-side URL fetch + multi-pass LLM run.
    if not _check_rate_limit(_client_ip(), scope="text", limit=_gen_rate_limit()):
        return jsonify({"error": "Too many requests — please wait a moment and try again."}), 429
    uid = _auth_optional(request)
    if uid is False:
        return _auth_rejected()   # a sent-but-rejected token is never 'anonymous'

    # Validate and normalise every field BEFORE the charge: {"text": 123} (or a
    # number/list url, filename, language, detail…) used to spend a credit and
    # then 500 with no refund. Missing/null → the default.
    try:
        text         = _str_field(data, "text").strip()
        url          = _str_field(data, "url").strip()
        lang_param   = _str_field(data, "language", "auto")
        filename     = _safe_name(_str_field(data, "filename") or "pasted_text")
        detail_level = _str_field(data, "detail", "standard")
        include_quiz = _str_field(data, "mode", "full") != "summary"
        include_mcq  = _flag_field(data, "quiz", True)
    except _BadField as e:
        return _bad_field(e, data)
    txt_dcfg = DETAIL.get(detail_level, DETAIL["standard"])
    if not text and not url:
        return _bad_request(_NO_TEXT_EN, _NO_TEXT_AR, data)
    # A URL that can never be fetched (no https://, localhost, a private IP…) is
    # refused BEFORE the charge: charging then refunding could lose an anonymous
    # visitor's free preview when the durable refund is unavailable.
    if not text and not _url_precheck(url):
        return _bad_request(_BAD_URL_EN, _BAD_URL_AR, data)

    # A full house is busy NOW, before the charge and before the URL fetch below (which
    # holds a web thread outside the generation gate).
    if FREE_MODE and not _gen_has_room():
        return _busy_response(_wants_ar(data))
    # The server-side URL fetch runs before any slot: its own, lower per-IP limit. (Pasted
    # text has no such work, so it keeps the general limit.)
    if not text and url and not _check_rate_limit(_client_ip(), scope="texturl", limit=_precheck_rate_limit()):
        return jsonify({"error": "Too many requests — please wait a moment and try again."}), 429

    charge, err = _charge_credit(uid, request, data)
    if err:
        return err
    tok_left = charge.tok_left

    _log_usage_async("user" if uid else "anon", "text")

    if not ollama_running():
        charge.refund()
        return jsonify({"error": "AI service is not configured. Set GROQ_API_KEY."}), 503

    if not text and url:
        try:
            text = _fetch_url_text(url)
        except ValueError as e:
            charge.refund()
            return jsonify({"error": str(e)}), 400
        except Exception:
            charge.refund()
            raise

    if not text:   # the page had no readable text
        charge.refund()
        return _bad_request(_NO_TEXT_EN, _NO_TEXT_AR, data)

    # Cap total input so a huge paste / large fetched page can't amplify Groq cost.
    text = text[:500_000]

    try:
        language = lang_param if lang_param in ("ar", "en") else _detect_language(text)
    except Exception:
        charge.refund()
        raise
    gen = _stream_text_as_sse(text, language, filename, "text", txt_dcfg, tok_left, include_quiz, include_mcq=include_mcq, charge=charge,
                              ar=_wants_ar(data) if FREE_MODE else None)
    return Response(
        stream_with_context(gen()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ── Anki export endpoint ───────────────────────────────────────────────────────

@app.route("/api/export/anki/<job_id>")
def export_anki(job_id):
    if not _valid_job(job_id):
        return jsonify({"error": "Invalid job ID"}), 400
    job = get_job(job_id)
    if not job:
        return _job_expired_json()
    guide = job.get("guide", {})
    flashcards = [f for f in guide.get("flashcards", []) if isinstance(f, dict)]
    if not flashcards:
        return jsonify({"error": "This guide has no flash cards to export.", "code": "no_flashcards"}), 404

    import csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["front", "back"])
    def _csv_safe(v):
        v = str(v)
        # Excel/Sheets evaluate a formula even when it's preceded by leading
        # whitespace or a carriage return, so test the first NON-blank char.
        stripped = v.lstrip(" \t\r\n")
        return "'" + v if stripped[:1] in ("=", "+", "-", "@") else v
    for fc in flashcards:
        writer.writerow([_csv_safe(fc.get("q", "")), _csv_safe(fc.get("a", ""))])

    csv_bytes = buf.getvalue().encode("utf-8")
    base = job.get("filename", "study_guide").replace(".pdf", "")
    download_name = f"{_safe_name(base)}_anki.csv"
    return send_file(
        io.BytesIO(csv_bytes),
        mimetype="text/csv",
        as_attachment=True,
        download_name=download_name
    )


@app.route("/api/summarize", methods=["POST"])
def summarize():
    return jsonify({"error": "This endpoint is deprecated. Use /api/summarize-stream instead."}), 410



# \u2500\u2500 Legal pages (privacy / terms) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
def _legal_shell(title, body):
    return """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>""" + title + """ \u2014 Alimne</title>
<style>
  :root{color-scheme:dark}
  *{box-sizing:border-box}
  body{margin:0;background:#0a1628;color:#dce6f5;font-family:'Segoe UI',system-ui,-apple-system,sans-serif;line-height:1.7}
  .wrap{max-width:820px;margin:0 auto;padding:2.5rem 1.5rem 4rem}
  .brand{display:flex;align-items:center;gap:.6rem;margin-bottom:2rem;text-decoration:none}
  .logo{width:38px;height:38px;border-radius:11px;background:linear-gradient(135deg,#4f8ef7,#a78bfa);
        display:flex;align-items:center;justify-content:center;font-weight:800;color:#fff;font-size:1.1rem;flex-shrink:0}
  .brand span{font-weight:800;font-size:1.15rem;color:#fff}
  .brand small{display:block;font-weight:500;font-size:.7rem;color:#7f93b3;letter-spacing:.02em}
  h1{font-size:1.9rem;color:#fff;margin:.2rem 0 .3rem}
  .updated{color:#7f93b3;font-size:.85rem;margin-bottom:2rem}
  h2{color:#8fb4ff;font-size:1.15rem;margin:2.2rem 0 .6rem}
  p,li{color:#c2d0e6;font-size:.95rem}
  a{color:#6fa8ff}
  ul{padding-left:1.2rem}
  .note{background:rgba(79,142,247,.08);border:1px solid rgba(79,142,247,.2);border-radius:12px;padding:1rem 1.2rem;margin:1.5rem 0}
  footer{margin-top:3rem;padding-top:1.5rem;border-top:1px solid rgba(120,140,180,.18);color:#7f93b3;font-size:.82rem}
  footer a{margin-right:1rem}
</style></head><body><div class="wrap">
<a class="brand" href="/"><div class="logo">A</div><span>Alimne<small>by souc ai</small></span></a>
""" + body + """
<footer>
  <a href="/">Home</a><a href="/privacy">Privacy</a><a href="/terms">Terms</a>
  <div style="margin-top:.6rem">\u00a9 2026 Alimne \u00b7 a souc ai product \u00b7 <a href="mailto:sales@souc.ai">sales@souc.ai</a></div>
</footer></div></body></html>"""


def _legal_free_mode():
    """True when the legal pages should describe Alimne as free (the default).
    The very same value as the credit logic (the FREE_MODE constant, one parser for
    "0", "false", "no", "off"): ALIMNE_FREE_MODE off brings the old token plans back,
    and then these pages say so again — they can never contradict what the app is
    actually doing."""
    return FREE_MODE


@app.route("/privacy")
def privacy_page():
    free = _legal_free_mode()
    acct_use = ("apply the fair-use daily limits to your account" if free
                else "track your monthly token balance")
    if free:
        counters = """<li><strong>Usage counters:</strong> to keep Alimne available to everyone and to prevent abuse, we count how many
study guides are generated (and chat questions asked). For visitors who are not signed in, one counter records how many
study guides have been made from your browser, so that we know when a free account becomes required; it is kept
against a random device identifier stored in your browser and is not reset daily. The other counters are daily
ones, kept against your IP address, or your account ID if you are signed in, plus overall daily totals. Each
counter is stored in our database (Supabase) and holds only a number and timestamps \u2014 never your files, text or study guides \u2014
and is used for nothing except applying usage limits.</li>"""
    else:
        counters = """<li><strong>Usage counters:</strong> to keep the free previews fair, we count how many are used per device. The counter
is stored in our database (Supabase) against a random device identifier kept in your browser (and, in server memory
only, your IP address). It holds only a number and timestamps \u2014 never your files, text or study guides \u2014 and
is used for nothing except applying usage limits.</li>"""
    if free:
        payments = """<p>Alimne is free and takes no payments. A small number of people subscribed to a paid plan before
Alimne became free; those subscriptions are processed by <strong>Stripe, Inc.</strong> We never receive or store
your full card number \u2014 Stripe handles payment details directly. For those subscribers we store only a Stripe
customer reference and your subscription status.</p>"""
    else:
        payments = """<p>Subscriptions are processed by <strong>Stripe, Inc.</strong> We never receive or store your full card
number \u2014 Stripe handles payment details directly. We store only a Stripe customer reference and your
subscription status.</p>"""
    # Free mode only: the client keeps what was waiting across the full-page Google sign-in, in the
    # visitor's own browser (IndexedDB). It is a copy on their device, so the policy says so. The token
    # client makes no such copy, and its page stays as it was.
    if free:
        signin_copy = """
<li><strong>Signing in:</strong> if a file, link or pasted text is waiting when you leave the page to sign in
with Google, your browser keeps it on your own device (it is not sent to us until you press Generate) so that it is
still there when you return. That copy is deleted as soon as it is restored, or when you sign out; a copy older
than 30 minutes is never used and is deleted the next time you open Alimne in that browser.</li>"""
        signin_copy_ar = (" وإذا غادرتَ الصفحة لتسجيل الدخول عبر Google،"
                          " يبقى ما كان ينتظر (ملف أو رابط أو نص) محفوظًا في متصفحك فقط إلى أن تعود،"
                          " ولا يُرسَل إلينا قبل أن تضغط «توليد».")
    else:
        signin_copy = signin_copy_ar = ""
    body = """
<h1>Privacy Policy</h1>
<div class="updated">Last updated: 7 October 2026</div>
<p>Alimne ("we", "us"), operated by souc ai, turns your slides, documents, pasted text and
YouTube videos into study guides and summaries. Privacy is core to how the product is built.
This policy explains what we handle and why.</p>

<div class="note"><strong>The short version:</strong> the files and text you upload are processed
<strong>in memory only</strong>, are <strong>never written to disk or seen by any human</strong>, and are
<strong>automatically deleted within 15 minutes</strong> \u2014 or immediately when you press
"Delete now". We do not sell your data and we do not show ads.</div>

<div class="note" lang="ar" dir="rtl"><strong>باختصار:</strong> تُعالَج ملفاتك ونصوصك <strong>في الذاكرة فقط</strong>،
ولا تُكتب على القرص ولا يطّلع عليها أي شخص، وتُحذف <strong>تلقائيًا خلال 15 دقيقة</strong> أو فورًا عند طلبك.
لا نبيع بياناتك ولا نعرض إعلانات. الأدلة المشتركة: إذا اخترتَ «مشاركة» يُخزَّن الدليل الناتج (وليس ملفك الأصلي)
ليبقى رابطه العام يعمل. ولتطبيق حدود الاستخدام العادل نحتفظ بعدّاد (رقم وتواريخ فقط، دون أي محتوى دراسي) مرتبط بمعرّف
عشوائي لجهازك أو بعنوان IP أو بحسابك.""" + signin_copy_ar + """ النص الإنجليزي هو المرجع.</div>

<h2>1. Study content you submit</h2>
<ul>
<li><strong>Files, pasted text and URLs</strong> are held in server memory only for the length of your
session (maximum 15 minutes) and are purged automatically after that window, or instantly on your request.
They are never persisted to disk, logged in full, or reviewed by a person.</li>
<li>To generate a guide, the extracted text is sent to our AI provider (Groq) for processing. It is used
only to produce your result and is not used to train models by us.</li>
<li><strong>Shared guides:</strong> if you press "Share" on a guide, that generated guide (not your original
file) is stored so its public link keeps working until it is removed.</li>""" + signin_copy + """
</ul>

<h2>2. Account &amp; fair-use information</h2>
<ul>
<li>If you sign in, we store your <strong>email address</strong> and a display name/avatar (when provided by
Google) in our authentication database (Supabase) to identify your account and """ + acct_use + """.</li>
<li>We use a session cookie / local storage entry to keep you signed in.</li>
""" + counters + """
</ul>

<h2>3. Payments</h2>
""" + payments + """

<h2>4. What we do not do</h2>
<ul>
<li>We do not sell, rent, or trade your personal data.</li>
<li>We do not run advertising or third-party ad trackers.</li>
<li>We do not retain your study material beyond the 15-minute processing window, except guides you choose to Share (see section 1).</li>
</ul>

<h2>5. Data retention &amp; your rights</h2>
<p>Study jobs: deleted within 15 minutes (or on demand). Account data: kept until you ask us to delete it.
Usage counters (section 2): kept in our database until we clear them; we may delete old counters at any time.
You may request access to, or deletion of, your account data or any usage counters linked to you at any time by emailing
<a href="mailto:sales@souc.ai">sales@souc.ai</a>.</p>

<h2>6. Third-party services</h2>
<p>We rely on Supabase (authentication, account database &amp; usage counters), Stripe (payments for existing subscribers), Groq (AI processing),
Render (hosting) and Cloudflare (DNS/network). Each processes data only as needed to provide the service.</p>

<h2>7. Changes &amp; contact</h2>
<p>We may update this policy; material changes will be reflected here with a new date. Questions?
Email <a href="mailto:sales@souc.ai">sales@souc.ai</a>.</p>
"""
    return _legal_shell("Privacy Policy", body), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/terms")
def terms_page():
    free = _legal_free_mode()
    if free:
        # The account rule is worded from the REAL allowance (ANON_FREE_USES), so this
        # page can never promise more free guides than the charge logic gives.
        rule_en, rule_ar = _anon_rule_text()
        evade = "the usage limits or the account requirement (for example with automated tools, or by resetting or rotating devices or networks)"
        plans = """<h2>2. Free to use &amp; fair use</h2>
<ul>
<li><strong>Alimne is free.</strong> No paid plan, subscription or credit card is required to use the Service.</li>
<li><strong>Free account:</strong> """ + rule_en + """ Creating an account is free, and the
Service stays free once you have one. The sample lecture, and opening, downloading or restoring study guides you
have already made, never need an account. The number of study guides that need no account may change.</li>
<li><strong>Fair use:</strong> to keep the Service available to everyone and to control costs, we apply daily limits
on how many study guides an account can generate, as well as limits per network and an overall daily
capacity. These limits may change at any
time, and at busy times you may be asked to wait in a queue or to try again later. We do not promise unlimited use.</li>
<li><strong>Existing subscribers:</strong> if you subscribed to a paid plan before Alimne became free, you can manage
or cancel your subscription at any time from within the app. Cancelling stops future charges and access
continues until the end of the period already paid. Payments for those subscriptions are processed by Stripe;
charges already made are non-refundable except where required by law.</li>
</ul>"""
        summary_ar = """
<div class="note" lang="ar" dir="rtl"><strong>باختصار:</strong> علّمني <strong>مجاني</strong> \u2014 لا حاجة لاشتراك
مدفوع ولا لبطاقة ائتمان. """ + rule_ar + """ إنشاء الحساب مجاني، ويبقى الاستخدام مجانيًا بعده.
تُطبَّق على الحسابات حدود <strong>استخدام عادل</strong> يومية قد تتغيّر،
وقد تنتظر دورك في أوقات الازدحام. ومن اشترك سابقًا في خطة مدفوعة يمكنه إدارة اشتراكه أو إلغاءه في أي وقت من داخل
التطبيق، وتُعالَج مدفوعاته عبر Stripe. النص الإنجليزي هو المرجع.</div>
"""
    else:
        evade = "the usage limits (for example with automated tools, or by rotating devices or networks)"
        plans = """<h2>2. Plans &amp; billing</h2>
<ul>
<li><strong>Free plan:</strong> 3 processing tokens per month. No credit card required.</li>
<li><strong>Pro plan:</strong> US$2.99 per month, billed via Stripe, including <strong>30 tokens per month</strong>
and priority processing. Your token allowance renews each billing cycle.</li>
<li>You can cancel anytime; access continues until the end of the paid period. Charges are non-refundable
except where required by law.</li>
</ul>"""
        summary_ar = ""
    body = """
<h1>Terms &amp; Conditions</h1>
<div class="updated">Last updated: 7 October 2026</div>
<p>By using Alimne (the "Service"), operated by souc ai, you agree to these terms.</p>
""" + summary_ar + """

<h2>1. The Service</h2>
<p>Alimne converts uploaded slides, documents, pasted text and YouTube videos into study guides,
summaries, flashcards and quizzes using AI. Output is generated automatically and may contain
inaccuracies \u2014 always verify important information against the source material.</p>

""" + plans + """

<h2>3. Acceptable use</h2>
<ul>
<li>Only upload content you have the right to use.</li>
<li>Do not use the Service for unlawful purposes or to process content that infringes others' rights.</li>
<li>Do not attempt to disrupt, overload, or reverse-engineer the Service.</li>
<li>Do not try to get around """ + evade + """.</li>
</ul>

<h2>4. Your content</h2>
<p>You retain all rights to the content you submit. As described in our
<a href="/privacy">Privacy Policy</a>, your content is processed in memory only and deleted within
15 minutes. You are responsible for keeping your own copies.</p>

<h2>5. Disclaimers &amp; liability</h2>
<p>The Service is provided "as is", without warranties of any kind. To the maximum extent permitted by
law, souc ai is not liable for any indirect or consequential damages, or for reliance on AI-generated
output. Third-party services (Stripe, Google, YouTube, etc.) are governed by their own terms.</p>

<h2>6. Changes &amp; governing law</h2>
<p>We may update these terms; continued use means acceptance. These terms are governed by the laws of
the United Arab Emirates (Dubai). Contact: <a href="mailto:sales@souc.ai">sales@souc.ai</a>.</p>
"""
    return _legal_shell("Terms & Conditions", body), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    if path and os.path.exists(os.path.join(DIST, path)):
        return send_from_directory(DIST, path)
    return send_from_directory(DIST, "index.html")


if __name__ == "__main__":
    print(f"  Model : {OLLAMA_MODEL}")
    print(f"  Ollama: {'running' if ollama_running() else 'NOT running — run: ollama serve'}")
    app.run(debug=False, host="127.0.0.1", port=5000, threaded=True)
