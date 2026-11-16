# Security model and reporting

This is a trusted single-owner remote shell, not an untrusted-code sandbox. A valid remote caller can execute with the Mac login user's permissions, including files and installed CLIs. Protect both credential layers. The server binds to loopback; don't publish the origin directly.

The program cannot prove whether an agent's request originated from the owner's task or an injected email. Agent source rules and scenario evaluations are necessary; XML delimiters or client-supplied authorization metadata do not establish trusted origin.

Cancellation targets the process group. A detached session can outlive it, and a signalling warning must not be reported as complete cleanup. Output is not guaranteed to be secret-free. Private runtime files and encrypted connection archives must never be committed. Generalized Cloudflare onboarding still requires fresh-account live validation.

For a suspected vulnerability, use the repository's private vulnerability reporting channel if enabled. If none is available, open a minimal issue asking the maintainer for a private channel; do not include active credentials, private logs, or exploit details that disclose someone's host. There is no promised response SLA for this early release.
