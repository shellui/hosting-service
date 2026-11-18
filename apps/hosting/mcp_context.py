"""Request-scoped MCP agent claims (revocation tenant checks)."""

from __future__ import annotations

from contextvars import ContextVar

_mcp_agent_claims: ContextVar[dict | None] = ContextVar('hosting_mcp_agent_claims', default=None)


def set_mcp_agent_claims(claims: dict | None):
    return _mcp_agent_claims.set(claims)


def reset_mcp_agent_claims(token) -> None:
    _mcp_agent_claims.reset(token)


def current_mcp_agent_claims() -> dict | None:
    return _mcp_agent_claims.get()
