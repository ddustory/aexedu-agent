"""학원 수업 도우미 에이전트 실행 입구: 목표 문장, AI 지침, 오프라인 시연 흐름."""

from agent import llm, runner
from agent.offline_scripts import _call, _say
from agent.runner import Step

from . import tools as T

SYSTEM_PROMPT = """당신은 중학교 국어 학원 교사를 돕는 '학원 수업 도우미 에이전트'입니다.
주어진 목표를 이루려고 도구를 스스로 골라 여러 단계로 일합니다.

📒 알림장: get_class_overview 로 반을 확인 → match_standards 로 오늘 진도와 연결된 성취기준을 찾고 →
   학부모용(parent)·학생용(student) 각각 draft_notice → check_notice 로 검사하고
   통과하지 못하면 다시 씁니다(최대 2번) → 학부모 중 번역이 필요한 언어가 있으면 학부모용을 translate_notice →
   present_notice 로 각각 보여줍니다. 교사가 주지 않은 사실은 지어내지 않습니다.
📊 시험 분석(고전검사이론): analyze_exam(난이도) → check_item_quality(변별도·추측도·오답지 매력도) →
   test_reliability(신뢰도·측정의 표준오차) → present_exam_report. 변별도가 낮거나 음수인 문항은 교사에게 검토를 권합니다.
📊 학생 리포트: student_history(원점수·T점수·백분위, 측정오차로 변화 해석) → standard_profile → group_wrong_answers →
   write_student_feedback(parent, student) → present_student_report.
   달마다 시험 난이도가 달라 원점수만으로 성적 변화를 판단하지 않습니다.
모든 도구의 reason 에 '왜 지금 이 도구를 쓰는지'를 한국어 한 문장으로 씁니다. 끝나면 교사에게 2~3문장으로 보고합니다.
모든 학생·시험은 가상 데이터입니다."""


# ── 오프라인 시연 흐름 (도구는 실제로 실행되고, 순서만 정해져 있다) ─────────

def notice_script(grade: int, class_name: str, today: str, homework: str, next_plan: str, translate: bool):
    info = (yield _call("get_class_overview", "알림장을 받을 반과 학부모 언어를 먼저 확인합니다.", grade=grade))[0]
    yield _call("match_standards", "오늘 진도가 교육과정의 어느 성취기준을 배우는 것인지 찾아 학부모께 알려 드립니다.",
                text=today)
    for aud, label in (("parent", "학부모"), ("student", "학생")):
        yield _call("draft_notice", f"{label}에게 맞는 말투로 알림장을 씁니다.", audience=aud, class_name=class_name,
                    today_progress=today, homework=homework, next_plan=next_plan)
        chk = (yield _call("check_notice", f"{label}용 알림장에 진도·숙제·앞으로의 진도가 다 들어갔는지 검사합니다.",
                           audience=aud))[0]
        if not chk["passed"]:
            yield _say("검사에서 고칠 점이 나와 다시 씁니다: " + " / ".join(chk["problems"]),
                       _call("draft_notice", "검사 결과를 반영해 다시 씁니다.", audience=aud, class_name=class_name,
                             today_progress=today, homework=homework, next_plan=next_plan))
        if aud == "parent" and translate and llm.online():
            for lang in info["translation_needed"]:
                yield _call("translate_notice", f"{lang['name']}를 쓰시는 학부모를 위해 번역합니다.",
                            audience="parent", language_code=lang["code"], language_name=lang["name"])
        yield _call("present_notice", f"완성된 {label}용 알림장을 보여줍니다.", audience=aud)
    need = ", ".join(x["name"] for x in info["translation_needed"])
    yield Step(texts=[f"{class_name} 학부모용·학생용 알림장을 썼고, 두 개 모두 필수 항목 검사를 통과했습니다."
                      + (f" 번역이 필요한 학부모 언어: {need}." if need else "")])


def exam_script(exam_id: str):
    r = (yield _call("analyze_exam", "문항난이도(정답률)와 성취기준별 정답률을 계산합니다.", exam_id=exam_id))[0]
    q = (yield _call("check_item_quality", "변별도·추측도·오답지 매력도로 문항이 제 역할을 했는지 점검합니다.",
                     exam_id=exam_id))[0]
    rel = (yield _call("test_reliability", "시험 전체의 신뢰도와 측정의 표준오차를 계산해 점수 해석의 기준을 잡습니다.",
                       exam_id=exam_id))[0]
    low, std = r["low_items"][0], r["standards"][0]
    msg = (f"평균 {r['average']}점, 신뢰도 {rel['kr20']}({rel['label']}), 측정오차 ±{rel['sem']}점. "
           f"가장 어려운 문항은 {low['no']}번(P={low['difficulty']}, {low['title']})이고, 반 전체가 가장 약한 성취기준은 "
           f"{std['code']}({std['rate']}%)입니다."
           + (f" 변별도가 낮은 {', '.join(map(str, q['low_discrimination']))}번 문항은 검토해 주세요." if q["low_discrimination"] else "")
           + (f" {', '.join(map(str, q['misconception']))}번은 매력적 오답이 많아 오개념 재지도를 권합니다." if q["misconception"] else ""))
    yield _call("present_exam_report", "분석 결과를 그래프로 보여줍니다.", exam_id=exam_id, message=msg)
    yield Step(texts=[msg])


