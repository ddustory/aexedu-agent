"""AI 두뇌 연결.

- Claude 모드: ANTHROPIC_API_KEY 가 있으면 실제 Claude 를 부른다.
- 로컬 AI 모드: 키가 없고, 이 컴퓨터에서 Ollama 가 켜져 있으면 노트북 안의 오픈 모델을 쓴다.
  (인터넷·사용료 없이 동작하고, 학생 정보가 컴퓨터 밖으로 나가지 않는다)
- 오프라인 시연 모드: 둘 다 없으면 data/offline_demo.json 의 '미리 준비된 응답'을 쓴다.
"""

import json
import os
import urllib.request

from dotenv import load_dotenv

from . import data
from .config import MODEL

load_dotenv()

# 거절(refusal) 시 서버가 자동으로 다른 모델로 다시 시도하게 하는 옵션
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class OfflineUnsupported(Exception):
    """오프라인 시연 모드에서 준비되지 않은 입력이 들어왔을 때."""


LOCAL_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11434")
LOCAL_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen3:8b")
_local_ok = None


def _claude_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def local_available() -> bool:
    """이 컴퓨터에 Ollama 가 켜져 있고, 쓸 모델이 내려받아져 있는지 확인한다(한 번만)."""
    global _local_ok
    if _local_ok is None:
        _local_ok = False
        if os.getenv("LOCAL_LLM", "on").lower() not in ("off", "0", "false"):
            try:
                with urllib.request.urlopen(f"{LOCAL_URL}/api/tags", timeout=1.0) as r:
                    names = [m.get("name", "") for m in json.load(r).get("models", [])]
                _local_ok = any(n in (LOCAL_MODEL, f"{LOCAL_MODEL}:latest") for n in names)
            except Exception:
                _local_ok = False
    return _local_ok


def backend() -> str | None:
    if _claude_key():
        return "claude"
    if local_available():
        return "local"
    return None


def online() -> bool:
    """실제 AI(Claude 또는 로컬 모델)가 연결되어 있는가."""
    return backend() is not None


class LocalModelError(Exception):
    """로컬 모델이 요청을 처리하지 못함 (예: 도구 호출을 지원하지 않는 모델)."""


def _post_chat(body: dict) -> dict:
    import urllib.error

    req = urllib.request.Request(f"{LOCAL_URL}/api/chat", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)["message"]
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise LocalModelError(detail or str(e)) from None


def local_chat(messages: list[dict], tools: list[dict] | None = None, system: str = "") -> dict:
    """Ollama 의 /api/chat 호출. 도구 목록을 주면 모델이 도구를 고른다."""
    body = {"model": LOCAL_MODEL, "stream": False, "think": False,
            "options": {"temperature": 0.2, "num_ctx": 16384},
            "messages": ([{"role": "system", "content": system}] if system else []) + messages}
    if tools:
        body["tools"] = tools
    try:
        msg = _post_chat(body)
    except LocalModelError as e:
        if "think" not in str(e).lower():
            raise
        body.pop("think")  # 생각 모드를 끌 수 없는 모델이면 옵션 없이 다시 보낸다
        msg = _post_chat(body)
    content = msg.get("content") or ""
    if "<think>" in content:  # 생각 과정이 답에 섞여 나오면 지운다
        import re

        msg["content"] = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    return msg


_client = None


def client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic()
    return _client


def create_message(**kwargs):
    """Claude 호출 공통 함수 (거절 시 서버 측 대체 모델 사용)."""
    return client().beta.messages.create(
        model=MODEL,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        thinking={"type": "adaptive", "display": "summarized"},
        **kwargs,
    )


def complete_text(system: str, prompt: str, effort: str = "low") -> str:
    """도구 내부에서 쓰는 짧은 글쓰기 호출 (쉬운 한국어 변환, 번역 등)."""
    if backend() == "local":
        return (local_chat([{"role": "user", "content": prompt}], system=system).get("content") or "").strip()
    resp = create_message(
        max_tokens=8000,
        system=system,
        output_config={"effort": effort},
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("AI가 이 요청을 처리하지 못했습니다(거절).")
    return "".join(b.text for b in resp.content if b.type == "text").strip()


# ── 오프라인 시연용 응답 ────────────────────────────────────────────

def _norm(text: str) -> str:
    return " ".join(text.split())


def offline_rewrite(text: str, level: int) -> str:
    for pid, item in data.offline_demo()["rewrite"].items():
        p = data.passage(pid)
        if p and _norm(p["text"]) == _norm(text):
            return item["annotated"] if level >= 3 else item["easy"]
    raise OfflineUnsupported("오프라인 시연 모드에서는 예시 지문만 변환할 수 있어요. 새 지문은 API 키를 넣으면 됩니다.")


def offline_translate(text: str, lang: str) -> str:
    items = [i for i in data.offline_demo()["translations"] if lang in i]
    for item in items:
        if _norm(item["source"]) == _norm(text):
            return item[lang]
    # 학생 맞춤으로 조금 바뀐 글: 줄마다 가장 비슷한 준비된 줄의 번역을 쓴다
    import difflib
    pairs = []
    for item in items:
        src, tr = item["source"].split("\n"), item[lang].split("\n")
        if len(src) == len(tr):
            pairs += list(zip(src, tr))
    out = []
    for line in text.strip().split("\n"):
        best = max(pairs, key=lambda p: difflib.SequenceMatcher(None, p[0], line).ratio(), default=None)
        if not best or difflib.SequenceMatcher(None, best[0], line).ratio() < 0.4:
            raise OfflineUnsupported("오프라인 시연 모드에서는 예시 문장만 번역할 수 있어요. 새 문장은 AI 모드에서 됩니다.")
        out.append(best[1])
    return "\n".join(out)
