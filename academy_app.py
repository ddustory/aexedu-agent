"""학원 수업 도우미 에이전트 시연 화면. 실행: streamlit run academy_app.py"""

import html
import time

import altair as alt
import pandas as pd
import streamlit as st

from academy import service
from academy import tools as T
from agent import llm

st.set_page_config(page_title="학원 수업 도우미 에이전트", page_icon="📚", layout="wide")
st.markdown("""
<style>
.block-container {padding-top: 1.6rem; max-width: 1400px;}
.mode {display:inline-block; padding:3px 10px; border-radius:999px; font-size:0.85rem; font-weight:600; background:#eef2ff; color:#3730a3;}
.notice {background:#fff7e6; border:1px solid #ffd591; border-radius:8px; padding:8px 14px; font-size:0.92rem;}
.step {border:1px solid #e5e7eb; border-left:4px solid #0d9488; border-radius:8px; padding:8px 12px; margin:6px 0; background:#fafafa;}
.step.err {border-left-color:#ef4444;}
.step .t {font-weight:700;} .step .r {color:#4b5563; font-size:0.9rem; margin-top:2px;} .step .o {font-size:0.9rem; margin-top:4px;}
.say {color:#374151; font-size:0.92rem; padding:4px 2px 4px 10px; border-left:3px dotted #99f6e4; margin:4px 0;}
.goal {background:#f0fdfa; border-radius:8px; padding:8px 12px; font-size:0.9rem; white-space:pre-wrap;}
.final {background:#ecfdf5; border:1px solid #a7f3d0; border-radius:8px; padding:10px 14px;}
.paper {background:white; border:1px solid #e5e7eb; border-radius:10px; padding:14px 16px; white-space:pre-wrap; line-height:1.7;}
.tag {display:inline-block; border-radius:999px; padding:1px 10px; font-size:0.8rem; font-weight:700;}
.tag.rep {background:#fee2e2; color:#b91c1c;} .tag.new {background:#e0e7ff; color:#3730a3;} .tag.once {background:#dcfce7; color:#166534;}
</style>
""", unsafe_allow_html=True)

if "astate" not in st.session_state:
    st.session_state.astate = T.AcademyState()
    st.session_state.aruns = {}
state: T.AcademyState = st.session_state.astate
BACKEND = llm.backend()

st.title("📚 학원 수업 도우미 에이전트")
st.caption("중학교 국어 학원 교사를 위한 알림장 작성 · 월말 학력평가 분석 에이전트  |  학원 강사로 일하며 직접 필요했던 기능")
st.markdown('<span class="mode">' + {
    "claude": "🟢 실시간 AI 모드 (Claude)",
    "local": f"💻 로컬 AI 모드 ({llm.LOCAL_MODEL} · 이 노트북 안에서 실행)",
}.get(BACKEND, "🎬 오프라인 시연 모드 (분석·검사 도구는 실제 실행, 글은 정해진 틀로 작성)") + "</span>", unsafe_allow_html=True)
st.markdown('<div class="notice">⚠️ 화면의 학생·시험·점수는 모두 <b>가상 데이터</b>입니다. 성취기준은 '
            '<b>2022 개정 국어과 교육과정</b>의 실제 성취기준이고, 문항 분석은 <b>고전검사이론</b>을 따릅니다. '
            '보내기 전에 교사가 내용을 확인해 주세요.</div>', unsafe_allow_html=True)
st.write("")


def esc(t) -> str:
    return html.escape(str(t or "")).replace("\n", "<br>")


def render_event(ev, box, counter):
    t = ev["type"]
    if t == "goal":
        first = ev["text"].split("\n")[0]
        box.markdown(f"**🎯 에이전트에게 준 목표** · <small>{esc(ev['mode'])}</small><div class='goal'>{esc(first)}</div>",
                     unsafe_allow_html=True)
    elif t == "say":
        box.markdown(f"<div class='say'>💬 {esc(ev['text'])}</div>", unsafe_allow_html=True)
    elif t == "tool_call":
        counter[0] += 1
        ev["_n"] = counter[0]
    elif t == "tool_result":
        c = ev["_call"]
        box.markdown(f"<div class='step{'' if ev['ok'] else ' err'}'><div class='t'>#{c['_n']} · "
                     f"{T.TOOL_LABELS.get(c['name'], c['name'])} <code style='font-size:0.75rem'>{c['name']}</code></div>"
                     f"<div class='r'>왜? {esc(c['reason'])}</div><div class='o'>→ {esc(ev['summary'])}</div></div>",
                     unsafe_allow_html=True)
    elif t == "final" and ev["text"]:
        box.markdown(f"<div class='final'>✅ <b>에이전트 보고</b><br>{esc(ev['text'])}</div>", unsafe_allow_html=True)
    elif t == "error":
        box.error(ev["text"])


