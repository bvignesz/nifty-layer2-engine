"""Private, read-only NIFTY trading desk read model.

Joins the existing video-style microstructure rows to audited data-readiness
and forward-outcome evidence. Does not rewrite original signals or run orders.
"""
from datetime import datetime,timezone
from pathlib import Path
import sqlite3
from .microstructure_terminal import read_rows as microstructure_rows
from .research_alerts import format_research_alert
from .storage import IST

def _connection(directory):
    p=(Path(directory)/"research.db").resolve()
    if not p.is_file():return None
    conn=sqlite3.connect(p.as_uri()+"?mode=ro",uri=True,timeout=5)
    conn.execute("PRAGMA query_only=ON")
    return conn

def _counts(directory):
    conn=_connection(directory)
    if conn is None:
        return {"research_runs":0,"valid_outcomes":0,
                "futures_bars":0,"option_exchange_timestamp_count":0,
                "outcome_rows":0,"status":"NO_DATABASE"}
    try:
        def count(table,where=""):
            try:
                return conn.execute(f"SELECT count(*) FROM {table} {where}").fetchone()[0]
            except sqlite3.Error:
                return 0
        return {"research_runs":count("signals"),
            "valid_outcomes":count("outcomes","WHERE status='VALID'"),
            "outcome_rows":count("outcomes"),
            "futures_bars":count("futures_data","WHERE exchange_at_utc IS NOT NULL"),
            "option_exchange_timestamp_count":count("events",
                "WHERE kind IN ('scheduled_research','manual_research') AND exchange_at_utc IS NOT NULL"),
            "status":"AVAILABLE"}
    finally:
        conn.close()

def desk_snapshot(directory,day,*,limit=40):
    """Return immutable inspection data only; no signals promoted."""
    data=microstructure_rows(directory,day,limit)
    counts=_counts(directory)
    rows=[]
    for entry in data["rows"]:
        bias=entry["legacy_research_bias"]
        watch="CE WATCH" if bias=="BULL" else "PE WATCH" if bias=="BEAR" else "IGNORE"
        # Observation-to-observation futures proxy does not prove a completed 1m bar.
        data_ready=(entry["contract_delta_comparable"] and
                    entry["ce_observed_subset"]["comparable"] and
                    entry["pe_observed_subset"]["comparable"])
        rows.append({**entry,"research_watch":watch,
            "data_readiness":"COMPARABLE_RECEIPTS" if data_ready else "UNVERIFIED",
            "trade_permission":"MANUAL_REVIEW_ONLY",
            "alert_preview":format_research_alert(entry)})
    flags={
        "live_option_exchange_timestamps_verified":counts["option_exchange_timestamp_count"]>0,
        "completed_futures_bars_in_database":counts["futures_bars"]>0,
        "validated_forward_outcomes_present":counts["valid_outcomes"]>0,
        "options_bid_ask_historical_replay_verified":False,
        "gex_dealer_inventory_observed":False,
        "xgboost_live_trained":False,
        "telegram_delivery_configured":False,
        "orders_enabled":False}
    return {"version":2,"date_ist":day,"status":data["status"],
        "readiness":flags,"counts":counts,"rows":rows,
        "signal_policy":"LEGACY_HYPOTHESIS / MANUAL_ONLY",
        "observation_semantics":"FYERS snapshot receipts; NOT synchronized 1m option candles",
        "research_only":True,"orders_enabled":False}
