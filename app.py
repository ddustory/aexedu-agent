"""시연용 화면 (Streamlit). 실행: streamlit run app.py"""

import html
import json
import time

import streamlit as st

from agent import data, llm, service
from agent.config import LANGUAGE_NAMES, SCAFFOLD_LEVELS
from agent import pocket
from agent.config import COVERAGE_MIN, KNOWN_AFTER_CORRECT, MAX_NEW_WORDS
from agent.tools import (MARK_CLOSE, MARK_OPEN, NOTE_CLOSE, NOTE_OPEN, TOOL_LABELS, AgentState, get_word_pocket,
                         personalize_wording, record_word_feedback)

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
mark.chg {background:#fde68a; color:inherit; border-radius:4px; padding:0 2px;}
.note {color:#047857; font-size:0.88em;}
.ptext {font-size:1.08rem; line-height:1.9; white-space:pre-wrap;}
.chip {display:inline-block; border:1px solid #e5e7eb; border-radius:999px; padding:1px 10px; margin:2px; font-size:0.85rem; background:white;}
.bubble {background:#eef2ff; border-radius:14px 14px 14px 4px; padding:8px 14px; display:inline-block;}
.peer {border:1px solid #e5e7eb; border-radius:12px; padding:10px; background:white; height:100%;}
.peer.me {border-color:#6366f1; background:#eef2ff;}
.peer .nm {font-weight:700; font-size:1.05rem;} .peer .sub {font-size:0.82rem; color:#4b5563;}
.peer .why {font-size:0.78rem; color:#6b7280; margin-top:4px;}
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
BACKEND = llm.backend()
mode_html = {
    "claude": '<span class="mode on">🟢 실시간 AI 모드 (Claude)</span>',
    "local": f'<span class="mode on">💻 로컬 AI 모드 ({llm.LOCAL_MODEL} · 이 노트북 안에서 실행 · 인터넷·사용료 없음)</span>',
}.get(BACKEND, '<span class="mode off">🎬 오프라인 시연 모드 (미리 준비된 시나리오 · 도구는 실제 실행)</span>')
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
    st.caption(f"{stu['grade']} · {stu['region']} · 한국 생활 {stu['months_in_korea']}개월 · "
               f"아는 낱말 수준 {stu['vocab_band']}/3\n\n📝 {stu['teacher_memo']}")

    st.divider()
    st.subheader("🪜 학생별 지원 단계")
    for s in students:
        lv = state.levels.get(s["id"])
        st.markdown(f"- **{s['display_name'].split(' ')[0]}** : " + (f"{lv}단계" if lv else "진단 전"))
    with st.expander("단계 기준 보기"):
        for n, lv in SCAFFOLD_LEVELS.items():
            st.markdown(f"**{lv['name']}**  \n{lv['policy']}")
        st.caption("진단: 80% 이상 3단계 / 50% 이상 2단계 / 그 미만 1단계\n\n"
                   "확인 문제: 75% 이상 → 지원 줄이기, 50% 미만 → 지원 늘리기")
    st.divider()
    first = stu["display_name"].split(" ")[0]
    st.subheader(f"🧺 {first}의 낱말 주머니")
    pk = get_word_pocket(state, sid)
    st.markdown(f"아는 낱말 **{pk['known_count']}개**")
    if pk["learning"]:
        st.markdown("배우는 중: " + ", ".join(f"{w} ({n}/{KNOWN_AFTER_CORRECT})" for w, n in pk["learning"].items()))
    if pk["newly_known"]:
        st.markdown("새로 알게 된 낱말 🎉: " + ", ".join(pk["newly_known"]))
    if pk["marked_unknown"]:
        st.markdown("'몰라요' 표시: " + ", ".join(pk["marked_unknown"]))
    st.caption(f"기준: 아는 낱말 {COVERAGE_MIN}% 이상 · 새 낱말 {MAX_NEW_WORDS}개까지 · {KNOWN_AFTER_CORRECT}번 맞히면 아는 낱말")
    if st.button("🔄 처음부터 다시 (단계·주머니 초기화)", use_container_width=True):
        st.session_state.agent_state = AgentState()
        st.session_state.runs = {}
        st.rerun()

    st.divider()
    if BACKEND == "local":
        st.success(f"노트북 안의 AI({llm.LOCAL_MODEL})가 도구를 고릅니다. 학생 정보가 컴퓨터 밖으로 나가지 않아요. "
                   "작은 모델이라 Claude보다 느리거나 번역이 서툴 수 있어요.")
    elif ONLINE:
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


def render_pair(korean: str, native: str, lang: str, ko_label: str = "쉬운 한국어"):
    k, n = korean.strip().split("\n"), native.strip().split("\n")
    head = f"<tr><th>🇰🇷 {esc(ko_label)}</th><th>🌐 {LANGUAGE_NAMES[lang]}</th></tr>"
    if len(k) == len(n):
        rows = "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td></tr>" for a, b in zip(k, n))
    else:
        rows = f"<tr><td>{esc(korean)}</td><td>{esc(native)}</td></tr>"
    st.markdown(f"<table class='pair' style='width:100%'>{head}{rows}</table>", unsafe_allow_html=True)


def render_coverage(cov: dict | None, s: dict, key: str):
    """'낱말 주머니'로 잰 결과와, 학생 반응(몰라요/맞혔어요) 버튼."""
    if not cov:
        return
    sid_ = s["id"]
    name = s["display_name"].split(" ")[0]
    ok = "✅ 기준 통과" if cov["passed"] else "⚠️ 기준 미달 (교사 확인)"
    st.markdown(f"**🧺 {name}의 낱말 주머니로 잰 결과** · {ok}  \n"
                f"아는 낱말 **{cov['coverage']}%** (기준 {COVERAGE_MIN}% 이상) · "
                f"새 낱말 **{len(cov['new_words'])}개** (기준 {MAX_NEW_WORDS}개 이하)")
    st.progress(min(cov["coverage"], 100) / 100)
    words = list(dict.fromkeys(cov["new_words"] + cov["learning_words"]))
    if words:
        st.caption(f"{name}의 반응을 눌러 주세요. {KNOWN_AFTER_CORRECT}번 맞히면 아는 낱말이 되고, '몰라요'는 다음 글에서 쉬운 말로 바뀌어요.")
    for w in words:
        stt = pocket.status(state, sid_, w, pocket.lookup(w)[1])
        rec = state.pocket.get(sid_, {}).get(w, {})
        tag = {"known": "✔ 아는 낱말", "learning": f"배우는 중 {rec.get('correct', 0)}/{KNOWN_AFTER_CORRECT}",
               "unknown": "새 낱말"}[stt]
        c1, c2, c3 = st.columns([3, 2, 2])
        c1.markdown(f"**{w}** <small style='color:#6b7280'>· {tag}</small>", unsafe_allow_html=True)
        if c2.button("😕 몰라요", key=f"fb:{key}:{w}:no", use_container_width=True):
            r = record_word_feedback(state, sid_, w, "dont_know")
            st.toast(r["_summary"])
            st.rerun()
        if c3.button("✅ 맞혔어요", key=f"fb:{key}:{w}:ok", use_container_width=True):
            r = record_word_feedback(state, sid_, w, "correct")
            st.toast(r["_summary"])
            st.rerun()
    others = [w for w in cov.get("known_list", []) if len(w) >= 2]
    if others:
        pick = st.multiselect("아는 낱말로 셌지만 학생이 모른다고 한 낱말이 있나요?", others, key=f"fbm:{key}",
                              placeholder="낱말을 고르세요")
        if pick and st.button("😕 고른 낱말을 '몰라요'로 기록", key=f"fbmb:{key}"):
            for w in pick:
                record_word_feedback(state, sid_, w, "dont_know")
            st.toast(f"{len(pick)}개 낱말을 '몰라요'로 기록했어요. 다시 만들면 쉬운 말로 바뀌어요.")
            st.rerun()


def render_output(out: dict, key: str = ""):
    s = data.student(out["student_id"])
    lang = s["home_language"]
    name = s["display_name"].split(" ")[0]
    if out["kind"] == "lesson":
        lv = out["level"]
        st.markdown(f"<span class='lv'>{lv}단계</span> **{SCAFFOLD_LEVELS[lv]['name']}** · {s['display_name']}",
                    unsafe_allow_html=True)
        st.caption(SCAFFOLD_LEVELS[lv]["policy"])
        if out["native_text"]:
            render_pair(out["korean_text"], out["native_text"], lang, f"{name} 맞춤 한국어")
        else:
            st.markdown(f"**📖 {name} 맞춤 지문**")
            st.info(out["korean_text"])
        render_cards(out["vocab_cards"])
        if out["teacher_note"]:
            st.markdown(f"**👩‍🏫 교사용 수업 팁**  \n{out['teacher_note']}")
        render_coverage(out.get("coverage"), s, key)
    elif out["kind"] == "bilingual":
        title = "🙋 학생 질문에 대한 답" if out["mode"] == "answer" else "👩‍🏫 교사 설명 나란히 보기"
        st.markdown(f"**{title}** · {s['display_name']}")
        if out["original_text"] and out["mode"] == "answer":
            st.markdown(f"> 학생 질문: {out['original_text']}")
        render_pair(out["korean_text"], out["native_text"], lang,
                    f"{name} 맞춤 한국어" if out["mode"] == "answer" else "선생님 설명")
        render_cards(out["vocab_cards"])
        render_coverage(out.get("coverage"), s, key)
    elif out["kind"] == "personal":
        render_personal(out, s)
        render_coverage(out.get("coverage"), s, key)
    elif out["kind"] == "peers":
        render_peers(out, s)
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


def marked_html(t: str) -> str:
    h = html.escape(t or "")
    for a, b in ((MARK_OPEN, "<mark class='chg'>"), (MARK_CLOSE, "</mark>"),
                 (NOTE_OPEN, "<span class='note'>"), (NOTE_CLOSE, "</span>")):
        h = h.replace(a, b)
    return h


def render_personal(out: dict, s: dict):
    step = out["ease_step"]
    st.markdown(f"**🪄 {s['display_name']} 맞춤 글** · "
                + ("처음 맞춤" if step == 0 else f"'좀 더 쉽게' {step}번째") +
                f" · 낱말 수준 {out['effective_band']} 기준", unsafe_allow_html=True)
    st.markdown(f"<div class='bubble'>🤖 {esc(out['message'])}</div>", unsafe_allow_html=True)
    st.write("")
    st.markdown(f"<div class='ptext'>{marked_html(out['marked_text'])}</div>", unsafe_allow_html=True)
    st.caption("노란색 = 이 학생이 아는 말로 바꾼 곳 · 초록색 = 핵심 용어 풀이 (용어 자체는 그대로 가르쳐요)")
    if out["changes"]:
        st.markdown(" ".join(f"<span class='chip'>{esc(c['from'])} → <b>{esc(c['to'])}</b></span>"
                             for c in out["changes"]), unsafe_allow_html=True)
    with st.expander("원래 글 보기"):
        st.write(out["original_text"])


def render_peers(out: dict, s: dict):
    mode = "같은 모국어 친구" if out["mode"] == "same_language" else "모국어가 다른 친구 (한국어로 대화)"
    st.markdown(f"**🤝 {s['display_name']}의 또래 모둠** · {mode}")
    c1, c2 = st.columns(2)
    c1.metric(f"같은 지역({out['student_region']}) 안 후보", f"{out['local_candidates']}명")
    c2.metric("지역을 넘은 후보", f"{out['nationwide_candidates']}명",
              delta=f"+{out['nationwide_candidates'] - out['local_candidates']}명")
    people = [{"name": s["display_name"].split(" ")[0] + " (우리 학생)", "region": s["region"], "center": "우리 반",
               "language": s["home_language_name"], "level": out["level"], "grade": s["grade"], "why": "", "me": True}]
    people += out["members"]
    cols = st.columns(2)
    for i, p in enumerate(people):
        cols[i % 2].markdown(
            f"<div class='peer{' me' if p.get('me') else ''}'><div class='nm'>{esc(p['name'])}</div>"
            f"<div class='sub'>📍 {esc(p['region'])} · {esc(p['center'])}</div>"
            f"<div class='sub'>🌐 {esc(p['language'])} · {p['level']}단계 · {esc(p['grade'])}</div>"
            + (f"<div class='why'>{esc(p['why'])}</div>" if p.get("why") else "") + "</div>",
            unsafe_allow_html=True)
        if i % 2 == 1:
            cols = st.columns(2)
    st.write("")
    st.success(out["message"])
    st.markdown(f"**함께 할 활동**: {out['activity']}  \n**대화 언어**: {out['talk_language']}")
    st.caption("미리보기입니다. 친구와 센터는 모두 가상이며, 실제 온라인 모둠 방 연결은 본선 확장 계획입니다.")


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
        for i, out in enumerate(run["outputs"]):
            render_output(out, f"{key}:{i}")


# ── 탭 ───────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs(["① 수업 자료 만들기",
                                        "② 이중언어 도우미",
                                        "③ 지원 단계 조정",
                                        "④ 학생 맞춤 낱말 (파파고와 다른 점)",
                                        "⑤ 지역 너머 또래 연결"])

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

with tab4:
    st.markdown("번역기는 누가 넣어도 **같은 결과 하나**를 내놓아요. 이 에이전트는 **학생마다 아는 낱말이 다르다**는 데서 "
                "출발해, 같은 글을 **그 학생이 아는 말로** 바꿔요. 학생이 **\"좀 더 쉽게\"**라고 하면 한 단계씩 더 쉽게 맞춥니다.")
    ptext = st.text_area("학생에게 보여줄 글", value=P["text"], height=130, key="ptext")
    if not ONLINE:
        st.caption("오프라인 시연 모드: 낱말 바꾸기는 어떤 글이든 되고, 문장 전체를 다시 쓰는 단계는 예시 지문에서만 됩니다.")
    ease_map = st.session_state.setdefault("ease", {})
    ekey = f"{sid}:{hash(ptext)}"
    ease = ease_map.get(ekey, 0)
    maxed = ease > stu["vocab_band"]
    c1, c2 = st.columns(2)
    go_fit = c1.button(f"▶ {stu['display_name'].split(' ')[0]}에게 맞추기", type="primary", key="go4",
                       use_container_width=True)
    go_easy = c2.button("🔁 좀 더 쉽게 설명해 주세요", key="go4e", use_container_width=True,
                        disabled=ekey not in ease_map or maxed,
                        help="먼저 '맞추기'를 누른 뒤 쓸 수 있어요.")
    if maxed:
        c2.caption("가장 쉬운 단계까지 왔어요. 이제는 선생님이 직접 그림이나 몸짓으로 설명해 주세요.")
    if go_fit:
        ease = 0
    elif go_easy and not maxed:
        ease += 1
    if go_fit or go_easy:
        ease_map[ekey] = ease
    key = f"personal:{ekey}:{ease}"
    if go_fit or go_easy:
        st.session_state.runs.pop(key, None)
    elif ekey not in ease_map:
        key = "personal:none"
    run_and_show(key, "personal", student_id=sid, text=ptext, ease_step=ease, _go=go_fit or go_easy)

    st.divider()
    st.markdown("#### 같은 글, 학생마다 다른 결과")
    st.caption("위 글을 네 학생에게 각각 맞춘 결과입니다 (도구를 바로 실행한 비교). 번역기라면 네 칸이 모두 똑같았을 거예요.")
    cols = st.columns(2)
    for i, o in enumerate(students):
        tmp = AgentState()
        r = personalize_wording(tmp, o["id"], ptext, 0)
        with cols[i % 2]:
            st.markdown(f"**{o['display_name'].split(' ')[0]}** · {o['home_language_name']} · 낱말 수준 {o['vocab_band']} "
                        f"→ <b>{len(r['changes'])}곳</b> 바뀜", unsafe_allow_html=True)
            st.markdown(f"<div class='ptext' style='font-size:0.95rem'>{marked_html(tmp.last_personal[o['id']]['marked_text'])}</div>",
                        unsafe_allow_html=True)
            st.write("")

with tab5:
    st.markdown("지역아동센터는 그 지역 안에서만 모이고, 지역마다 출신 나라 비율도 달라서 **수준이 맞는 친구를 찾기 어렵습니다.** "
                "에이전트가 **지역과 상관없이** 한국어 수준이 비슷한 또래를 찾아 온라인 모둠을 제안합니다.")
    mode_label = st.radio("어떻게 묶을까요?", ["🗣️ 모국어가 다른 친구 (한국어로 대화)", "🏠 같은 모국어 친구"],
                          horizontal=True, key="peermode")
    pmode = "mixed_language" if mode_label.startswith("🗣️") else "same_language"
    st.caption("교사가 학생 상황에 맞게 고르세요. 다른 모국어 모둠은 한국어 사용 기회를, 같은 모국어 모둠은 개념 이해를 돕습니다.")
    go = st.button(f"▶ {stu['display_name'].split(' ')[0]}의 또래 모둠 만들기", type="primary", key="go5")
    key = f"peer:{sid}:{pmode}"
    if go:
        st.session_state.runs.pop(key, None)
    run_and_show(key, "peer", student_id=sid, mode=pmode, _go=go)
