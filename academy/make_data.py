"""시연용 가상 학원 데이터 만들기 (중1~3 국어 월말 학력평가 4회).

실행: python -m academy.make_data   → data/academy/*.json 을 새로 만든다.
모든 학생·문항·점수는 가상이다. 성취기준은 '예시'이며, 실제 사용 시 교사가 학원 시험의 성취기준 코드로 바꾼다.
"""

import json
import math
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "academy"
MONTHS = ["2026-07", "2026-08", "2026-09", "2026-10"]

STANDARDS = [
    {"id": "듣말-토론근거", "area": "듣기·말하기", "desc": "토론에서 주장과 근거가 알맞은지 판단하기"},
    {"id": "듣말-발표구성", "area": "듣기·말하기", "desc": "듣는 이를 고려해 발표 내용을 구성하기"},
    {"id": "읽기-요약", "area": "읽기", "desc": "글의 중심 내용을 찾아 요약하기"},
    {"id": "읽기-설명방법", "area": "읽기", "desc": "설명 방법(정의·예시·비교 등)을 파악하기"},
    {"id": "읽기-논증평가", "area": "읽기", "desc": "주장과 근거의 타당성을 평가하며 읽기"},
    {"id": "쓰기-고쳐쓰기", "area": "쓰기", "desc": "통일성을 고려해 글을 고쳐 쓰기"},
    {"id": "문법-품사", "area": "문법", "desc": "낱말을 품사에 따라 분류하기"},
    {"id": "문법-문장성분", "area": "문법", "desc": "문장 성분을 파악하기"},
    {"id": "문법-음운변동", "area": "문법", "desc": "음운의 변동을 이해하기"},
    {"id": "문학-비유상징", "area": "문학", "desc": "비유와 상징 표현의 효과 이해하기"},
    {"id": "문학-갈등구성", "area": "문학", "desc": "소설의 갈등과 구성 단계 파악하기"},
    {"id": "문학-관점", "area": "문학", "desc": "말하는 이·서술자의 관점 파악하기"},
]
# 한 시험 20문항의 성취기준 배치 (영역 비율: 문학 6, 읽기 6, 문법 4, 쓰기 2, 듣기·말하기 2)
LAYOUT = ["문학-비유상징", "문학-비유상징", "문학-갈등구성", "문학-갈등구성", "문학-관점", "문학-관점",
          "읽기-요약", "읽기-요약", "읽기-설명방법", "읽기-설명방법", "읽기-논증평가", "읽기-논증평가",
          "문법-품사", "문법-문장성분", "문법-음운변동", "문법-음운변동",
          "쓰기-고쳐쓰기", "쓰기-고쳐쓰기", "듣말-토론근거", "듣말-발표구성"]
# 성취기준별 기본 난이도 (클수록 어려움)
BASE_DIFF = {"듣말-토론근거": -0.6, "듣말-발표구성": -0.9, "읽기-요약": -0.4, "읽기-설명방법": -0.1,
             "읽기-논증평가": 0.7, "쓰기-고쳐쓰기": 0.1, "문법-품사": 0.2, "문법-문장성분": 0.6,
             "문법-음운변동": 1.2, "문학-비유상징": -0.3, "문학-갈등구성": 0.0, "문학-관점": 0.5}
