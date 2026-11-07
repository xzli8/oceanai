import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  ApiError,
  type BulkResult,
  type CertificateDetail,
  type CertPage,
  type Course,
  type Ctx,
  type EnrollmentPage,
  type ListParams,
  type Tenant,
} from "./api";

const errText = (e: unknown) => (e instanceof ApiError ? `${e.status}: ${e.message}` : String(e));

export default function App() {
  const [actors, setActors] = useState<string[]>([]);
  const [actor, setActor] = useState("");
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenantId, setTenantId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.actors().then(setActors).catch((e) => setError(errText(e)));
  }, []);

  useEffect(() => {
    setTenants([]);
    setTenantId(null);
    if (!actor) return;
    let stale = false;
    api
      .myTenants(actor)
      .then((r) => {
        if (stale) return;
        setTenants(r.tenants);
        if (r.tenants.length === 1) setTenantId(r.tenants[0].id);
      })
      .catch((e) => !stale && setError(errText(e)));
    return () => {
      stale = true;
    };
  }, [actor]);

  const tenant = tenants.find((t) => t.id === tenantId);
  // stable identity so tenant-scoped effects only re-run when the context really changes
  const ctx = useMemo<Ctx | null>(() => (actor && tenantId != null ? { actor, tenantId } : null), [actor, tenantId]);

  return (
    <div className="app">
      <header>
        <h1>Certificate Admin</h1>
        <div className="context">
          <label>
            Acting as{" "}
            <select value={actor} onChange={(e) => setActor(e.target.value)}>
              <option value="">Select admin…</option>
              {actors.map((a) => (
                <option key={a}>{a}</option>
              ))}
            </select>
          </label>
          {actor && (
            <label>
              Tenant{" "}
              <select
                value={tenantId ?? ""}
                onChange={(e) => setTenantId(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">Select tenant…</option>
                {tenants.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.timezone})
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </header>
      {error && <div className="banner error">{error}</div>}
      {!ctx && <p className="hint">Choose an admin and one of their tenants to continue.</p>}
      {/* key forces a full reset of tenant-scoped state when switching actor/tenant */}
      {ctx && tenant && <TenantWorkspace key={`${actor}:${tenantId}`} ctx={ctx} tenant={tenant} />}
    </div>
  );
}

function TenantWorkspace({ ctx, tenant }: { ctx: Ctx; tenant: Tenant }) {
  const [tab, setTab] = useState<"courses" | "certificates">("courses");
  const [courseId, setCourseId] = useState<number | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [openId, setOpenId] = useState<number | null>(null);
  const bump = () => setRefresh((n) => n + 1);
  return (
    <main>
      <nav className="tabs">
        <button className={tab === "courses" ? "active" : ""} onClick={() => setTab("courses")}>
          Courses
        </button>
        <button className={tab === "certificates" ? "active" : ""} onClick={() => setTab("certificates")}>
          Certificates
        </button>
      </nav>
      {tab === "courses" &&
        (courseId == null ? (
          <CourseList ctx={ctx} tenant={tenant} refresh={refresh} onOpen={setCourseId} />
        ) : (
          <CourseDetail
            key={courseId}
            ctx={ctx}
            courseId={courseId}
            refresh={refresh}
            onBack={() => setCourseId(null)}
            onChanged={bump}
            onOpenCert={setOpenId}
          />
        ))}
      {tab === "certificates" && (
        <CertificateList ctx={ctx} tenant={tenant} refresh={refresh} onOpen={setOpenId} />
      )}
      {openId != null && (
        <DetailPanel ctx={ctx} id={openId} onClose={() => setOpenId(null)} onChanged={bump} />
      )}
    </main>
  );
}

// ---------------- courses ----------------

function CourseList({
  ctx,
  tenant,
  refresh,
  onOpen,
}: {
  ctx: Ctx;
  tenant: Tenant;
  refresh: number;
  onOpen: (id: number) => void;
}) {
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let stale = false;
    setError(null);
    api
      .courses(ctx)
      .then((c) => !stale && setCourses(c))
      .catch((e) => !stale && setError(errText(e)));
    return () => {
      stale = true;
    };
  }, [ctx, refresh, retry]);

  return (
    <section className="card">
      <h2>Courses — {tenant.name}</h2>
      {error ? (
        <div className="banner error">
          Failed to load courses — {error} <button onClick={() => setRetry((n) => n + 1)}>Retry</button>
        </div>
      ) : !courses ? (
        <p className="muted">Loading…</p>
      ) : courses.length === 0 ? (
        <p className="empty">No courses in this tenant.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Course</th>
              <th>Enrolled</th>
              <th>Completed</th>
              <th>Incomplete</th>
              <th>Certified</th>
              <th>Eligible to issue</th>
            </tr>
          </thead>
          <tbody>
            {courses.map((c) => (
              <tr key={c.id} className="clickable" onClick={() => onOpen(c.id)}>
                <td>{c.title}</td>
                <td>{c.enrolled.toLocaleString()}</td>
                <td>{c.completed.toLocaleString()}</td>
                <td>{c.incomplete.toLocaleString()}</td>
                <td>
                  {c.certified_active.toLocaleString()}
                  {c.certified_revoked > 0 && <span className="muted"> (+{c.certified_revoked} revoked)</span>}
                </td>
                <td>{c.eligible > 0 ? <b>{c.eligible.toLocaleString()}</b> : 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function CourseDetail({
  ctx,
  courseId,
  refresh,
  onBack,
  onChanged,
  onOpenCert,
}: {
  ctx: Ctx;
  courseId: number;
  refresh: number;
  onBack: () => void;
  onChanged: () => void;
  onOpenCert: (id: number) => void;
}) {
  const [course, setCourse] = useState<Course | null>(null);
  const [data, setData] = useState<EnrollmentPage | null>(null);
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const ac = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all([api.course(ctx, courseId), api.enrollments(ctx, courseId, page, pageSize, ac.signal)])
      .then(([c, e]) => {
        if (ac.signal.aborted) return;
        setCourse(c);
        setData(e);
      })
      .catch((e) => !ac.signal.aborted && setError(errText(e)))
      .finally(() => !ac.signal.aborted && setLoading(false));
    return () => ac.abort();
  }, [ctx, courseId, page, refresh, retry]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;

  return (
    <>
      <section className="card">
        <div className="row space">
          <h2>{course ? course.title : "Course"}</h2>
          <button onClick={onBack}>← All courses</button>
        </div>
        {course && (
          <div className="stats">
            <span>Enrolled <b>{course.enrolled}</b></span>
            <span>Completed <b>{course.completed}</b></span>
            <span>Incomplete <b>{course.incomplete}</b></span>
            <span>Certified <b>{course.certified_active}</b></span>
            {course.certified_revoked > 0 && <span>Revoked <b>{course.certified_revoked}</b></span>}
            <span>Eligible <b>{course.eligible}</b></span>
          </div>
        )}
      </section>

      {course && <BulkIssuePanel ctx={ctx} course={course} onDone={onChanged} />}

      <section className="card">
        <h2>Enrollments</h2>
        {error ? (
          <div className="banner error">
            Failed to load enrollments — {error} <button onClick={() => setRetry((n) => n + 1)}>Retry</button>
          </div>
        ) : !data ? (
          <p className="muted">Loading…</p>
        ) : data.items.length === 0 ? (
          <p className="empty">No learners enrolled in this course.</p>
        ) : (
          <div className={loading ? "loading" : ""}>
            <table>
              <thead>
                <tr>
                  <th>Learner</th>
                  <th>Enrollment</th>
                  <th>Completed at</th>
                  <th>Certificate</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((e) => (
                  <tr key={e.id}>
                    <td>{e.learner_name}</td>
                    <td>
                      <span className={`badge ${e.status === "COMPLETED" ? "active" : "pending"}`}>{e.status}</span>
                    </td>
                    <td>{e.completed_local ?? "—"}</td>
                    <td>
                      {e.certificate_id ? (
                        <button className="link" onClick={() => onOpenCert(e.certificate_id!)}>
                          <span className="mono">{e.serial}</span>{" "}
                          <span className={`badge ${e.certificate_status!.toLowerCase()}`}>{e.certificate_status}</span>
                        </button>
                      ) : e.status === "COMPLETED" ? (
                        <span className="outcome skipped">Not issued — eligible</span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="row pager">
              <button disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)}>
                Prev
              </button>
              <span>
                Page {page} / {totalPages} · {data.total.toLocaleString()} enrolled
              </span>
              <button disabled={page >= totalPages || loading} onClick={() => setPage((p) => p + 1)}>
                Next
              </button>
            </div>
          </div>
        )}
      </section>
    </>
  );
}

// ---------------- bulk issue ----------------

function BulkIssuePanel({ ctx, course, onDone }: { ctx: Ctx; course: Course; onDone: () => void }) {
  const [status, setStatus] = useState<"idle" | "running" | "done" | "error">("idle");
  const [result, setResult] = useState<BulkResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  // One key per intended operation: reused on retry after an error, rotated after success.
  // The panel is remounted per course (CourseDetail key), so a key never spans two courses.
  const keyRef = useRef<string>(crypto.randomUUID());
  const inFlight = useRef(false);

  const submit = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setStatus("running");
    setError(null);
    try {
      const r = await api.bulkIssue(ctx, course.id, keyRef.current);
      setResult(r);
      setStatus("done");
      keyRef.current = crypto.randomUUID();
      onDone();
    } catch (e) {
      setError(errText(e));
      setStatus("error"); // keep the same key so a retry is the same logical operation
    } finally {
      inFlight.current = false;
    }
  };

  return (
    <section className="card">
      <div className="row space">
        <h2>Bulk issue</h2>
        <button onClick={submit} disabled={status === "running"}>
          {status === "running"
            ? "Issuing…"
            : status === "error"
              ? "Retry"
              : `Issue to eligible learners (${course.eligible})`}
        </button>
      </div>
      {error && <div className="banner error">Bulk issue failed — {error}</div>}
      {result && status === "done" && (
        <div>
          <p className="banner ok">
            Operation #{result.operation_id}{result.replayed ? " (replayed)" : ""}: {result.summary.issued} issued,{" "}
            {result.summary.skipped} skipped, {result.summary.failed} failed
          </p>
          <table>
            <thead>
              <tr>
                <th>Learner</th>
                <th>Outcome</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {result.results.slice(0, 200).map((r) => (
                <tr key={r.learner_id}>
                  <td>{r.learner_name}</td>
                  <td className={`outcome ${r.outcome}`}>{r.outcome}</td>
                  <td>{r.reason ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {result.results.length > 200 && (
            <p className="muted">Showing first 200 of {result.results.length} outcomes.</p>
          )}
        </div>
      )}
    </section>
  );
}


// ---------------- list ----------------

const SORTS = [
  ["issued_date", "Issue date"],
  ["learner_name", "Learner"],
  ["course_title", "Course"],
  ["serial", "Serial"],
] as const;

function CertificateList({
  ctx,
  tenant,
  refresh,
  onOpen,
}: {
  ctx: Ctx;
  tenant: Tenant;
  refresh: number;
  onOpen: (id: number) => void;
}) {
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("issued_date");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const [data, setData] = useState<CertPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [retry, setRetry] = useState(0);

  // debounce search input
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(search);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    const ac = new AbortController();
    setLoading(true);
    setError(null);
    const params: ListParams = { q, sort, order, page, pageSize };
    api
      .list(ctx, params, ac.signal)
      .then((d) => setData(d))
      .catch((e) => {
        if (!ac.signal.aborted) setError(errText(e));
      })
      .finally(() => {
        if (!ac.signal.aborted) setLoading(false);
      });
    return () => ac.abort(); // drop stale responses
  }, [ctx, q, sort, order, page, refresh, retry]);

  const doExport = async () => {
    setExporting(true);
    try {
      const blob = await api.exportCsv(ctx, { q, sort, order });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `certificates-${tenant.name.toLowerCase()}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(`Export failed — ${errText(e)}`);
    } finally {
      setExporting(false);
    }
  };

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;

  return (
    <section className="card">
      <div className="row space">
        <h2>Certificates — {tenant.name}</h2>
        <span className="muted">Dates shown in {tenant.timezone}</span>
      </div>
      <div className="row">
        <input
          placeholder="Search learner name or serial…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          value={sort}
          onChange={(e) => {
            setSort(e.target.value);
            setPage(1);
          }}
        >
          {SORTS.map(([v, l]) => (
            <option key={v} value={v}>
              Sort: {l}
            </option>
          ))}
        </select>
        <select
          value={order}
          onChange={(e) => {
            setOrder(e.target.value as "asc" | "desc");
            setPage(1);
          }}
        >
          <option value="asc">Ascending</option>
          <option value="desc">Descending</option>
        </select>
        <button onClick={doExport} disabled={exporting}>
          {exporting ? "Exporting…" : "Export CSV"}
        </button>
      </div>

      {error ? (
        <div className="banner error">
          Failed to load certificates — {error} <button onClick={() => setRetry((n) => n + 1)}>Retry</button>
        </div>
      ) : loading && !data ? (
        <p className="muted">Loading…</p>
      ) : data && data.items.length === 0 ? (
        <p className="empty">{q ? `No certificates match “${q}”.` : "No certificates yet."}</p>
      ) : data ? (
        <div className={loading ? "loading" : ""}>
          <table>
            <thead>
              <tr>
                <th>Serial</th>
                <th>Learner</th>
                <th>Course</th>
                <th>Issued ({tenant.timezone})</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => onOpen(c.id)}>
                  <td className="mono">{c.serial}</td>
                  <td>{c.learner_name}</td>
                  <td>{c.course_title}</td>
                  <td>{c.issued_local}</td>
                  <td>
                    <span className={`badge ${c.status.toLowerCase()}`}>{c.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row pager">
            <button disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)}>
              Prev
            </button>
            <span>
              Page {page} / {totalPages} · {data.total.toLocaleString()} total
            </span>
            <button disabled={page >= totalPages || loading} onClick={() => setPage((p) => p + 1)}>
              Next
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

// ---------------- detail ----------------

function DetailPanel({
  ctx,
  id,
  onClose,
  onChanged,
}: {
  ctx: Ctx;
  id: number;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<CertificateDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [revoking, setRevoking] = useState(false);

  useEffect(() => {
    let stale = false;
    api
      .detail(ctx, id)
      .then((d) => !stale && setDetail(d))
      .catch((e) => !stale && setError(errText(e)));
    return () => {
      stale = true;
    };
  }, [ctx, id]);

  const revoke = async () => {
    setRevoking(true);
    setError(null);
    try {
      const d = await api.revoke(ctx, id);
      setDetail(d);
      setConfirming(false);
      onChanged();
    } catch (e) {
      setError(`Revoke failed — ${errText(e)}`);
    } finally {
      setRevoking(false);
    }
  };

  return (
    <div className="overlay" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="row space">
          <h2>Certificate</h2>
          <button onClick={onClose}>Close</button>
        </div>
        {error && <div className="banner error">{error}</div>}
        {!detail && !error && <p className="muted">Loading…</p>}
        {detail && (
          <>
            <dl>
              <dt>Serial</dt>
              <dd className="mono">{detail.serial}</dd>
              <dt>Learner</dt>
              <dd>{detail.learner_name}</dd>
              <dt>Course</dt>
              <dd>{detail.course_title}</dd>
              <dt>Issued (tenant local)</dt>
              <dd>
                {detail.issued_local} <span className="muted">({detail.issued_at} UTC)</span>
              </dd>
              <dt>Status</dt>
              <dd>
                <span className={`badge ${detail.status.toLowerCase()}`}>{detail.status}</span>
                {detail.revoked_local && <span className="muted"> on {detail.revoked_local}</span>}
              </dd>
            </dl>
            {detail.status === "ACTIVE" &&
              (confirming ? (
                <div className="confirm">
                  <p>
                    Revoke <b>{detail.serial}</b> for {detail.learner_name}? This cannot be undone.
                  </p>
                  <button className="danger" onClick={revoke} disabled={revoking}>
                    {revoking ? "Revoking…" : "Confirm revoke"}
                  </button>
                  <button onClick={() => setConfirming(false)} disabled={revoking}>
                    Cancel
                  </button>
                </div>
              ) : (
                <button className="danger" onClick={() => setConfirming(true)}>
                  Revoke…
                </button>
              ))}
            <h3>Audit trail</h3>
            <ul className="audit">
              {detail.audit.map((a, i) => (
                <li key={i}>
                  <b>{a.action}</b> by {a.actor} at {a.created_local}
                  {a.operation_id ? ` (operation #${a.operation_id})` : ""}
                </li>
              ))}
            </ul>
          </>
        )}
      </aside>
    </div>
  );
}
