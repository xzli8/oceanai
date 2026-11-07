"""Generate N certificates for one tenant (default: 100,000 for East) for export load testing (A6).

Adds a dedicated course and learners; never modifies the quick-start rows.
Names and dates come from small pools so many rows share equal sort-key values.
Usage: python -m app.gen_bulk [--tenant East] [--count 100000]
"""
import argparse
import random
from datetime import datetime, timedelta, timezone

from .db import connect, local_date, write_tx
from .seed import seed

FIRST = ["Alex", "Sam", "Taylor", "Jordan", "Morgan", "Casey", "Riley", "Jamie", "Avery", "Quinn"]
LAST = ["Lee", "Park", "Wong", "Kim", "Smith", "Nguyen", "Brown", "Chen", "Patel", "Garcia"]


def generate(tenant: str, count: int, seed_value: int = 42) -> None:
    conn = connect()
    seed(conn)
    t = conn.execute("SELECT id, name, timezone FROM tenants WHERE name = ?", (tenant,)).fetchone()
    if not t:
        raise SystemExit(f"tenant {tenant} not found")
    admin_id = conn.execute(
        "SELECT admin_id FROM admin_tenants WHERE tenant_id = ? ORDER BY admin_id LIMIT 1", (t["id"],)
    ).fetchone()[0]
    rnd = random.Random(seed_value)
    with write_tx(conn):
        batch_no = conn.execute("SELECT COUNT(*) FROM courses WHERE title LIKE 'Load Test %'").fetchone()[0] + 1
        title = f"Load Test {batch_no:03d}"
        course_id = conn.execute(
            "INSERT INTO courses(tenant_id, title) VALUES (?, ?)", (t["id"], title)
        ).lastrowid
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        learners, enrollments, certs = [], [], []
        first_learner = (conn.execute("SELECT COALESCE(MAX(id), 0) FROM learners").fetchone()[0]) + 1
        first_cert = (conn.execute("SELECT COALESCE(MAX(id), 0) FROM certificates").fetchone()[0]) + 1
        for i in range(count):
            lid = first_learner + i
            name = f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"  # 100 distinct names -> many ties
            # 30 days x 24 hourly slots -> many equal issue dates, and spans local-midnight boundaries
            ts = (base + timedelta(days=rnd.randrange(30), hours=rnd.randrange(24))).strftime("%Y-%m-%dT%H:%M:%SZ")
            learners.append((lid, t["id"], name))
            enrollments.append((t["id"], lid, course_id, "COMPLETED", ts))
            certs.append((first_cert + i, t["id"], lid, course_id,
                          f"{t['name'][0]}-L{batch_no:03d}-{i:06d}", name, title, ts,
                          local_date(ts, t["timezone"]), "ACTIVE"))
        conn.executemany("INSERT INTO learners(id, tenant_id, name) VALUES (?, ?, ?)", learners)
        conn.executemany("INSERT INTO enrollments(tenant_id, learner_id, course_id, status, completed_at)"
                         " VALUES (?, ?, ?, ?, ?)", enrollments)
        conn.executemany("INSERT INTO certificates(id, tenant_id, learner_id, course_id, serial, learner_name,"
                         " course_title, issued_at, issued_local_date, status)"
                         " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", certs)
        conn.executemany("INSERT INTO audit_events(tenant_id, actor_id, action, certificate_id, created_at)"
                         " VALUES (?, ?, 'ISSUE', ?, ?)",
                         [(t["id"], admin_id, c[0], c[7]) for c in certs])
    print(f"generated {count} certificates for {tenant} in course '{title}'")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="East")
    ap.add_argument("--count", type=int, default=100_000)
    args = ap.parse_args()
    generate(args.tenant, args.count)


if __name__ == "__main__":
    main()
