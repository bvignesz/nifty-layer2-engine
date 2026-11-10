from datetime import datetime,timezone
from nifty_l2.telegram_delivery import prepare_alert,deliver_once
from nifty_l2.storage import IST

def snapshot(now,bias="BULL",readiness="COMPARABLE_RECEIPTS"):
    return {"date_ist":now.astimezone(IST).date().isoformat(),
      "rows":[{"observed_epoch":int(now.timestamp())-100,
      "legacy_research_bias":bias,"data_readiness":readiness,
      "alert_preview":"BULL NIFTY RESEARCH WATCH / MANUAL ONLY"}]}

def test_telegram_dry_run_ready_only_on_fresh_research():
    now=datetime(2026,11,6,5,0,tzinfo=timezone.utc) # 10:30 IST
    result=prepare_alert(snapshot(now),now=now)
    assert result["status"]=="READY_RESEARCH_ONLY"
    assert len(result["key"])==64
    assert prepare_alert(snapshot(now,bias="NO TRADE"),now=now)["status"]=="SKIPPED_NO_DIRECTIONAL_WATCH"
    assert prepare_alert(snapshot(now,readiness="UNVERIFIED"),now=now)["status"]=="SKIPPED_UNVERIFIED_RECEIPTS"
    assert prepare_alert(snapshot(now),now=now,max_age_seconds=20)["status"]=="SKIPPED_STALE_DATA"

def test_telegram_explicit_one_shot_delivery_and_idempotency(tmp_path):
    now=datetime(2026,11,6,5,0,tzinfo=timezone.utc)
    alert=prepare_alert(snapshot(now),now=now)
    calls=[]
    def sender(token,chat,text):
        calls.append((token,chat,text))
    first=deliver_once(alert,token="secret",chat_id="1",
          marker_dir=tmp_path,transport=sender)
    second=deliver_once(alert,token="secret",chat_id="1",
          marker_dir=tmp_path,transport=sender)
    assert first["status"]=="RESEARCH_ALERT_SENT"
    assert first["orders_enabled"] is False
    assert second["status"]=="SKIPPED_ALREADY_SUBMITTED"
    assert len(calls)==1

def test_telegram_failure_allows_retry_without_losing_status(tmp_path):
    now=datetime(2026,11,6,5,0,tzinfo=timezone.utc)
    alert=prepare_alert(snapshot(now),now=now)
    def failed(*_):raise RuntimeError("no")
    result=deliver_once(alert,token="secret",chat_id="1",
        marker_dir=tmp_path,transport=failed)
    assert result["status"]=="DELIVERY_FAILED"
    good=deliver_once(alert,token="secret",chat_id="1",
        marker_dir=tmp_path,transport=lambda *_:None)
    assert good["status"]=="RESEARCH_ALERT_SENT"
