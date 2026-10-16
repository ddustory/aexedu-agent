"""에이전트가 스스로 골라 쓰는 도구(tool) 모음.

각 도구는 (1) Claude 에게 보여줄 설명/입력 형식(TOOL_SCHEMAS)과
(2) 실제로 실행되는 파이썬 함수(TOOL_FUNCS)로 이루어진다.
모든 도구는 `reason`(지금 이 도구를 쓰는 이유)을 받아 화면 트레이스에 보여준다.
"""

import re
from dataclasses import dataclass, field

from . import data, llm
from .config import (
    CHECK_DOWN_THRESHOLD,
    CHECK_UP_THRESHOLD,
    DIAGNOSIS_RULE_TEXT,
    DIAGNOSIS_RULES,
    LANGUAGE_NAMES,
    READABILITY_MAX_AVG_EOJEOL,
    READABILITY_MAX_SENTENCE_EOJEOL,
    SCAFFOLD_LEVELS,
)


@dataclass
class AgentState:
    """한 번의 시연 세션 동안 유지되는 상태 (학생별 비계 단계 등)."""

    levels: dict = field(default_factory=dict)        # 학생ID → 현재 비계 단계
    level_history: dict = field(default_factory=dict)  # 학생ID → [(단계, 이유)]
    outputs: list = field(default_factory=list)        # 화면에 보여줄 최종 결과물


class ToolError(Exception):
    pass


# ── 1. 학생 정보 ──────────────────────────────────────────────────

def get_student_profile(state: AgentState, student_id: str, reason: str = "") -> dict:
    s = data.student(student_id)
    if not s:
        raise ToolError(f"학생 {student_id} 를 찾을 수 없습니다.")
    level = state.levels.get(student_id)
    return {
        "student_id": s["id"],
        "name": s["display_name"],
        "grade": s["grade"],
        "home_language": s["home_language"],
        "home_language_name": s["home_language_name"],
        "months_in_korea": s["months_in_korea"],
        "teacher_memo": s["teacher_memo"],
        "current_scaffold_level": level,
        "note": "아직 진단 전입니다. 먼저 진단 문제를 실행하세요." if level is None else
                f"현재 {SCAFFOLD_LEVELS[level]['name']}",
        "_summary": f"{s['display_name']} · {s['home_language_name']} · 한국 생활 {s['months_in_korea']}개월 · "
                    + ("진단 전" if level is None else f"현재 {level}단계"),
    }


# ── 2. 진단 ───────────────────────────────────────────────────────

def run_diagnostic_quiz(state: AgentState, student_id: str, reason: str = "") -> dict:
    s = data.student(student_id)
    if not s:
        raise ToolError(f"학생 {student_id} 를 찾을 수 없습니다.")
    items = data.diagnostic_items()
    answers = s["diagnostic_answers"]  # 시연용: 가상 학생이 미리 응답해 둔 답
    results = []
    for item, ans in zip(items, answers):
        results.append({
            "skill": item["skill"],
            "question": item["question"],
            "student_answer": item["choices"][ans - 1],
            "correct": ans == item["answer"],
        })
    correct = sum(r["correct"] for r in results)
    pct = round(correct / len(items) * 100)
    weak = [r["skill"] for r in results if not r["correct"]]
    return {
        "student_id": student_id,
        "correct": correct,
        "total": len(items),
        "score_percent": pct,
        "weak_skills": weak,
        "details": results,
        "_summary": f"진단 {correct}/{len(items)} 정답 ({pct}%)" + (f" · 약한 영역: {', '.join(weak)}" if weak else ""),
    }


# ── 3. 비계 단계 결정 (fading) ────────────────────────────────────

def decide_scaffold_level(state: AgentState, student_id: str, score_percent: float, mode: str,
                          reason: str = "") -> dict:
    current = state.levels.get(student_id)
    if mode == "diagnosis" or current is None:
        new = next(level for threshold, level in DIAGNOSIS_RULES if score_percent >= threshold)
        rule = (f"진단 정답률 {score_percent:.0f}% → 기준표({DIAGNOSIS_RULE_TEXT})에 따라 "
                f"{new}단계로 시작")
        change = "시작"
    elif mode == "check":
        if score_percent >= CHECK_UP_THRESHOLD:
            new = min(current + 1, 3)
            change = "지원 줄이기 (fading)" if new != current else "유지 (이미 최소 지원 단계)"
        elif score_percent < CHECK_DOWN_THRESHOLD:
            new = max(current - 1, 1)
            change = "지원 늘리기" if new != current else "유지 (이미 최대 지원 단계)"
        else:
            new = current
            change = "유지"
        rule = (f"확인 문제 정답률 {score_percent:.0f}% (기준: {CHECK_UP_THRESHOLD}% 이상이면 지원 줄이기, "
                f"{CHECK_DOWN_THRESHOLD}% 미만이면 지원 늘리기) → {current}단계 → {new}단계 [{change}]")
    else:
        raise ToolError("mode 는 'diagnosis' 또는 'check' 여야 합니다.")

    state.levels[student_id] = new
    state.level_history.setdefault(student_id, []).append((new, rule))
    lv = SCAFFOLD_LEVELS[new]
    return {
        "student_id": student_id,
        "previous_level": current,
        "new_level": new,
        "level_name": lv["name"],
        "support_policy": lv["policy"],
        "show_full_translation": lv["show_full_translation"],
        "vocab_card_count": lv["vocab_card_count"],
        "rule_applied": rule,
        "_summary": rule,
    }


