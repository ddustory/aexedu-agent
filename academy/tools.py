"""학원 수업 도우미 에이전트의 도구 모음.

📒 알림장 에이전트: 교사가 오늘 진도·숙제·앞으로의 진도를 주면 학부모용/학생용 알림장을 쓰고 스스로 검사한다.
📊 학력평가 분석 에이전트: 월말 국어 학력평가를 문항·성취기준·학생별로 분석하고, 지난 성적과 연결한다.

모든 학생·시험은 시연용 가상 데이터다.
"""

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from statistics import mean

from agent import llm
from agent.config import DATA_DIR

ACADEMY_DIR = DATA_DIR / "academy"


class ToolError(Exception):
    pass


@dataclass
class AcademyState:
    outputs: list = field(default_factory=list)
    last_exam: dict = field(default_factory=dict)      # 시험ID → 분석 결과
    last_student: dict = field(default_factory=dict)   # 학생ID → 분석 결과 모음
    notices: dict = field(default_factory=dict)        # 대상 → 마지막 알림장 초안


# ── 데이터 ───────────────────────────────────────────────────────

@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    return json.loads((ACADEMY_DIR / name).read_text(encoding="utf-8"))


def students() -> list[dict]:
    return _load("students.json")["students"]


def student(sid: str) -> dict:
    s = next((x for x in students() if x["id"] == sid), None)
    if not s:
        raise ToolError(f"학생 {sid} 를 찾을 수 없습니다.")
    return s


def standards() -> dict:
    return {s["id"]: s for s in _load("exams.json")["standards"]}


def exams(grade: int | None = None) -> list[dict]:
    ex = _load("exams.json")["exams"]
    return [e for e in ex if grade is None or e["grade"] == grade]


def exam(eid: str) -> dict:
    e = next((x for x in exams() if x["id"] == eid), None)
    if not e:
        raise ToolError(f"시험 {eid} 를 찾을 수 없습니다.")
    return e


def answers(eid: str) -> dict:
    return {r["student_id"]: r["answers"] for r in _load("results.json")["results"] if r["exam_id"] == eid}


def _score(e: dict, ans: list[int]) -> int:
    return sum(it["points"] for it, a in zip(e["items"], ans) if a == it["answer"])


def _month(e: dict) -> str:
    return f"{int(e['month'][-2:])}월"


# ── 📒 알림장 ─────────────────────────────────────────────────────

def get_class_overview(state: AcademyState, grade: int, reason: str = "") -> dict:
    grade = int(grade)
    ss = [s for s in students() if s["grade"] == grade]
    if not ss:
        raise ToolError(f"중{grade} 반 학생이 없습니다.")
    langs = Counter(s["parent_language_name"] for s in ss)
    other = {s["parent_language"]: s["parent_language_name"] for s in ss if s["parent_language"] != "ko"}
    return {
        "class": ss[0]["class"], "student_count": len(ss), "parent_languages": dict(langs),
        "translation_needed": [{"code": c, "name": n} for c, n in other.items()],
        "_summary": f"{ss[0]['class']} {len(ss)}명 · 학부모 언어: " + ", ".join(f"{k} {v}명" for k, v in langs.items()),
    }


def _bullets(text: str) -> list[str]:
    lines = [re.sub(r"^\s*(?:[-•·*]|\d+[.)])\s*", "", ln).strip() for ln in (text or "").splitlines()]
    return [ln for ln in lines if ln]


NOTICE_SYSTEM = {
    "parent": """당신은 학원 국어 교사입니다. 학부모에게 보낼 알림장을 씁니다.
- 정중한 '-습니다/-ㅂ니다'체. 반말 금지. 400자 안팎.
- 반드시 세 부분을 이 순서로: ■ 오늘 수업 진도 / ■ 숙제 / ■ 앞으로의 진도 계획
- 교사가 준 내용만 쓰고, 없는 사실(점수·행사 등)을 지어내지 않습니다.
- 마지막에 가정에서 도와주실 점 한 문장과 인사. 알림장 글만 출력합니다.""",
    "student": """당신은 학원 국어 선생님입니다. 중학생에게 보낼 알림장을 씁니다.
- 친근하지만 바른 말투(가벼운 반말 가능), 이모지 2~3개, 250자 안팎.
- 반드시 세 부분: 오늘 배운 것 / 숙제 / 다음 시간
- 교사가 준 내용만 쓰고 지어내지 않습니다. 짧은 응원 한마디로 끝냅니다. 알림장 글만 출력합니다.""",
}


