from nifty_l2.release_gate import evaluate

def test_release_gate_requires_all_real_evidence():
    historical={"checks":{k:True for k in (
        "sqlite_integrity","schema_present","records_present","research_safety",
        "strike_integrity","nine_checks_recorded","exchange_timestamp_coverage")}}
    fyers={"checks":[{"name":k,"status":"PASS"} for k in (
        "profile","index_quote","actual_expiry_optionchain",
        "equity_daily","equity_15m","futures_3m")]}
    assert evaluate(historical,fyers)["status"]=="BLOCKED"
    assert evaluate(historical,{"checks":[]})["status"]=="BLOCKED"
    assert evaluate({},fyers,{"verified":True},{"verified":True},
                    {"verified":True},{"verified":True})["status"]=="BLOCKED"
    complete=evaluate(historical,fyers,{"verified":True},{"verified":True},
                      {"verified":True},{"verified":True})
    assert complete["status"]=="READY_FOR_MANUAL_DEPLOYMENT_REVIEW"
    assert complete["auto_deploy"] is False
    assert complete["orders_enabled"] is False