def run_and_show(key, scenario, go, render, **kwargs):
    left, right = st.columns([5, 7], gap="large")
    left.subheader("🧠 에이전트 실행 과정")
    right.subheader("📄 결과")
    run = st.session_state.aruns.get(key)
    if run is None and not go:
        left.caption("▶ 버튼을 누르면 에이전트가 도구를 골라 일하는 과정이 여기에 나타납니다.")
        return
    counter = [0]
    if run is None:
        events, before, last = [], len(state.outputs), None
        with st.spinner("에이전트가 일하는 중..."):
            for ev in service.run(scenario, state, **kwargs):
                if ev["type"] == "tool_call":
                    last = ev
                if ev["type"] == "tool_result":
                    ev["_call"] = last
                render_event(ev, left, counter)
                events.append(ev)
                if not BACKEND:
                    time.sleep(0.25)
        run = {"events": events, "outputs": state.outputs[before:]}
        st.session_state.aruns[key] = run
    else:
        for ev in run["events"]:
            render_event(ev, left, counter)
    with right:
        for out in run["outputs"]:
            render(out)


# ── 결과 화면 ────────────────────────────────────────────────────

def render_notice(out):
    who = "👪 학부모용" if out["audience"] == "parent" else "🧑‍🎓 학생용"
    st.markdown(f"**{who} 알림장**")
    st.markdown(f"<div class='paper'>{esc(out['text'])}</div>", unsafe_allow_html=True)
    with st.expander("복사용 글"):
        st.code(out["text"], language=None)
    for lang, tr in out["translations"].items():
        st.markdown(f"**🌐 {lang} 번역 (다문화 가정 학부모용)**")
        st.markdown(f"<div class='paper'>{esc(tr)}</div>", unsafe_allow_html=True)
    st.write("")


