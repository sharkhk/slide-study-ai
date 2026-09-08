-- ============================================================
-- 009 — Anonymous free-tier hardening (durable per-device quota)
-- The anonymous free previews were tracked in memory (wiped on every restart/
-- deploy) and keyed only by IP (reset by switching network / VPN). This makes the
-- quota DURABLE and keyed by a persistent browser device id, so the same device
-- can't farm unlimited free previews by restarting the server or hopping IPs.
--
-- No login required — this only hardens the existing anonymous try. The backend
-- fails OPEN if this table/RPC is missing or errors, so a real visitor is never
-- blocked by a DB hiccup.
--
-- No public RLS policies: only the service-role backend touches it.
-- Idempotent — safe to run multiple times.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.anon_usage (
  key          TEXT PRIMARY KEY,          -- e.g. 'dev:<device-id>'
  count        INTEGER NOT NULL DEFAULT 0,
  window_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.anon_usage ENABLE ROW LEVEL SECURITY;
-- No policies → only the service-role backend can read/write.

-- Atomic check-and-consume: resets the window if it has elapsed, blocks at the
-- limit, otherwise increments. Returns {ok, remaining}.
CREATE OR REPLACE FUNCTION public.anon_consume(p_key TEXT, p_limit INT, p_window_hours INT)
RETURNS JSON LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE r public.anon_usage%ROWTYPE;
BEGIN
  INSERT INTO public.anon_usage(key) VALUES (p_key) ON CONFLICT (key) DO NOTHING;
  SELECT * INTO r FROM public.anon_usage WHERE key = p_key FOR UPDATE;
  IF r.window_start < NOW() - make_interval(hours => p_window_hours) THEN
    UPDATE public.anon_usage SET count = 0, window_start = NOW() WHERE key = p_key;
    r.count := 0;
  END IF;
  IF r.count >= p_limit THEN
    RETURN json_build_object('ok', false, 'remaining', 0);
  END IF;
  UPDATE public.anon_usage SET count = count + 1, last_at = NOW() WHERE key = p_key;
  RETURN json_build_object('ok', true, 'remaining', GREATEST(0, p_limit - (r.count + 1)));
END; $$;

-- Read remaining without consuming (for the free-preview badge).
CREATE OR REPLACE FUNCTION public.anon_remaining(p_key TEXT, p_limit INT, p_window_hours INT)
RETURNS INT LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE r public.anon_usage%ROWTYPE;
BEGIN
  SELECT * INTO r FROM public.anon_usage WHERE key = p_key;
  IF NOT FOUND THEN RETURN p_limit; END IF;
  IF r.window_start < NOW() - make_interval(hours => p_window_hours) THEN RETURN p_limit; END IF;
  RETURN GREATEST(0, p_limit - r.count);
END; $$;

REVOKE ALL ON FUNCTION public.anon_consume(text, int, int)   FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.anon_remaining(text, int, int) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.anon_consume(text, int, int)   TO service_role;
GRANT EXECUTE ON FUNCTION public.anon_remaining(text, int, int) TO service_role;
