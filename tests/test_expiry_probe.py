import json
from datetime import datetime,timezone
from nifty_l2.expiry_probe import collect_expiries,write_snapshot
from nifty_l2.research_readmodel import expiry_matrix

def test_actual_fyers_expiry_ids_and_json_archive(tmp_path):
    calls=[]
    def transport(op,*,params,credentials):
        calls.append(params)
        if params["strikecount"]==1:
            return {"s":"ok","data":{"expiryData":[
                {"date":"09-11-2026","expiry":111},
                {"date":"16-11-2026","expiry":222}]}}
        return {"s":"ok","data":{"optionsChain":[
            {"option_type":"CE","strike_price":24450,"symbol":"NSE:OPT-CE",
             "ltp":120,"oi":5000,"greeks":{"gamma":.0001}},
            {"option_type":"PE","strike_price":24450,"symbol":"NSE:OPT-PE",
             "ltp":90,"oi":7000,"greeks":{"gamma":.0002}}]}}
    moment=datetime(2026,11,5,5,0,tzinfo=timezone.utc)
    captured=collect_expiries({"client_id":"TEST"},count=2,transport=transport,
                              observed_at=moment)
    assert len(captured["expiries"])==2
    assert calls[1]["timestamp"]=="111" and calls[2]["timestamp"]=="222"
    dest=tmp_path/"expiry-20261105-1030.json"
    write_snapshot(captured,dest)
    rows=expiry_matrix(tmp_path,"2026-11-05",24450)["rows"]
    assert len(rows)==4
    assert {r["expiry"] for r in rows}=={"09-11-2026","16-11-2026"}
    assert all(r["quality"]=="BROKER_RECEIPT_ONLY" for r in rows)
    assert expiry_matrix(tmp_path,"2026-11-04",24450)["rows"]==[]
    try:
        write_snapshot(captured,dest)
    except FileExistsError:
        pass
    else:
        raise AssertionError("must refuse overwrite")
