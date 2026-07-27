"""Lightweight observability: an append-only audit log of every question.

Every question asked of the app is recorded as one JSON line in
logs/queries.jsonl — what was asked, how it was routed, what trust level the
answer carried, whether the AI narration passed validation, and how long it
took. This is the audit trail a production deployment would ship to a
monitoring stack; locally it doubles as the demo's "observability" story.

Logging must never break the app: every function here swallows its own
errors and returns gracefully.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LOG_PATH = Path(__file__).resolve().parent / "logs" / "queries.jsonl"


def log_turn(turn: dict, path: Path = LOG_PATH) -> None:
    """Append one question/answer record. Only safe scalar fields are kept —
    never the full packet, so the log stays small and skimmable."""
    try:
        narration = turn.get("narration")
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "question": turn.get("question", ""),
            "status": "refused" if "refusal" in turn else "answered",
            "intent": turn.get("intent"),
            "matched_on": turn.get("matched_on"),
            "trust": (turn["packet"].trust if "packet" in turn else None),
            "narration_verified": (narration.ok if narration else None),
            "numbers_checked": (narration.numbers_checked if narration
                                else None),
            "duration_ms": turn.get("duration_ms"),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass                       # observability must never take the app down


def _read(path: Path = LOG_PATH) -> list:
    try:
        with path.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    except FileNotFoundError:
        return []
    except Exception:
        return []


def recent(n: int = 8, path: Path = LOG_PATH) -> list:
    """The last n logged questions, newest first."""
    return list(reversed(_read(path)[-n:]))


def summary(path: Path = LOG_PATH) -> Optional[dict]:
    """Aggregate stats over the whole log; None when nothing is logged yet."""
    rows = _read(path)
    if not rows:
        return None
    answered = [r for r in rows if r.get("status") == "answered"]
    timings = [r["duration_ms"] for r in rows
               if isinstance(r.get("duration_ms"), (int, float))]
    verified = [r for r in answered if r.get("narration_verified")]
    return {
        "total": len(rows),
        "answered": len(answered),
        "refused": len(rows) - len(answered),
        "narrations_verified": len(verified),
        "avg_ms": int(sum(timings) / len(timings)) if timings else None,
    }
