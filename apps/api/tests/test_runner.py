"""Form runner tests: the persona cards from the stage 2 doc, played through the runner API."""

import pytest

from app.voice.runner import DK, REFUSED, FormRunner, pick_language
from app.xlsform.evaluate import evaluate, truthy
from app.xlsform.parse import parse_form
from app.xlsform.workbook import load_xlsform
from tests.conftest import SAMPLES

TRIAL = SAMPLES / "trial" / "1_clean_phone_ready.xlsx"


def make_runner(path=TRIAL) -> FormRunner:
    parsed = parse_form(load_xlsform(path.read_bytes()))
    qs = [dict(q.__dict__, read_aloud=True, hint_read_aloud=False, not_used_by_phone=False)
          for q in parsed.questions]
    return FormRunner(qs, {k: v.choices for k, v in parsed.choice_lists.items()},
                      parsed.languages, parsed.default_language)


def play(r: FormRunner, script: dict, lang="en") -> list[str]:
    """Answer each question from the script until done; return the names asked, in order."""
    asked = []
    item = r.start(lang)
    while item is not None:
        asked.append(item.name if not item.index else f"{item.name}{list(item.index)}")
        value = script[asked[-1]] if asked[-1] in script else script[item.name]
        res = r.code(item.name, value) if value in (DK, REFUSED) else r.answer(item.name, value)
        assert res.ok, (item.name, value, res.message)
        item = r.next()
    return asked


CARD_A = {"consent": "yes", "age": 34, "hh_size": 5, "children_school": "yes", "num_children": 2,
          "child_age[0]": 8, "school_type[0]": "government", "child_age[1]": 12,
          "school_type[1]": "government", "ration_card": "yes", "main_problem": "water supply"}


def test_card_a_english_cooperative():
    r = make_runner()
    asked = play(r, CARD_A)
    assert asked == ["consent", "age", "hh_size", "children_school", "num_children", "child_age[0]",
                     "school_type[0]", "child_age[1]", "school_type[1]", "ration_card", "main_problem"]
    out = r.finish()
    assert out["age"] == 34 and out["child_age[1]"] == 8 and out["child_age[2]"] == 12
    assert out["school_type[2]"] == "government" and out["main_problem"] == "water supply"
    assert out["start"] and out["end"]


def test_card_b_hindi_text_and_labels():
    r = make_runner()
    first = r.start("hi")
    assert first.text.startswith("हम घरेलू सेवाओं")
    assert [o["label"] for o in first.options][:2] == ["हाँ", "नहीं"]
    r.answer("consent", "हाँ")  # option label also accepted
    for name, v in [("age", "45"), ("hh_size", 6), ("children_school", "yes"), ("num_children", 1),
                    ("child_age", 10), ("school_type", "private"), ("ration_card", "no"),
                    ("main_problem", "बेरोज़गारी")]:
        item = r.next()
        assert item.name == name
        assert r.answer(name, v).ok
    assert r.next() is None
    assert r.finish()["school_type[1]"] == "private"


def test_card_c_correction_reevaluates_following_questions():
    r = make_runner()
    r.start("hi")
    r.answer("consent", "yes"); r.next()
    r.answer("age", 30); r.next()
    r.answer("hh_size", 4); r.next()
    # "actually 5": go back, change, continue from the right place.
    assert r.back("hh_size").name == "hh_size"
    assert r.answer("hh_size", 5).ok
    assert r.next().name == "children_school"
    r.answer("children_school", "no")
    item = r.next()
    assert item.name == "ration_card"  # children questions skipped
    r.code("ration_card", DK)  # "pata nahi"
    r.next(); r.answer("main_problem", "bijli ka bill")
    assert r.next() is None
    out = r.finish()
    assert out["hh_size"] == 5 and out["ration_card"] == "dk" and "num_children" not in out


def test_correction_that_drops_answers():
    r = make_runner()
    play(r, CARD_A)
    r.back("children_school")
    r.answer("children_school", "no")
    assert r.next() is None  # ration_card / main_problem already answered
    out = r.finish()
    assert "num_children" not in out and "child_age[1]" not in out


