"""학원 수업 도우미 에이전트: 오프라인 시연으로 끝까지 실행되는지 확인한다."""

import os

os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["LOCAL_LLM"] = "off"

from academy import service  # noqa: E402
from academy import tools as T  # noqa: E402


def _run(st, scenario, **kw):
    ev = list(service.run(scenario, st, **kw))
    assert ev[-1]["type"] == "final", ev[-1]
    assert all(e["ok"] for e in ev if e["type"] == "tool_result")
    return ev


def test_notice_parent_and_student():
    st = T.AcademyState()
    _run(st, "notice", grade=2, class_name="중2 A반", today="소설의 갈등 구조\n품사 복습",
         homework="교재 42~45쪽", next_plan="10월 말 학력평가 대비", translate=False)
    parent, student = st.outputs
    assert parent["audience"] == "parent" and "■ 숙제" in parent["text"] and "10월 말" in parent["text"]
    assert student["audience"] == "student" and "교재 42~45쪽" in student["text"]


def test_check_notice_catches_problems():
    st = T.AcademyState()
    st.notices["parent"] = {"text": "숙제 꼭 해! 010-1234-5678", "translations": {},
                            "inputs": {"today": "소설의 갈등 구조", "homework": "교재 42쪽", "next": "시점"}}
    r = T.check_notice(st, "parent")
    assert not r["passed"] and len(r["problems"]) >= 3


def test_exam_and_student_report():
    st = T.AcademyState()
    _run(st, "exam", exam_id="G2-2026-10")
    r = st.outputs[-1]
    assert len(r["items"]) == 20 and r["low_items"][0]["rate"] <= r["high_items"][0]["rate"]
    _run(st, "student", student_id="M203", exam_id="G2-2026-10")
    s = st.outputs[-1]
    assert len(s["history"]) == 4 and {"parent", "student"} <= s["feedback"].keys()
    assert any(g["pattern"] == "반복 약점" for g in s["wrong_groups"])
