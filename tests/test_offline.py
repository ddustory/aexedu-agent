"""오프라인 시연 모드로 네 가지 시나리오가 끝까지 실행되는지 확인한다.  실행: python -m pytest tests"""

import os

os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

from agent import data, service  # noqa: E402
from agent.tools import AgentState  # noqa: E402

P = data.passage("P01")


def _run(state, scenario, **kw):
    events = list(service.run(scenario, state, **kw))
    assert events[-1]["type"] == "final", events[-1]
    assert all(e["ok"] for e in events if e["type"] == "tool_result")
    return events


def test_lesson_levels_follow_diagnosis():
    st = AgentState()
    for sid, level in [("S01", 1), ("S02", 2), ("S03", 3), ("S04", 2)]:
        _run(st, "lesson", student_id=sid, passage_text=P["text"], passage_id="P01")
        assert st.levels[sid] == level
        out = st.outputs[-1]
        assert out["level"] == level
        assert bool(out["native_text"]) == (level == 1)


def test_bilingual_question_and_teacher_sentence():
    st = AgentState()
    demo = data.offline_demo()
    for s in data.students():
        q = demo["student_questions"][s["home_language"]]["question"]
        _run(st, "question", student_id=s["id"], text=q)
        _run(st, "teacher", student_id=s["id"], text=demo["teacher_sentence"])
    assert len(st.outputs) == 8


def test_fading_up_and_down():
    st = AgentState()
    _run(st, "fading", student_id="S01", passage_id="P01", results=[True, True, True, True])
    assert st.levels["S01"] == 2  # 1단계로 시작 → 다 맞혀서 지원 줄이기
    _run(st, "fading", student_id="S01", passage_id="P01", results=[False, False, False, True])
    assert st.levels["S01"] == 1  # 많이 틀려서 지원 늘리기
