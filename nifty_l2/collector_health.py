"""Read-only collector health check for AWS systemd + SQLite.

Exit codes: 0 healthy, 1 warning (before first expected observation), 2 failure.
No broker credentials, no service restarts, no database writes.
"""
import argparse
from datetime import datetime, time, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc


def service_state(name):
    result = subprocess.run(
        ["systemctl", "is-active", name], capture_output=True, text=True,
        timeout=10, check=False)
    return result.stdout.strip() or result.stderr.strip() or "unknown"


def check(db, service="nifty-collector.service", now=None, max_age_minutes=9):
    now = now or datetime.now(UTC)
    local = now.astimezone(IST)
    state = service_state(service)
    report = {
        "checked_at_ist": local.isoformat(timespec="seconds"),
        "service": service, "service_state": state,
        "database": str(Path(db).expanduser()),
        "scheduled_today": 0, "latest_scheduled_ist": None,
        "latest_age_minutes": None, "status": "UNKNOWN", "reasons": [],
    }
    if state != "active":
        report["reasons"].append("Collector systemd service is not active")
    path = Path(db).expanduser().resolve()
    if not path.is_file():
        report["reasons"].append("Research database does not exist")
        report["status"] = "FAIL"
        return report
    start = datetime.combine(local.date(), time.min, IST).astimezone(UTC)
    end = start + timedelta(days=1)
    try:
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5) as conn:
            count, latest = conn.execute(
                """SELECT COUNT(*), MAX(observed_at_utc) FROM events
                   WHERE kind='scheduled_research'
                     AND observed_at_utc>=? AND observed_at_utc<?""",
                (start.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                 end.isoformat(timespec="microseconds").replace("+00:00", "Z")),
            ).fetchone()
            report["scheduled_today"] = count
            if latest:
                observed = datetime.fromisoformat(latest.replace("Z", "+00:00"))
                if observed.tzinfo is None:
                    raise ValueError("Stored observation timestamp lacks timezone")
                report["latest_scheduled_ist"] = observed.astimezone(IST).isoformat()
                report["latest_age_minutes"] = round((now-observed).total_seconds()/60, 1)
    except (sqlite3.Error, ValueError) as exc:
        report["reasons"].append("Cannot read valid scheduled event timestamps: " + str(exc))
        report["status"] = "FAIL"
        return report

    # Only require fresh collection after a short startup grace period in
    # ordinary weekday sessions; exchange holidays/special sessions need
    # calendar-aware interpretation.
    market_window = (local.weekday() < 5 and
                     time(9, 24) <= local.time() <= time(15, 30))
    if market_window and (report["latest_age_minutes"] is None or
                          report["latest_age_minutes"] > max_age_minutes or
                          report["latest_age_minutes"] < -1):
        report["reasons"].append("No recent scheduled event during regular weekday market window")
    if report["reasons"]:
        report["status"] = "FAIL" if state != "active" else "WARN"
    elif market_window:
        report["status"] = "OK"
    else:
        report["status"] = "WAITING_OUTSIDE_REGULAR_WINDOW"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="/home/ubuntu/.config/nifty-layer2/web-runtime/research.db")
    parser.add_argument("--service", default="nifty-collector.service")
    parser.add_argument("--max-age-minutes", type=int, default=9)
    args = parser.parse_args()
    report = check(args.db, args.service, max_age_minutes=args.max_age_minutes)
    print(json.dumps(report, indent=2))
    return 2 if report["status"] == "FAIL" else 1 if report["status"] == "WARN" else 0


if __name__ == "__main__":
    raise SystemExit(main())
