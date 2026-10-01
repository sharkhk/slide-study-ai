-- Atomic token increment / decrement (refunds, referral rewards).
-- Called by the backend via sb.rpc("add_tokens", {"p_user_id": "...", "p_delta": N}).
-- A read-modify-write in Python races with the atomic consume_token RPC and
-- loses concurrent decrements; this does the arithmetic inside one UPDATE.
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
