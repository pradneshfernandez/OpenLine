"""Unit tests for every phone-compatibility check."""

from collections import Counter
from dataclasses import dataclass, field

import pytest

from app.checks.engine import NOT_READY, READY, READY_WITH_WARNINGS, run_checks, status_for
from app.checks.rules import CHECKS, Context, estimate_minutes
from app.xlsform.parse import parse_form
from app.xlsform.workbook import load_xlsform
from tests.conftest import SAMPLES

EN, HI = "English (en)", "Hindi (hi)"


@dataclass
class Q:
    name: str
    type: str = "text"
    label: str = "What is your name?"
    kind: str = "question"
    labels: dict = None
    hints: dict = field(default_factory=dict)
    choice_list: str | None = None
    required: bool = False
    constraint: str = ""
    appearance: str = ""
    repeat_count: str = ""
    media: dict = field(default_factory=dict)
    group_path: list = field(default_factory=list)
    row: int = 2
    read_aloud: bool = True
    hint_read_aloud: bool = False
    not_used_by_phone: bool = False

    def __post_init__(self):
        if self.labels is None:
            self.labels = {EN: self.label} if self.label else {}


def run(questions, choices=None, languages=(EN,), **thresholds):
    return run_checks(questions, choices or {}, list(languages), EN, thresholds)


def codes(result, code):
    return [i for i in result.issues if i.check_code == code]


@pytest.mark.parametrize("qtype", ["geopoint", "geotrace", "geoshape", "image", "video", "barcode", "file"])
def test_unsupported_type_is_blocker(qtype):
    r = run([Q("q", type=qtype)])
    [issue] = codes(r, "unsupported_type")
    assert issue.severity == "blocker" and r.status == NOT_READY


def test_signature_is_unsupported_and_not_used_by_phone_is_skipped():
    assert codes(run([Q("sig", type="image", appearance="signature")]), "unsupported_type")
    assert not codes(run([Q("gps", type="geopoint", not_used_by_phone=True)]), "unsupported_type")
    assert not codes(run([Q("t", type="text")]), "unsupported_type")


def test_image_only_question_and_options():
    q = Q("pic", label="", media={"image": {EN: "a.png"}})
    assert codes(run([q]), "image_only")[0].severity == "blocker"
    sel = Q("s", type="select_one", choice_list="c")
    choices = {"c": [{"name": "1", "labels": {}, "media": {"image": {EN: "x.png"}}},
                     {"name": "2", "labels": {EN: "Two"}, "media": {}}]}
    [issue] = codes(run([sel], choices), "image_only")
    assert "1" in issue.message
    assert not codes(run([Q("ok", media={"image": {EN: "a.png"}})]), "image_only")


@pytest.mark.parametrize("text", [
    "ENUMERATOR: ask for the name", "Do not read: income bracket", "INTERVIEWER: probe",
    "Read options aloud and pick one", "PROBE FOR ALL SOURCES OF INCOME",
])
def test_enumerator_text(text):
    [issue] = codes(run([Q("q", label=text)]), "enumerator_text")
    assert issue.severity == "warning"


def test_enumerator_text_respects_read_aloud_off():
    assert not codes(run([Q("q", label="ENUMERATOR: note", read_aloud=False)]), "enumerator_text")
    assert not codes(run([Q("q", label="What is your name?")]), "enumerator_text")


@pytest.mark.parametrize("text", ["Show the respondent the card", "Point to the picture",
                                  "Tick all that apply", "Circle the answer", "Look at this list"])
def test_visual_reference(text):
    assert codes(run([Q("q", label=text)]), "visual_reference")[0].severity == "warning"


def test_visual_reference_negative():
    assert not codes(run([Q("q", label="How old are you?")]), "visual_reference")


def test_too_long_uses_threshold_and_hint_switch():
    words = " ".join(["word"] * 41)
    assert codes(run([Q("q", label=words)]), "too_long")
    assert not codes(run([Q("q", label=words)], max_words=50), "too_long")
    short = Q("q", label=" ".join(["w"] * 30), hints={EN: " ".join(["h"] * 15)})
    assert not codes(run([short]), "too_long")
    short.hint_read_aloud = True
    assert codes(run([short]), "too_long")


def test_too_many_options():
    opts = {"c": [{"name": str(i), "labels": {EN: f"O{i}"}} for i in range(7)]}
    assert codes(run([Q("q", type="select_one", choice_list="c")], opts), "too_many_options")
    assert not codes(run([Q("q", type="select_one", choice_list="c")], opts, max_options=7), "too_many_options")


def test_grid():
    g = Q("g", type="begin_group", kind="group", appearance="field-list", row=5)
    child = Q("c", type="select_one", appearance="label", group_path=[{"name": "g", "type": "group", "row": 5}])
    assert codes(run([g, child]), "grid")[0].severity == "warning"
    plain_child = Q("c", group_path=[{"name": "g", "type": "group", "row": 5}])
    assert not codes(run([g, plain_child]), "grid")
    assert codes(run([Q("t", type="begin_group", kind="group", appearance="table-list")]), "grid")


