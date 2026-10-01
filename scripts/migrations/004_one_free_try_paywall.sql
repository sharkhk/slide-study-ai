-- ============================================================
-- 004 — One free try, then subscribe
-- Free (non-subscribed) accounts no longer receive tokens: new accounts start
-- at 0 and the monthly reset grants free users 0. Combined with ANON_FREE_LIMIT=1
-- (one anonymous preview per device), a subscription is required to continue
-- after the single free try.
--
-- Self-contained: also (re)adds the usage-tracking columns + logic from 003, so
-- running just this file is enough. Idempotent — safe to run multiple times.
-- Run in the Supabase SQL Editor (or via scripts/apply_migration.py).
-- ============================================================

-- Usage-tracking columns (from 003).
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS generations_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_used_at      TIMESTAMPTZ;

-- New free accounts start with no tokens (must subscribe for access).
ALTER TABLE public.users ALTER COLUMN tokens_remaining SET DEFAULT 0;

CREATE OR REPLACE FUNCTION public.consume_token(p_user_id UUID)
RETURNS JSON
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_user          public.users%ROWTYPE;
  v_current_month TEXT;
  v_new_tokens    INT;
BEGIN
  v_current_month := TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM');

  SELECT * INTO v_user FROM public.users WHERE id = p_user_id FOR UPDATE;

  IF NOT FOUND THEN
    RETURN json_build_object('success', false, 'reason', 'user_not_found');
  END IF;

  -- Monthly reset: active subscribers get their allowance; free users get none.
  IF v_user.tokens_month IS DISTINCT FROM v_current_month THEN
    IF v_user.subscription_status = 'active'
       AND (v_user.subscription_period_end IS NULL
            OR v_user.subscription_period_end > NOW()) THEN
      v_new_tokens := 20;
    ELSE
      v_new_tokens := 0;   -- free accounts no longer get monthly tokens
    END IF;

    UPDATE public.users
       SET tokens_remaining = v_new_tokens,
           tokens_month     = v_current_month
     WHERE id = p_user_id;

    v_user.tokens_remaining := v_new_tokens;
  END IF;

  IF v_user.tokens_remaining <= 0 THEN
    RETURN json_build_object('success', false, 'reason', 'no_tokens',
                             'tokens_remaining', 0);
  END IF;

  -- Consume one token + record usage.
  UPDATE public.users
     SET tokens_remaining  = tokens_remaining - 1,
         generations_count = COALESCE(generations_count, 0) + 1,
         last_used_at      = NOW()
   WHERE id = p_user_id;

  RETURN json_build_object('success', true,
                           'tokens_remaining', v_user.tokens_remaining - 1);
END;
$$;

-- Re-apply the 002 lockdown (CREATE OR REPLACE resets grants/search_path).
ALTER FUNCTION public.consume_token(uuid) SET search_path = public, pg_temp;
REVOKE ALL ON FUNCTION public.consume_token(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.consume_token(uuid) TO service_role;