def render_exam(out):
    st.markdown(f"**{out['title']}** · 응시 {out['students']}명")
    rel = out.get("reliability", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("평균", f"{out['average']}점")
    c2.metric("표준편차", f"{out['sd']}점")
    if rel:
        c3.metric("신뢰도 (KR-20)", f"{rel['kr20']}", help="문항 내적 일관성. 0.8 이상 높음, 0.6 이상 보통")
        c4.metric("측정의 표준오차", f"±{rel['sem']}점", help="이 범위 안의 점수 차이는 우연일 수 있어요")
    st.success(out["message"])
    df = pd.DataFrame(out["items"])
    order = ["매우 어려운 문항", "어려운 문항", "중간 난이도 문항", "쉬운 문항", "매우 쉬운 문항",
             "적절한 문항"]
    st.markdown(f"**문항난이도 P (정답률, {out['scale']} 기준 해석)**")
    st.altair_chart(alt.Chart(df).mark_bar().encode(
        x=alt.X("no:O", title="문항"), y=alt.Y("difficulty:Q", title="난이도 P", scale=alt.Scale(domain=[0, 1])),
        color=alt.Color("difficulty_label:N", title="해석", sort=order,
                        scale=alt.Scale(domain=order[:5], range=["#b91c1c", "#f97316", "#94a3b8", "#22c55e", "#15803d"])),
        tooltip=["no", "title", "standard", "difficulty", "difficulty_label"]).properties(height=240),
        use_container_width=True)
    st.markdown("**문항 지도: 난이도 × 변별도** (아래쪽에 있을수록 잘하는 학생과 못하는 학생을 가려내지 못하는 문항)")
    df["점검"] = df["discrimination"].map(lambda d: "꼭 검토 (변별도 0.2 미만)" if d < 0.2 else "양호")
    pts = alt.Chart(df).mark_circle(size=160, opacity=0.9).encode(
        x=alt.X("difficulty:Q", title="난이도 P (오른쪽일수록 쉬움)", scale=alt.Scale(domain=[0, 1])),
        y=alt.Y("discrimination:Q", title="변별도 (문항-총점 상관)", scale=alt.Scale(domain=[-0.3, 0.9])),
        color=alt.Color("점검:N", scale=alt.Scale(domain=["꼭 검토 (변별도 0.2 미만)", "양호"], range=["#ef4444", "#0d9488"])),
        tooltip=["no", "title", "difficulty", "discrimination", "discrimination_label"])
    lbl = alt.Chart(df).mark_text(dy=-12, fontSize=11).encode(x="difficulty:Q", y="discrimination:Q", text="no:N")
    line = alt.Chart(pd.DataFrame({"y": [0.2, 0.4]})).mark_rule(strokeDash=[4, 4], color="#94a3b8").encode(y="y:Q")
    st.altair_chart((line + pts + lbl).properties(height=300), use_container_width=True)
    st.caption("점선: 변별도 0.2(이 아래는 낮음), 0.4(이 위는 높음) — Ebel(1990) 기준")
    st.markdown("**문항 품질 점검표**")
    table = pd.DataFrame([{
        "문항": it["no"], "성취기준": f"[{it['standard']}]", "난이도 P": it["difficulty"], "난이도 해석": it["difficulty_label"],
        "변별도": it["discrimination"], "변별도 해석": it["discrimination_label"], "추측도": it["guessing"],
        "교정 난이도": it["corrected_difficulty"],
        "매력적 오답": ", ".join(map(str, it["attractive_wrong"])) or "-",
        "기능 상실 답지": ", ".join(map(str, it["dead_options"])) or "-",
        "점검 결과": " / ".join(it["flags"]) or "양호"} for it in out["items"]])
    st.dataframe(table, hide_index=True, use_container_width=True)
    c1, c2 = st.columns(2)
    c1.markdown("**🔻 가장 어려운 문항**")
    for x in out["low_items"]:
        c1.markdown(f"- **{x['no']}번** P={x['difficulty']} · {x['title']}  \n  <small>매력적 오답: "
                    f"{', '.join(map(str, x['attractive_wrong'])) or '없음'}번</small>", unsafe_allow_html=True)
    c2.markdown("**🔺 가장 쉬운 문항**")
    for x in out["high_items"]:
        c2.markdown(f"- **{x['no']}번** P={x['difficulty']} · {x['title']}")
    sdf = pd.DataFrame(out["standards"])
    sdf["label"] = sdf["code"] + " " + sdf["area"]
    st.markdown("**성취기준별 정답률** (2022 개정 국어과 교육과정)")
    st.altair_chart(alt.Chart(sdf).mark_bar(color="#0d9488").encode(
        y=alt.Y("label:N", sort="x", title=None), x=alt.X("rate:Q", title="정답률(%)", scale=alt.Scale(domain=[0, 100])),
        tooltip=["code", "desc", "rate"]).properties(height=30 * len(sdf)), use_container_width=True)
    with st.expander("이 분석의 기준 (고전검사이론)"):
        st.markdown(
            "- **문항난이도 P** = 정답자 수 / 전체 학생 수. 성태제(2015): 0.2 미만 매우 어려움 · 0.4 미만 어려움 · 0.6 미만 중간 · "
            "0.8 미만 쉬움 · 그 이상 매우 쉬움\n"
            "- **문항변별도** = 문항 점수와 총점의 상관(점이연 상관). Ebel(1990): 0.1 미만 없음 · 0.2 미만 매우 낮음 · 0.3 미만 낮음 · "
            "0.4 미만 있음 · 0.4 이상 높음. 음수면 잘하는 학생이 더 틀린 문항이라 정답·문항 오류를 확인\n"
            "- **추측도** = 틀린 학생 수 / ((답지 수 − 1) × 전체 학생 수),  **교정 난이도** = 난이도 − 추측도\n"
            "- **오답지 매력도**: 그 오답을 고른 비율이 기대치 (1 − P) / (답지 수 − 1)보다 크면 매력적인 오답, "
            "0명이면 기능 상실 답지 (틀린 학생이 답지 수 × 2명보다 적으면 판단 보류)\n"
            "- **신뢰도** KR-20, **측정의 표준오차** = 표준편차 × √(1 − 신뢰도)")


def render_student(out):
    st.markdown(f"**{out['name']} 학생 리포트**")
    st.info(out["message"])
    h = pd.DataFrame(out["history"])
    last = out["history"][-1]
    c1, c2, c3 = st.columns(3)
    c1.metric(f"{last['month']} 점수", f"{last['score']}점", f"{out['history'][-1]['score'] - out['history'][-2]['score']:+d}점"
              if len(out["history"]) > 1 else None)
    c2.metric("반 안 위치 (T점수)", f"{last['t']}", help="반 평균 50, 표준편차 10으로 바꾼 점수. 시험 난이도가 달라도 비교할 수 있어요")
    c3.metric("백분위", f"{last['percentile']}", help="반에서 이 학생보다 점수가 낮은 학생의 비율")
    if out.get("history_read"):
        st.caption("해석: " + out["history_read"])
    months = list(h["month"])
    h["low"] = h["score"] - h["sem"]
    h["high"] = h["score"] + h["sem"]
    band = alt.Chart(h).mark_area(opacity=0.18, color="#0d9488").encode(
        x=alt.X("month:N", sort=months, title=None), y=alt.Y("low:Q", title="점수", scale=alt.Scale(domain=[0, 100])), y2="high:Q")
    me = alt.Chart(h).mark_line(point=True, color="#0d9488").encode(x=alt.X("month:N", sort=months), y="score:Q",
                                                                   tooltip=["month", "score", "sem", "rank"])
    avg = alt.Chart(h).mark_line(strokeDash=[5, 4], color="#94a3b8").encode(x=alt.X("month:N", sort=months), y="class_avg:Q")
    t = alt.Chart(h).mark_line(point=True, color="#7c3aed").encode(
        x=alt.X("month:N", sort=months, title=None), y=alt.Y("t:Q", title="T점수", scale=alt.Scale(domain=[20, 80])),
        tooltip=["month", "t", "percentile"])
    base = alt.Chart(pd.DataFrame({"y": [50]})).mark_rule(strokeDash=[4, 4], color="#94a3b8").encode(y="y:Q")
    c1, c2 = st.columns(2)
    c1.markdown("**📈 원점수 (색 띠 = 측정오차 범위, 점선 = 반 평균)**")
    c1.altair_chart((band + avg + me).properties(height=230), use_container_width=True)
    c2.markdown("**📊 반 안 위치 T점수 (점선 = 반 평균 50)**")
    c2.altair_chart((base + t).properties(height=230), use_container_width=True)
    p = pd.DataFrame(out["profile"])
    p["label"] = p["code"] + " " + p["area"]
    pl = pd.concat([p.assign(구분=out["name"], 정답률=p["student_rate"]), p.assign(구분="반 평균", 정답률=p["class_rate"])])
    order = list(p["label"])
    st.markdown("**🎯 성취기준별 정답률 (4회 누적, 반 평균과 비교)**")
    rule = alt.Chart(p).mark_rule(color="#cbd5e1", strokeWidth=3).encode(
        y=alt.Y("label:N", title=None, sort=order), x=alt.X("class_rate:Q", title="정답률(%)", scale=alt.Scale(domain=[0, 100])),
        x2="student_rate:Q")
    dots = alt.Chart(pl).mark_circle(size=140, opacity=1).encode(
        y=alt.Y("label:N", title=None, sort=order), x=alt.X("정답률:Q", scale=alt.Scale(domain=[0, 100])),
        color=alt.Color("구분:N", scale=alt.Scale(domain=[out["name"], "반 평균"], range=["#0d9488", "#94a3b8"])),
        tooltip=["desc", "구분", "정답률"])
    st.altair_chart((rule + dots).properties(height=32 * len(p)), use_container_width=True)
    st.caption("위에 있을수록 반 평균보다 약한 성취기준이에요.")
    st.markdown("**🧩 이번 시험 오답 묶음 (성취기준별 + 지난 시험 유사 문항)**")
    cls = {"반복 약점": "rep", "처음 나온 유형": "new", "이번에만 틀림": "once"}
    for g in out["wrong_groups"]:
        nos = ", ".join(f"{w['no']}번" for w in g["wrong_items"])
        with st.expander(f"{g['code']} {g['area']} · {nos} · 지난 유사 문항 {g['past_correct']} 맞힘"):
            st.markdown(f"<span class='tag {cls[g['pattern']]}'>{g['pattern']}</span> {esc(g['desc'])}",
                        unsafe_allow_html=True)
            for w in g["wrong_items"]:
                st.markdown(f"- 이번 {w['no']}번: {w['title']} (고른 답 {w['picked']}번 / 정답 {w['answer']}번)")
            if g["similar_items"]:
                st.markdown("유사 문항 (지난 시험)")
                for x in g["similar_items"]:
                    st.markdown(f"- {x['exam']} {x['no']}번 {'✅' if x['correct'] else '❌'} {x['title']}")
    fb = out.get("feedback", {})
    c1, c2 = st.columns(2)
    if "parent" in fb:
        c1.markdown("**👪 학부모용 피드백**")
        c1.markdown(f"<div class='paper'>{esc(fb['parent'])}</div>", unsafe_allow_html=True)
    if "student" in fb:
        c2.markdown("**🧑‍🎓 학생용 피드백**")
        c2.markdown(f"<div class='paper'>{esc(fb['student'])}</div>", unsafe_allow_html=True)


def render(out):
    {"notice": render_notice, "exam": render_exam, "student": render_student}[out["kind"]](out)


# ── 탭 ───────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["📒 알림장 에이전트", "📊 학력평가 분석 에이전트"])

with tab1:
    st.markdown("오늘 진도·숙제·앞으로의 진도를 적으면, 에이전트가 **학부모용**과 **학생용** 알림장을 따로 쓰고, "
                "빠진 내용·말투·개인정보를 **스스로 검사**합니다. 다문화 가정 학부모에게는 **번역**도 붙입니다(AI 모드).")
    g = st.selectbox("반", [1, 2, 3], index=1, format_func=lambda x: f"중{x} A반", key="ngrade")
    c1, c2, c3 = st.columns(3)
    today = c1.text_area("오늘 수업 진도", "문학: 소설의 갈등 구조 (「소나기」 1~3장)\n문법: 품사의 분류 복습", height=120, key="ntoday")
    hw = c2.text_area("숙제", "교재 42~45쪽 문제 풀기\n「소나기」 4장 읽고 갈등 정리하기", height=120, key="nhw")
    nxt = c3.text_area("앞으로의 진도 방향", "다음 주: 「소나기」 마무리, 서술자의 시점\n10월 말 학력평가 대비 모의고사", height=120, key="nnext")
    tr = st.checkbox("다문화 가정 학부모에게 번역 붙이기", value=True, key="ntr", disabled=not BACKEND,
                     help="번역은 로컬 AI 또는 Claude 모드에서 됩니다.")
    go = st.button("▶ 알림장 만들기", type="primary", key="ago1")
    key = f"notice:{g}:{hash((today, hw, nxt, tr))}"
    if go:
        st.session_state.aruns.pop(key, None)
        st.session_state["last_notice"] = key
    key = key if go else st.session_state.get("last_notice", key)
    run_and_show(key, "notice", go, render, grade=g, class_name=f"중{g} A반", today=today, homework=hw,
                 next_plan=nxt, translate=bool(tr and BACKEND))

with tab2:
    st.markdown("월말 국어 학력평가를 **고전검사이론**으로 분석합니다. 문항마다 **난이도·변별도·추측도·오답지 매력도**를 따져 "
                "검토할 문항을 찾고, 시험의 **신뢰도와 측정오차**를 계산합니다. 학생별로는 달마다 다른 시험 난이도를 고려해 "
                "**원점수와 반 안 위치(T점수)**로 성적 변화를 해석하고, 틀린 문제를 **성취기준별로 묶어 지난 시험 유사 문항**과 함께 정리합니다.")
    c1, c2 = st.columns(2)
    g2 = c1.selectbox("학년", [1, 2, 3], index=1, format_func=lambda x: f"중{x}", key="egrade")
    ex = T.exams(g2)
    eid = c2.selectbox("시험", [e["id"] for e in ex], index=len(ex) - 1,
                       format_func=lambda i: T.exam(i)["title"], key="eexam")
    mode = st.radio("무엇을 볼까요?", ["📊 반 전체 시험 분석", "👤 학생 리포트"], horizontal=True, key="emode")
    if mode.startswith("📊"):
        go = st.button("▶ 시험 분석하기", type="primary", key="ago2")
        run_and_show(f"exam:{eid}", "exam", go, render, exam_id=eid)
    else:
        ss = [s for s in T.students() if s["grade"] == g2]
        sid = st.selectbox("학생", [s["id"] for s in ss], format_func=lambda i: T.student(i)["name"] + " (가상)", key="estu")
        go = st.button("▶ 학생 리포트 만들기", type="primary", key="ago3")
        run_and_show(f"student:{sid}:{eid}", "student", go, render, student_id=sid, exam_id=eid)
