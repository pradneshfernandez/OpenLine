"""Turn-taking, interruption and answer-check rules (component deep dive §1, §2, §4.3, §7)."""

import asyncio

from pipecat.flows import ContextStrategy
from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy

from app.voice.flow import number_mismatch
from app.voice.runner import ANOTHER, Item
from app.voice.turns import WAIT_NUMBER, WAIT_OPEN, WAIT_SHORT, TurnPolicy, silence_wait
from tests.test_survey_flow import Bot, trial_version  # noqa: F401  (fixture)


def item(type_, n_opts=0, name="q"):
    return Item(name=name, index=(), type=type_, kind="question", text="?",
                options=[{"name": str(i), "label": str(i)} for i in range(n_opts)])


def test_wait_depends_on_the_question():
    assert silence_wait(item("select_one", 2)) == WAIT_SHORT
    assert silence_wait(item("integer")) == WAIT_NUMBER
    assert silence_wait(item("text")) == WAIT_OPEN
    assert silence_wait(item("select_one", 2, name=ANOTHER)) == WAIT_SHORT
    assert silence_wait(item("integer")) > silence_wait(item("select_one", 2))


def test_policy_updates_smart_turn_and_needs_two_words_to_interrupt():
    p = TurnPolicy(sample_rate=8000)
    p.asking(item("integer"))
    assert p.analyzer.params.stop_secs == WAIT_NUMBER and p.analyzer._stop_ms == WAIT_NUMBER * 1000
    p.asking(item("select_one", 2))
    assert p.analyzer._stop_ms == WAIT_SHORT * 1000
    start = p.strategies().start
    assert len(start) == 1 and isinstance(start[0], MinWordsUserTurnStartStrategy)
    assert start[0]._min_words == 2


def test_consent_is_protected_until_the_agent_stops_speaking():
    p = TurnPolicy(sample_rate=8000)
    mute = p.mute
    run = lambda f: asyncio.run(mute.process_frame(f))  # noqa: E731
    p.asking(item("select_one", 2), protect=True)
    assert run(BotStartedSpeakingFrame()) is True   # respondent muted during consent
    assert run(BotStoppedSpeakingFrame()) is False  # then free to answer
    assert run(BotStartedSpeakingFrame()) is False  # next question can be interrupted


def test_number_check():
    q = item("integer")
    assert number_mismatch(q, 5, "char nahi actually 5") is None      # correction: 5 is there
    assert number_mismatch(q, 5, "4 nahi 5") is None
    assert number_mismatch(q, 34, "34 saal") is None
    assert number_mismatch(q, 43, "34 saal") == 43                    # LLM swapped digits: confirm
    assert number_mismatch(q, 34, "chautees") is None                 # no digits: trust the LLM
    assert number_mismatch(item("select_one", 2), "1", "2") is None   # only for numbers


def test_record_answer_confirms_when_digits_disagree(trial_version):  # noqa: F811
    b = Bot(trial_version, "en")
    b.open()
    b.answer("yes")
    r = b.tool("record_answer", value=43, heard_text="I am 34", confidence=0.9)
    assert r["status"] == "confirm" and r["say"] == "43?"
    assert b.node_name.endswith("age") or "age" in b.node_name  # still on age
    r = b.tool("record_answer", value=34, heard_text="34", confidence=0.95)
    assert r["status"] == "ok"


def test_each_question_resets_context_with_a_summary(trial_version):  # noqa: F811
    b = Bot(trial_version, "en")
    b.open()
    b.answer("yes")
    b.answer(34)
    node = b.node
    assert node["context_strategy"].strategy == ContextStrategy.RESET
    assert "role_message" in node
    assert "Answers so far: consent=yes, age=34." in node["task_messages"][0]["content"]


def test_silence_reasks_then_ends_partial(trial_version):  # noqa: F811
    b = Bot(trial_version, "en")
    b.flow.opened = True
    b.open()
    b.answer("yes")
    for _ in range(2):  # two re-asks, prefixed with "didn't hear you"
        b.enter(b.flow.on_idle())
        assert b.said[-1].startswith("Sorry, I didn't hear you.") and "How old are you?" in b.said[-1]
    b.enter(b.flow.on_idle())  # third silence: polite goodbye, call kept as partial
    assert "I can't hear you" in b.said[-1]
    status, answers, _ = b.interview()
    assert status == "partial" and answers.get("consent") == "yes"


def test_an_answer_resets_the_silence_count(trial_version):  # noqa: F811
    b = Bot(trial_version, "en")
    b.flow.opened = True
    b.open()
    b.answer("yes")
    b.enter(b.flow.on_idle())
    b.enter(b.flow.on_idle())
    b.answer(34)  # next question starts fresh
    b.enter(b.flow.on_idle())
    assert b.said[-1].startswith("Sorry") and b.interview()[0] == "in-progress"


def test_read_back_needs_a_real_yes():
    from app.voice.flow import confirmation_holds
    assert confirmation_holds("haan", 5) and confirmation_holds("हाँ, पाँच", 5) and confirmation_holds("ஆமா", 5)
    assert confirmation_holds("yes 5", 5) and confirmation_holds("5", 5)
    assert not confirmation_holds("No.", 5)                       # live, Nov 3: recorded as confirmed
    assert not confirmation_holds("नहीं, छह", 5) and not confirmation_holds("இல்லை", 5)
    assert not confirmation_holds("பானிக்கி problem. தண்ணி வரவே இல்ல", "yes", "Yes")  # unrelated answer
    assert confirmation_holds("Yes", "1", "Yes")


def test_llm_confirmed_but_respondent_said_no_is_not_saved(trial_version):  # noqa: F811
    bot = Bot(trial_version, "en")
    bot.open()
    bot.answer("yes")                                                  # consent
    bot.answer("34")                                                   # age
    res = bot.answer("5", heard="We are five, me, my wife and 3 kids")
    assert res["status"] == "confirm" and res["say"] == "5?"            # 5 isn't among the digits
    res = bot.answer("5", heard="No.", confirmed=True)
    assert res["status"] == "not_confirmed"                            # the LLM can't override a "no"
    res = bot.answer("5", heard="We are 5", confirmed=True)
    assert res["status"] == "ok"


def test_correct_answer_sees_question_wording_and_type(trial_version):  # noqa: F811
    bot = Bot(trial_version, "en")
    bot.open()
    for v in ("yes", "34", "5", "yes"):
        bot.answer(v)
    fn = next(f for f in bot.node["functions"] if f.name == "correct_answer")
    assert 'num_children' not in fn.description  # not answered yet
    assert 'children_school: "Do any children in your household go to school?" (select_one) = yes' in fn.description
    assert 'hh_size: "How many people live in your household, including you?" (integer) = 5' in fn.description
