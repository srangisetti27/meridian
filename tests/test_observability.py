"""Tests for the query audit log — logging must be accurate and unbreakable."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import observability as O                # noqa: E402


class _FakeNarration:
    ok = True
    numbers_checked = 7


class _FakePacket:
    trust = "Verified with assumptions"


def test_answered_turn_is_logged(tmp_path):
    log = tmp_path / "queries.jsonl"
    O.log_turn({"question": "How is Enterprise tracking?",
                "intent": "enterprise_q2_attainment",
                "matched_on": "suggested question",
                "packet": _FakePacket(), "narration": _FakeNarration(),
                "duration_ms": 1234}, path=log)
    record = json.loads(log.read_text().strip())
    assert record["status"] == "answered"
    assert record["intent"] == "enterprise_q2_attainment"
    assert record["trust"] == "Verified with assumptions"
    assert record["narration_verified"] is True
    assert record["numbers_checked"] == 7
    assert record["duration_ms"] == 1234
    assert record["ts"]                      # timestamp present


def test_refusal_is_logged(tmp_path):
    log = tmp_path / "queries.jsonl"
    O.log_turn({"question": "What will Q3 revenue be?",
                "refusal": "cannot answer", "matched_on": "out of scope",
                "duration_ms": 12}, path=log)
    record = json.loads(log.read_text().strip())
    assert record["status"] == "refused"
    assert record["trust"] is None


def test_summary_and_recent(tmp_path):
    log = tmp_path / "queries.jsonl"
    O.log_turn({"question": "q1", "intent": "pipeline_summary",
                "matched_on": "kw", "packet": _FakePacket(),
                "narration": _FakeNarration(), "duration_ms": 100}, path=log)
    O.log_turn({"question": "q2", "refusal": "no", "matched_on": "oos",
                "duration_ms": 10}, path=log)
    stats = O.summary(path=log)
    assert stats == {"total": 2, "answered": 1, "refused": 1,
                     "narrations_verified": 1, "avg_ms": 55}
    latest = O.recent(1, path=log)
    assert latest[0]["question"] == "q2"     # newest first


def test_logging_never_raises(tmp_path):
    # Unwritable path (a directory where the file should be) must not raise
    bad = tmp_path / "queries.jsonl"
    bad.mkdir()
    O.log_turn({"question": "x", "refusal": "y", "matched_on": "z"}, path=bad)
    assert O.summary(path=bad) is None       # unreadable -> graceful None
