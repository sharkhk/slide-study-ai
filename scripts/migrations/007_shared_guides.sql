-- ============================================================
-- 007 — Shareable public study guides
-- A guide is ephemeral by default (in-memory, wiped on the job TTL). ONLY when a
-- user explicitly clicks "Share" is that one guide's *content* (never the source
-- file) persisted here and given a public /s/<slug> page — a viral + SEO surface.
--
-- No public RLS policies: the /s/<slug> page is rendered server-side with the
-- service role, so the anon/public key never touches this table.
-- Idempotent — safe to run multiple times.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.shared_guides (
  slug        TEXT PRIMARY KEY,
  guide       JSONB NOT NULL,              -- generated guide content only (no file/slides)
  title       TEXT,
  language    TEXT DEFAULT 'en',
  created_by  UUID REFERENCES public.users(id) ON DELETE SET NULL,
  views       INTEGER NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS shared_guides_created_at_idx ON public.shared_guides (created_at DESC);

ALTER TABLE public.shared_guides ENABLE ROW LEVEL SECURITY;
-- No policies → only the service-role backend can read/write. anon/authenticated get nothing.

-- Atomic view counter (avoids a read-modify-write race on popular guides).
CREATE OR REPLACE FUNCTION public.bump_shared_views(p_slug TEXT)
RETURNS VOID LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  UPDATE public.shared_guides SET views = views + 1 WHERE slug = p_slug;
$$;

REVOKE ALL ON FUNCTION public.bump_shared_views(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bump_shared_views(text) TO service_role;
