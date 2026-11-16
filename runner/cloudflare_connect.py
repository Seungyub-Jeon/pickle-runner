#!/usr/bin/env python3
"""Provision only this runner's isolated CF resources; preserve existing services."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import plistlib
import subprocess
import time
import shutil
import hashlib
import urllib.error
import urllib.request
import urllib.parse

from cloudflare_token import ROOT, STORE, HOST, NoRedirect
from manage import RUNTIME, private_json

LABEL = "io.picklerunner.tunnel"
PLIST = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
PREFIX = "pickle-runner-" + hashlib.sha256(HOST.encode()).hexdigest()[:10]


class Setup:
    def __init__(self):
        self.plan = json.loads((STORE / "plan.json").read_text())
        if not HOST or self.plan["hostname"] != HOST:
            raise RuntimeError("Cloudflare hostname configuration differs; do not reuse another setup")
        self.token = (STORE / "api-token").read_text().strip()
        self.account = "/accounts/" + self.plan["account_id"]
        self.zone = "/zones/" + self.plan["zone_id"]
        self.state_file = STORE / "resources.json"
        self.state = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def api(self, path, method="GET", body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request("https://api.cloudflare.com/client/v4" + path, data=data, method=method,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=25) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            try:
                error = json.loads(exc.read(64000))
                codes = [e.get("code") for e in error.get("errors", [])]
            except Exception:
                codes = []
            raise RuntimeError("Cloudflare API HTTP %s, error codes %s" % (exc.code, codes)) from None
        if len(raw) > 8 * 1024 * 1024:
            raise RuntimeError("Cloudflare response too large")
        value = json.loads(raw)
        if not value.get("success"):
            raise RuntimeError("Cloudflare API refused request; codes=" + str([e.get("code") for e in value.get("errors", [])]))
        return value.get("result")

    def checkpoint(self, key, value):
        self.state[key] = value
        private_json(self.state_file, self.state)

    def preserve_app(self):
        # Snapshot only user-selected existing hosts. Never rewrite their DNS records.
        names = self.plan.get("preserve_hostnames", [])
        def stable(records):
            return sorted([{k: r.get(k) for k in ("id", "name", "type", "content", "proxied", "ttl", "comment")} for r in records], key=lambda r:r["id"])
        current = {}
        for host in names:
            records = self.api(self.zone + "/dns_records?name=" + urllib.parse.quote(host) + "&per_page=100")
            if len(records) >= 100:
                raise RuntimeError("Too many records for preserved host; review DNS manually")
            current[host] = stable(records)
        path = STORE / "before.json"
        if not path.exists():
            private_json(path, {"dns_records": current})
        elif json.loads(path.read_text())["dns_records"] != current:
            raise RuntimeError("Preserved DNS changed; investigate without overwriting it")
        return True

    def no_existing(self, path, field, value):
        if any(item.get(field) == value for item in self.api(path)):
            raise RuntimeError("A resource with this name already exists without a local receipt. Review before continuing.")

    def provision(self):
        self.preserve_app()
        if "service_token_id" not in self.state:
            self.no_existing(self.account + "/access/service_tokens?per_page=100", "name", PREFIX + "-client")
            result = self.api(self.account + "/access/service_tokens", "POST", {"name": PREFIX + "-client", "duration": "720h"})
            private_json(STORE / "service-token.json", result)
            self.checkpoint("service_token_id", result["id"])
            print("전용 Access 서비스 토큰 생성 완료 (비밀값은 로컬에만 저장)", flush=True)
        service = json.loads((STORE / "service-token.json").read_text())
        if "policy_id" not in self.state:
            self.no_existing(self.account + "/access/policies?per_page=100", "name", PREFIX + "-service-only")
            policy = self.api(self.account + "/access/policies", "POST", {"name": PREFIX + "-service-only", "decision": "non_identity",
                "include": [{"service_token": {"token_id": service["id"]}}], "exclude": [], "require": []})
            self.checkpoint("policy_id", policy["id"])
            print("원격 에이전트 전용 Service Auth 정책 생성 완료", flush=True)
        if "access_app_id" not in self.state:
            self.no_existing(self.account + "/access/apps?per_page=100", "domain", HOST)
            app = self.api(self.account + "/access/apps", "POST", {"name": "Pickle Runner", "type": "self_hosted", "domain": HOST,
                "session_duration": "15m", "app_launcher_visible": False, "service_auth_401_redirect": True,
                "policies": [{"id": self.state["policy_id"], "precedence": 1}]})
            self.checkpoint("access_app_id", app["id"])
            print("runner 호스트 전용 Access 앱 생성 완료", flush=True)
        self.verify_policy()
        if "tunnel_id" not in self.state:
            self.no_existing(self.account + "/cfd_tunnel?is_deleted=false&per_page=100", "name", PREFIX)
            tunnel = self.api(self.account + "/cfd_tunnel", "POST", {"name": PREFIX, "config_src": "cloudflare"})
            private_json(STORE / "created-tunnel.json", tunnel)
            self.checkpoint("tunnel_id", tunnel["id"])
            print("독립 실행기 터널 생성 완료", flush=True)
        tid = self.state["tunnel_id"]
        token_file = STORE / "tunnel-token"
        if not token_file.exists():
            result = self.api(self.account + "/cfd_tunnel/" + tid + "/token")
            if not isinstance(result, str) or len(result) < 32:
                raise RuntimeError("Tunnel token response invalid")
            fd = os.open(str(token_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(result + "\n")
        desired = {"ingress": [{"hostname": HOST, "service": self.plan["target_origin"]}, {"service": "http_status:404"}]}
        self.api(self.account + "/cfd_tunnel/" + tid + "/configurations", "PUT", {"config": desired})
        actual = self.api(self.account + "/cfd_tunnel/" + tid + "/configurations")
        if actual["config"]["ingress"] != desired["ingress"]:
            raise RuntimeError("Tunnel configuration readback differs")
        cfg = {"url": "https://" + HOST, "token": (RUNTIME / "agent-token").read_text().strip(),
               "access_client_id": service["client_id"], "access_client_secret": service["client_secret"], "dns_over_https": True}
        private_json(RUNTIME / "client-remote.json", cfg)
        self.preserve_app()
        print("설정 읽기 확인 완료. DNS 공개와 터널 실행은 아직 진행 전입니다.", flush=True)

    def verify_policy(self):
        app = self.api(self.account + "/access/apps/" + self.state["access_app_id"])
        policy = self.api(self.account + "/access/policies/" + self.state["policy_id"])
        if app.get("domain") != HOST or len(app.get("policies", [])) != 1 or app["policies"][0].get("id") != self.state["policy_id"]:
            raise RuntimeError("Runner Access application scope/policy differs")
        expected = [{"service_token": {"token_id": self.state["service_token_id"]}}]
        if policy.get("decision") != "non_identity" or policy.get("include") != expected or policy.get("exclude") or policy.get("require"):
            raise RuntimeError("Runner Service Auth policy differs")
        return True

    def service(self, stop=False):
        domain = "gui/" + str(os.getuid())
        if stop:
            subprocess.run(["/bin/launchctl", "bootout", domain + "/" + LABEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        self.verify_policy()
        binary = Path(shutil.which("cloudflared") or "/missing-cloudflared")
        if not binary.is_file() or not (STORE / "tunnel-token").is_file():
            raise RuntimeError("Verified cloudflared binary or tunnel credential missing")
        argv = [str(binary), "--no-autoupdate", "tunnel", "--protocol", "http2", "--metrics", "127.0.0.1:0", "run", "--token-file", str(STORE / "tunnel-token")]
        if PLIST.exists():
            previous = plistlib.loads(PLIST.read_bytes())
            if previous.get("ProgramArguments") != argv:
                raise RuntimeError("A different service owns this launchd label")
        props = {"Label": LABEL, "ProgramArguments": argv, "WorkingDirectory": str(ROOT), "RunAtLoad": True, "KeepAlive": True,
            "ThrottleInterval": 10, "Umask": 0o077, "EnvironmentVariables": {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(Path.home())},
            "StandardOutPath": str(STORE / "tunnel.out.log"), "StandardErrorPath": str(STORE / "tunnel.err.log")}
        PLIST.write_bytes(plistlib.dumps(props))
        os.chmod(PLIST, 0o600)
        self.service(stop=True)
        subprocess.run(["/bin/launchctl", "bootstrap", domain, str(PLIST)], check=True)
        print("독립 사용자 터널 서비스 시작 완료", flush=True)

    def publish(self):
        self.verify_policy()
        self.preserve_app()
        tunnel = self.api(self.account + "/cfd_tunnel/" + self.state["tunnel_id"])
        if tunnel.get("status") != "healthy":
            raise RuntimeError("Tunnel is not healthy; no DNS record was published")
        wanted = self.state["tunnel_id"] + ".cfargotunnel.com"
        records = self.api(self.zone + "/dns_records?name=" + HOST)
        if records:
            if len(records) != 1 or records[0]["id"] != self.state.get("dns_record_id") or records[0]["content"] != wanted:
                raise RuntimeError("Runner hostname already belongs to a different DNS record")
        else:
            record = self.api(self.zone + "/dns_records", "POST", {"type": "CNAME", "name": HOST, "content": wanted,
                "proxied": True, "ttl": 1, "comment": "Pickle Runner dedicated tunnel"})
            self.checkpoint("dns_record_id", record["id"])
        self.preserve_app()
        print("runner DNS 공개 완료. 선택한 기존 DNS 보존 확인", flush=True)

    def status(self):
        result = {"hostname": HOST, "resources": self.state, "existing_app_dns_preserved": self.preserve_app()}
        if self.state.get("tunnel_id"):
            tunnel = self.api(self.account + "/cfd_tunnel/" + self.state["tunnel_id"])
            result.update({"tunnel_status": tunnel.get("status"), "connections": len(tunnel.get("connections", []))})
        if self.state.get("access_app_id"):
            result["service_auth_policy_verified"] = self.verify_policy()
        result["access_service_token"] = self.credential_metadata()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    def credential_metadata(self):
        from credentials import expiry_status
        remote = self.api(self.account + "/access/service_tokens/" + self.state["service_token_id"])
        local = json.loads((STORE / "service-token.json").read_text())
        if remote["id"] != local["id"] or remote["client_id"] != local["client_id"]:
            raise RuntimeError("Runner service token identity differs")
        metadata = {"access_expires_on": remote.get("expires_at"), "checked_at": datetime.now(timezone.utc).isoformat()}
        if not metadata["access_expires_on"]:
            raise RuntimeError("Runner service token expiry missing")
        private_json(RUNTIME / "credential-status.json", metadata)
        # GET never reveals a new secret; preserve the existing private value.
        for key in ("expires_at", "duration", "updated_at"):
            if key in remote:
                local[key] = remote[key]
        private_json(STORE / "service-token.json", local)
        return expiry_status(metadata["access_expires_on"])

    def renew(self):
        # A duration update extends this token without rotating its Client Secret.
        # Keep the original 30-day policy; the refresh endpoint instead adds a year.
        self.preserve_app()
        self.verify_policy()
        local = json.loads((STORE / "service-token.json").read_text())
        path = self.account + "/access/service_tokens/" + self.state["service_token_id"]
        remote = self.api(path)
        if remote["id"] != local["id"] or remote["client_id"] != local["client_id"]:
            raise RuntimeError("Runner service token identity differs")
        self.api(path, "PUT", {"name": remote["name"], "duration": "720h"})
        status = self.credential_metadata()
        self.preserve_app()
        print(json.dumps({"renewed": True, "secret_rotated": False, "access_service_token": status}, ensure_ascii=False))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["provision", "start", "stop", "publish", "status", "renew"])
    args = parser.parse_args()
    try:
        if args.command == "stop":
            subprocess.run(["/bin/launchctl", "bootout", "gui/" + str(os.getuid()) + "/" + LABEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        setup = Setup()
        if args.command == "provision":
            setup.provision()
        elif args.command == "start":
            setup.service()
        elif args.command == "stop":
            setup.service(stop=True)
        elif args.command == "publish":
            setup.publish()
        elif args.command == "renew":
            setup.renew()
        else:
            setup.status()
    except Exception as exc:
        # Only our deliberately sanitized API/ownership errors are printable.
        print(str(exc) if isinstance(exc, RuntimeError) else "설정 단계가 실패했습니다. 비밀값은 출력하지 않았습니다.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
