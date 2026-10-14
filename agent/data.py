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
