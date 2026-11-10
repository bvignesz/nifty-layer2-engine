"""Second-stage research quality filter, built on historical memory.

Never promotes old nine-check BULL/BEAR into a broker BUY. Historical
nearest-neighbor outcomes are *descriptive*, not calibrated forecast odds.
The conservative floor is a Wilson score bound for binary positive outcomes;
it is not a guarantee and no live profitability threshold is claimed.
"""
from math import sqrt
from .market_memory import search_cases,memory_status

def wilson_lower(successes,total,z=1.96):
    if not isinstance(total,int) or total<=0 or not 0<=successes<=total:
        raise ValueError("valid positive sample size required")
    p=successes/total
    denom=1+z*z/total
    return max(0.0,(p+z*z/(2*total)-z*sqrt((p*(1-p)+z*z/(4*total))/total))/denom)

def assess_quality(db_path,*,at,features,strategy,regime=None,
                   original_bias="UNAVAILABLE",min_neighbors=30,min_sessions=10):
    """Return compare-only context and an explicit review status.

    REVIEW_CONTEXT_AVAILABLE means a human can inspect historical analogues.
    It does NOT mean BUY/SELL or validate the original bullish/bearish signal.
    """
    if original_bias not in ("BULL","BEAR","UNAVAILABLE","IGNORE"):
        raise ValueError("research bias is not an order instruction")
    if min_neighbors<20 or min_sessions<5:
        raise ValueError("sample thresholds cannot be relaxed below safe minima")
    found=search_cases(db_path,at=at,features=features,strategy=strategy,
      regime=regime,limit=max(30,min_neighbors),min_neighbors=min_neighbors,
      min_sessions=min_sessions)
    answer={"status":"BLOCKED_NO_EVIDENCE","original_bias":original_bias,
       "quality_action":"IGNORE_UNVERIFIED","review_only":True,
       "orders_enabled":False,"calibrated_probability":None,
       "reason":"Insufficient independently verified comparable mature cases",
       "history":found}
    if found["status"]!="SUFFICIENT_HISTORICAL_NEIGHBORS":
        return answer
    neighbors=found["neighbors"]
    wins=sum(r["label_after_costs"] for r in neighbors)
    n=len(neighbors)
    floor=wilson_lower(wins,n)
    expectancy=found["empirical_mean_net_pnl_inr"]
    answer.update(status="RESEARCH_CONTEXT_AVAILABLE",
      quality_action="REVIEW_CONTEXT_ONLY",
      reason="Comparable historical outcomes are available, not validated forward predictions",
      historical_positive_fraction=round(wins/n,4),
      historical_wilson_lower_bound=round(floor,4),
      historical_mean_net_pnl_inr=expectancy)
    # Explicit descriptive warnings to prevent a favorable sample from being
    # displayed as a high-confidence predictive probability.
    answer["warnings"]=["Nearest neighbors selected on supplied feature space, not a calibrated model.",
       "Selection bias, regime drift, overlapping labels and execution costs require separate validation.",
       "No automated entry/exit orders, risk allocation or trade recommendation."]
    return answer

def quality_status(db_path):
    cases=memory_status(db_path)
    return {**cases,"trained_meta_model":False,
      "quality_policy":"EVIDENCE_GATED_RESEARCH",
      "historical_neighbors_are_calibrated":False}
