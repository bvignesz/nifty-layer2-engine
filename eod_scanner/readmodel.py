"""Read-only display of the unchanged EOD scanner's last exported CSV."""
import csv
from pathlib import Path

FIELDS=("Symbol","As_Of","Strategy_Track","Research_State","Actionability",
        "Close","RS_Excess_20D_Pct","Williams_R_3","Setup_POC",
        "VAL","VAH","Stop_Loss_Structural","Risk_Reward_Ratio","Data_Quality")

def results(directory,limit=100):
    """No history manipulation; only explicit dedicated EOD CSV, not live engine DB."""
    path=Path(directory)/"eod_scanner_results.csv"
    result={"status":"NO_DATA","rows":[],"source":"eod_scanner_results.csv",
            "provider":"FYERS_ADAPTER_UNVERIFIED",
            "note":"Results require independent OHLCV parity/adjustment checks."}
    if not path.is_file():return result
    if path.stat().st_size>25_000_000:
        return {**result,"status":"INVALID","note":"EOD CSV exceeds safe display limit"}
    with path.open(newline="",encoding="utf-8-sig") as file:
        reader=csv.DictReader(file)
        if not {"Symbol","Research_State","Strategy_Track"}.issubset(reader.fieldnames or []):
            return {**result,"status":"INVALID"}
        for index,row in enumerate(reader):
            if index>=limit:break
            result["rows"].append({k:row.get(k) for k in FIELDS})
    result["status"]="AVAILABLE" if result["rows"] else "NO_DATA"
    return result
