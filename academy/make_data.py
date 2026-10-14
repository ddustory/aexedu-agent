"""시연용 가상 학원 데이터 만들기 (중1~3 국어 월말 학력평가 4회, 학년별 30명).

실행: python -m academy.make_data   → data/academy/*.json 을 새로 만든다.
모든 학생·문항·점수는 가상이다. 성취기준은 2022 개정 국어과 교육과정의 실제 중학교 성취기준을 쓴다.
"""

import json
import math
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "academy"
MONTHS = ["2026-07", "2026-08", "2026-09", "2026-10"]

# 2022 개정 국어과 교육과정의 실제 중학교 성취기준 코드 (data/curriculum_standards.json 에서 문장을 가져옴)
# 한 시험 20문항 배치 (영역 비율: 문학 6, 읽기 6, 문법 4, 쓰기 2, 듣기·말하기 2)
LAYOUT = ["9국05-01", "9국05-01", "9국05-02", "9국05-02", "9국05-04", "9국05-04",
          "9국02-02", "9국02-02", "9국02-05", "9국02-05", "9국02-03", "9국02-03",
          "9국04-03", "9국04-04", "9국04-01", "9국04-01",
          "9국03-08", "9국03-08", "9국01-08", "9국01-06"]
# 성취기준별 기본 난이도 (클수록 어려움)
BASE_DIFF = {"9국01-08": 0.2, "9국01-06": -0.9, "9국02-02": -0.4, "9국02-05": 0.1, "9국02-03": 0.6,
             "9국03-08": -0.1, "9국04-03": 0.2, "9국04-04": 0.6, "9국04-01": 1.1,
             "9국05-01": -0.3, "9국05-02": -0.1, "9국05-04": 0.5}
TITLES = {
    "9국01-08": "토론에서 상대 논증의 허점을 지적한 반박 고르기", "9국01-06": "청중을 고려해 발표 자료를 재구성한 방법 고르기",
    "9국02-02": "글의 구조를 고려한 요약으로 알맞은 것 고르기", "9국02-05": "글에 쓰인 설명·논증 방법과 그 타당성 판단하기",
    "9국02-03": "글에 드러나지 않은 글쓴이의 의도 추론하기", "9국03-08": "독자를 고려해 초고를 고쳐 쓴 방법 고르기",
    "9국04-03": "품사의 종류와 특성이 다른 하나 고르기", "9국04-04": "문장의 짜임(홑문장·겹문장) 분석하기",
    "9국04-01": "음운 체계·음운의 변동 이해하기", "9국05-01": "시의 운율·비유·상징과 그 효과 고르기",
    "9국05-02": "소설의 갈등이 진행·해결되는 과정 파악하기", "9국05-04": "보는 이·말하는 이(서술자)의 특성과 효과 파악하기",
}
FIRST = {
    1: [("김하늘", "ko", 0.6, 0.05), ("이준서", "ko", -0.2, 0.15), ("박서윤", "ko", 1.2, 0.0),
        ("최민재", "ko", -0.8, 0.2), ("응우옌 안", "vi", -0.5, 0.25), ("정다은", "ko", 0.2, -0.1)],
    2: [("한지우", "ko", 0.9, 0.05), ("오세훈", "ko", 0.0, -0.15), ("왕하오", "zh", -0.4, 0.2),
        ("송예린", "ko", 0.4, 0.1), ("임도윤", "ko", -1.0, 0.1), ("강유나", "ko", 1.5, 0.0)],
    3: [("윤서진", "ko", 0.7, 0.0), ("장민호", "ko", -0.3, 0.2), ("서하린", "ko", 1.1, -0.05),
        ("백승우", "ko", -0.9, 0.15), ("레티 마이", "vi", 0.1, 0.2), ("노지훈", "ko", 0.3, -0.2)],
}
SURNAMES = list("김이박최정강조윤장임한오서신권황안송류홍")
GIVEN = ["민준", "서연", "도윤", "지우", "하준", "서윤", "시우", "하은", "주원", "지유", "예준", "수아", "유준", "지아",
         "건우", "채원", "현우", "다인", "우진", "소율", "선우", "윤서", "연우", "예린", "준혁", "가은", "승민", "나연"]
PER_GRADE = 30
LANG = {"ko": "한국어", "vi": "베트남어", "zh": "중국어"}


