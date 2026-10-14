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

from . import ctt

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


# 진도에 자주 쓰는 말 → 2022 개정 국어과 교육과정 중학교 성취기준
STANDARD_KEYWORDS = [
    (r"갈등", "9국05-02"), (r"시점|서술자|보는 이|말하는 이|화자", "9국05-04"), (r"비유|상징|운율", "9국05-01"),
    (r"성장", "9국05-03"), (r"사회[·⋅ ]?문화적|시대 ?배경", "9국05-05"), (r"품사", "9국04-03"),
    (r"문장 ?성분|문장의 짜임|홑문장|겹문장", "9국04-04"), (r"음운", "9국04-01"), (r"단어의 짜임|새말|합성어|파생어", "9국04-02"),
    (r"피동|인용 표현", "9국04-05"), (r"맞춤법", "9국04-06"), (r"요약", "9국02-02"), (r"설명 방법|논증", "9국02-05"),
    (r"추론", "9국02-03"), (r"토론", "9국01-08"), (r"토의", "9국01-07"), (r"발표", "9국01-06"), (r"면담", "9국01-05"),
    (r"주장하는 글", "9국03-03"), (r"고쳐 ?쓰", "9국03-08"), (r"광고|홍보", "9국06-05"), (r"매체", "9국06-02"),
]


@lru_cache(maxsize=1)
def curriculum() -> dict:
    cur = json.loads((DATA_DIR / "curriculum_standards.json").read_text(encoding="utf-8"))
    return {x["code"].strip("[]"): x for x in cur["standards"]}


