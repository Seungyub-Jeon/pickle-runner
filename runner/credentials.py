"""Local credential metadata only; never returns any credential value."""
import argparse
from datetime import datetime, timezone
import json

from cloudflare_token import STORE
from manage import RUNTIME


def expiry_status(expires_on):
    if not expires_on:
        return {"expires_on": None, "status": "unknown"}
    expires = datetime.fromisoformat(expires_on.replace("Z", "+00:00"))
    remaining = (expires - datetime.now(timezone.utc)).total_seconds()
    return {"expires_on": expires_on, "days_remaining": round(remaining / 86400, 2),
            "status": "expired" if remaining <= 0 else "expiring" if remaining <= 7*86400 else "valid"}


def local_status():
    path = RUNTIME / "credential-status.json"
    metadata = json.loads(path.read_text()) if path.exists() else {}
    return {"access_service_token": expiry_status(metadata.get("access_expires_on")),
            "checked_at": metadata.get("checked_at"),
            "setup_api_token_stored": (STORE / "api-token").exists(),
            "automatic_renewal": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["status", "forget-setup-token"])
    args = parser.parse_args()
    if args.command == "forget-setup-token":
        (STORE / "api-token").unlink(missing_ok=True)
        print("관리용 API 토큰의 로컬 사본을 삭제했습니다. 발행된 토큰 자체의 폐기는 Cloudflare에서 합니다.")
    else:
        print(json.dumps(local_status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
