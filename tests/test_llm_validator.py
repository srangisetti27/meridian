"""Tests for the LLM layer's numeric validator — no API calls involved.

The validator is the guardrail that makes LLM narration safe: any number in
generated prose that the deterministic engine did not produce must cause
rejection. These tests exercise it against real computed packets.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analytics as A                    # noqa: E402
import llm_layer as L                    # noqa: E402
from data_loader import load_bundle      # noqa: E402


@pytest.fixture(scope="session")
def bundle():
    return load_bundle()


def test_extract_numbers_normalizes_formats():
    text = "Booked $518,000 (8.4% of quota), coverage 1.03x on day 32."
    assert L.extract_numbers(text) == {518000.0, 8.4, 1.03, 32.0}


def test_allowed_numbers_contains_packet_figures(bundle):
    packet = A.build_answer("q1_q2_same_point_comparison", None, bundle)
    allowed = L.allowed_numbers(packet)
    for figure in (518000.0, 1260000.0, 145000.0, 373000.0, 8.4, 21.3):
        assert figure in allowed, f"{figure} missing from allowed set"


def test_validator_accepts_faithful_narration(bundle):
    packet = A.build_answer("q1_q2_same_point_comparison", None, bundle)
    faithful = ("Q2 has closed $518,000 (8.4% of quota) versus $1,260,000 "
                "(21.3%) at the same point in Q1. Note that $373,000 of the "
                "Q2 figure is re-dated Q1 revenue — strictly new wins are "
                "$145,000.")
    found = L.extract_numbers(faithful)
    assert not (found - L.allowed_numbers(packet))


def test_validator_rejects_hallucinated_number(bundle):
    packet = A.build_answer("q1_q2_same_point_comparison", None, bundle)
    hallucinated = ("Q2 has closed $999,999 so far, which is 42.7% of quota.")
    found = L.extract_numbers(hallucinated)
    rejected = found - L.allowed_numbers(packet)
    assert 999999.0 in rejected and 42.7 in rejected


def test_validator_rejects_abbreviated_millions(bundle):
    """'$3.65M' style abbreviation must be rejected — 3.65 is not a figure
    the engine produced, and silent unit conversion is exactly the class of
    distortion the guardrail exists to stop."""
    packet = A.build_answer("enterprise_q2_attainment", None, bundle)
    found = L.extract_numbers("Enterprise quota is $3.65M.")
    assert found - L.allowed_numbers(packet)


def test_llm_availability_is_false_without_any_key(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert L.is_llm_available() is False
    assert L.provider() is None


def test_provider_selection(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                "MERIDIAN_LLM_PROVIDER", "MERIDIAN_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert L.provider() == "gemini"
    assert "gemini" in L.model_name()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert L.provider() == "anthropic"          # Anthropic preferred if both
    monkeypatch.setenv("MERIDIAN_LLM_PROVIDER", "gemini")
    assert L.provider() == "gemini"             # explicit override wins
