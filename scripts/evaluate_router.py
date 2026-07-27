#!/usr/bin/env python3
"""Router evaluation harness — measures routing accuracy on a golden set.

Runs the keyword rules against every golden question; optionally (--llm, with
ANTHROPIC_API_KEY set) also measures the rules→LLM-fallback pipeline that the
app actually uses. This is the audit artifact for "how do you know routing
works": routing accuracy is measured, not assumed.

Usage:
    python scripts/evaluate_router.py          # rules only
    python scripts/evaluate_router.py --llm    # rules + LLM fallback tier
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import llm_layer                             # noqa: E402
from data_loader import load_bundle          # noqa: E402
from question_router import UNSUPPORTED, route  # noqa: E402

# (question, expected_intent) — phrasings deliberately vary from the
# suggested questions to exercise the tiers.
GOLDEN: list = [
    ("How is the Enterprise segment tracking against quota this quarter?",
     "enterprise_q2_attainment"),
    ("Which reps are at risk of missing Q2?", "reps_at_risk"),
    ("How does Q2 attainment compare to where we were at the same point in Q1?",
     "q1_q2_same_point_comparison"),
    ("Is enterprise on target for the quarter?", "enterprise_q2_attainment"),
    ("Who on the sales team is behind?", "reps_at_risk"),
    ("Compare this quarter to last quarter", "q1_q2_same_point_comparison"),
    ("What was Q1 revenue?", "q1_q2_same_point_comparison"),
    ("How is Priya Patel doing?", "rep_performance"),
    ("Give me Tom Bradley's numbers", "rep_performance"),
    ("How is SMB tracking?", "segment_performance"),
    ("Mid-market performance please", "segment_performance"),
    ("Show me the pipeline", "pipeline_summary"),
    ("What are our biggest open deals?", "pipeline_summary"),
    ("How are we doing overall?", "pipeline_summary"),
    ("Pipeline by region", "region_performance"),
    ("How is the Northeast doing?", "region_performance"),
    ("What's wrong with my data?", "data_quality_report"),
    ("Can I trust these numbers? Any data issues?", "data_quality_report"),
    ("What will Q3 revenue be?", UNSUPPORTED),
    ("Forecast next quarter", UNSUPPORTED),
    ("Who will win the World Cup?", UNSUPPORTED),
    # Hard phrasings where keyword rules are expected to struggle —
    # these measure what the LLM tier adds.
    ("Are we going to make the number this quarter?", "pipeline_summary"),
    ("Anything I should worry about before the QBR?", "reps_at_risk"),
    ("Walk me through where the big accounts stand", "pipeline_summary"),
]


def evaluate(use_llm: bool) -> None:
    bundle = load_bundle()
    hits, rows = 0, []
    for question, expected in GOLDEN:
        result = route(question, bundle)
        tier = "rules"
        if result.intent == UNSUPPORTED and use_llm:
            llm_result = llm_layer.classify_intent_llm(question, bundle)
            if llm_result is not None:
                result, tier = llm_result, "LLM"
        ok = result.intent == expected
        hits += ok
        rows.append((("✓" if ok else "✗"), tier, question[:52],
                     expected, result.intent))

    print(f"\n{'':2}{'tier':6}{'question':54}{'expected':30}{'got'}")
    print("-" * 118)
    for mark, tier, question, expected, got in rows:
        print(f"{mark:2}{tier:6}{question:54}{expected:30}{got}")
    mode = "rules + LLM fallback" if use_llm else "rules only"
    print(f"\nAccuracy ({mode}): {hits}/{len(GOLDEN)} "
          f"= {hits / len(GOLDEN):.0%}\n")


if __name__ == "__main__":
    use_llm = "--llm" in sys.argv
    if use_llm and not llm_layer.is_llm_available():
        print("--llm requested but ANTHROPIC_API_KEY is not set; "
              "running rules only.")
        use_llm = False
    evaluate(use_llm)
