#!/usr/bin/env python3
"""Local-only configuration and user LaunchAgent management. Never prints tokens."""
import argparse
import getpass
import json
import os
from pathlib import Path
import plistlib
import secrets
import subprocess
import socket
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / ".runtime" / "pickle-runner"
LABEL = "io.picklerunner.agent"
PLIST = Path.home() / "Library" / "LaunchAgents" / (LABEL + ".plist")


def private_json(path, value):
    temp = path.with_name("." + path.name + "." + secrets.token_hex(8))
    try:
        fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def initialize(port):
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(RUNTIME, 0o700)
    workspace = ROOT / "workspace"
    workspace.mkdir(exist_ok=True, mode=0o700)
    if workspace.is_symlink():
        raise SystemExit("workspace must not be a symlink")
    if (RUNTIME / "config.json").exists():
        print("이미 설정돼 있습니다. 기존 설정과 비밀값을 보존합니다.")
        return
    token = secrets.token_urlsafe(48)
    fd = os.open(str(RUNTIME / "agent-token"), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(token + "\n")
    private_json(RUNTIME / "config.json", {"port": port, "workspace": str(workspace), "terminal_enabled": True, "tasks": {
        "system.uptime": {"description": "맥 가동 시간과 부하 확인", "argv": ["/usr/bin/uptime"], "cwd": str(workspace), "timeout_sec": 10},
        "system.disk": {"description": "작업 폴더가 있는 디스크의 남은 공간", "argv": ["/bin/df", "-h", str(workspace)], "cwd": str(workspace), "timeout_sec": 10},
        "python.version": {"description": "실행기에 쓰는 Python 버전", "argv": [sys.executable, "--version"], "cwd": str(workspace), "timeout_sec": 10}}})
    private_json(RUNTIME / "client-local.json", {"url": "http://127.0.0.1:" + str(port), "token": token})
    print("로컬 설정 완료. 비밀값은 .runtime/pickle-runner 안에만 저장했습니다.")


def service(action):
    domain = "gui/" + str(os.getuid())
    target = domain + "/" + LABEL
    if action == "install":
        if not (RUNTIME / "config.json").exists():
            raise SystemExit("먼저 init을 실행하세요")
        if PLIST.exists():
            existing = plistlib.loads(PLIST.read_bytes())
            if existing.get("ProgramArguments") != [sys.executable, str(ROOT / "runner" / "agent.py"), "--runtime", str(RUNTIME)]:
                raise SystemExit("같은 이름의 다른 서비스가 있습니다. 덮어쓰지 않았습니다.")
        loaded = subprocess.run(["/bin/launchctl", "print", target], capture_output=True).returncode == 0
        if not loaded:
            port = json.loads((RUNTIME / "config.json").read_text())["port"]
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", port))
                except OSError:
                    raise SystemExit("설정 포트가 이미 사용 중입니다. 기존 서비스를 중지하거나 덮어쓰지 않았습니다.")
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        data = {"Label": LABEL, "ProgramArguments": [sys.executable, str(ROOT / "runner" / "agent.py"), "--runtime", str(RUNTIME)],
                "WorkingDirectory": str(ROOT), "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10,
                "Umask": 0o077, "StandardOutPath": str(RUNTIME / "launchd.out.log"), "StandardErrorPath": str(RUNTIME / "launchd.err.log")}
        PLIST.write_bytes(plistlib.dumps(data))
        os.chmod(PLIST, 0o600)
        loaded = subprocess.run(["/bin/launchctl", "print", target], capture_output=True).returncode == 0
        if loaded:
            subprocess.run(["/bin/launchctl", "kickstart", "-k", target], check=True)
        else:
            subprocess.run(["/bin/launchctl", "bootstrap", domain, str(PLIST)], check=True)
        from client import request
        config = json.loads((RUNTIME / "client-local.json").read_text())
        ready = False
        for unused in range(100):
            try:
                if request(config, "GET", "/health")[0] == 200:
                    ready = True
                    break
            except OSError:
                pass
            time.sleep(0.1)
        if not ready:
            raise SystemExit("서비스를 등록했으나 로컬 health 응답을 확인하지 못했습니다")
        print("사용자 서비스 등록 완료:", LABEL, "(127.0.0.1 전용)")
    elif action == "stop":
        result = subprocess.run(["/bin/launchctl", "bootout", target], capture_output=True)
        if result.returncode:
            check = subprocess.run(["/bin/launchctl", "print", target], capture_output=True)
            if check.returncode == 0:
                raise SystemExit("서비스 중지에 실패했습니다")
        print("사용자 서비스 중지 완료")
    elif action == "uninstall":
        service("stop")
        if PLIST.exists():
            PLIST.unlink()
        print("자동 시작 등록 해제. 작업 파일·기록·비밀값은 보존했습니다.")
    elif action == "status":
        result = subprocess.run(["/bin/launchctl", "print", target], capture_output=True, text=True)
        print("등록됨" if result.returncode == 0 else "가동되지 않음")
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.strip().startswith(("state =", "pid =", "last exit code =")):
                    print(line.strip())


def remote_config(url):
    from client import validate_url
    validate_url(url)
    if not url.startswith("https://"):
        raise SystemExit("원격 주소에는 HTTPS가 필요합니다")
    client_id = getpass.getpass("Cloudflare Access Client ID (화면에 표시하지 않음): ").strip()
    client_secret = getpass.getpass("Cloudflare Access Client Secret (화면에 표시하지 않음): ").strip()
    if not client_id or not client_secret:
        raise SystemExit("Access 값 두 개가 필요합니다")
    token = (RUNTIME / "agent-token").read_text().strip()
    private_json(RUNTIME / "client-remote.json", {"url": url.rstrip("/"), "token": token, "access_client_id": client_id, "access_client_secret": client_secret})
    print("원격 클라이언트 설정 저장 완료. 비밀값을 표시하거나 전송하지 않았습니다.")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "install", "status", "stop", "uninstall", "remote-config"])
    parser.add_argument("--port", type=int, default=8796)
    parser.add_argument("--url")
    args = parser.parse_args()
    if args.command == "init":
        if not 1024 <= args.port <= 65535:
            parser.error("port must be 1024..65535")
        initialize(args.port)
    elif args.command == "remote-config":
        if not args.url:
            parser.error("--url is required")
        remote_config(args.url)
    else:
        service(args.command)


if __name__ == "__main__":
    main()