def test_card_d_out_of_range_and_refusal():
    r = make_runner()
    r.start("en")
    r.answer("consent", "yes")
    assert r.next().name == "age"
    bad = r.answer("age", 200)
    assert not bad.ok and bad.message == "Please tell me an age between 18 and 100."
    assert r.current().name == "age"
    assert r.answer("age", "forty two years") .ok is False  # no digits: re-ask
    assert r.answer("age", 42).ok
    r.next(); r.answer("hh_size", 3)
    r.next(); r.answer("children_school", "no")
    assert r.next().name == "ration_card"
    r.code("ration_card", REFUSED)
    assert r.next().name == "main_problem"


def test_card_e_declines():
    r = make_runner()
    r.start("hi")
    r.answer("consent", "no")
    assert r.next() is None
    assert set(r.finish()) == {"start", "end", "consent"}


def test_constraint_with_reference():
    r = make_runner()
    r.start("en")
    for name, v in [("consent", "yes"), ("age", 40), ("hh_size", 3), ("children_school", "yes")]:
        r.answer(name, v); r.next()
    res = r.answer("num_children", 3)
    assert not res.ok and "household size" in res.message
    assert r.answer("num_children", 2).ok


def test_required_and_bad_option():
    r = make_runner()
    r.start("en")
    assert not r.answer("consent", "").ok
    assert not r.answer("consent", "maybe").ok


def test_repeat_without_count_asks_another():
    qs = [
        {"name": "member", "type": "begin_repeat", "kind": "repeat", "labels": {"default": "member"},
         "group_path": [], "repeat_count": ""},
        {"name": "m_name", "type": "text", "kind": "question", "labels": {"default": "Name?"},
         "group_path": [{"name": "member", "type": "repeat", "row": 2}], "required": True},
    ]
    r = FormRunner(qs, {}, ["default"], "default")
    assert r.start("en").name == "m_name"
    r.answer("m_name", "Asha")
    another = r.next()
    assert another.name == "__another__" and "member" in another.text
    r.answer("__another__", "yes")
    assert r.next().index == (1,)
    r.answer("m_name", "Ravi")
    r.next()
    r.answer("__another__", "no")
    assert r.next() is None
    assert r.finish() == {"m_name[1]": "Asha", "m_name[2]": "Ravi"}


def test_pick_language():
    langs = ["English (en)", "Hindi (hi)"]
    assert pick_language(langs, "English (en)", "hi") == "Hindi (hi)"
    assert pick_language(langs, "English (en)", "hi-IN") == "Hindi (hi)"
    assert pick_language(langs, "English (en)", "ta") == "English (en)"
    assert pick_language(["english"], "english", "en") == "english"


@pytest.mark.parametrize("expr,values,expected", [
    ("${a} = 'yes'", {"a": "yes"}, True),
    ("${a} > 5 and ${b} = 1", {"a": 6, "b": 1}, True),
    ("${a} > 5 or ${b} = 1", {"a": 2, "b": 2}, False),
    ("selected(${c}, 'x')", {"c": "x y"}, True),
    ("not(selected(${c}, 'z'))", {"c": "x y"}, True),
    ("${a} != ''", {"a": ""}, False),
    ("${a} + 2 = 5", {"a": 3}, True),
    ("count-selected(${c}) >= 2", {"c": "x y"}, True),
])
def test_evaluate(expr, values, expected):
    assert truthy(evaluate(expr, values.get)) is expected


def test_all_stage1_test_forms_walk():
    """Every stored test form can be walked to the end with placeholder answers."""
    for path in [TRIAL, SAMPLES / "test" / "kobo_extras_form.xlsx", SAMPLES / "odk_socio_economic_survey.xlsx"]:
        r = make_runner(path)
        item = r.start("en")
        steps = 0
        while item is not None and steps < 500:
            steps += 1
            if item.is_note:
                item = r.next()
                continue
            v = "no" if item.name == "__another__" else item.options[0]["name"] if item.options else ("1" if item.type in ("integer", "decimal") else "x")
            if not r.answer(item.name, v).ok:
                r.code(item.name, DK)
            item = r.next()
        assert item is None, path
