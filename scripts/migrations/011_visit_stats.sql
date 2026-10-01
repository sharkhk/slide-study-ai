-- ============================================================
-- 011 — Durable, uncapped site-visit counter
-- The admin "N visits" badge was just the length of an in-memory rolling log
-- capped at 1000 and wiped on every restart. This stores a real per-day page-view
-- count in Supabase so the admin can show a true all-time total + today + week.
--
-- One row per UTC day; the app increments today's row on each real page view
-- (the app root or a shared /s/ guide — not API calls, assets, or admin).
-- No public RLS policies: only the service-role backend touches it.
-- Idempotent — safe to run multiple times.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.visit_stats (
  day    TEXT PRIMARY KEY,          -- 'YYYY-MM-DD' (UTC)
  count  INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE public.visit_stats ENABLE ROW LEVEL SECURITY;
-- No policies → only the service-role backend can read/write.

-- Atomic per-day increment (avoids a read-modify-write race on concurrent hits).
CREATE OR REPLACE FUNCTION public.bump_visit(p_day TEXT)
RETURNS VOID LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  INSERT INTO public.visit_stats(day, count) VALUES (p_day, 1)
  ON CONFLICT (day) DO UPDATE SET count = public.visit_stats.count + 1;
$$;

REVOKE ALL ON FUNCTION public.bump_visit(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bump_visit(text) TO service_role;
