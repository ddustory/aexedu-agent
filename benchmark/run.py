"""노트북 AI 모델 비교 실험.

같은 과제를 여러 오픈 모델(Ollama)에 똑같이 시키고, 이 프로젝트가 정한 교육적 기준으로 채점한다.
실행: python -m benchmark.run qwen3:8b qwen3:4b gemma3:4b
결과: benchmark/results/benchmark_report.html, benchmark_report.md, results.json

과제 (모델마다 똑같이)
 A. 학생 맞춤 고쳐 쓰기   — 린·웨이에게 '물의 순환' 쉬운 글을 낱말 주머니에 맞게 고치기
                            기준: 아는 낱말 80% 이상 · 새 낱말 3개 이하 · 한국어로만 · 핵심 용어 유지
 B. 학생 질문에 답하기     — 학생 4명의 모국어 질문(베트남어·중국어·러시아어·몽골어)에 쉬운 한국어로 답
                            기준: 한국어로 답함 · 질문을 되풀이하지 않음 · 아는 낱말 80% 이상
 C. 학부모 알림장 쓰기     — 기준: 필수 내용·존댓말·길이·개인정보 검사 통과
 D. 에이전트 완주          — 모델이 직접 도구를 골라 '학생 질문 → 한국어 답 → 번역 → 화면 표시'까지 끝내기
                            기준: 오류 없이 마지막 단계(present_bilingual)까지 완료
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

os.environ.pop("ANTHROPIC_API_KEY", None)  # 비교는 노트북 모델끼리만
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

from academy import tools as AT  # noqa: E402
from agent import data, llm, pocket, service  # noqa: E402
from agent.config import COVERAGE_MIN, MAX_NEW_WORDS  # noqa: E402
from agent.tools import AgentState, adapt_to_pocket, answer_student_question, hangul_ratio  # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
DEFAULT_MODELS = ["qwen3:8b", "qwen3:4b", "gemma3:4b"]


def installed() -> list[str]:
    try:
        with urllib.request.urlopen(f"{llm.LOCAL_URL}/api/tags", timeout=3) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except Exception:
        return []


def use_model(name: str):
    llm.LOCAL_MODEL = name
    llm._local_ok = None


def timed(fn, *a, **k):
    t = time.time()
    try:
        return fn(*a, **k), None, round(time.time() - t, 1)
    except Exception as e:  # noqa: BLE001 — 모델 실패도 결과로 기록한다
        return None, f"{type(e).__name__}: {str(e)[:160]}", round(time.time() - t, 1)


def task_adapt(log):
    text = data.offline_demo()["rewrite"]["P01"]["easy"]
    rows = []
    for sid in ("S01", "S02"):
        st = AgentState()
        before = pocket.analyze(st, sid, text)
        out, err, sec = timed(adapt_to_pocket, st, sid, text, before["words_to_replace"],
                              before["terms_to_defer"], before["terms_to_keep"])
        if err:
            rows.append({"student": sid, "pass": False, "sec": sec, "error": err})
            log(f"   A {sid}: 실패 ({err[:60]})")
            continue
        t = out["adapted_text"]
        after = pocket.analyze(st, sid, t)
        kept = all(k in t for k in before["terms_to_keep"])
        ok = after["coverage"] >= COVERAGE_MIN and len(after["new_words"]) <= MAX_NEW_WORDS and hangul_ratio(t) >= 0.9 and kept
        rows.append({"student": sid, "pass": ok, "sec": sec, "coverage_before": before["coverage"],
                     "coverage": after["coverage"], "new_words": len(after["new_words"]), "korean": round(hangul_ratio(t), 2),
                     "kept_terms": kept, "sample": t[:160]})
        log(f"   A {sid}: {'통과' if ok else '미달'} · 아는 낱말 {before['coverage']}% → {after['coverage']}% · "
            f"새 낱말 {len(after['new_words'])}개 · {sec}초")
    return rows


def task_answer(log):
    rows = []
    for s in data.students():
        q = data.offline_demo()["student_questions"][s["home_language"]]["question"]
        st = AgentState()
        out, err, sec = timed(answer_student_question, st, s["id"], q)
        if err:
            rows.append({"student": s["id"], "lang": s["home_language_name"], "pass": False, "sec": sec, "error": err})
            log(f"   B {s['home_language_name']}: 실패 ({err[:60]})")
            continue
        a = out["korean_answer"]
        cov = pocket.analyze(st, s["id"], a)
        echo = q.strip() in a or a.strip().endswith("?")
        ok = hangul_ratio(a) >= 0.9 and not echo and cov["coverage"] >= COVERAGE_MIN
        rows.append({"student": s["id"], "lang": s["home_language_name"], "pass": ok, "sec": sec,
                     "korean": round(hangul_ratio(a), 2), "coverage": cov["coverage"], "echo": echo, "sample": a[:160]})
        log(f"   B {s['home_language_name']}: {'통과' if ok else '미달'} · 한국어 {hangul_ratio(a):.0%} · "
            f"아는 낱말 {cov['coverage']}% · {sec}초")
    return rows


def task_notice(log):
    st = AT.AcademyState()
    _, err, sec = timed(AT.draft_notice, st, "parent", "중2 A반", "문학: 소설의 갈등 구조 (「소나기」 1~3장)\n문법: 품사의 분류 복습",
                        "교재 42~45쪽 문제 풀기\n「소나기」 4장 읽고 갈등 정리하기", "다음 주: 서술자의 시점\n10월 말 학력평가 대비")
    if err:
        log(f"   C 알림장: 실패 ({err[:60]})")
        return [{"pass": False, "sec": sec, "error": err}]
    chk = AT.check_notice(st, "parent")
    log(f"   C 알림장: {'통과' if chk['passed'] else '미달 — ' + ' / '.join(chk['problems'])} · {sec}초")
    return [{"pass": chk["passed"], "sec": sec, "problems": chk["problems"], "sample": st.notices["parent"]["text"][:160]}]


def task_agent(log):
    rows = []
    for sid in ("S01", "S04"):
        s = data.student(sid)
        q = data.offline_demo()["student_questions"][s["home_language"]]["question"]
        st = AgentState()
        t0 = time.time()
        events, err = [], None
        try:
            events = list(service.run("question", st, student_id=sid, text=q))
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:160]}"
        sec = round(time.time() - t0, 1)
        calls = [e["name"] for e in events if e["type"] == "tool_call"]
        bad = [e for e in events if e["type"] == "tool_result" and not e["ok"]]
        errs = [e["text"] for e in events if e["type"] == "error"]
        done = any(o["kind"] == "bilingual" for o in st.outputs)
        if errs and not err:
            err = errs[0][:160]
        no_tools = bool(err and "tool" in err.lower() and "support" in err.lower())
        rows.append({"student": sid, "pass": done and not errs, "sec": sec, "tool_calls": len(calls),
                     "tool_errors": len(bad), "tools": calls, "error": err, "no_tool_support": no_tools})
        why = "도구 호출을 지원하지 않는 모델" if no_tools else (err or "")[:60]
        log(f"   D 에이전트({s['home_language_name']}): {'완주' if done and not errs else '실패'} · 도구 {len(calls)}번"
            f"(오류 {len(bad)}) · {sec}초" + (f" · {why}" if why and not done else ""))
    return rows


def run_model(name: str, log) -> dict:
    use_model(name)
    if not llm.local_available():
        log(f"⚠️ {name} 모델이 없어 건너뜁니다.")
        return {"model": name, "skipped": True}
    log(f"▶ {name} 실험 시작")
    res = {"model": name, "skipped": False}
    for key, fn in (("A", task_adapt), ("B", task_answer), ("C", task_notice), ("D", task_agent)):
        res[key] = fn(log)
    allrows = [r for k in "ABCD" for r in res[k]]
    res["passed"] = sum(r["pass"] for r in allrows)
    res["total"] = len(allrows)
    res["avg_sec"] = round(sum(r["sec"] for r in allrows) / len(allrows), 1)
    log(f"   = {name}: {res['passed']}/{res['total']} 통과 · 평균 {res['avg_sec']}초")
    return res


def _rate(rows):
    return f"{sum(r['pass'] for r in rows)}/{len(rows)}"


def _avg(rows, key):
    v = [r[key] for r in rows if key in r]
    return f"{sum(v) / len(v):.0f}" if v else "-"


def report(results: list[dict]):
    OUT.mkdir(parents=True, exist_ok=True)
    done = [r for r in results if not r["skipped"]]
    best = max(done, key=lambda r: (r["passed"], -r["avg_sec"])) if done else None
    head = ["모델", "A 맞춤 고쳐 쓰기", "A 아는 낱말 %", "B 질문 답(한국어)", "B 아는 낱말 %", "C 알림장", "D 에이전트 완주",
            "전체 통과", "평균 시간(초)"]
    rows = [[r["model"], _rate(r["A"]), _avg(r["A"], "coverage"), _rate(r["B"]), _avg(r["B"], "coverage"),
             _rate(r["C"]), _rate(r["D"]) + (" (도구 호출 미지원)" if any(x.get("no_tool_support") for x in r["D"]) else ""),
             f"{r['passed']}/{r['total']}", str(r["avg_sec"])] for r in done]
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    md = [f"# 노트북 AI 모델 비교 실험 ({when})", "",
          "같은 과제를 모델마다 똑같이 시키고, 이 프로젝트의 교육적 기준으로 채점했습니다.", "",
          f"- 기준: 아는 낱말 {COVERAGE_MIN}% 이상, 새 낱말 {MAX_NEW_WORDS}개 이하, 한국어로만 답하기, 알림장 검사 통과, 에이전트 완주",
          "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    md += ["| " + " | ".join(r) + " |" for r in rows]
    if best:
        md += ["", f"**선택: {best['model']}** — 통과 {best['passed']}/{best['total']}, 평균 {best['avg_sec']}초"]
    md += ["", "## 자세한 결과", "```json", json.dumps(results, ensure_ascii=False, indent=1), "```"]
    (OUT / "benchmark_report.md").write_text("\n".join(md), encoding="utf-8")
    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    th = "".join(f"<th>{h}</th>" for h in head)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    samples = ""
    for r in done:
        b = next((x for x in r["B"] if "sample" in x), None)
        if b:
            samples += f"<h3>{r['model']} — 학생 질문 답 예시 ({b['lang']})</h3><pre>{b['sample']}</pre>"
    html = f"""<!doctype html><meta charset="utf-8"><title>AI 모델 비교 실험</title>