def draft_notice(state: AcademyState, audience: str, class_name: str, today_progress: str, homework: str,
                 next_plan: str, reason: str = "") -> dict:
    if audience not in NOTICE_SYSTEM:
        raise ToolError("audience 는 'parent' 또는 'student' 여야 합니다.")
    if llm.online():
        prompt = (f"반: {class_name}\n[오늘 수업 진도]\n{today_progress}\n[숙제]\n{homework}\n"
                  f"[앞으로의 진도 계획]\n{next_plan}")
        text = llm.complete_text(NOTICE_SYSTEM[audience], prompt)
    else:
        t, h, n = _bullets(today_progress), _bullets(homework), _bullets(next_plan)
        if audience == "parent":
            text = (f"안녕하십니까, {class_name} 국어 담당 교사입니다. 오늘 수업 내용을 알려 드립니다.\n\n"
                    "■ 오늘 수업 진도\n" + "\n".join(f"- {x}" for x in t) + "\n\n"
                    "■ 숙제\n" + "\n".join(f"- {x}" for x in h) + "\n\n"
                    "■ 앞으로의 진도 계획\n" + "\n".join(f"- {x}" for x in n) + "\n\n"
                    "가정에서 숙제를 마쳤는지 한 번 확인해 주시면 큰 도움이 됩니다. 궁금하신 점은 언제든 연락 주십시오.\n"
                    "감사합니다.")
        else:
            text = (f"📒 {class_name} 오늘의 알림장\n\n"
                    "✅ 오늘 배운 것\n" + "\n".join(f"- {x}" for x in t) + "\n\n"
                    "📝 숙제\n" + "\n".join(f"- {x}" for x in h) + "\n\n"
                    "🚀 다음 시간\n" + "\n".join(f"- {x}" for x in n) + "\n\n"
                    "오늘도 수고 많았어! 숙제 잊지 말고 챙기자 💪")
    state.notices[audience] = {"text": text, "inputs": {"today": today_progress, "homework": homework,
                                                        "next": next_plan}, "translations": {}}
    return {"audience": audience, "notice": text,
            "_summary": f"{'학부모' if audience == 'parent' else '학생'}용 알림장 초안 {len(text)}자"}


_PHONE = re.compile(r"01[016789][-\s]?\d{3,4}[-\s]?\d{4}")
_RRN = re.compile(r"\d{6}[-\s]?[1-4]\d{6}")
_BANMAL = re.compile(r"(해!|하자|했어|할게|야!|거든|잖아|해\.|줘\.)")


