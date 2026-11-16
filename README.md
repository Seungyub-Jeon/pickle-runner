# Pickle Runner

A self-hosted macOS command runner for a trusted remote AI agent.

**Early developer release, v0.3.3.** Run commands and installed CLIs in original project directories, as the macOS login user. There is no command allowlist, mandatory copy, or per-command approval. Credentials grant that user's shell authority; this is not a multi-tenant sandbox.

The code lives on GitHub. The process and files stay on your Mac. Cloudflare Tunnel and Access provide the remote connection.

```text
Remote agent → HTTPS + Cloudflare Access → Cloudflare Tunnel
                                             ↓
                           Mac: 127.0.0.1:8796 → zsh / installed CLIs
```

## Start with an agent

Open this repository with your local coding agent and say:

> Read AGENTS.md and docs/SETUP.md. Install Pickle Runner on this Mac. Start locally, then help connect my Cloudflare domain. Ask me for account/domain choices and handle credentials through hidden local input, not chat. Verify the connection before reporting success.

The agent reads `AGENTS.md`; the program does not depend on any particular AI model. `python3 runner/setup.py status` reports the next setup step. There is no bundled model or model API key requirement.

## Local quick start

Requirements: macOS, Python 3.9+, zsh. Run from the repository root:

```bash
python3 runner/setup.py status
python3 runner/setup.py init
python3 runner/manage.py install
python3 runner/client.py health
python3 runner/client.py capabilities
```

New configurations enable `terminal.run`. Existing configurations are preserved. `install` starts a login-user LaunchAgent; it refuses to replace an existing same-name service owned by another checkout. Check your current installation before installing a second copy.

```bash
python3 runner/client.py submit --action terminal.run \
  --args '{"cwd":"/absolute/path/to/project","command":"pwd","timeout_sec":60}' \
  --request-id my-unique-request-001 --wait
```

## Remote setup

Use your own Cloudflare account, a zone you manage, and a dedicated unused subdomain. Install `cloudflared` using the official distribution or your package manager. There is no shared server, default connection token, or preconfigured customer domain.

```bash
python3 runner/setup.py cloudflare --zone example.com --hostname runner.example.com
python3 runner/cloudflare_token.py prompt
python3 runner/setup.py connect
```

The first command only records local choices. The second accepts a management API token in a hidden macOS prompt. `connect` creates scoped Access/Tunnel resources and the selected DNS record, then verifies both authentication layers. Read [setup](docs/SETUP.md) for permissions and the exact changes. Your existing production installation is not a template credential source.

## Runtime contract

- `POST /v1/jobs`: asynchronous, single worker; poll the returned job ID.
- `terminal.run`: zsh `-lc`, original cwd, default 3,600 seconds, maximum 86,400; no stdin or PTY.
- `POST /v1/jobs/{id}/cancel` with `{}`: cancel queued work or request process-group termination. A 202 is not completed cleanup. Already-finished results remain intact.
- Same request ID and body retrieve the existing record, including after cwd moves. Changed body returns 409. Deduplication records expire after 30 days; never reuse old IDs for new work.
- stdout/stderr each retain a bounded head/tail summary, not a full log. Read `truncated`, `output`, and `cleanup_warning`.
- Results: at most 7 days or 2,000 full records; deduplication receipts: 30 days, up to 100,000. Project copies/backups currently require separate storage management.
- `GET /v1/state`, `/v1/events`, and job reads remain available while a command runs.
- `project.*` provides optional compatibility operations. New installs use the direct terminal route; project-root/tool configuration is not enabled automatically.

[Agent usage](runner/PICKLE.md) · [OpenAPI](runner/openapi.json) · [Operations](docs/OPERATIONS.md) · [Security model](SECURITY.md) · [Development](docs/DEVELOPMENT.md)

## Verification and limits

```bash
python3 -m unittest discover -s runner -p 'test_*.py' -v
```

Tests use temporary workspaces, subprocesses and local HTTP. Cloudflare configuration tests use fake responses; they do not create resources in your account. The original deployed runner's end-to-end evidence is private and is not shipped here. The generalized public installer still needs fresh-account end-to-end validation.

This is not a guarantee against prompt injection. External emails, pages and tool output cannot grant new execution authority. Read the source rules in `runner/PICKLE.md`. Detached processes may outlive cancellation. No Windows/Linux service installer, interactive terminal, web dashboard, or hosted multi-user control plane is included. Do not present process exit code zero as business acceptance.

## License

A reuse license has not yet been selected. Repository visibility alone should not be read as a reuse grant.
