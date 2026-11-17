"""Overlay must never contradict the ops gold set; recall is reported, not assumed.

The overlay is a high-precision safety net behind the LLM classifier, so `None`
(no override) is a legitimate outcome. What it must never do is fire on a phrase
and pick a label that disagrees with the hand-labelled gold.
"""

import json
from pathlib import Path

from app.agents.nodes.intent_overlay import high_precision_intent

_GOLD = Path("eval/dataset/intent_ops_smoke.jsonl")


def test_overlay_never_contradicts_gold_and_reports_recall() -> None:
    rows = [
        json.loads(line) for line in _GOLD.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(rows) >= 25
    conflicts = []
    covered = 0
    for row in rows:
        pred = high_precision_intent(row["query"])
        if pred is None:
            continue
        covered += 1
        if pred.value != row["intent"]:
            conflicts.append((row["id"], row["query"], row["intent"], pred.value))
    assert conflicts == []
    # Keep the net honest: at least half the gold phrases must be covered by
    # deterministic rules, otherwise the overlay is dead code.
    assert covered / len(rows) >= 0.5
