"""Bulk issuance with idempotency.

Concurrency model: the whole operation (key claim, issuance, audit, result) runs inside one
BEGIN IMMEDIATE transaction. SQLite allows a single writer, so concurrent requests with the same
key are serialized: the second one waits for the write lock, then finds the committed DONE
operation and replays its stored result. A crash mid-operation rolls everything back, so a
half-executed operation is never visible.
"""
import hashlib
import json
import secrets
import sqlite3

from fastapi import HTTPException

from .db import local_date, utc_now_iso, write_tx
from .deps import TenantCtx


def request_hash(course_id: int) -> str:
    return hashlib.sha256(json.dumps({"course_id": course_id}, sort_keys=True).encode()).hexdigest()


def _new_serial(conn: sqlite3.Connection, tenant_id: int) -> str:
    prefix = conn.execute("SELECT substr(name, 1, 1) FROM tenants WHERE id = ?", (tenant_id,)).fetchone()[0]
    return f"{prefix.upper()}-{secrets.token_hex(5).upper()}"


def bulk_issue(conn: sqlite3.Connection, ctx: TenantCtx, idem_key: str, course_id: int) -> dict:
    req_hash = request_hash(course_id)
    with write_tx(conn):
        existing = conn.execute(
            "SELECT id, request_hash, status, result_json FROM bulk_operations"
            " WHERE tenant_id = ? AND idempotency_key = ?",
            (ctx.tenant_id, idem_key),
        ).fetchone()
        if existing:
            if existing["request_hash"] != req_hash:
                raise HTTPException(409, "Idempotency-Key was already used with a different request")
            return {**json.loads(existing["result_json"]), "replayed": True}

        course = conn.execute(
            "SELECT id, title FROM courses WHERE id = ? AND tenant_id = ?", (course_id, ctx.tenant_id)
        ).fetchone()
        if not course:
            raise HTTPException(404, "course not found")  # rollback: no operation, certs or audit

        now = utc_now_iso()
        op_id = conn.execute(
            "INSERT INTO bulk_operations(tenant_id, idempotency_key, request_hash, status, created_by, created_at)"
            " VALUES (?, ?, ?, 'RUNNING', ?, ?)",
            (ctx.tenant_id, idem_key, req_hash, ctx.actor.id, now),
        ).lastrowid

        rows = conn.execute(
            "SELECT e.learner_id, e.status AS enrollment_status, l.name AS learner_name,"
            "       c.id AS cert_id, c.status AS cert_status"
            " FROM enrollments e"
            " JOIN learners l ON l.id = e.learner_id AND l.tenant_id = e.tenant_id"
            " LEFT JOIN certificates c ON c.tenant_id = e.tenant_id"
            "      AND c.learner_id = e.learner_id AND c.course_id = e.course_id"
            " WHERE e.tenant_id = ? AND e.course_id = ?"
            " ORDER BY l.name, e.learner_id",
            (ctx.tenant_id, course_id),
        ).fetchall()

        results = []
        for r in rows:
            base = {"learner_id": r["learner_id"], "learner_name": r["learner_name"]}
            if r["enrollment_status"] != "COMPLETED":
                results.append({**base, "outcome": "skipped", "reason": "incomplete"})
                continue
            if r["cert_id"] is not None:
                results.append({**base, "outcome": "skipped", "reason": "already_certified",
                                "certificate_id": r["cert_id"], "certificate_status": r["cert_status"]})
                continue
            conn.execute("SAVEPOINT issue_one")
            try:
                cert_id = conn.execute(
                    "INSERT INTO certificates(tenant_id, learner_id, course_id, serial, learner_name, course_title,"
                    " issued_at, issued_local_date, status, operation_id)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)",
                    (ctx.tenant_id, r["learner_id"], course_id, _new_serial(conn, ctx.tenant_id),
                     r["learner_name"], course["title"], now, local_date(now, ctx.timezone), op_id),
                ).lastrowid
                conn.execute(
                    "INSERT INTO audit_events(tenant_id, actor_id, action, certificate_id, operation_id, created_at)"
                    " VALUES (?, ?, 'ISSUE', ?, ?, ?)",
                    (ctx.tenant_id, ctx.actor.id, cert_id, op_id, now),
                )
                conn.execute("RELEASE issue_one")
                results.append({**base, "outcome": "issued", "certificate_id": cert_id})
            except sqlite3.Error as e:
                conn.execute("ROLLBACK TO issue_one")
                conn.execute("RELEASE issue_one")
                results.append({**base, "outcome": "failed", "reason": type(e).__name__})

        summary = {k: sum(1 for x in results if x["outcome"] == k) for k in ("issued", "skipped", "failed")}
        result = {"operation_id": op_id, "course_id": course_id, "course_title": course["title"],
                  "status": "DONE", "summary": summary, "results": results}
        conn.execute(
            "UPDATE bulk_operations SET status = 'DONE', result_json = ? WHERE id = ?",
            (json.dumps(result), op_id),
        )
    return {**result, "replayed": False}