def match_standards(state: AcademyState, text: str, reason: str = "") -> dict:
    found = []
    for pat, code in STANDARD_KEYWORDS:
        if re.search(pat, text or "") and code not in found:
            found.append(code)
    if not found and llm.online():
        menu = "\n".join(f"{k} {v['text']}" for k, v in curriculum().items() if k.startswith("9국"))
        out = llm.complete_text("수업 진도에 해당하는 중학교 국어 성취기준 코드만 쉼표로 답합니다(최대 3개, 없으면 '없음').",
                                f"[진도]\n{text}\n\n[성취기준 목록]\n{menu}")
        found = [c for c in re.findall(r"9국0\d-\d\d", out) if c in curriculum()][:3]
    items = [{"code": f"[{c}]", "area": curriculum()[c]["area"], "text": curriculum()[c]["text"]} for c in found]
    state.notices["_standards"] = items
    return {"standards": items,
            "_summary": ("연결된 성취기준: " + ", ".join(x["code"] for x in items)) if items else "연결할 성취기준을 찾지 못함"}


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
        stds = state.notices.get("_standards", [])
        prompt = (f"반: {class_name}\n[오늘 수업 진도]\n{today_progress}\n[숙제]\n{homework}\n"
                  f"[앞으로의 진도 계획]\n{next_plan}"
                  + (("\n[연결된 성취기준 — 학부모용이면 '■ 이번 수업과 연결된 성취기준' 칸에 그대로 적기]\n"
                      + "\n".join(f"{x['code']} {x['text']}" for x in stds)) if stds and audience == "parent" else ""))
        text = llm.complete_text(NOTICE_SYSTEM[audience], prompt)
    else:
        t, h, n = _bullets(today_progress), _bullets(homework), _bullets(next_plan)
        stds = state.notices.get("_standards", [])
        if audience == "parent":
            text = (f"안녕하십니까, {class_name} 국어 담당 교사입니다. 오늘 수업 내용을 알려 드립니다.\n\n"
                    "■ 오늘 수업 진도\n" + "\n".join(f"- {x}" for x in t) + "\n\n"
                    + (("■ 이번 수업과 연결된 성취기준 (2022 개정 국어과 교육과정)\n"
                        + "\n".join(f"- {x['code']} {x['text']}" for x in stds) + "\n\n") if stds else "") +
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
    limit = 900 if audience == "parent" else 450
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


@lru_cache(maxsize=None)
def _ctt(exam_id: str) -> dict:
    e = exam(exam_id)
    return ctt.analyze(e["items"], answers(exam_id))


def std_short(k: str) -> str:
    """성취기준의 쉬운 이름 (문항 제목에서): 학부모·학생용 글에 쓴다."""
    for e in exams():
        for it in e["items"]:
            if it["standard"] == k:
                return it["title"]
    return standards()[k]["desc"]


def _std_label(k: str, n: int = 26) -> str:
    d = standards()[k]["desc"]
    return f"[{k}] " + (d if len(d) <= n else d[:n] + "…")


def analyze_exam(state: AcademyState, exam_id: str, reason: str = "") -> dict:
    e = exam(exam_id)
    c = _ctt(exam_id)
    items = [{**it, "rate": round(it["difficulty"] * 100)} for it in c["items"]]
    by_std = defaultdict(list)
    for it in items:
        by_std[it["standard"]].append(it["difficulty"])
    std_rates = sorted(({"standard": k, "code": f"[{k}]", "area": standards()[k]["area"], "desc": standards()[k]["desc"],
                         "rate": round(mean(v) * 100)} for k, v in by_std.items()), key=lambda x: x["rate"])
    ranked = sorted(items, key=lambda x: x["difficulty"])
    scores = list(c["totals"].values())
    labels = Counter(it["difficulty_label"] for it in items)
    res = {
        "exam_id": exam_id, "title": e["title"], "students": c["n"], "average": c["mean"], "sd": c["sd"],
        "max": max(scores), "min": min(scores), "scale": c["scale"], "difficulty_mix": dict(labels),
        "items": items, "low_items": ranked[:3], "high_items": ranked[::-1][:3], "standards": std_rates,
    }
    state.last_exam[exam_id] = res
    low = ", ".join(f"{x['no']}번(P={x['difficulty']})" for x in res["low_items"])
    high = ", ".join(f"{x['no']}번(P={x['difficulty']})" for x in res["high_items"])
    mix = " · ".join(f"{k} {v}" for k, v in labels.items())
    return {**{k: v for k, v in res.items() if k != "items"},
            "_summary": f"평균 {res['average']}점 · 난이도 분포({c['scale']} 기준): {mix} · 어려운 문항 {low} · 쉬운 문항 {high} · "
                        f"가장 약한 성취기준 {_std_label(std_rates[0]['standard'])}({std_rates[0]['rate']}%)"}


def check_item_quality(state: AcademyState, exam_id: str, reason: str = "") -> dict:
    r = state.last_exam.get(exam_id)
    if not r:
        raise ToolError("먼저 analyze_exam 으로 분석해야 합니다.")
    flagged = [it for it in r["items"] if it["flags"]]
    low_disc = [it["no"] for it in r["items"] if it["discrimination"] < 0.2]
    dead = [it["no"] for it in r["items"] if it["dead_options"]]
    misc = [it["no"] for it in r["items"] if any("오개념" in f for f in it["flags"])]
    r["quality"] = {"flagged": [{"no": it["no"], "flags": it["flags"]} for it in flagged],
                    "low_discrimination": low_disc, "dead_options": dead, "misconception": misc}
    neg = [it["no"] for it in r["items"] if it["discrimination"] < 0]
    return {**r["quality"], "negative_discrimination": neg,
            "_summary": f"꼭 검토할 문항(변별도 0.2 미만): {low_disc or '없음'}"
                        + (f" — 그중 {neg}번은 변별도 음수라 정답·문항 오류 확인 필요" if neg else "")
                        + f" · 오개념 재지도 문항(어렵고 매력적 오답 있음): {misc or '없음'}"
                        + f" · 답지를 손볼 문항(기능 상실 답지) {len(dead)}개"}


def test_reliability(state: AcademyState, exam_id: str, reason: str = "") -> dict:
    r = state.last_exam.get(exam_id)
    if not r:
        raise ToolError("먼저 analyze_exam 으로 분석해야 합니다.")
    c = _ctt(exam_id)
    r["reliability"] = {"kr20": c["reliability"], "label": c["reliability_label"], "sem": c["sem"], "sd": c["sd"]}
    return {**r["reliability"],
            "_summary": f"신뢰도(KR-20) {c['reliability']} ({c['reliability_label']}) · 측정의 표준오차 ±{c['sem']}점 → "
                        f"학생 점수를 볼 때 ±{c['sem']}점 안의 차이는 우연일 수 있음"}


def student_history(state: AcademyState, student_id: str, reason: str = "") -> dict:
    s = student(student_id)
    rows = []
    for e in exams(s["grade"]):
        ans = answers(e["id"])
        if student_id not in ans:
            continue
        c = _ctt(e["id"])
        all_scores = sorted(c["totals"].values(), reverse=True)
        mine = c["totals"][student_id]
        pos = ctt.standing(mine, all_scores)
        rows.append({"exam_id": e["id"], "month": _month(e), "score": mine, "class_avg": c["mean"],
                     "rank": all_scores.index(mine) + 1, "of": len(all_scores), "t": pos["t"],
                     "percentile": pos["percentile"], "sem": c["sem"]})
    if not rows:
        raise ToolError("이 학생의 시험 기록이 없습니다.")
    delta = rows[-1]["score"] - rows[-2]["score"] if len(rows) > 1 else 0
    t_delta = round(rows[-1]["t"] - rows[-2]["t"], 1) if len(rows) > 1 else 0
    sem = rows[-1]["sem"]
    if len(rows) > 1 and abs(delta) <= sem:
        read = f"원점수 변화({delta:+d}점)가 측정의 표준오차(±{sem}점) 안이라 실력 변화로 보기 어려움"
    elif len(rows) > 1 and (delta < 0) != (t_delta < 0) and abs(t_delta) >= 1:
        read = f"원점수는 {delta:+d}점이지만 반 안 위치(T점수)는 {t_delta:+.1f} → 시험 난이도의 영향이 큼"
    else:
        read = f"원점수 {delta:+d}점, 반 안 위치(T점수) {t_delta:+.1f} → 실제 변화로 볼 만함"
    state.last_student.setdefault(student_id, {})["history"] = rows
    state.last_student[student_id]["history_read"] = read
    return {"student": s["name"], "history": rows, "last_change": delta, "t_change": t_delta, "reading": read,
            "_summary": " → ".join(f"{r['month']} {r['score']}점(T{r['t']:.0f})" for r in rows) + f" · {read}"}


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
        prof.append({"standard": k, "code": f"[{k}]", "area": standards()[k]["area"], "desc": standards()[k]["desc"],
                     "student_rate": round(c / t * 100), "class_rate": round(cc / ct * 100),
                     "gap": round(c / t * 100 - cc / ct * 100), "solved": f"{c}/{t}"})
    prof.sort(key=lambda x: x["gap"])
    state.last_student.setdefault(student_id, {})["profile"] = prof
    weak, strong = prof[:3], prof[::-1][:2]
    return {"profile": prof, "weakest": weak, "strongest": strong,
            "_summary": "약한 성취기준: " + ", ".join(f"{_std_label(w['standard'], 14)}({w['gap']:+d}%p)" for w in weak)
                        + " · 강한 성취기준: " + ", ".join(f"{_std_label(x['standard'], 14)}({x['gap']:+d}%p)" for x in strong)}


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
        groups.append({"standard": std, "code": f"[{std}]", "area": standards()[std]["area"], "desc": standards()[std]["desc"],
                       "wrong_items": its, "similar_items": similar,
                       "past_correct": f"{hit}/{len(similar)}", "pattern": pattern})
    order = {"반복 약점": 0, "처음 나온 유형": 1, "이번에만 틀림": 2}
    groups.sort(key=lambda g: (order[g["pattern"]], -len(g["wrong_items"])))
    state.last_student.setdefault(student_id, {}).update(wrong_groups=groups, exam_id=exam_id)
    n = sum(len(g["wrong_items"]) for g in groups)
    rep = [_std_label(g["standard"], 14) for g in groups if g["pattern"] == "반복 약점"]
    return {"exam_id": exam_id, "wrong_count": n, "groups": groups,
            "_summary": f"틀린 {n}문항을 성취기준 {len(groups)}묶음으로 정리"
                        + (f" · 반복 약점: {', '.join(rep)}" if rep else " · 반복 약점 없음")}


FEEDBACK_SYSTEM = {
    "parent": "당신은 학원 국어 교사입니다. 학부모에게 자녀의 월말 학력평가 결과를 설명합니다. 정중한 '-습니다'체, "
              "350자 안팎. 점수 변화(시험 난이도·측정오차를 고려한 해석 포함), 잘한 점 1가지, 반복 약점과 다음 달 지도 계획을 "
              "주어진 분석에만 근거해 씁니다. 성취기준 코드는 쓰지 말고 쉬운 말로 풀어 씁니다. 글만 출력합니다.",
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
        facts = {"이름": s["name"], "성적(원점수·T점수·백분위·측정오차)": h, "성적 변화 해석": d.get("history_read"),
                 "강한 성취기준": strong, "반복 약점": rep}
        text = llm.complete_text(FEEDBACK_SYSTEM[audience], json.dumps(facts, ensure_ascii=False))
    else:
        change = (f"지난달보다 {abs(last['score'] - prev['score'])}점 {'올랐' if last['score'] >= prev['score'] else '내려갔'}"
                  if prev else "첫 시험이었")
        read = d.get("history_read", "")
        weak_txt = ", ".join(f"'{std_short(g['standard'])}'" for g in rep) if rep else "특별한 약점 없이 고르게"
        strong_txt = std_short(strong["standard"])
        if audience == "parent":
            text = (f"안녕하십니까. {s['name']} 학생의 {last['month']} 국어 학력평가 결과를 알려 드립니다.\n"
                    f"이번 점수는 {last['score']}점(반 평균 {last['class_avg']}점, 반 안 백분위 {last['percentile']})으로 "
                    f"{change}습니다. 매달 시험 난이도가 달라 반 안의 위치로 함께 보면, "
                    + ("이 정도 차이는 시험 오차 범위 안이라 큰 변화는 아닙니다. " if "보기 어려움" in read else
                       "점수 변화는 시험 난이도의 영향이 큽니다. " if "난이도" in read else
                       "실제 실력 변화로 보입니다. ") +
                    f"'{strong_txt}' 문제는 반 평균보다 잘 풀고 있습니다.\n"
                    f"다만 {weak_txt} 문제를 여러 달 반복해서 어려워하고 있어, 다음 달에는 이 유형의 유사 문제를 "
                    f"묶어 집중 지도하겠습니다. 가정에서도 격려 부탁드립니다. 감사합니다.")
        else:
            text = (f"{s['name']}, {last['month']} 학력평가 수고했어! 이번엔 {last['score']}점으로 {change}어. "
                    f"'{strong_txt}' 문제는 정말 잘하고 있어 👍\n"
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
    {"name": "match_standards", "description": "교사가 적은 오늘 진도가 2022 개정 국어과 교육과정의 어느 중학교 성취기준과 연결되는지 찾는다. "
                                               "학부모용 알림장을 쓰기 전에 쓴다.",
     "input_schema": _schema({"text": {"type": "string", "description": "오늘 수업 진도"}}, ["text"])},
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
    {"name": "analyze_exam", "description": "시험의 문항난이도(정답률, 성태제 5단계 해석), 어려운/쉬운 문항, 성취기준별 정답률을 분석한다.",
     "input_schema": _schema({"exam_id": {"type": "string"}}, ["exam_id"])},
    {"name": "check_item_quality", "description": "고전검사이론으로 문항 품질을 점검한다: 변별도(문항-총점 상관, Ebel 기준), 추측도, "
                                                  "교정 난이도, 오답지 매력도(매력적 오답·기능 상실 답지). analyze_exam 다음에 쓴다.",
     "input_schema": _schema({"exam_id": {"type": "string"}}, ["exam_id"])},
    {"name": "test_reliability", "description": "시험의 신뢰도(KR-20)와 측정의 표준오차를 계산한다. 점수 차이를 해석할 때 쓴다.",
     "input_schema": _schema({"exam_id": {"type": "string"}}, ["exam_id"])},
    {"name": "student_history", "description": "학생의 지난 학력평가 원점수, 반 평균, 등수, 반 안 위치(T점수·백분위) 변화를 보고, "
                                               "측정의 표준오차와 시험 난이도 영향을 고려해 변화를 해석한다.",
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
    "get_class_overview": "👥 반 정보 확인", "match_standards": "📚 성취기준 연결", "draft_notice": "✏️ 알림장 쓰기", "check_notice": "🔍 알림장 검사",
    "translate_notice": "🌐 학부모 언어로 번역", "present_notice": "📒 알림장 보여주기",
    "list_exams": "🗂️ 시험 목록", "analyze_exam": "📊 문항난이도·성취기준 분석",
    "check_item_quality": "🔬 문항 품질 점검 (변별도·추측도·답지)", "test_reliability": "📐 신뢰도·측정오차", "student_history": "📈 성적 추이",
    "standard_profile": "🎯 성취기준별 강약점", "group_wrong_answers": "🧩 오답 묶기·유사 문항",
    "write_student_feedback": "💬 피드백 쓰기", "present_exam_report": "📄 시험 리포트 보여주기",
    "present_student_report": "📄 학생 리포트 보여주기",
}


def execute(state: AcademyState, name: str, args: dict) -> dict:
    f = TOOL_FUNCS.get(name)
    if not f:
        raise ToolError(f"없는 도구입니다: {name}")
    return f(state, **args)
