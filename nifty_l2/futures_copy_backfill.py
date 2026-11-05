"""Optional copy-only historical futures normalization from archived calls.

Input DB is opened read-only. Output DB is a new SQLite backup with original
raw events preserved, supplemented by authenticated archived futures bars.
Never changes original production database or events.exchange_at_utc.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
from .futures_persistence import persist_futures

def backfill_copy(source, destination):
    source, destination = Path(source).expanduser().resolve(), Path(destination).expanduser().resolve()
    if source == destination or not source.is_file():
        raise ValueError("Distinct existing source and new output are required")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=20) as inp:
            out = sqlite3.connect(destination, timeout=20)
            try:
                inp.backup(out)
                out.execute("PRAGMA foreign_keys=ON")
                before = out.execute("SELECT count(*) FROM futures_data").fetchone()[0]
                count = 0
                examined = 0
                for eid, observed, raw in out.execute(
                    "SELECT event_id, observed_at_utc, payload_json FROM events "
                    "WHERE kind IN ('scheduled_research','manual_research') ORDER BY observed_at_utc"
                ):
                    examined += 1
                    try:
                        payload = json.loads(raw)
                        calls = payload.get("calls") if isinstance(payload, dict) else None
                        if isinstance(calls, list):
                            count += bool(persist_futures(out, eid, calls, observed))
                    except (ValueError, TypeError, OverflowError, KeyError):
                        continue
                out.commit()
                after = out.execute("SELECT count(*) FROM futures_data").fetchone()[0]
                if out.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Output database integrity failure")
                if out.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("Output database has foreign-key violations")
                return {"status":"COPY_CREATED","source_unchanged":True,
                        "events_examined":examined,"futures_before":before,
                        "futures_after":after,"new_futures_rows":after-before,
                        "normalized_candidate_events":count,
                        "event_exchange_timestamps_modified":False,
                        "output":str(destination)}
            finally:
                out.close()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args(argv)
    report=backfill_copy(args.source,args.output)
    print(json.dumps(report,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
