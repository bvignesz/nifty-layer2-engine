"""Opt-in FYERS-to-Yahoo dataframe compatibility adapter for frozen EOD code.

The archived v0.7.0 strategy is imported UNCHANGED. Requires an explicit
reviewed symbol JSON map; no Yahoo network, guessed symbol IDs or live orders.
Corporate-action adjustment is NOT provided; no backtest parity is claimed.
"""
from datetime import datetime,timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd

from nifty_l2 import fyers
from nifty_l2.eod_fyers_adapter import validate_symbol,normalize_ohlcv

IST=ZoneInfo("Asia/Kolkata")
class FyersDownloadShim:
    def __init__(self,credentials,symbol_map):
        self.credentials=credentials
        self.symbol_map=dict(symbol_map)
        self.calls=0

    def _frame(self,ticker,period,interval):
        if ticker not in self.symbol_map:
            raise ValueError("No approved FYERS symbol mapping for "+str(ticker))
        symbol=validate_symbol(self.symbol_map[ticker])
        now=datetime.now(IST)
        days=400 if period.endswith("y") else 90 if period.endswith("d") else None
        if period.endswith("d"):
            try:days=int(period[:-1])+7
            except ValueError:raise ValueError("Invalid period")
        if days is None:raise ValueError("Unsupported history period")
        resolution="D" if interval=="1d" else "15" if interval=="15m" else None
        if resolution is None:raise ValueError("Unsupported interval")
        params={"symbol":symbol,"resolution":resolution,"date_format":"1",
                "range_from":(now.date()-timedelta(days=days)).isoformat(),
                "range_to":now.date().isoformat(),"cont_flag":"1"}
        response=fyers.request("history",params=params,credentials=self.credentials)
        self.calls+=1
        rows=normalize_ohlcv(response,resolution,now)
        if not rows:return pd.DataFrame()
        idx=pd.DatetimeIndex([r["start_utc"] for r in rows])
        if resolution=="D":
            idx=idx.tz_convert(IST).tz_localize(None).normalize()
        else:idx=idx.tz_convert(IST)
        frame=pd.DataFrame([{k:r[k] for k in ("open","high","low","close","volume")} for r in rows],index=idx)
        frame.columns=["Open","High","Low","Close","Volume"]
        return frame[~frame.index.duplicated(keep="last")].sort_index()

    def download(self,tickers,*,period,interval,**kwargs):
        if kwargs.get("auto_adjust") is not True:
            raise ValueError("Expected scanner compatibility mode")
        items=[tickers] if isinstance(tickers,str) else list(tickers)
        if not items:raise ValueError("No symbols")
        # A missing contract must FAIL, never fabricate a zero OHLCV series.
        frames={ticker:self._frame(ticker,period,interval) for ticker in items}
        if len(items)==1:return frames[items[0]]
        return pd.concat(frames,axis=1)

def load_credentials_and_map(token_path,mapping_path):
    token=Path(token_path).expanduser()
    mapping=Path(mapping_path).expanduser()
    if token.stat().st_mode & 0o077:raise ValueError("FYERS token permissions unsafe")
    with token.open(encoding="utf-8") as handle:credentials=json.load(handle)
    if not credentials.get("client_id") or not credentials.get("access_token"):
        raise ValueError("FYERS token incomplete")
    with mapping.open(encoding="utf-8") as handle:approved=json.load(handle)
    if not isinstance(approved,dict) or not approved:
        raise ValueError("Approved symbol mapping required")
    for k,v in approved.items():
        if not isinstance(k,str):raise ValueError("Invalid ticker key")
        validate_symbol(v)
    return credentials,approved
