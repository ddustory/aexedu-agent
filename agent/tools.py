"""에이전트가 스스로 골라 쓰는 도구(tool) 모음.

각 도구는 (1) Claude 에게 보여줄 설명/입력 형식(TOOL_SCHEMAS)과
(2) 실제로 실행되는 파이썬 함수(TOOL_FUNCS)로 이루어진다.
모든 도구는 `reason`(지금 이 도구를 쓰는 이유)을 받아 화면 트레이스에 보여준다.
"""

import re
from dataclasses import dataclass, field

from . import data, llm, pocket
from .config import (
    COVERAGE_MIN,
    KNOWN_AFTER_CORRECT,
    MAX_NEW_WORDS,
    CHECK_DOWN_THRESHOLD,
    CHECK_UP_THRESHOLD,
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
    last_personal: dict = field(default_factory=dict)  # 학생ID → 마지막 '아는 낱말 맞춤' 결과
    last_peer: dict = field(default_factory=dict)      # 학생ID → 마지막 또래 연결 결과
    pocket: dict = field(default_factory=dict)         # 학생ID → 낱말 주머니 기록 (반응으로 바뀐 낱말)
    last_coverage: dict = field(default_factory=dict)  # 학생ID → 마지막 '아는 낱말 비율' 검사 결과


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
        rule = (f"진단 정답률 {score_percent:.0f}% → 기준표(80% 이상 3단계 / 50% 이상 2단계 / 그 미만 1단계)에 따라 "
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
        if "\ufffd" in out:  # 글자가 깨져 나오면 한 번 더 번역한다
            out = llm.complete_text(TRANSLATE_SYSTEM, f"모국어: {LANGUAGE_NAMES[language]}\n\n{text}")
        out = out.replace("\ufffd", "")
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
    _need_korean(korean_text, "korean_text")
    state.outputs.append({
        "kind": "lesson", "student_id": student_id, "level": level,
        "korean_text": korean_text, "native_text": native_text,
        "vocab_cards": vocab_cards, "teacher_note": teacher_note,
        "coverage": _coverage_for(state, student_id, korean_text),
    })
    return {"shown": True, "_summary": f"학습 자료를 화면에 표시함 ({level}단계)"}


def _coverage_for(state: AgentState, student_id: str, text: str) -> dict:
    """화면에 보여줄 글의 '아는 낱말' 검사 결과. 이미 잰 글이면 그 결과를, 아니면 지금 잰다."""
    last = state.last_coverage.get(student_id)
    if last and " ".join(last["text"].split()) == " ".join((text or "").split()):
        return last
    a = pocket.analyze(state, student_id, text)
    return {k: v for k, v in a.items() if k != "items"} | {"text": text}


def hangul_ratio(text: str) -> float:
    """글자 중 한글 비율 (공백·숫자·문장부호 제외)."""
    letters = [c for c in text or "" if c.isalpha()]
    if not letters:
        return 0.0
    return sum("\uac00" <= c <= "\ud7a3" for c in letters) / len(letters)


def _need_korean(text: str, field: str):
    if hangul_ratio(text) < 0.6:
        raise ToolError(f"{field} 에 한국어가 아닌 글이 들어왔습니다. {field} 는 반드시 쉬운 한국어로 써야 합니다. "
                        "학생 질문의 답은 answer_student_question 으로, 모국어는 translate_text 로 따로 만드세요.")


ANSWER_SYSTEM = """당신은 한국 초등학교 교사입니다. 한국어를 배우는 이주배경 학생의 질문에 답합니다.
반드시 지킬 것:
- 답은 오직 한국어로만 씁니다. 학생의 모국어를 쓰지 않습니다.
- 쉬운 한국어, '-해요'체, 한 문장은 10어절 이하, 3~4문장, 한 문장씩 줄을 바꿉니다.
- 질문을 그대로 되풀이하지 말고, 왜 그런지 과학적 까닭을 차례대로 설명합니다.
- 오늘 수업 낱말(수증기, 증발, 응결, 구름, 물방울, 강수)을 알맞게 씁니다.
예) 질문: 비는 왜 와요?
답:
바다와 강의 물이 수증기가 되어 하늘로 올라가요.
하늘은 차가워서 수증기가 작은 물방울이 돼요.
물방울이 모여 구름이 되고, 점점 무거워져요.
무거워진 물방울이 땅으로 떨어지는 것이 비예요.
답 글만 출력합니다."""


def answer_student_question(state: AgentState, student_id: str, question: str, reason: str = "") -> dict:
    s = _need_student(student_id)
    if llm.online():
        known = ", ".join(pocket.known_examples(state, student_id, 120))
        prompt = (f"학생 모국어: {s['home_language_name']}\n학생 질문(모국어): {question}\n"
                  f"이 학생이 아는 낱말(되도록 이 낱말로 쓰세요): {known}\n"
                  "먼저 질문의 뜻을 이해한 뒤, 쉬운 한국어로만 답하세요. 질문을 다시 쓰지 말고 답만 쓰세요.")
        out = llm.complete_text(ANSWER_SYSTEM, prompt)
        if hangul_ratio(out) < 0.6:  # 작은 모델이 모국어로 답하면 한 번 더 분명하게 요청
            out = llm.complete_text(ANSWER_SYSTEM, prompt + "\n\n주의: 방금 답이 한국어가 아니었습니다. 한국어로만 다시 쓰세요.")
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        lines = [ln for ln in lines if not ln.endswith("?") and not ln.startswith(("답:", "질문:"))] or lines
        out = "\n".join(ln.removeprefix("답:").strip() for ln in lines)
        _need_korean(out, "answer")
    else:
        preset = data.offline_demo()["student_questions"].get(s["home_language"], {})
        if " ".join(preset.get("question", "").split()) != " ".join(question.split()):
            raise llm.OfflineUnsupported("오프라인 시연 모드에서는 예시 질문에만 답할 수 있어요.")
        out = preset["korean_easy"]
    return {"korean_answer": out, "_summary": f"쉬운 한국어 답 {len(_sentences(out))}문장 작성"}


def present_bilingual(state: AgentState, student_id: str, kind: str, korean_text: str, native_text: str,
                      original_text: str = "", vocab_cards: list[dict] | None = None,
                      reason: str = "") -> dict:
    _need_korean(korean_text, "korean_text")
    if hangul_ratio(native_text) > 0.6:
        raise ToolError("native_text 가 한국어입니다. translate_text 로 학생 모국어 번역을 만들어 native_text 에 넣으세요.")
    state.outputs.append({
        "kind": "bilingual", "mode": kind, "student_id": student_id,
        "original_text": original_text, "korean_text": korean_text,
        "native_text": native_text, "vocab_cards": vocab_cards or [],
        "coverage": _coverage_for(state, student_id, korean_text) if kind == "answer" else None,
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


# ── 10. 학생별 '아는 낱말' 맞춤 (파파고와 다른 점) ──────────────
# 번역기는 같은 입력에 늘 같은 출력 하나를 낸다. 이 도구들은 '이 학생이 아는 낱말' 안에서
# 표현을 바꿔, 같은 글이라도 학생마다 다른 글을 만든다.

MARK_OPEN, MARK_CLOSE = "⟦", "⟧"      # 바뀐 표현 표시 (화면에서 형광펜)
NOTE_OPEN, NOTE_CLOSE = "⟪", "⟫"      # 핵심 용어 풀이 표시


def _need_student(student_id: str) -> dict:
    s = data.student(student_id)
    if not s:
        raise ToolError(f"학생 {student_id} 를 찾을 수 없습니다.")
    return s


def _effective_band(s: dict, ease_step: int) -> int:
    return s["vocab_band"] - ease_step


def _pick_option(opts: dict, band: int) -> str:
    levels = sorted(int(k) for k in opts)
    ok = [lv for lv in levels if lv <= band]
    return opts[str(max(ok) if ok else min(levels))]


def _scan_words(text: str, s: dict, ease_step: int) -> tuple[list, list]:
    """글에서 학생이 모를 낱말(바꿀 것)과 아는 낱말(그대로 둘 것)을 찾는다."""
    band = max(_effective_band(s, ease_step), 0)
    change, keep = [], []
    for w in data.word_levels():
        for form, opts in w["forms"].items():
            if form not in text:
                continue
            observed = w["word"] in s.get("known_extra", [])
            if w["band"] <= band:
                keep.append({"word": w["word"], "form": form, "why": f"학생이 아는 수준의 낱말 (난이도 {w['band']} ≤ {band})"})
            elif observed and ease_step == 0:
                keep.append({"word": w["word"], "form": form, "why": "교사가 '이 학생은 안다'고 관찰한 낱말"})
            else:
                to = _pick_option(opts, band)
                if to != form:
                    change.append({"word": w["word"], "form": form, "to": to,
                                   "why": f"난이도 {w['band']} 낱말 → 학생 수준 {band}에 맞는 말로"})
    change.sort(key=lambda c: -len(c["form"]))  # 긴 표현부터 바꿔야 겹치지 않는다
    return change, keep


def _core_notes(text: str, band: int, ease_step: int) -> list[dict]:
    """'좀 더 쉽게'를 요청한 초급 학생에게는 핵심 용어 뒤에 짧은 풀이를 붙인다(용어 자체는 그대로)."""
    if ease_step < 1 or band > 1:
        return []
    notes = []
    for g in data.glossary():
        form = next((f for f in g["forms"] if f in text), None)
        if form and f"{form}(" not in text:
            notes.append({"word": g["word"], "form": form, "note": g["easy"]})
    return notes


def _insert_note(text: str, form: str, note: str) -> str:
    """핵심 용어의 첫 등장 뒤에 풀이를 붙인다. 바뀐 표현(⟦…⟧) 안이면 그 표현이 끝난 뒤에 붙인다."""
    i = text.find(form)
    if i < 0:
        return text
    end = i + len(form)
    if text.count(MARK_OPEN, 0, i) > text.count(MARK_CLOSE, 0, i):
        end = text.index(MARK_CLOSE, i) + len(MARK_CLOSE)
    return text[:end] + note + text[end:]


def check_known_words(state: AgentState, student_id: str, text: str, ease_step: int = 0, reason: str = "") -> dict:
    s = _need_student(student_id)
    ease_step = int(ease_step)
    band = _effective_band(s, ease_step)
    change, keep = _scan_words(text, s, ease_step)
    notes = _core_notes(text, max(band, 0), ease_step)
    full = band < 0
    return {
        "student_id": student_id,
        "student_vocab_band": s["vocab_band"],
        "ease_step": ease_step,
        "effective_band": max(band, 0),
        "words_to_change": change,
        "words_kept": keep,
        "core_terms_to_explain": [n["word"] for n in notes],
        "needs_full_rewrite": full,
        "_summary": (f"학생 낱말 수준 {max(band, 0)} 기준 · 바꿀 낱말 {len(change)}개"
                     + (f" ({', '.join(c['form'] for c in change[:4])}{'…' if len(change) > 4 else ''})" if change else "")
                     + f" · 그대로 둘 낱말 {len(keep)}개"
                     + (" · 낱말 바꾸기만으로는 더 쉽게 할 수 없어 문장 전체를 다시 써야 함" if full else "")),
    }


def personalize_wording(state: AgentState, student_id: str, text: str, ease_step: int = 0,
                        reason: str = "") -> dict:
    s = _need_student(student_id)
    ease_step = int(ease_step)
    band = max(_effective_band(s, ease_step), 0)
    change, _ = _scan_words(text, s, ease_step)
    marked = text
    for c in change:
        marked = marked.replace(c["form"], f"{MARK_OPEN}{c['to']}{MARK_CLOSE}")
    notes = _core_notes(text, band, ease_step)
    for n in notes:
        marked = _insert_note(marked, n["form"], f"{NOTE_OPEN}({n['note']}){NOTE_CLOSE}")
    plain = marked
    for m in (MARK_OPEN, MARK_CLOSE, NOTE_OPEN, NOTE_CLOSE):
        plain = plain.replace(m, "")
    state.last_personal[student_id] = {
        "input_text": text, "marked_text": marked, "text": plain,
        "changes": [{"from": c["form"], "to": c["to"]} for c in change],
        "notes": [n["word"] for n in notes], "ease_step": ease_step, "effective_band": band,
    }
    return {
        "student_id": student_id,
        "personalized_text": plain,
        "changes": [{"from": c["form"], "to": c["to"]} for c in change],
        "explained_terms": [n["word"] for n in notes],
        "_summary": (f"{len(change)}곳을 이 학생이 아는 말로 바꿈"
                     + (f" · 핵심 용어 {len(notes)}개에 풀이 붙임" if notes else "")
                     + (" · 바꿀 낱말 없음(이미 학생 수준)" if not change and not notes else "")),
    }


def present_personalized(state: AgentState, student_id: str, message: str, original_text: str = "",
                         reason: str = "") -> dict:
    p = state.last_personal.get(student_id)
    if not p:
        raise ToolError("먼저 personalize_wording 으로 학생 맞춤 글을 만들어야 합니다.")
    state.outputs.append({"kind": "personal", "student_id": student_id, "message": message,
                          "original_text": original_text or p["input_text"], **p,
                          "coverage": _coverage_for(state, student_id, p["text"])})
    return {"shown": True, "_summary": f"학생 맞춤 글을 화면에 표시함 (쉽게 {p['ease_step']}단계)"}


# ── 11. 지역 너머 또래 연결 (미리보기) ───────────────────────────

def _grade_num(g: str) -> int:
    m = re.search(r"(\d+)", g or "")
    return int(m.group(1)) if m else 0


ACTIVITIES = {
    1: "그림 어휘 카드를 보며 낱말 맞히기 게임 (막히면 그림으로 힌트 주기)",
    2: "오늘 배운 낱말로 짧은 문장 만들기 릴레이",
    3: "짧은 글을 읽고 한국어로 생각 나누기",
}


def find_peer_group(state: AgentState, student_id: str, mode: str, reason: str = "") -> dict:
    s = _need_student(student_id)
    level = state.levels.get(student_id)
    if level is None:
        raise ToolError("이 학생의 지원 단계가 아직 없습니다. 먼저 진단으로 단계를 정해 주세요.")
    if mode not in ("same_language", "mixed_language"):
        raise ToolError("mode 는 'same_language' 또는 'mixed_language' 여야 합니다.")
    pool = [dict(p, source="또래 연결망") for p in data.peers()]
    for o in data.students():  # 우리 반 다른 가상 학생도 단계가 정해졌다면 후보
        if o["id"] != student_id and state.levels.get(o["id"]):
            pool.append({"id": o["id"], "display_name": o["display_name"].split(" ")[0], "region": o["region"],
                         "center": "우리 반", "home_language": o["home_language"],
                         "home_language_name": o["home_language_name"], "level": state.levels[o["id"]],
                         "grade": o["grade"], "interests": [], "source": "우리 반"})
    lang = s["home_language"]
    if mode == "same_language":
        cands = [p for p in pool if p["home_language"] == lang]
    else:
        cands = [p for p in pool if p["home_language"] != lang]
    cands = [p for p in cands if abs(p["level"] - level) <= 1]
    my_grade = _grade_num(s["grade"])
    cands.sort(key=lambda p: (abs(p["level"] - level), abs(_grade_num(p["grade"]) - my_grade)))

    group, used_langs = [], {lang}
    if mode == "mixed_language":  # 모국어가 겹치지 않게 먼저 고르고, 모자라면 채운다
        for p in cands:
            if len(group) < 3 and p["home_language"] not in used_langs:
                group.append(p)
                used_langs.add(p["home_language"])
    for p in cands:
        if len(group) < 3 and p not in group:
            group.append(p)

    local = [p for p in cands if p["region"] == s["region"]]
    members = []
    for p in group:
        why = ["같은 단계" if p["level"] == level else f"단계 차이 1 ({p['level']}단계)"]
        if _grade_num(p["grade"]) == my_grade:
            why.append("같은 학년")
        why.append("같은 지역" if p["region"] == s["region"] else f"다른 지역({p['region']})")
        members.append({"name": p["display_name"], "region": p["region"], "center": p["center"],
                        "language": p["home_language_name"], "level": p["level"], "grade": p["grade"],
                        "interests": p.get("interests", []), "why": " · ".join(why)})
    talk = ("서로 모국어가 달라서, 모둠 안의 공통 언어는 한국어가 됩니다. 자연스럽게 한국어로 말할 기회가 늘어나요."
            if mode == "mixed_language" else
            "같은 모국어 친구와 어려운 개념을 모국어로 먼저 이해하고, 한국어 표현으로 함께 정리해요.")
    result = {
        "student": s["display_name"], "student_region": s["region"], "level": level, "mode": mode,
        "members": members, "local_candidates": len(local), "nationwide_candidates": len(cands),
        "activity": ACTIVITIES[level], "talk_language": talk,
    }
    state.last_peer[student_id] = result
    return {**result, "_summary": (f"조건에 맞는 친구: 같은 지역 {len(local)}명 → 지역을 넘으면 {len(cands)}명 · "
                                   f"모둠 {len(members) + 1}명 구성")}


def present_peer_group(state: AgentState, student_id: str, message: str, reason: str = "") -> dict:
    p = state.last_peer.get(student_id)
    if not p:
        raise ToolError("먼저 find_peer_group 으로 모둠을 만들어야 합니다.")
    state.outputs.append({"kind": "peers", "student_id": student_id, "message": message, **p})
    return {"shown": True, "_summary": f"또래 모둠 {len(p['members']) + 1}명을 화면에 표시함"}


# ── 12. 학생별 낱말 주머니: 재고 → 고치고 → 다시 재기 ─────────────
# 기준(교사 확정): 아는 낱말 80% 이상, 새 낱말 3개까지, 3번 맞히면 '아는 낱말'.

def get_word_pocket(state: AgentState, student_id: str, reason: str = "") -> dict:
    _need_student(student_id)
    sm = pocket.summary(state, student_id)
    learning = ", ".join(f"{w}({n}/{KNOWN_AFTER_CORRECT})" for w, n in sm["learning"].items())
    return {
        **{k: v for k, v in sm.items()},
        "rules": f"아는 낱말 {COVERAGE_MIN}% 이상 · 새 낱말 {MAX_NEW_WORDS}개까지 · {KNOWN_AFTER_CORRECT}번 맞히면 아는 낱말",
        "_summary": (f"아는 낱말 {sm['known_count']}개 · 배우는 중 {len(sm['learning'])}개"
                     + (f" ({learning})" if learning else "")
                     + (f" · '몰라요' 표시 {len(sm['marked_unknown'])}개" if sm["marked_unknown"] else "")),
    }


def check_coverage(state: AgentState, student_id: str, text: str, reason: str = "") -> dict:
    _need_student(student_id)
    a = pocket.analyze(state, student_id, text)
    state.last_coverage[student_id] = {k: v for k, v in a.items() if k != "items"} | {"text": text}
    verdict = "✅ 통과" if a["passed"] else "❌ 기준 미달"
    return {
        **{k: v for k, v in a.items() if k != "items"},
        "_summary": (f"{verdict} · 아는 낱말 {a['coverage']}% (기준 {COVERAGE_MIN}%) · 새 낱말 {len(a['new_words'])}개 "
                     f"(기준 {MAX_NEW_WORDS}개)" + (f": {', '.join(a['new_words'][:6])}" if a["new_words"] else "")
                     + (f" · 오늘은 미룰 핵심 용어: {', '.join(a['terms_to_defer'])}" if not a["passed"] and a["terms_to_defer"] else "")),
    }


ADAPT_SYSTEM = """당신은 한국어를 배우는 이주배경 초등학생을 위한 글 고치기 전문가입니다.
주어진 글을 이 학생이 아는 낱말로 고쳐 씁니다. 반드시 지킬 것:
- [바꿀 낱말]은 학생이 모르는 말입니다. [학생이 아는 낱말]에 있는 쉬운 말로 바꿉니다.
- [남길 핵심 용어]는 오늘 배울 낱말이니 그대로 둡니다.
- [미룰 핵심 용어]는 오늘 가르치지 않습니다. 그 용어를 쓰지 말고 뜻을 쉬운 말로 풀어 씁니다.
- 내용(과학적 사실)은 바꾸지 않습니다. 줄 수와 줄 바꿈은 원래 글과 같게 둡니다.
- 한국어로만, 고친 글만 출력합니다."""


def adapt_to_pocket(state: AgentState, student_id: str, text: str, words_to_replace: list[str] | None = None,
                    terms_to_defer: list[str] | None = None, terms_to_keep: list[str] | None = None,
                    reason: str = "") -> dict:
    s = _need_student(student_id)
    rep, defer, keep = list(words_to_replace or []), list(terms_to_defer or []), list(terms_to_keep or [])
    if not rep and not defer:
        return {"adapted_text": text, "changes": [], "_summary": "바꿀 낱말이 없어 그대로 둠"}
    changes, out = [], text
    if llm.online():
        known = ", ".join(pocket.known_examples(state, student_id, 150))
        prompt = (f"[바꿀 낱말] {', '.join(rep) or '없음'}\n[남길 핵심 용어] {', '.join(keep) or '없음'}\n"
                  f"[미룰 핵심 용어] {', '.join(defer) or '없음'}\n[학생이 아는 낱말] {known}\n\n[글]\n{text}")
        out = llm.complete_text(ADAPT_SYSTEM, prompt)
        if hangul_ratio(out) < 0.6 or not out.strip():
            raise ToolError("고친 글이 한국어가 아니었습니다. 다시 시도해 주세요.")
        changes = [{"from": w, "to": "(AI가 아는 말로 바꿈)"} for w in rep] + [{"from": t, "to": "(용어 없이 풀어 씀)"} for t in defer]
    else:
        band = 0
        table = sorted(((form, opts) for w in data.word_levels() for form, opts in w["forms"].items()),
                       key=lambda fo: -len(fo[0]))
        for form, opts in table:
            first = pocket.tokens(form)[0] if pocket.tokens(form) else form
            if form in out and pocket.lookup(first)[0] in rep:
                to = _pick_option(opts, band)
                out = out.replace(form, to)
                changes.append({"from": form, "to": to})
        for term in defer:
            for r in sorted(data.defer_terms().get(term, []), key=lambda r: -len(r["from"])):
                if r["from"] in out and r["from"] != r["to"]:
                    out = out.replace(r["from"], r["to"])
                    changes.append({"from": r["from"].strip(), "to": r["to"] or "(문장 빼기)"})
        out = re.sub(r"[ \t]+\n", "\n", out).strip()
    left = [w for w in rep if w in [pocket.lookup(t)[0] for t in pocket.tokens(out)]]
    return {
        "adapted_text": out, "changes": changes, "deferred_terms": defer,
        "not_replaced": left,
        "_summary": (f"{len(changes)}곳을 {data.subj(s['display_name'].split(' ')[0])} 아는 말로 고침"
                     + (f" · 용어 없이 풀어 쓴 핵심 용어: {', '.join(defer)}" if defer else "")
                     + (f" · 못 바꾼 낱말: {', '.join(left)}" if left else "")),
    }


def record_word_feedback(state: AgentState, student_id: str, word: str, result: str, reason: str = "") -> dict:
    _need_student(student_id)
    try:
        rec = pocket.record(state, student_id, word, result)
    except ValueError as e:
        raise ToolError(str(e))
    label = {"known": "아는 낱말로 옮김 🎉", "learning": f"배우는 중 ({rec['correct']}/{KNOWN_AFTER_CORRECT})",
             "unknown": "모르는 낱말로 표시 → 다음 글에서 쉬운 말로 바꿈"}[rec["status"]]
    return {**rec, "_summary": f"'{word}' {label}"}


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
    {"name": "answer_student_question",
     "description": "학생이 모국어로 한 질문에 쉬운 한국어로만 답을 쓴다(3~4문장, 과학적 까닭 설명). "
                    "학생 질문에 답할 때 가장 먼저 쓰고, 그 결과를 translate_text 로 모국어로 옮긴다.",
     "input_schema": _schema({"student_id": {"type": "string"}, "question": {"type": "string"}},
                             ["student_id", "question"])},
    {"name": "get_word_pocket",
     "description": "학생의 '낱말 주머니'(아는 낱말 수, 배우는 중인 낱말, 학생이 '몰라요'라고 한 낱말)와 교사가 정한 기준을 본다. "
                    "학생용 글을 쓰기 전에 먼저 쓴다.",
     "input_schema": _schema({"student_id": {"type": "string"}}, ["student_id"])},
    {"name": "check_coverage",
     "description": "글을 낱말 단위로 나눠 이 학생이 아는 낱말 비율(기준 80% 이상)과 새 낱말 수(기준 3개까지)를 잰다. "
                    "통과하지 못하면 words_to_replace(아는 말로 바꿀 낱말), terms_to_keep(오늘 가르칠 핵심 용어), "
                    "terms_to_defer(오늘은 미룰 핵심 용어)를 adapt_to_pocket 에 그대로 넘긴다.",
     "input_schema": _schema({"student_id": {"type": "string"}, "text": {"type": "string"}}, ["student_id", "text"])},
    {"name": "adapt_to_pocket",
     "description": "check_coverage 결과대로 글을 이 학생이 아는 낱말로 고쳐 쓴다. 고친 뒤에는 반드시 check_coverage 로 다시 잰다(최대 2번 반복).",
     "input_schema": _schema({"student_id": {"type": "string"}, "text": {"type": "string"},
                              "words_to_replace": {"type": "array", "items": {"type": "string"}},
                              "terms_to_keep": {"type": "array", "items": {"type": "string"}},
                              "terms_to_defer": {"type": "array", "items": {"type": "string"}}},
                             ["student_id", "text"])},
    {"name": "record_word_feedback",
     "description": "학생 반응을 낱말 주머니에 기록한다. result='dont_know'(몰라요) 이면 모르는 낱말로, "
                    "'correct'(맞혔어요) 이면 맞힌 횟수를 올려 3번이면 아는 낱말로 옮긴다.",
     "input_schema": _schema({"student_id": {"type": "string"}, "word": {"type": "string"},
                              "result": {"type": "string", "enum": ["dont_know", "correct"]}},
                             ["student_id", "word", "result"])},
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
    {"name": "check_known_words",
     "description": "학생별 '아는 낱말' 기록(낱말 수준 + 교사 관찰)과 비교해, 글에서 이 학생이 모를 낱말과 그대로 둬도 되는 낱말을 찾는다. "
                    "ease_step 은 학생이 '좀 더 쉽게'를 요청한 횟수(0=처음)로, 클수록 더 쉬운 말을 쓴다. "
                    "needs_full_rewrite 가 true 면 낱말 바꾸기만으로는 부족하니 rewrite_easy_korean(level=1)로 먼저 다시 쓴다.",
     "input_schema": _schema({"student_id": {"type": "string"}, "text": {"type": "string"},
                              "ease_step": {"type": "integer", "minimum": 0}}, ["student_id", "text"])},
    {"name": "personalize_wording",
     "description": "check_known_words 기준대로 글의 어려운 표현을 이 학생이 아는 말로 바꾼다. 교과 핵심 용어는 바꾸지 않고, "
                    "'좀 더 쉽게'를 요청한 초급 학생에게는 핵심 용어 뒤에 짧은 풀이를 붙인다. 같은 글도 학생마다 결과가 다르다.",
     "input_schema": _schema({"student_id": {"type": "string"}, "text": {"type": "string"},
                              "ease_step": {"type": "integer", "minimum": 0}}, ["student_id", "text"])},
    {"name": "present_personalized",
     "description": "personalize_wording 으로 만든 학생 맞춤 글(바뀐 곳 표시)을 원래 글과 함께 화면에 보여준다.",
     "input_schema": _schema({"student_id": {"type": "string"},
                              "original_text": {"type": "string", "description": "교사가 처음 준 글"},
                              "message": {"type": "string", "description": "학생에게 건네는 짧은 쉬운 한국어 한마디"}},
                             ["student_id", "message"])},
    {"name": "find_peer_group",
     "description": "지역과 상관없이 한국어 지원 단계와 학년이 비슷한 또래를 찾아 4명 모둠을 만든다. "
                    "mode='same_language' 는 같은 모국어 친구끼리, mode='mixed_language' 는 모국어가 서로 달라 한국어로 대화하는 모둠. "
                    "같은 지역 안 후보 수와 전국 후보 수도 알려준다. 학생의 지원 단계가 먼저 정해져 있어야 한다.",
     "input_schema": _schema({"student_id": {"type": "string"},
                              "mode": {"type": "string", "enum": ["same_language", "mixed_language"]}},
                             ["student_id", "mode"])},
    {"name": "present_peer_group",
     "description": "find_peer_group 으로 만든 또래 모둠과 함께 할 활동을 화면에 보여준다.",
     "input_schema": _schema({"student_id": {"type": "string"},
                              "message": {"type": "string", "description": "교사에게 주는 짧은 안내"}},
                             ["student_id", "message"])},
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
    "answer_student_question": answer_student_question,
    "get_word_pocket": get_word_pocket,
    "check_coverage": check_coverage,
    "adapt_to_pocket": adapt_to_pocket,
    "record_word_feedback": record_word_feedback,
    "check_known_words": check_known_words,
    "personalize_wording": personalize_wording,
    "present_personalized": present_personalized,
    "find_peer_group": find_peer_group,
    "present_peer_group": present_peer_group,
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
    "answer_student_question": "💡 쉬운 한국어로 답 쓰기",
    "get_word_pocket": "🧺 낱말 주머니 보기",
    "check_coverage": "📏 아는 낱말 비율 재기",
    "adapt_to_pocket": "🛠️ 학생이 아는 낱말로 고쳐 쓰기",
    "record_word_feedback": "📝 학생 반응 기록",
    "check_known_words": "🧩 학생이 아는 낱말인지 확인",
    "personalize_wording": "🪄 학생이 아는 말로 바꾸기",
    "present_personalized": "📄 학생 맞춤 글 보여주기",
    "find_peer_group": "🤝 지역 너머 또래 찾기",
    "present_peer_group": "📋 또래 모둠 보여주기",
}


def execute(state: AgentState, name: str, args: dict) -> dict:
    func = TOOL_FUNCS.get(name)
    if not func:
        raise ToolError(f"없는 도구입니다: {name}")
    return func(state, **args)
