"""시연용 화면 (Streamlit). 실행: streamlit run app.py"""

import html
import json
import time

import streamlit as st

from agent import data, llm, service
from agent.config import (CHECK_DOWN_THRESHOLD, CHECK_UP_THRESHOLD, DIAGNOSIS_RULE_TEXT, LANGUAGE_NAMES,
                          SCAFFOLD_LEVELS)
from agent.tools import TOOL_LABELS, AgentState

st.set_page_config(page_title="다문화 학습 지원 에이전트", page_icon="🌏", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.6rem; max-width: 1400px;}
.notice {background:#fff7e6; border:1px solid #ffd591; border-radius:8px; padding:8px 14px; font-size:0.92rem;}
.mode {display:inline-block; padding:3px 10px; border-radius:999px; font-size:0.85rem; font-weight:600;}
.mode.on {background:#e6f4ff; color:#0958d9;}
.mode.off {background:#f6ffed; color:#389e0d;}
.step {border:1px solid #e5e7eb; border-left:4px solid #6366f1; border-radius:8px; padding:8px 12px; margin:6px 0; background:#fafafa;}
.step.err {border-left-color:#ef4444;}
.step .t {font-weight:700;} .step .r {color:#4b5563; font-size:0.9rem; margin-top:2px;}
.step .o {font-size:0.9rem; margin-top:4px; color:#111827;}
.say {color:#374151; font-size:0.92rem; padding:4px 2px 4px 10px; border-left:3px dotted #c7d2fe; margin:4px 0;}
.goal {background:#eef2ff; border-radius:8px; padding:8px 12px; font-size:0.9rem; white-space:pre-wrap;}
.final {background:#ecfdf5; border:1px solid #a7f3d0; border-radius:8px; padding:10px 14px;}
.card {border:1px solid #e5e7eb; border-radius:12px; padding:10px; text-align:center; background:white; height:100%;}
.card .i {font-size:2.2rem;} .card .w {font-size:1.15rem; font-weight:700;}
.card .e {font-size:0.85rem; color:#4b5563;} .card .n {font-size:0.95rem; color:#1d4ed8; margin-top:4px;}
.card .s {font-size:0.7rem; color:#9ca3af;}
.pair td {vertical-align:top; padding:6px 10px; border-bottom:1px solid #f0f0f0; font-size:1.02rem;}
.pair th {text-align:left; padding:6px 10px; background:#f8fafc;}
.lv {display:inline-block; background:#4f46e5; color:white; border-radius:6px; padding:2px 10px; font-weight:700;}
</style>
""", unsafe_allow_html=True)

# ── 세션 상태 ────────────────────────────────────────────────────
if "agent_state" not in st.session_state:
    st.session_state.agent_state = AgentState()
if "runs" not in st.session_state:
    st.session_state.runs = {}
state: AgentState = st.session_state.agent_state
ONLINE = llm.online()
students = data.students()
P = data.passage("P01")
demo = data.offline_demo()

# ── 머리말 ───────────────────────────────────────────────────────
st.title("🌏 다문화 학습 지원 에이전트")
st.caption("이주배경 학생을 위한 쉬운 한국어 · 이중언어 지원 · 맞춤형 비계 조정 에이전트  |  2026 Ax-Edu 해커톤 ③ 포용·다문화")
mode_html = (f'<span class="mode on">🟢 실시간 AI 모드 (Claude)</span>' if ONLINE
             else f'<span class="mode off">🎬 오프라인 시연 모드 (미리 준비된 시나리오 · 도구는 실제 실행)</span>')
st.markdown(mode_html, unsafe_allow_html=True)
st.markdown('<div class="notice">⚠️ <b>교사 확인용 보조 자료</b>입니다. 번역과 쉬운 한국어 변환은 완벽하지 않을 수 있으니 '
            '수업에 쓰기 전에 교사가 확인해 주세요. 화면의 학생은 모두 <b>가상 인물</b>입니다.</div>',
            unsafe_allow_html=True)
st.write("")

# ── 사이드바 ─────────────────────────────────────────────────────
with st.sidebar:
    st.header("👥 학생 선택")
    labels = {s["id"]: f"{s['display_name']} · {s['home_language_name']}" for s in students}
    sid = st.radio("지원할 학생", list(labels), format_func=labels.get, label_visibility="collapsed")
    stu = data.student(sid)
    st.caption(f"{stu['grade']} · 한국 생활 {stu['months_in_korea']}개월\n\n📝 {stu['teacher_memo']}")

    st.divider()
    st.subheader("🪜 학생별 지원 단계")
    for s in students:
        lv = state.levels.get(s["id"])
        st.markdown(f"- **{s['display_name'].split(' ')[0]}** : " + (f"{lv}단계" if lv else "진단 전"))
    with st.expander("단계 기준 보기"):
        for n, lv in SCAFFOLD_LEVELS.items():
            st.markdown(f"**{lv['name']}**  \n{lv['policy']}")
        st.caption(f"진단: {DIAGNOSIS_RULE_TEXT}\n\n"
                   f"확인 문제: {CHECK_UP_THRESHOLD}% 이상 → 지원 줄이기, {CHECK_DOWN_THRESHOLD}% 미만 → 지원 늘리기")
    if st.button("🔄 처음부터 다시 (단계 초기화)", use_container_width=True):
        st.session_state.agent_state = AgentState()
        st.session_state.runs = {}
        st.rerun()

    st.divider()
    if ONLINE:
        st.success("Claude API 키가 연결되어 있어 실제 AI가 도구를 고릅니다.")
    else:
        st.info("API 키 없이 실행 중입니다. 예시 지문·예시 질문으로 전체 과정을 시연할 수 있어요. "
                "새 지문/질문을 쓰려면 README의 'API 키 넣기'를 따라 해 주세요.")


# ── 화면 그리기 도우미 ────────────────────────────────────────────

def esc(t: str) -> str:
    return html.escape(t or "").replace("\n", "<br>")


def render_event(ev: dict, box, counter: list):
    t = ev["type"]
    if t == "goal":
        first, _, rest = ev["text"].partition("\n")
        box.markdown(f"**🎯 에이전트에게 준 목표** · <small>{esc(ev['mode'])}</small>"
                     f"<div class='goal'>{esc(first)}</div>", unsafe_allow_html=True)
        if rest.strip():
            with box.expander("목표 전체 보기"):
                st.text(ev["text"])
    elif t == "thinking":
        with box.expander("🧠 생각 요약"):
            st.write(ev["text"])
    elif t == "say":
        box.markdown(f"<div class='say'>💬 {esc(ev['text'])}</div>", unsafe_allow_html=True)
    elif t == "tool_call":
        counter[0] += 1
        ev["_n"] = counter[0]
    elif t == "tool_result":
        call = ev["_call"]
        cls = "step" if ev["ok"] else "step err"
        box.markdown(
            f"<div class='{cls}'><div class='t'>#{call['_n']} · {TOOL_LABELS.get(call['name'], call['name'])} "
            f"<code style='font-size:0.75rem'>{call['name']}</code></div>"
            f"<div class='r'>왜? {esc(call['reason'])}</div>"
            f"<div class='o'>→ {esc(ev['summary'])}</div></div>", unsafe_allow_html=True)
        with box.expander(f"#{call['_n']} 자세히 (입력/출력)"):
            st.caption("입력")
            st.json(call["input"], expanded=False)
            st.caption("출력")
            st.json(ev["output"], expanded=False)
    elif t == "final":
        if ev["text"]:
            box.markdown(f"<div class='final'>✅ <b>에이전트 보고</b><br>{esc(ev['text'])}</div>",
                         unsafe_allow_html=True)
    elif t == "error":
        box.error(ev["text"])


def render_cards(cards: list[dict]):
    if not cards:
        return
    st.markdown("**🃏 어휘 카드**")
    per_row = 4
    for i in range(0, len(cards), per_row):
        cols = st.columns(per_row)
        for col, c in zip(cols, cards[i:i + per_row]):
            col.markdown(
                f"<div class='card'><div class='i'>{esc(c.get('icon', ''))}</div><div class='w'>{esc(c['word'])}</div>"
                f"<div class='e'>{esc(c['easy'])}</div><div class='n'>{esc(c['native'])}</div>"
                f"<div class='s'>{esc(c.get('source', ''))}</div></div>", unsafe_allow_html=True)
        st.write("")


def render_pair(korean: str, native: str, lang: str):
    k, n = korean.strip().split("\n"), native.strip().split("\n")
    head = f"<tr><th>🇰🇷 쉬운 한국어</th><th>🌐 {LANGUAGE_NAMES[lang]}</th></tr>"
    if len(k) == len(n):
        rows = "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td></tr>" for a, b in zip(k, n))
    else:
        rows = f"<tr><td>{esc(korean)}</td><td>{esc(native)}</td></tr>"
    st.markdown(f"<table class='pair' style='width:100%'>{head}{rows}</table>", unsafe_allow_html=True)


def render_output(out: dict):
    s = data.student(out["student_id"])
    lang = s["home_language"]
    if out["kind"] == "lesson":
        lv = out["level"]
        st.markdown(f"<span class='lv'>{lv}단계</span> **{SCAFFOLD_LEVELS[lv]['name']}** · {s['display_name']}",
                    unsafe_allow_html=True)
        st.caption(SCAFFOLD_LEVELS[lv]["policy"])
        if out["native_text"]:
            render_pair(out["korean_text"], out["native_text"], lang)
        else:
            st.markdown("**📖 학생용 지문**")
            st.info(out["korean_text"])
        render_cards(out["vocab_cards"])
        if out["teacher_note"]:
            st.markdown(f"**👩‍🏫 교사용 수업 팁**  \n{out['teacher_note']}")
    elif out["kind"] == "bilingual":
        title = "🙋 학생 질문에 대한 답" if out["mode"] == "answer" else "👩‍🏫 교사 설명 나란히 보기"
        st.markdown(f"**{title}** · {s['display_name']}")
        if out["original_text"] and out["mode"] == "answer":
            st.markdown(f"> 학생 질문: {out['original_text']}")
        render_pair(out["korean_text"], out["native_text"], lang)
        render_cards(out["vocab_cards"])
    elif out["kind"] == "plan":
        hist = out["history"]
        before = hist[-2][0] if len(hist) >= 2 else None
        c1, c2 = st.columns(2)
        c1.metric("이전 단계", f"{before}단계" if before else "-")
        c2.metric("새 단계", f"{out['new_level']}단계",
                  delta=None if before is None or before == out["new_level"] else
                  ("지원 줄이기" if out["new_level"] > before else "지원 늘리기"))
        st.success(out["message"])
        st.markdown("**다음 수업 계획**")
        for x in out["next_steps"]:
            st.markdown(f"- {x}")
        with st.expander("단계 변경 기록 (판단 근거)"):
            for lv, why in hist:
                st.markdown(f"- **{lv}단계** ← {why}")


def run_and_show(key: str, scenario: str, **kwargs):
    """에이전트를 실행하며 트레이스를 실시간으로 그리고, 결과를 저장한다."""
    left, right = st.columns([5, 6], gap="large")
    left.subheader("🧠 에이전트 실행 과정")
    right.subheader("📄 결과")
    trace_box = left.container()
    result_box = right.container()

    run = st.session_state.runs.get(key)
    if run is None and not kwargs.get("_go"):
        trace_box.caption("▶ 버튼을 누르면 에이전트가 스스로 도구를 골라 단계별로 일하는 과정이 여기에 나타납니다.")
        return
    kwargs.pop("_go", None)

    counter = [0]
    if run is None:
        events, before = [], len(state.outputs)
        last_call = None
        with st.spinner("에이전트가 일하는 중..."):
            for ev in service.run(scenario, state, **kwargs):
                if ev["type"] == "tool_call":
                    last_call = ev
                if ev["type"] == "tool_result":
                    ev["_call"] = last_call
                render_event(ev, trace_box, counter)
                events.append(ev)
                if not ONLINE:
                    time.sleep(0.35)
        run = {"events": events, "outputs": state.outputs[before:]}
        st.session_state.runs[key] = run
        st.rerun()  # 사이드바의 단계 현황을 새로 그리기 위해
    else:
        for ev in run["events"]:
            render_event(ev, trace_box, counter)
    with result_box:
        if not run["outputs"]:
            st.caption("아직 표시할 결과가 없습니다.")
        for out in run["outputs"]:
            render_output(out)


# ── 탭 ───────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["① 수업 자료 만들기 (쉬운 한국어 + 어휘 카드)",
                            "② 실시간 이중언어 도우미",
                            "③ 확인 문제 → 지원 단계 조정"])

with tab1:
    st.markdown("교과 지문을 학생 수준에 맞춰 **쉬운 한국어 + 모국어 + 그림 어휘 카드**로 바꿉니다. "
                "지원 단계가 없으면 에이전트가 먼저 **진단**부터 합니다.")
    use_custom = st.toggle("지문 직접 입력하기", value=False, disabled=not ONLINE,
                           help="새 지문은 실시간 AI 모드(API 키)에서 쓸 수 있어요.")
    if use_custom:
        text = st.text_area("지문", height=150, placeholder="교과서 수준의 지문을 붙여 넣으세요 (교과서를 그대로 베끼지 마세요).")
        pid = None
    else:
        st.markdown(f"**예시 지문 · {P['subject']} {P['grade']} 「{P['title']}」**")
        st.markdown(f"<div class='goal'>{esc(P['text'])}</div>", unsafe_allow_html=True)
        text, pid = P["text"], P["id"]
    go = st.button(f"▶ {data.student(sid)['display_name']} 학생용 자료 만들기", type="primary", key="go1")
    key = f"lesson:{sid}:{pid or hash(text)}"
    if go:
        st.session_state.runs.pop(key, None)
    run_and_show(key, "lesson", student_id=sid, passage_text=text, passage_id=pid, _go=go)

with tab2:
    st.markdown("수업 중 학생이 **모국어로 질문**하면 쉬운 한국어 + 모국어로 함께 답하고, "
                "교사의 설명 문장은 **한국어/모국어 나란히** 보여줍니다.")
    lang = data.student(sid)["home_language"]
    sub = st.radio("무엇을 할까요?", ["🙋 학생 질문에 답하기", "👩‍🏫 교사 설명 나란히 보기"], horizontal=True)
    if sub.startswith("🙋"):
        preset = demo["student_questions"][lang]
        q = st.text_input(f"학생 질문 ({LANGUAGE_NAMES[lang]})", value=preset["question"], disabled=not ONLINE)
        st.caption(f"예시 질문 뜻: “{preset['question_ko']}”")
        scenario, txt = "question", q
    else:
        s_txt = st.text_input("교사 설명 문장", value=demo["teacher_sentence"], disabled=not ONLINE)
        scenario, txt = "teacher", s_txt
    go = st.button("▶ 에이전트 실행", type="primary", key="go2")
    key = f"{scenario}:{sid}:{txt}"
    if go:
        st.session_state.runs.pop(key, None)
    run_and_show(key, scenario, student_id=sid, text=txt, _go=go)

with tab3:
    st.markdown("수업 후 **확인 문제** 결과를 넣으면, 에이전트가 채점하고 기준표에 따라 "
                "**맞히면 지원을 줄이고(fading), 틀리면 지원을 늘립니다.** 판단 근거도 함께 보여줍니다.")
    cur = state.levels.get(sid)
    st.markdown(f"현재 **{data.student(sid)['display_name']}** 학생 지원 단계: "
                + (f"<span class='lv'>{cur}단계</span>" if cur else "진단 전 (에이전트가 먼저 진단합니다)"),
                unsafe_allow_html=True)
    results = []
    for q in P["check_questions"]:
        c1, c2 = st.columns([5, 2])
        c1.markdown(f"{q['id']}. {q['question']}  <small style='color:#9ca3af'>(정답: {q['answer']})</small>",
                    unsafe_allow_html=True)
        results.append(c2.toggle("맞음", value=q["id"] != 4, key=f"chk{q['id']}"))
    go = st.button("▶ 결과 반영하기", type="primary", key="go3")
    key = f"fading:{sid}:{json.dumps(results)}:{len(state.level_history.get(sid, []))}"
    if go:
        st.session_state.runs.pop(key, None)
        st.session_state["last_fading"] = key
    key = st.session_state.get("last_fading", key) if not go else key
    if not key.startswith(f"fading:{sid}:"):
        key = "fading:none"
    run_and_show(key, "fading", student_id=sid, passage_id=P["id"], results=results, _go=go)
