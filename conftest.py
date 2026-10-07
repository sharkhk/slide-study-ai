import os
import sys

import pytest

# Make the repo root importable so `import app` works no matter where pytest is
# invoked from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Belt-and-braces: these tests MUST run offline. Never let a stray real key in the
# environment cause the suite to reach Stripe / Supabase / Groq. We blank the
# secrets before app.py is imported so no real client is ever constructed.
# The free-mode knobs are read once at import: clear them too, so the suite always
# runs against the code defaults (a developer's shell must not change the results).
for _var in (
    "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PRICE_ID",
    "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_JWT_SECRET",
    "GROQ_API_KEY", "RENDER", "PRODUCTION",
    "ALIMNE_FREE_MODE", "FAIR_DEVICE_DAILY", "FAIR_IP_DAILY", "FAIR_USER_DAILY",
    "FAIR_GLOBAL_DAILY", "GEN_MAX_CONCURRENT", "GEN_QUEUE_WAIT_S", "RATE_SUMMARIZE_PER_MIN",
    "FAIR_ANON_SHARE_PCT", "FAIR_CHAT_DAILY", "WEB_THREADS", "GEN_MAX_WAITING", "RATE_PRECHECK_PER_MIN",
    "ANON_FREE_USES", "ANON_USES_WINDOW_HOURS", "FAIR_ANON_IP_DAILY",
):
    os.environ.pop(_var, None)


@pytest.fixture(autouse=True)
def _free_mode_and_no_slot_leaks(monkeypatch):
    """Alimne is free by default: every test starts in free mode (a test of the
    old token system asks for `legacy_tokens`). And no test may end with a
    generation slot still taken or a request still 'waiting' for one: that would
    be the leak that slowly starves production of generation capacity."""
    import app as appmod
    monkeypatch.setattr(appmod, "FREE_MODE", True)
    appmod._demo_cache.clear()       # the cached sample guide must never leak from one test into the next
    real_sem = appmod._gen_sem       # a test that swaps in a tiny semaphore asserts on its own
    yield
    appmod._demo_cache.clear()
    assert real_sem._value == appmod._GEN_SLOTS, "a generation slot was never released"
    assert appmod._gen_waiting == [], "a request is still waiting for a generation slot"


@pytest.fixture
def legacy_tokens(monkeypatch):
    """Run a test against the OLD token system (ALIMNE_FREE_MODE=0). The file-level
    form is `pytestmark = pytest.mark.usefixtures("legacy_tokens")`."""
    import app as appmod
    monkeypatch.setattr(appmod, "FREE_MODE", False)
