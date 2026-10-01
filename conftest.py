import os
import sys

# Make the repo root importable so `import app` works no matter where pytest is
# invoked from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Belt-and-braces: these tests MUST run offline. Never let a stray real key in the
# environment cause the suite to reach Stripe / Supabase / Groq. We blank the
# secrets before app.py is imported so no real client is ever constructed.
for _var in (
    "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PRICE_ID",
    "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_JWT_SECRET",
    "GROQ_API_KEY", "RENDER", "PRODUCTION",
):
    os.environ.pop(_var, None)
