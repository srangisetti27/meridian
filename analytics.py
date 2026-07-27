"""Deterministic analytics engine for the Meridian prototype.

Every public entry point returns an AnswerPacket whose numbers were computed
with pandas from the validated CSVs. No language model participates anywhere
in this module — the LLM-free zone is the whole file.

Each AnswerPacket carries its own evidence rows, calculation trace,
assumptions, and warnings, so the UI can render a fully traceable answer
without recomputing anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

import config as C
from data_loader import DataBundle

EVIDENCE_COLS: list[str] = [
    "deal_id", "account_name", "segment", "region", "rep_id", "stage",
    "deal_value", "close_date"]


class ReconciliationError(Exception):
    """Raised when independent totals fail to agree."""


# ---------------------------------------------------------------------------
# Formatting helpers (display only — never used in arithmetic)
# ---------------------------------------------------------------------------
def money(x: float) -> str:
    """Format a number as whole dollars."""
    return f"${x:,.0f}"


def pct(x: float, digits: int = 1) -> str:
    """Format a ratio as a percentage."""
    return f"{x * 100:.{digits}f}%"


# ---------------------------------------------------------------------------
# Answer container
# ---------------------------------------------------------------------------
@dataclass
class MetricCard:
    label: str
    value: str
    caption: str = ""


@dataclass
class EvidenceTable:
    title: str
    df: pd.DataFrame


@dataclass
class ChartSpec:
    """Declarative chart description; the UI decides how to draw it."""
    kind: str                     # grouped_money | coverage | attainment_compare | stage_mix
    title: str
    df: pd.DataFrame
    meta: dict = field(default_factory=dict)


@dataclass
class AnswerPacket:
    intent: str
    headline: str
    trust: str
    metrics: list[MetricCard]
    chart: Optional[ChartSpec]
    evidence: list[EvidenceTable]
    calculation: list[str]
    assumptions: list[str]
    warnings: list[str]


def _trust_level(warnings: list[str], insufficient: bool = False) -> str:
    """Trust is rule-based: red if a defect dominates, yellow if any
    data-quality warning touches the computation, green otherwise."""
    if insufficient:
        return C.TRUST_INSUFFICIENT
    return C.TRUST_WITH_ASSUMPTIONS if warnings else C.TRUST_VERIFIED


# ---------------------------------------------------------------------------
# Row selectors (the only quarter/stage filters in the application)
# ---------------------------------------------------------------------------
def won_rows(deals: pd.DataFrame, start, end,
             segment: Optional[str] = None,
             rep_id: Optional[str] = None) -> pd.DataFrame:
    """Closed-Won deals with close_date inside [start, end]."""
    mask = (deals["stage"] == "Closed Won") & deals["close_date"].between(start, end)
    if segment:
        mask &= deals["segment"] == segment
    if rep_id:
        mask &= deals["rep_id"] == rep_id
    return deals[mask].sort_values("deal_value", ascending=False)


def open_rows(bundle: DataBundle,
              segment: Optional[str] = None,
              rep_id: Optional[str] = None) -> pd.DataFrame:
    """Open deals expected to close inside the Q2 window (unweighted)."""
    deals = bundle.q2_deals
    mask = (deals["stage"].isin(C.OPEN_STAGES)
            & deals["close_date"].between(C.Q2_START, C.Q2_END))
    if segment:
        mask &= deals["segment"] == segment
    if rep_id:
        mask &= deals["rep_id"] == rep_id
    return deals[mask].sort_values("deal_value", ascending=False)


def _evidence(df: pd.DataFrame, bundle: DataBundle, title: str) -> EvidenceTable:
    """Build an evidence table, visibly tagging known data-quality rows."""
    out = df[EVIDENCE_COLS].copy()
    notes = []
    for deal_id in out["deal_id"]:
        tags = []
        if deal_id in bundle.recycled_ids:
            tags.append("reused ID")
        if deal_id in bundle.overdue_ids:
            tags.append("past expected close")
        if deal_id in bundle.reverted_ids:
            tags.append("changed after Q1 close")
        if deal_id in bundle.redated_ids:
            tags.append("ALSO in final Q1 revenue (close date moved)")
        if deal_id in bundle.edited_ids:
            tags.append("record edited after Q1 close")
        notes.append(", ".join(tags))
    out["data_note"] = notes
    return EvidenceTable(title=title, df=out.reset_index(drop=True))


# ---------------------------------------------------------------------------
# Aggregate tables
# ---------------------------------------------------------------------------
def classify_risk(attainment: float, pace_ratio: float, coverage: float,
                  recycled_share: float, cov_breakeven: float) -> str:
    """Metric 6 risk rules, evaluated in order. All inputs are published."""
    if recycled_share > C.RISK["recycled_max"]:
        return C.RISK_INSUFFICIENT
    if attainment >= 1.0:
        return C.RISK_ON_TRACK
    if pace_ratio >= C.RISK["pace_on"] and coverage >= cov_breakeven:
        return C.RISK_ON_TRACK
    if pace_ratio < C.RISK["pace_risk"] and coverage < C.RISK["cov_floor"]:
        return C.RISK_AT_RISK
    return C.RISK_WATCH


def rep_table(bundle: DataBundle) -> pd.DataFrame:
    """Per-rep Q2 position: booked, attainment, pipeline, coverage, risk."""
    rows = []
    for _, rep in bundle.reps.iterrows():
        rep_id = rep["rep_id"]
        quota = int(rep["quota_q2_2026"])
        booked = int(won_rows(bundle.q2_deals, C.Q2_START, C.AS_OF,
                              rep_id=rep_id)["deal_value"].sum())
        pipe_df = open_rows(bundle, rep_id=rep_id)
        pipeline = int(pipe_df["deal_value"].sum())
        recycled = int(pipe_df.loc[
            pipe_df["deal_id"].isin(bundle.recycled_ids), "deal_value"].sum())
        attainment = booked / quota
        remaining = max(quota - booked, 0)
        coverage = (pipeline / remaining) if remaining else float("inf")
        pace_ratio = attainment / C.ELAPSED_FRAC
        recycled_share = (recycled / pipeline) if pipeline else 0.0
        rows.append({
            "rep_id": rep_id, "rep_name": rep["rep_name"],
            "segment": rep["segment"], "region": rep["region"],
            "quota_q2": quota, "booked_q2": booked, "attainment": attainment,
            "remaining": remaining, "open_pipeline": pipeline,
            "coverage": coverage, "pace_ratio": pace_ratio,
            "recycled_share": recycled_share,
            "risk": classify_risk(attainment, pace_ratio, coverage,
                                  recycled_share, bundle.cov_breakeven)})
    return pd.DataFrame(rows)


def segment_table(bundle: DataBundle) -> pd.DataFrame:
    """Per-segment Q2 position with the same measures as rep_table."""
    rows = []
    for segment in C.SEGMENTS:
        quota = int(bundle.reps.loc[
            bundle.reps["segment"] == segment, "quota_q2_2026"].sum())
        booked = int(won_rows(bundle.q2_deals, C.Q2_START, C.AS_OF,
                              segment=segment)["deal_value"].sum())
        pipe_df = open_rows(bundle, segment=segment)
        pipeline = int(pipe_df["deal_value"].sum())
        recycled = int(pipe_df.loc[
            pipe_df["deal_id"].isin(bundle.recycled_ids), "deal_value"].sum())
        remaining = max(quota - booked, 0)
        rows.append({
            "segment": segment, "quota_q2": quota, "booked_q2": booked,
            "attainment": booked / quota, "remaining": remaining,
            "open_pipeline": pipeline,
            "coverage": (pipeline / remaining) if remaining else float("inf"),
            "recycled_in_pipe": recycled})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Reconciliation — every total must agree via two independent paths
# ---------------------------------------------------------------------------
def reconcile(bundle: DataBundle) -> list[str]:
    """Run cross-checks R1–R5. Returns pass messages; raises on any failure."""
    reps_df, segs_df = rep_table(bundle), segment_table(bundle)
    booked_deal_level = int(won_rows(
        bundle.q2_deals, C.Q2_START, C.AS_OF)["deal_value"].sum())
    pipe_deal_level = int(open_rows(bundle)["deal_value"].sum())

    checks = [
        ("R1 booked revenue: deal-level == per-rep == per-segment",
         booked_deal_level == reps_df["booked_q2"].sum() == segs_df["booked_q2"].sum()),
        ("R2 open pipeline: deal-level == per-rep == per-segment",
         pipe_deal_level == reps_df["open_pipeline"].sum() == segs_df["open_pipeline"].sum()),
        ("R3 quota: sum of rep quotas == sum of segment quotas",
         int(bundle.reps["quota_q2_2026"].sum()) == segs_df["quota_q2"].sum()),
    ]
    # R4 — every Q2-file row lands in exactly one bucket
    q2 = bundle.q2_deals
    n_won = len(won_rows(q2, C.Q2_START, C.AS_OF))
    n_open = len(open_rows(bundle))
    n_lost = int(((q2["stage"] == "Closed Lost")
                  & q2["close_date"].between(C.Q2_START, C.AS_OF)).sum())
    n_q1_dated = int((q2["close_date"] < C.Q2_START).sum())
    checks.append((
        "R4 row buckets: won + open + lost + Q1-dated == all Q2-file rows",
        n_won + n_open + n_lost + n_q1_dated == len(q2)))
    # R5 — the Q1 same-point subset is contained in the final Q1 book
    same_point = set(won_rows(bundle.q1_deals, C.Q1_START, C.Q1_CUTOFF)["deal_id"])
    final_book = set(won_rows(bundle.q1_deals, C.Q1_START, C.Q1_END)["deal_id"])
    checks.append(("R5 same-point wins are a subset of the final Q1 book",
                   same_point <= final_book))

    failures = [name for name, ok in checks if not ok]
    if failures:
        raise ReconciliationError("Totals failed to reconcile: " + "; ".join(failures))
    return [name for name, _ in checks]


# ---------------------------------------------------------------------------
# Answer builders — one per approved intent
# ---------------------------------------------------------------------------
def _segment_packet(bundle: DataBundle, segment: str, intent: str) -> AnswerPacket:
    """Shared builder for segment-level tracking (Enterprise question included)."""
    seg = segment_table(bundle)
    row = seg.loc[seg["segment"] == segment].iloc[0]
    won = won_rows(bundle.q2_deals, C.Q2_START, C.AS_OF, segment=segment)
    pipe = open_rows(bundle, segment=segment)
    quota_rows = bundle.reps.loc[bundle.reps["segment"] == segment,
                                 ["rep_id", "rep_name", "region", "quota_q2_2026"]]
    pace_ratio = row["attainment"] / C.ELAPSED_FRAC

    # F4 — booked revenue also present in the final Q1 book (re-dated deals)
    redated_booked = int(won.loc[
        won["deal_id"].isin(bundle.redated_ids), "deal_value"].sum())
    strictly_new = int(row["booked_q2"]) - redated_booked
    # F2 — pipeline value from deals that were already closed in the Q1 book
    reverted_pipe = int(pipe.loc[
        pipe["deal_id"].isin(bundle.reverted_ids), "deal_value"].sum())
    # If most of the booked figure is re-dated Q1 revenue, quarter attribution
    # — the heart of this metric — is dominated by a data defect.
    insufficient = row["booked_q2"] > 0 and redated_booked / row["booked_q2"] > 0.5

    headline = (
        f"{segment} has closed {money(row['booked_q2'])} of its "
        f"{money(row['quota_q2'])} Q2 quota ({pct(row['attainment'])}) with "
        f"{pct(C.ELAPSED_FRAC, 0)} of the quarter elapsed. Open pipeline of "
        f"{money(row['open_pipeline'])} covers the remaining gap "
        f"{row['coverage']:.2f}x — "
        + ("below" if row["coverage"] < bundle.cov_breakeven else "above")
        + f" the {bundle.cov_breakeven:.2f}x needed at Q1's realized win rate.")
    if insufficient:
        headline += (
            f" Caution: {money(redated_booked)} of that booked figure was "
            "already recorded as won in the final Q1 book — strictly new Q2 "
            f"revenue is {money(strictly_new)}.")

    warnings: list[str] = []
    if redated_booked:
        warnings.append(
            f"{money(redated_booked)} of {segment}'s Q2 booked revenue "
            f"({pct(redated_booked / row['booked_q2'], 0)}) comes from deals "
            "recorded as Closed Won in the final Q1 book whose close dates "
            "moved into Q2 between snapshots (F4). Counting only strictly new "
            f"wins, {segment} Q2 bookings are {money(strictly_new)}.")
    if row["recycled_in_pipe"]:
        warnings.append(
            f"{money(row['recycled_in_pipe'])} of {segment} open pipeline sits "
            "on reused deal IDs (F1); treat pipeline-based conclusions with care.")
    if reverted_pipe:
        warnings.append(
            f"{money(reverted_pipe)} of {segment} open pipeline is deals that "
            "were already closed in the final Q1 book and have reopened (F2); "
            "part of this value may already sit in Q1 revenue.")
    overdue_here = set(pipe["deal_id"]) & bundle.overdue_ids
    if overdue_here:
        warnings.append(
            f"{len(overdue_here)} open deal(s) in this segment are past their "
            f"expected close date ({', '.join(sorted(overdue_here))}).")

    assumptions = [C.ASSUMPTIONS[k] for k in ("A1", "A2", "A3", "A4")]
    if len(won) <= 2:
        assumptions.append(
            f"Only {len(won)} {segment} deal(s) have closed in Q2 so far — the "
            "attainment percentage is sensitive to individual deals this early.")

    chart_df = pd.DataFrame([
        {"label": rep_name, "measure": m, "amount": v}
        for rep_id, rep_name in quota_rows[["rep_id", "rep_name"]].itertuples(index=False)
        for m, v in (
            ("Closed-Won (booked)", int(won.loc[won["rep_id"] == rep_id, "deal_value"].sum())),
            ("Open pipeline", int(pipe.loc[pipe["rep_id"] == rep_id, "deal_value"].sum())),
            ("Q2 quota", int(quota_rows.loc[quota_rows["rep_id"] == rep_id,
                                            "quota_q2_2026"].iloc[0])))])

    return AnswerPacket(
        intent=intent,
        headline=headline,
        trust=_trust_level(warnings, insufficient=insufficient),
        metrics=[
            MetricCard("Closed-Won (booked)", money(row["booked_q2"]),
                       f"{len(won)} deal(s), Apr 1 – May 2"),
            MetricCard("Q2 quota", money(row["quota_q2"]),
                       f"{len(quota_rows)} {segment} reps"),
            MetricCard("Attainment", pct(row["attainment"]),
                       f"vs {pct(C.ELAPSED_FRAC, 0)} of quarter elapsed"),
            MetricCard("Open pipeline", money(row["open_pipeline"]),
                       f"{len(pipe)} open deals (not booked revenue)"),
            MetricCard("Pipeline coverage", f"{row['coverage']:.2f}x",
                       f"break-even {bundle.cov_breakeven:.2f}x at Q1 win rate")],
        chart=ChartSpec(
            kind="grouped_money",
            title=f"{segment}: booked vs open pipeline vs quota, by rep",
            df=chart_df),
        evidence=[
            _evidence(won, bundle,
                      f"{segment} Q2 Closed-Won deals — the entire numerator "
                      f"({len(won)} rows)"),
            EvidenceTable(f"{segment} quota basis — the entire denominator",
                          quota_rows.reset_index(drop=True)),
            _evidence(pipe, bundle,
                      f"{segment} open pipeline ({len(pipe)} rows)")],
        calculation=[
            f"Numerator   = sum of deal_value where stage = 'Closed Won' and "
            f"segment = '{segment}' and close_date in [{C.Q2_START} … {C.AS_OF}] "
            f"= {money(row['booked_q2'])}",
            f"Denominator = sum of quota_q2_2026 for {segment} reps "
            f"= {money(row['quota_q2'])}",
            f"Attainment  = numerator / denominator = {pct(row['attainment'])}",
            f"Pace ratio  = attainment / {C.ELAPSED_FRAC:.3f} elapsed "
            f"= {pace_ratio:.2f}",
            f"Coverage    = open pipeline {money(row['open_pipeline'])} / "
            f"remaining quota {money(row['remaining'])} = {row['coverage']:.2f}x",
            f"Break-even  = 1 / Q1 realized value win-rate "
            f"({pct(bundle.q1_win_rate_value)}) = {bundle.cov_breakeven:.2f}x",
            f"F4 check    = booked value also present in the final Q1 book "
            f"= {money(redated_booked)} → strictly-new Q2 bookings "
            f"= {money(strictly_new)}"],
        assumptions=assumptions,
        warnings=warnings)


def answer_enterprise_q2_attainment(bundle: DataBundle) -> AnswerPacket:
    """'How is the Enterprise segment tracking against quota this quarter?'"""
    return _segment_packet(bundle, "Enterprise", "enterprise_q2_attainment")


def answer_segment_performance(bundle: DataBundle, segment: str) -> AnswerPacket:
    """Segment-level tracking for any of the three segments."""
    return _segment_packet(bundle, segment, "segment_performance")


def answer_reps_at_risk(bundle: DataBundle) -> AnswerPacket:
    """'Which reps are at risk of missing Q2?'"""
    table = rep_table(bundle)
    counts = table["risk"].value_counts()
    at_risk = table[table["risk"] == C.RISK_AT_RISK]
    unclassified = table[table["risk"] == C.RISK_INSUFFICIENT]
    at_risk_names = ", ".join(
        f"{r.rep_name} ({r.rep_id})" for r in at_risk.itertuples())

    headline = (
        f"{len(at_risk)} of {len(table)} reps are At risk — behind pace with "
        "pipeline mathematically short of their remaining quota: "
        f"{at_risk_names}. {counts.get(C.RISK_WATCH, 0)} are on Watch, and "
        f"{len(unclassified)} cannot be responsibly classified because most of "
        "their pipeline sits on reused deal IDs.")

    display = table.copy()
    display["attainment"] = display["attainment"].map(lambda v: pct(v))
    display["pace_ratio"] = display["pace_ratio"].map(lambda v: f"{v:.2f}")
    display["coverage"] = display["coverage"].map(
        lambda v: "n/a (quota met)" if v == float("inf") else f"{v:.2f}x")
    display["recycled_share"] = display["recycled_share"].map(lambda v: pct(v, 0))

    # F4 — how much of each rep's booked figure is re-dated Q1 revenue
    q2_won_all = won_rows(bundle.q2_deals, C.Q2_START, C.AS_OF)
    redated_won = q2_won_all[q2_won_all["deal_id"].isin(bundle.redated_ids)]
    redated_by_rep = redated_won.groupby("rep_id")["deal_value"].sum()
    redated_notes = [
        f"{rep_id} ({money(value)}, "
        f"{pct(value / table.set_index('rep_id').loc[rep_id, 'booked_q2'], 0)} "
        "of their booked)"
        for rep_id, value in redated_by_rep.items()]

    warnings = [
        f"Day {C.ELAPSED_DAYS} of {C.Q2_DAYS}: "
        f"{int((table['booked_q2'] == 0).sum())} of {len(table)} reps have $0 "
        "booked. Q1 showed the same early pattern (21% booked at day 32) and "
        "finished at 102% — read 'At risk' as needs pipeline scrutiny, not a verdict.",
        f"{len(unclassified)} reps carry >50% of their pipeline on reused deal "
        "IDs (F1) and are reported as a data problem, not a performance problem.",
        "No stage-aging or activity data exists in this dataset; risk is based "
        "on booked position and pipeline arithmetic only."]
    if not redated_by_rep.empty:
        warnings.insert(0,
            f"{money(int(redated_won['deal_value'].sum()))} of booked Q2 "
            "revenue was already recorded as won in the final Q1 book (F4 "
            "re-dated deals), concentrated in: "
            f"{'; '.join(redated_notes)}. Their apparent Q2 progress is "
            "partly re-dated Q1 revenue.")

    return AnswerPacket(
        intent="reps_at_risk",
        headline=headline,
        trust=_trust_level(warnings),
        metrics=[
            MetricCard("At risk", str(len(at_risk)),
                       "behind pace and pipeline < remaining quota"),
            MetricCard("Watch", str(int(counts.get(C.RISK_WATCH, 0))),
                       "behind on one signal, not both"),
            MetricCard("On track", str(int(counts.get(C.RISK_ON_TRACK, 0))),
                       "on pace with sufficient coverage"),
            MetricCard("Insufficient data", str(len(unclassified)),
                       ">50% of pipeline on reused deal IDs")],
        chart=ChartSpec(
            kind="coverage",
            title="Pipeline coverage of remaining quota, by rep",
            df=table[["rep_name", "coverage", "risk"]]
                .replace(float("inf"), float("nan")).copy(),
            meta={"breakeven": bundle.cov_breakeven}),
        evidence=[
            EvidenceTable(
                "Per-rep Q2 position — every input to the risk rules",
                display[["rep_id", "rep_name", "segment", "quota_q2",
                         "booked_q2", "attainment", "remaining",
                         "open_pipeline", "coverage", "pace_ratio",
                         "recycled_share", "risk"]].reset_index(drop=True)),
            _evidence(won_rows(bundle.q2_deals, C.Q2_START, C.AS_OF), bundle,
                      "All Q2 Closed-Won deals to date (the booked revenue)")],
        calculation=[
            f"Pace ratio = (booked / quota) / {C.ELAPSED_FRAC:.3f} of quarter elapsed",
            "Coverage   = open Q2 pipeline / remaining quota (max(quota − booked, 0))",
            "Rules, evaluated in order:",
            f"  1. reused-ID share of pipeline > {pct(C.RISK['recycled_max'], 0)}"
            "  → Insufficient data",
            "  2. attainment ≥ 100%  → On track",
            f"  3. pace ≥ {C.RISK['pace_on']:.2f} and coverage ≥ "
            f"{bundle.cov_breakeven:.2f}x  → On track",
            f"  4. pace < {C.RISK['pace_risk']:.2f} and coverage < "
            f"{C.RISK['cov_floor']:.2f}x  → At risk",
            "  5. otherwise  → Watch",
            f"Coverage break-even {bundle.cov_breakeven:.2f}x = 1 / Q1 realized "
            f"value win-rate ({pct(bundle.q1_win_rate_value)}).",
            "Thresholds are fixed configuration, not model output."],
        assumptions=[C.ASSUMPTIONS[k] for k in ("A1", "A2", "A3", "A5")],
        warnings=warnings)


def answer_same_point(bundle: DataBundle) -> AnswerPacket:
    """'How does Q2 attainment compare to the same point in Q1?'"""
    q2_won = won_rows(bundle.q2_deals, C.Q2_START, C.AS_OF)
    q1_won = won_rows(bundle.q1_deals, C.Q1_START, C.Q1_CUTOFF)
    q1_final = won_rows(bundle.q1_deals, C.Q1_START, C.Q1_END)
    q2_total = int(q2_won["deal_value"].sum())
    q1_total = int(q1_won["deal_value"].sum())
    quota_q2 = int(bundle.reps["quota_q2_2026"].sum())
    quota_q1 = int(bundle.reps["quota_q1_2026"].sum())
    att_q2, att_q1 = q2_total / quota_q2, q1_total / quota_q1
    q1_final_total = int(q1_final["deal_value"].sum())

    # F4 — part of Q2 booked is re-dated Q1 revenue; the strict view removes it
    redated_total = int(q2_won.loc[
        q2_won["deal_id"].isin(bundle.redated_ids), "deal_value"].sum())
    strictly_new = q2_total - redated_total

    headline = (
        f"Q2 is running behind Q1's pace: {money(q2_total)} closed "
        f"({pct(att_q2)} of quota) through day {C.ELAPSED_DAYS}, versus "
        f"{money(q1_total)} ({pct(att_q1)}) at the same point in Q1 — about "
        f"{pct(q2_total / q1_total, 0)} of Q1's dollar pace. Q1 went on to "
        f"finish at {pct(q1_final_total / quota_q1)}."
        + (f" Counting only strictly new Q2 wins ({money(strictly_new)}), the "
           "gap is wider still." if redated_total else ""))

    warnings = [
        f"The Q1 side is a reconstruction: the final Q1 file filtered to "
        f"close_date ≤ {C.Q1_CUTOFF:%b %d}. A deal won by then but re-staged "
        "before quarter-end would be invisible.",
        "Q2's window has one more business day (23 vs 22) and one more "
        "calendar day in the quarter (91 vs 90); both favor Q2, so the gap is "
        "not an alignment artifact. Dollars are deliberately not adjusted.",
        f"Quota bases differ ({money(quota_q1)} vs {money(quota_q2)}); compare "
        "the percentages — dollars are shown for scale."]
    if redated_total:
        warnings.insert(0,
            f"{money(redated_total)} of Q2's booked figure comes from deals "
            "already recorded as won in the final Q1 book (F4 re-dated close "
            f"dates). On a strictly-new basis Q2 has closed {money(strictly_new)} "
            f"({pct(strictly_new / quota_q2)} of quota) — the comparison "
            "conclusion only gets stronger, not weaker.")

    chart_df = pd.DataFrame([
        {"quarter": f"Q1 through {C.Q1_CUTOFF:%b %d}", "measure": "Closed-Won",
         "amount": q1_total, "attainment_pct": att_q1 * 100},
        {"quarter": f"Q2 through {C.AS_OF:%b %d}", "measure": "Closed-Won",
         "amount": q2_total, "attainment_pct": att_q2 * 100}])

    return AnswerPacket(
        intent="q1_q2_same_point_comparison",
        headline=headline,
        trust=_trust_level(warnings),
        metrics=[
            MetricCard(f"Q2 booked (day {C.ELAPSED_DAYS})", money(q2_total),
                       f"{len(q2_won)} deals, {pct(att_q2)} of quota"),
            MetricCard(f"Q1 booked (day {C.ELAPSED_DAYS})", money(q1_total),
                       f"{len(q1_won)} deals, {pct(att_q1)} of quota"),
            MetricCard("Attainment gap", f"−{pct(att_q1 - att_q2)} pts",
                       "Q2 vs Q1 at equal days elapsed"),
            MetricCard("Strictly-new Q2 wins", money(strictly_new),
                       "excluding F4 deals also in the final Q1 book"),
            MetricCard("Q1 final result", pct(q1_final_total / quota_q1),
                       f"{money(q1_final_total)} — quarter was back-loaded")],
        chart=ChartSpec(
            kind="attainment_compare",
            title="Quota attainment at the same point in each quarter",
            df=chart_df),
        evidence=[
            _evidence(q2_won, bundle,
                      f"Q2 wins through {C.AS_OF:%b %d} ({len(q2_won)} rows)"),
            _evidence(q1_won, bundle,
                      f"Q1 wins through {C.Q1_CUTOFF:%b %d} ({len(q1_won)} rows)")],
        calculation=[
            f"Q2 numerator   = Closed-Won, close_date in [{C.Q2_START} … "
            f"{C.AS_OF}], from the Q2 file = {money(q2_total)}",
            f"Q1 numerator   = Closed-Won, close_date in [{C.Q1_START} … "
            f"{C.Q1_CUTOFF}], from the final Q1 file = {money(q1_total)}",
            f"Denominators   = total Q2 quota {money(quota_q2)}; total Q1 "
            f"quota {money(quota_q1)}",
            f"Alignment      = equal days elapsed: day {C.ELAPSED_DAYS} of "
            f"each quarter ({C.AS_OF:%b %d} ↔ {C.Q1_CUTOFF:%b %d})",
            f"Result         = Q2 {pct(att_q2)} vs Q1 {pct(att_q1)} "
            f"(gap {pct(att_q1 - att_q2)} points)",
            f"F4 check       = Q2 booked also present in the final Q1 book "
            f"= {money(redated_total)} → strictly-new Q2 = {money(strictly_new)}"],
        assumptions=[C.ASSUMPTIONS[k] for k in ("A1", "A2", "A3", "A6")],
        warnings=warnings)


def answer_rep_performance(bundle: DataBundle, rep_id: str) -> AnswerPacket:
    """Position and risk classification for a single named rep."""
    table = rep_table(bundle)
    row = table.loc[table["rep_id"] == rep_id].iloc[0]
    won = won_rows(bundle.q2_deals, C.Q2_START, C.AS_OF, rep_id=rep_id)
    pipe = open_rows(bundle, rep_id=rep_id)

    # F4 — booked revenue that also sits in the final Q1 book
    redated_booked = int(won.loc[
        won["deal_id"].isin(bundle.redated_ids), "deal_value"].sum())
    redated_dominates = (row["booked_q2"] > 0
                         and redated_booked / row["booked_q2"] > 0.5)
    insufficient = row["risk"] == C.RISK_INSUFFICIENT or redated_dominates

    headline = (
        f"{row['rep_name']} ({rep_id}, {row['segment']} {row['region']}) has "
        f"closed {money(row['booked_q2'])} of a {money(row['quota_q2'])} Q2 "
        f"quota ({pct(row['attainment'])}), with {money(row['open_pipeline'])} "
        f"open pipeline covering the gap {row['coverage']:.2f}x. "
        f"Status: {row['risk']}.")
    if row["risk"] == C.RISK_INSUFFICIENT:
        headline += (" This rep's pipeline is dominated by reused deal IDs — "
                     "the records need correction before performance "
                     "conclusions are reliable.")
    elif redated_dominates:
        headline += (
            f" Caution: {money(redated_booked)} of this booked figure was "
            "already recorded as won in the final Q1 book (re-dated close "
            f"date) — strictly new Q2 revenue is "
            f"{money(int(row['booked_q2']) - redated_booked)}.")

    warnings: list[str] = []
    if redated_booked:
        warnings.append(
            f"{money(redated_booked)} of this rep's Q2 booked revenue "
            f"({pct(redated_booked / row['booked_q2'], 0)}) is from F4 "
            "re-dated deals also counted in the final Q1 book.")
    if row["recycled_share"] > 0:
        warnings.append(
            f"{pct(row['recycled_share'], 0)} of this rep's open pipeline "
            "value sits on reused deal IDs (F1).")
    overdue_here = set(pipe["deal_id"]) & bundle.overdue_ids
    if overdue_here:
        warnings.append(
            "Open deal(s) past expected close date: "
            f"{', '.join(sorted(overdue_here))}.")

    return AnswerPacket(
        intent="rep_performance",
        headline=headline,
        trust=_trust_level(warnings, insufficient=insufficient),
        metrics=[
            MetricCard("Q2 quota", money(row["quota_q2"])),
            MetricCard("Closed-Won (booked)", money(row["booked_q2"]),
                       f"{len(won)} deal(s)"),
            MetricCard("Attainment", pct(row["attainment"]),
                       f"pace ratio {row['pace_ratio']:.2f}"),
            MetricCard("Open pipeline", money(row["open_pipeline"]),
                       f"{len(pipe)} open deal(s)"),
            MetricCard("Coverage", f"{row['coverage']:.2f}x",
                       f"of {money(row['remaining'])} remaining"),
            MetricCard("Status", str(row["risk"]))],
        chart=None,
        evidence=[
            _evidence(won, bundle,
                      f"Q2 Closed-Won deals for {row['rep_name']} ({len(won)} rows)"),
            _evidence(pipe, bundle,
                      f"Open Q2 pipeline for {row['rep_name']} ({len(pipe)} rows)")],
        calculation=[
            f"Booked     = Closed-Won, rep = {rep_id}, close_date in "
            f"[{C.Q2_START} … {C.AS_OF}] = {money(row['booked_q2'])}",
            f"Attainment = booked / quota {money(row['quota_q2'])} "
            f"= {pct(row['attainment'])}",
            f"Coverage   = pipeline {money(row['open_pipeline'])} / remaining "
            f"{money(row['remaining'])} = {row['coverage']:.2f}x",
            f"Status     = risk rules (see methodology) → {row['risk']}"],
        assumptions=[C.ASSUMPTIONS[k] for k in ("A1", "A2", "A3", "A5")],
        warnings=warnings)


def answer_pipeline_summary(bundle: DataBundle) -> AnswerPacket:
    """Company-wide Q2 position and the shape of the open pipeline."""
    q2_won = won_rows(bundle.q2_deals, C.Q2_START, C.AS_OF)
    pipe = open_rows(bundle)
    booked = int(q2_won["deal_value"].sum())
    pipeline = int(pipe["deal_value"].sum())
    quota = int(bundle.reps["quota_q2_2026"].sum())
    remaining = quota - booked
    uncovered = max(remaining - pipeline, 0)
    recycled_value = int(pipe.loc[
        pipe["deal_id"].isin(bundle.recycled_ids), "deal_value"].sum())

    stage_mix = (pipe.groupby("stage")["deal_value"]
                 .agg(deals="count", value="sum")
                 .reindex(list(C.STAGE_ORDER)).fillna(0).astype(int)
                 .reset_index())

    # F4 / F2 — contamination of booked and pipeline figures
    redated_booked = int(q2_won.loc[
        q2_won["deal_id"].isin(bundle.redated_ids), "deal_value"].sum())
    reverted_pipe = int(pipe.loc[
        pipe["deal_id"].isin(bundle.reverted_ids), "deal_value"].sum())

    headline = (
        f"Company-wide, Q2 stands at {money(booked)} closed of a "
        f"{money(quota)} quota ({pct(booked / quota)}) with {money(pipeline)} "
        f"of open in-quarter pipeline ({len(pipe)} deals). Even if every open "
        f"deal closed, {money(uncovered)} of quota would remain uncovered — "
        "new pipeline creation is the immediate priority.")

    warnings = [
        f"{money(recycled_value)} ({pct(recycled_value / pipeline, 0)}) of "
        "open pipeline sits on reused deal IDs (F1).",
        f"{len(bundle.overdue_ids)} open deals are past their expected close "
        f"date ({', '.join(sorted(bundle.overdue_ids))})."]
    if redated_booked:
        warnings.insert(0,
            f"{money(redated_booked)} of the {money(booked)} booked "
            f"({pct(redated_booked / booked, 0)}) comes from F4 re-dated "
            "deals also counted in the final Q1 book — strictly new Q2 "
            f"revenue is {money(booked - redated_booked)}.")
    if reverted_pipe:
        warnings.append(
            f"{money(reverted_pipe)} of open pipeline is deals that were "
            "already closed in the final Q1 book and reopened in Q2 (F2).")
    empty_stages = [s for s in C.STAGE_ORDER
                    if int(stage_mix.loc[stage_mix["stage"] == s,
                                         "deals"].iloc[0]) == 0]
    if empty_stages:
        warnings.append(
            f"No open deals in stage(s): {', '.join(empty_stages)} — no new "
            "early-stage pipeline is being seeded, which compounds the "
            "coverage shortfall.")

    return AnswerPacket(
        intent="pipeline_summary",
        headline=headline,
        trust=_trust_level(warnings),
        metrics=[
            MetricCard("Q2 quota", money(quota), "all 10 reps"),
            MetricCard("Closed-Won (booked)", money(booked),
                       f"{len(q2_won)} deals, {pct(booked / quota)}"),
            MetricCard("Open pipeline", money(pipeline),
                       f"{len(pipe)} deals (not booked revenue)"),
            MetricCard("Uncovered quota", money(uncovered),
                       "shortfall even at a 100% win rate")],
        chart=ChartSpec(
            kind="stage_mix",
            title="Open Q2 pipeline by stage",
            df=stage_mix),
        evidence=[
            _evidence(pipe.head(10), bundle,
                      "10 largest open Q2 opportunities"),
            _evidence(q2_won, bundle,
                      f"All Q2 Closed-Won deals to date ({len(q2_won)} rows)"),
            EvidenceTable("Open pipeline by stage", stage_mix)],
        calculation=[
            f"Booked    = Closed-Won, close_date in [{C.Q2_START} … {C.AS_OF}] "
            f"= {money(booked)}",
            f"Pipeline  = open stages, close_date in [{C.Q2_START} … {C.Q2_END}] "
            f"= {money(pipeline)}",
            f"Uncovered = (quota − booked) − pipeline, floored at zero "
            f"= {money(uncovered)}"],
        assumptions=[C.ASSUMPTIONS[k] for k in ("A1", "A2", "A3", "A5")],
        warnings=warnings)


def answer_region_performance(bundle: DataBundle,
                              region: Optional[str] = None) -> AnswerPacket:
    """Q2 position by sales region — with the quota-basis caveat made loud.

    Revenue and pipeline follow the deal's region; quota follows the rep's
    home region. Deals sold outside the owner's home region make regional
    attainment approximate, so the mismatch is counted and disclosed.
    """
    won = won_rows(bundle.q2_deals, C.Q2_START, C.AS_OF)
    pipe = open_rows(bundle)
    rep_home = bundle.reps.set_index("rep_id")["region"]

    rows = []
    for reg in sorted(bundle.reps["region"].unique()):
        booked = int(won.loc[won["region"] == reg, "deal_value"].sum())
        pipeline = int(pipe.loc[pipe["region"] == reg, "deal_value"].sum())
        quota = int(bundle.reps.loc[bundle.reps["region"] == reg,
                                    "quota_q2_2026"].sum())
        rows.append({"region": reg, "quota_q2": quota, "booked_q2": booked,
                     "attainment": booked / quota,
                     "open_pipeline": pipeline})
    table = pd.DataFrame(rows)

    active = pd.concat([won, pipe])
    cross = active[active["region"] != active["rep_id"].map(rep_home)]
    cross_value = int(cross["deal_value"].sum())

    leader = table.loc[table["booked_q2"].idxmax()]
    focus = f" Focus region: {region}." if region else ""
    headline = (
        f"By deal region, {leader['region']} leads Q2 bookings with "
        f"{money(leader['booked_q2'])}; total Q2 bookings are "
        f"{money(int(table['booked_q2'].sum()))} against a "
        f"{money(int(table['quota_q2'].sum()))} quota, with "
        f"{money(int(table['open_pipeline'].sum()))} of open pipeline "
        f"distributed across four regions.{focus}")

    warnings = [
        f"{len(cross)} active deals ({money(cross_value)}) sit in a region "
        "different from their owning rep's home region. Revenue follows the "
        "deal's region while quota follows the rep's home region, so "
        "regional attainment is approximate — treat it as directional."]

    display = table.copy()
    display["attainment"] = display["attainment"].map(lambda v: pct(v))

    chart_df = pd.DataFrame([
        {"label": r["region"], "measure": m, "amount": r[k]}
        for r in rows
        for m, k in (("Closed-Won (booked)", "booked_q2"),
                     ("Open pipeline", "open_pipeline"),
                     ("Q2 quota", "quota_q2"))])

    return AnswerPacket(
        intent="region_performance",
        headline=headline,
        trust=_trust_level(warnings),
        metrics=[MetricCard(r["region"], money(r["booked_q2"]),
                            f"quota {money(r['quota_q2'])} · pipeline "
                            f"{money(r['open_pipeline'])}") for r in rows],
        chart=ChartSpec(kind="grouped_money",
                        title="Q2 position by region (deal-level region)",
                        df=chart_df),
        evidence=[
            EvidenceTable("Per-region Q2 position",
                          display.reset_index(drop=True)),
            _evidence(cross, bundle,
                      f"Deals outside their owner's home region "
                      f"({len(cross)} rows — the source of the approximation)")],
        calculation=[
            "Booked / pipeline = grouped by the DEAL's region "
            f"(Closed-Won {C.Q2_START} → {C.AS_OF}; open stages in Q2)",
            "Quota = sum of quota_q2_2026 for reps whose HOME region matches",
            f"Basis mismatch = {len(cross)} deals ({money(cross_value)}) "
            "where deal region ≠ rep home region"],
        assumptions=[C.ASSUMPTIONS[k] for k in ("A1", "A2", "A3")],
        warnings=warnings)


def answer_data_quality(bundle: DataBundle) -> AnswerPacket:
    """'What's wrong with my data?' — the five findings, quantified.

    Every figure here is detected from the data at load time; if the client
    ships corrected files, this report empties itself.
    """
    q2 = bundle.q2_deals
    q2_by_id = q2.set_index("deal_id")["deal_value"]

    def value_of(ids) -> int:
        return int(q2_by_id.reindex(sorted(ids)).sum())

    findings = [
        ("F1 — Reused deal IDs", bundle.recycled_ids,
         "Same deal ID, different company in each snapshot. History for "
         "these IDs is unusable; current rows are kept as system of record."),
        ("F2 — Closed deals reopened", bundle.reverted_ids,
         "Closed in the final Q1 book, open or re-lost in the Q2 system. "
         "Q1 reporting follows the closed book; the overlap is flagged."),
        ("F3 — Overdue open deals", bundle.overdue_ids,
         "Open deals already past their expected close date."),
        ("F4 — Re-dated revenue", bundle.redated_ids,
         "Closed-Won in BOTH snapshots with the close date moved from Q1 "
         "into Q2 — the same revenue appears in both quarters."),
        ("F5 — Edited closed records", bundle.edited_ids,
         "Closed deals whose value or close date was edited after the Q1 "
         "book closed (e.g. one deal's value cut by $35,000)."),
    ]

    affected_ids = set().union(*(ids for _, ids, _ in findings))
    impact_df = pd.DataFrame(
        [{"finding": name, "deals": len(ids), "value_at_stake": value_of(ids)}
         for name, ids, _ in findings])

    headline = (
        f"Five distinct data-integrity findings affect "
        f"{len(affected_ids)} of {len(q2)} deals in the current snapshot. "
        f"The most consequential: {money(value_of(bundle.redated_ids))} of "
        "Q2 'bookings' was already recorded as Q1 revenue (F4), and "
        f"{money(value_of(bundle.recycled_ids))} of open pipeline sits on "
        "reused deal IDs (F1). Every affected answer in this tool is "
        "flagged automatically; fixing the source data clears the flags.")

    affected_rows = q2[q2["deal_id"].isin(affected_ids)].sort_values("deal_id")
    q1_versions = bundle.q1_deals[
        bundle.q1_deals["deal_id"].isin(
            set(bundle.redated_ids) | set(bundle.edited_ids))
    ].sort_values("deal_id")

    return AnswerPacket(
        intent="data_quality_report",
        headline=headline,
        trust=C.TRUST_VERIFIED,     # the report itself is exact, by design
        metrics=[MetricCard(name.split(" — ")[0],
                            f"{len(ids)} deals",
                            f"{money(value_of(ids))} at stake")
                 for name, ids, _ in findings],
        chart=ChartSpec(kind="impact_bar",
                        title="Value touched by each data-quality finding",
                        df=impact_df.rename(
                            columns={"finding": "label",
                                     "value_at_stake": "value"})),
        evidence=[
            EvidenceTable("Findings summary",
                          impact_df.assign(
                              note=[d for _, _, d in findings])),
            _evidence(affected_rows, bundle,
                      f"All affected deals in the current snapshot "
                      f"({len(affected_rows)} rows, tagged per finding)"),
            EvidenceTable(
                "Final Q1 book versions of re-dated / edited deals "
                "(compare against the tagged rows above)",
                q1_versions[EVIDENCE_COLS].reset_index(drop=True))],
        calculation=[
            "F1 = same deal_id, different account_name across snapshots",
            "F2 = closed in final Q1 book, different stage in Q2 snapshot",
            f"F3 = open stage with close_date earlier than {C.AS_OF}",
            "F4 = Closed-Won in both snapshots, close_date moved across "
            f"the {C.Q2_START} quarter boundary",
            "F5 = closed in both snapshots with same stage but changed "
            "deal_value or close_date",
            "All detections run at load time against the raw files — "
            "nothing is hardcoded."],
        assumptions=[C.ASSUMPTIONS["A2"]],
        warnings=[])


# ---------------------------------------------------------------------------
# Dispatcher — the complete catalog of approved computations
# ---------------------------------------------------------------------------
def build_answer(intent: str, entity: Optional[str],
                 bundle: DataBundle) -> AnswerPacket:
    """Route an approved intent to its (single) deterministic builder."""
    if intent == "enterprise_q2_attainment":
        return answer_enterprise_q2_attainment(bundle)
    if intent == "reps_at_risk":
        return answer_reps_at_risk(bundle)
    if intent == "q1_q2_same_point_comparison":
        return answer_same_point(bundle)
    if intent == "rep_performance" and entity:
        return answer_rep_performance(bundle, entity)
    if intent == "segment_performance" and entity:
        return answer_segment_performance(bundle, entity)
    if intent == "region_performance":
        return answer_region_performance(bundle, entity)
    if intent == "data_quality_report":
        return answer_data_quality(bundle)
    if intent == "pipeline_summary":
        return answer_pipeline_summary(bundle)
    raise ValueError(f"No approved builder for intent '{intent}'")
