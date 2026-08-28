-- SECURITY FIX (critical): the token RPCs are SECURITY DEFINER and, by Supabase
-- default, EXECUTE is granted to PUBLIC (anon + authenticated). Anyone holding the
-- public anon key could call add_tokens/consume_token directly against PostgREST
-- and mint or drain tokens, bypassing the paywall. These functions are ONLY ever
-- called by the backend's service-role client, so restrict EXECUTE to service_role.
--
-- Also pin search_path on both SECURITY DEFINER functions so a caller-controlled
-- search_path can't shadow the unqualified functions they call (json_build_object,
-- to_char, now, greatest, coalesce).

-- 1) Pin search_path (defense against function-shadowing under SECURITY DEFINER).
ALTER FUNCTION public.add_tokens(uuid, int)  SET search_path = public, pg_temp;
ALTER FUNCTION public.consume_token(uuid)    SET search_path = public, pg_temp;

-- 2) Remove the default PUBLIC/anon/authenticated EXECUTE grants.
REVOKE ALL ON FUNCTION public.add_tokens(uuid, int) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.add_tokens(uuid, int) FROM anon;
REVOKE ALL ON FUNCTION public.add_tokens(uuid, int) FROM authenticated;

REVOKE ALL ON FUNCTION public.consume_token(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.consume_token(uuid) FROM anon;
REVOKE ALL ON FUNCTION public.consume_token(uuid) FROM authenticated;

-- 3) Grant EXECUTE to service_role only (the backend). service_role bypasses RLS
--    and is never exposed to clients.
GRANT EXECUTE ON FUNCTION public.add_tokens(uuid, int) TO service_role;
GRANT EXECUTE ON FUNCTION public.consume_token(uuid)   TO service_role;

-- Verify afterwards with:
--   SELECT proname, proacl FROM pg_proc
--   WHERE proname IN ('add_tokens','consume_token');
-- proacl should list only the owner and service_role, NOT anon/authenticated.
