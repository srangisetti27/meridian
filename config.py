"""Central configuration for the Meridian pipeline-intelligence prototype.

Nothing in this file computes anything. It exists so an auditor can read one
page and know every date boundary, threshold, and assumption the application
uses. Changing a business rule means changing it here, visibly.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent
DATA_DIR: Path = BASE_DIR / "data"

# --------------------------------------------------------------------------
# Time boundaries (assignment brief: Q1 2026 is final; Q2 is in progress)
# --------------------------------------------------------------------------
AS_OF: date = date(2026, 5, 2)          # snapshot date, from the brief (A1)
Q1_START: date = date(2026, 1, 1)
Q1_END: date = date(2026, 3, 31)        # 90-day quarter
Q2_START: date = date(2026, 4, 1)
Q2_END: date = date(2026, 6, 30)        # 91-day quarter

Q1_DAYS: int = (Q1_END - Q1_START).days + 1                     # 90
Q2_DAYS: int = (Q2_END - Q2_START).days + 1                     # 91
ELAPSED_DAYS: int = (AS_OF - Q2_START).days + 1                 # day 32, inclusive
ELAPSED_FRAC: float = ELAPSED_DAYS / Q2_DAYS                    # ~0.352
Q1_CUTOFF: date = Q1_START + timedelta(days=ELAPSED_DAYS - 1)   # Feb 1 (day-32 alignment)

# --------------------------------------------------------------------------
# Pipeline taxonomy (whitelist — unknown stage values fail validation)
# --------------------------------------------------------------------------
OPEN_STAGES: frozenset[str] = frozenset(
    {"Prospecting", "Discovery", "Proposal", "Negotiation"})
CLOSED_STAGES: frozenset[str] = frozenset({"Closed Won", "Closed Lost"})
VALID_STAGES: frozenset[str] = OPEN_STAGES | CLOSED_STAGES
STAGE_ORDER: tuple[str, ...] = (
    "Prospecting", "Discovery", "Proposal", "Negotiation")
SEGMENTS: tuple[str, ...] = ("Enterprise", "Mid-Market", "SMB")

# --------------------------------------------------------------------------
# Expected file schemas
# --------------------------------------------------------------------------
DEAL_COLUMNS: list[str] = [
    "deal_id", "account_name", "segment", "region", "rep_id", "stage",
    "deal_value", "close_date", "created_date", "product_line", "loss_reason"]
REP_COLUMNS_Q1: list[str] = [
    "rep_id", "rep_name", "segment", "region", "quota_q1_2026",
    "manager", "hire_date"]
REP_COLUMNS_Q2: list[str] = [
    "rep_id", "rep_name", "segment", "region", "quota_q1_2026",
    "quota_q2_2026", "manager", "hire_date"]

# --------------------------------------------------------------------------
# Risk-engine thresholds (published, not hidden inside code paths)
# --------------------------------------------------------------------------
RISK: dict[str, float] = {
    # >= 70% of linear pace is treated as normal for a back-loaded quarter
    # (evidence in this data: Q1 had booked 21% at day 32, finished at 102%)
    "pace_on": 0.70,
    # < 35% of linear pace: less than half of the relaxed bar above
    "pace_risk": 0.35,
    # coverage < 1.0x: the gap cannot be closed even at a 100% win rate
    "cov_floor": 1.00,
    # > 50% of a rep's pipeline on reused deal IDs: classify the data, not the rep
    "recycled_max": 0.50,
}
# Coverage break-even is DERIVED at load time from the Q1 realized value
# win-rate (~1.28x) — see data_loader.load_bundle.

RISK_ON_TRACK = "On track"
RISK_WATCH = "Watch"
RISK_AT_RISK = "At risk"
RISK_INSUFFICIENT = "Insufficient data"

# --------------------------------------------------------------------------
# Trust levels shown on every answer
# --------------------------------------------------------------------------
TRUST_VERIFIED = "Verified"
TRUST_WITH_ASSUMPTIONS = "Verified with assumptions"
TRUST_INSUFFICIENT = "Insufficient data"

# --------------------------------------------------------------------------
# Standing assumptions (surfaced on any answer they touch)
# --------------------------------------------------------------------------
ASSUMPTIONS: dict[str, str] = {
    "A1": (f"As-of date {AS_OF:%B %d, %Y} comes from the assignment brief; "
           "the data files carry no snapshot timestamp."),
    "A2": ("Deals are attributed to a quarter by close date. The Q2 file is a "
           "cumulative snapshot containing Q1 history, so folder membership "
           "is never used for attribution."),
    "A3": ("Attainment counts Closed-Won revenue only. Open pipeline is "
           "reported separately and is never blended into attainment."),
    "A4": ("Segment roll-ups use the deal-level segment (verified equal to "
           "the owning rep's segment on every current record)."),
    "A5": ("Close dates on open deals are rep forecasts, not facts — 44 of 88 "
           "deals slipped between the Q1 and Q2 snapshots."),
    "A6": (f"'Same point in the quarter' means equal days elapsed (day "
           f"{ELAPSED_DAYS}): Q2 through {AS_OF:%b %d} vs Q1 through "
           f"{Q1_CUTOFF:%b %d}."),
}

# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------
UNSUPPORTED_MESSAGE = (
    "I cannot answer that reliably from the current dataset. The available "
    "data supports questions about quota, attainment, deals, representatives, "
    "segments, regions, stages, and quarter-over-quarter comparisons.")
