"""Quick-start demo data. Idempotent: does nothing if tenants already exist (use --reset to rebuild)."""
import os
import sys

from .db import connect, db_path, init_schema, local_date, write_tx

A5_TS = "2026-01-10T13:30:00Z"

TENANTS = [
    ("East", "Australia/Sydney", "E"),
    ("West", "Australia/Perth", "W"),
]
ADMINS = {
    "alice@east.test": ["East"],
    "bob@west.test": ["West"],
    "carol@multi.test": ["East", "West"],  # many-to-many demo
}
# (learner, enrollment status, already certified at)
SAFETY_ENROLLMENTS = [
    ("Alex Lee", "COMPLETED", A5_TS),          # already certified (A4 duplicate, A5 date)
    ("Sam Park", "COMPLETED", None),            # eligible
    ("Taylor Wong", "COMPLETED", None),         # eligible
    ("Jordan Kim", "INCOMPLETE", None),         # skipped: incomplete
]


def seed(conn) -> bool:
    init_schema(conn)
    if conn.execute("SELECT 1 FROM tenants LIMIT 1").fetchone():
        return False
    with write_tx(conn):
        tenant_ids = {}
        for name, tz, prefix in TENANTS:
            tenant_ids[name] = conn.execute(
                "INSERT INTO tenants(name, timezone) VALUES (?, ?)", (name, tz)
            ).lastrowid
        admin_ids = {}
        for email, tenants in ADMINS.items():
            admin_ids[email] = conn.execute("INSERT INTO admins(email) VALUES (?)", (email,)).lastrowid
            for t in tenants:
                conn.execute(
                    "INSERT INTO admin_tenants(admin_id, tenant_id) VALUES (?, ?)",
                    (admin_ids[email], tenant_ids[t]),
                )
        primary_admin = {"East": admin_ids["alice@east.test"], "West": admin_ids["bob@west.test"]}

        for name, tz, prefix in TENANTS:
            tid = tenant_ids[name]
            safety = conn.execute(
                "INSERT INTO courses(tenant_id, title) VALUES (?, 'Safety 101')", (tid,)
            ).lastrowid
            conn.execute("INSERT INTO courses(tenant_id, title) VALUES (?, 'First Aid 201')", (tid,))
            for i, (learner, status, cert_ts) in enumerate(SAFETY_ENROLLMENTS, start=1):
                lid = conn.execute(
                    "INSERT INTO learners(tenant_id, name) VALUES (?, ?)", (tid, learner)
                ).lastrowid
                conn.execute(
                    "INSERT INTO enrollments(tenant_id, learner_id, course_id, status, completed_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (tid, lid, safety, status, "2026-01-05T00:00:00Z" if status == "COMPLETED" else None),
                )
                if cert_ts:
                    cid = conn.execute(
                        "INSERT INTO certificates(tenant_id, learner_id, course_id, serial, learner_name,"
                        " course_title, issued_at, issued_local_date, status)"
                        " VALUES (?, ?, ?, ?, ?, 'Safety 101', ?, ?, 'ACTIVE')",
                        (tid, lid, safety, f"{prefix}-SEED-{i:04d}", learner, cert_ts, local_date(cert_ts, tz)),
                    ).lastrowid
                    conn.execute(
                        "INSERT INTO audit_events(tenant_id, actor_id, action, certificate_id, created_at)"
                        " VALUES (?, ?, 'ISSUE', ?, ?)",
                        (tid, primary_admin[name], cid, cert_ts),
                    )
    return True


def main():
    if "--reset" in sys.argv:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(db_path() + suffix):
                os.remove(db_path() + suffix)
    os.makedirs(os.path.dirname(db_path()), exist_ok=True)
    conn = connect()
    print("seeded" if seed(conn) else "already seeded", db_path())


if __name__ == "__main__":
    main()
