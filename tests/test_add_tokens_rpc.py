"""
Bug 2 (nightly debug run): DOUBLE REFUND in _add_tokens. On ANY add_tokens RPC
error it fell back to a manual read-modify-write — so an RPC that was applied
server-side but whose HTTP reply timed out (or hit a reset / gateway 5xx) was
applied a SECOND time. The fallback now runs only when PostgREST definitively says
the RPC does not exist (PGRST202 / 404 / "Could not find the function"); anything
else is logged and reported as failure (None) without a second update, and does
not switch the RPC off for the rest of the process.

EVERYTHING IS OFFLINE: Supabase is a fake object.
"""
from types import SimpleNamespace

import pytest

import app as appmod


# ── 2. _add_tokens never applies a credit twice ─────────────────────────────────
class _PgError(Exception):
    """Shaped like postgrest.exceptions.APIError (code / message / details / hint)."""
    def __init__(self, code=None, message=None, details=None, hint=None):
        super().__init__(message or "")
        self.code, self.message, self.details, self.hint = code, message, details, hint


class _FakeUsersTable:
    def __init__(self, sb):
        self.sb, self.op, self.payload = sb, None, None

    def select(self, *a, **k):
        self.op = "select"
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, *a, **k):
        return self

    def single(self):
        return self

    def execute(self):
        if self.op == "select":
            self.sb.selects += 1
            return SimpleNamespace(data={"tokens_remaining": self.sb.balance})
        self.sb.updates += 1
        self.sb.balance = self.payload["tokens_remaining"]
        return SimpleNamespace(data=[{"tokens_remaining": self.sb.balance}])


class _FakeSb:
    """A users row with a balance and an add_tokens RPC whose failure mode is set
    per test. 'apply_then_raise' applies the delta server-side and THEN raises —
    the reply was lost (timeout / reset / gateway 5xx) but the credit landed."""
    def __init__(self, balance=5, mode="ok", exc=None):
        self.balance, self.mode, self.exc = balance, mode, exc
        self.rpc_calls = self.updates = self.selects = 0

    def rpc(self, name, params):
        assert name == "add_tokens"
        sb = self

        class _Call:
            def execute(self_inner):
                sb.rpc_calls += 1
                if sb.mode == "missing":
                    raise sb.exc
                sb.balance += params["p_delta"]
                if sb.mode == "apply_then_raise":
                    raise sb.exc
                return SimpleNamespace(data=sb.balance)
        return _Call()

    def table(self, name):
        assert name == "users"
        return _FakeUsersTable(self)


@pytest.fixture
def rpc_on(monkeypatch):
    monkeypatch.setattr(appmod, "_add_tokens_rpc", True)


def _ambiguous_errors():
    errs = [
        TimeoutError("The read operation timed out"),
        ConnectionResetError(10054, "An existing connection was forcibly closed"),
        _PgError(code=504, message="JSON could not be generated", details="b'<html>504 Gateway Time-out</html>'"),
        _PgError(code="502", message="upstream connect error or disconnect/reset before headers"),
        _PgError(code="XX000", message="internal error"),
        _PgError(code=None, message=None),
    ]
    try:
        import httpx
        errs += [httpx.ReadTimeout("timed out"), httpx.RemoteProtocolError("Server disconnected")]
    except ImportError:   # pragma: no cover - httpx ships with supabase
        pass
    return errs


def test_add_tokens_rpc_success_applies_exactly_once(rpc_on):
    sb = _FakeSb(balance=5)
    assert appmod._add_tokens(sb, "user-1", 1) == 6
    assert sb.balance == 6 and sb.rpc_calls == 1 and sb.updates == 0
    assert appmod._add_tokens_rpc is True


@pytest.mark.parametrize("exc", _ambiguous_errors(), ids=lambda e: type(e).__name__ + ":" + str(getattr(e, "code", "")))
def test_add_tokens_ambiguous_rpc_error_never_double_applies(rpc_on, exc):
    sb = _FakeSb(balance=5, mode="apply_then_raise", exc=exc)
    res = appmod._add_tokens(sb, "user-1", 1)
    assert res is None                       # reported as NOT done (outcome unknown)…
    assert sb.balance == 6                   # …and the balance changed exactly once
    assert sb.updates == 0 and sb.selects == 0
    assert appmod._add_tokens_rpc is True    # a blip must not switch the RPC off for good


def test_refund_after_rpc_timeout_credits_once_and_is_not_reported_refunded(rpc_on, monkeypatch):
    sb = _FakeSb(balance=0, mode="apply_then_raise", exc=TimeoutError("timed out"))
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)
    ch = appmod._Charge(uid="user-1")
    assert ch.refund() is True
    assert ch.refunded is False              # never claim 'your credit was returned'
    assert sb.balance == 1                   # the RPC's own credit — no second one
    assert sb.updates == 0


def _missing_errors():
    errs = [
        _PgError(code="PGRST202", message="Could not find the function public.add_tokens(p_delta, p_user_id) in the schema cache",
                 hint="Perhaps you meant to call the function public.consume_token"),
        _PgError(code=404, message="JSON could not be generated", details="b'Not Found'"),
        _PgError(code=None, message="Could not find the public.add_tokens(p_delta, p_user_id) function or the "
                                    "public.add_tokens function with a single unnamed json or jsonb parameter in the schema cache"),
        _PgError(code="42883", message="function public.add_tokens(uuid, integer) does not exist"),
    ]
    try:
        from postgrest.exceptions import APIError
        errs.append(APIError({"code": "PGRST202", "message": "Could not find the function public.add_tokens(p_delta, p_user_id) in the schema cache",
                              "details": None, "hint": None}))
    except ImportError:   # pragma: no cover
        pass
    return errs


@pytest.mark.parametrize("exc", _missing_errors(), ids=lambda e: str(getattr(e, "code", "")))
def test_add_tokens_missing_rpc_falls_back_once_and_latches(rpc_on, exc):
    sb = _FakeSb(balance=5, mode="missing", exc=exc)
    assert appmod._add_tokens(sb, "user-1", 1) == 6
    assert sb.balance == 6 and sb.updates == 1
    assert appmod._add_tokens_rpc is False   # latched: later calls skip the missing RPC
    assert appmod._add_tokens(sb, "user-1", 2) == 8
    assert sb.rpc_calls == 1 and sb.updates == 2


def test_add_tokens_real_postgrest_gateway_error_is_ambiguous(rpc_on):
    APIError = pytest.importorskip("postgrest.exceptions").APIError
    exc = APIError({"message": "JSON could not be generated", "code": 502,
                    "hint": "Refer to full message for details", "details": "b'Bad Gateway'"})
    sb = _FakeSb(balance=5, mode="apply_then_raise", exc=exc)
    assert appmod._add_tokens(sb, "user-1", 1) is None
    assert sb.balance == 6 and sb.updates == 0 and appmod._add_tokens_rpc is True
