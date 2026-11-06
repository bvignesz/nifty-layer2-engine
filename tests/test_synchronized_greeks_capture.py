from datetime import datetime,timedelta,timezone
import pytest
from nifty_l2.synchronized_greeks_capture import capture,save_new

def test_bracket_option_chain_with_futures_quotes_and_no_orders(tmp_path):
    t=datetime.fromisoformat("2026-11-05T10:30:00+05:30")
    ticks=iter([t+timedelta(seconds=i) for i in range(8)])
    called=[]
    def broker(op,*,params,credentials):
        called.append((op,params))
        if op=="optionchain" and params["strikecount"]==1:
            return {"s":"ok","data":{"expiryData":[{"expiry":111,"date":"09-11-2026"}]}}
        if op=="optionchain":
            return {"s":"ok","data":{"optionsChain":[
                {"option_type":"CE","symbol":"NSE:C","strike_price":24500,
                "oi":65000,"greeks":{"gamma":.0002,"iv":15,"delta":.5}}]}}
        if op=="quotes":
            return {"s":"ok","d":[{"n":"NSE:NIFTY26NOVFUT","v":{"lp":24500}}]}
        raise AssertionError("Unknown or forbidden endpoint")
    result=capture({}, "NSE:NIFTY26NOVFUT",transport=broker,clock=lambda:next(ticks))
    assert result["status"]=="RECEIPT_BRACKET_UNVERIFIED"
    assert result["exchange_oi_timestamp_verified"] is False
    assert result["oi_units_verified"] is False
    assert len(result["legs"])==1
    assert result["future_quotes"][0]["requested_at"]== (t+timedelta(seconds=2)).astimezone(timezone.utc).isoformat()
    assert result["future_quotes"][0]["received_at"]== (t+timedelta(seconds=3)).astimezone(timezone.utc).isoformat()
    assert result["future_quotes"][1]["requested_at"]== (t+timedelta(seconds=6)).astimezone(timezone.utc).isoformat()
    assert result["chain_latency_seconds"]==1
    assert result["trade_eligible"] is False
    assert result["lot_sizes_verified"] is False
    assert "lot_size" in result["missing_fields"][0]["fields"]
    assert result["stale_data_status"]=="UNKNOWN_EXCHANGE_TIMESTAMPS_UNVERIFIED"
    assert [x[0] for x in called]==["optionchain","quotes","optionchain","quotes"]
    p=tmp_path/"one.json"
    save_new(p,result)
    assert p.exists()
    with pytest.raises(FileExistsError):
        save_new(p,result)

def test_bracket_rejects_market_price_drift():
    t=datetime.fromisoformat("2026-11-05T10:30:00+05:30")
    ticks=iter([t+timedelta(seconds=i) for i in range(8)])
    price_calls=iter([24500,24700])
    def broker(op,*,params,credentials):
        if op=="optionchain" and params["strikecount"]==1:
            return {"s":"ok","data":{"expiryData":[{"expiry":111,"date":"09-11-2026"}]}}
        if op=="optionchain":
            return {"s":"ok","data":{"optionsChain":[
                {"option_type":"PE","symbol":"NSE:P","strike_price":24500,
                "oi":65000,"greeks":{"gamma":.0002,"iv":15}}]}}
        if op=="quotes":
            return {"s":"ok","d":[{"n":"NSE:NIFTY26NOVFUT","v":{"lp":next(price_calls)}}]}
    result=capture({}, "NSE:NIFTY26NOVFUT",transport=broker,clock=lambda:next(ticks))
    assert result["status"]=="UNSTABLE_QUOTE_BRACKET"
    assert "gamma_model" not in result


def cli_args(path):
    return ["--live","--future-symbol","NSE:NIFTY26NOVFUT",
            "--token-path","unused-token.json","--report",str(path)]


def test_cli_collision_stops_before_token_or_broker_access(tmp_path,monkeypatch,capsys):
    from nifty_l2 import synchronized_greeks_capture as module
    path=tmp_path/"evidence.json"
    path.write_bytes(b"original evidence")
    def forbidden(*args,**kwargs):
        pytest.fail("Collision must prevent credential and broker access")
    monkeypatch.setattr(module,"load_token",forbidden)
    monkeypatch.setattr(module,"capture",forbidden)
    with pytest.raises(SystemExit) as exc:
        module.main(cli_args(path))
    assert exc.value.code==2
    assert "Choose a new --report" in capsys.readouterr().err
    assert path.read_bytes()==b"original evidence"


def test_cli_reserves_output_before_capture_and_keeps_failure(tmp_path,monkeypatch,capsys):
    import json
    from nifty_l2 import synchronized_greeks_capture as module
    path=tmp_path/"new.json"
    monkeypatch.setattr(module,"load_token",lambda _: {})
    def fail(*args,**kwargs):
        assert path.stat().st_mode & 0o777==0o600
        with pytest.raises(FileExistsError):
            module.save_new(path,{"overwrite":True})
        raise RuntimeError("secret-token-must-not-appear")
    monkeypatch.setattr(module,"capture",fail)
    with pytest.raises(SystemExit) as exc:
        module.main(cli_args(path))
    assert exc.value.code==1
    assert json.loads(path.read_text())["status"]=="CAPTURE_FAILED"
    assert "secret-token" not in capsys.readouterr().err+path.read_text()


def test_dangling_symlink_is_a_collision(tmp_path):
    from nifty_l2.synchronized_greeks_capture import reserve_report
    path=tmp_path/"link.json"
    target=tmp_path/"absent.json"
    path.symlink_to(target)
    with pytest.raises(FileExistsError):
        reserve_report(path)
    assert not target.exists()


def test_concurrent_reservations_have_exactly_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from nifty_l2.synchronized_greeks_capture import save_new
    import json
    path=tmp_path/"race.json"
    def attempt(i):
        try:
            save_new(path,{"winner":i})
            return i
        except FileExistsError:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        winners=[i for i in pool.map(attempt,range(16)) if i is not None]
    assert len(winners)==1
    assert json.loads(path.read_text())=={"winner":winners[0]}
