"""에이전트 전체 설정.

교육적 판단 기준(비계 단계, 점수 기준)은 이 파일 한 곳에 모아 두었다.
도메인 전문가(교사)의 확인을 받아 숫자만 바꾸면 에이전트 동작이 바뀐다.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

MODEL = "claude-opus-5-5"
MAX_AGENT_TURNS = 20

LANGUAGE_NAMES = {
    "vi": "베트남어",
    "zh": "중국어",
    "ru": "러시아어",
    "mn": "몽골어",
}

# ── 비계(scaffolding) 단계 ─────────────────────────────────────────
# 1단계가 지원이 가장 많고, 3단계로 갈수록 지원을 줄인다(fading).
# [도메인 확인 필요] 단계 정의와 아래 점수 기준은 교사 확인 후 확정한다.
SCAFFOLD_LEVELS = {
    1: {
        "name": "1단계 · 모국어 중심 지원",
        "policy": "쉬운 한국어 + 모국어 전체 번역 + 그림 어휘 카드(전체)",
        "show_full_translation": True,
        "vocab_card_count": 8,
    },
    2: {
        "name": "2단계 · 쉬운 한국어 중심",
        "policy": "쉬운 한국어 중심 + 핵심어만 모국어(어휘 카드 5개)",
        "show_full_translation": False,
        "vocab_card_count": 5,
    },
    3: {
        "name": "3단계 · 원문 + 필요할 때만 도움",
        "policy": "원문 한국어 + 어려운 낱말 풀이(괄호) + 어휘 카드 3개",
        "show_full_translation": False,
        "vocab_card_count": 3,
    },
}

# 진단 문제 정답률(%) → 시작 단계  (교사 확인: '느슨한 기준' 채택, 2026-10-16)
DIAGNOSIS_RULES = [
    (80, 3),  # 5문제 중 4개 이상 → 3단계
    (40, 2),  # 2~3개 → 2단계
    (0, 1),   # 1개 이하 → 1단계
]
DIAGNOSIS_RULE_TEXT = "5문제 중 4개 이상 3단계 / 2~3개 2단계 / 1개 이하 1단계"

# 수업 후 확인 문제 정답률(%) → 단계 조정
CHECK_UP_THRESHOLD = 75    # 이 이상이면 지원 줄이기(단계 +1)
CHECK_DOWN_THRESHOLD = 50  # 이 미만이면 지원 늘리기(단계 -1)

# 쉬운 한국어 가독성 기준 (어절 = 띄어쓰기 단위)
READABILITY_MAX_AVG_EOJEOL = 8
READABILITY_MAX_SENTENCE_EOJEOL = 12
