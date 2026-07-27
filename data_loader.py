"""Load, parse, and validate the Meridian CSV files.

Fail-closed by design: if any file is missing, any schema drifts, any value
fails to parse, or any integrity check fails, load_bundle raises
DataValidationError and the application refuses to serve numbers.

Data-quality findings (reused deal IDs, reverted closed deals, overdue open
deals) are DETECTED from the data at load time — never hardcoded — so if the
client ships corrected files, the flags disappear on their own.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

import config as C


class DataValidationError(Exception):
    """Raised when the source data fails a structural or integrity check."""


@dataclass(frozen=True)
class DataBundle:
    """Validated data plus everything derived from it at load time."""

    q1_deals: pd.DataFrame          # Q1 snapshot (final book)
    q2_deals: pd.DataFrame          # Q2 snapshot (cumulative, as of AS_OF)
    reps: pd.DataFrame              # rep master with Q1 and Q2 quotas
    recycled_ids: frozenset         # deal IDs reused for different accounts
    reverted_ids: frozenset         # deals closed in final Q1, changed in Q2
    redated_ids: frozenset          # won in BOTH snapshots, close date moved Q1→Q2
    edited_ids: frozenset           # closed records with edited value/date
    overdue_ids: frozenset          # open deals past their expected close date
    new_q2_ids: frozenset           # deal IDs that first appear in Q2
    global_flags: tuple             # human-readable data-quality flags
    q1_win_rate_value: float        # Q1 realized win rate, by deal value
    cov_breakeven: float            # 1 / win rate — pipeline coverage break-even


def _fail(msg: str) -> None:
    raise DataValidationError(msg)


def _read_csv(path: Path, expected_columns: list[str]) -> pd.DataFrame:
    """Read a CSV as strings and enforce the expected schema exactly."""
    if not path.exists():
        _fail(f"Required file not found: {path}")
    df = pd.read_csv(path, dtype=str).fillna("")
    if list(df.columns) != expected_columns:
        _fail(f"{path.name}: unexpected schema.\n"
              f"  expected: {expected_columns}\n  found:    {list(df.columns)}")
    return df


def _parse_dates(df: pd.DataFrame, cols: list[str], name: str) -> pd.DataFrame:
    for col in cols:
        parsed = pd.to_datetime(df[col], format="%Y-%m-%d", errors="coerce")
        bad = df.loc[parsed.isna(), col]
        if not bad.empty:
            _fail(f"{name}: unparseable {col} values: {bad.tolist()}")
        df[col] = parsed.dt.date
    return df


def _load_deals(path: Path) -> pd.DataFrame:
    df = _read_csv(path, C.DEAL_COLUMNS)
    df = _parse_dates(df, ["close_date", "created_date"], path.name)
    values = pd.to_numeric(df["deal_value"], errors="coerce")
    if values.isna().any() or (values <= 0).any():
        _fail(f"{path.name}: deal_value must be a positive number for all rows")
    df["deal_value"] = values.astype(int)
    unknown = set(df["stage"]) - C.VALID_STAGES
    if unknown:
        _fail(f"{path.name}: unknown pipeline stages {sorted(unknown)}")
    dupes = df.loc[df.duplicated("deal_id", keep=False), "deal_id"]
    if not dupes.empty:
        _fail(f"{path.name}: duplicate deal IDs {sorted(set(dupes))}")
    return df


def _load_reps(path: Path, expected_columns: list[str]) -> pd.DataFrame:
    df = _read_csv(path, expected_columns)
    df = _parse_dates(df, ["hire_date"], path.name)
    for col in [c for c in expected_columns if c.startswith("quota")]:
        quotas = pd.to_numeric(df[col], errors="coerce")
        if quotas.isna().any() or (quotas <= 0).any():
            _fail(f"{path.name}: {col} must be a positive number for all rows")
        df[col] = quotas.astype(int)
    if df["rep_id"].duplicated().any():
        _fail(f"{path.name}: duplicate rep IDs")
    return df


def load_bundle(data_dir: Path = C.DATA_DIR) -> DataBundle:
    """Load all four files, run every integrity check, detect quality flags."""
    q1_deals = _load_deals(data_dir / "Q1" / "deals.csv")
    q2_deals = _load_deals(data_dir / "Q2" / "deals.csv")
    q1_reps = _load_reps(data_dir / "Q1" / "reps.csv", C.REP_COLUMNS_Q1)
    reps = _load_reps(data_dir / "Q2" / "reps.csv", C.REP_COLUMNS_Q2)

    # I2 — every rep referenced by a deal exists in the rep master
    for name, deals in (("Q1 deals", q1_deals), ("Q2 deals", q2_deals)):
        orphans = set(deals["rep_id"]) - set(reps["rep_id"])
        if orphans:
            _fail(f"{name}: rep IDs missing from rep master: {sorted(orphans)}")

    # I3 — no closed deal may be dated after the snapshot date
    closed_future = q2_deals[q2_deals["stage"].isin(C.CLOSED_STAGES)
                             & (q2_deals["close_date"] > C.AS_OF)]
    if not closed_future.empty:
        _fail("Q2 deals: closed deals dated after the as-of date: "
              f"{closed_future['deal_id'].tolist()}")

    # G6 — Q1 quotas must be identical in both rep files
    q1_quotas = q1_reps.set_index("rep_id")["quota_q1_2026"]
    q2_view = reps.set_index("rep_id")["quota_q1_2026"]
    if not q1_quotas.sort_index().equals(q2_view.sort_index()):
        _fail("Q1 quotas differ between Q1/reps.csv and Q2/reps.csv")

    # I5 — deal-level segment must equal the owning rep's segment (A4 basis)
    merged_seg = q2_deals.merge(reps[["rep_id", "segment"]],
                                on="rep_id", suffixes=("", "_rep"))
    seg_mismatch = merged_seg[merged_seg["segment"] != merged_seg["segment_rep"]]
    if not seg_mismatch.empty:
        _fail("Q2 deals: deal segment differs from rep segment for "
              f"{seg_mismatch['deal_id'].tolist()} — segment roll-up basis is void")

    # ------------------------------------------------------------------
    # Snapshot comparison — detect data-quality findings from the data
    # ------------------------------------------------------------------
    merged = q1_deals.merge(q2_deals, on="deal_id", suffixes=("_q1", "_q2"))
    if len(merged) != len(q1_deals):
        _fail("Q2 snapshot is missing deals that exist in the final Q1 file")
    new_q2_ids = frozenset(set(q2_deals["deal_id"]) - set(q1_deals["deal_id"]))

    # Finding F1 — same deal_id, different account => a reused (recycled) ID
    recycled_ids = frozenset(
        merged.loc[merged["account_name_q1"] != merged["account_name_q2"],
                   "deal_id"])

    # Finding F2 — deals closed in the final Q1 book whose outcome changed
    stable = merged[~merged["deal_id"].isin(recycled_ids)]
    reverted = stable[stable["stage_q1"].isin(C.CLOSED_STAGES)
                      & (stable["stage_q1"] != stable["stage_q2"])]
    reverted_ids = frozenset(reverted["deal_id"])

    # Finding F3 — open deals already past their expected close date
    overdue = q2_deals[q2_deals["stage"].isin(C.OPEN_STAGES)
                       & (q2_deals["close_date"] < C.AS_OF)]
    overdue_ids = frozenset(overdue["deal_id"])

    # Finding F4 — CROSS-QUARTER RE-DATED REVENUE: deals Closed Won in BOTH
    # snapshots whose close date moved from inside Q1 to inside Q2. Under the
    # "each quarter reports from its own authoritative file" policy these
    # deals appear as revenue in BOTH quarters — the single largest trust
    # hazard in this dataset.
    redated = stable[(stable["stage_q1"] == "Closed Won")
                     & (stable["stage_q2"] == "Closed Won")
                     & (stable["close_date_q1"] <= C.Q1_END)
                     & (stable["close_date_q2"] >= C.Q2_START)]
    redated_ids = frozenset(redated["deal_id"])
    redated_value = int(redated["deal_value_q2"].sum())

    # Finding F5 — edited history: closed deals with the SAME stage in both
    # snapshots but a changed deal_value or close_date (excluding F4).
    edited = stable[stable["stage_q1"].isin(C.CLOSED_STAGES)
                    & (stable["stage_q1"] == stable["stage_q2"])
                    & ((stable["deal_value_q1"] != stable["deal_value_q2"])
                       | (stable["close_date_q1"] != stable["close_date_q2"]))]
    edited = edited[~edited["deal_id"].isin(redated_ids)]
    edited_ids = frozenset(edited["deal_id"])

    flags: list[str] = []
    if recycled_ids:
        flags.append(
            f"F1 — {len(recycled_ids)} deal IDs were reused for different "
            "accounts between the Q1 and Q2 snapshots "
            f"({min(recycled_ids)}…{max(recycled_ids)}). They are included in "
            "current-quarter figures as the current system of record, but "
            "excluded from all deal-history comparisons.")
    if reverted_ids:
        won_reverted = sorted(
            reverted.loc[reverted["stage_q1"] == "Closed Won", "deal_id"])
        flags.append(
            f"F2 — {len(reverted_ids)} deals recorded as closed in the final "
            f"Q1 book changed outcome in the Q2 system (won deals affected: "
            f"{', '.join(won_reverted)}). Q1 figures follow the closed Q1 "
            "book. Note: their Q1 revenue stays in the Q1 book while the "
            "deals also reappear in the Q2 pipeline — this overlap is flagged "
            "on every answer it touches.")
    if overdue_ids:
        flags.append(
            f"F3 — {len(overdue_ids)} open deals are past their expected "
            f"close date as of {C.AS_OF:%b %d} "
            f"({', '.join(sorted(overdue_ids))}). Kept in pipeline; hygiene flag.")
    if redated_ids:
        flags.append(
            f"F4 — {len(redated_ids)} deals ({', '.join(sorted(redated_ids))}, "
            f"${redated_value:,.0f}) are recorded as Closed Won in BOTH "
            "snapshots, but their close dates moved from Q1 into Q2. They are "
            "counted in the final Q1 book AND in Q2 bookings — the same "
            "revenue appears in both quarters. Every affected answer shows "
            "figures with and without these deals.")
    if edited_ids:
        flags.append(
            f"F5 — {len(edited_ids)} closed deals "
            f"({', '.join(sorted(edited_ids))}) had their value or close date "
            "edited after the Q1 book closed (e.g. a deal value cut from "
            "$155,000 to $120,000). Q1 reporting follows the Q1 file; the "
            "edits are surfaced, not silently adopted.")

    # ------------------------------------------------------------------
    # Derived constant: Q1 realized value win-rate -> coverage break-even
    # ------------------------------------------------------------------
    q1_in_window = q1_deals[q1_deals["close_date"].between(C.Q1_START, C.Q1_END)]
    won_value = q1_in_window.loc[
        q1_in_window["stage"] == "Closed Won", "deal_value"].sum()
    lost_value = q1_in_window.loc[
        q1_in_window["stage"] == "Closed Lost", "deal_value"].sum()
    if won_value + lost_value <= 0:
        _fail("Q1 deals: no decided deals found — cannot derive win rate")
    q1_win_rate = float(won_value) / float(won_value + lost_value)

    return DataBundle(
        q1_deals=q1_deals, q2_deals=q2_deals, reps=reps,
        recycled_ids=recycled_ids, reverted_ids=reverted_ids,
        redated_ids=redated_ids, edited_ids=edited_ids,
        overdue_ids=overdue_ids, new_q2_ids=new_q2_ids,
        global_flags=tuple(flags),
        q1_win_rate_value=q1_win_rate,
        cov_breakeven=1.0 / q1_win_rate)
