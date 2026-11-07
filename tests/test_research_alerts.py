import pytest
from nifty_l2.research_alerts import format_research_alert

def test_alert_is_human_review_only_and_has_provenance():
    text=format_research_alert({"observed_at_ist":"2026-11-06T10:00:00+05:30",
       "legacy_research_bias":"BULL","spot":24500,
       "pe_wall":{"strike":24450,"side":"PE"},
       "ce_wall":{"strike":24550,"side":"CE"},
       "futures_observation_quadrant":"LONG_BUILDUP_PROXY"})
    assert "BULL" in text
    assert "manual review" in text
    assert "24450 PE" in text
    assert "No automatic orders" in text

def test_alert_missing_data_is_explicit_not_fabricated():
    text=format_research_alert({})
    assert "UNAVAILABLE" in text
    assert "unavailable" in text
    with pytest.raises(ValueError):
        format_research_alert(None)
