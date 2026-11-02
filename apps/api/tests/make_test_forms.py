"""Generate the test XLSForms stored in sample_forms/test/.

    uv run python tests/make_test_forms.py

phone_rules_test.xlsx  breaks every phone-compatibility rule exactly once.
broken_form.xlsx       fails pyxform (reference to a question that does not exist).
kobo_extras_form.xlsx  a valid form carrying KoboToolbox-only columns.
"""

from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).resolve().parent.parent / "sample_forms" / "test"
EN, HI = "English (en)", "Hindi (hi)"


def write(path: Path, sheets: dict[str, list[list]]) -> None:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def phone_rules_test() -> None:
    hdr = ["type", "name", f"label::{EN}", f"label::{HI}", f"hint::{EN}", f"hint::{HI}",
           "required", "constraint", "appearance", "repeat_count", f"media::image::{EN}"]

    def row(t, n, en="", hi="", required="", constraint="", appearance="", image=""):
        return [t, n, en, hi, "", "", required, constraint, appearance, "", image]

    long_en = ("Thinking about the last twelve months, including the time before and after the "
               "harvest season, about how much money did your household usually spend each "
               "month on food, cooking fuel, school fees, transport to the market, medicine "
               "and clothes for everybody living here")
    survey = [
        hdr,
        row("start", "start"),                                                     # background_field
        row("geopoint", "location", "Where are you now?", "आप अभी कहाँ हैं?"),         # unsupported_type
        row("text", "img_q", image="village_map.png"),                             # image_only
        row("text", "enum_q", "ENUMERATOR: ask the respondent for their full name",
            "प्रगणक: उत्तरदाता का पूरा नाम पूछें"),                                       # enumerator_text
        row("text", "visual_q", "Please look at the card and tell me your favourite colour",
            "कृपया कार्ड देखें और अपना पसंदीदा रंग बताएं"),                                # visual_reference
        row("text", "long_q", long_en, "पिछले बारह महीनों में आपका परिवार हर महीने कितना खर्च करता है"),  # too_long
        row("select_one states", "many_q", "Which state do you live in", "आप किस राज्य में रहते हैं"),  # too_many_options
        row("begin_group", "grid_g", "Rate the following", "निम्नलिखित को रेट करें", appearance="field-list"),  # grid
        row("select_one agree", "r_header", "Rating", "रेटिंग", appearance="label"),
        row("select_one agree", "r_food", "Food", "भोजन", appearance="list-nolabel"),
        row("end_group", ""),
        row("text", "double_q", "Do you own a bicycle and do you ride it to work",
            "क्या आपके पास साइकिल है और क्या आप उससे काम पर जाते हैं"),                   # double_question
        row("text", "trans_q", "What is your village called"),                     # missing_translation
        row("select_one yesno", "req_q", "Are you over eighteen years old", "क्या आपकी उम्र अठारह से अधिक है",
            required="yes"),                                                       # no_dont_know
        row("integer", "num_q", "How many people live in your household",
            "आपके घर में कितने लोग रहते हैं"),                                         # number_no_range
        row("begin_repeat", "member", "Household member", "परिवार का सदस्य"),        # repeat_no_count
        row("text", "member_name", "What is the member name", "सदस्य का नाम क्या है"),
        row("end_repeat", ""),
        # 220 short questions push the estimated call length over 30 minutes (long_call).
        row("begin_group", "filler", "More questions", "और प्रश्न"),
    ]
    for i in range(1, 221):
        survey.append(row("text", f"filler_{i:03d}", f"What is your answer number {i}",
                          f"आपका उत्तर संख्या {i} क्या है"))
    survey.append(row("end_group", ""))

    choices = [["list_name", "name", f"label::{EN}", f"label::{HI}"]]
    for i, s in enumerate(["Bihar", "Gujarat", "Karnataka", "Kerala", "Punjab", "Rajasthan", "Odisha"], 1):
        choices.append(["states", str(i), s, s])
    for code, en, hi in [("1", "Agree", "सहमत"), ("2", "Neutral", "तटस्थ"), ("3", "Disagree", "असहमत")]:
        choices.append(["agree", code, en, hi])
    choices += [["yesno", "1", "Yes", "हाँ"], ["yesno", "0", "No", "नहीं"]]
    settings = [["form_title", "form_id", "version", "default_language"],
                ["Phone rules test", "phone_rules_test", "1", EN]]
    write(OUT / "phone_rules_test.xlsx", {"survey": survey, "choices": choices, "settings": settings})


def broken_form() -> None:
    write(OUT / "broken_form.xlsx", {
        "survey": [
            ["type", "name", "label", "relevant"],
            ["integer", "age", "How old are you?", ""],
            ["text", "school", "Which school do you attend?", "${agee} < 18"],
        ],
        "settings": [["form_title", "form_id"], ["Broken form", "broken_form"]],
    })


