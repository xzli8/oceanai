# Decision Log

All decisions below happened in a single Claude Code session.

| Field | Value |
|---|---|
| Session ID | `0c74d973-8a16-4c7b-bff7-5274b9753742` |
| Tool / model | Claude Code, `claude-opus-5-5` |
| Export file | `ai/sessions/0c74d973-8a16-4c7b-bff7-5274b9753742.jsonl` |

Timestamps are Asia/Shanghai (+08:00). Each entry gives the commit hashes, plus the conversation step ("turn") where the decision was made.

---

## D1 — Corrected: admins ↔ tenants changed from one-to-many to many-to-many, with a membership check on every request

**Type:** AI suggestion rejected / corrected

**What the AI proposed.** The first data model (planning turn, before any code) put `tenant_id` directly on the `admins` table, so each admin belonged to exactly one tenant.

**What I changed and why.** In a multi-tenant SaaS product, one admin often manages several tenants, and one tenant has several admins. Modelling that as one-to-many would have to be migrated later. I asked for three things:

- A join table, `admin_tenants`.
- A tenant list endpoint and a tenant switcher in the UI.
- A backend check, on every request, that the actor really belongs to the requested tenant. The client's word is not trusted.

All other resources stay isolated per tenant. I also asked for a demo admin who belongs to both tenants, `carol@multi.test`. The brief's required accounts are unchanged: `alice@east.test` belongs to East only and `bob@west.test` to West only.

**Result.**

| What | Where |
|---|---|
| Join table | `backend/app/schema.sql`, `admin_tenants` |
| Membership check, returns 404 to non-members | `backend/app/deps.py`, `get_tenant_ctx` |
| Tenant list endpoint | `GET /api/me/tenants` |
| Tenant switcher, remounts all tenant-scoped state on switch | `frontend/src/App.tsx` |

**Verification.**

- `test_actor_context_and_membership`: carol sees both tenants and bob sees only West. An unknown actor gets 401.
- `test_a1_tenant_isolation`: bob gets 404 on East through the list, detail, revoke, export and bulk-issue endpoints. Row counts are unchanged afterwards.
- Manual UI check: as carol, switched between East and West.

**Commits.** `2e4fcc5` (model in AGENTS.md), `2568457` (implementation), `3735bb1` (tests)

---

## D2 — Accepted: run the whole bulk-issue operation in one `BEGIN IMMEDIATE` transaction for idempotency

**Type:** AI suggestion accepted

**Proposal.** One SQLite write transaction covers the whole operation:

1. Claim the idempotency key (look it up; insert it if absent).
2. Issue certificates and write their audit events.
3. Store the result as `result_json`.

SQLite allows only one writer at a time. A concurrent request with the same key therefore waits on the lock, then reads the committed result and replays it. A crash rolls back everything, so a half-done operation is never visible. A key reused with a different payload returns 409.

**Alternative considered.** Insert a `RUNNING` row first, then have concurrent callers poll it. This needs extra handling for operations that crash halfway and leave a stuck `RUNNING` row. With SQLite it adds complexity and no benefit.

**Why I accepted.**

- Correctness does not depend on application-level locking.
- Database constraints act as a backstop: `UNIQUE(tenant_id, idempotency_key)`, `UNIQUE(tenant_id, learner_id, course_id)` on certificates, and `UNIQUE(certificate_id, action)` on audit events.
- It is simple enough to review within the time limit.

**Trade-off I accepted knowingly.** A bulk issue holds the write lock for its whole duration. Concurrent callers block, waiting up to `busy_timeout` = 30 s, instead of receiving a 202 and polling. The README lists this under known limitations, together with how I would change it on PostgreSQL (row-lock claim, batched processing).

**Verification.**

- `test_a2_retry_sequential_and_concurrent`: 8 concurrent plus 2 sequential requests with one key give one `operation_id` and identical results. Only one response has `replayed=false`. The database holds 2 new certificates and 2 ISSUE audit events.
- `test_a3_key_misuse_returns_409`: reusing a key with a different payload returns 409. No rows are written, and replaying the original request still returns the original result.
- I reviewed `bulk.py` against `db.write_tx` to confirm that `HTTPException` (404 / 409) triggers a ROLLBACK.

