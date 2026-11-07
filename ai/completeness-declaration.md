# AI Completeness Declaration

## Tools used

| Tool | Model | Used for | Export |
|---|---|---|---|
| Claude Code (CLI, macOS) | `claude-opus-5-5` | All planning, code, tests, docs and git commits in this repository | Native JSONL: `ai/sessions/0c74d973-8a16-4c7b-bff7-5274b9753742.jsonl` |
| Claude in Chrome (browser extension, driven from the same Claude Code session) | same session | Manual UI checks: actor/tenant switch, bulk issue, course detail, revoke | Included in the same JSONL as tool calls and results |

No other AI tools were used:

- No other chat assistants.
- No IDE inline autocomplete or AI code completion. There is no non-exportable activity to disclose.
- No subagents were spawned. The session directory contains only the one JSONL file.

There is exactly one AI session, listed in `ai/session-index.csv`.

## What the export contains

The JSONL is Claude Code's native transcript, not a curated list. It contains:

- Every user prompt and full assistant response.
- Every tool call with its result: shell commands and their output, file writes and edits, file reads, browser actions and screenshots.
- Errors and failed runs. For example, the first test run failed on the SOCKS proxy, and the API server failed to start because port 8000 was in use.
- Timestamps (UTC in the file) and the model identifier.

`AGENTS.md`, the AI instruction file used for this build, is committed at the repository root.

## Export limitations

- **Snapshot timing.** The export is a copy of the live session file, made by `ai/export-session.sh`. That script is re-run after the final AI interaction. Any AI activity after the final copy, such as the commit that adds the copy itself, is not in the export.
- **Embedded binary data.** The export contains base64 image data for the browser screenshots and the PDF brief that was given to the assistant. This is the tool's native format; it was left unmodified.

## Redactions

Narrow string replacements only. The substance of the interaction is unchanged.

| Original | Replacement | Reason |
|---|---|---|
| Candidate's personal email address | `[REDACTED: candidate email]` | Personal data |

- No credentials, API keys or tokens appear in the session; the export was scanned for these before submission.
- The demo accounts (`alice@east.test`, `bob@west.test`, `carol@multi.test`) are fictional seed data and are not redacted.

## Section 6 (written answers)
I confirm that Section 6 (`written-answers.md`) was completed by me alone, without any AI assistance, including translation and language polishing.
