# Certificate Admin Console

An internal admin console for a multi-tenant training platform. Tenant admins can review certificates, bulk-issue them to eligible learners, revoke them, and export them to CSV.

- **Backend:** Python 3.11+, FastAPI, SQLite in WAL mode (`backend/`)
- **Frontend:** React 18, Vite, TypeScript (`frontend/`)
- **Agent instructions:** data model, rules and acceptance checks are in `AGENTS.md`

## Quick start

Requires Python ≥ 3.11 and Node ≥ 18.

```bash
./start.sh            # installs deps, seeds the demo data if the DB is empty, starts the API and UI
./start.sh --reset    # rebuilds the DB from the quick-start dataset first
./verify.sh           # runs acceptance tests A1–A7, then type-checks and builds the frontend
```

- UI: http://127.0.0.1:5173
- API: http://127.0.0.1:8000. Interactive docs are at `/docs`.

`verify.sh` starts each test with its own temporary database and its own server, so your dev database is never touched.

## Actors and tenants

There is no production authentication, by design. The actor is identified by request headers:

| Header | Meaning |
|---|---|
| `X-Actor` | Admin email, for example `alice@east.test` |
| `X-Tenant-Id` | Tenant to act in. Get the ids from `GET /api/me/tenants`. |

Admins and tenants are many-to-many through the `admin_tenants` table. Every tenant-scoped request is checked against that table:

- An unknown actor gets **401**.
- An admin who is not a member of the tenant gets **404**. The response does not reveal whether the tenant exists.

| Admin | Tenants | Tenant ids in a fresh DB |
|---|---|---|
| alice@east.test | East (Australia/Sydney) | 1 |
| bob@west.test | West (Australia/Perth) | 2 |
| carol@multi.test | East and West. Shows the many-to-many link and the tenant switcher in the UI. | 1, 2 |

In the UI, pick an admin, then pick one of that admin's tenants. The workspace has two tabs:

- **Courses:** every course in the current tenant with completion and certificate counts. Open a course to see each enrollment (completed or incomplete, completion time, certificate) and to run **Bulk issue** for that course.
- **Certificates:** search, sort, paginate, export, and open a certificate to view its audit trail or revoke it.

### Demo data, per tenant

- **Courses:** `Safety 101` and `First Aid 201`.
- **Safety 101 enrollments:**

| Learner | Enrollment | Certificate before any bulk issue |
|---|---|---|
| Alex Lee | completed | Already certified at `2026-01-10T13:30:00Z` |
| Sam Park | completed | None (eligible) |
| Taylor Wong | completed | None (eligible) |
| Jordan Kim | incomplete | None |

### Generating 100,000 rows

```bash
cd backend && .venv/bin/python -m app.gen_bulk --tenant East --count 100000
```

This adds a new course, `Load Test NNN`, with its own learners and certificates. It does not modify the quick-start rows; `./start.sh --reset` removes the generated data.

Names come from a pool of 100 and dates from 30 days, so many rows share the same sort-key value. Generation takes about 6 seconds.

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/api/actors` | Demo actor picker |
| GET | `/api/me/tenants` | Tenants of the current `X-Actor` |
| GET | `/api/courses` | Courses in the tenant, with enrolled / completed / incomplete / certified / eligible counts |
| GET | `/api/courses/{id}` | One course with the same counts |
| GET | `/api/courses/{id}/enrollments?page=&page_size=` | Enrollments with completion time (tenant local) and certificate serial / status |
| GET | `/api/certificates?q=&sort=&order=&page=&page_size=` | `sort` is one of `issued_date`, `learner_name`, `course_title`, `serial` |
| GET | `/api/certificates/export.csv?q=&sort=&order=` | Same filter and order as the list. Streamed. |
| GET | `/api/certificates/{id}` | Detail plus audit trail |
| POST | `/api/certificates/{id}/revoke` | Idempotent. The response includes `changed`. |
| POST | `/api/bulk-issues` | Body `{"course_id": N}`. Requires an `Idempotency-Key` header. |

## Acceptance scenarios

Each scenario has an automated test in `backend/tests/test_acceptance.py`. Run them all with `./verify.sh`, or one at a time:

```bash
cd backend && .venv/bin/python -m pytest -v tests -k a2
```

For manual curl checks, start the app with `./start.sh --reset` and set `API=http://127.0.0.1:8000`.

### A1 — Tenant isolation (`test_a1_tenant_isolation`)

```bash
curl -i $API/api/certificates   -H 'X-Actor: bob@west.test' -H 'X-Tenant-Id: 1'   # 404
curl -i $API/api/certificates/1 -H 'X-Actor: bob@west.test' -H 'X-Tenant-Id: 2'   # 404 (cert 1 belongs to East)
curl -i -X POST $API/api/bulk-issues -H 'X-Actor: bob@west.test' -H 'X-Tenant-Id: 2' \
  -H 'Idempotency-Key: x' -H 'Content-Type: application/json' -d '{"course_id":1}'  # 404
```

The test also covers revoke and export. It checks that no certificates, audit events or operations are created.

