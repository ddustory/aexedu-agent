"""오프라인 시연 시나리오.

API 키가 없을 때 ScriptedBrain 이 이 시나리오대로 도구를 고른다.
도구는 실제로 실행되며, 시나리오는 도구 결과(진단 점수, 비계 단계, 검사 통과 여부)를 보고
다음 행동을 바꾼다. 실제 Claude 를 쓰면 이 판단을 Claude 가 스스로 한다.
"""

from . import data
from .config import LANGUAGE_NAMES, SCAFFOLD_LEVELS
from .runner import Step, ToolCall


def _call(name: str, reason: str, **args) -> Step:
    return Step(calls=[ToolCall("", name, {**args, "reason": reason})])


def _say(text: str, step: Step) -> Step:
    step.texts.insert(0, text)
    return step


TEACHER_NOTES = {
    1: "모국어 번역을 먼저 읽게 한 뒤, 쉬운 한국어 문장을 한 줄씩 함께 읽어 주세요. "
       "어휘 카드의 그림을 가리키며 핵심어(증발·응결·강수)를 소리 내어 따라 하게 하면 좋습니다.",
    2: "쉬운 한국어로 먼저 읽게 하고, 막히는 낱말만 어휘 카드의 모국어 뜻을 보게 해 주세요.",
    3: "원문을 그대로 읽되 괄호 풀이를 참고하게 해 주세요. 긴 문장은 쉼표 단위로 나눠 읽기를 권합니다.",
}


def _ensure_level(student_id: str, profile: dict):
    """현재 단계가 없으면 진단 → 단계 결정. (생성기 안에서 yield from 으로 사용)"""
    level = profile["current_scaffold_level"]
    if level is not None:
        return level
    quiz = (yield _say("아직 이 학생의 지원 단계가 정해지지 않았네요. 먼저 한국어 수준을 진단하겠습니다.",
                       _call("run_diagnostic_quiz", "학생의 한국어 수준을 알아야 알맞은 지원 단계를 정할 수 있습니다.",
                             student_id=student_id)))[0]
    decided = (yield _call("decide_scaffold_level",
                           f"진단 정답률 {quiz['score_percent']}%를 기준표에 넣어 시작 단계를 정합니다.",
                           student_id=student_id, score_percent=quiz["score_percent"], mode="diagnosis"))[0]
    return decided["new_level"]


def lesson_script(student_id: str, passage_text: str):
    profile = (yield _call("get_student_profile", "학생의 모국어와 현재 지원 단계를 먼저 확인합니다.",
                           student_id=student_id))[0]
    lang = profile["home_language"]
    level = yield from _ensure_level(student_id, profile)
    policy = SCAFFOLD_LEVELS[level]

    orig = (yield _say(f"{policy['name']} 정책({policy['policy']})에 맞춰 자료를 만들겠습니다.",
                       _call("check_readability", "원문이 이 학생에게 얼마나 어려운지 먼저 측정합니다.",
                             text=passage_text)))[0]

    if level < 3:
        why = "원문 문장이 길고 어려워" if not orig["passed"] else "학생 수준에 맞추기 위해"
        rw = (yield _call("rewrite_easy_korean", f"{why} {level}단계 규칙(짧은 문장, 쉬운 말)으로 바꿉니다.",
                          text=passage_text, level=level))[0]
        korean = rw["rewritten_text"]
        for attempt in range(2):
            chk = (yield _call("check_readability", "바꾼 글이 정말 읽기 쉬워졌는지 스스로 확인합니다.", text=korean))[0]
            if chk["passed"]:
                break
            rw = (yield _say("아직 기준에 못 미쳐서 한 번 더 고쳐 쓰겠습니다.",
                             _call("rewrite_easy_korean", "가독성 기준을 통과하도록 다시 고쳐 씁니다.",
                                   text=korean, level=level)))[0]
            korean = rw["rewritten_text"]
    else:
        rw = (yield _call("rewrite_easy_korean", "3단계 학생이므로 원문을 유지하고 어려운 낱말에만 괄호 풀이를 넣습니다.",
                          text=passage_text, level=3))[0]
        korean = rw["rewritten_text"]

    found = (yield _call("find_difficult_words", "어휘 카드로 미리 가르칠 핵심 낱말을 원문에서 찾습니다.",
                         text=passage_text))[0]["difficult_words"]
    words = found[:policy["vocab_card_count"]]
    cards = (yield _call("make_vocab_cards",
                         f"정책에 따라 중요한 낱말 {len(words)}개를 {LANGUAGE_NAMES[lang]} 어휘 카드로 만듭니다.",
                         words=words, language=lang))[0]["cards"]

    native = ""
    if policy["show_full_translation"]:
        native = (yield _call("translate_text", f"1단계 학생이므로 쉬운 한국어 전체를 {LANGUAGE_NAMES[lang]}로 나란히 제공합니다.",
                              text=korean, language=lang))[0]["translation"]

    yield _call("present_lesson_material", "완성된 학습 자료를 교사와 학생이 볼 수 있게 화면에 보여줍니다.",
                student_id=student_id, level=level, korean_text=korean, native_text=native,
                vocab_cards=cards, teacher_note=TEACHER_NOTES[level])

    yield Step(texts=[
        f"{profile['name']} 학생을 위해 {policy['name']} 학습 자료를 만들었습니다. "
        f"원문(평균 {orig['avg_eojeol_per_sentence']}어절/문장)을 학생 수준에 맞게 바꾸고, "
        f"핵심 낱말 {len(cards)}개를 {LANGUAGE_NAMES[lang]} 어휘 카드로 붙였습니다."
        + (" 쉬운 한국어 전체의 모국어 번역도 함께 넣었습니다." if native else "")
    ])