def _covered(source: str, text: str) -> bool:
    """교사가 준 내용의 핵심 낱말(2글자 이상)이 절반 이상 알림장에 들어 있는가."""
    words = {w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", source or "")}
    if not words:
        return True
    return sum(w in text for w in words) / len(words) >= 0.5


def check_notice(state: AcademyState, audience: str, reason: str = "") -> dict:
    d = state.notices.get(audience)
    if not d:
        raise ToolError("먼저 draft_notice 로 알림장을 써야 합니다.")
    text, inp = d["text"], d["inputs"]
    problems = []
    for key, label in (("today", "오늘 수업 진도"), ("homework", "숙제"), ("next", "앞으로의 진도")):
        if not _covered(inp[key], text):
            problems.append(f"'{label}' 내용이 빠졌거나 너무 바뀌었습니다")
    if audience == "parent" and _BANMAL.search(text):
        problems.append("학부모용인데 반말 표현이 있습니다")
    limit = 700 if audience == "parent" else 450
    if len(text) > limit:
        problems.append(f"너무 깁니다 ({len(text)}자, 기준 {limit}자 이하)")
    if _PHONE.search(text) or _RRN.search(text):
        problems.append("전화번호·주민번호 같은 개인정보가 들어 있습니다")
    passed = not problems
    return {"audience": audience, "passed": passed, "problems": problems, "length": len(text),
            "_summary": ("✅ 통과" if passed else "❌ " + " / ".join(problems)) + f" · {len(text)}자"}


def translate_notice(state: AcademyState, audience: str, language_code: str, language_name: str,
                     reason: str = "") -> dict:
    d = state.notices.get(audience)
    if not d:
        raise ToolError("먼저 draft_notice 로 알림장을 써야 합니다.")
    if not llm.online():
        raise llm.OfflineUnsupported("번역은 AI 모드(로컬 AI 또는 Claude)에서 됩니다. 오프라인 시연에서는 한국어 알림장만 만듭니다.")
    out = llm.complete_text(f"학원 알림장을 {language_name}로 번역합니다. 학부모가 읽기 쉽게, 형식(■ 제목, 줄 바꿈)은 그대로 둡니다. "
                            "번역문만 출력합니다.", d["text"]).replace("�", "")
    d["translations"][language_name] = out
    return {"language": language_name, "translation": out, "_summary": f"{language_name} 번역 {len(out)}자"}


def present_notice(state: AcademyState, audience: str, message: str = "", reason: str = "") -> dict:
    d = state.notices.get(audience)
    if not d:
        raise ToolError("먼저 draft_notice 로 알림장을 써야 합니다.")
    state.outputs.append({"kind": "notice", "audience": audience, "text": d["text"],
                          "translations": dict(d["translations"]), "message": message})
    return {"shown": True, "_summary": f"{'학부모' if audience == 'parent' else '학생'}용 알림장을 화면에 표시함"}


# ── 📊 학력평가 분석 ──────────────────────────────────────────────

def list_exams(state: AcademyState, grade: int, reason: str = "") -> dict:
    ex = exams(int(grade))
    return {"exams": [{"id": e["id"], "title": e["title"], "month": e["month"]} for e in ex],
            "_summary": f"중{grade} 학력평가 {len(ex)}회: " + ", ".join(_month(e) for e in ex)}


def analyze_exam(state: AcademyState, exam_id: str, reason: str = "") -> dict:
    e = exam(exam_id)
    ans = answers(exam_id)
    n = len(ans)
    scores = {sid: _score(e, a) for sid, a in ans.items()}
    items = []
    for i, it in enumerate(e["items"]):
        picks = [a[i] for a in ans.values()]
        rate = round(sum(p == it["answer"] for p in picks) / n * 100)
        wrong = Counter(p for p in picks if p != it["answer"]).most_common(1)
        items.append({"no": it["no"], "standard": it["standard"], "title": it["title"], "rate": rate,
                      "attractive_wrong": wrong[0][0] if wrong else None,
                      "attractive_wrong_count": wrong[0][1] if wrong else 0})
    by_std = defaultdict(list)
    for it in items:
        by_std[it["standard"]].append(it["rate"])
    std_rates = sorted(({"standard": k, "area": standards()[k]["area"], "desc": standards()[k]["desc"],
                         "rate": round(mean(v))} for k, v in by_std.items()), key=lambda x: x["rate"])
    ranked = sorted(items, key=lambda x: x["rate"])
    res = {
        "exam_id": exam_id, "title": e["title"], "students": n, "average": round(mean(scores.values()), 1),
        "max": max(scores.values()), "min": min(scores.values()),
        "items": items, "low_items": ranked[:3], "high_items": ranked[::-1][:3], "standards": std_rates,
    }
    state.last_exam[exam_id] = res
    low = ", ".join(f"{x['no']}번({x['rate']}%)" for x in res["low_items"])
    high = ", ".join(f"{x['no']}번({x['rate']}%)" for x in res["high_items"])
    return {**{k: v for k, v in res.items() if k != "items"},
            "_summary": f"평균 {res['average']}점 · 정답률 낮은 문항 {low} · 높은 문항 {high} · "
                        f"가장 약한 성취기준: {std_rates[0]['desc']}({std_rates[0]['rate']}%)"}


def student_history(state: AcademyState, student_id: str, reason: str = "") -> dict:
    s = student(student_id)
    rows = []
    for e in exams(s["grade"]):
        ans = answers(e["id"])
        if student_id not in ans:
            continue
        all_scores = sorted((_score(e, a) for a in ans.values()), reverse=True)
        mine = _score(e, ans[student_id])
        rows.append({"exam_id": e["id"], "month": _month(e), "score": mine,
                     "class_avg": round(mean(all_scores), 1), "rank": all_scores.index(mine) + 1, "of": len(all_scores)})
    if not rows:
        raise ToolError("이 학생의 시험 기록이 없습니다.")
    delta = rows[-1]["score"] - rows[-2]["score"] if len(rows) > 1 else 0
    trend = rows[-1]["score"] - rows[0]["score"]
    state.last_student.setdefault(student_id, {})["history"] = rows
    return {"student": s["name"], "history": rows, "last_change": delta, "overall_change": trend,
            "_summary": " → ".join(f"{r['month']} {r['score']}점" for r in rows)
                        + f" · 지난달 대비 {delta:+d}점 · 첫 시험 대비 {trend:+d}점"}


def standard_profile(state: AcademyState, student_id: str, reason: str = "") -> dict:
    s = student(student_id)
    mine, cls = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for e in exams(s["grade"]):
        ans = answers(e["id"])
        for sid, a in ans.items():
            for it, pick in zip(e["items"], a):
                bucket = cls[it["standard"]]
                bucket[0] += pick == it["answer"]
                bucket[1] += 1
                if sid == student_id:
                    mine[it["standard"]][0] += pick == it["answer"]
                    mine[it["standard"]][1] += 1
    prof = []
    for k, (c, t) in mine.items():
        cc, ct = cls[k]
        prof.append({"standard": k, "area": standards()[k]["area"], "desc": standards()[k]["desc"],
                     "student_rate": round(c / t * 100), "class_rate": round(cc / ct * 100),
                     "gap": round(c / t * 100 - cc / ct * 100), "solved": f"{c}/{t}"})
    prof.sort(key=lambda x: x["gap"])
    state.last_student.setdefault(student_id, {})["profile"] = prof
    weak, strong = prof[:3], prof[::-1][:2]
    return {"profile": prof, "weakest": weak, "strongest": strong,
            "_summary": "약한 성취기준: " + ", ".join(f"{w['desc']}(반 평균보다 {w['gap']}%p)" for w in weak)
                        + " · 강한 성취기준: " + ", ".join(f"{x['desc']}({x['gap']:+d}%p)" for x in strong)}


def group_wrong_answers(state: AcademyState, student_id: str, exam_id: str, reason: str = "") -> dict:
    s = student(student_id)
    e = exam(exam_id)
    ans = answers(exam_id).get(student_id)
    if ans is None:
        raise ToolError("이 학생은 이 시험 기록이 없습니다.")
    wrong = defaultdict(list)
    for it, pick in zip(e["items"], ans):
        if pick != it["answer"]:
            wrong[it["standard"]].append({"no": it["no"], "title": it["title"], "picked": pick, "answer": it["answer"]})
    groups = []
    for std, its in wrong.items():
        # 지난 시험에서 같은 성취기준의 문항(유사 문항)과 그때 맞혔는지
        similar = []
        for pe in exams(s["grade"]):
            if pe["month"] >= e["month"]:
                continue
            pa = answers(pe["id"]).get(student_id)
            for it, pick in zip(pe["items"], pa or []):
                if it["standard"] == std:
                    similar.append({"exam": f"{_month(pe)}", "no": it["no"], "title": it["title"],
                                    "correct": pick == it["answer"]})
        hit = sum(x["correct"] for x in similar)
        pattern = ("반복 약점" if similar and hit / len(similar) < 0.5 else
                   "이번에만 틀림" if similar else "처음 나온 유형")
        groups.append({"standard": std, "area": standards()[std]["area"], "desc": standards()[std]["desc"],
                       "wrong_items": its, "similar_items": similar,
                       "past_correct": f"{hit}/{len(similar)}", "pattern": pattern})
    order = {"반복 약점": 0, "처음 나온 유형": 1, "이번에만 틀림": 2}
    groups.sort(key=lambda g: (order[g["pattern"]], -len(g["wrong_items"])))
    state.last_student.setdefault(student_id, {}).update(wrong_groups=groups, exam_id=exam_id)
    n = sum(len(g["wrong_items"]) for g in groups)
    rep = [g["desc"] for g in groups if g["pattern"] == "반복 약점"]
    return {"exam_id": exam_id, "wrong_count": n, "groups": groups,
            "_summary": f"틀린 {n}문항을 성취기준 {len(groups)}묶음으로 정리"
                        + (f" · 반복 약점: {', '.join(rep)}" if rep else " · 반복 약점 없음")}


FEEDBACK_SYSTEM = {
    "parent": "당신은 학원 국어 교사입니다. 학부모에게 자녀의 월말 학력평가 결과를 설명합니다. 정중한 '-습니다'체, "
              "300자 안팎. 점수 변화, 잘한 점 1가지, 반복 약점과 다음 달 지도 계획을 주어진 분석에만 근거해 씁니다. 글만 출력합니다.",
    "student": "당신은 학원 국어 선생님입니다. 중학생에게 학력평가 결과 피드백을 씁니다. 친근한 말투, 200자 안팎. "
               "칭찬 1가지, 반복해서 틀리는 유형 1~2가지와 구체적인 공부 방법을 주어진 분석에만 근거해 씁니다. 글만 출력합니다.",
}


def write_student_feedback(state: AcademyState, student_id: str, audience: str, reason: str = "") -> dict:
    s = student(student_id)
    d = state.last_student.get(student_id, {})
    if not {"history", "profile", "wrong_groups"} <= d.keys():
        raise ToolError("먼저 student_history, standard_profile, group_wrong_answers 로 분석해야 합니다.")
    if audience not in FEEDBACK_SYSTEM:
        raise ToolError("audience 는 'parent' 또는 'student' 여야 합니다.")
    h, prof, groups = d["history"], d["profile"], d["wrong_groups"]
    last, prev = h[-1], (h[-2] if len(h) > 1 else None)
    strong = prof[-1]
    rep = [g for g in groups if g["pattern"] == "반복 약점"][:2] or groups[:1]
    if llm.online():
        facts = {"이름": s["name"], "성적": h, "강한 성취기준": strong, "반복 약점": rep}
        text = llm.complete_text(FEEDBACK_SYSTEM[audience], json.dumps(facts, ensure_ascii=False))
    else:
        change = (f"지난달보다 {abs(last['score'] - prev['score'])}점 {'올랐' if last['score'] >= prev['score'] else '내려갔'}"
                  if prev else "첫 시험이었")
        weak_txt = ", ".join(f"'{g['desc']}'" for g in rep) if rep else "특별한 약점 없이 고르게"
        if audience == "parent":
            text = (f"안녕하십니까. {s['name']} 학생의 {last['month']} 국어 학력평가 결과를 알려 드립니다.\n"
                    f"이번 점수는 {last['score']}점(반 평균 {last['class_avg']}점)으로 {change}습니다. "
                    f"'{strong['desc']}' 영역은 반 평균보다 잘하고 있습니다.\n"
                    f"다만 {weak_txt} 문제를 여러 달 반복해서 어려워하고 있어, 다음 달에는 이 유형의 유사 문제를 "
                    f"묶어 집중 지도하겠습니다. 가정에서도 격려 부탁드립니다. 감사합니다.")
        else:
            text = (f"{s['name']}, {last['month']} 학력평가 수고했어! 이번엔 {last['score']}점으로 {change}어. "
                    f"'{strong['desc']}'는 정말 잘하고 있어 👍\n"
                    f"대신 {weak_txt} 문제를 자꾸 놓치고 있어. 틀린 문제랑 지난달 비슷한 문제를 묶어 줄 테니, "
                    f"왜 틀렸는지 한 줄씩 써 보면서 다시 풀어 보자 💪")
    d.setdefault("feedback", {})[audience] = text
    return {"audience": audience, "feedback": text, "_summary": f"{'학부모' if audience == 'parent' else '학생'}용 피드백 {len(text)}자"}


def present_exam_report(state: AcademyState, exam_id: str, message: str, reason: str = "") -> dict:
    r = state.last_exam.get(exam_id)
    if not r:
        raise ToolError("먼저 analyze_exam 으로 분석해야 합니다.")
    state.outputs.append({"kind": "exam", "message": message, **r})
    return {"shown": True, "_summary": "시험 분석 리포트를 화면에 표시함"}


def present_student_report(state: AcademyState, student_id: str, message: str, reason: str = "") -> dict:
    d = state.last_student.get(student_id)
    if not d or "wrong_groups" not in d:
        raise ToolError("먼저 학생 분석 도구들을 실행해야 합니다.")
    state.outputs.append({"kind": "student", "student_id": student_id, "name": student(student_id)["name"],
                          "message": message, **d})
    return {"shown": True, "_summary": "학생 리포트를 화면에 표시함"}


# ── 도구 설명 ────────────────────────────────────────────────────

_R = {"type": "string", "description": "지금 이 도구를 쓰는 이유. 교사가 읽을 한국어 한 문장."}


def _schema(props: dict, req: list[str]) -> dict:
    return {"type": "object", "properties": {**props, "reason": _R}, "required": [*req, "reason"]}


_AUD = {"type": "string", "enum": ["parent", "student"], "description": "parent=학부모, student=학생"}

TOOL_SCHEMAS = [
    {"name": "get_class_overview", "description": "반 학생 수와 학부모 언어(번역이 필요한 가정)를 확인한다.",
     "input_schema": _schema({"grade": {"type": "integer", "enum": [1, 2, 3]}}, ["grade"])},
    {"name": "draft_notice", "description": "교사가 준 오늘 진도·숙제·앞으로의 진도로 학부모용 또는 학생용 알림장 초안을 쓴다.",
     "input_schema": _schema({"audience": _AUD, "class_name": {"type": "string"}, "today_progress": {"type": "string"},
                              "homework": {"type": "string"}, "next_plan": {"type": "string"}},
                             ["audience", "class_name", "today_progress", "homework", "next_plan"])},
    {"name": "check_notice", "description": "알림장에 세 내용(진도·숙제·앞으로의 진도)이 다 있는지, 학부모용 말투, 길이, 개인정보를 검사한다. "
                                            "통과하지 못하면 draft_notice 로 다시 쓴다.",
     "input_schema": _schema({"audience": _AUD}, ["audience"])},
    {"name": "translate_notice", "description": "학부모용 알림장을 다문화 가정 학부모의 언어로 번역한다.",
     "input_schema": _schema({"audience": _AUD, "language_code": {"type": "string"}, "language_name": {"type": "string"}},
                             ["audience", "language_code", "language_name"])},
    {"name": "present_notice", "description": "완성된 알림장(과 번역)을 화면에 보여준다.",
     "input_schema": _schema({"audience": _AUD, "message": {"type": "string"}}, ["audience"])},
    {"name": "list_exams", "description": "학년의 월말 학력평가 목록을 본다.",
     "input_schema": _schema({"grade": {"type": "integer", "enum": [1, 2, 3]}}, ["grade"])},
    {"name": "analyze_exam", "description": "시험의 문항별 정답률, 정답률 높은/낮은 문항, 매력적 오답, 성취기준별 정답률을 분석한다.",
     "input_schema": _schema({"exam_id": {"type": "string"}}, ["exam_id"])},
    {"name": "student_history", "description": "학생의 지난 학력평가 점수·반 평균·등수 변화를 본다.",
     "input_schema": _schema({"student_id": {"type": "string"}}, ["student_id"])},
    {"name": "standard_profile", "description": "학생의 성취기준별 정답률을 반 평균과 비교해 약한/강한 성취기준을 찾는다.",
     "input_schema": _schema({"student_id": {"type": "string"}}, ["student_id"])},
    {"name": "group_wrong_answers", "description": "이번 시험에서 틀린 문항을 성취기준별로 묶고, 지난 시험의 같은 성취기준 유사 문항과 "
                                                   "그때 맞혔는지를 붙여 '반복 약점'인지 판단한다.",
     "input_schema": _schema({"student_id": {"type": "string"}, "exam_id": {"type": "string"}}, ["student_id", "exam_id"])},
    {"name": "write_student_feedback", "description": "분석 결과에만 근거해 학부모용 또는 학생용 성적 피드백을 쓴다.",
     "input_schema": _schema({"student_id": {"type": "string"}, "audience": _AUD}, ["student_id", "audience"])},
    {"name": "present_exam_report", "description": "시험 분석 리포트를 그래프와 함께 화면에 보여준다.",
     "input_schema": _schema({"exam_id": {"type": "string"}, "message": {"type": "string"}}, ["exam_id", "message"])},
    {"name": "present_student_report", "description": "학생 리포트(성적 추이 그래프, 성취기준 비교, 오답 묶음, 피드백)를 화면에 보여준다.",
     "input_schema": _schema({"student_id": {"type": "string"}, "message": {"type": "string"}}, ["student_id", "message"])},
]

TOOL_FUNCS = {t["name"]: globals()[t["name"]] for t in TOOL_SCHEMAS}

TOOL_LABELS = {
    "get_class_overview": "👥 반 정보 확인", "draft_notice": "✏️ 알림장 쓰기", "check_notice": "🔍 알림장 검사",
    "translate_notice": "🌐 학부모 언어로 번역", "present_notice": "📒 알림장 보여주기",
    "list_exams": "🗂️ 시험 목록", "analyze_exam": "📊 문항·성취기준 분석", "student_history": "📈 성적 추이",
    "standard_profile": "🎯 성취기준별 강약점", "group_wrong_answers": "🧩 오답 묶기·유사 문항",
    "write_student_feedback": "💬 피드백 쓰기", "present_exam_report": "📄 시험 리포트 보여주기",
    "present_student_report": "📄 학생 리포트 보여주기",
}


def execute(state: AcademyState, name: str, args: dict) -> dict:
    f = TOOL_FUNCS.get(name)
    if not f:
        raise ToolError(f"없는 도구입니다: {name}")
    return f(state, **args)
