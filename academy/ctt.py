"""고전검사이론(CTT)에 의한 문항·검사 분석.

참고: 「14장 고전검사이론에 의한 문항분석」 강의 자료
- 문항난이도 P = 정답자 수 / 총 피험자 수 (0~1)  → Cangelosi(1990) 3단계 / 성태제(2015) 5단계 해석
- 문항변별도 = 문항 점수와 총점의 상관 (이분 문항: 점이연 상관)  → Ebel(1990) 5단계 해석
- 문항추측도 = 추측으로 맞힌 피험자 비율.  추측으로 맞힌 수 = (정답을 모르는 학생 수) / 답지 수
- 교정 난이도 = 문항난이도 − 문항추측도
- 오답지 매력도: 오답지 응답 비율 > 기대치 (1 − P) / (답지 수 − 1) 이면 매력적인 오답지, 0명이면 답지 기능 상실
  (단, 틀린 학생이 답지 수 × 2 명보다 적으면 0명이 우연일 수 있어 판단을 보류한다 — 소규모 학원 반 보정)
- 신뢰도: 문항 내적 일관성 (이분 문항: KR-20 = Cronbach α),  측정의 표준오차 SEM = SD × √(1 − 신뢰도)
- 한계: 문항 모수가 피험자 집단과 시험 난이도에 따라 달라진다 → 달마다 시험 난이도가 다르므로
  원점수 대신 반 안에서의 위치(표준점수 T = 50 + 10z, 백분위)로 성적 변화를 본다.
"""

from math import sqrt
from statistics import mean, pstdev

# 교사가 고를 수 있는 난이도 해석 기준 (기본: 성태제 2015)
DIFFICULTY_SCALE = "성태제"

_DIFF = {
    "Cangelosi": [(0.25, "어려운 문항"), (0.75, "적절한 문항"), (1.01, "쉬운 문항")],
    "성태제": [(0.2, "매우 어려운 문항"), (0.4, "어려운 문항"), (0.6, "중간 난이도 문항"),
             (0.8, "쉬운 문항"), (1.01, "매우 쉬운 문항")],
}
_EBEL = [(0.1, "변별력이 없는 문항"), (0.2, "변별력이 매우 낮은 문항"), (0.3, "변별력이 낮은 문항"),
         (0.4, "변별력이 있는 문항"), (9, "변별력이 높은 문항")]


def difficulty_label(p: float, scale: str = DIFFICULTY_SCALE) -> str:
    return next(lbl for cut, lbl in _DIFF[scale] if p < cut)


def discrimination_label(d: float) -> str:
    if d < 0:
        return "변별력이 거꾸로인 문항 (잘하는 학생이 더 틀림)"
    return next(lbl for cut, lbl in _EBEL if d < cut)


def _corr(x: list[float], y: list[float]) -> float:
    mx, my = mean(x), mean(y)
    sx, sy = pstdev(x), pstdev(y)
    if sx == 0 or sy == 0:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (len(x) * sx * sy)


def analyze(items: list[dict], answers: dict[str, list[int]], scale: str = DIFFICULTY_SCALE) -> dict:
    """items: [{no, answer, choices, points, ...}], answers: {학생ID: [고른 답, ...]}"""
    ids = list(answers)
    n, k = len(ids), len(items)
    scored = {s: [int(a == it["answer"]) for a, it in zip(answers[s], items)] for s in ids}
    totals = {s: sum(it["points"] * c for it, c in zip(items, scored[s])) for s in ids}
    tot = [totals[s] for s in ids]
    out_items = []
    for i, it in enumerate(items):
        q = it.get("choices", 5)
        col = [scored[s][i] for s in ids]
        p = sum(col) / n
        w = n - sum(col)
        guess = w / ((q - 1) * n)                         # 추측으로 맞혔을 것으로 보는 비율
        disc = _corr(col, tot)                            # 문항-총점 상관 (점이연 상관)
        expected = (1 - p) / (q - 1)                      # 오답지 매력도 기대치
        # 틀린 학생이 너무 적으면(답지 수 × 2 미만) 아무도 안 고른 답지가 우연일 수 있어 '기능 상실'로 판정하지 않는다
        enough_wrong = w >= (q - 1) * 2
        options = []
        for c in range(1, q + 1):
            rate = sum(answers[s][i] == c for s in ids) / n
            kind = ("정답" if c == it["answer"] else
                    "기능 상실 (아무도 안 고름)" if rate == 0 and enough_wrong else
                    "선택 없음 (틀린 학생이 적어 판단 보류)" if rate == 0 else
                    "매력적인 오답지" if rate > expected else "보통 오답지")
            options.append({"choice": c, "rate": round(rate, 2), "kind": kind})
        flags = []
        if disc < 0:
            flags.append("정답·문항 오류 확인 필요 (변별도 음수)")
        elif disc < 0.2:
            flags.append("변별력 낮음 → 문항 검토")
        if any(o["kind"].startswith("기능 상실") for o in options):
            flags.append("기능 상실 답지 → 답지 수정")
        if p < 0.4 and any(o["kind"] == "매력적인 오답지" for o in options):
            flags.append("오개념 의심 → 매력적 오답 중심 재지도")
        out_items.append({
            **{kk: it[kk] for kk in ("no", "standard", "title") if kk in it},
            "difficulty": round(p, 2), "difficulty_label": difficulty_label(p, scale),
            "discrimination": round(disc, 2), "discrimination_label": discrimination_label(disc),
            "guessing": round(guess, 2), "corrected_difficulty": round(max(p - guess, 0), 2),
            "options": options, "attractive_wrong": [o["choice"] for o in options if o["kind"] == "매력적인 오답지"],
            "dead_options": [o["choice"] for o in options if o["kind"].startswith("기능 상실")],
            "flags": flags,
        })
    # 신뢰도: KR-20 (이분 문항의 Cronbach α)
    var_raw = pstdev([sum(scored[s]) for s in ids]) ** 2
    pq = sum((it["difficulty"]) * (1 - it["difficulty"]) for it in out_items)
    kr20 = (k / (k - 1)) * (1 - pq / var_raw) if var_raw > 0 and k > 1 else 0.0
    sd = pstdev(tot)
    sem = sd * sqrt(max(1 - kr20, 0))
    return {"n": n, "items": out_items, "totals": totals, "mean": round(mean(tot), 1), "sd": round(sd, 1),
            "reliability": round(kr20, 2), "sem": round(sem, 1),
            "reliability_label": ("높음" if kr20 >= 0.8 else "보통" if kr20 >= 0.6 else "낮음"),
            "scale": scale}


def standing(score: float, all_scores: list[float]) -> dict:
    """반 안에서의 위치: 표준점수 T(평균 50, 표준편차 10)와 백분위."""
    m, sd = mean(all_scores), pstdev(all_scores)
    z = (score - m) / sd if sd else 0.0
    rank = sum(x < score for x in all_scores) + 0.5 * sum(x == score for x in all_scores)
    return {"z": round(z, 2), "t": round(50 + 10 * z, 1), "percentile": round(rank / len(all_scores) * 100)}
