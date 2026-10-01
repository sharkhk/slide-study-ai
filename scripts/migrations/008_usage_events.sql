-- ============================================================
-- 008 — Durable usage events (accurate admin activity)
-- The old "Used the app" count only reflected signed-in users' generations, and
-- the recent-visitors log is in-memory (wiped on every restart/redeploy). So
-- anonymous + demo generations — most of the real usage — were invisible.
--
-- This logs one row per generation (signed-in, anonymous, or demo), so the admin
-- shows real activity that survives restarts. Content is never stored — only that
-- a generation happened, its kind/source, and coarse geo (country/city).
--
-- No public RLS policies: only the service-role backend reads/writes it.
-- Idempotent — safe to run multiple times.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.usage_events (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  kind       TEXT NOT NULL,     -- 'user' | 'anon' | 'demo'
  source     TEXT,              -- 'file' | 'youtube' | 'text' | 'url' | 'demo'
  country    TEXT,
  city       TEXT,
  title      TEXT
);

CREATE INDEX IF NOT EXISTS usage_events_created_at_idx ON public.usage_events (created_at DESC);

ALTER TABLE public.usage_events ENABLE ROW LEVEL SECURITY;
-- No policies → only the service-role backend can read/write. anon/authenticated get nothing.
