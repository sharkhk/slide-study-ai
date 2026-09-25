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

Exit code 0 = all checks pass. Non-zero = at least one check failed.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_PY = os.path.join(ROOT, "app.py")

# Minimum number of @app.route endpoints we expect to be wired up. A big drop
# usually means a decorator or a whole block was accidentally deleted.
MIN_ROUTES = 25
REQUIRED_ROUTES = {"/api/stripe/checkout", "/api/stripe/webhook", "/api/config"}


def fail(msg):
    print(f"PREFLIGHT FAIL: {msg}")
    sys.exit(1)


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

    print("PREFLIGHT PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
