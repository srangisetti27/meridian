"""Golden-number and edge-case tests for the Meridian analytics engine.

The expected values below were independently verified during the data
analysis phase (CLI engine + manual checks). If any number here changes, the
data or a business rule changed — either way, a human should look.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analytics as A          # noqa: E402
import config as C             # noqa: E402
import question_router as R    # noqa: E402
from data_loader import load_bundle  # noqa: E402


@pytest.fixture(scope="session")
def bundle():
    return load_bundle()


# ---------------------------------------------------------------------------
# Loading & integrity
# ---------------------------------------------------------------------------
def test_loads_expected_row_counts(bundle):
    assert len(bundle.q1_deals) == 88
    assert len(bundle.q2_deals) == 92
    assert len(bundle.reps) == 10


def test_recycled_ids_detected_not_hardcoded(bundle):
    expected = {f"OPP-{i:03d}" for i in range(76, 89)}
    assert bundle.recycled_ids == frozenset(expected)


def test_reverted_and_overdue_detection(bundle):
    assert bundle.reverted_ids == frozenset(
        {"OPP-010", "OPP-020", "OPP-032", "OPP-043",
         "OPP-049", "OPP-050", "OPP-054"})
    assert bundle.overdue_ids == frozenset({"OPP-066", "OPP-075"})
    assert bundle.new_q2_ids == frozenset(
        {"OPP-089", "OPP-090", "OPP-091", "OPP-092"})


def test_redated_revenue_detection(bundle):
    """F4 — Closed Won in both snapshots, close date moved across Apr 1.
    These deals appear as revenue in BOTH quarters; the audit's top finding."""
    assert bundle.redated_ids == frozenset({"OPP-042", "OPP-060", "OPP-074"})
    redated = bundle.q2_deals[
        bundle.q2_deals["deal_id"].isin(bundle.redated_ids)]
    assert int(redated["deal_value"].sum()) == 373_000


def test_edited_history_detection(bundle):
    """F5 — closed records silently edited between snapshots (OPP-021 value
    cut 155k -> 120k; OPP-027/OPP-038 close dates shifted within Q1)."""
    assert bundle.edited_ids == frozenset({"OPP-021", "OPP-027", "OPP-038"})


def test_f4_and_f5_flags_are_raised(bundle):
    text = " ".join(bundle.global_flags)
    assert "F4" in text and "F5" in text


def test_no_closed_deal_after_as_of(bundle):
    closed = bundle.q2_deals[bundle.q2_deals["stage"].isin(C.CLOSED_STAGES)]
    assert (closed["close_date"] <= C.AS_OF).all()


def test_reconciliations_pass(bundle):
    assert len(A.reconcile(bundle)) == 5


# ---------------------------------------------------------------------------
# Golden totals
# ---------------------------------------------------------------------------
def test_q1_final_closed_won(bundle):
    won = A.won_rows(bundle.q1_deals, C.Q1_START, C.Q1_END)
    assert int(won["deal_value"].sum()) == 6_041_000
    assert len(won) == 51


def test_q2_booked_to_date(bundle):
    won = A.won_rows(bundle.q2_deals, C.Q2_START, C.AS_OF)
    assert int(won["deal_value"].sum()) == 518_000
    assert len(won) == 5


def test_q1_same_point_reconstruction(bundle):
    assert C.Q1_CUTOFF == date(2026, 2, 1)          # day-32 alignment
    won = A.won_rows(bundle.q1_deals, C.Q1_START, C.Q1_CUTOFF)
    assert int(won["deal_value"].sum()) == 1_260_000
    assert len(won) == 10


def test_quota_totals(bundle):
    assert int(bundle.reps["quota_q2_2026"].sum()) == 6_200_000
    assert int(bundle.reps["quota_q1_2026"].sum()) == 5_920_000


def test_open_pipeline_total(bundle):
    pipe = A.open_rows(bundle)
    assert int(pipe["deal_value"].sum()) == 5_198_000
    assert len(pipe) == 46


def test_enterprise_position(bundle):
    seg = A.segment_table(bundle)
    ent = seg.loc[seg["segment"] == "Enterprise"].iloc[0]
    assert ent["booked_q2"] == 165_000
    assert ent["quota_q2"] == 3_650_000
    assert ent["open_pipeline"] == 3_600_000
    assert ent["recycled_in_pipe"] == 1_475_000
    assert ent["attainment"] == pytest.approx(165_000 / 3_650_000)


def test_q1_win_rate_and_breakeven(bundle):
    assert bundle.q1_win_rate_value == pytest.approx(0.779, abs=0.001)
    assert bundle.cov_breakeven == pytest.approx(1.283, abs=0.002)


# ---------------------------------------------------------------------------
# Risk engine
# ---------------------------------------------------------------------------
def test_risk_classifications(bundle):
    table = A.rep_table(bundle).set_index("rep_id")
    assert table.loc["REP-06", "risk"] == C.RISK_AT_RISK
    assert table.loc["REP-09", "risk"] == C.RISK_AT_RISK
    assert table.loc["REP-10", "risk"] == C.RISK_AT_RISK
    assert table.loc["REP-03", "risk"] == C.RISK_INSUFFICIENT
    assert table.loc["REP-05", "risk"] == C.RISK_INSUFFICIENT
    assert table.loc["REP-07", "risk"] == C.RISK_INSUFFICIENT
    assert table.loc["REP-08", "risk"] == C.RISK_WATCH
    assert table.loc["REP-01", "risk"] == C.RISK_WATCH


