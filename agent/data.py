"""예시 데이터(가상 학생, 예시 지문, 어휘 사전) 불러오기."""

import json
from functools import lru_cache

from .config import DATA_DIR


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def students() -> list[dict]:
    return _load("students.json")["students"]


def student(student_id: str) -> dict | None:
    return next((s for s in students() if s["id"] == student_id), None)


def passages() -> list[dict]:
    return _load("passages.json")["passages"]


def passage(passage_id: str) -> dict | None:
    return next((p for p in passages() if p["id"] == passage_id), None)


def diagnostic_items() -> list[dict]:
    return _load("diagnostic_quiz.json")["items"]


def glossary() -> list[dict]:
    return _load("glossary.json")["words"]


def offline_demo() -> dict:
    return _load("offline_demo.json")


def word_levels() -> list[dict]:
    return _load("word_levels.json")["words"]


def peers() -> list[dict]:
    return _load("peers.json")["peers"]


def lexicon() -> dict:
    return _load("lexicon.json")


def defer_terms() -> dict:
    return _load("defer_terms.json")["terms"]


def target_terms() -> list[str]:
    """모든 지문의 '오늘 배울 핵심 용어' (중요한 순서)."""
    out = []
    for p in passages():
        for t in p.get("target_terms", []):
            if t not in out:
                out.append(t)
    return out


def subj(name: str) -> str:
    """이름 뒤에 '이/가'를 알맞게 붙인다 (린 → 린이, 바트 → 바트가)."""
    if not name:
        return name
    c = name[-1]
    if "\uac00" <= c <= "\ud7a3":
        return name + ("이" if (ord(c) - 0xAC00) % 28 else "가")
    return name + "가"


def topic(word: str) -> str:
    """낱말 뒤에 '은/는'을 알맞게 붙인다."""
    c = word[-1] if word else ""
    if "\uac00" <= c <= "\ud7a3":
        return word + ("은" if (ord(c) - 0xAC00) % 28 else "는")
    return word + "는"


def curriculum() -> dict:
    return {x["code"].strip("[]"): x for x in _load("curriculum_standards.json")["standards"]}


def guidance() -> list[dict]:
    return _load("curriculum_guidance.json")["guidance"]
