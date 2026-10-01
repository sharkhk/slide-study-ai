"""
Regression guard for the 2026-10-01 production incident (deploy 64d08e5, rolled
back in ffc0b3d).

app.py started a JWKS warm-up thread at import time. On Render's Python 3.14 that
thread's lazy `import jwt` raced the main thread's imports and left `jwt` half
initialised for the life of the process: every Bearer request crashed ("partially
initialized module 'jwt' has no attribute 'get_unverified_header'") or hung, and
Supabase never connected ("cannot import name 'get_algorithm_by_name'").

These tests import app.py in a FRESH interpreter, with production-shaped settings
(dummy, non-routable values; no network), and check that:
  - no background thread is started while the module is being imported,
  - jwt / supabase are imported at module level (no lazy import left to race),
  - the Supabase client is built during import, and
  - a garbage token is rejected cleanly (401 token_invalid), never a 500.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PROBE = r"""
import json, os, sys, threading
sys.path.insert(0, os.environ["APP_ROOT"])
os.chdir(os.environ["APP_ROOT"])
before = {t.name for t in threading.enumerate()}
import app as A
started = sorted({t.name for t in threading.enumerate()} - before)
c = A.app.test_client()
r = c.get("/api/auth/me", headers={"Authorization": "Bearer abc.def.ghi"})
print(json.dumps({
    "threads_started_at_import": started,
    "jwt_module_level": A._pyjwt is sys.modules.get("jwt"),
    "jwt_complete": hasattr(sys.modules["jwt"], "get_unverified_header"),
    "sb_client_built": A._sb_client is not None,
    "bad_token_status": r.status_code,
    "bad_token_code": (r.get_json(silent=True) or {}).get("code"),
}))
"""


def _run_probe():
    env = {k: v for k, v in os.environ.items()
           if k not in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "GROQ_API_KEY",
                        "SUPABASE_JWT_SECRET", "RENDER", "PRODUCTION")}
    env.update({
        "APP_ROOT": ROOT,
        # Production-shaped but harmless: .invalid never resolves, nothing is called
        # at import time, and the bad token fails before any JWKS fetch.
        "SUPABASE_URL": "https://example.invalid",
        "SUPABASE_SERVICE_ROLE_KEY": "dummy-service-role-key",
        "SUPABASE_ANON_KEY": "dummy-anon-key",
    })
    out = subprocess.run([sys.executable, "-c", _PROBE], env=env, capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_import_starts_no_threads_and_auth_rejects_cleanly():
    res = _run_probe()
    assert res["threads_started_at_import"] == [], res
    assert res["jwt_module_level"] is True
    assert res["jwt_complete"] is True
    assert res["sb_client_built"] is True
    assert res["bad_token_status"] == 401 and res["bad_token_code"] == "token_invalid", res


def test_no_lazy_jwt_or_supabase_imports_left():
    import re
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    # Only the module-level imports may exist; a function-local one can race again.
    jwt_imports = re.findall(r"^([ \t]*)import jwt\b", src, re.M)
    assert jwt_imports == [""], jwt_imports
    sb_imports = re.findall(r"^([ \t]*)from supabase import", src, re.M)
    # create_client + ClientOptions, each in a top-level try block (4-space indent)
    assert sb_imports == ["    ", "    "], sb_imports
    assert "from supabase import create_client as _sb_create_client" in src
