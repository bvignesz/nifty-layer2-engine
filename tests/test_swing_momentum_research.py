from datetime import date,timedelta
from eod_scanner.momentum_research import rank_universe

def history(growth=1.001,turnover=200_000_000):
    d=date(2025,1,1)
    return [{"date":(d+timedelta(days=i)).isoformat(),
             "adj_close":100*(growth**i)*(1+(.002 if i%2 else 0)),
             "turnover_inr":turnover} for i in range(260)]
def test_point_in_time_rank_and_liquidity():
    result=rank_universe({"AAA":history(1.002),"BBB":history(1.001),
        "LOW":history(1.004,turnover=20_000_000),
        "EXCLUDED":history(1.02)},["AAA","BBB","LOW"],
        as_of="2026-01-01")
    assert result["status"]=="AVAILABLE"
    assert [x["symbol"] for x in result["ranked"]]==["AAA","BBB"]
    assert result["rejected"]["LOW"]=="LOW_LIQUIDITY"
    assert "EXCLUDED" not in [x["symbol"] for x in result["ranked"]]
def test_future_and_insufficient_data_fail_closed():
    result=rank_universe({"AAA":history()[:10],
          "FUTURE":history()},["AAA","FUTURE"],as_of="2025-01-15")
    assert result["status"]=="NO_CANDIDATES"
    assert result["rejected"]["AAA"]=="INSUFFICIENT_BARS"
    assert result["rejected"]["FUTURE"]=="INVALID_HISTORY"