<style>body{{font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;max-width:1100px;margin:32px auto;padding:0 16px;color:#111}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #e5e7eb;padding:8px;text-align:center}}th{{background:#f0fdfa}}
.best{{background:#ecfdf5;border:1px solid #a7f3d0;padding:12px;border-radius:8px;margin:16px 0}}pre{{background:#f8fafc;padding:10px;white-space:pre-wrap}}</style>
<h1>🧪 노트북 AI 모델 비교 실험</h1><p>{when} · 같은 과제를 모델마다 똑같이 시키고 교육적 기준으로 채점했습니다.<br>
기준: 아는 낱말 {COVERAGE_MIN}% 이상 · 새 낱말 {MAX_NEW_WORDS}개 이하 · 한국어로만 답하기 · 알림장 검사 통과 · 에이전트 완주</p>
<table><tr>{th}</tr>{tr}</table>
{f'<div class="best">✅ <b>선택: {best["model"]}</b> — 통과 {best["passed"]}/{best["total"]}, 평균 {best["avg_sec"]}초</div>' if best else ''}
<p>A 맞춤 고쳐 쓰기(학생 2명) · B 질문 답(4개 언어) · C 학부모 알림장 · D 에이전트가 도구를 직접 골라 끝까지 완주(학생 2명)</p>
{samples}<p style="color:#6b7280">이 파일(benchmark_report.md 또는 이 화면 캡처)을 Claude에게 보내면 결과를 정리해 줍니다.</p>"""
    (OUT / "benchmark_report.html").write_text(html, encoding="utf-8")
    return OUT / "benchmark_report.html"


def main(models: list[str]):
    log = lambda m: print(m, flush=True)  # noqa: E731
    have = installed()
    if not have:
        log("❌ Ollama가 켜져 있지 않아요. Ollama 앱을 실행한 뒤 다시 해 주세요.")
        return None
    log(f"설치된 모델: {', '.join(have)}")
    results = [run_model(m, log) for m in models]
    path = report(results)
    log(f"\n✅ 끝! 결과: {path}")
    return path


if __name__ == "__main__":
    main(sys.argv[1:] or DEFAULT_MODELS)
