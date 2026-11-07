import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  ApiError,
  type BulkResult,
  type CertificateDetail,
  type CertPage,
  type Course,
  type Ctx,
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
  const [refresh, setRefresh] = useState(0);
  const [openId, setOpenId] = useState<number | null>(null);
  const bump = () => setRefresh((n) => n + 1);
  return (
    <main>
      <BulkIssuePanel ctx={ctx} onDone={bump} />
      <CertificateList ctx={ctx} tenant={tenant} refresh={refresh} onOpen={setOpenId} />
      {openId != null && (
        <DetailPanel ctx={ctx} id={openId} onClose={() => setOpenId(null)} onChanged={bump} />
      )}
    </main>
  );
}

// ---------------- bulk issue ----------------

function BulkIssuePanel({ ctx, onDone }: { ctx: Ctx; onDone: () => void }) {
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseId, setCourseId] = useState<number | null>(null);
  const [status, setStatus] = useState<"idle" | "running" | "done" | "error">("idle");
  const [result, setResult] = useState<BulkResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  // One key per intended operation: reused on retry after an error, rotated after success or course change.
  const keyRef = useRef<string>(crypto.randomUUID());
  const inFlight = useRef(false);

  useEffect(() => {
    api.courses(ctx).then(setCourses).catch((e) => setError(errText(e)));
  }, [ctx]);

  const submit = async () => {
    if (courseId == null || inFlight.current) return;
    inFlight.current = true;
    setStatus("running");
    setError(null);
    try {
      const r = await api.bulkIssue(ctx, courseId, keyRef.current);
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
      <h2>Bulk issue</h2>
      <div className="row">
        <select
          value={courseId ?? ""}
          disabled={status === "running"}
          onChange={(e) => {
            setCourseId(e.target.value ? Number(e.target.value) : null);
            keyRef.current = crypto.randomUUID();
            setResult(null);
            setStatus("idle");
          }}
        >
          <option value="">Select course…</option>
          {courses.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title} ({c.enrolled} enrolled)
            </option>
          ))}
        </select>
        <button onClick={submit} disabled={courseId == null || status === "running"}>
          {status === "running" ? "Issuing…" : status === "error" ? "Retry" : "Issue to eligible learners"}
        </button>
      </div>
      {error && <div className="banner error">Bulk issue failed — {error}</div>}
      {result && status === "done" && (
        <div>
          <p className="banner ok">
            Operation #{result.operation_id} ({result.course_title}){result.replayed ? " — replayed" : ""}:{" "}
            {result.summary.issued} issued, {result.summary.skipped} skipped, {result.summary.failed} failed
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
              {result.results.map((r) => (
                <tr key={r.learner_id}>
                  <td>{r.learner_name}</td>
                  <td className={`outcome ${r.outcome}`}>{r.outcome}</td>
                  <td>{r.reason ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
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
