-- ============================================================
-- 006 — Free to activate (relaunch growth model)
-- Reverses the aggressive "1 try then pay" wall (004). For an early-stage
-- consumer study app, the growth loop is: generous free value -> the student
-- experiences the "aha" -> shares it -> word of mouth -> convert power users.
--
-- New model:
--   * Anonymous (no signup): 2 free previews  (set via ANON_FREE_LIMIT=2 in app)
--   * Sign up:               5 free guides     (this file: DEFAULT 5)
--   * Free plan monthly:     3 guides / month  (consume_token free reset -> 3)
--   * Pro:                   30 guides / month (consume_token active reset -> 30,
--                            aligning the monthly reset with the advertised 30
--                            and the amount granted on subscribe)
--
-- Self-contained + idempotent — safe to run multiple times. Run in the Supabase
-- SQL Editor.
-- ============================================================

-- Usage-tracking columns (from 003) — keep in case this runs on a fresh DB.
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS generations_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_used_at      TIMESTAMPTZ;

-- New accounts start with 5 free guides (was 0 under the hard paywall).
ALTER TABLE public.users ALTER COLUMN tokens_remaining SET DEFAULT 5;

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

  -- Monthly reset: active subscribers get 30; free users get a small 3/month
  -- recurring allowance (enough to keep the habit, not enough to cram an exam).
  IF v_user.tokens_month IS DISTINCT FROM v_current_month THEN
    IF v_user.subscription_status = 'active'
       AND (v_user.subscription_period_end IS NULL
            OR v_user.subscription_period_end > NOW()) THEN
      v_new_tokens := 30;
    ELSE
      v_new_tokens := 3;
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

-- Backfill: give existing non-subscribed accounts a fresh 5 free guides so they
-- can actually try the app (they were zeroed out under the old hard paywall).
UPDATE public.users
   SET tokens_remaining = 5
 WHERE subscription_status IS DISTINCT FROM 'active'
   AND COALESCE(tokens_remaining, 0) < 5;
