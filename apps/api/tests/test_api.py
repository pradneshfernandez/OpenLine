"""End-to-end tests of the stage 1 definition of done, through the HTTP API."""

import io

import openpyxl
import pytest

from app.xlsform.convert import run_pyxform
from tests.conftest import SAMPLES, upload

REAL_FORMS = [
    "odk_all_question_types.xlsx",
    "odk_socio_economic_survey.xlsx",
    "ifrc_distribution_site_assessment.xls",
    "kobo_tutorial.xls",
    "kobo_childrens_survey_unicode.xls",
]


@pytest.mark.parametrize("name", REAL_FORMS)
def test_real_public_forms_upload_without_errors(client, project_id, name):
    r = upload(client, project_id, SAMPLES / name)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"], body["errors"]
    s = body["version"]["summary"]
    assert body["version"]["version_no"] == 1
    assert s["question_count"] > 0 and s["title"] and s["form_id"]
    assert body["report"]["status"] in ("ready", "ready_with_warnings", "not_ready")


def test_surveycto_form_offers_not_used_by_phone(client, project_id):
    path = SAMPLES / "surveycto_advanced_cati_starter_kit.xlsx"
    first = upload(client, project_id, path).json()
    assert not first["ok"]
    assert {r["type"] for r in first["platform_rows"]} >= {"caseid", "calculate_here", "audio audit"}
    assert all(e["row"] for e in first["errors"][1:])
    retry = client.post(f"/api/forms/{first['form']['id']}/convert", json={"exclude_platform_rows": True})
    body = retry.json()
    assert body["ok"], body["errors"]
    version = client.get(f"/api/versions/{body['version']['id']}").json()
    excluded = {q["name"] for q in version["questions"] if q["not_used_by_phone"]}
    assert "caseid" in excluded
    # The enumerator-only text in this real CATI form is picked up.
    assert any(i["check_code"] == "enumerator_text" for i in version["report"]["issues"])


def test_broken_form_shows_plain_errors_with_sheet_and_row(client, project_id):
    body = upload(client, project_id, SAMPLES / "test" / "broken_form.xlsx").json()
    assert not body["ok"] and body["version"] is None
    [err] = body["errors"]
    assert err["sheet"] == "survey" and err["row"] == 3 and err["question"] == "school"
    assert "${agee}" in err["message"]
    # The original is still stored and downloadable.
    dl = client.get(f"/api/versions/{body['original_version_id']}/download", params={"kind": "original"})
    assert dl.content == (SAMPLES / "test" / "broken_form.xlsx").read_bytes()


def test_rejects_non_excel_files(client, project_id):
    r = client.post(f"/api/projects/{project_id}/forms/upload", files={"file": ("x.csv", b"a,b")})
    assert r.status_code == 415


@pytest.fixture
def kobo_form(client, project_id):
    body = upload(client, project_id, SAMPLES / "test" / "kobo_extras_form.xlsx").json()
    assert body["ok"]
    return body


def test_original_download_is_unchanged(client, kobo_form):
    original = (SAMPLES / "test" / "kobo_extras_form.xlsx").read_bytes()
    v1 = kobo_form["version"]["id"]
    assert client.get(f"/api/versions/{v1}/download?kind=original").content == original
    assert client.get(f"/api/versions/{kobo_form['original_version_id']}/download?kind=original").content == original
    xml = client.get(f"/api/versions/{v1}/download?kind=xform")
    assert xml.status_code == 200 and b"<h:html" in xml.content


