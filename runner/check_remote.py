#!/usr/bin/env python3
"""Read-only authentication matrix. Agent's own 401 is not proof of Access."""
import argparse
import json
from pathlib import Path
from client import request, validate_url


def check(config):
    validate_url(config["url"])
    if not config["url"].startswith("https://") or not all(config.get(k) for k in ("token", "access_client_id", "access_client_secret")):
        raise ValueError("HTTPS 주소와 두 인증 계층의 값이 필요합니다")
    results = {}
    for name, mode in [("no_credentials", "none"), ("agent_only", "agent"), ("access_only", "access"), ("both", "full")]:
        status, body = request(config, "GET", "/health", auth=mode)
        origin = body.get("service") == "pickle-runner" or body.get("error", {}).get("code") == "unauthorized"
        if name in ("no_credentials", "agent_only"):
            passed = status in (302, 303, 401, 403) and not origin
        elif name == "access_only":
            passed = status == 401 and body.get("error", {}).get("code") == "unauthorized"
        else:
            passed = status == 200 and body.get("service") == "pickle-runner" and body.get("status") == "ok"
        results[name] = {"status": status, "origin_response": origin, "passed": passed}
    return {"passed": all(item["passed"] for item in results.values()), "checks": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        result = check(json.loads(Path(args.config).read_text()))
    except Exception:
        parser.exit(1, "외부 연결을 확인하지 못했습니다. 설정·DNS·Access를 확인하세요. 비밀값은 출력하지 않았습니다.\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
