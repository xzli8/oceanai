from dataclasses import dataclass
from typing import Iterator, Optional

import sqlite3
from fastapi import Depends, Header, HTTPException

from .db import connect


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@dataclass(frozen=True)
class Actor:
    id: int
    email: str


@dataclass(frozen=True)
class TenantCtx:
    actor: Actor
    tenant_id: int
    timezone: str


def get_actor(
    x_actor: Optional[str] = Header(default=None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Actor:
    if not x_actor:
        raise HTTPException(401, "missing X-Actor header")
    row = conn.execute("SELECT id, email FROM admins WHERE email = ?", (x_actor.strip().lower(),)).fetchone()
    if not row:
        raise HTTPException(401, "unknown actor")
    return Actor(row["id"], row["email"])


def get_tenant_ctx(
    actor: Actor = Depends(get_actor),
    x_tenant_id: Optional[str] = Header(default=None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> TenantCtx:
    """Membership is verified against admin_tenants on every request. Non-member -> 404 (non-revealing)."""
    if not x_tenant_id or not x_tenant_id.isdigit():
        raise HTTPException(400, "missing or invalid X-Tenant-Id header")
    row = conn.execute(
        "SELECT t.id, t.timezone FROM tenants t"
        " JOIN admin_tenants at ON at.tenant_id = t.id"
        " WHERE t.id = ? AND at.admin_id = ?",
        (int(x_tenant_id), actor.id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "tenant not found")
    return TenantCtx(actor, row["id"], row["timezone"])
