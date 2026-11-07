"""Acceptance scenarios A1-A7 from the brief, run against a real server over HTTP."""
import csv
import io
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from conftest import BACKEND

ALICE, BOB, CAROL = "alice@east.test", "bob@west.test", "carol@multi.test"


def counts(env):
    return {
        "certs": env.sql("SELECT COUNT(*) FROM certificates")[0][0],
        "audit": env.sql("SELECT COUNT(*) FROM audit_events")[0][0],
        "ops": env.sql("SELECT COUNT(*) FROM bulk_operations")[0][0],
    }


def bulk(c, course_id, key):
    return c.post("/api/bulk-issues", json={"course_id": course_id}, headers={"Idempotency-Key": key})


# ---------- actor / tenant context ----------

def test_actor_context_and_membership(env):
    east, west = env.tenant_id("East"), env.tenant_id("West")
    with env.client(CAROL) as c:
        names = [t["name"] for t in c.get("/api/me/tenants").json()["tenants"]]
        assert names == ["East", "West"]
    with env.client(BOB) as c:
        assert [t["name"] for t in c.get("/api/me/tenants").json()["tenants"]] == ["West"]
    with env.client(CAROL, east) as c:
        assert c.get("/api/certificates").status_code == 200
    with env.client(CAROL, west) as c:
        assert c.get("/api/certificates").status_code == 200
    with env.client("nobody@x.test", east) as c:
        assert c.get("/api/certificates").status_code == 401
    with env.client(None, east) as c:
        assert c.get("/api/certificates").status_code == 401


# ---------- A1 ----------

def test_a1_tenant_isolation(env):
    east, west = env.tenant_id("East"), env.tenant_id("West")
    east_cert = env.sql("SELECT id FROM certificates WHERE tenant_id = ?", (east,))[0][0]
    east_course = env.course_id("East", "Safety 101")
    before = counts(env)

    # Bob claims the East tenant: every endpoint is non-revealing 404
    with env.client(BOB, east) as c:
        assert c.get("/api/certificates").status_code == 404
        assert c.get(f"/api/certificates/{east_cert}").status_code == 404
        assert c.get("/api/certificates/export.csv").status_code == 404
        assert c.post(f"/api/certificates/{east_cert}/revoke").status_code == 404
        assert bulk(c, east_course, "a1-x").status_code == 404

    # Bob in his own tenant, referencing East resource ids
    with env.client(BOB, west) as c:
        items = c.get("/api/certificates").json()["items"]
        assert items and all(i["serial"].startswith("W-") for i in items)
        assert c.get(f"/api/certificates/{east_cert}").status_code == 404
        assert c.post(f"/api/certificates/{east_cert}/revoke").status_code == 404
        assert bulk(c, east_course, "a1-y").status_code == 404
        assert all(r[2].startswith("W-") for r in csv.reader(io.StringIO(c.get("/api/certificates/export.csv").text))
                   if r[0] != "learner_name")

    assert counts(env) == before  # no certificates, audit events or operations created
    assert env.sql("SELECT status FROM certificates WHERE id = ?", (east_cert,))[0][0] == "ACTIVE"


# ---------- A2 ----------

def test_a2_retry_sequential_and_concurrent(env):
    east = env.tenant_id("East")
    course = env.course_id("East", "Safety 101")

    def call(_):
        with env.client(ALICE, east) as c:
            return bulk(c, course, "a2-key")

    with ThreadPoolExecutor(8) as ex:
        responses = list(ex.map(call, range(8)))
    responses += [call(0), call(0)]  # sequential retries

    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    bodies = [r.json() for r in responses]
    assert len({b["operation_id"] for b in bodies}) == 1
    strip = lambda b: {k: v for k, v in b.items() if k != "replayed"}
    assert all(strip(b) == strip(bodies[0]) for b in bodies)
    assert sum(1 for b in bodies if not b["replayed"]) == 1
    assert bodies[0]["summary"] == {"issued": 2, "skipped": 2, "failed": 0}

    assert env.sql("SELECT COUNT(*) FROM bulk_operations")[0][0] == 1
    # each learner at most one certificate; each issuance exactly one audit event
    assert env.sql("SELECT MAX(n) FROM (SELECT COUNT(*) n FROM certificates GROUP BY tenant_id, learner_id, course_id)")[0][0] == 1
    issued = env.sql("SELECT COUNT(*) FROM certificates WHERE operation_id IS NOT NULL")[0][0]
    assert issued == 2
    assert env.sql("SELECT COUNT(*) FROM audit_events WHERE action='ISSUE' AND operation_id IS NOT NULL")[0][0] == 2


# ---------- A3 ----------

def test_a3_key_misuse_returns_409(env):
    east = env.tenant_id("East")
    safety, first_aid = env.course_id("East", "Safety 101"), env.course_id("East", "First Aid 201")
    with env.client(ALICE, east) as c:
        first = bulk(c, safety, "a3-key")
        assert first.status_code == 200
        before = counts(env)
        r = bulk(c, first_aid, "a3-key")
        assert r.status_code == 409
        r2 = c.post("/api/bulk-issues", json={"course_id": "not-a-number"}, headers={"Idempotency-Key": "a3-key"})
        assert r2.status_code in (409, 422)
        assert counts(env) == before
        replay = bulk(c, safety, "a3-key").json()  # original result not overwritten
        assert replay["operation_id"] == first.json()["operation_id"]
        assert replay["results"] == first.json()["results"]


# ---------- A4 ----------