# ── 4. 쉬운 한국어 ────────────────────────────────────────────────

REWRITE_SYSTEM = """당신은 한국어를 배우는 이주배경 초등학생을 위한 '쉬운 한국어' 전문가입니다.
교과 지문을 학생 수준에 맞게 다시 씁니다. 과학적/교과적 내용은 빠뜨리거나 틀리게 바꾸지 않습니다.
결과 글만 출력하고 다른 설명은 쓰지 않습니다."""

REWRITE_RULES = {
    1: "한 문장에 한 가지 내용만. 한 문장은 8어절 이하. '-해요'체. 한자어는 쉬운 말로 풀고, 꼭 배워야 할 핵심 용어는 '용어'라고 해요 형식으로 한 번 소개. 한 문장씩 줄을 바꿔 쓰세요.",
    2: "한 문장에 한 가지 내용만. 한 문장은 10어절 이하. '-해요'체. 핵심 교과 용어는 남기되 바로 뒤에 쉬운 풀이를 붙이세요. 한 문장씩 줄을 바꿔 쓰세요.",
    3: "원문 문장은 그대로 두고, 초등학생이 어려워할 낱말 바로 뒤에만 괄호로 짧은 풀이를 넣으세요. 예: 증발(물이 공기 속으로 날아가는 것).",
}


def rewrite_easy_korean(state: AgentState, text: str, level: int, reason: str = "") -> dict:
    if level not in REWRITE_RULES:
        raise ToolError("level 은 1, 2, 3 중 하나여야 합니다.")
    if llm.online():
        out = llm.complete_text(REWRITE_SYSTEM, f"[규칙]\n{REWRITE_RULES[level]}\n\n[원문]\n{text}")
    else:
        out = llm.offline_rewrite(text, level)
    return {
        "level": level,
        "rewritten_text": out,
        "_summary": f"{level}단계 규칙으로 변환 완료 ({len(_sentences(out))}문장)",
    }


# ── 5. 가독성 검사 (스스로 결과 확인) ─────────────────────────────

def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _glossary_hits(text: str) -> list[dict]:
    hits = []
    for w in data.glossary():
        if any(f in text for f in w["forms"]):
            hits.append(w)
    return hits


def check_readability(state: AgentState, text: str, reason: str = "") -> dict:
    sents = _sentences(text)
    if not sents:
        raise ToolError("검사할 문장이 없습니다.")
    lengths = [len(s.split()) for s in sents]
    avg = sum(lengths) / len(lengths)
    longest = max(lengths)
    long_sents = [s for s, n in zip(sents, lengths) if n > READABILITY_MAX_SENTENCE_EOJEOL]
    hard = [w["word"] for w in _glossary_hits(text)]
    passed = avg <= READABILITY_MAX_AVG_EOJEOL and longest <= READABILITY_MAX_SENTENCE_EOJEOL
    problems = []
    if avg > READABILITY_MAX_AVG_EOJEOL:
        problems.append(f"문장이 평균 {avg:.1f}어절로 깁니다 (기준 {READABILITY_MAX_AVG_EOJEOL}어절 이하)")
    if longest > READABILITY_MAX_SENTENCE_EOJEOL:
        problems.append(f"가장 긴 문장이 {longest}어절입니다 (기준 {READABILITY_MAX_SENTENCE_EOJEOL}어절 이하)")
    return {
        "passed": passed,
        "sentence_count": len(sents),
        "avg_eojeol_per_sentence": round(avg, 1),
        "longest_sentence_eojeol": longest,
        "too_long_sentences": long_sents[:3],
        "difficult_words_found": hard,
        "problems": problems,
        "_summary": ("✅ 통과" if passed else "❌ 기준 미달") +
                    f" · {len(sents)}문장 · 평균 {avg:.1f}어절 · 최장 {longest}어절 · 어려운 낱말 {len(hard)}개",
    }