def kobo_extras_form() -> None:
    write(OUT / "kobo_extras_form.xlsx", {
        "survey": [
            ["type", "name", "label::English (en)", "label::French (fr)", "required", "relevant",
             "constraint", "constraint_message::English (en)", "kobo--locking-profile", "$kuid"],
            ["integer", "age", "How old are you?", "Quel âge avez-vous ?", "yes", "",
             ". >= 0 and . <= 120", "Age must be between 0 and 120", "lock_all", "a1b2c3"],
            ["select_one yesno", "married", "Are you married?", "Êtes-vous marié(e) ?", "", "${age} >= 18",
             "", "", "", "d4e5f6"],
        ],
        "choices": [
            ["list_name", "name", "label::English (en)", "label::French (fr)"],
            ["yesno", "yes", "Yes", "Oui"], ["yesno", "no", "No", "Non"],
            ["yesno", "-98", "Don't know", "Ne sait pas"],
        ],
        "settings": [["form_title", "form_id", "version", "default_language"],
                     ["Kobo extras", "kobo_extras", "1", "English (en)"]],
        "kobo--locking-profiles": [["restriction", "lock_all"], ["choice_add", "locked"]],
    })


def clean_phone_ready() -> None:
    """Stage 2 trial form, written to match the persona cards in the stage 2 build doc."""
    hdr = ["type", "name", f"label::{EN}", f"label::{HI}", "required", "relevant", "constraint",
           f"constraint_message::{EN}", f"constraint_message::{HI}", "repeat_count"]

    def row(t, n, en="", hi="", required="", relevant="", constraint="", msg_en="", msg_hi="", count=""):
        return [t, n, en, hi, required, relevant, constraint, msg_en, msg_hi, count]

    survey = [
        hdr,
        row("start", "start"),
        row("end", "end"),
        row("select_one yesno", "consent",
            "We are doing a short survey about household services. It takes about three minutes, "
            "the call is recorded, and you can stop at any time. Do you agree to take part?",
            "हम घरेलू सेवाओं के बारे में एक छोटा सर्वे कर रहे हैं। इसमें लगभग तीन मिनट लगेंगे, "
            "कॉल रिकॉर्ड की जा रही है, और आप कभी भी रुक सकते हैं। क्या आप भाग लेने के लिए सहमत हैं?",
            required="yes"),
        row("begin_group", "main", "Survey", "सर्वे", relevant="${consent} = 'yes'"),
        row("integer", "age", "How old are you?", "आपकी उम्र कितनी है?", "yes", "",
            ". >= 18 and . <= 100", "Please tell me an age between 18 and 100.",
            "कृपया 18 से 100 के बीच की उम्र बताइए।"),
        row("integer", "hh_size", "How many people live in your household, including you?",
            "आपके घर में आपको मिलाकर कितने लोग रहते हैं?", "yes", "",
            ". >= 1 and . <= 30", "Please tell me a number between 1 and 30.",
            "कृपया 1 से 30 के बीच की संख्या बताइए।"),
        row("select_one yesno", "children_school", "Do any children in your household go to school?",
            "क्या आपके घर का कोई बच्चा स्कूल जाता है?", "yes"),
        row("integer", "num_children", "How many children in your household go to school?",
            "आपके घर के कितने बच्चे स्कूल जाते हैं?", "yes", "${children_school} = 'yes'",
            ". >= 1 and . < ${hh_size}",
            "The number of children must be at least 1 and less than the household size.",
            "बच्चों की संख्या कम से कम 1 और घर के लोगों की संख्या से कम होनी चाहिए।"),
        row("begin_repeat", "child", "child", "बच्चे", relevant="${children_school} = 'yes'",
            count="${num_children}"),
        row("integer", "child_age", "How old is this child?", "इस बच्चे की उम्र कितनी है?", "yes", "",
            ". >= 3 and . <= 25", "Please tell me an age between 3 and 25.",
            "कृपया 3 से 25 के बीच की उम्र बताइए।"),
        row("select_one school", "school_type", "Does this child go to a government school or a private school?",
            "यह बच्चा सरकारी स्कूल जाता है या प्राइवेट स्कूल?", "yes"),
        row("end_repeat", ""),
        row("select_one yesno", "ration_card", "Does your household have a ration card?",
            "क्या आपके घर में राशन कार्ड है?", "yes"),
        row("text", "main_problem", "What is the biggest problem in your area?",
            "आपके इलाके की सबसे बड़ी समस्या क्या है?", "yes"),
        row("end_group", ""),
    ]
    choices = [["list_name", "name", f"label::{EN}", f"label::{HI}"],
               ["yesno", "yes", "Yes", "हाँ"], ["yesno", "no", "No", "नहीं"],
               ["yesno", "-98", "Don't know", "पता नहीं"], ["yesno", "-99", "Refused", "जवाब नहीं देना चाहते"],
               ["school", "government", "Government school", "सरकारी स्कूल"],
               ["school", "private", "Private school", "प्राइवेट स्कूल"],
               ["school", "other", "Other", "अन्य"],
               ["school", "-98", "Don't know", "पता नहीं"], ["school", "-99", "Refused", "जवाब नहीं देना चाहते"]]
    settings = [["form_title", "form_id", "version", "default_language"],
                ["Household services survey", "clean_phone_ready", "1", EN]]
    write(OUT.parent / "trial" / "1_clean_phone_ready.xlsx",
          {"survey": survey, "choices": choices, "settings": settings})


