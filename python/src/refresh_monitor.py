"""Summarise analytics refresh health and record the last successful refresh."""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any

import duckdb


def inspect_database(database: str | Path) -> dict[str, Any]:
    path = Path(database)
    if not path.exists():
        raise FileNotFoundError(f"Analytics database not found at {path}")
    con = duckdb.connect(str(path), read_only=True)
    try:
        con.execute("SET TimeZone='UTC'")
        conversations, latest = con.execute(
            "SELECT COUNT(*), max(arrived_at_utc) FROM conversations").fetchone()
        checks = con.execute("SELECT metric, status FROM data_reconciliation").fetchall()
    finally:
        con.close()
    return {
        "conversations": int(conversations),
        "latest_arrived_at_utc": latest.isoformat() if latest is not None else None,
        "reconciliation_checks": len(checks),
        "failed_checks": sorted(metric for metric, status in checks if status != "PASS"),
    }


def build_state(info: dict[str, Any], *, profile: str, run_id: str,
                previous: dict[str, Any] | None = None, now: datetime.datetime | None = None) -> dict[str, Any]:
    healthy = (info["reconciliation_checks"] > 0 and not info["failed_checks"]
               and info["conversations"] > 0 and info["latest_arrived_at_utc"] is not None)
    current = now or datetime.datetime.now(datetime.UTC)
    carried = (previous or {}).get("last_successful_refresh_utc")
    return {
        "profile": profile,
        "run_id": run_id,
        "checked_at_utc": current.isoformat(timespec="seconds"),
        "healthy": healthy,
        "last_successful_refresh_utc": current.isoformat(timespec="seconds") if healthy else carried,
        "carried_previous_success": healthy is False and carried is not None,
        **{key: value for key, value in info.items()},
    }


def markdown(state: dict[str, Any]) -> str:
    lines = ["## Analytics refresh",
             "",
             f"- profile: `{state['profile']}`",
             f"- conversations: `{state['conversations']}`",
             f"- latest conversation timestamp: `{state['latest_arrived_at_utc'] or 'none'}`",
             f"- reconciliation checks: `{state['reconciliation_checks']}`",
             f"- status: `{'PASS' if state['healthy'] else 'FAIL'}`",
             f"- last successful refresh: `{state['last_successful_refresh_utc'] or 'never recorded'}`"]
    if state["failed_checks"]:
        lines += ["", "**Failed reconciliation metrics:** " + ", ".join(f"`{name}`" for name in state["failed_checks"])]
    return "\n".join(lines) + "\n"


def append_summary(text: str) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Record analytics refresh health for monitoring")
    parser.add_argument("--database", default="outputs/commerce_analytics.duckdb")
    parser.add_argument("--state", default="outputs/refresh_state.json")
    parser.add_argument("--profile", default=os.getenv("REFRESH_PROFILE", "unknown"))
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", "local"))
    args = parser.parse_args(argv)
    state_path = Path(args.state)
    previous = None
    if state_path.exists():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            previous = None
    previous = previous if isinstance(previous, dict) else None
    try:
        state = build_state(inspect_database(args.database), profile=args.profile,
                            run_id=args.run_id, previous=previous)
    except (FileNotFoundError, duckdb.Error, RuntimeError) as error:
        state = {"profile": args.profile, "run_id": args.run_id, "healthy": False,
                 "conversations": 0, "latest_arrived_at_utc": None, "reconciliation_checks": 0,
                 "failed_checks": [], "error": str(error),
                 "checked_at_utc": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
                 "last_successful_refresh_utc": (previous or {}).get("last_successful_refresh_utc")}
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        append_summary(f"## Analytics refresh\n\n`{error}`\n")
        print(f"REFRESH CHECK FAILED: {error}", file=sys.stderr)
        return 1
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    append_summary(markdown(state))
    print(json.dumps(state, indent=2))
    return 0 if state["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
