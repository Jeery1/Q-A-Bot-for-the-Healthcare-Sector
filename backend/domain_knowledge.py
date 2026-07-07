"""Lightweight domain data retrieval for shipbuilding QA prompts."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "shipbuilding_dialogues.json"


@lru_cache(maxsize=1)
def load_dialogues() -> list[dict]:
    if not DATA_PATH.exists():
        return []
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _score_dialogue(question: str, item: dict) -> int:
    terms = item.get("terms", [])
    topic = item.get("topic", "")
    score = 0
    for term in terms:
        if term and term in question:
            score += 3
    if topic and topic in question:
        score += 2
    for turn in item.get("turns", []):
        user_text = turn.get("user", "")
        for token in terms:
            if token and token in user_text and token in question:
                score += 1
    return score


def retrieve_domain_examples(question: str, limit: int = 2) -> list[dict]:
    scored = []
    for item in load_dialogues():
        score = _score_dialogue(question, item)
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:limit]]


def build_domain_context(question: str, limit: int = 2) -> str:
    examples = retrieve_domain_examples(question, limit=limit)
    blocks = []
    for item in examples:
        turns = item.get("turns", [])
        if not turns:
            continue
        first = turns[0]
        blocks.append(
            f"- 主题：{item.get('topic', '造船')}\n"
            f"  问：{first.get('user', '')}\n"
            f"  答：{first.get('assistant', '')}"
        )
    return "\n".join(blocks)
