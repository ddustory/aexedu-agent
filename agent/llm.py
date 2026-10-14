"""Claude API 연결.

- 온라인 모드: ANTHROPIC_API_KEY 가 있으면 실제 Claude 를 부른다.
- 오프라인 시연 모드: 키가 없으면 data/offline_demo.json 의 '미리 준비된 응답'을 쓴다.
"""

import os

from dotenv import load_dotenv

from . import data
from .config import MODEL

load_dotenv()

# 거절(refusal) 시 서버가 자동으로 다른 모델로 다시 시도하게 하는 옵션
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class OfflineUnsupported(Exception):
    """오프라인 시연 모드에서 준비되지 않은 입력이 들어왔을 때."""


def online() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


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
    for item in data.offline_demo()["translations"]:
        if _norm(item["source"]) == _norm(text) and lang in item:
            return item[lang]
    raise OfflineUnsupported("오프라인 시연 모드에서는 예시 문장만 번역할 수 있어요. 새 문장은 API 키를 넣으면 됩니다.")
