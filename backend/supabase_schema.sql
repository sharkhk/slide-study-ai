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

  -- ── Consume one token ────────────────────────────────────────
  UPDATE public.users
     SET tokens_remaining = tokens_remaining - 1
   WHERE id = p_user_id;

  RETURN json_build_object(
    'success',          true,
    'tokens_remaining', v_user.tokens_remaining - 1
  );
END;
$$;
