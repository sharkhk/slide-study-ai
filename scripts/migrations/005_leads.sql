-- ============================================================
-- 005 — Email leads (captured before the paywall)
-- Stores emails collected when a visitor hits the "free trial used" wall, so
-- non-converting visitors still become a marketing list. Written by the backend
-- with the service role (bypasses RLS); no public policies → anon cannot read.
-- Idempotent — safe to run multiple times.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.leads (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email      TEXT NOT NULL UNIQUE,
  source     TEXT,
  ip         TEXT,
  user_agent TEXT,
  converted  BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.leads ENABLE ROW LEVEL SECURITY;
-- No policies: only the service-role backend can read/write. anon/authenticated
-- keys get nothing.
