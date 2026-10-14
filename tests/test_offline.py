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


def test_same_text_different_students():
    """같은 글이라도 학생마다 아는 낱말이 달라 결과가 달라야 한다 (번역기와 다른 점)."""
    st = AgentState()
    texts = {}
    for s in data.students():
        _run(st, "personal", student_id=s["id"], text=P["text"], ease_step=0)
        texts[s["id"]] = st.last_personal[s["id"]]["text"]
    assert len(set(texts.values())) == 4
    assert texts["S03"] == P["text"]                 # 3단계 낱말 수준 학생은 그대로
    assert "태양열" in texts["S02"]                    # 웨이는 '태양열'을 안다고 관찰됨
    assert "끊임없이" in texts["S04"]                  # 바트는 '끊임없이'를 안다고 관찰됨
    assert "증발" in texts["S01"] and "강수" in texts["S01"]  # 핵심 용어는 바꾸지 않는다


def test_easier_steps_get_simpler():
    st = AgentState()
    changes = []
    for step in range(3):  # 사샤(낱말 수준 3): 요청할수록 더 많이 바뀐다
        _run(st, "personal", student_id="S03", text=P["text"], ease_step=step)
        changes.append(len(st.last_personal["S03"]["changes"]))
    assert changes[0] < changes[1] < changes[2]
    _run(st, "personal", student_id="S01", text=P["text"], ease_step=2)  # 린: 낱말만으로 부족 → 문장 다시 쓰기
    assert "\n" in st.last_personal["S01"]["text"]


def test_peer_group_crosses_regions():
    st = AgentState()
    for mode in ("same_language", "mixed_language"):
        _run(st, "peer", student_id="S01", mode=mode)
        g = st.last_peer["S01"]
        assert len(g["members"]) == 3
        assert g["nationwide_candidates"] > g["local_candidates"]
        langs = [m["language"] for m in g["members"]]
        if mode == "same_language":
            assert set(langs) == {"베트남어"}
        else:
            assert "베트남어" not in langs and len(set(langs)) == 3


def test_lesson_fits_word_pocket():
    """수업 자료는 학생 낱말 주머니 기준(아는 낱말 80% 이상, 새 낱말 3개까지)을 통과해야 한다."""
    from agent.config import COVERAGE_MIN, MAX_NEW_WORDS
    st = AgentState()
    for s in data.students():
        _run(st, "lesson", student_id=s["id"], passage_text=P["text"], passage_id="P01")
        cov = st.outputs[-1]["coverage"]
        assert cov["coverage"] >= COVERAGE_MIN and len(cov["new_words"]) <= MAX_NEW_WORDS, (s["id"], cov)


def test_reactions_change_next_text():
    """학생 반응(3번 맞힘 / 몰라요)이 다음 글을 바꾼다: 1대1 번역이 아닌 '자라는' 맞춤."""
    from agent.tools import record_word_feedback
    st = AgentState()
    _run(st, "lesson", student_id="S02", passage_text=P["text"], passage_id="P01")
    first = st.outputs[-1]
    assert "강수" not in first["coverage"]["new_words"]          # 새 낱말 3개 기준으로 '강수'는 미룸
    for _ in range(3):
        record_word_feedback(st, "S02", "증발", "correct")
    record_word_feedback(st, "S02", "지구", "dont_know")
    _run(st, "lesson", student_id="S02", passage_text=P["text"], passage_id="P01")
    second = st.outputs[-1]
    assert "증발" not in second["coverage"]["new_words"]         # 이제 아는 낱말
    assert "강수" in second["coverage"]["new_words"]             # 빈자리에 다음 핵심 용어
    assert "지구" in first["korean_text"] and "지구" not in second["korean_text"]  # '몰라요' 낱말은 바뀜