**Commits.** `2568457`, `3735bb1`

---

## D3 — Scope: add a read-only course list and course detail, scoped to the current tenant

**Type:** Scope / design trade-off

**Context.** The required scope (brief §3) lists certificate list, bulk issue, certificate detail and CSV export. The product description, however, starts with "Tenant admins **review course completions**". Without a course view, an admin issues certificates blind: they cannot see who has completed a course, who is incomplete, or who is already certified.

**Decision.** I proposed adding a course list and a course detail page showing enrollments. The AI agreed, but recommended keeping it narrow. I accepted these limits:

- **Read-only.** No create, edit or delete for courses or enrollments. The brief says not to add unrelated features.
- **Current tenant only.** The course list is not aggregated across an admin's tenants, so the A1 isolation model is unchanged.
- **Bulk issue moves into the course detail page,** so the admin sees eligibility before issuing.
- **Enrollments are paginated,** because the load-test course has 100k enrollments.

**Verification.**

- `test_course_summary_and_enrollments`: counts are correct before and after a bulk issue, and the new endpoints return 404 across tenants.
- Manual UI pass: course list → Safety 101 → bulk issue. The counts refreshed (Certified 3, Eligible 0) and the enrollment rows showed the new serials.

**Commit.** `f406f1c`

---

## D4 — Defects in AI-written code, caught by verification

**Type:** AI output corrected

These are real defects that appeared in this session, each caught by running something. None is invented for this log.

### 1. Test fixture leaked server processes

**How it was found.** While verifying D3 in the browser, the API returned the old `/api/courses` response without the new count fields.

**Root causes.**

- **Leaked servers.** An earlier test run had failed because of the environment's SOCKS proxy. The pytest fixture only caught `httpx.HTTPError` while waiting for the server to start, so the `ImportError` escaped and 9 uvicorn subprocesses were never terminated.
- **Stale backend.** The API launched by an earlier `start.sh` run was still listening on port 8000, so the new backend failed to bind (the log showed `address already in use`). `start.sh` carried on and started Vite anyway, so the UI silently talked to the old backend.

**Fix.**

- The fixture now uses `try/finally` and always terminates the server, killing it if needed.
- `start.sh` fails fast if port 8000 or 5173 is taken, or if the API does not become healthy.

**Verification.** After `./verify.sh`, `ps aux | grep uvicorn` shows 0 processes. A second `./start.sh` exits with "Port 8000 is already in use".

**Commit.** `f406f1c`

### 2. Tests could not reach the local server

**Symptom.** The first test run errored with `Using SOCKS proxy, but the 'socksio' package is not installed`.

**Cause.** The environment's proxy settings were applied to localhost calls.

**Fix.** `trust_env=False` on the test HTTP clients.

**Commit.** `3735bb1`

### 3. Unstable React context object

**Problem.** In `App`, `ctx` was rebuilt on every render. Every effect that depends on `ctx` (courses, certificate list) would have refetched on unrelated re-renders.

**How it was found.** Caught when reviewing the component after the first build.

**Fix.** Memoised it with `useMemo`.

**Commit.** `8244203`

---

## Other recorded choices (minor)

| Choice | Reason | Where |
|---|---|---|
| SQLite in WAL mode, not PostgreSQL | One-command startup with no Docker. WAL lets the export read while writes continue. | `db.py` |
| Revoked certificates are not re-issued (`already_certified`) | Keeps one certificate row per learner and course; confirmed with the AI during planning. | `bulk.py` |
| Idempotency keys scoped per tenant | Confirmed during planning | `schema.sql` |
| `issued_local_date` stored at issue time | Index-friendly sort and export. Assumes a tenant's timezone never changes; this assumption is documented. | `db.local_date` |
| Every sort ends with `id`; list and export share one query builder | Deterministic ordering for A6 | `certs.py` |