def test_a4_learner_outcomes(env):
    east = env.tenant_id("East")
    with env.client(ALICE, east) as c:
        res = bulk(c, env.course_id("East", "Safety 101"), "a4").json()
    by_name = {r["learner_name"]: r for r in res["results"]}
    assert by_name["Alex Lee"]["outcome"] == "skipped" and by_name["Alex Lee"]["reason"] == "already_certified"
    assert by_name["Jordan Kim"]["outcome"] == "skipped" and by_name["Jordan Kim"]["reason"] == "incomplete"
    assert by_name["Sam Park"]["outcome"] == "issued"
    assert by_name["Taylor Wong"]["outcome"] == "issued"
    # incomplete learner has no certificate
    assert env.sql("SELECT COUNT(*) FROM certificates WHERE learner_name='Jordan Kim'")[0][0] == 0


# ---------- A5 ----------

def test_a5_tenant_local_dates(env):
    east, west = env.tenant_id("East"), env.tenant_id("West")
    for actor, tid, expected_dt, expected_date in [
        (ALICE, east, "2026-01-11 00:30", "2026-01-11"),
        (BOB, west, "2026-01-10 21:30", "2026-01-10"),
    ]:
        with env.client(actor, tid) as c:
            item = next(i for i in c.get("/api/certificates").json()["items"] if i["learner_name"] == "Alex Lee")
            assert item["issued_at"] == "2026-01-10T13:30:00Z"
            assert item["issued_local"] == expected_dt
            assert c.get(f"/api/certificates/{item['id']}").json()["issued_local"] == expected_dt
            rows = list(csv.reader(io.StringIO(c.get("/api/certificates/export.csv?q=Alex Lee").text)))
            assert rows[1] == ["Alex Lee", "Safety 101", item["serial"], expected_date]


def test_a5_sort_uses_local_date(env):
    """Two East certs on the same UTC date but different Sydney dates must sort by Sydney date."""
    east = env.tenant_id("East")
    with env.client(ALICE, east) as c:
        bulk(c, env.course_id("East", "Safety 101"), "a5-sort")  # issued today
        asc = [i["issued_local_date"] for i in c.get("/api/certificates?sort=issued_date&order=asc").json()["items"]]
        assert asc == sorted(asc) and asc[0] == "2026-01-11"


# ---------- A6 ----------

def test_a6_export_100k(env):
    subprocess.run([sys.executable, "-m", "app.gen_bulk", "--tenant", "East", "--count", "100000"],
                   cwd=BACKEND, env=env.proc_env, check=True, capture_output=True)
    east = env.tenant_id("East")
    q, sort = "Lee", "learner_name"

    # independent oracle: fetch matching rows and sort in Python by (learner_name, id)
    rows = env.sql("SELECT id, learner_name, course_title, serial, issued_local_date FROM certificates"
                   " WHERE tenant_id = ?", (east,))
    match = [r for r in rows if "lee" in r[1].lower() or r[3].lower().startswith("lee")]
    expected = [[r[1], r[2], r[3], r[4]] for r in sorted(match, key=lambda r: (r[1], r[0]))]
    assert len(expected) > 5000
    assert len({r[0] for r in expected}) < len(expected)  # equal sort-key values exist

    exports, list_status = [], []
    with env.client(ALICE, east) as c:
        for attempt in range(2):
            t0 = time.monotonic()
            chunks = []
            with c.stream("GET", "/api/certificates/export.csv", params={"q": q, "sort": sort, "order": "asc"}) as r:
                assert r.status_code == 200
                for i, chunk in enumerate(r.iter_text()):
                    chunks.append(chunk)
                    if attempt == 0 and i == 0:
                        # while the first export is still streaming, request the list
                        with env.client(ALICE, east) as c2:
                            lr = c2.get("/api/certificates", params={"q": q, "sort": sort})
                            list_status.append((lr.status_code, lr.json()["total"]))
            assert time.monotonic() - t0 < 60
            exports.append(list(csv.reader(io.StringIO("".join(chunks))))[1:])

    assert list_status == [(200, len(expected))]
    assert exports[0] == expected
    assert exports[1] == exports[0]

    # full unfiltered export, date sort desc, also stable and complete
    with env.client(ALICE, east) as c:
        t0 = time.monotonic()
        a = c.get("/api/certificates/export.csv", params={"sort": "issued_date", "order": "desc"}).text
        assert time.monotonic() - t0 < 60
        b = c.get("/api/certificates/export.csv", params={"sort": "issued_date", "order": "desc"}).text
    assert a == b and len(a.splitlines()) - 1 == len(rows)


# ---------- A7 ----------

def test_a7_revocation_audit(env):
    east = env.tenant_id("East")
    cert = env.sql("SELECT id FROM certificates WHERE tenant_id = ? AND status='ACTIVE'", (east,))[0][0]
    with env.client(ALICE, east) as c:
        r1 = c.post(f"/api/certificates/{cert}/revoke").json()
        r2 = c.post(f"/api/certificates/{cert}/revoke").json()
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(lambda _: env.client(ALICE, east).post(f"/api/certificates/{cert}/revoke"), range(4)))
    assert r1["changed"] is True and r1["status"] == "REVOKED"
    assert r2["changed"] is False and r2["status"] == "REVOKED"
    assert env.sql("SELECT COUNT(*) FROM audit_events WHERE certificate_id=? AND action='REVOKE'", (cert,))[0][0] == 1
    assert [a["action"] for a in r2["audit"]] == ["ISSUE", "REVOKE"]
