"""Time-leakage and quality-gate regression tests for historical memory."""
from datetime import datetime,timedelta,timezone
import hashlib
import pytest
from nifty_l2.market_memory import import_cases,search_cases,memory_status
from nifty_l2.quality_filter import assess_quality,wilson_lower,quality_status
from nifty_l2.xgboost_shadow import FEATURES

START=datetime(2026,1,5,5,0,tzinfo=timezone.utc)
FEATURES_EXAMPLE={k:float(i+1) for i,k in enumerate(FEATURES)}
def sample(i,*,at=None,source="VERIFIED_HISTORICAL_REPLAY",feature_at=None,
           available_at=None,override_features=None):
    t=at or START+timedelta(days=i)
    feature=feature_at or t-timedelta(minutes=1)
    availability=available_at or t+timedelta(minutes=16)
    outcome=1 if i%3 else 0
    return {"case_id":"case-"+str(i),"observed_at_utc":t.isoformat(),
        "outcome_available_at_utc":availability.isoformat(),
        "feature_observed_at_utc":feature.isoformat(),
        "session_date":t.date().isoformat(),"strategy":"NIFTY_L2_WALL_BREAK",
        "symbol":"NSE:NIFTY50-INDEX","regime":"TREND_UP",
        "label_after_costs":outcome,
        "net_pnl_inr":150.0 if outcome else -200.0,
        "features":override_features or {k:v+(i%5)*0.01 for k,v in FEATURES_EXAMPLE.items()},
        "source":source,"evidence_sha256":hashlib.sha256(str(i).encode()).hexdigest()}
def test_memory_never_imports_outcome_before_maturity(tmp_path):
    db=tmp_path/"market_memory.db"
    now=START
    with pytest.raises(ValueError,match="not occurred"):
        import_cases(db,[sample(0)],at=now)
    assert memory_status(db)["cases"]==0
    with pytest.raises(ValueError,match="feature lookahead"):
        import_cases(db,[sample(0,feature_at=START+timedelta(minutes=1))],
          at=now+timedelta(days=3))
    with pytest.raises(ValueError,match="provenance"):
        import_cases(db,[sample(0,source="MODEL_PREDICTION")],at=now+timedelta(days=3))

def test_time_causal_neighbors_and_no_false_probability(tmp_path):
    db=tmp_path/"market_memory.db"
    cases=[sample(i) for i in range(36)]
    import_cases(db,cases,at=START+timedelta(days=40))
    assert db.stat().st_mode&0o777==0o600
    assert memory_status(db)["cases"]==36
    at=START+timedelta(days=37)
    evidence=search_cases(db,at=at,features=FEATURES_EXAMPLE,
      strategy="NIFTY_L2_WALL_BREAK",regime="TREND_UP",limit=32)
    assert evidence["status"]=="SUFFICIENT_HISTORICAL_NEIGHBORS"
    assert evidence["sample_count"]==32
    assert evidence["unique_sessions"]==32
    assert evidence["prediction_is_calibrated"] is False
    quality=assess_quality(db,at=at,features=FEATURES_EXAMPLE,
      strategy="NIFTY_L2_WALL_BREAK",regime="TREND_UP",original_bias="BULL")
    assert quality["status"]=="RESEARCH_CONTEXT_AVAILABLE"
    assert quality["quality_action"]=="REVIEW_CONTEXT_ONLY"
    assert quality["calibrated_probability"] is None
    assert not quality["orders_enabled"]
    with pytest.raises(Exception):
        import_cases(db,[sample(0)],at=START+timedelta(days=40))
    future=search_cases(db,at=START-timedelta(minutes=1),
      features=FEATURES_EXAMPLE,strategy="NIFTY_L2_WALL_BREAK")
    assert future["status"]=="NO_VERIFIED_MEMORY"

def test_future_outcome_not_eligible_even_if_features_old(tmp_path):
    db=tmp_path/"market_memory.db"
    old=sample(0,available_at=START+timedelta(days=8))
    import_cases(db,[old],at=START+timedelta(days=10))
    lookup=search_cases(db,at=START+timedelta(days=1),
       features=FEATURES_EXAMPLE,strategy="NIFTY_L2_WALL_BREAK")
    assert lookup["sample_count"]==0

def test_quality_filter_rejects_small_samples(tmp_path):
    db=tmp_path/"market_memory.db"
    import_cases(db,[sample(i) for i in range(12)],
      at=START+timedelta(days=15))
    q=assess_quality(db,at=START+timedelta(days=20),
      features=FEATURES_EXAMPLE,strategy="NIFTY_L2_WALL_BREAK")
    assert q["status"]=="BLOCKED_NO_EVIDENCE"
    assert q["quality_action"]=="IGNORE_UNVERIFIED"
    assert quality_status(db)["trained_meta_model"] is False
    with pytest.raises(ValueError):
        assess_quality(db,at=START+timedelta(days=20),
          features=FEATURES_EXAMPLE,strategy="NIFTY_L2_WALL_BREAK",
          min_neighbors=5)
    assert 0<wilson_lower(15,30)<.5

def test_feature_validation_and_regime_isolation(tmp_path):
    db=tmp_path/"market_memory.db"
    with pytest.raises(ValueError,match="features"):
        import_cases(db,[sample(0,override_features={"wall_cut_ce_pct":3})],
          at=START+timedelta(days=2))
    import_cases(db,[sample(i) for i in range(30)],
      at=START+timedelta(days=35))
    wrong=search_cases(db,at=START+timedelta(days=40),
       features=FEATURES_EXAMPLE,strategy="NIFTY_L2_WALL_BREAK",regime="TREND_DOWN")
    assert wrong["sample_count"]==0
