-- ============================================================
-- 012 — Refund a durable anonymous free preview
-- 009 made the anonymous free previews durable (public.anon_usage, keyed
-- 'dev:<device-id>') but added no way to give one back. The app refunds a
-- credit whenever a generation fails or the visitor disconnects mid-run; for
-- anonymous visitors that refund only touched the in-memory per-IP list, so
-- every failed attempt still burned one of the device's 2 lifetime previews.
--
-- anon_refund(p_key) decrements the counter by one (never below 0). A missing
-- row is a no-op. The backend tolerates this function not existing yet (it logs
-- a warning), so app.py can deploy before or after this migration.
--
-- Service-role only, like anon_consume / anon_remaining.
-- Idempotent — safe to run multiple times. Run in the Supabase SQL Editor.
-- ============================================================

CREATE OR REPLACE FUNCTION public.anon_refund(p_key TEXT)
RETURNS VOID
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  UPDATE public.anon_usage
     SET count = GREATEST(0, count - 1)
   WHERE key = p_key;
$$;

REVOKE ALL ON FUNCTION public.anon_refund(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.anon_refund(text) TO service_role;