def test_risk_rule_edges():
    """Boundary behavior of the published thresholds."""
    kw = dict(recycled_share=0.0, cov_breakeven=1.28)
    assert A.classify_risk(1.0, 0.0, 0.0, **kw) == C.RISK_ON_TRACK   # quota met
    assert A.classify_risk(0.3, 0.70, 1.28, **kw) == C.RISK_ON_TRACK # both bars met
    assert A.classify_risk(0.0, 0.34, 0.99, **kw) == C.RISK_AT_RISK
    assert A.classify_risk(0.0, 0.34, 1.00, **kw) == C.RISK_WATCH    # coverage saves
    assert A.classify_risk(0.0, 0.35, 0.50, **kw) == C.RISK_WATCH    # pace at bound
    assert A.classify_risk(
        0.0, 2.0, 5.0, recycled_share=0.51, cov_breakeven=1.28
    ) == C.RISK_INSUFFICIENT                                          # data first


# ---------------------------------------------------------------------------
# Answer packets
# ---------------------------------------------------------------------------
def test_every_intent_builds_a_complete_packet(bundle):
    cases = [("enterprise_q2_attainment", None), ("reps_at_risk", None),
             ("q1_q2_same_point_comparison", None),
             ("rep_performance", "REP-08"),
             ("segment_performance", "SMB"), ("pipeline_summary", None),
             ("region_performance", None), ("data_quality_report", None)]
    for intent, entity in cases:
        packet = A.build_answer(intent, entity, bundle)
        assert packet.headline
        assert packet.metrics and packet.evidence and packet.calculation
        assert packet.trust in (C.TRUST_VERIFIED, C.TRUST_WITH_ASSUMPTIONS,
                                C.TRUST_INSUFFICIENT)


def test_rep_with_recycled_pipeline_is_flagged_insufficient(bundle):
    packet = A.build_answer("rep_performance", "REP-07", bundle)
    assert packet.trust == C.TRUST_INSUFFICIENT


def test_enterprise_answer_downgraded_for_redated_numerator(bundle):
    """The whole $165k Enterprise Q2 numerator (OPP-060) is re-dated Q1
    revenue — the answer must carry the red trust badge and say so."""
    packet = A.build_answer("enterprise_q2_attainment", None, bundle)
    assert packet.trust == C.TRUST_INSUFFICIENT
    assert any("$165,000" in w and "Q1" in w for w in packet.warnings)
    assert any("$0" in line for line in packet.calculation)  # strictly-new = $0


def test_rep08_answer_downgraded_for_redated_booked(bundle):
    """REP-08: $208k of $293k booked (71%) is re-dated -> red badge."""
    packet = A.build_answer("rep_performance", "REP-08", bundle)
    assert packet.trust == C.TRUST_INSUFFICIENT
    assert any("$208,000" in w for w in packet.warnings)


def test_same_point_reports_strictly_new_figure(bundle):
    packet = A.build_answer("q1_q2_same_point_comparison", None, bundle)
    assert any(card.value == "$145,000" for card in packet.metrics)
    assert any("$373,000" in w for w in packet.warnings)


def test_pipeline_summary_warnings_are_computed_not_hardcoded(bundle):
    packet = A.build_answer("pipeline_summary", None, bundle)
    joined = " ".join(packet.warnings)
    assert "Prospecting" in joined          # true today: 0 open Prospecting deals
    assert "$373,000" in joined             # re-dated booked revenue
    assert "$466,000" in joined             # reverted deals back in pipeline


def test_unknown_intent_raises(bundle):
    with pytest.raises(ValueError):
        A.build_answer("forecast_q3", None, bundle)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def test_router_suggested_questions(bundle):
    for text, intent in R.SUGGESTED_QUESTIONS:
        assert R.route(text, bundle).intent == intent


def test_router_rep_and_segment(bundle):
    result = R.route("How is Priya Patel doing?", bundle)
    assert result.intent == "rep_performance" and result.entity == "REP-03"
    result = R.route("How is SMB tracking against quota?", bundle)
    assert result.intent == "segment_performance" and result.entity == "SMB"


def test_router_refuses_out_of_scope(bundle):
    # Future periods / forecasts must be refused, never answered with Q2 data
    assert R.route("What will Q3 revenue be?", bundle).intent == R.UNSUPPORTED
    assert R.route("Forecast next quarter for me", bundle).intent == R.UNSUPPORTED
    assert R.route("Who will win the World Cup?", bundle).intent == R.UNSUPPORTED
    assert R.route("", bundle).intent == R.UNSUPPORTED


def test_router_region_and_data_quality_intents(bundle):
    assert R.route("Show me deals in the Northeast region",
                   bundle).intent == "region_performance"
    assert R.route("Pipeline by region", bundle).intent == "region_performance"
    assert R.route("What's wrong with my data?",
                   bundle).intent == "data_quality_report"
    assert R.route("Can I trust this data?",
                   bundle).intent == "data_quality_report"


def test_region_packet_discloses_quota_basis_mismatch(bundle):
    packet = A.build_answer("region_performance", None, bundle)
    assert any("home region" in w for w in packet.warnings)


def test_data_quality_report_is_verified_and_quantified(bundle):
    packet = A.build_answer("data_quality_report", None, bundle)
    assert packet.trust == C.TRUST_VERIFIED       # exact by construction
    assert len(packet.metrics) == 5               # F1..F5
    joined = packet.headline + " ".join(m.caption for m in packet.metrics)
    assert "$373,000" in joined                   # F4 value at stake


def test_router_comparison_outranks_segment_on_q1_reference(bundle):
    result = R.route("How does Enterprise Q2 compare to Q1?", bundle)
    assert result.intent == "q1_q2_same_point_comparison"
    result = R.route("What was Q1 revenue?", bundle)
    assert result.intent == "q1_q2_same_point_comparison"
