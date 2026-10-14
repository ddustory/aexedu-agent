"""에이전트 루프.

목표(goal)를 받으면 '두뇌(brain)'가 다음에 쓸 도구를 고르고, 루프가 그 도구를 실행해
결과를 다시 두뇌에게 돌려준다. 두뇌가 더 이상 도구를 부르지 않을 때까지 반복한다.
모든 단계는 이벤트로 흘려보내 화면 트레이스에 그대로 표시된다.

- ClaudeBrain  : 실제 Claude 가 도구를 고른다 (API 키 필요).
- ScriptedBrain: 오프라인 시연용. 같은 도구를 같은 루프로 실행하되,
                 도구 선택은 미리 짜 둔 시나리오(offline_scripts.py)가 한다.
"""

import json
from dataclasses import dataclass, field
from typing import Iterator

from . import llm
from .config import MAX_AGENT_TURNS
from .tools import TOOL_SCHEMAS, AgentState, ToolError, execute


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class Step:
    thinking: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    calls: list[ToolCall] = field(default_factory=list)
    error: str | None = None


SYSTEM_PROMPT = """당신은 한국 초등학교 교실의 '포용·다문화 학습 지원 에이전트'입니다.
이주배경 학생(모국어: 베트남어·중국어·러시아어·몽골어, 한국어 초급~중급)이 수업을 따라올 수 있도록
교사를 돕습니다. 주어진 목표를 이루기 위해 도구를 스스로 골라 여러 단계로 일합니다.

일하는 원칙:
1. 항상 get_student_profile 로 학생을 먼저 확인합니다.
2. 학생의 현재 비계 단계가 없으면 run_diagnostic_quiz → decide_scaffold_level(mode='diagnosis') 로 정합니다.
3. 자료는 decide_scaffold_level 이 돌려준 support_policy 를 그대로 따릅니다.
   (1단계: 쉬운 한국어 + 모국어 전체 번역 + 어휘 카드 / 2단계: 쉬운 한국어 + 핵심어만 모국어 / 3단계: 원문 + 괄호 풀이)
   단계가 이미 있으면 그 단계의 정책을 따르며, 정책은 1단계일수록 지원이 많습니다.
4. 1·2단계는 rewrite_easy_korean 결과를 반드시 check_readability 로 확인하고, 기준 미달이면 다시 고쳐 씁니다(최대 2번).
5. 어휘 카드는 정책의 개수만큼, find_difficult_words 가 찾은 순서(중요한 순)대로 만듭니다.
6. 마지막에는 present_lesson_material / present_bilingual / present_support_plan 중 알맞은 도구로 결과를 화면에 보여줍니다.
7. 모든 도구 호출의 reason 에 '왜 지금 이 도구를 쓰는지'를 교사가 이해할 수 있는 한국어 한 문장으로 씁니다.
8. 정해진 기준에 없는 교육적 판단(예: 기준표 밖의 단계 변경)은 스스로 하지 말고, 교사에게 확인을 요청하는 말로 남깁니다.
9. 번역은 교사 확인용 보조 자료임을 기억하고, 확신이 없는 번역은 teacher_note 에 적습니다.
10. 학생에게 줄 한국어 글(수업 자료, 질문의 답)은 반드시 '낱말 주머니'에 맞춥니다:
    get_word_pocket 으로 학생을 본 뒤 글을 쓰고 → check_coverage 로 잽니다(기준: 아는 낱말 80% 이상, 새 낱말 3개까지).
    기준 미달이면 check_coverage 가 준 words_to_replace / terms_to_keep / terms_to_defer 를 그대로 adapt_to_pocket 에 넘겨
    고치고, 다시 check_coverage 로 잽니다(최대 2번). 같은 글이라도 학생마다 아는 낱말이 달라 결과가 달라야 합니다.
    미룬 핵심 용어가 있으면 teacher_note 에 '다음 수업의 새 낱말'로 적습니다. 모국어 번역은 맞춘 뒤의 글로 만듭니다.
11. 학생이 '좀 더 쉽게'를 요청하면 ease_step 을 요청 횟수로 올려 다시 맞추고 present_personalized 로 보여줍니다.
    needs_full_rewrite 가 true 면 rewrite_easy_korean(level=1)로 짧게 다시 쓴 뒤 그 글을 맞춥니다.
12. 또래 연결 요청은 지원 단계를 확인(없으면 진단)한 뒤 find_peer_group → present_peer_group 으로 처리합니다.
13. 다 끝나면 교사에게 무엇을 했는지 쉬운 한국어 2~3문장으로 요약합니다.
학생 개인정보는 다루지 않으며, 모든 학생은 가상 인물입니다."""


