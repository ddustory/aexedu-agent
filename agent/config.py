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
# [도메인 확정 · 2026-10-14] 단계 정의, 점수 기준, 어휘 카드 수, 문장 길이 기준을
# 교사(도메인 담당)가 검토하고 확정했다. 번역은 원어민 검토 없이 '교사 확인용 보조 자료'로 표시한다.
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

# 진단 문제 정답률(%) → 시작 단계
DIAGNOSIS_RULES = [
    (80, 3),  # 80% 이상 → 3단계
    (50, 2),  # 50% 이상 → 2단계
    (0, 1),   # 그 미만 → 1단계
]

# 수업 후 확인 문제 정답률(%) → 단계 조정
CHECK_UP_THRESHOLD = 75    # 이 이상이면 지원 줄이기(단계 +1)
CHECK_DOWN_THRESHOLD = 50  # 이 미만이면 지원 늘리기(단계 -1)

# 쉬운 한국어 가독성 기준 (어절 = 띄어쓰기 단위)
READABILITY_MAX_AVG_EOJEOL = 8
READABILITY_MAX_SENTENCE_EOJEOL = 12

# ── 학생별 낱말 주머니 기준 (교사 확정 · 2026-10-15) ───────────────
# 학생에게 주는 글은 '아는 낱말' 비율이 이 % 이상이어야 한다.
COVERAGE_MIN = 80
# 한 글에 남겨 둘 새 낱말(모르는 낱말)은 이 개수까지. 오늘 배울 핵심 용어도 여기에 들어간다.
MAX_NEW_WORDS = 3
# 이만큼 맞히면(맞게 쓰거나 문제를 맞히면) '아는 낱말'로 옮긴다.
KNOWN_AFTER_CORRECT = 3
# 기준을 넘지 못하면 다시 고쳐 쓰는 최대 횟수
MAX_ADAPT_ROUNDS = 2
