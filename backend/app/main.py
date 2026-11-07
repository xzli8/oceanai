import csv
import io
import sqlite3
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import bulk, certs
from .db import connect, local_datetime, utc_now_iso, write_tx
from .deps import Actor, TenantCtx, get_actor, get_conn, get_tenant_ctx

app = FastAPI(title="Certificate Admin Console")


def cert_out(row: sqlite3.Row, tz: str) -> dict:
    return {
        "id": row["id"],
        "serial": row["serial"],
        "learner_name": row["learner_name"],
        "course_title": row["course_title"],
        "issued_at": row["issued_at"],
        "issued_local": local_datetime(row["issued_at"], tz),
        "issued_local_date": row["issued_local_date"],
        "status": row["status"],
        "revoked_at": row["revoked_at"],
        "revoked_local": local_datetime(row["revoked_at"], tz) if row["revoked_at"] else None,
    }


# ---------- actor context ----------

@app.get("/api/actors")
def list_actors(conn: sqlite3.Connection = Depends(get_conn)):
    """Demo-only actor picker (no production auth by design)."""
    return [r["email"] for r in conn.execute("SELECT email FROM admins ORDER BY email")]


@app.get("/api/me/tenants")
def my_tenants(actor: Actor = Depends(get_actor), conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute(
        "SELECT t.id, t.name, t.timezone FROM tenants t JOIN admin_tenants at ON at.tenant_id = t.id"
        " WHERE at.admin_id = ? ORDER BY t.name",
        (actor.id,),
    ).fetchall()
    return {"actor": actor.email, "tenants": [dict(r) for r in rows]}


# ---------- courses ----------

@app.get("/api/courses")
def list_courses(ctx: TenantCtx = Depends(get_tenant_ctx), conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute(
        "SELECT c.id, c.title,"
        " (SELECT COUNT(*) FROM enrollments e WHERE e.course_id = c.id AND e.tenant_id = c.tenant_id) AS enrolled"
        " FROM courses c WHERE c.tenant_id = ? ORDER BY c.title, c.id",
        (ctx.tenant_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- certificates ----------

@app.get("/api/certificates")
def list_certificates(
    q: Optional[str] = None,
    sort: str = "issued_date",
    order: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: TenantCtx = Depends(get_tenant_ctx),
    conn: sqlite3.Connection = Depends(get_conn),
):
    where, params, order_by = certs.build_query(ctx.tenant_id, q, sort, order)
    total = conn.execute(f"SELECT COUNT(*) FROM certificates WHERE {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT {certs.COLUMNS} FROM certificates WHERE {where} ORDER BY {order_by} LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()
    return {"items": [cert_out(r, ctx.timezone) for r in rows], "total": total,
            "page": page, "page_size": page_size, "timezone": ctx.timezone}


@app.get("/api/certificates/export.csv")
def export_certificates(
    q: Optional[str] = None,
    sort: str = "issued_date",
    order: str = "desc",
    ctx: TenantCtx = Depends(get_tenant_ctx),
):
    where, params, order_by = certs.build_query(ctx.tenant_id, q, sort, order)
    sql = (f"SELECT learner_name, course_title, serial, issued_local_date FROM certificates"
           f" WHERE {where} ORDER BY {order_by}")

    def stream():
        # Own connection + one read transaction = consistent snapshot for the whole file.
        # WAL mode: this reader never blocks list requests or writers.
        conn = connect()
        try:
            conn.execute("BEGIN")
            cur = conn.execute(sql, params)
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["learner_name", "course_title", "serial_number", "issue_date"])
            while True:
                batch = cur.fetchmany(5000)
                if not batch:
                    break
                w.writerows(tuple(r) for r in batch)
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()
            yield buf.getvalue()
            conn.execute("COMMIT")
        finally:
            conn.close()

    return StreamingResponse(stream(), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="certificates.csv"'})


def _load_detail(conn: sqlite3.Connection, ctx: TenantCtx, cert_id: int) -> dict:
    row = conn.execute(
        f"SELECT {certs.COLUMNS} FROM certificates WHERE id = ? AND tenant_id = ?", (cert_id, ctx.tenant_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "certificate not found")
    audit = conn.execute(
        "SELECT a.action, a.created_at, a.operation_id, ad.email AS actor FROM audit_events a"
        " JOIN admins ad ON ad.id = a.actor_id WHERE a.certificate_id = ? AND a.tenant_id = ? ORDER BY a.id",
        (cert_id, ctx.tenant_id),
    ).fetchall()
    return {**cert_out(row, ctx.timezone),
            "audit": [{**dict(a), "created_local": local_datetime(a["created_at"], ctx.timezone)} for a in audit]}


@app.get("/api/certificates/{cert_id}")
def get_certificate(cert_id: int, ctx: TenantCtx = Depends(get_tenant_ctx),
                    conn: sqlite3.Connection = Depends(get_conn)):
    return _load_detail(conn, ctx, cert_id)


@app.post("/api/certificates/{cert_id}/revoke")
def revoke_certificate(cert_id: int, ctx: TenantCtx = Depends(get_tenant_ctx),
                       conn: sqlite3.Connection = Depends(get_conn)):
    now = utc_now_iso()
    with write_tx(conn):
        cur = conn.execute(
            "UPDATE certificates SET status = 'REVOKED', revoked_at = ?"
            " WHERE id = ? AND tenant_id = ? AND status = 'ACTIVE'",
            (now, cert_id, ctx.tenant_id),
        )
        changed = cur.rowcount == 1
        if changed:
            conn.execute(
                "INSERT INTO audit_events(tenant_id, actor_id, action, certificate_id, created_at)"
                " VALUES (?, ?, 'REVOKE', ?, ?)",
                (ctx.tenant_id, ctx.actor.id, cert_id, now),
            )
    detail = _load_detail(conn, ctx, cert_id)  # 404 if not in this tenant
    return {**detail, "changed": changed}


# ---------- bulk issue ----------

class BulkIssueIn(BaseModel):
    course_id: int


@app.post("/api/bulk-issues")
def create_bulk_issue(
    body: BulkIssueIn,
    idempotency_key: Optional[str] = Header(default=None),
    ctx: TenantCtx = Depends(get_tenant_ctx),
    conn: sqlite3.Connection = Depends(get_conn),
):
    if not idempotency_key or not idempotency_key.strip() or len(idempotency_key) > 200:
        raise HTTPException(400, "Idempotency-Key header is required (max 200 chars)")
    return bulk.bulk_issue(conn, ctx, idempotency_key.strip(), body.course_id)