# ── 6. 어려운 낱말 찾기 / 어휘 카드 ──────────────────────────────

def find_difficult_words(state: AgentState, text: str, reason: str = "") -> dict:
    hits = _glossary_hits(text)
    words = [w["word"] for w in hits]
    return {
        "difficult_words": words,
        "source": "교과 핵심 어휘 사전(data/glossary.json)",
        "_summary": f"{len(words)}개 발견: {', '.join(words)}" if words else "사전에 있는 어려운 낱말 없음",
    }


CARD_SYSTEM = """당신은 이주배경 초등학생을 위한 어휘 카드 제작자입니다.
주어진 한국어 낱말마다 JSON 한 줄로 답합니다: {"word":..., "easy":쉬운 한국어 뜻(15자 이내), "icon":이모지 1개, "native":모국어 번역}
JSON 줄만 출력합니다."""


def make_vocab_cards(state: AgentState, words: list[str], language: str, reason: str = "") -> dict:
    if language not in LANGUAGE_NAMES:
        raise ToolError(f"지원하지 않는 언어입니다: {language}")
    gl = {w["word"]: w for w in data.glossary()}
    cards, missing = [], []
    for word in words:
        g = gl.get(word) or next((w for w in data.glossary() if word in w["forms"]), None)
        if g:
            cards.append({"word": g["word"], "easy": g["easy"], "icon": g["icon"],
                          "native": g[language], "source": "어휘 사전"})
        else:
            missing.append(word)
    if missing and llm.online():
        import json
        out = llm.complete_text(CARD_SYSTEM, f"모국어: {LANGUAGE_NAMES[language]}\n낱말: {', '.join(missing)}")
        for line in out.splitlines():
            try:
                c = json.loads(line)
                cards.append({**c, "source": "AI 생성 (교사 확인 필요)"})
                missing.remove(c["word"])
            except (ValueError, KeyError):
                continue
    return {
        "language": language,
        "cards": cards,
        "not_found": missing,
        "_summary": f"{LANGUAGE_NAMES[language]} 어휘 카드 {len(cards)}장"
                    + (f" · 못 만든 낱말: {', '.join(missing)}" if missing else ""),
    }


# ── 7. 번역 ───────────────────────────────────────────────────────

TRANSLATE_SYSTEM = """당신은 초등학생용 교육 번역가입니다. 주어진 한국어를 학생의 모국어로,
초등학생이 이해할 수 있는 쉬운 말로 번역합니다. 줄 바꿈은 원문과 똑같이 맞춥니다. 번역문만 출력합니다."""


def translate_text(state: AgentState, text: str, language: str, reason: str = "") -> dict:
    if language not in LANGUAGE_NAMES:
        raise ToolError(f"지원하지 않는 언어입니다: {language}")
    if llm.online():
        out = llm.complete_text(TRANSLATE_SYSTEM, f"모국어: {LANGUAGE_NAMES[language]}\n\n{text}")
    else:
        out = llm.offline_translate(text, language)
    return {
        "language": language,
        "translation": out,
        "_summary": f"{LANGUAGE_NAMES[language]}로 번역 완료 ({len(out)}자)",
    }


# ── 8. 확인 문제 채점 ─────────────────────────────────────────────

def grade_check_answers(state: AgentState, passage_id: str, results: list[bool], reason: str = "") -> dict:
    p = data.passage(passage_id)
    if not p:
        raise ToolError(f"지문 {passage_id} 를 찾을 수 없습니다.")
    qs = p["check_questions"]
    if len(results) != len(qs):
        raise ToolError(f"확인 문제는 {len(qs)}개입니다. 결과도 {len(qs)}개를 주세요.")
    correct = sum(bool(r) for r in results)
    pct = round(correct / len(qs) * 100)
    wrong = [q["question"] for q, r in zip(qs, results) if not r]
    return {
        "correct": correct,
        "total": len(qs),
        "score_percent": pct,
        "missed_questions": wrong,
        "_summary": f"확인 문제 {correct}/{len(qs)} 정답 ({pct}%)",
    }


# ── 9. 화면에 결과 보여주기 ───────────────────────────────────────

def present_lesson_material(state: AgentState, student_id: str, level: int, korean_text: str,
                            vocab_cards: list[dict], native_text: str = "", teacher_note: str = "",
                            reason: str = "") -> dict:
    state.outputs.append({
        "kind": "lesson", "student_id": student_id, "level": level,
        "korean_text": korean_text, "native_text": native_text,
        "vocab_cards": vocab_cards, "teacher_note": teacher_note,
    })
    return {"shown": True, "_summary": f"학습 자료를 화면에 표시함 ({level}단계)"}