class ClaudeBrain:
    """실제 Claude 가 다음 행동을 결정한다 (tool use 기반)."""

    label = "Claude (실시간 AI)"

    def __init__(self, goal: str):
        self.messages = [{"role": "user", "content": goal}]

    def next(self, results: list[dict] | None) -> Step:
        if results:
            self.messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": r["id"], "content": r["content"],
                 **({"is_error": True} if r["is_error"] else {})}
                for r in results
            ]})
        resp = llm.create_message(
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            output_config={"effort": "medium"},
            messages=self.messages,
        )
        self.messages.append({"role": "assistant", "content": resp.content})
        step = Step()
        if resp.stop_reason == "refusal":
            step.error = "AI가 이 요청을 처리하지 못했습니다(거절)."
            return step
        for b in resp.content:
            if b.type == "thinking" and b.thinking:
                step.thinking.append(b.thinking)
            elif b.type == "text" and b.text.strip():
                step.texts.append(b.text.strip())
            elif b.type == "tool_use":
                step.calls.append(ToolCall(b.id, b.name, dict(b.input)))
        if resp.stop_reason == "max_tokens" and not step.calls:
            step.error = "응답이 너무 길어 중간에 끊겼습니다."
        return step


def _ollama_tools() -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": t["input_schema"]}} for t in TOOL_SCHEMAS]


class LocalBrain:
    """노트북 안의 오픈 모델(Ollama)이 다음 행동을 결정한다. 인터넷·API 키가 필요 없다."""

    def __init__(self, goal: str):
        self.label = f"로컬 AI ({llm.LOCAL_MODEL} · 이 컴퓨터 안에서 실행)"
        self.messages = [{"role": "user", "content": goal}]
        self.tools = _ollama_tools()
        self.counter = 0
        self.pending: list[ToolCall] = []

    def next(self, results: list[dict] | None) -> Step:
        if results:
            names = {c.id: c.name for c in self.pending}
            for r in results:
                self.messages.append({"role": "tool", "tool_name": names.get(r["id"], ""), "content": r["content"]})
        msg = llm.local_chat(self.messages, tools=self.tools, system=SYSTEM_PROMPT + LOCAL_HINT)
        self.messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
        step = Step()
        if (msg.get("content") or "").strip():
            step.texts.append(msg["content"].strip())
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            self.counter += 1
            step.calls.append(ToolCall(f"local_{self.counter}", fn.get("name", ""), dict(args)))
        self.pending = step.calls
        return step


LOCAL_HINT = """

(로컬 모델 안내) 한 번에 도구 하나씩 부르고, 도구 결과를 읽은 뒤 다음 도구를 고르세요.
도구 이름과 입력 형식을 정확히 지키고, 모든 설명은 한국어로 씁니다."""


class ScriptedBrain:
    """오프라인 시연용 두뇌. 미리 짜 둔 시나리오가 도구 결과를 보고 다음 도구를 고른다."""

    label = "오프라인 시연 (미리 준비된 시나리오)"

    def __init__(self, script):
        self.gen = script
        self.started = False
        self.counter = 0

    def next(self, results: list[dict] | None) -> Step:
        if not self.started:
            self.started = True
            step = next(self.gen)
        else:
            errors = [r for r in results if r["is_error"]]
            if errors:
                self.gen.close()
                return Step(texts=[f"도구 실행에 실패해서 작업을 멈춥니다: {errors[0]['content']}"])
            try:
                step = self.gen.send([json.loads(r["content"]) for r in results])
            except StopIteration:
                return Step()
        for c in step.calls:
            self.counter += 1
            c.id = f"offline_{self.counter}"
        return step


