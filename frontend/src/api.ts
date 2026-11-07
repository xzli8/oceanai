export type Tenant = { id: number; name: string; timezone: string };
export type Course = { id: number; title: string; enrolled: number };
export type Certificate = {
  id: number;
  serial: string;
  learner_name: string;
  course_title: string;
  issued_at: string;
  issued_local: string;
  issued_local_date: string;
  status: "ACTIVE" | "REVOKED";
  revoked_local: string | null;
};
export type AuditEvent = { action: string; actor: string; created_local: string; operation_id: number | null };
export type CertificateDetail = Certificate & { audit: AuditEvent[]; changed?: boolean };
export type CertPage = { items: Certificate[]; total: number; page: number; page_size: number; timezone: string };
export type Outcome = {
  learner_id: number;
  learner_name: string;
  outcome: "issued" | "skipped" | "failed";
  reason?: string;
  certificate_id?: number;
};
export type BulkResult = {
  operation_id: number;
  course_title: string;
  summary: { issued: number; skipped: number; failed: number };
  results: Outcome[];
  replayed: boolean;
};

export type Ctx = { actor: string; tenantId: number };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function headers(ctx: Partial<Ctx>, extra: Record<string, string> = {}) {
  const h: Record<string, string> = { ...extra };
  if (ctx.actor) h["X-Actor"] = ctx.actor;
  if (ctx.tenantId != null) h["X-Tenant-Id"] = String(ctx.tenantId);
  return h;
}

async function request<T>(path: string, ctx: Partial<Ctx>, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: headers(ctx, (init.headers as Record<string, string>) ?? {}),
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export type ListParams = { q: string; sort: string; order: "asc" | "desc"; page: number; pageSize: number };

function listQuery(p: Omit<ListParams, "page" | "pageSize">) {
  const s = new URLSearchParams({ sort: p.sort, order: p.order });
  if (p.q.trim()) s.set("q", p.q.trim());
  return s;
}

export const api = {
  actors: () => request<string[]>("/api/actors", {}),
  myTenants: (actor: string) => request<{ tenants: Tenant[] }>("/api/me/tenants", { actor }),
  courses: (ctx: Ctx) => request<Course[]>("/api/courses", ctx),
  list: (ctx: Ctx, p: ListParams, signal?: AbortSignal) => {
    const s = listQuery(p);
    s.set("page", String(p.page));
    s.set("page_size", String(p.pageSize));
    return request<CertPage>(`/api/certificates?${s}`, ctx, { signal });
  },
  detail: (ctx: Ctx, id: number) => request<CertificateDetail>(`/api/certificates/${id}`, ctx),
  revoke: (ctx: Ctx, id: number) =>
    request<CertificateDetail>(`/api/certificates/${id}/revoke`, ctx, { method: "POST" }),
  bulkIssue: (ctx: Ctx, courseId: number, idempotencyKey: string) =>
    request<BulkResult>("/api/bulk-issues", ctx, {
      method: "POST",
      body: JSON.stringify({ course_id: courseId }),
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    }),
  exportCsv: async (ctx: Ctx, p: Omit<ListParams, "page" | "pageSize">) => {
    const res = await fetch(`/api/certificates/export.csv?${listQuery(p)}`, { headers: headers(ctx) });
    if (!res.ok) throw new ApiError(res.status, res.statusText);
    return res.blob();
  },
};
