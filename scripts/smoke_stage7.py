from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta

import requests


def _admin_headers(token: str | None) -> dict[str, str]:
    if not token:
        return {}
    return {"X-Admin-Token": token}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage-7 smoke test: POST /api/ai/plan (fast) and verify /admin/plan/summary changes.",
    )
    parser.add_argument("--base-url", default=os.getenv("BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--admin-token", default=os.getenv("ADMIN_API_TOKEN"))
    parser.add_argument("--user-id", type=int, default=int(os.getenv("SMOKE_USER_ID", "1")))
    parser.add_argument("--destination", default=os.getenv("SMOKE_DESTINATION", "广州"))
    parser.add_argument("--days", type=int, default=int(os.getenv("SMOKE_DAYS", "2")))
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    start = date.today()
    end = start + timedelta(days=max(args.days, 1) - 1)
    payload = {
        "user_id": args.user_id,
        "destination": args.destination,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "mode": "fast",
        "save": False,
        "seed": 7,
        "preferences": {"interests": ["food", "sight"], "pace": "normal"},
    }

    if args.admin_token:
        before = requests.get(
            f"{base_url}/admin/plan/summary",
            headers=_admin_headers(args.admin_token),
            timeout=10,
        )
        if before.status_code != 200:
            raise SystemExit(f"admin summary failed: {before.status_code} {before.text}")
        before_calls = int(before.json()["data"].get("plan_fast_calls") or 0)
    else:
        before_calls = None

    resp = requests.post(f"{base_url}/api/ai/plan", json=payload, timeout=30)
    if resp.status_code != 200:
        raise SystemExit(f"plan failed: {resp.status_code} {resp.text}")
    data = resp.json().get("data") or {}
    plan = data.get("plan") or {}
    assert plan.get("day_count") == max(args.days, 1)
    assert len(plan.get("day_cards") or []) == max(args.days, 1)
    assert isinstance(data.get("trace_id"), str)

    if args.admin_token and before_calls is not None:
        after = requests.get(
            f"{base_url}/admin/plan/summary",
            headers=_admin_headers(args.admin_token),
            timeout=10,
        )
        if after.status_code != 200:
            raise SystemExit(f"admin summary failed: {after.status_code} {after.text}")
        after_calls = int(after.json()["data"].get("plan_fast_calls") or 0)
        if after_calls < before_calls + 1:
            raise SystemExit(
                f"metric not increased: before={before_calls} after={after_calls}"
            )

    print("OK: Stage-7 smoke passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

