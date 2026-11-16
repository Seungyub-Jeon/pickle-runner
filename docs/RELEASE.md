# Public preparation status

Prepared 2026-11-16, code version0.3.3.

- 64 local regression tests passed on macOS, including temporary real HTTP/subprocess tests and mocked onboarding tests.
- Tracked-file heuristic checks passed. Operational histories, archives, production settings, tokens, personal paths/domains and bundled binaries are excluded from this repository.
- A fresh local init enables terminal.run and preserves existing settings. Public service labels are io.picklerunner.agent/tunnel; an occupied local port prevents installation from confusing another service with this checkout.
- Cloudflare tests cover local settings, setup orchestration with a mocked Setup, DNS preservation/collision, service dispatch and token renewal. Provisioning API creation/resume paths are not fully covered. A fresh-account live provisioning cycle has not yet been performed. CI execution on GitHub is also pending first push.
- Claude Code, Codex and AGY each launched successfully via the public terminal execution path (`--version`); this does not verify every model or a remote Pickle task.
- License selection is pending. No third-party binaries are bundled.

This is an early developer release. Source publication, installation success, external authentication checks, agent prompt-injection resistance and business acceptance are separate claims.

Independent source-snapshot reviews were completed with Claude Fable 5.2 and AGY's default model. Relevant findings led to RSA4096 transfer guidance, safe connection-stage errors, partial-setup retry guidance, tunnel restart dispatch, lifecycle documentation and tests. Review comments were checked against source; these static reviews are not live installation acceptance or approval of every subsequent change.
