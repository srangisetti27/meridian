# Meridian Pipeline Intelligence

A chat application that lets a sales leader ask a plain-English question about
pipeline and get back a **direct answer**, the **exact source records behind
it**, and a **flag whenever the answer rests on incomplete data, ambiguity,
or an assumption**.

Built for the Meridian Systems sales-intelligence scenario: Q1 2026 is final;
Q2 2026 is in progress as of **May 2, 2026**.

## The trust architecture

```
User question
  → Intent recognition        (keyword rules; optional LLM fallback that may
                               ONLY select from the approved intent menu)
  → Approved business metric  (one of eight hand-verified calculations)
  → Deterministic pandas      (no LLM anywhere in the numeric path)
  → Direct answer             (optional LLM narration, behind a numeric
                               validator that vetoes any number the engine
                               did not produce)
  → Supporting source records (the actual rows, not "based on your data")
  → Assumption / warning banner + trust badge (Verified / With assumptions /
                               Insufficient data)
```

The language model never calculates a metric, writes SQL, invents a filter,
or produces a number. Routing is constrained to a fixed menu; narration is
validated number-by-number against the computed result and rejected on any
mismatch (the rejection is shown — the guardrail is visible, not silent).
Questions outside the approved set are refused. Data that fails validation
stops the app entirely. **The app is fully functional without an API key** —
the LLM tier degrades gracefully to keyword routing and deterministic
headlines.

## Project structure

```
app.py                    Streamlit chat UI (rendering only)
analytics.py              Deterministic metric engine — every answer carries
                          its own evidence, formulas, assumptions, warnings
data_loader.py            Load / validate; integrity checks; the five
                          data-quality findings detected at runtime
question_router.py        Keyword intent routing with visible match reasons
llm_layer.py              Optional Claude integration: constrained routing +
                          validated narration (the numeric-veto guardrail)
config.py                 Every date boundary, threshold, and assumption
scripts/evaluate_router.py  Routing-accuracy harness on a golden question set
data/Q1, data/Q2          Client CSV snapshots (unmodified)
tests/                    37 tests: golden numbers, risk rules, router,
                          narration validator
```

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -v                  # verify all golden numbers first
python scripts/evaluate_router.py           # routing accuracy (rules tier)

streamlit run app.py                        # deterministic mode
ANTHROPIC_API_KEY=sk-... streamlit run app.py   # + LLM routing & narration
ANTHROPIC_API_KEY=sk-... python scripts/evaluate_router.py --llm
```

## The eight approved analyses

Enterprise Q2 quota tracking · Reps at risk · Q2-vs-Q1 same-point comparison ·
Individual rep performance · Segment performance · Regional performance ·
Data-quality report ("what's wrong with my data?") · Company pipeline summary

## Known data findings (auto-detected, surfaced in the app)

- **F1** — 13 deal IDs reused for different accounts between snapshots
  (~38% of open pipeline value).
- **F2** — 7 deals closed in the final Q1 book changed outcome in Q2.
- **F3** — 2 open deals past their expected close date.
- **F4** — $373,000 Closed-Won in *both* snapshots with close dates moved
  across the quarter boundary — the same revenue appears in both quarters.
  Affected answers show figures with and without it and downgrade their own
  trust badge.
- **F5** — 3 closed records edited after the Q1 book closed.

## Documentation

| Document | Purpose |
|---|---|
| `docs/guardrails.pdf` | **Guardrails specification** — the 10 safety constraints in 4 layers: what each prevents, where it lives in code, how to demo it |
| `docs/presenter-guide.pdf` | 24-page plain-English walkthrough companion (~60 min of client-facing material) |
| `docs/leave-behind.pdf` | One-page executive summary: architecture, the three answers, findings F1–F5 |
| In-app → Methodology | Metric definitions, assumptions A1–A6, reconciliation checks |
| `logs/queries.jsonl` | Audit log of every question, route, trust level, and validation result |

## Run with Docker

```bash
GEMINI_API_KEY=... docker compose up     # tests run during build; image
                                         # cannot be produced if they fail
```

## Intentionally out of scope

Free-form text-to-SQL, predictive forecasting, stage-weighted pipeline
(no stage-outcome history exists to calibrate probabilities), CRM
integration, and authentication. Each cut trades capability for
verifiability; capability is added back intent-by-intent with an audit trail.
