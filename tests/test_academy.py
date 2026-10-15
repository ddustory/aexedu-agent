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


def test_ctt_matches_lecture_example():
    """「14장 고전검사이론에 의한 문항분석(3)」의 예: 1·2·3번 문항 난이도 0.6 / 0.6 / 0.4"""
    from academy import ctt
    items = [{"no": i, "answer": 1, "choices": 5, "points": 1} for i in (1, 2, 3)]
    table = {"A": [1, 1, 1], "B": [1, 1, 0], "C": [0, 0, 1], "D": [0, 0, 0], "E": [1, 1, 0]}
    answers = {k: [1 if v else 2 for v in row] for k, row in table.items()}
    r = ctt.analyze(items, answers)
    assert [it["difficulty"] for it in r["items"]] == [0.6, 0.6, 0.4]
    assert ctt.difficulty_label(0.6, "성태제") == "쉬운 문항" and ctt.difficulty_label(0.4, "Cangelosi") == "적절한 문항"
    assert r["items"][0]["discrimination"] > r["items"][2]["discrimination"]   # 1번이 3번보다 잘 가려냄
    assert ctt.discrimination_label(0.45) == "변별력이 높은 문항"


def test_quality_reliability_and_t_scores():
    st = T.AcademyState()
    T.analyze_exam(st, "G2-2026-10")
    q = T.check_item_quality(st, "G2-2026-10")
    rel = T.test_reliability(st, "G2-2026-10")
    assert 0 < rel["kr20"] < 1 and rel["sem"] > 0
    assert isinstance(q["low_discrimination"], list)
    h = T.student_history(st, "M203")
    assert all(20 < r["t"] < 80 for r in h["history"]) and h["reading"]


def test_notice_links_standards():
    st = T.AcademyState()
    r = T.match_standards(st, "소설의 갈등 구조, 품사의 분류")
    assert [x["code"] for x in r["standards"]] == ["[9국05-02]", "[9국04-03]"]


def test_benchmark_module_imports():
    from benchmark import run
    assert run.DEFAULT_MODELS[0] == "qwen3:8b"