TITLES = {
    "듣말-토론근거": "토론 대화에서 근거가 부족한 발언 고르기", "듣말-발표구성": "발표 계획에서 빠진 내용 고르기",
    "읽기-요약": "글의 중심 내용으로 알맞은 것 고르기", "읽기-설명방법": "밑줄 친 부분에 쓰인 설명 방법 고르기",
    "읽기-논증평가": "글쓴이 주장의 근거로 알맞지 않은 것 고르기", "쓰기-고쳐쓰기": "통일성을 해치는 문장 찾기",
    "문법-품사": "품사가 다른 하나 고르기", "문법-문장성분": "밑줄 친 말의 문장 성분 고르기",
    "문법-음운변동": "음운 변동이 일어나는 단어 고르기", "문학-비유상징": "시에 쓰인 표현 방법과 효과 고르기",
    "문학-갈등구성": "소설의 갈등 양상으로 알맞은 것 고르기", "문학-관점": "서술자의 시점과 효과 고르기",
}
STUDENTS = {
    1: [("김하늘", "ko", 0.6, 0.05), ("이준서", "ko", -0.2, 0.15), ("박서윤", "ko", 1.2, 0.0),
        ("최민재", "ko", -0.8, 0.2), ("응우옌 안", "vi", -0.5, 0.25), ("정다은", "ko", 0.2, -0.1)],
    2: [("한지우", "ko", 0.9, 0.05), ("오세훈", "ko", 0.0, -0.15), ("왕하오", "zh", -0.4, 0.2),
        ("송예린", "ko", 0.4, 0.1), ("임도윤", "ko", -1.0, 0.1), ("강유나", "ko", 1.5, 0.0)],
    3: [("윤서진", "ko", 0.7, 0.0), ("장민호", "ko", -0.3, 0.2), ("서하린", "ko", 1.1, -0.05),
        ("백승우", "ko", -0.9, 0.15), ("레티 마이", "vi", 0.1, 0.2), ("노지훈", "ko", 0.3, -0.2)],
}
LANG = {"ko": "한국어", "vi": "베트남어", "zh": "중국어"}


def main():
    rnd = random.Random(20261015)
    students, exams, results = [], [], []
    for grade, rows in STUDENTS.items():
        for i, (name, lang, ability, trend) in enumerate(rows):
            weak = rnd.sample([s["id"] for s in STANDARDS], 2)  # 학생마다 약한 성취기준 2개
            students.append({"id": f"M{grade}{i + 1:02d}", "name": name, "grade": grade, "class": f"중{grade} A반",
                             "parent_language": lang, "parent_language_name": LANG[lang],
                             "_ability": ability, "_trend": trend, "_weak": weak})
        for m, month in enumerate(MONTHS):
            items = []
            for n, sid in enumerate(LAYOUT, 1):
                items.append({"no": n, "standard": sid, "title": TITLES[sid], "points": 5,
                              "answer": rnd.randint(1, 5),
                              "_diff": BASE_DIFF[sid] + rnd.uniform(-0.5, 0.5) + 0.25 * (grade - 2)})
            exams.append({"id": f"G{grade}-{month}", "grade": grade, "month": month,
                          "title": f"중{grade} {int(month[-2:])}월 국어 학력평가", "items": items})
    for e in exams:
        m = MONTHS.index(e["month"])
        for s in [s for s in students if s["grade"] == e["grade"]]:
            ans = []
            for it in e["items"]:
                theta = s["_ability"] + s["_trend"] * m - (0.9 if it["standard"] in s["_weak"] else 0)
                p = 1 / (1 + math.exp(-(1.7 * (theta - it["_diff"]) + 0.6)))
                if rnd.random() < p:
                    ans.append(it["answer"])
                else:
                    ans.append(rnd.choice([c for c in range(1, 6) if c != it["answer"]]))
            results.append({"exam_id": e["id"], "student_id": s["id"], "answers": ans})
    for s in students:
        for k in ("_ability", "_trend", "_weak"):
            s.pop(k)
    for e in exams:
        for it in e["items"]:
            it.pop("_diff")
    OUT.mkdir(parents=True, exist_ok=True)
    note = "시연용 가상 데이터입니다. 실제 학생·시험이 아닙니다. 성취기준은 예시이며 교사가 실제 코드로 바꿔 쓸 수 있습니다."
    (OUT / "students.json").write_text(json.dumps({"_note": note, "students": students}, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "exams.json").write_text(json.dumps({"_note": note, "standards": STANDARDS, "exams": exams}, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "results.json").write_text(json.dumps({"_note": note, "results": results}, ensure_ascii=False), encoding="utf-8")
    print(f"학생 {len(students)}명, 시험 {len(exams)}회, 응답 {len(results)}건")


if __name__ == "__main__":
    main()
