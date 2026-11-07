"""Certificate queries shared by list and CSV export, so both use identical filter + order."""
from fastapi import HTTPException

# Every sort ends with `id` so ordering is total and stable across repeated queries/exports.
SORTS = {
    "issued_date": ["issued_local_date", "issued_at", "id"],
    "learner_name": ["learner_name", "id"],
    "course_title": ["course_title", "id"],
    "serial": ["serial", "id"],
}

COLUMNS = (
    "id, serial, learner_id, course_id, learner_name, course_title,"
    " issued_at, issued_local_date, status, revoked_at"
)


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_query(tenant_id: int, q: str | None, sort: str, order: str):
    if sort not in SORTS:
        raise HTTPException(400, f"sort must be one of {sorted(SORTS)}")
    if order not in ("asc", "desc"):
        raise HTTPException(400, "order must be asc or desc")
    where = ["tenant_id = ?"]
    params: list = [tenant_id]
    if q and q.strip():
        term = _escape_like(q.strip())
        # learner name: case-insensitive contains; serial: case-insensitive prefix
        where.append("(learner_name LIKE ? ESCAPE '\\' OR serial LIKE ? ESCAPE '\\')")
        params += [f"%{term}%", f"{term}%"]
    direction = "ASC" if order == "asc" else "DESC"
    order_by = ", ".join(f"{col} {direction}" for col in SORTS[sort])
    return " AND ".join(where), params, order_by
