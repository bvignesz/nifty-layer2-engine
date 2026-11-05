from datetime import datetime, timedelta
from nifty_l2.option_receipt_capture import capture_one, write_capture, compare_files

def test_receipt_capture_only_uses_expiry_and_restricts_persisted_fields(tmp_path):
    at=datetime.fromisoformat("2026-11-05T10:00:00+05:30")
    ticks=iter([at,at+timedelta(milliseconds=100),
                at+timedelta(milliseconds=200),at+timedelta(milliseconds=400)])
    requested=[]
    def transport(method,*,params,credentials):
        assert method=="optionchain"
        assert credentials["access_token"]=="SECRET"
        requested.append(params)
        if params["strikecount"]==1:
            return {"s":"ok","data":{"expiryData":[{"expiry":1793894400,"date":"05-11-2026"}]}}
        return {"s":"ok","data":{"optionsChain":[
            {"option_type":"","strike_price":-1,"ltp":24500},
            {"option_type":"CE","symbol":"NSE:CONTRACT-CE","oi":1000,
             "greeks":{"gamma":0.0001},"access_token":"SECRET"}]}}
    data=capture_one({"access_token":"SECRET"},transport=transport,
                     now=lambda:next(ticks))
    assert requested[1]["timestamp"]=="1793894400"
    assert data["meta"]["status"]=="RECEIPT_ONLY"
    assert data["meta"]["exchange_oi_timestamp"] is None
    assert data["meta"]["request_duration_seconds"]==0.2
    assert data["legs"]=={"NSE:CONTRACT-CE":1000}
    out=tmp_path/"bracket.json"
    write_capture(out,data)
    assert "SECRET" not in out.read_text()
    import pytest
    with pytest.raises(FileExistsError):
        write_capture(out,data)

def test_receipt_capture_comparison_guards_broker_universe(tmp_path):
    from nifty_l2.option_receipt_capture import write_capture
    at=datetime.fromisoformat("2026-11-05T10:00:00+05:30")
    from nifty_l2.option_observation_gate import snapshot_from_response
    def snapshot(oi, when):
        result=snapshot_from_response({"s":"ok","data":{"optionsChain":[
            {"option_type":"CE","symbol":"NSE:C","oi":oi}]}},
            requested_at=when,received_at=when+timedelta(seconds=1),expiry_id=111)
        return result
    p,q=tmp_path/"one.json",tmp_path/"two.json"
    write_capture(p,snapshot(100,at))
    write_capture(q,snapshot(120,at+timedelta(minutes=3)))
    result=compare_files(p,q)
    assert result["status"]=="COMPARABLE_RECEIPT_DELTA_UNVERIFIED"
    assert result["delta_oi_by_symbol"]=={"NSE:C":20}
    assert result["completed_option_candle"] is False
