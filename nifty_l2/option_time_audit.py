"""Read-only inspection of FYERS option-chain time provenance.

This audits keys and candidate timestamp values already archived in the raw
FYERS responses. A matching key does NOT establish an exchange timestamp.
The script must never populate events.exchange_at_utc or invent candle time.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

# These are *candidates* only; schema/version semantics must be verified.
CANDIDATES = ("timestamp", "exchange_timestamp", "exchange_time",
              "exch_feed_time", "last_traded_time", "last_trade_time",
              "ltt", "tt", "t", "last_update_time", "last_updated_time")
SENSITIVE = {"access_token", "authorization", "app_id", "client_id"}

def _parse_epoch(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        x = float(value)
        if x > 1e12:
            x /= 1000
        try:
            d = datetime.fromtimestamp(x, timezone.utc)
            return d if 2020 <= d.year <= 2040 else None
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc) if dt.tzinfo else None
        except ValueError:
            return None
    return None

def inspect_option_timestamps(path, *, max_events=10000):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        return {"status":"FAIL", "reason":"Database not found"}
    report = {"status":"UNVERIFIED", "events_examined":0, "optionchain_calls":0,
              "option_legs":0, "candidate_fields":{}, "candidate_parseable":{},
              "candidate_future_dated":{}, "candidate_stale_over_180s":{},
              "events_with_any_parseable_candidate":0,
              "exchange_timestamp_verified":False,
              "production_db_modified":False,
              "notes":[
                "Candidate key names do not demonstrate exchange provenance.",
                "Event receipt time is not a completed option candle timestamp.",
                "No event.exchange_at_utc field is written or inferred."]}
    key_counts, good_counts, future_counts, stale_counts = (Counter() for _ in range(4))
    with sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, timeout=10) as con:
        con.execute("PRAGMA query_only=ON")
        cur = con.execute("""SELECT observed_at_utc,payload_json FROM events
            WHERE kind IN ('manual_research','scheduled_research')
            ORDER BY observed_at_utc LIMIT ?""", (int(max_events),))
        for receipt, raw in cur:
            report["events_examined"] += 1
            try:
                observed = datetime.fromisoformat(receipt.replace("Z","+00:00"))
                if observed.tzinfo is None:
                    continue
                observed = observed.astimezone(timezone.utc)
                payload = json.loads(raw)
                calls = payload.get("calls", [])
            except (TypeError, ValueError, AttributeError):
                continue
            if not isinstance(calls,list):
                continue
            per_event = False
            for call in calls:
                if not isinstance(call,dict) or call.get("method")!="optionchain":
                    continue
                report["optionchain_calls"] += 1
                response = call.get("response",{})
                data = response.get("data",{}) if isinstance(response,dict) else {}
                if not isinstance(data,dict):
                    continue
                legs = data.get("optionsChain",[])
                if not isinstance(legs,list):
                    continue
                for leg in legs:
                    if not isinstance(leg,dict) or leg.get("option_type") not in ("CE","PE"):
                        continue
                    report["option_legs"] += 1
                    for key, val in leg.items():
                        if not isinstance(key,str) or key.lower() in SENSITIVE:
                            continue
                        if key.lower() not in CANDIDATES:
                            continue
                        key_counts[key] += 1
                        parsed = _parse_epoch(val)
                        if parsed is None:
                            continue
                        good_counts[key] += 1
                        per_event = True
                        seconds = (observed - parsed).total_seconds()
                        if seconds < -5:
                            future_counts[key] += 1
                        elif seconds > 180:
                            stale_counts[key] += 1
            report["events_with_any_parseable_candidate"] += bool(per_event)
    for name, counts in (("candidate_fields",key_counts),("candidate_parseable",good_counts),
                         ("candidate_future_dated",future_counts),("candidate_stale_over_180s",stale_counts)):
        report[name] = dict(counts)
    return report

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",required=True,type=Path)
    p.add_argument("--report",type=Path)
    args = p.parse_args(argv)
    result = inspect_option_timestamps(args.db)
    output = json.dumps(result,indent=2,allow_nan=False)
    print(output)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        with args.report.open("x",encoding="utf-8") as f:
            f.write(output+"\n")
        args.report.chmod(0o600)
    return 0 if result["status"]!="FAIL" else 1

if __name__=="__main__":
    raise SystemExit(main())