def demo_form() -> None:
    """The public demo survey (/demo): short, and built so each OpenLine feature has a place to show."""
    hdr = ["type", "name", f"label::{EN}", f"label::{HI}", "required", "relevant", "constraint",
           f"constraint_message::{EN}", f"constraint_message::{HI}"]

    def row(t, n, en="", hi="", required="", relevant="", constraint="", msg_en="", msg_hi=""):
        return [t, n, en, hi, required, relevant, constraint, msg_en, msg_hi]

    survey = [
        hdr,
        row("start", "start"),
        row("end", "end"),
        row("select_one yesno", "consent",
            "This is a demo of OpenLine, an AI that runs phone surveys. It takes about two minutes. "
            "The call is recorded for playback, so please don't share real personal details. Shall we begin?",
            "यह OpenLine का डेमो है, एक AI जो फ़ोन पर सर्वे करता है। इसमें लगभग दो मिनट लगेंगे। कॉल रिकॉर्ड "
            "की जा रही है, इसलिए कृपया अपनी असली निजी जानकारी न दें। क्या हम शुरू करें?", required="yes"),
        row("begin_group", "main", "Survey", "सर्वे", relevant="${consent} = 'yes'"),
        row("integer", "age", "How old are you?", "आपकी उम्र कितनी है?", "yes", "",
            ". >= 18 and . <= 100", "Please tell me an age between 18 and 100.",
            "कृपया 18 से 100 के बीच की उम्र बताइए।"),
        row("integer", "hh_size", "How many people live in your household, including you?",
            "आपके घर में आपको मिलाकर कितने लोग रहते हैं?", "yes", "",
            ". >= 1 and . <= 30", "Please tell me a number between 1 and 30.",
            "कृपया 1 से 30 के बीच की संख्या बताइए।"),
        row("select_one yesno", "children_school", "Do any children in your household go to school?",
            "क्या आपके घर का कोई बच्चा स्कूल जाता है?", "yes"),
        row("integer", "num_children", "How many of them go to school?",
            "उनमें से कितने बच्चे स्कूल जाते हैं?", "yes", "${children_school} = 'yes'",
            ". >= 1 and . < ${hh_size}",
            "That should be at least 1 and fewer than the people in your household.",
            "यह संख्या कम से कम 1 और घर के लोगों से कम होनी चाहिए।"),
        row("select_one water", "water_source", "Where does your household mostly get its drinking water from?",
            "आपके घर में पीने का पानी ज़्यादातर कहाँ से आता है?", "yes"),
        row("text", "main_problem", "What is the biggest problem in your area?",
            "आपके इलाके की सबसे बड़ी समस्या क्या है?", "yes"),
        row("end_group", ""),
    ]
    choices = [["list_name", "name", f"label::{EN}", f"label::{HI}"],
               ["yesno", "yes", "Yes", "हाँ"], ["yesno", "no", "No", "नहीं"],
               ["yesno", "-98", "Don't know", "पता नहीं"], ["yesno", "-99", "Refused", "जवाब नहीं देना चाहते"],
               ["water", "piped", "A tap at home", "घर में नल"],
               ["water", "handpump", "A hand pump or borewell", "हैंडपंप या बोरवेल"],
               ["water", "tanker", "A water tanker", "पानी का टैंकर"],
               ["water", "other", "Somewhere else", "कहीं और से"],
               ["water", "-98", "Don't know", "पता नहीं"], ["water", "-99", "Refused", "जवाब नहीं देना चाहते"]]
    settings = [["form_title", "form_id", "version", "default_language"],
                ["OpenLine demo survey", "openline_demo", "1", EN]]
    write(OUT.parent / "demo" / "openline_demo.xlsx", {"survey": survey, "choices": choices, "settings": settings})


if __name__ == "__main__":
    clean_phone_ready()
    phone_rules_test()
    broken_form()
    kobo_extras_form()
    demo_form()
    print(f"Wrote test forms to {OUT}")
