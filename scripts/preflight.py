#!/usr/bin/env python3
"""
Preflight for the Alimne (slide-study-ai) root app.py.

Fast, dependency-light guards that must pass before any Alimne update ships.
Runs entirely offline: it parses the source, it does NOT import the app or
touch Stripe / Supabase / Groq.

Checks:
  1. app.py parses (valid Python syntax via ast.parse).
  2. APP_URL has no onrender default — the canonical default must be
     https://alimne.app, never an *.onrender.com URL (guards the APP_URL drift
     that leaks Render's origin host into links, success/cancel URLs and CORS).
  3. Route-count sanity: app.py registers at least the expected number of
     @app.route endpoints, and the payment routes are present.
  4. Render Blueprint config: BOTH render.yaml and backend/render.yaml are
     checked so a future Blueprint re-sync is safe — no *.onrender.com APP_URL
     default and no deprecated llama-3.1-8b-instant Groq model in either file.

Exit code 0 = all checks pass. Non-zero = at least one check failed.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_PY = os.path.join(ROOT, "app.py")

# Render Blueprint configs that must stay drift-free so a future re-sync is safe.
RENDER_YAMLS = [
    os.path.join(ROOT, "render.yaml"),
    os.path.join(ROOT, "backend", "render.yaml"),
]
# Groq removed this model from free/dev tiers (Jun 2026); it must not linger in
# any Blueprint default or a re-sync would deploy a 404-ing model.
DEPRECATED_GROQ_MODEL = "llama-3.1-8b-instant"

# Minimum number of @app.route endpoints we expect to be wired up. A big drop
# usually means a decorator or a whole block was accidentally deleted.
MIN_ROUTES = 25
REQUIRED_ROUTES = {"/api/stripe/checkout", "/api/stripe/webhook", "/api/config"}


def fail(msg):
    print(f"PREFLIGHT FAIL: {msg}")
    sys.exit(1)


def _app_url_default(text):
    """Return the APP_URL 'value:' from a render.yaml body, or None."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        key = line.strip().lstrip("- ").strip()
        if key == "key: APP_URL" or key.replace(" ", "") == "key:APP_URL":
            for j in range(i + 1, min(i + 4, len(lines))):
                s = lines[j].strip()
                if s.startswith("value:"):
                    return s.split("value:", 1)[1].strip().strip('"').strip("'")
                if s.startswith("- key:"):
                    break
    return None


def check_render_yamls():
    """Guard both Blueprint configs against onrender APP_URL and the dead model."""
    for path in RENDER_YAMLS:
        rel = os.path.relpath(path, ROOT)
        if not os.path.exists(path):
            fail(f"render config not found: {rel}")
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()

        # (a) APP_URL default must not point at a Render origin host.
        app_url = _app_url_default(text)
        if app_url is None:
            fail(f"{rel}: no APP_URL default found")
        if "onrender" in app_url.lower():
            fail(f"{rel}: APP_URL default points at Render origin: {app_url!r}")

        # (b) the deprecated Groq model must not appear anywhere in the file.
        if DEPRECATED_GROQ_MODEL in text:
            fail(f"{rel}: deprecated Groq model {DEPRECATED_GROQ_MODEL!r} present")

        print(f"OK: {rel} APP_URL is {app_url!r}, no deprecated Groq model")


def main():
    if not os.path.exists(APP_PY):
        fail(f"app.py not found at {APP_PY}")

    with open(APP_PY, "r", encoding="utf-8") as fh:
        src = fh.read()

    # 1. Syntax check ---------------------------------------------------------
    try:
        tree = ast.parse(src, filename=APP_PY)
    except SyntaxError as exc:
        fail(f"app.py does not parse: {exc}")
    print("OK: app.py parses cleanly")

    # 2. APP_URL default must not be an onrender host ------------------------
    app_url_default = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "APP_URL" not in targets:
            continue
        call = node.value
        # Expect: os.environ.get("APP_URL", "<default>")
        if isinstance(call, ast.Call) and len(call.args) >= 2:
            default = call.args[1]
            if isinstance(default, ast.Constant) and isinstance(default.value, str):
                app_url_default = default.value

    if app_url_default is None:
        fail("could not find APP_URL default in app.py")
    if "onrender" in app_url_default.lower():
        fail(f"APP_URL default points at Render origin: {app_url_default!r}")
    print(f"OK: APP_URL default is {app_url_default!r} (no onrender)")

    # 3. Route-count sanity ---------------------------------------------------
    routes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            is_route = (
                isinstance(func, ast.Attribute)
                and func.attr == "route"
                and isinstance(func.value, ast.Name)
                and func.value.id == "app"
            )
            if is_route and dec.args and isinstance(dec.args[0], ast.Constant):
                routes.append(dec.args[0].value)

    n = len(routes)
    if n < MIN_ROUTES:
        fail(f"only {n} @app.route endpoints found (expected >= {MIN_ROUTES})")
    missing = REQUIRED_ROUTES - set(routes)
    if missing:
        fail(f"required routes missing: {sorted(missing)}")
    print(f"OK: {n} routes registered, payment routes present")

    # 4. Render Blueprint config drift ---------------------------------------
    check_render_yamls()

    print("PREFLIGHT PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
