"""Optional LLM layer: constrained intent classification and validated narration.

Supports two interchangeable providers — Anthropic Claude (ANTHROPIC_API_KEY)
and Google Gemini (GEMINI_API_KEY / GOOGLE_API_KEY). The trust contract is
identical for both, because it does not live in the model — it lives here:

* The model NEVER computes a number. Routing may only SELECT one intent id
  from the approved catalog; its choice is re-validated against the catalog
  and its entities against the real rep master before use.
* Narration may only REPHRASE an AnswerPacket that deterministic code already
  computed. A numeric validator extracts every number from the generated
  prose and rejects the narration if any number is absent from the packet —
  the UI then falls back to the deterministic headline. A hallucinated figure
  cannot reach the screen, regardless of vendor.
* No API key, SDK missing, timeout, refusal, or any API error → graceful
  degradation to keyword routing and templated answers. The app never
  requires the LLM to function.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Optional

import config as C
from analytics import AnswerPacket
from data_loader import DataBundle
from question_router import INTENT_LABELS, RouteResult, UNSUPPORTED

_TIMEOUT_SECONDS = 25.0
_DEFAULT_MODELS = {"anthropic": "claude-opus-4-8",
                   "gemini": "gemini-flash-latest"}


# ---------------------------------------------------------------------------
# Provider detection — Anthropic preferred, Gemini as alternative
# ---------------------------------------------------------------------------
def _has_anthropic() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _has_gemini() -> bool:
    if not (os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")):
        return False
    try:
        from google import genai  # noqa: F401
    except ImportError:
        return False
    return True


def provider() -> Optional[str]:
    """Which LLM backend is usable right now, honoring an explicit override
    via MERIDIAN_LLM_PROVIDER=anthropic|gemini."""
    preference = os.environ.get("MERIDIAN_LLM_PROVIDER", "").strip().lower()
    if preference == "anthropic" and _has_anthropic():
        return "anthropic"
    if preference == "gemini" and _has_gemini():
        return "gemini"
    if _has_anthropic():
        return "anthropic"
    if _has_gemini():
        return "gemini"
    return None


def model_name() -> str:
    active = provider()
    return os.environ.get("MERIDIAN_LLM_MODEL",
                          _DEFAULT_MODELS.get(active or "anthropic"))


def provider_label() -> str:
    active = provider()
    if active is None:
        return "none"
    vendor = "Anthropic" if active == "anthropic" else "Google Gemini"
    return f"{vendor} · {model_name()}"


def is_llm_available() -> bool:
    return provider() is not None


# ---------------------------------------------------------------------------
# Unified completion call — one place where either vendor is invoked
# ---------------------------------------------------------------------------
def _complete(system: str, user: str,
              json_schema: Optional[dict] = None) -> Optional[str]:
    """One completion from the active provider. Returns text or None on any
    failure — callers always treat None as 'degrade gracefully'."""
    active = provider()
    try:
        if active == "anthropic":
            import anthropic
            client = anthropic.Anthropic(timeout=_TIMEOUT_SECONDS,
                                         max_retries=1)
            kwargs = {}
            if json_schema is not None:
                kwargs["output_config"] = {
                    "format": {"type": "json_schema", "schema": json_schema}}
            response = client.messages.create(
                model=model_name(), max_tokens=500, system=system,
                messages=[{"role": "user", "content": user}], **kwargs)
            if response.stop_reason == "refusal":
                return None
            return " ".join(b.text for b in response.content
                            if b.type == "text").strip() or None

        if active == "gemini":
            from google import genai
            from google.genai import types
            key = (os.environ.get("GEMINI_API_KEY")
                   or os.environ.get("GOOGLE_API_KEY"))
            client = genai.Client(
                api_key=key,
                http_options=types.HttpOptions(
                    timeout=int(_TIMEOUT_SECONDS * 1000)))
            # Gemini's current models always spend output tokens on internal
            # "thinking" (cannot be disabled), so the budget must cover
            # thoughts AND prose — and a truncated response is treated as a
            # failure, never shown half-finished.
            config = types.GenerateContentConfig(
                system_instruction=system, max_output_tokens=4000,
                response_mime_type=("application/json"
                                    if json_schema is not None else None))
            if json_schema is not None:
                # Gemini's schema dialect differs from JSON Schema, so the
                # shape is stated in the prompt and enforced by OUR
                # validation of the parsed output — the whitelist check is
                # the real guardrail either way.
                user = (f"{user}\n\nRespond with ONLY a JSON object of "
                        f"exactly this shape: "
                        f"{json.dumps(_schema_example(json_schema))}")
            response = client.models.generate_content(
                model=model_name(), contents=user, config=config)
            candidates = response.candidates or []
            if not candidates or "STOP" not in str(candidates[0].finish_reason):
                return None            # truncated or blocked → degrade
            return (response.text or "").strip() or None
    except Exception:
        return None
    return None


def _schema_example(schema: dict) -> dict:
    """Render a JSON schema as a filled example for prompt-based shaping."""
    example = {}
    for key, spec in schema.get("properties", {}).items():
        if "enum" in spec:
            example[key] = f"<one of: {', '.join(spec['enum'])}>"
        else:
            example[key] = f"<{spec.get('description', 'string')}>"
    return example


# ---------------------------------------------------------------------------
# Tier-3 routing — the model chooses from a menu; it never cooks
# ---------------------------------------------------------------------------
_INTENT_GUIDE: dict = {
    "enterprise_q2_attainment": "Enterprise segment tracking against Q2 quota",
    "reps_at_risk": "which sales reps are at risk of missing Q2 quota",
    "q1_q2_same_point_comparison": "comparing Q2 progress vs Q1 at the same "
                                   "point in the quarter, or questions about "
                                   "Q1 results",
    "rep_performance": "performance of one named sales rep (entity = the "
                       "rep's full name)",
    "segment_performance": "performance of one customer segment (entity = "
                           "Enterprise, Mid-Market, or SMB)",
    "region_performance": "revenue/pipeline broken down by sales region",
    "pipeline_summary": "overall company pipeline, bookings, largest deals, "
                        "or general 'how are we doing'",
    "data_quality_report": "problems, inconsistencies, or trust issues in "
                           "the underlying data",
}

_ROUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": list(_INTENT_GUIDE) + [UNSUPPORTED],
        },
        "entity": {
            "type": "string",
            "description": "Rep full name or segment name if the intent "
                           "requires one; empty string otherwise.",
        },
    },
    "required": ["intent", "entity"],
    "additionalProperties": False,
}

_SEGMENTS = {"enterprise": "Enterprise", "mid-market": "Mid-Market",
             "mid market": "Mid-Market", "midmarket": "Mid-Market",
             "smb": "SMB"}


def _resolve_entity(intent: str, raw: str,
                    bundle: DataBundle) -> Optional[str]:
    """Map the model's entity string onto a real rep_id / segment — or None.

    The model's output is never trusted as-is: entities must resolve against
    the actual rep master or the fixed segment list.
    """
    text = raw.strip().lower()
    if intent == "rep_performance":
        for _, rep in bundle.reps.iterrows():
            full = rep["rep_name"].lower()
            if text == full or full in text:
                return rep["rep_id"]
        return None
    if intent == "segment_performance":
        return _SEGMENTS.get(text)
    return None


def classify_intent_llm(question: str,
                        bundle: DataBundle) -> Optional[RouteResult]:
    """Classify a question into an approved intent via the active provider.

    Returns None on any failure or invalid output — callers treat None as
    'stick with the rules-based result'.
    """
    guide = "\n".join(f"- {k}: {v}" for k, v in _INTENT_GUIDE.items())
    reps = ", ".join(bundle.reps["rep_name"])
    system = (
        "You route questions about a sales pipeline dataset to exactly one "
        "approved analysis intent. You do NOT answer questions and you do "
        "NOT compute anything — you only classify.\n\n"
        f"Approved intents:\n{guide}\n- {UNSUPPORTED}: anything else, "
        "including future periods (Q3, forecasts), topics outside sales "
        "pipeline, or requests the intents above cannot honestly satisfy.\n\n"
        f"Known reps: {reps}. Known segments: Enterprise, Mid-Market, SMB.\n"
        "The data covers Q1 2026 (final) and Q2 2026 through May 2 only. "
        "Never substitute a similar or corrected name: if the exact person "
        "asked about is not in the known reps list, use 'unsupported'. "
        "When unsure, prefer 'unsupported' over guessing.")
    text = _complete(system, question, json_schema=_ROUTE_SCHEMA)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

    intent = str(data.get("intent", ""))
    if intent == UNSUPPORTED:
        return RouteResult(UNSUPPORTED, None,
                           "LLM classification: outside the approved analyses")
    if intent not in _INTENT_GUIDE:
        return None
    entity = _resolve_entity(intent, str(data.get("entity", "")), bundle)
    if intent in ("rep_performance", "segment_performance") and entity is None:
        return None
    return RouteResult(intent, entity,
                       "LLM classification, validated against the approved "
                       "intent catalog")


# ---------------------------------------------------------------------------
# Validated narration — the model rephrases; the validator has veto power
# ---------------------------------------------------------------------------
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def extract_numbers(text: str) -> set:
    """All numeric tokens in a string, normalized to floats."""
    found = set()
    for match in _NUMBER_RE.finditer(text):
        try:
            found.add(round(float(match.group().replace(",", "")), 2))
        except ValueError:
            continue
    return found


def allowed_numbers(packet: AnswerPacket) -> set:
    """Every number that legitimately exists in the computed packet."""
    parts = [packet.headline, *packet.calculation, *packet.warnings,
             *packet.assumptions]
    for card in packet.metrics:
        parts += [card.label, card.value, card.caption]
    for table in packet.evidence:
        parts.append(table.df.to_string())
    allowed = extract_numbers(" ".join(parts))
    # Global computed facts (quarter calendar) are always legitimate.
    allowed |= {float(C.ELAPSED_DAYS), float(C.Q2_DAYS), float(C.Q1_DAYS),
                round(C.ELAPSED_FRAC * 100, 1),
                float(round(C.ELAPSED_FRAC * 100)),
                2026.0, 1.0, 2.0, 3.0, 4.0, 5.0, 10.0}
    return allowed


@dataclass
class Narration:
    """A validated (or rejected) LLM narration of a computed answer."""
    text: str
    numbers_checked: int
    ok: bool
    rejected_numbers: tuple


_NARRATE_SYSTEM = (
    "You write a short executive summary of PRE-COMPUTED sales metrics for a "
    "skeptical Chief Commercial Officer whose trust was burned by a tool "
    "that hallucinated numbers.\n"
    "Rules:\n"
    "1. 2-4 sentences. Direct. Answer the question first.\n"
    "2. Use ONLY numbers that appear verbatim in the provided material. "
    "Never invent, derive, round, convert, or abbreviate a number — write "
    "$3,650,000, never $3.65M or 'about 3.7 million'.\n"
    "3. Always include the single most important caveat from the warnings.\n"
    "4. No preamble, no headers, no bullet points — plain prose.")


def narrate_answer(packet: AnswerPacket,
                   question: str) -> Optional[Narration]:
    """Ask the model to phrase the computed answer; veto any invented number.

    Returns None on API failure (caller falls back to the deterministic
    headline). Returns Narration(ok=False) when the validator rejected the
    prose — the rejection itself is surfaced in the UI as evidence the
    guardrail works.
    """
    material = json.dumps({
        "headline": packet.headline,
        "metrics": [{"label": m.label, "value": m.value,
                     "context": m.caption} for m in packet.metrics],
        "calculation": packet.calculation,
        "warnings": packet.warnings,
    }, default=str)
    text = _complete(_NARRATE_SYSTEM,
                     f"Question asked: {question}\n\n"
                     f"Computed results:\n{material}")
    if not text:
        return None

    found = extract_numbers(text)
    rejected = tuple(sorted(found - allowed_numbers(packet)))
    return Narration(text=text, numbers_checked=len(found),
                     ok=not rejected, rejected_numbers=rejected)
