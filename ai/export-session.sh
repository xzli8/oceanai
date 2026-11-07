#!/usr/bin/env bash
# Copy the native Claude Code session export into ai/sessions/ with narrow redactions,
# then fill ended_at / related_commits in ai/session-index.csv.
# Re-run after the final AI interaction so the export is complete.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SESSION_ID="0c74d973-8a16-4c7b-bff7-5274b9753742"
SRC="$HOME/.claude/projects/-Users-lee-Desktop-oceanai/$SESSION_ID.jsonl"
DST="$ROOT/ai/sessions/$SESSION_ID.jsonl"
# Email to redact is passed at runtime so it is never committed. Usage: REDACT_EMAIL=you@example.com ./ai/export-session.sh
: "${REDACT_EMAIL:?set REDACT_EMAIL to the address to redact}"
export REDACT_EMAIL

python3 - "$SRC" "$DST" "$ROOT/ai/session-index.csv" "$ROOT" <<'EOF'
import csv, json, os, subprocess, sys
from datetime import datetime, timedelta, timezone

src, dst, index, root = sys.argv[1:5]
REDACTIONS = {
    os.environ["REDACT_EMAIL"]: "[REDACTED: candidate email]",
}

text = open(src, encoding="utf-8").read()
counts = {}
for old, new in REDACTIONS.items():
    counts[old] = text.count(old)
    text = text.replace(old, new)
open(dst, "w", encoding="utf-8").write(text)

# ended_at = last timestamp recorded in the export, in +08:00 like started_at
last = None
for line in text.splitlines():
    try:
        ts = json.loads(line).get("timestamp")
    except ValueError:
        continue
    if ts:
        last = ts
ended = (datetime.fromisoformat(last.replace("Z", "+00:00"))
         .astimezone(timezone(timedelta(hours=8))).isoformat(timespec="seconds"))

# related_commits = every commit co-authored with Claude
commits = subprocess.run(
    ["git", "log", "--reverse", "--format=%h", "--grep=Co-Authored-By: Claude"],
    cwd=root, capture_output=True, text=True, check=True).stdout.split()

rows = list(csv.DictReader(open(index, encoding="utf-8")))
fields = ["session_id", "tool", "model", "started_at", "ended_at", "export_file", "purpose", "related_commits"]
for r in rows:
    if r["session_id"] == dst.rsplit("/", 1)[1].removesuffix(".jsonl"):
        r["ended_at"] = ended
        r["related_commits"] = ";".join(commits)
with open(index, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)

print(f"exported {dst}")
print(f"redactions: {counts}")
print(f"ended_at: {ended}")
print(f"related_commits: {';'.join(commits)}")
EOF

if grep -qF "$REDACT_EMAIL" "$DST"; then
  echo "ERROR: unredacted email remains in export" >&2
  exit 1
fi