def question_script(student_id: str, question: str):
    profile = (yield _call("get_student_profile", "질문한 학생의 모국어와 지원 단계를 확인합니다.",
                           student_id=student_id))[0]
    lang = profile["home_language"]
    preset = data.offline_demo()["student_questions"].get(lang)
    if not preset or " ".join(preset["question"].split()) != " ".join(question.split()):
        yield Step(texts=["오프라인 시연 모드에서는 준비된 예시 질문에만 답할 수 있어요. "
                          "새 질문은 API 키를 넣으면 실제 AI가 답합니다."])
        return
    cards = (yield _say(f"학생이 {LANGUAGE_NAMES[lang]}로 \"{preset['question_ko']}\"라고 물었습니다. "
                        f"오늘 배운 낱말과 연결해 답하겠습니다.",
                        _call("make_vocab_cards", "답에 꼭 필요한 오늘의 핵심 낱말을 어휘 카드로 준비합니다.",
                              words=preset["related_words"], language=lang)))[0]["cards"]
    yield _call("present_bilingual", "쉬운 한국어 답과 모국어 답을 나란히 보여줍니다.",
                student_id=student_id, kind="answer", original_text=question,
                korean_text=preset["korean_easy"], native_text=preset["native"], vocab_cards=cards)
    yield Step(texts=[f"학생의 {LANGUAGE_NAMES[lang]} 질문에 쉬운 한국어와 {LANGUAGE_NAMES[lang]}로 함께 답했습니다. "
                      f"관련 낱말 {len(cards)}개를 카드로 붙였으니, 한국어 문장을 함께 소리 내어 읽어 보게 해 주세요."])


def teacher_sentence_script(student_id: str, sentence: str):
    profile = (yield _call("get_student_profile", "학생의 모국어를 확인합니다.", student_id=student_id))[0]
    lang = profile["home_language"]
    tr = (yield _call("translate_text", f"교사 설명을 {LANGUAGE_NAMES[lang]}로 옮겨 나란히 보여주려 합니다.",
                      text=sentence, language=lang))[0]["translation"]
    found = (yield _call("find_difficult_words", "설명 속에 어휘 카드가 필요한 낱말이 있는지 찾습니다.",
                         text=sentence))[0]["difficult_words"]
    cards = []
    if found:
        cards = (yield _call("make_vocab_cards", "찾은 낱말을 어휘 카드로 만듭니다.",
                             words=found, language=lang))[0]["cards"]
    yield _call("present_bilingual", "교사 문장과 모국어 문장을 나란히 보여줍니다.",
                student_id=student_id, kind="teacher", original_text=sentence,
                korean_text=sentence, native_text=tr, vocab_cards=cards)
    yield Step(texts=[f"교사 설명을 한국어/{LANGUAGE_NAMES[lang]}로 나란히 보여 주었습니다."])


def fading_script(student_id: str, passage_id: str, results: list[bool]):
    profile = (yield _call("get_student_profile", "학생의 현재 지원 단계를 확인합니다.", student_id=student_id))[0]
    before = yield from _ensure_level(student_id, profile)
    graded = (yield _call("grade_check_answers", "수업 후 확인 문제 결과를 채점합니다.",
                          passage_id=passage_id, results=results))[0]
    decided = (yield _call("decide_scaffold_level",
                           f"확인 문제 정답률 {graded['score_percent']}%를 기준표에 넣어 지원을 줄일지 늘릴지 정합니다.",
                           student_id=student_id, score_percent=graded["score_percent"], mode="check"))[0]
    new = decided["new_level"]
    if new > before:
        msg = f"잘 이해했어요! 지원을 한 단계 줄여 {new}단계로 올립니다. ({SCAFFOLD_LEVELS[new]['name']})"
        steps = [f"다음 수업 자료는 '{SCAFFOLD_LEVELS[new]['policy']}' 방식으로 제공",
                 "모국어 의존을 줄이고 한국어로 먼저 읽게 하기"]
    elif new < before:
        msg = f"아직 어려워했어요. 지원을 한 단계 늘려 {new}단계로 내립니다. ({SCAFFOLD_LEVELS[new]['name']})"
        steps = [f"다음 수업 자료는 '{SCAFFOLD_LEVELS[new]['policy']}' 방식으로 제공"]
        if graded["missed_questions"]:
            steps.append("틀린 문제의 핵심 낱말을 어휘 카드로 다시 복습: " + " / ".join(graded["missed_questions"]))
    else:
        msg = f"현재 단계({SCAFFOLD_LEVELS[new]['name']})를 유지합니다."
        steps = ["같은 방식으로 지원을 계속하되, 틀린 문제만 다시 짚어 주기"]
    steps.append("[교사 확인] 단계 변경이 학생 실제 모습과 맞는지 확인해 주세요.")
    yield _call("present_support_plan", "조정 결과와 다음 수업 계획을 교사에게 보여줍니다.",
                student_id=student_id, new_level=new, message_to_teacher=msg, next_steps=steps)
    yield Step(texts=[f"확인 문제 {graded['correct']}/{graded['total']}개 정답 → {before}단계 → {new}단계. "
                      + msg])
