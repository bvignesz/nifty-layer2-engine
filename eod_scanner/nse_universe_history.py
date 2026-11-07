"""NIFTY500 *point-in-time* membership importer from dated NSE Indices CSVs.

NSE's current constituent download is not historical membership evidence.
Import actual dated snapshots only. This has no web scraping or broker calls.
Store provenance and refuse to backfill dates before the first real snapshot.
"""
from datetime import date
import csv,hashlib,io,json,sqlite3
from pathlib import Path

DDL="""CREATE TABLE IF NOT EXISTS universe_sources(
 as_of TEXT PRIMARY KEY,sha256 TEXT UNIQUE NOT NULL,
 file_name TEXT NOT NULL,source_name TEXT NOT NULL,
 imported_rows INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS universe_members(
 as_of TEXT NOT NULL,symbol TEXT NOT NULL,
 industry TEXT,source_sha256 TEXT NOT NULL,
 PRIMARY KEY(as_of,symbol),
 FOREIGN KEY(as_of) REFERENCES universe_sources(as_of)
);
CREATE INDEX IF NOT EXISTS universe_asof_symbol ON universe_members(symbol,as_of);
"""

def parse_constituents_csv(content,*,as_of,source_name):
    d=date.fromisoformat(as_of)
    if not isinstance(content,bytes) or not content:
        raise ValueError("CSV file bytes required")
    if source_name!="NSE_INDICES_DATED_CONSTITUENTS":
        raise ValueError("Only explicit source identity allowed")
    text=content.decode("utf-8-sig")
    rows=list(csv.DictReader(io.StringIO(text)))
    if not rows or "Symbol" not in rows[0]:
        raise ValueError("Expected NSE constituent Symbol field")
    seen=set()
    output=[]
    for row in rows:
        symbol=(row.get("Symbol") or "").strip().upper()
        if not symbol or not symbol.replace("&","").replace("-","").replace(".","").isalnum():
            raise ValueError("invalid constituent symbol")
        if symbol in seen:raise ValueError("duplicate constituent")
        seen.add(symbol)
        output.append({"symbol":symbol,"industry":(row.get("Industry") or "").strip()[:100]})
    if not 1<=len(output)<=600:
        raise ValueError("unsupported universe size")
    return {"as_of":d.isoformat(),"symbols":output,
        "sha256":hashlib.sha256(content).hexdigest(),"source_name":source_name,
        "note":"Actual constituent publication/effective date must be verified by operator, not inferred from filename."}

def import_snapshot(db_path,csv_path,*,as_of,source_name="NSE_INDICES_DATED_CONSTITUENTS"):
    p=Path(db_path).expanduser().resolve()
    if p.name!="universe_history.db":
        raise ValueError("separate universe_history.db required")
    csv_path=Path(csv_path).expanduser().resolve()
    info=parse_constituents_csv(csv_path.read_bytes(),as_of=as_of,source_name=source_name)
    p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with sqlite3.connect(p) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(DDL)
        conn.execute("INSERT INTO universe_sources VALUES(?,?,?,?,?)",
             (info["as_of"],info["sha256"],csv_path.name,source_name,len(info["symbols"])))
        conn.executemany("INSERT INTO universe_members VALUES(?,?,?,?)",
          [(info["as_of"],r["symbol"],r["industry"],info["sha256"])
           for r in info["symbols"]])
    p.chmod(0o600)
    return {"status":"IMPORTED","as_of":as_of,"member_count":len(info["symbols"]),
        "sha256":info["sha256"],"source":source_name}

def members_asof(db_path,day):
    requested=date.fromisoformat(day)
    p=Path(db_path).expanduser().resolve()
    if p.name!="universe_history.db" or not p.is_file():
        return {"status":"NO_UNIVERSE_HISTORY","members":[]}
    with sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True) as conn:
        row=conn.execute("SELECT as_of,sha256 FROM universe_sources WHERE as_of<=? ORDER BY as_of DESC LIMIT 1",
            (requested.isoformat(),)).fetchone()
        if row is None:
            return {"status":"NO_POINT_IN_TIME_MEMBERSHIP","members":[]}
        matches=[r[0] for r in conn.execute(
          "SELECT symbol FROM universe_members WHERE as_of=? ORDER BY symbol",(row[0],))]
    return {"status":"IMPORTED_ASOF_SNAPSHOT","members":matches,
      "effective_as_of":row[0],"source_sha256":row[1],
      "note":"The latest dated snapshot on or before the target date. No inferred historical constituent changes."}
