"""화면(UI)과 에이전트를 잇는 입구. 시나리오 이름과 입력을 받아 에이전트를 실행한다."""

from . import llm, offline_scripts, runner
from .tools import AgentState

SCENARIOS = {
    "lesson": (runner.goal_lesson, offline_scripts.lesson_script),
    "question": (runner.goal_question, offline_scripts.question_script),
    "teacher": (runner.goal_teacher_sentence, offline_scripts.teacher_sentence_script),
    "fading": (runner.goal_fading, offline_scripts.fading_script),
}


def mode_label() -> str:
    return runner.ClaudeBrain.label if llm.online() else runner.ScriptedBrain.label


def run(scenario: str, state: AgentState, **kwargs):
    goal_fn, script_fn = SCENARIOS[scenario]
    if scenario == "lesson":
        goal = goal_fn(kwargs["student_id"], kwargs["passage_text"], kwargs.get("passage_id"))
        script_args = (kwargs["student_id"], kwargs["passage_text"])
    elif scenario in ("question", "teacher"):
        text = kwargs["text"]
        goal = goal_fn(kwargs["student_id"], text)
        script_args = (kwargs["student_id"], text)
    else:
        goal = goal_fn(kwargs["student_id"], kwargs["passage_id"], kwargs["results"])
        script_args = (kwargs["student_id"], kwargs["passage_id"], kwargs["results"])

    brain = runner.ClaudeBrain(goal) if llm.online() else runner.ScriptedBrain(script_fn(*script_args))
    yield {"type": "goal", "text": goal, "mode": brain.label}
    yield from runner.run_agent(brain, state)
