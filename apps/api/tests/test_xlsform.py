import io

import openpyxl
import pytest

from app.xlsform.convert import describe, run_pyxform
from app.xlsform.parse import canonical_type, parse_form, platform_extras
from app.xlsform.plain_logic import explain, explain_relevant
from app.xlsform.text import spoken_text, word_count
from app.xlsform.workbook import (
    CellEdit,
    WorkbookError,
    apply_edits,
    load_xlsform,
    neutralise_rows,
    sniff_file_type,
    xls_to_xlsx,
)
from tests.conftest import SAMPLES

LOOKUP = {"consent": ("select_one", {"yes": "Yes", "no": "No"}),
          "crops": ("select_multiple", {"1": "Maize", "2": "Rice"})}.get


@pytest.mark.parametrize("expr,plain", [
    ("${age} >= 18", "Only if age is 18 or more"),
    ("${age} < 5", "Only if age is less than 5"),
    ("selected(${consent}, 'yes')", 'Only if consent is "Yes"'),
    ("selected(${crops}, '2')", 'Only if crops includes "Rice"'),
    ("not(selected(${crops}, '1'))", 'Only if crops does not include "Maize"'),
    ("${name} != ''", "Only if name is answered"),
    ("${a} = 1 and (${b} = 2 or ${c} = 3)", "Only if a is 1 and (b is 2 or c is 3)"),
    ("count-selected(${crops}) > 1", "Only if the number of options chosen in crops is more than 1"),
])
def test_relevant_in_plain_language(expr, plain):
    assert explain_relevant(expr, LOOKUP) == plain


def test_plain_language_falls_back_to_raw_text():
    assert explain_relevant("weird((${x}") == "Only if: weird((${x}"
    assert explain("") == ""
    assert explain(". >= 0 and . <= 120", self_name="age") == "age is 0 or more and age is 120 or less"


def test_spoken_text_strips_html_markdown_and_refs():
    assert spoken_text("<p><b>Hello</b> ${full_name}</p>") == "Hello full name"
    assert spoken_text("**Bold** text") == "Bold text"
    assert word_count("Don't you know ${hh_size}?") == 5


def test_sniff_and_xls_conversion():
    data = (SAMPLES / "kobo_tutorial.xls").read_bytes()
    assert sniff_file_type(data) == "xls"
    xlsx = xls_to_xlsx(data)
    assert sniff_file_type(xlsx) == "xlsx"
    assert run_pyxform(xlsx).ok
    with pytest.raises(WorkbookError):
        sniff_file_type(b"not a spreadsheet")


def test_languages_and_default_language():
    form = load_xlsform((SAMPLES / "test" / "kobo_extras_form.xlsx").read_bytes())
    parsed = parse_form(form)
    assert parsed.languages == ["English (en)", "French (fr)"]
    assert parsed.default_language == "English (en)"
    age = parsed.questions[0]
    assert age.labels["French (fr)"] == "Quel âge avez-vous ?"
    assert age.required and age.constraint == ". >= 0 and . <= 120"
    assert parsed.questions[1].relevant_plain == "Only if age is 18 or more"


def test_untagged_hints_belong_to_first_label_language():
    """All labels tagged, hints untagged, no settings.default_language: no phantom "default"."""
    parsed = parse_form(load_xlsform((SAMPLES / "odk_socio_economic_survey.xlsx").read_bytes()))
    assert parsed.default_language == "English (en)"
    assert parsed.languages == ["English (en)", "French (fr)"]
    q = next(q for q in parsed.questions if q.name == "healthFacility")
    assert q.hints == {"English (en)": "Select top 3"}


def test_surveycto_aliases_are_understood():
    parsed = parse_form(load_xlsform((SAMPLES / "surveycto_advanced_cati_starter_kit.xlsx").read_bytes()))
    with_relevance = [q for q in parsed.questions if q.relevant]
    assert with_relevance and all(q.relevant_plain for q in with_relevance)
    assert any(q.calculation for q in parsed.questions)


def test_canonical_types():
    assert canonical_type("select_one yesno") == ("select_one", "yesno", True)
    assert canonical_type("select all that apply crops") == ("select_multiple", "crops", True)
    assert canonical_type("begin group")[0] == "begin_group"
    assert canonical_type("gps")[0] == "geopoint"
    assert canonical_type("photo")[0] == "image"
    assert canonical_type("caseid") == ("caseid", None, False)


def test_platform_extras_detected():
    form = load_xlsform((SAMPLES / "surveycto_phone_call_sample.xlsx").read_bytes())
    warnings, rows = platform_extras(form, parse_form(form))
    assert [r["type"] for r in rows] == ["caseid"]
    assert any("phone-call plug-in" in w["message"] for w in warnings)
    form = load_xlsform((SAMPLES / "test" / "kobo_extras_form.xlsx").read_bytes())
    warnings, rows = platform_extras(form, parse_form(form))
    assert not rows and sum(w["platform"] == "KoboToolbox" for w in warnings) == 2


def test_neutralised_surveycto_rows_convert():
    data = (SAMPLES / "surveycto_advanced_cati_starter_kit.xlsx").read_bytes()
    form = load_xlsform(data)
    _, rows = platform_extras(form, parse_form(form))
    assert not run_pyxform(data).ok
    assert run_pyxform(neutralise_rows(data, [r["row"] for r in rows])).ok


def test_pyxform_error_has_sheet_and_row():
    r = run_pyxform((SAMPLES / "test" / "broken_form.xlsx").read_bytes())
    [err] = r.errors
    assert (err.sheet, err.row) == ("survey", 3)
    m = describe("[row : 7] On the 'choices' sheet, the 'name' value is invalid.", "error")
    assert (m.sheet, m.row) == ("choices", 7)


def test_apply_edits_keeps_sheets_columns_and_freezes_formulas():
    data = (SAMPLES / "surveycto_phone_call_sample.xlsx").read_bytes()
    before = openpyxl.load_workbook(io.BytesIO(data))
    edited = apply_edits(data, [CellEdit("survey", 11, "label", "english", "New text")], "20260101000000")
    after = openpyxl.load_workbook(io.BytesIO(edited))
    assert after.sheetnames == before.sheetnames
    for name in before.sheetnames:
        assert [c.value for c in after[name][1]][: before[name].max_column] == [c.value for c in before[name][1]]
    assert after["survey"].cell(11, 3).value == "New text"
    settings = {c.value: after["settings"].cell(2, c.column).value for c in after["settings"][1] if c.value}
    assert settings["version"] == "20260101000000"  # was an Excel formula
    assert not any(c.data_type == "f" for row in after["survey"].iter_rows() for c in row)


def test_apply_edits_adds_missing_translation_column():
    data = (SAMPLES / "test" / "kobo_extras_form.xlsx").read_bytes()
    edited = apply_edits(data, [CellEdit("survey", 2, "hint", "French (fr)", "En années")])
    parsed = parse_form(load_xlsform(edited))
    assert parsed.questions[0].hints == {"French (fr)": "En années"}
    assert run_pyxform(edited).ok
