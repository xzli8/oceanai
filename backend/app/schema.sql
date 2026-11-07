CREATE TABLE IF NOT EXISTS tenants (
  id        INTEGER PRIMARY KEY,
  name      TEXT NOT NULL UNIQUE,
  timezone  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admins (
  id     INTEGER PRIMARY KEY,
  email  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS admin_tenants (
  admin_id   INTEGER NOT NULL REFERENCES admins(id),
  tenant_id  INTEGER NOT NULL REFERENCES tenants(id),
  PRIMARY KEY (admin_id, tenant_id)
);

CREATE TABLE IF NOT EXISTS courses (
  id         INTEGER PRIMARY KEY,
  tenant_id  INTEGER NOT NULL REFERENCES tenants(id),
  title      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_courses_tenant ON courses(tenant_id);

CREATE TABLE IF NOT EXISTS learners (
  id         INTEGER PRIMARY KEY,
  tenant_id  INTEGER NOT NULL REFERENCES tenants(id),
  name       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_learners_tenant ON learners(tenant_id);

CREATE TABLE IF NOT EXISTS enrollments (
  id            INTEGER PRIMARY KEY,
  tenant_id     INTEGER NOT NULL REFERENCES tenants(id),
  learner_id    INTEGER NOT NULL REFERENCES learners(id),
  course_id     INTEGER NOT NULL REFERENCES courses(id),
  status        TEXT NOT NULL CHECK (status IN ('COMPLETED', 'INCOMPLETE')),
  completed_at  TEXT,
  UNIQUE (tenant_id, learner_id, course_id)
);
CREATE INDEX IF NOT EXISTS ix_enrollments_course ON enrollments(tenant_id, course_id);

CREATE TABLE IF NOT EXISTS certificates (
  id                 INTEGER PRIMARY KEY,
  tenant_id          INTEGER NOT NULL REFERENCES tenants(id),
  learner_id         INTEGER NOT NULL REFERENCES learners(id),
  course_id          INTEGER NOT NULL REFERENCES courses(id),
  serial             TEXT NOT NULL UNIQUE,
  learner_name       TEXT NOT NULL,
  course_title       TEXT NOT NULL,
  issued_at          TEXT NOT NULL,   -- UTC, ISO-8601 with Z
  issued_local_date  TEXT NOT NULL,   -- YYYY-MM-DD in tenant timezone
  status             TEXT NOT NULL CHECK (status IN ('ACTIVE', 'REVOKED')),
  revoked_at         TEXT,
  operation_id       INTEGER REFERENCES bulk_operations(id),
  UNIQUE (tenant_id, learner_id, course_id)
);
CREATE INDEX IF NOT EXISTS ix_cert_date    ON certificates(tenant_id, issued_local_date, issued_at, id);
CREATE INDEX IF NOT EXISTS ix_cert_learner ON certificates(tenant_id, learner_name, id);
CREATE INDEX IF NOT EXISTS ix_cert_course  ON certificates(tenant_id, course_title, id);
CREATE INDEX IF NOT EXISTS ix_cert_serial  ON certificates(tenant_id, serial);

CREATE TABLE IF NOT EXISTS bulk_operations (
  id               INTEGER PRIMARY KEY,
  tenant_id        INTEGER NOT NULL REFERENCES tenants(id),
  idempotency_key  TEXT NOT NULL,
  request_hash     TEXT NOT NULL,
  status           TEXT NOT NULL CHECK (status IN ('RUNNING', 'DONE', 'FAILED')),
  result_json      TEXT,
  created_by       INTEGER NOT NULL REFERENCES admins(id),
  created_at       TEXT NOT NULL,
  UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS audit_events (
  id              INTEGER PRIMARY KEY,
  tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
  actor_id        INTEGER NOT NULL REFERENCES admins(id),
  action          TEXT NOT NULL CHECK (action IN ('ISSUE', 'REVOKE')),
  certificate_id  INTEGER NOT NULL REFERENCES certificates(id),
  operation_id    INTEGER REFERENCES bulk_operations(id),
  created_at      TEXT NOT NULL,
  UNIQUE (certificate_id, action)
);
CREATE INDEX IF NOT EXISTS ix_audit_tenant ON audit_events(tenant_id, certificate_id);