def _std_text():
    cur = json.loads((OUT.parent / "curriculum_standards.json").read_text(encoding="utf-8"))
    return {x["code"].strip("[]"): x for x in cur["standards"]}


def main():
    rnd = random.Random(20261015)
    cur = _std_text()
    standards = [{"id": c, "code": f"[{c}]", "area": cur[c]["area"], "desc": cur[c]["text"]}
                 for c in dict.fromkeys(LAYOUT)]
    students, exams, results = [], [], []
    for grade in (1, 2, 3):
        rows = list(FIRST[grade])
        used = {r[0] for r in rows}
        while len(rows) < PER_GRADE:
            nm = rnd.choice(SURNAMES) + rnd.choice(GIVEN)
            if nm not in used:
                used.add(nm)
                rows.append((nm, "ko", rnd.gauss(0, 0.9), rnd.uniform(-0.15, 0.2)))
        for i, (name, lang, ability, trend) in enumerate(rows):
            weak = rnd.sample(list(dict.fromkeys(LAYOUT)), 2)  # 학생마다 약한 성취기준 2개
            students.append({"id": f"M{grade}{i + 1:02d}", "name": name, "grade": grade, "class": f"중{grade} A반",
                             "parent_language": lang, "parent_language_name": LANG[lang],
                             "_ability": ability, "_trend": trend, "_weak": weak})
        for month in MONTHS:
            items = []
            noisy = rnd.randrange(20)  # 시험마다 1문항은 능력과 상관없이 맞히는(변별력 낮은) 문항
            for n, sid in enumerate(LAYOUT, 1):
                ans = rnd.randint(1, 5)
                wrong = [c for c in range(1, 6) if c != ans]
                rnd.shuffle(wrong)
                weights = {wrong[0]: 0.55, wrong[1]: 0.22, wrong[2]: 0.18,
                           wrong[3]: 0.0 if rnd.random() < 0.15 else 0.08}  # 일부 답지는 아무도 안 고름
                items.append({"no": n, "standard": sid, "title": TITLES[sid], "points": 5, "choices": 5, "answer": ans,
                              "_diff": BASE_DIFF[sid] + rnd.uniform(-0.5, 0.5) + 0.25 * (grade - 2),
                              "_noisy": n - 1 == noisy, "_w": weights})
            exams.append({"id": f"G{grade}-{month}", "grade": grade, "month": month,
                          "title": f"중{grade} {int(month[-2:])}월 국어 학력평가", "items": items})
    for e in exams:
        m = MONTHS.index(e["month"])
        for s in [s for s in students if s["grade"] == e["grade"]]:
            ans = []
            for it in e["items"]:
                theta = s["_ability"] + s["_trend"] * m - (0.9 if it["standard"] in s["_weak"] else 0)
                p = 0.5 if it["_noisy"] else 1 / (1 + math.exp(-(1.7 * (theta - it["_diff"]))))
                if rnd.random() < p:
                    ans.append(it["answer"])
                else:  # 모르면 답지 매력에 따라 고르고, 가끔은 찍어서 맞힌다
                    opts = list(it["_w"].items()) + [(it["answer"], 0.15)]
                    r, acc = rnd.random() * sum(w for _, w in opts), 0
                    for c, w in opts:
                        acc += w
                        if r <= acc:
                            ans.append(c)
                            break
            results.append({"exam_id": e["id"], "student_id": s["id"], "answers": ans})
    for s in students:
        for k in ("_ability", "_trend", "_weak"):
            s.pop(k)
    for e in exams:
        for it in e["items"]:
            for k in ("_diff", "_noisy", "_w"):
                it.pop(k)
    OUT.mkdir(parents=True, exist_ok=True)
    note = ("시연용 가상 데이터입니다. 실제 학생·시험이 아닙니다. 성취기준 코드와 문장은 2022 개정 국어과 교육과정"
            "(교육부 고시 제2022-33호)의 실제 중학교 성취기준이며, 문항은 그 성취기준을 평가하는 가상 문항입니다.")
    (OUT / "students.json").write_text(json.dumps({"_note": note, "students": students}, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "exams.json").write_text(json.dumps({"_note": note, "standards": standards, "exams": exams}, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "results.json").write_text(json.dumps({"_note": note, "results": results}, ensure_ascii=False), encoding="utf-8")
    print(f"학생 {len(students)}명, 시험 {len(exams)}회, 응답 {len(results)}건")


if __name__ == "__main__":
    main()
