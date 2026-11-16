# Agent-assisted setup

## Where each part runs

GitHub distributes source and updates. The Mac runs the shell, installed CLIs, local HTTP server and `cloudflared`. Cloudflare routes HTTPS requests and checks Access service credentials. The remote agent additionally supplies the runner bearer token. The Mac must be awake and online.


Reference: [Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/).

## 1. Local installation

Run `python3 runner/setup.py status`. Unsupported systems should not install the LaunchAgent. Choose a checkout that will remain on disk; launchd references its absolute path.

Run `python3 runner/setup.py init --port 8796`, `python3 runner/manage.py install`, then `python3 runner/client.py health`. New configuration includes terminal_enabled=true. Init preserves existing configuration and secrets; it does not silently migrate an older config. The server binds to 127.0.0.1.

The public checkout uses the service name io.picklerunner.agent for this public distribution. A second checkout cannot replace the same label. To migrate, plan downtime and preserve the existing state; installation is not a second independent instance on another port.

## 2. Cloudflare choices and local preparation

This automated path requires a Cloudflare account with an active DNS zone and an unused subdomain, for example runner.example.com. Account registration, domain purchase/delegation and billing choices remain with the user. Local-only use requires none of them. Public quick tunnels are not the default deployment path.

Install cloudflared from [official downloads](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/) or your package manager (for example `brew install cloudflared`). It must be on PATH when configuring the service; its absolute path is then saved in the LaunchAgent. We do not bundle a downloaded binary.

```bash
python3 runner/setup.py cloudflare --zone example.com --hostname runner.example.com \
  --preserve-host app.example.com
```

`--preserve-host` is optional/repeatable. It snapshots those existing hosts and refuses to proceed if their records change; it never rewrites them. The target hostname must not be a preserved host. Once provisioning has started, changing hostname/zone in-place is refused so resources from different setups are not mixed. The chosen host is checked for ownership before DNS publication.

## 3. Credentials

Sign into your Cloudflare account and issue a narrowly scoped user API token for the selected account and zone. Required capabilities for this path are Zone Read, DNS Edit, Cloudflare Tunnel Edit, Access Apps and Policies Edit, and Access Service Tokens Edit. Cloudflare may rename permission labels; use the current [permissions reference](https://developers.cloudflare.com/fundamentals/api/reference/permissions/). This path verifies user tokens; account-owned API tokens are not yet supported by its verification flow.

Run `python3 runner/cloudflare_token.py prompt` for hidden macOS entry, or `save` in your own interactive terminal. Do not supply the token as a CLI flag, environment dump, chat message or GitHub secret in a public issue. The tool validates the token/zone and stores private local files under .runtime.

## 4. Connect and verify

`python3 runner/setup.py connect` performs the explicitly requested remote setup:

1. Verify local runner health and cloudflared availability.
2. Create a per-host Access service token (720h), Service Auth policy and self-hosted Access application.
3. Create a dedicated named tunnel and configure ingress only for the chosen host to the configured loopback port, plus a catch-all404.
4. Start the user tunnel LaunchAgent and wait for a healthy connector.
5. Create the chosen proxied CNAME. Existing unrelated DNS records are not overwritten.
6. Verify no credentials and runner-only credentials are rejected upstream, Access-only reaches the runner but is rejected, and both credentials return health200.
7. Save expiration metadata and remove the local management API token copy. The provider-issued token itself is not revoked by deleting its file.

Provisioning checkpoints are private. A failed step can leave created resources; inspect .runtime/cloudflare-setup through tools that do not print secrets and retry the same configuration. Do not delete checkpoints and rerun blindly: cloud objects may remain. This is not an atomic transaction or automatic rollback. DNS propagation may delay verification; `check_remote.py` can be rerun without new provisioning.

The generalized installer is covered by local/mock tests; validate it in your own fresh account before treating it as a supported one-click installer. References: [Tunnel API setup](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel-api/), [Service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/).

## 5. Connect the remote agent

The generated .runtime/pickle-runner/client-remote.json contains credentials and must remain private (0600). Transfer it only using an explicitly chosen private mechanism, such as recipient-public-key encryption. client.py supports RSA-OAEP(SHA256) encrypted configuration with `--encrypted-config` and `--private-key`. No automatic upload/email is performed.

Ask the remote agent to read runner/PICKLE.md, query capabilities and perform one bounded test task in a disposable folder. Confirm results on the Mac. A successful API check does not establish resistance to all indirect prompt injection.