def test_edit_creates_version_logs_and_keeps_names(client, kobo_form):
    v1 = client.get(f"/api/versions/{kobo_form['version']['id']}").json()
    changes = [
        {"question_name": "age", "field": "label", "lang": "English (en)", "value": "What is your age in years?"},
        {"question_name": "age", "field": "hint", "lang": "French (fr)", "value": "En années"},
        {"question_name": "married", "field": "required", "value": True},
        {"question_name": "married", "field": "relevant", "value": "${age} >= 16"},
        {"question_name": "married", "field": "read_aloud", "value": False},
        {"target": "choice", "list_name": "yesno", "choice_name": "no", "field": "label",
         "lang": "French (fr)", "value": "Non merci"},
    ]
    r = client.post(f"/api/versions/{v1['id']}/edits", json={"message": "wording", "changes": changes})
    assert r.status_code == 200, r.text
    v2 = client.get(f"/api/versions/{r.json()['version']['id']}").json()
    assert v2["version_no"] == 2 and v2["parent_version"] == v1["id"]
    by_no = client.get(f"/api/forms/{v2['form_id']}/versions/2").json()
    assert by_no["id"] == v2["id"] and by_no["questions"] == v2["questions"]
    assert client.get(f"/api/forms/{v2['form_id']}/versions/99").status_code == 404
    assert [q["name"] for q in v2["questions"]] == [q["name"] for q in v1["questions"]]
    age, married = v2["questions"]
    assert age["labels"]["English (en)"] == "What is your age in years?"
    assert married["required"] and married["relevant_plain"] == "Only if age is 16 or more"
    assert married["read_aloud"] is False
    assert v2["choice_lists"]["yesno"][1]["labels"]["French (fr)"] == "Non merci"

    log = client.get(f"/api/versions/{v2['id']}/edit-log").json()
    assert len(log) == 6 and all(e["user"] == "tester" for e in log)
    assert {e["field"] for e in log} >= {"label [English (en)]", "required", "read_aloud"}

    # The old version is unchanged.
    again = client.get(f"/api/versions/{v1['id']}").json()
    assert again["questions"][0]["labels"]["English (en)"] == "How old are you?"

    # The edited .xlsx keeps every sheet and re-converts cleanly (proxy for Kobo / Central).
    xlsx = client.get(f"/api/versions/{v2['id']}/download?kind=xlsx").content
    wb = openpyxl.load_workbook(io.BytesIO(xlsx))
    assert wb.sheetnames == ["survey", "choices", "settings", "kobo--locking-profiles"]
    assert [c.value for c in wb["survey"][1]][:10] == ["type", "name", "label::English (en)", "label::French (fr)",
                                                         "required", "relevant", "constraint",
                                                         "constraint_message::English (en)",
                                                         "kobo--locking-profile", "$kuid"]
    assert run_pyxform(xlsx).ok
    assert v2["summary"]["xform_version"] != v1["summary"]["xform_version"]

    # Diff between the two versions.
    d = client.get("/api/versions/diff", params={"a": v1["id"], "b": v2["id"]}).json()
    subjects = {(c["subject"], c["field"]) for c in d["changes"]}
    assert ("age", "labels.English (en)") in subjects and ("married", "required") in subjects
    assert ("yesno/no", "option label [French (fr)]") in subjects

    # Editing an older version is refused.
    stale = client.post(f"/api/versions/{v1['id']}/edits", json={"changes": changes[:1]})
    assert stale.status_code == 409


def test_edit_rejected_by_pyxform_is_not_saved(client, kobo_form):
    vid = kobo_form["version"]["id"]
    r = client.post(f"/api/versions/{vid}/edits", json={"changes": [
        {"question_name": "married", "field": "relevant", "value": "${nope} = 1"}]})
    assert r.status_code == 422
    assert r.json()["detail"]["errors"][0]["row"] == 3
    form = client.get(f"/api/forms/{kobo_form['form']['id']}").json()
    assert form["latest_version_id"] == vid


def test_disallowed_edits(client, kobo_form):
    vid = kobo_form["version"]["id"]
    for change in ({"question_name": "age", "field": "name", "value": "age2"},
                   {"question_name": "age", "field": "type", "value": "text"}):
        assert client.post(f"/api/versions/{vid}/edits", json={"changes": [change]}).status_code == 400


def test_phone_issues_link_and_acceptance_is_kept(client, project_id):
    body = upload(client, project_id, SAMPLES / "test" / "phone_rules_test.xlsx").json()
    assert body["ok"]
    report = body["report"]
    assert report["status"] == "not_ready" and report["estimated_minutes"] > 30
    v = client.get(f"/api/versions/{body['version']['id']}").json()
    names = {q["name"] for q in v["questions"]}
    assert all(i["question_name"] in names for i in report["issues"] if i["question_name"])

    gps = next(i for i in report["issues"] if i["check_code"] == "unsupported_type")
    assert client.post(f"/api/issues/{gps['id']}/accept", json={"reason": ""}).status_code == 400
    ok = client.post(f"/api/issues/{gps['id']}/accept", json={"reason": "Asked as village name instead"})
    assert ok.json()["state"] == "accepted"

    # Mark the image-only question not used by phone: the blocker disappears, and the
    # accepted issue keeps its reason in the new version's report.
    r = client.post(f"/api/versions/{v['id']}/edits", json={"changes": [
        {"question_name": "img_q", "field": "not_used_by_phone", "value": True}]}).json()
    new_report = r["report"]
    kept = next(i for i in new_report["issues"] if i["check_code"] == "unsupported_type")
    assert kept["state"] == "accepted" and kept["accepted_reason"] == "Asked as village name instead"
    assert not any(i["check_code"] == "image_only" for i in new_report["issues"])
    assert new_report["status"] == "ready_with_warnings"
    log = client.get(f"/api/forms/{body['form']['id']}/edit-log").json()
    assert any(e["field"] == "phone issue unsupported_type" for e in log)


def test_thresholds_are_adjustable_per_project(client, project_id):
    r = client.put(f"/api/projects/{project_id}/settings", json={"max_options": 10}).json()
    assert r["thresholds"]["max_options"] == 10
    body = upload(client, project_id, SAMPLES / "test" / "phone_rules_test.xlsx").json()
    assert not any(i["check_code"] == "too_many_options" for i in body["report"]["issues"])
    client.put(f"/api/projects/{project_id}/settings", json={"max_options": 6})


def test_forms_list(client, project_id):
    forms = client.get(f"/api/projects/{project_id}/forms").json()
    assert forms and any(f["phone_status"] for f in forms)
