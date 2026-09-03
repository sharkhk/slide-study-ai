-- ============================================================
-- Slide Study AI — Supabase Schema
-- Run this entire file in your Supabase SQL Editor once.
-- ============================================================

-- ── Users table ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.users (
  id                      UUID REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
  email                   TEXT NOT NULL,
  name                    TEXT,
  avatar_url              TEXT,
  created_at              TIMESTAMPTZ DEFAULT NOW(),

  -- Stripe
  stripe_customer_id      TEXT UNIQUE,
  subscription_id         TEXT,
  subscription_status     TEXT DEFAULT 'free',      -- 'free' | 'active' | 'canceled' | 'past_due'
  subscription_period_end TIMESTAMPTZ,

  -- Tokens
  tokens_remaining        INTEGER DEFAULT 3,
  tokens_month            TEXT DEFAULT TO_CHAR(NOW(), 'YYYY-MM')
);

-- Row-level security: users can only read their own row.
-- Backend uses the service role key and bypasses RLS entirely.
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users read own profile"
  ON public.users FOR SELECT
  USING (auth.uid() = id);

-- ── Auto-create profile on first Google sign-in ───────────────
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
BEGIN
  INSERT INTO public.users (id, email, name, avatar_url)
  VALUES (
    NEW.id,
    NEW.email,
    NEW.raw_user_meta_data->>'full_name',
    NEW.raw_user_meta_data->>'avatar_url'
  )
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user();

-- ── Referral system columns ──────────────────────────────────────
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS referral_code TEXT UNIQUE,
  ADD COLUMN IF NOT EXISTS referred_by   UUID REFERENCES public.users(id),
  ADD COLUMN IF NOT EXISTS referral_paid BOOLEAN DEFAULT false;

-- ── Usage tracking columns (see migration 003) ───────────────────
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS generations_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_used_at      TIMESTAMPTZ;

-- ── Atomic token consumption (avoids race conditions) ─────────
-- Called by backend via sb.rpc("consume_token", {"p_user_id": "..."})
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

  -- Lock the row for this transaction
  SELECT * INTO v_user FROM public.users WHERE id = p_user_id FOR UPDATE;

  IF NOT FOUND THEN
    RETURN json_build_object('success', false, 'reason', 'user_not_found');
  END IF;

  -- ── Monthly reset ────────────────────────────────────────────
  IF v_user.tokens_month IS DISTINCT FROM v_current_month THEN
    IF v_user.subscription_status = 'active'
       AND (v_user.subscription_period_end IS NULL
            OR v_user.subscription_period_end > NOW()) THEN
      v_new_tokens := 20;
    ELSE
      v_new_tokens := 3;
    END IF;

    UPDATE public.users
       SET tokens_remaining = v_new_tokens,
           tokens_month     = v_current_month
     WHERE id = p_user_id;

    v_user.tokens_remaining := v_new_tokens;
  END IF;

  -- ── Check balance ────────────────────────────────────────────
  IF v_user.tokens_remaining <= 0 THEN
    RETURN json_build_object('success', false, 'reason', 'no_tokens',
                             'tokens_remaining', 0);
  END IF;

  -- ── Consume one token + record usage ─────────────────────────
  UPDATE public.users
     SET tokens_remaining  = tokens_remaining - 1,
         generations_count = COALESCE(generations_count, 0) + 1,
         last_used_at      = NOW()
   WHERE id = p_user_id;

  RETURN json_build_object(
    'success',          true,
    'tokens_remaining', v_user.tokens_remaining - 1
  );
END;
$$;

-- ── Atomic token increment / decrement (refunds, referral rewards) ─────────
-- Called by backend via sb.rpc("add_tokens", {"p_user_id": "...", "p_delta": N})
-- A read-modify-write in Python would race with consume_token and lose
-- concurrent decrements; this does the arithmetic inside a single UPDATE.
CREATE OR REPLACE FUNCTION public.add_tokens(p_user_id UUID, p_delta INT)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_new INT;
BEGIN
  UPDATE public.users
     SET tokens_remaining = GREATEST(0, COALESCE(tokens_remaining, 0) + p_delta)
   WHERE id = p_user_id
   RETURNING tokens_remaining INTO v_new;
  RETURN v_new;  -- NULL when the user row does not exist
END;
$$;

-- ── Lock down the token RPCs (SECURITY) ────────────────────────────────────
-- These SECURITY DEFINER functions are ONLY called by the backend's service-role
-- client. Supabase grants EXECUTE to PUBLIC (anon + authenticated) by default,
-- which would let anyone with the public anon key mint/drain tokens via PostgREST.
-- Pin search_path (anti function-shadowing) and restrict EXECUTE to service_role.
ALTER FUNCTION public.add_tokens(uuid, int) SET search_path = public, pg_temp;
ALTER FUNCTION public.consume_token(uuid)   SET search_path = public, pg_temp;

REVOKE ALL ON FUNCTION public.add_tokens(uuid, int) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.consume_token(uuid)   FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.add_tokens(uuid, int) TO service_role;
GRANT EXECUTE ON FUNCTION public.consume_token(uuid)   TO service_role;
