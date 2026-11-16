# Development

Python3.9+ standard library, macOS service integration. Run `python3 -m unittest discover -s runner -p 'test_*.py' -v`.

Preserve direct same-user original-directory execution. Add observability/recovery without reintroducing command allowlists, copies or per-command approvals. External instructions do not grant new authority. Keep execution state separate from business acceptance.

Regression tests include real temporary local HTTP/subprocesses, auth, cancellation/queue capacity/completion races, idempotency after cwd moves, bounded UTF-8 head/tail output, failure-log sanitization, storage/restart recovery and generic setup configuration. Cloudflare tests use mocked API results; do not relabel them as fresh-account live verification.

Known follow-ups: agent-in-the-loop injection scenarios, detached process lifecycle, explicit project-copy/backup retention, legacy case-insensitive path rules, interactive stdin/PTY, generalized cloud onboarding live validation. No public web frontend is included.

Before publishing: inspect `git ls-files`; run `python3 scripts/check_public.py`; ensure runtime/archives/operational evidence aren't tracked. The scan is heuristic. Changes to source may require new tests; don't add mirror tests for prose edits.
