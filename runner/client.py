#!/usr/bin/env python3
"""Client usable by Pickle. Tokens come from a private file, never CLI arguments."""
import argparse
import http.client
import ipaddress
import json
from pathlib import Path
import subprocess
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DNS_CACHE = {}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def doh_addresses(hostname):
    cached = DNS_CACHE.get(hostname)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    req = urllib.request.Request("https://1.1.1.1/dns-query?" + urllib.parse.urlencode({"name": hostname, "type": "A"}),
        headers={"Accept": "application/dns-json", "User-Agent": "pickle-runner-client/0.1"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(req, timeout=10) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError("DNS 응답 크기 초과")
    data = json.loads(raw)
    addresses = [item["data"] for item in data.get("Answer", [])
        if item.get("type") == 1 and ipaddress.ip_address(item["data"]).is_global]
    if data.get("Status") != 0 or not addresses:
        raise ValueError("공개 DNS에서 실행기 주소를 확인하지 못했습니다")
    DNS_CACHE[hostname] = (time.monotonic() + 60, addresses)
    return addresses


class ResolvedHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        # Override resolution only. Retain the original hostname for TLS SNI and verification.
        last = None
        for address in doh_addresses(self.host):
            try:
                self.sock = socket.create_connection((address, self.port), self.timeout, self.source_address)
                self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)
                return
            except OSError as exc:
                last = exc
                if self.sock:
                    self.sock.close()
        raise last or ValueError("DNS 주소로 연결하지 못했습니다")


class DoHHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(ResolvedHTTPSConnection, req, context=self._context)


def validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/") or not parsed.hostname:
        raise ValueError("API 주소에는 호스트와 포트만 넣으세요")
    local = parsed.hostname in ("127.0.0.1", "localhost")
    if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
        raise ValueError("로컬을 제외한 주소에는 HTTPS가 필요합니다")


def encrypted_config(ciphertext, private_key):
    """Decrypt directly into memory; never persist or print plaintext settings."""
    key = Path(private_key)
    if key.stat().st_mode & 0o077:
        raise ValueError("개인키 파일은 본인만 접근할 수 있어야 합니다 (chmod 600)")
    result = subprocess.run(["openssl", "pkeyutl", "-decrypt", "-inkey", str(key), "-passin", "pass:",
        "-in", str(ciphertext), "-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256",
        "-pkeyopt", "rsa_mgf1_md:sha256"], capture_output=True, timeout=10)
    if result.returncode or len(result.stdout) > 8192:
        raise ValueError("암호화된 연결 설정을 열지 못했습니다")
    value = json.loads(result.stdout)
    validate_url(value["url"])
    return value


def request(config, method, path, body=None, auth="full"):
    validate_url(config["url"])
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "pickle-runner-client/0.1"}
    if auth in ("full", "agent"):
        headers["Authorization"] = "Bearer " + config["token"]
    if auth in ("full", "access") and config.get("access_client_id"):
        headers["CF-Access-Client-Id"] = config["access_client_id"]
        headers["CF-Access-Client-Secret"] = config["access_client_secret"]
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(config["url"].rstrip("/") + path, data=data, headers=headers, method=method)
    # Explicitly ignore shell proxy settings and never follow a redirect with credentials.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(req, timeout=15)
    except urllib.error.HTTPError as exc:
        response = exc
    except urllib.error.URLError as exc:
        if not config.get("dns_over_https") or not isinstance(exc.reason, socket.gaierror) or urllib.parse.urlsplit(config["url"]).scheme != "https":
            raise
        fallback = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), DoHHTTPSHandler())
        try:
            response = fallback.open(req, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
    with response:
        raw = response.read(512 * 1024 + 1)
        if len(raw) > 512 * 1024:
            raise ValueError("응답 크기 한도를 넘었습니다")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            value = {"error": {"code": "non_json_response"}}
        if not isinstance(value, dict):
            raise ValueError("응답은 JSON 객체여야 합니다")
        if response.code in (401, 403):
            runner_codes = {"unauthorized", "browser_denied", "action_denied", "task_denied", "path_denied", "file_type_denied"}
            value["auth_layer"] = "runner" if value.get("error", {}).get("code") in runner_codes else "cloudflare_or_upstream"
        return response.code, value


def wait(config, job_id, seconds=130):
    deadline = time.monotonic() + seconds
    path = "/v1/jobs/" + job_id
    body = {"job": {"id": job_id, "state": "unknown"}}
    while True:
        try:
            code, latest = request(config, "GET", path)
        except (ValueError, OSError, urllib.error.URLError):
            return 202, {**body, "poll": path, "pending": True, "poll_error": "connection_failed"}
        if code != 200:
            return code, {**latest, "job": body["job"], "poll": path}
        body = latest
        if code != 200 or body["job"]["state"] in ("succeeded", "failed", "interrupted"):
            return code, body
        if time.monotonic() >= deadline:
            return 202, {**body, "poll": path, "pending": True, "waiting_timed_out": True}
        time.sleep(min(.25, max(0, deadline - time.monotonic())))


def exit_status(code, body):
    job = body.get("job", {})
    if code >= 400 or job.get("state") in ("failed", "interrupted"):
        return 1
    if job.get("archived"):
        return 3
    if body.get("pending") or (job and job.get("state") not in ("succeeded", "failed", "interrupted")):
        return 2
    return 0


def main():
    parser = argparse.ArgumentParser()
    default = Path(__file__).resolve().parent.parent / ".runtime" / "pickle-runner" / "client-local.json"
    parser.add_argument("--config", default=str(default))
    parser.add_argument("--encrypted-config", help="RSA-OAEP(SHA-256) 암호화된 연결 설정 파일")
    parser.add_argument("--private-key", help="원격 에이전트 환경에만 보관한 RSA 개인키")
    parser.add_argument("command", choices=["health", "capabilities", "state", "events", "submit", "get", "cancel"])
    parser.add_argument("--body-file", help="request_id, action, args가 든 JSON 파일")
    parser.add_argument("--action")
    parser.add_argument("--args", default="{}")
    parser.add_argument("--request-id")
    parser.add_argument("--job-id")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--wait-seconds", type=float, default=130)
    parser.add_argument("--since", type=int, default=0, help="events의 마지막 처리 커서")
    parser.add_argument("--limit", type=int, default=50, help="events 페이지 크기 (1~100)")
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 3600:
        parser.error("--wait-seconds must be between 0 and 3600")
    try:
        if args.encrypted_config:
            if not args.private_key:
                parser.error("--encrypted-config에는 --private-key가 필요합니다")
            config = encrypted_config(args.encrypted_config, args.private_key)
        else:
            config = json.loads(Path(args.config).read_text())
        if args.command == "state":
            code, body = request(config, "GET", "/v1/state")
        elif args.command == "cancel":
            import re
            if not args.job_id or not re.fullmatch(r"[0-9a-f]{32}", args.job_id):
                parser.error("cancel에는 올바른 --job-id가 필요합니다")
            code, body = request(config, "POST", "/v1/jobs/" + args.job_id + "/cancel", {})
            if args.wait and code < 400:
                code, body = wait(config, args.job_id, args.wait_seconds)
        elif args.command == "events":
            code, body = request(config, "GET", "/v1/events?" + urllib.parse.urlencode({"since": args.since, "limit": args.limit}))
        elif args.command in ("health", "capabilities"):
            code, body = request(config, "GET", "/health" if args.command == "health" else "/v1/capabilities")
        elif args.command == "get":
            if not args.job_id:
                parser.error("--job-id is required")
            code, body = request(config, "GET", "/v1/jobs/" + args.job_id)
        else:
            if args.body_file:
                payload = json.loads(Path(args.body_file).read_text())
            else:
                if not args.action or not args.request_id:
                    parser.error("--body-file or both --action and --request-id are required")
                payload = {"request_id": args.request_id, "action": args.action, "args": json.loads(args.args)}
            code, body = request(config, "POST", "/v1/jobs", payload)
            if code in (200, 202):
                receipt = {"job_id": body["job"]["id"], "request_id": body["job"]["request_id"], "poll": body["poll"], "reused": body["reused"]}
                print(json.dumps({"accepted": receipt}, ensure_ascii=False), file=sys.stderr, flush=True)
                if args.wait:
                    code, body = wait(config, receipt["job_id"], args.wait_seconds)
                    body["accepted"] = receipt
        print(json.dumps({"http_status": code, **body}, ensure_ascii=False, indent=2))
        raise SystemExit(exit_status(code, body))
    except (ValueError, KeyError, OSError, subprocess.TimeoutExpired, urllib.error.URLError):
        parser.exit(1, "연결 또는 입력 오류입니다. 설정 파일·주소·인증 상태를 확인하세요. 비밀값은 출력하지 않았습니다.\n")


if __name__ == "__main__":
    main()