### A2 — Retry safety (`test_a2_retry_sequential_and_concurrent`)

The test sends 8 concurrent requests and then 2 sequential ones, all with the same key. All of them return the same `operation_id` and the same results. Only one response has `replayed: false`. The database then holds 2 new certificates and 2 ISSUE audit events.

To try it by hand, send this command several times, including in parallel:

```bash
curl -X POST $API/api/bulk-issues -H 'X-Actor: alice@east.test' -H 'X-Tenant-Id: 1' \
  -H 'Idempotency-Key: demo-1' -H 'Content-Type: application/json' -d '{"course_id":1}'
```

### A3 — Key misuse (`test_a3_key_misuse_returns_409`)

Reuse the key `demo-1` with `{"course_id":2}`. The API returns **409**. No new rows are written, and replaying the original request still returns the original result.

### A4 — Learner outcomes (`test_a4_learner_outcomes`)

Bulk-issue East Safety 101. The result is:

| Learner | Outcome | Reason |
|---|---|---|
| Alex Lee | skipped | `already_certified` |
| Jordan Kim | skipped | `incomplete` |
| Sam Park | issued | |
| Taylor Wong | issued | |

### A5 — DST and local date (`test_a5_tenant_local_dates`, `test_a5_sort_uses_local_date`)

Alex Lee's seeded certificate was issued at `2026-01-10T13:30:00Z`.

| Tenant | Displayed time | CSV date |
|---|---|---|
| East | `2026-01-11 00:30` | `2026-01-11` |
| West | `2026-01-10 21:30` | `2026-01-10` |

Sorting by issue date uses `issued_local_date`, then `issued_at`, then `id`.

### A6 — Export growth (`test_a6_export_100k`)

The test does the following:

1. Generates 100k East certificates.
2. Exports with `q=Lee&sort=learner_name&order=asc` twice. While the first export is streaming, it requests the list and checks that the list returns 200.
3. Checks both exports against an independent oracle: the matching rows sorted in Python by `(learner_name, id)`. Both exports must match it and match each other byte for byte.
4. Exports the full 100k dataset twice and checks the results are identical.

Measured: the full 100k export takes about 0.6 seconds.

### A7 — Revocation audit (`test_a7_revocation_audit`)

- The first revoke returns `changed: true` and writes one REVOKE audit event.
- A second revoke, and 4 more concurrent repeats, return `changed: false` and write no audit events.

## Key design decisions

- **Idempotency:** The whole bulk operation runs in one `BEGIN IMMEDIATE` transaction: claiming the key, issuing certificates, writing audit events and storing the result. SQLite allows only one writer at a time, so concurrent requests with the same key queue up. Each one then reads the committed result. If the operation crashes, everything rolls back, so a half-finished operation is never visible. A key reused with a different `request_hash` gets 409. Keys are scoped per tenant.
- **No duplicates, enforced in the database:**
  - `UNIQUE(tenant_id, learner_id, course_id)` on certificates.
  - `UNIQUE(certificate_id, action)` on audit events.
  - Revoke is a conditional `UPDATE ... WHERE status='ACTIVE'`, and the audit event is written only when exactly one row changed.
- **Stable ordering:** Every sort ends with `id`. The list and the CSV export use the same query builder (`backend/app/certs.py`).
- **Export:** Streamed in batches of 5,000 rows from a single read transaction, so the file is a consistent snapshot. In WAL mode a reader does not block list requests or writers.
- **Local date:** `issued_local_date` is computed once, at issue time, from the tenant's timezone. Displayed times are converted from `issued_at` UTC on each request.
- **Revoked certificates are not re-issued.** They are skipped as `already_certified`.

## Known limitations and unfinished work

- **SQLite single writer.** A bulk issue holds the write lock for its whole duration. Concurrent writes, such as a revoke, wait up to 30 seconds via `busy_timeout`. That is fine at demo scale; on PostgreSQL I would claim the key with a row lock and process learners in batches.
- **Same-key callers wait synchronously.** A concurrent caller blocks until the first operation commits. There is no "202 + poll" flow.
- **Idempotency keys never expire.**
- **The list uses OFFSET pagination.** Very deep pages on 100k rows get slower. Export is not affected.
- **Contains-search scans the tenant's rows.** `LIKE '%q%'` cannot use an index. It is fast enough at 100k; a full-text index would be needed beyond that.
- **Serial collisions are not retried.** Serials are 10 random hex characters. A collision is reported as a `failed` outcome for that learner rather than retried.
- **UI export buffers the file in memory.** The UI downloads the CSV via `fetch` into a blob, about 5 MB at 100k rows, so that it can send the actor headers. The API itself streams.
- **No UI tests.** The UI was checked manually: actor and tenant switching, bulk issue, list, detail, revoke confirmation, and audit trail.
- **Running `gen_bulk` twice adds another 100k rows** under a new course.
- **Course counts are computed on every request.** That is fine at 100k enrollments; at larger scale they would be maintained incrementally.
- **Course and enrollment data is read-only.** It comes from the seed and generator only, by design (scope control).