@pytest.mark.parametrize("text,hit", [
    ("How old are you? Where were you born?", True),
    ("Do you own a bicycle and do you ride it?", True),
    ("Is the house rented or is it owned?", True),
    ("Do you like rice and beans?", False),
    ("What is your name?", False),
])
def test_double_question(text, hit):
    assert bool(codes(run([Q("q", label=text)]), "double_question")) is hit


def test_missing_translation():
    q = Q("q", labels={EN: "Name?", HI: ""})
    assert codes(run([q], languages=(EN, HI)), "missing_translation")
    full = Q("q", labels={EN: "Name?", HI: "नाम?"})
    assert not codes(run([full], languages=(EN, HI)), "missing_translation")
    opts = {"c": [{"name": "1", "labels": {EN: "Yes"}}]}
    sel = Q("s", type="select_one", choice_list="c", labels={EN: "A?", HI: "ए?"})
    assert codes(run([sel], opts, languages=(EN, HI)), "missing_translation")


def test_no_dont_know_option():
    yn = {"yn": [{"name": "1", "labels": {EN: "Yes"}}, {"name": "0", "labels": {EN: "No"}}]}
    q = Q("q", type="select_one", choice_list="yn", required=True)
    assert codes(run([q], yn), "no_dont_know")[0].severity == "info"
    with_dk = {"yn": yn["yn"] + [{"name": "-98", "labels": {EN: "Don't know"}}]}
    assert not codes(run([q], with_dk), "no_dont_know")
    labelled = {"yn": yn["yn"] + [{"name": "x", "labels": {EN: "Refused"}}]}
    assert not codes(run([q], labelled), "no_dont_know")
    q.required = False
    assert not codes(run([q], yn), "no_dont_know")


def test_number_no_range():
    assert codes(run([Q("n", type="integer")]), "number_no_range")[0].severity == "info"
    assert codes(run([Q("n", type="decimal")]), "number_no_range")
    assert not codes(run([Q("n", type="integer", constraint=". < 100")]), "number_no_range")


def test_repeat_no_count():
    assert codes(run([Q("r", type="begin_repeat", kind="repeat")]), "repeat_no_count")[0].severity == "info"
    assert not codes(run([Q("r", type="begin_repeat", kind="repeat", repeat_count="${n}")]), "repeat_no_count")


@pytest.mark.parametrize("qtype", ["start", "end", "today", "deviceid", "audit", "calculate", "hidden"])
def test_background_field(qtype):
    [issue] = codes(run([Q("b", type=qtype, kind="background", label="")]), "background_field")
    assert issue.severity == "info"


def test_long_call_and_estimate():
    many = [Q(f"q{i}", label="What is your answer number one") for i in range(240)]
    r = run(many)
    assert codes(r, "long_call")[0].severity == "warning"
    assert r.estimated_minutes > 30
    assert not codes(run(many, max_call_minutes=60), "long_call")
    # 130 words read aloud = 1 minute, plus 8 seconds for the single answer.
    ctx = Context([Q("q", label=" ".join(["w"] * 130))], {}, [EN], EN, run([]).thresholds)
    assert estimate_minutes(ctx) == round((60 + 8) / 60, 1)


def test_status_and_accepted_issues():
    r = run([Q("gps", type="geopoint")])
    assert r.status == NOT_READY
    assert status_for(r.issues, {("gps", "unsupported_type")}) == READY
    assert run([Q("q", label="Look at the card")]).status == READY_WITH_WARNINGS
    assert run([Q("q", label="What is your name?")]).status == READY


def test_disabled_checks():
    assert not codes(run([Q("gps", type="geopoint")], disabled_checks=["unsupported_type"]), "unsupported_type")


def test_phone_rules_test_form_triggers_every_check_once():
    parsed = parse_form(load_xlsform((SAMPLES / "test" / "phone_rules_test.xlsx").read_bytes()))
    qs = [Q(**{k: getattr(q, k) for k in ("name", "type", "kind", "labels", "hints", "choice_list",
                                          "required", "constraint", "appearance", "repeat_count",
                                          "media", "group_path", "row")}, label="")
          for q in parsed.questions]
    r = run_checks(qs, {k: v.choices for k, v in parsed.choice_lists.items()},
                   parsed.languages, parsed.default_language)
    got = Counter((i.check_code, i.severity) for i in r.issues)
    expected = {
        ("unsupported_type", "blocker"), ("image_only", "blocker"),
        ("enumerator_text", "warning"), ("visual_reference", "warning"), ("too_long", "warning"),
        ("too_many_options", "warning"), ("grid", "warning"), ("double_question", "warning"),
        ("missing_translation", "warning"), ("long_call", "warning"),
        ("no_dont_know", "info"), ("number_no_range", "info"), ("repeat_no_count", "info"),
        ("background_field", "info"),
    }
    assert set(got) == expected
    assert all(n == 1 for n in got.values()), got
    assert {c for c, _ in got} == set(CHECKS)


def test_visual_reference_ignores_ration_card():
    assert not codes(run([Q("q", label="Does your household have a ration card?")]), "visual_reference")
    assert codes(run([Q("q", label="Show the card to the respondent")]), "visual_reference")
