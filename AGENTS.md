# AGENTS.md — Certificate Admin Console

Instructions for AI agents working in this repo. Read fully before changing code.

## Stack
- Backend: Python 3.11+, FastAPI, SQLite (WAL mode), plain `sqlite3` or SQLAlchemy Core (no ORM magic around transactions).
- Frontend: React + Vite + TypeScript.
- One command installs deps, seeds demo data, starts backend + frontend. A second command runs verification.

## Actor & tenant context (no production auth)
- No password login. Frontend "login" = pick an admin from a seeded list.
- Every API request carries `X-Actor: <admin email>` and (for tenant-scoped APIs) `X-Tenant-Id: <id>`.
- `GET /api/me/tenants` returns tenants the actor belongs to (via `admin_tenants`); UI lets the admin pick one.
- Backend MUST verify on every tenant-scoped request that `(admin_id, tenant_id)` exists in `admin_tenants`.
  Missing/unknown actor → 401. Not a member of tenant → 404 (non-revealing).
- Every query on tenant resources filters by `tenant_id` from the verified context, never from request body/path alone.
- A resource id belonging to another tenant → 404.

## Data model
```
tenants         id, name, timezone (IANA)
admins          id, email UNIQUE
admin_tenants   admin_id, tenant_id, PRIMARY KEY(admin_id, tenant_id)
courses         id, tenant_id, title
learners        id, tenant_id, name
enrollments     id, tenant_id, learner_id, course_id, status(COMPLETED|INCOMPLETE), completed_at
                UNIQUE(tenant_id, learner_id, course_id)
certificates    id, tenant_id, learner_id, course_id, serial UNIQUE,
                learner_name, course_title          -- denormalized for search/sort/export
                issued_at (UTC ISO), issued_local_date (YYYY-MM-DD in tenant tz, computed at issue)
                status(ACTIVE|REVOKED), revoked_at, operation_id
                UNIQUE(tenant_id, learner_id, course_id)
                INDEX(tenant_id, issued_local_date, id), (tenant_id, learner_name, id), (tenant_id, serial)
bulk_operations id, tenant_id, idempotency_key, request_hash, status(RUNNING|DONE|FAILED),
                result_json, created_by, created_at
                UNIQUE(tenant_id, idempotency_key)
audit_events    id, tenant_id, actor_id, action(ISSUE|REVOKE), certificate_id, operation_id, created_at
                UNIQUE(certificate_id, action)
```
All resources except `admins` / `admin_tenants` are tenant-isolated.

## Business rules
- Bulk issue (`POST /api/bulk-issues`, header `Idempotency-Key` required, body `{course_id}`):
  1. Insert `bulk_operations` row first (claim). On UNIQUE conflict:
     different `request_hash` → 409, no execution; same hash → wait until DONE, return stored `result_json`.
  2. Per learner outcome: `issued` | `skipped` (reason: `incomplete`, `not_enrolled`, `already_certified`) | `failed`.
  3. Certificate insert + ISSUE audit in the same transaction. Revoked certificates are NOT re-issued (`already_certified`).
  4. Course of another tenant → 404, no certificates, no audit, no operation side effects.
- Revoke: `UPDATE ... SET status='REVOKED' WHERE id=? AND tenant_id=? AND status='ACTIVE'`;
  write REVOKE audit only if rowcount == 1. Repeat returns current state, no new audit.
- Dates: display = `issued_at` converted to tenant tz (`YYYY-MM-DD HH:mm`). Sort & CSV use `issued_local_date`.
- List sort keys: `issued_date`, `learner_name`, `course_title`, `serial`; asc/desc; ALWAYS append `id` tie-breaker.
- Search: learner name (case-insensitive contains) OR serial.
- CSV export shares the exact filter/sort builder with the list. Stream with keyset batches; columns:
  learner name, course title, serial number, tenant-local issue date. Must not block list requests.

- Courses (read-only): `GET /api/courses` (with counts), `GET /api/courses/{id}`, `GET /api/courses/{id}/enrollments` (paginated).
  Courses are always scoped to the current tenant, never aggregated across an admin's tenants.
  The UI runs bulk issue from the course detail page.

## Acceptance (must stay green): A1–A7 from the brief
A1 tenant isolation · A2 idempotent retry (sequential + concurrent) · A3 key misuse → 409 ·
A4 learner outcomes · A5 Sydney/Perth local dates · A6 100k export < 60s, stable order, list works during export ·
A7 revoke idempotent audit.

## Demo data
- Tenants: East (Australia/Sydney), West (Australia/Perth).
- Admins: alice@east.test → East only; bob@west.test → West only;
  carol@multi.test → East AND West (demonstrates many-to-many + tenant switcher).
- Both tenants: course "Safety 101", learner "Alex Lee"; completed, incomplete, already-certified enrollments.
- One East and one West certificate at `2026-01-10T13:30:00Z` (A5).
- Separate script generates 100k East certificates (with equal sort-key values) without touching quick-start data.

## Out of scope
Real authentication, cloud deploy, notifications, unrelated features. Correctness before visual polish.

## Working rules
- Commit in small steps. Don't change the data model or rules above without updating this file.
- Verify with tests/scripts against A1–A7; report failures honestly.