def run_agent(brain, state: AgentState) -> Iterator[dict]:
    """에이전트 루프를 돌리며 화면에 보여줄 이벤트를 하나씩 내보낸다."""
    results = None
    for turn in range(1, MAX_AGENT_TURNS + 1):
        try:
            step = brain.next(results)
        except llm.OfflineUnsupported as e:
            yield {"type": "error", "text": str(e)}
            return
        except Exception as e:  # API 연결 오류 등
            yield {"type": "error", "text": f"AI 호출 중 오류가 났습니다: {e}"}
            return
        for t in step.thinking:
            yield {"type": "thinking", "text": t}
        if step.error:
            yield {"type": "error", "text": step.error}
            return
        if not step.calls:
            yield {"type": "final", "text": "\n\n".join(step.texts)}
            return
        for t in step.texts:
            yield {"type": "say", "text": t}

        results = []
        for call in step.calls:
            args = dict(call.input)
            reason = args.get("reason", "")
            yield {"type": "tool_call", "turn": turn, "name": call.name, "reason": reason,
                   "input": {k: v for k, v in args.items() if k != "reason"}}
            try:
                out = execute(state, call.name, args)
                summary = out.get("_summary", "")
                payload = {k: v for k, v in out.items() if k != "_summary"}
                results.append({"id": call.id, "content": json.dumps(payload, ensure_ascii=False), "is_error": False})
                yield {"type": "tool_result", "name": call.name, "ok": True, "summary": summary, "output": payload}
            except (ToolError, llm.OfflineUnsupported, TypeError) as e:
                results.append({"id": call.id, "content": f"오류: {e}", "is_error": True})
                yield {"type": "tool_result", "name": call.name, "ok": False, "summary": f"오류: {e}", "output": {}}
            except Exception as e:
                results.append({"id": call.id, "content": f"오류: {e}", "is_error": True})
                yield {"type": "tool_result", "name": call.name, "ok": False, "summary": f"오류: {e}", "output": {}}
    yield {"type": "error", "text": f"{MAX_AGENT_TURNS}단계 안에 끝내지 못해 멈췄습니다."}


# ── 목표(goal) 문장 만들기 ────────────────────────────────────────

def goal_lesson(student_id: str, passage_text: str, passage_id: str | None) -> str:
    src = f"(지문 ID: {passage_id})" if passage_id else "(교사가 직접 입력한 지문)"
    return (f"학생 {student_id} 를 위해 아래 지문으로 오늘 수업 학습 자료를 만들어 주세요. {src}\n\n"
            f"[지문]\n{passage_text}")


def goal_question(student_id: str, question: str) -> str:
    return (f"수업 중 학생 {student_id} 가 모국어로 이렇게 질문했습니다:\n\"{question}\"\n"
            f"오늘 수업 내용(물의 순환)과 연결해, 쉬운 한국어와 학생 모국어로 함께 답해 주세요. "
            f"답에 나오는 핵심 낱말은 어휘 카드로 붙여 주세요.\n"
            f"(순서: get_student_profile → get_word_pocket → answer_student_question 으로 한국어 답 → check_coverage → "
            f"(기준 미달이면 adapt_to_pocket → check_coverage) → translate_text 로 모국어 번역 → "
            f"make_vocab_cards → present_bilingual 에 korean_text=한국어 답, native_text=번역)")


def goal_teacher_sentence(student_id: str, sentence: str) -> str:
    return (f"교사가 수업 중 아래 문장으로 설명했습니다. 학생 {student_id} 가 이해할 수 있게 "
            f"한국어와 모국어를 나란히 보여 주세요. 어려운 낱말이 있으면 어휘 카드도 붙여 주세요.\n\"{sentence}\"")


def goal_fading(student_id: str, passage_id: str, results: list[bool]) -> str:
    marks = ", ".join(f"{i + 1}번 {'맞음' if r else '틀림'}" for i, r in enumerate(results))
    return (f"학생 {student_id} 의 수업 후 확인 문제 결과입니다 (지문 {passage_id}): {marks}.\n"
            f"결과를 채점해 비계 단계를 조정하고, 다음 수업 지원 계획을 교사에게 보여 주세요.")


def goal_personal(student_id: str, text: str, ease_step: int) -> str:
    if ease_step == 0:
        head = (f"학생 {student_id} 에게 아래 글을 보여주려 합니다. 이 학생이 아는 낱말로 맞춰 주세요. "
                f"(ease_step=0)")
    else:
        head = (f"학생 {student_id} 가 \"좀 더 쉽게 설명해 주세요\"라고 했습니다 ({ease_step}번째 요청, ease_step={ease_step}). "
                f"아래 글을 이 학생이 아는 말로 더 쉽게 맞춰 주세요.")
    return f"{head}\n\n[글]\n{text}"


def goal_peer(student_id: str, mode: str) -> str:
    kind = "같은 모국어를 쓰는 친구" if mode == "same_language" else "모국어가 서로 달라 한국어로 대화하게 되는 친구"
    return (f"학생 {student_id} 와 한국어 수준이 비슷한 또래를 지역과 상관없이 찾아 4명 모둠을 만들어 주세요. "
            f"이번에는 '{kind}'로 묶어 주세요 (mode={mode}).")