def present_bilingual(state: AgentState, student_id: str, kind: str, korean_text: str, native_text: str,
                      original_text: str = "", vocab_cards: list[dict] | None = None,
                      reason: str = "") -> dict:
    state.outputs.append({
        "kind": "bilingual", "mode": kind, "student_id": student_id,
        "original_text": original_text, "korean_text": korean_text,
        "native_text": native_text, "vocab_cards": vocab_cards or [],
    })
    return {"shown": True, "_summary": "한국어/모국어 나란히 화면에 표시함"}


def present_support_plan(state: AgentState, student_id: str, new_level: int, message_to_teacher: str,
                         next_steps: list[str], reason: str = "") -> dict:
    state.outputs.append({
        "kind": "plan", "student_id": student_id, "new_level": new_level,
        "message": message_to_teacher, "next_steps": next_steps,
        "history": state.level_history.get(student_id, []),
    })
    return {"shown": True, "_summary": f"지원 계획을 화면에 표시함 ({new_level}단계)"}


# ── Claude 에게 보여줄 도구 설명 ──────────────────────────────────

_REASON = {"type": "string", "description": "지금 이 도구를 쓰는 이유. 교사가 화면에서 읽을 한국어 한 문장."}
_CARD = {
    "type": "object",
    "properties": {
        "word": {"type": "string"}, "easy": {"type": "string"},
        "icon": {"type": "string"}, "native": {"type": "string"}, "source": {"type": "string"},
    },
    "required": ["word", "easy", "icon", "native"],
}
_LANG = {"type": "string", "enum": list(LANGUAGE_NAMES), "description": "vi=베트남어, zh=중국어, ru=러시아어, mn=몽골어"}


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": {**props, "reason": _REASON}, "required": [*required, "reason"]}


