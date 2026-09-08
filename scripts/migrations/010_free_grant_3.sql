-- ============================================================
-- 010 — Reduce the free signup grant from 5 to 3
-- New free accounts now start with 3 guides (matching the 3/month free allowance
-- from 006, for a clean "3 free a month" story). Pro is unchanged (30/month).
-- Idempotent — safe to run multiple times.
-- ============================================================

-- New signups get 3 free guides.
ALTER TABLE public.users ALTER COLUMN tokens_remaining SET DEFAULT 3;

-- Bring existing NON-subscribed accounts down to 3 (only those currently above 3;
-- never touches active subscribers, and never raises anyone).
UPDATE public.users
   SET tokens_remaining = 3
 WHERE subscription_status IS DISTINCT FROM 'active'
   AND COALESCE(tokens_remaining, 0) > 3;
