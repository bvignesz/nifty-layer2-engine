import csv
import json
from datetime import datetime
import pandas as pd
import pytest

from eod_scanner.fyers_bridge import FyersDownloadShim,load_credentials_and_map
from eod_scanner.readmodel import results
from nifty_l2 import fyers

def test_eod_shim_preserves_yahoo_dataframe_contract(monkeypatch):
    calls=[]
    ts=int(datetime.fromisoformat("2026-10-20T09:15:00+05:30").timestamp())
    def fake_request(op,*,params,credentials):
        calls.append((op,params,credentials))
        return {"s":"ok","candles":[[ts,100,105,99,104,20000]]}
    monkeypatch.setattr(fyers,"request",fake_request)
    shim=FyersDownloadShim({"client_id":"TEST","access_token":"OFFLINE"},
                           {"TCS.NS":"NSE:TCS-EQ","RELIANCE.NS":"NSE:RELIANCE-EQ"})
    out=shim.download(["TCS.NS","RELIANCE.NS"],period="60d",interval="15m",auto_adjust=True)
    assert isinstance(out.columns,pd.MultiIndex)
    assert "TCS.NS" in out.columns.get_level_values(0)
    assert out["TCS.NS"]["Close"].iloc[0]==104
    assert len(calls)==2
    with pytest.raises(ValueError,match="mapping"):
        shim.download("UNKNOWN.NS",period="60d",interval="15m",auto_adjust=True)

def test_credentials_and_mapping_must_be_explicit_and_private(tmp_path):
    token=tmp_path/"token.json"
    mapping=tmp_path/"map.json"
    token.write_text(json.dumps({"client_id":"TEST","access_token":"FAKE"}))
    mapping.write_text(json.dumps({"TCS.NS":"NSE:TCS-EQ"}))
    token.chmod(0o600)
    creds,symbols=load_credentials_and_map(token,mapping)
    assert creds["client_id"]=="TEST" and symbols["TCS.NS"]=="NSE:TCS-EQ"
    token.chmod(0o644)
    with pytest.raises(ValueError,match="permissions"):
        load_credentials_and_map(token,mapping)

def test_eod_csv_view_requires_actual_saved_output(tmp_path):
    assert results(tmp_path)["status"]=="NO_DATA"
    path=tmp_path/"eod_scanner_results.csv"
    with path.open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=[
            "Symbol","As_Of","Research_State","Strategy_Track","Actionability"])
        writer.writeheader()
        writer.writerow({"Symbol":"KIRLOSENG","As_Of":"2026-11-05",
            "Research_State":"PULLBACK_AT_POC","Strategy_Track":"TRACK_A_POC_PULLBACK",
            "Actionability":"RESEARCH_ONLY"})
    actual=results(tmp_path)
    assert actual["status"]=="AVAILABLE"
    assert actual["rows"][0]["Symbol"]=="KIRLOSENG"

def test_frozen_eod_v070_source_hash():
    from pathlib import Path
    import hashlib
    path=Path(__file__).resolve().parents[1]/"eod_scanner"/"frozen"/"nifty500_rs_wpr_poc_screener_v0_7_0.py"
    raw=path.read_bytes()
    blob=hashlib.sha1(b"blob "+str(len(raw)).encode()+bytes([0])+raw).hexdigest()
    assert blob=="f10218d50af88da622fa84783926c5962e297c7b", (
        "Frozen EOD strategy v0.7.0 changed; review before revising reference baseline")
