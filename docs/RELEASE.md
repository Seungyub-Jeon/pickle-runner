# Public preparation status

Prepared 2026-11-16, code version0.3.3.

- 60 local regression tests passed on macOS, including temporary real HTTP/subprocess tests and mocked onboarding tests.
- Tracked-file heuristic checks passed. Operational histories, archives, production settings, tokens, personal paths/domains and bundled binaries are excluded from this repository.
- A fresh local init enables terminal.run and preserves existing settings. Public service labels are io.picklerunner.agent/tunnel; an occupied local port prevents installation from confusing another service with this checkout.
- Generalized Cloudflare account/zone setup has local/mock coverage. A fresh-account live provisioning cycle has not yet been performed. CI execution on GitHub is also pending first push.
- License selection is pending. No third-party binaries are bundled.

This is an early developer release. Source publication, installation success, external authentication checks, agent prompt-injection resistance and business acceptance are separate claims.