def student_script(student_id: str, exam_id: str):
    s = T.student(student_id)
    h = (yield _call("student_history", f"{s['name']} 학생의 지난 학력평가 점수 변화를 먼저 봅니다.",
                     student_id=student_id))[0]
    step = _call("standard_profile", "성취기준별로 반 평균과 비교해 강점과 약점을 찾습니다.", student_id=student_id)
    if "보기 어려움" in h["reading"] or "난이도" in h["reading"]:
        step = _say(f"점수만 보면 {h['last_change']:+d}점이지만, {h['reading']}. 피드백에서 이 점을 반영하겠습니다.", step)
    p = (yield step)[0]
    g = (yield _call("group_wrong_answers", "이번 시험 오답을 성취기준별로 묶고, 지난달 유사 문항과 비교합니다.",
                     student_id=student_id, exam_id=exam_id))[0]
    rep = [x for x in g["groups"] if x["pattern"] == "반복 약점"]
    say = (f"{rep[0]['code']}은 지난 시험에서도 자주 틀린 반복 약점이에요. 피드백에 꼭 넣겠습니다." if rep
           else "반복되는 약점은 없어요. 이번에 틀린 유형 위주로 피드백을 쓰겠습니다.")
    yield _say(say, _call("write_student_feedback", "학부모에게 보낼 성적 피드백을 씁니다.",
                          student_id=student_id, audience="parent"))
    yield _call("write_student_feedback", "학생에게 줄 피드백을 씁니다.", student_id=student_id, audience="student")
    last = h["history"][-1]
    msg = (f"{s['name']}: {last['month']} {last['score']}점(반 평균 {last['class_avg']}점, {last['rank']}등/{last['of']}명), "
           f"T점수 {last['t']}(백분위 {last['percentile']}), 지난달 대비 {h['last_change']:+d}점 — {h['reading']}. "
           f"가장 약한 성취기준: {p['weakest'][0]['code']}.")
    yield _call("present_student_report", "성적 추이 그래프·오답 묶음·피드백을 한 화면에 보여줍니다.",
                student_id=student_id, message=msg)
    yield Step(texts=[msg + f" 틀린 {g['wrong_count']}문항을 {len(g['groups'])}묶음으로 정리했습니다."])


# ── 목표 문장 ────────────────────────────────────────────────────

def goal_notice(grade, class_name, today, homework, next_plan, translate):
    return (f"{class_name}(중{grade}) 오늘 수업 알림장을 학부모용과 학생용으로 써 주세요."
            + (" 번역이 필요한 학부모에게는 번역도 붙여 주세요." if translate else "") +
            f"\n[오늘 수업 진도]\n{today}\n[숙제]\n{homework}\n[앞으로의 진도 계획]\n{next_plan}")


def goal_exam(exam_id):
    return f"{exam_id} 학력평가 결과를 분석해 정답률이 높은/낮은 문항과 약한 성취기준을 알려 주세요."


def goal_student(student_id, exam_id):
    return (f"학생 {student_id} 의 {exam_id} 학력평가 결과를 지난 성적과 연결해 분석하고, 틀린 문제를 유사 문항과 묶어 "
            f"학부모용·학생용 피드백까지 만들어 주세요.")


SCENARIOS = {
    "notice": (lambda k: goal_notice(**k), lambda k: notice_script(**k)),
    "exam": (lambda k: goal_exam(**k), lambda k: exam_script(**k)),
    "student": (lambda k: goal_student(**k), lambda k: student_script(**k)),
}


def run(scenario: str, state: T.AcademyState, **kwargs):
    goal_fn, script_fn = SCENARIOS[scenario]
    goal = goal_fn(kwargs)
    b = llm.backend()
    if b == "claude":
        brain = runner.ClaudeBrain(goal, SYSTEM_PROMPT, T.TOOL_SCHEMAS)
    elif b == "local":
        brain = runner.LocalBrain(goal, SYSTEM_PROMPT, T.TOOL_SCHEMAS)
    else:
        brain = runner.ScriptedBrain(script_fn(kwargs))
    yield {"type": "goal", "text": goal, "mode": brain.label}
    yield from runner.run_agent(brain, state, executor=T.execute, errors=(T.ToolError,))
