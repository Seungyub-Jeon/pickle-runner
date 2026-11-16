#!/usr/bin/env python3
"""Save a setup-only CF API token via hidden TTY input. Read-only validation."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import subprocess
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / ".runtime" / "cloudflare-setup"
settings_file = STORE / "settings.json"
SETTINGS = json.loads(settings_file.read_text()) if settings_file.exists() else {}
ZONE = SETTINGS.get("zone", "")
HOST = SETTINGS.get("hostname", "")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api(token, path):
    req = urllib.request.Request("https://api.cloudflare.com/client/v4" + path,
                                 headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=20) as response:
            raw = response.read(1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError("Cloudflare 인증·권한 확인 실패 (HTTP %d)" % exc.code) from None
    except OSError:
        raise ValueError("Cloudflare 연결 실패. 네트워크를 확인하세요") from None
    if len(raw) > 1024 * 1024:
        raise ValueError("Cloudflare 응답 크기 초과")
    payload = json.loads(raw)
    if not payload.get("success"):
        raise ValueError("Cloudflare가 요청을 거절했습니다. 토큰 권한과 만료를 확인하세요")
    return payload["result"]


def validate(token):
    if not ZONE or not HOST:
        raise ValueError("먼저 setup.py cloudflare --zone DOMAIN --hostname HOST를 실행하세요")
    if api(token, "/user/tokens/verify").get("status") != "active":
        raise ValueError("활성 API 토큰이 아닙니다")
    zones = api(token, "/zones?" + urllib.parse.urlencode({"name": ZONE, "status": "active", "per_page": 50}))
    matches = [zone for zone in zones if zone.get("name") == ZONE]
    if len(matches) != 1:
        raise ValueError(ZONE + " 영역을 조회할 수 없습니다. Zone Read와 리소스 범위를 확인하세요")
    zone = matches[0]
    return {"hostname": HOST, "zone_name": ZONE, "zone_id": zone["id"], "account_id": zone["account"]["id"],
            "target_origin": "http://127.0.0.1:" + str(SETTINGS.get("port", 8796)), "preserve_hostnames": SETTINGS.get("preserve_hostnames", [])}


def save(token, plan):
    STORE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if STORE.is_symlink():
        raise ValueError("저장 폴더는 심볼릭 링크일 수 없습니다")
    os.chmod(STORE, 0o700)
    for name, value in [("api-token", token + "\n"), ("plan.json", json.dumps(plan, ensure_ascii=False, indent=2) + "\n")]:
        fd = os.open(str(STORE / name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(value)
            os.fchmod(stream.fileno(), 0o600)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="관리용 CF API 토큰의 숨김 입력·로컬 저장·읽기 전용 확인")
    parser.add_argument("command", choices=["save", "prompt", "status"])
    args = parser.parse_args()
    try:
        if args.command in ("save", "prompt"):
            if args.command == "prompt":
                script = '''text returned of (display dialog "Cloudflare에서 발행한 관리용 API 토큰을 붙여넣으세요.\n\n토큰은 이 맥의 비공개 설정에 저장합니다. 채팅·메일로 보내지 않습니다." default answer "" with hidden answer buttons {"취소", "저장"} default button "저장" with title "피클 실행기 — 토큰 등록")'''
                result = subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, text=True)
                if result.returncode:
                    print("토큰 입력을 취소했습니다. 저장하지 않았습니다.")
                    return
                token = result.stdout.strip()
            else:
                if not sys.stdin.isatty():
                    raise ValueError("본인 맥의 터미널에서 실행하세요. 토큰을 명령 인자나 채팅에 넣지 않습니다")
                token = getpass.getpass("Cloudflare 관리용 API 토큰 (붙여넣어도 화면에 표시되지 않음): ").strip()
            if not token or any(ch.isspace() for ch in token):
                raise ValueError("API 토큰 형식이 올바르지 않습니다")
            plan = validate(token)
            save(token, plan)
            print("토큰 저장 완료. 활성 상태와 " + ZONE + " 조회를 확인했습니다.")
        else:
            token = (STORE / "api-token").read_text().strip()
            validate(token)
            print("관리용 API 토큰 활성, " + ZONE + " 조회 가능")
        print("설정 예정 주소: https://" + HOST)
        print("이 명령은 Cloudflare 설정을 변경하거나 원격 에이전트에게 토큰을 보내지 않습니다.")
    except (ValueError, OSError, KeyboardInterrupt) as exc:
        # Do not print exception text from urllib or JSON responses, which may carry request data.
        if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError):
            print(str(exc), file=sys.stderr)
        else:
            print("저장·확인을 완료하지 못했습니다. 비밀값은 출력하지 않았습니다.", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
