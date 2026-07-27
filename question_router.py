"""Constrained question routing.

A question is mapped onto one of six approved intents using transparent,
deterministic keyword rules — or declared unsupported. The router only ever
CHOOSES from a fixed menu; it cannot construct filters, columns, dates, or
calculations. Every route result reports what it matched on, so the user can
see (and correct) the interpretation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from data_loader import DataBundle

UNSUPPORTED = "unsupported"

INTENT_LABELS: dict[str, str] = {
    "enterprise_q2_attainment": "Enterprise Q2 quota tracking",
    "reps_at_risk": "Reps at risk of missing Q2",
    "q1_q2_same_point_comparison": "Q2 vs Q1 at the same point in the quarter",
    "rep_performance": "Individual rep performance",
    "segment_performance": "Segment performance",
    "region_performance": "Regional performance",
    "data_quality_report": "Data quality report",
    "pipeline_summary": "Company pipeline summary",
}

SUGGESTED_QUESTIONS: list[tuple[str, str]] = [
    ("How is the Enterprise segment tracking against quota this quarter?",
     "enterprise_q2_attainment"),
    ("Which reps are at risk of missing Q2?", "reps_at_risk"),
    ("How does Q2 attainment compare to where we were at the same point in Q1?",
     "q1_q2_same_point_comparison"),
]

_SEGMENT_ALIASES: dict[str, str] = {
    "enterprise": "Enterprise",
    "mid-market": "Mid-Market",
    "mid market": "Mid-Market",
    "midmarket": "Mid-Market",
    "smb": "SMB",
}

_RISK_WORDS = ("at risk", "risk", "missing", "miss ", "behind",
               "struggling", "danger", "shortfall", "underperform")
# Topics the dataset cannot answer — refused BEFORE any other matching so a
# question about the future is never answered with current-quarter figures.
_OUT_OF_SCOPE = ("q3", "q4", "2027", "next quarter", "next year",
                 "forecast", "predict", "projection")
# Region and data-quality questions route to their own audited intents.
_REGION_WORDS = ("region", "northeast", "southeast", "west", "central")
_DATA_QUALITY_WORDS = ("quality", "wrong", "issue", "problem", "trust",
                       "reliable", "clean", "anomal", "flag", "integrity",
                       "inconsisten")
_QUOTA_WORDS = ("quota", "track", "attain", "target", "goal", "pacing")
_COMPARE_WORDS = ("compare", "comparison", "versus", " vs ", "same point",
                  "last quarter", "previous quarter", "quarter over quarter")
_PIPELINE_WORDS = ("pipeline", "stage", "open deal", "biggest deal",
                   "largest deal", "top deal", "summary", "overview",
                   "how are we doing", "overall")
_GENERAL_WORDS = ("attainment", "bookings", "revenue", "closed", "won",
                  "deals", "region")


@dataclass(frozen=True)
class RouteResult:
    """The router's full, inspectable decision."""
    intent: str
    entity: Optional[str]       # rep_id or segment name, when applicable
    matched_on: str             # shown to the user for transparency


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s\-]", " ", text.lower())).strip()


def _find_rep(question: str, bundle: DataBundle) -> Optional[tuple[str, str]]:
    """Match a rep by full name or unique surname from the rep master."""
    words = set(question.split())
    for _, rep in bundle.reps.iterrows():
        full = rep["rep_name"].lower()
        last = full.split()[-1]
        if full in question or last in words:
            return rep["rep_id"], rep["rep_name"]
    return None


def _find_segment(question: str) -> Optional[tuple[str, str]]:
    for alias, segment in _SEGMENT_ALIASES.items():
        if alias in question:
            return segment, alias
    return None


def _first_hit(question: str, terms: tuple[str, ...]) -> Optional[str]:
    for term in terms:
        if term in question:
            return term.strip()
    return None


def route(question: str, bundle: DataBundle) -> RouteResult:
    """Map a plain-English question to an approved intent, or refuse."""
    q = _normalize(question)
    if not q:
        return RouteResult(UNSUPPORTED, None, "empty question")

    # Guard — questions about the future or periods outside the data are
    # refused up front, never answered with current-quarter figures.
    scope_hit = _first_hit(q, _OUT_OF_SCOPE)
    if scope_hit:
        return RouteResult(UNSUPPORTED, None,
                           f"out of scope: no data for '{scope_hit}'")

    # Tier 1 — exact match against the suggested questions
    for text, intent in SUGGESTED_QUESTIONS:
        if q == _normalize(text):
            return RouteResult(intent, None, "suggested question")

    # Tier 2 — transparent keyword rules, most specific first
    rep_hit = _find_rep(q, bundle)
    if rep_hit:
        rep_id, rep_name = rep_hit
        return RouteResult("rep_performance", rep_id, f"rep name '{rep_name}'")

    # Data-quality questions get their own audited report.
    if "data" in q and _first_hit(q, _DATA_QUALITY_WORDS):
        return RouteResult("data_quality_report", None,
                           "keywords 'data' + quality/issues")

    risk_hit = _first_hit(q, _RISK_WORDS)
    if risk_hit and ("rep" in q or "who" in q or "team" in q
                     or "sales" in q or "quota" in q or "q2" in q):
        return RouteResult("reps_at_risk", None, f"keyword '{risk_hit}'")

    # Any Q1 reference or comparison wording outranks segment matching, so
    # "How does Enterprise Q2 compare to Q1?" reaches the comparison view.
    compare_hit = _first_hit(q, _COMPARE_WORDS)
    if compare_hit or "q1" in q.split():
        return RouteResult("q1_q2_same_point_comparison", None,
                           f"keyword '{compare_hit or 'Q1 reference'}'")

    seg_hit = _find_segment(q)
    if seg_hit:
        segment, alias = seg_hit
        if segment == "Enterprise" and _first_hit(q, _QUOTA_WORDS):
            return RouteResult("enterprise_q2_attainment", None,
                               "keywords 'enterprise' + quota tracking")
        return RouteResult("segment_performance", segment,
                           f"segment '{alias}'")

    # Regions before pipeline words, so "pipeline by region" gets the
    # regional view rather than the unfiltered company summary.
    region_hit = _first_hit(q, _REGION_WORDS)
    if region_hit:
        return RouteResult("region_performance", None,
                           f"keyword '{region_hit}'")

    pipe_hit = _first_hit(q, _PIPELINE_WORDS)
    if pipe_hit:
        return RouteResult("pipeline_summary", None, f"keyword '{pipe_hit}'")

    general_hit = _first_hit(q, _QUOTA_WORDS + _GENERAL_WORDS)
    if general_hit:
        return RouteResult("pipeline_summary", None,
                           f"general keyword '{general_hit}' → company summary")

    return RouteResult(UNSUPPORTED, None, "no approved intent matched")