TOOL_SCHEMAS = [
    {"name": "get_student_profile",
     "description": "학생의 모국어, 한국 거주 기간, 교사 메모, 현재 비계 단계를 가져온다. 어떤 일이든 가장 먼저 쓴다.",
     "input_schema": _schema({"student_id": {"type": "string"}}, ["student_id"])},
    {"name": "run_diagnostic_quiz",
     "description": "학생의 한국어 수준 진단 문제 결과(정답률, 약한 영역)를 가져온다. 현재 비계 단계가 없을 때 쓴다.",
     "input_schema": _schema({"student_id": {"type": "string"}}, ["student_id"])},
    {"name": "decide_scaffold_level",
     "description": "정답률을 교사가 정한 기준표에 넣어 비계 단계(1=지원 많음 ~ 3=지원 적음)를 정하고 저장한다. "
                    "mode='diagnosis' 는 진단 결과로 시작 단계를 정할 때, mode='check' 는 수업 후 확인 문제 결과로 "
                    "지원을 줄이거나(fading) 늘릴 때 쓴다. 반환되는 support_policy 대로 자료를 만들어야 한다.",
     "input_schema": _schema({"student_id": {"type": "string"}, "score_percent": {"type": "number"},
                              "mode": {"type": "string", "enum": ["diagnosis", "check"]}},
                             ["student_id", "score_percent", "mode"])},
    {"name": "check_readability",
     "description": "한국어 글의 문장 길이(어절 수)와 어려운 낱말을 검사해 학생이 읽기 쉬운지 판정한다. "
                    "원문 진단과, 쉬운 한국어로 바꾼 뒤의 결과 확인에 쓴다. 기준 미달이면 다시 고쳐 써야 한다.",
     "input_schema": _schema({"text": {"type": "string"}}, ["text"])},
    {"name": "rewrite_easy_korean",
     "description": "교과 지문을 비계 단계 규칙에 맞는 쉬운 한국어로 바꾼다. 1·2단계는 짧은 문장으로 다시 쓰고, "
                    "3단계는 원문을 유지하며 어려운 낱말에 괄호 풀이만 넣는다.",
     "input_schema": _schema({"text": {"type": "string"}, "level": {"type": "integer", "enum": [1, 2, 3]}},
                             ["text", "level"])},
    {"name": "find_difficult_words",
     "description": "글에서 교과 핵심 어휘 사전에 있는 어려운 낱말을 찾는다.",
     "input_schema": _schema({"text": {"type": "string"}}, ["text"])},
    {"name": "make_vocab_cards",
     "description": "낱말 목록으로 어휘 카드(쉬운 뜻 + 그림 아이콘 + 모국어 번역)를 만든다. 사전에 없는 낱말은 AI가 만들고 '교사 확인 필요'로 표시한다.",
     "input_schema": _schema({"words": {"type": "array", "items": {"type": "string"}}, "language": _LANG},
                             ["words", "language"])},
    {"name": "translate_text",
     "description": "한국어 글을 학생 모국어로 쉬운 말로 번역한다. 줄 바꿈을 원문과 맞춰 나란히 보기에 쓸 수 있다.",
     "input_schema": _schema({"text": {"type": "string"}, "language": _LANG}, ["text", "language"])},
    {"name": "grade_check_answers",
     "description": "수업 후 확인 문제의 맞음/틀림 결과를 채점해 정답률을 계산한다.",
     "input_schema": _schema({"passage_id": {"type": "string"},
                              "results": {"type": "array", "items": {"type": "boolean"}}},
                             ["passage_id", "results"])},
    {"name": "present_lesson_material",
     "description": "완성된 학습 자료(쉬운 한국어, 모국어 번역, 어휘 카드, 교사 메모)를 화면에 보여준다. 수업 자료 만들기의 마지막 단계.",
     "input_schema": _schema({"student_id": {"type": "string"}, "level": {"type": "integer"},
                              "korean_text": {"type": "string"},
                              "native_text": {"type": "string", "description": "1단계일 때만 전체 번역. 아니면 빈 문자열."},
                              "vocab_cards": {"type": "array", "items": _CARD},
                              "teacher_note": {"type": "string", "description": "교사에게 주는 짧은 수업 팁"}},
                             ["student_id", "level", "korean_text", "vocab_cards", "teacher_note"])},
    {"name": "present_bilingual",
     "description": "쉬운 한국어와 모국어를 나란히 화면에 보여준다. kind='answer' 는 학생 질문에 대한 답, "
                    "kind='teacher' 는 교사 설명 문장의 나란히 보기.",
     "input_schema": _schema({"student_id": {"type": "string"}, "kind": {"type": "string", "enum": ["answer", "teacher"]},
                              "original_text": {"type": "string", "description": "학생 질문 원문 또는 교사 원래 문장"},
                              "korean_text": {"type": "string"}, "native_text": {"type": "string"},
                              "vocab_cards": {"type": "array", "items": _CARD}},
                             ["student_id", "kind", "korean_text", "native_text"])},
    {"name": "present_support_plan",
     "description": "비계 단계 조정 결과와 다음 수업 지원 계획을 교사에게 화면으로 보여준다.",
     "input_schema": _schema({"student_id": {"type": "string"}, "new_level": {"type": "integer"},
                              "message_to_teacher": {"type": "string"},
                              "next_steps": {"type": "array", "items": {"type": "string"}}},
                             ["student_id", "new_level", "message_to_teacher", "next_steps"])},
]

TOOL_FUNCS = {
    "get_student_profile": get_student_profile,
    "run_diagnostic_quiz": run_diagnostic_quiz,
    "decide_scaffold_level": decide_scaffold_level,
    "check_readability": check_readability,
    "rewrite_easy_korean": rewrite_easy_korean,
    "find_difficult_words": find_difficult_words,
    "make_vocab_cards": make_vocab_cards,
    "translate_text": translate_text,
    "grade_check_answers": grade_check_answers,
    "present_lesson_material": present_lesson_material,
    "present_bilingual": present_bilingual,
    "present_support_plan": present_support_plan,
}

TOOL_LABELS = {
    "get_student_profile": "👤 학생 정보 확인",
    "run_diagnostic_quiz": "📝 한국어 수준 진단",
    "decide_scaffold_level": "🪜 비계 단계 결정",
    "check_readability": "🔍 읽기 쉬운지 검사",
    "rewrite_easy_korean": "✏️ 쉬운 한국어로 바꾸기",
    "find_difficult_words": "🔎 어려운 낱말 찾기",
    "make_vocab_cards": "🃏 어휘 카드 만들기",
    "translate_text": "🌐 모국어 번역",
    "grade_check_answers": "✅ 확인 문제 채점",
    "present_lesson_material": "📄 학습 자료 보여주기",
    "present_bilingual": "↔️ 이중언어 나란히 보여주기",
    "present_support_plan": "📋 지원 계획 보여주기",
}


def execute(state: AgentState, name: str, args: dict) -> dict:
    func = TOOL_FUNCS.get(name)
    if not func:
        raise ToolError(f"없는 도구입니다: {name}")
    return func(state, **args)
