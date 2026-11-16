# Operations

`client.py health`, `state`, `events --since CURSOR` and `get --job-id ID` expose the recorded execution state. client.py waits130seconds by default; waiting timeout doesn't cancel the job. `cancel --job-id ID --wait` requests cancellation and polls. Detached descendants aren't guaranteed to stop.

A user LaunchAgent runs after login, not before FileVault unlock. Sleep/network loss interrupts remote availability. No power-management changes are made by this installer.

## Emergency stop

From the intended checkout:

```bash
launchctl disable "gui/$(id -u)/io.picklerunner.agent"
launchctl disable "gui/$(id -u)/io.picklerunner.tunnel"
python3 runner/manage.py stop
launchctl bootout "gui/$(id -u)/io.picklerunner.tunnel"
```

Wait for both services to disappear from launchctl print. disable persists across login; bootout alone does not. Distinguish already-absent from actual errors. Check local origin failure and authenticated external health failure; an unauthenticated401 doesn't prove the origin is down. Investigate owned residual processes without killing unrelated user processes.

To restore existing plist registrations:

```bash
launchctl enable "gui/$(id -u)/io.picklerunner.agent"
launchctl enable "gui/$(id -u)/io.picklerunner.tunnel"
python3 runner/manage.py install
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/io.picklerunner.tunnel.plist"
python3 runner/client.py health
python3 runner/check_remote.py --config .runtime/pickle-runner/client-remote.json
```

Don't bootstrap a tunnel already loaded. Restarts mark unfinished jobs interrupted instead of replaying them. Check original files before retrying work with a new ID.

## Credentials and storage

The generated client config contains real secrets. Keep it0600 and transfer privately. Access service tokens are issued for 720 hours (30 days), with no automatic renewal; health reports stored expiry metadata, not live provider validation. Renewing needs a new hidden management-token input, then `cloudflare_connect.py renew`, followed by external checks and `credentials.py forget-setup-token`. Revocation/rotation after compromise is separate: revoke Access credentials and rotate runner/client secrets together; assess tunnel tokens, management tokens, CLI sessions and host SSH keys according to actual exposure.

Results are retained at most7days/2,000full records, dedup receipts30days/100,000. Events30days/20,000. Failure logs rotate separately (256KiB plus2backups) without request bodies, commands, query strings or tokens. Unknown routes/actions become unrecognized. Project run copies and backups are not automatically pruned; manage disk usage and retain needed recovery copies.

Don't delete the live DB to recover from a failed job. Keep a private SQLite-consistent backup and preserve records of work that may have already changed files.

## Remove a connection permanently

First follow Emergency stop and verify the runner and tunnel are stopped. Run `python3 runner/manage.py uninstall` and remove the owned `$HOME/Library/LaunchAgents/io.picklerunner.tunnel.plist` after confirming its ProgramArguments points to this checkout. Keep both labels disabled until intentionally reinstalling.

In Cloudflare, remove only this installation's resources, matching IDs from the private `.runtime/cloudflare-setup/resources.json`: `dns_record_id` (the selected hostname), `access_app_id`, `policy_id`, `service_token_id`, and `tunnel_id`. Delete the DNS record first, then the dedicated Access app/policy, revoke the service token, and delete the tunnel. Inspect for partially created same-name resources when a receipt is missing; do not delete resources based solely on a similar display name. Revoke the setup management API token separately in the account where it was issued.

Confirm the hostname no longer reaches the runner. Revoke/remove recipient configuration copies and keep or remove this checkout's private runtime data according to your backup needs. Local uninstall does not delete Cloudflare resources or recipient credentials.

## Legacy project helpers

`project.*` and `summarize_workspace.py` are retained compatibility helpers; new installations do not enable their project/tool configuration. The older project CLI adapter uses a fixed Codex model and priority service setting. Use `terminal.run` for the installed Claude Code, Codex, AGY or other CLI and its chosen model/account settings. The model-independent usage described in README refers to that direct terminal path.
