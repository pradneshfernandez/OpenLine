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


# The demo survey in every call language. Keys: consent, group, age, age_msg, hh, hh_msg, school,
# nchild, nchild_msg, water, problem, then choice labels. English and Hindi were written for the
# product; the other eight are first drafts for a native speaker to check.
DEMO_TEXT = {
    "en": ["This is a demo of OpenLine, an AI that runs phone surveys. It takes about two minutes. "
           "The call is recorded for playback, so please don't share real personal details. Shall we begin?",
           "Survey", "How old are you?", "Please tell me an age between 18 and 100.",
           "How many people live in your household, including you?", "Please tell me a number between 1 and 30.",
           "Do any children in your household go to school?", "How many of them go to school?",
           "That should be at least 1 and fewer than the people in your household.",
           "Where does your household mostly get its drinking water from?", "What is the biggest problem in your area?",
           "Yes", "No", "Don't know", "Refused", "A tap at home", "A hand pump or borewell", "A water tanker", "Somewhere else"],
    "hi": ["यह OpenLine का डेमो है, एक AI जो फ़ोन पर सर्वे करता है। इसमें लगभग दो मिनट लगेंगे। कॉल रिकॉर्ड "
           "की जा रही है, इसलिए कृपया अपनी असली निजी जानकारी न दें। क्या हम शुरू करें?",
           "सर्वे", "आपकी उम्र कितनी है?", "कृपया 18 से 100 के बीच की उम्र बताइए।",
           "आपके घर में आपको मिलाकर कितने लोग रहते हैं?", "कृपया 1 से 30 के बीच की संख्या बताइए।",
           "क्या आपके घर का कोई बच्चा स्कूल जाता है?", "उनमें से कितने बच्चे स्कूल जाते हैं?",
           "यह संख्या कम से कम 1 और घर के लोगों से कम होनी चाहिए।",
           "आपके घर में पीने का पानी ज़्यादातर कहाँ से आता है?", "आपके इलाके की सबसे बड़ी समस्या क्या है?",
           "हाँ", "नहीं", "पता नहीं", "जवाब नहीं देना चाहते", "घर में नल", "हैंडपंप या बोरवेल", "पानी का टैंकर", "कहीं और से"],
    "bn": ["এটি OpenLine-এর একটি ডেমো, একটি AI যা ফোনে সমীক্ষা করে। প্রায় দুই মিনিট লাগবে। কলটি রেকর্ড করা "
           "হচ্ছে, তাই আসল ব্যক্তিগত তথ্য দেবেন না। আমরা কি শুরু করব?",
           "সমীক্ষা", "আপনার বয়স কত?", "অনুগ্রহ করে 18 থেকে 100-এর মধ্যে বয়স বলুন।",
           "আপনাকে নিয়ে আপনার বাড়িতে কতজন থাকেন?", "অনুগ্রহ করে 1 থেকে 30-এর মধ্যে একটি সংখ্যা বলুন।",
           "আপনার বাড়ির কোনো শিশু কি স্কুলে যায়?", "তাদের মধ্যে কতজন স্কুলে যায়?",
           "সংখ্যাটি অন্তত 1 এবং বাড়ির লোকসংখ্যার চেয়ে কম হতে হবে।",
           "আপনার বাড়িতে খাবার জল বেশিরভাগ কোথা থেকে আসে?", "আপনার এলাকার সবচেয়ে বড় সমস্যা কী?",
           "হ্যাঁ", "না", "জানি না", "উত্তর দিতে চাই না", "বাড়িতে জলের কল", "টিউবওয়েল বা বোরওয়েল", "জলের ট্যাঙ্কার", "অন্য কোথাও থেকে"],
    "gu": ["આ OpenLine નો ડેમો છે, એક AI જે ફોન પર સર્વે કરે છે. તેમાં લગભગ બે મિનિટ લાગશે. કૉલ રેકોર્ડ થઈ "
           "રહ્યો છે, તેથી કૃપા કરીને સાચી અંગત માહિતી ન આપશો. શું આપણે શરૂ કરીએ?",
           "સર્વે", "તમારી ઉંમર કેટલી છે?", "કૃપા કરીને 18 થી 100 વચ્ચેની ઉંમર કહો.",
           "તમારા સહિત તમારા ઘરમાં કેટલા લોકો રહે છે?", "કૃપા કરીને 1 થી 30 વચ્ચેની સંખ્યા કહો.",
           "શું તમારા ઘરનું કોઈ બાળક શાળાએ જાય છે?", "તેમાંથી કેટલા બાળકો શાળાએ જાય છે?",
           "આ સંખ્યા ઓછામાં ઓછી 1 અને ઘરના લોકો કરતાં ઓછી હોવી જોઈએ.",
           "તમારા ઘરમાં પીવાનું પાણી મોટે ભાગે ક્યાંથી આવે છે?", "તમારા વિસ્તારની સૌથી મોટી સમસ્યા શું છે?",
           "હા", "ના", "ખબર નથી", "જવાબ આપવા નથી માંગતા", "ઘરમાં નળ", "હેન્ડપંપ કે બોરવેલ", "પાણીનું ટેન્કર", "બીજે ક્યાંકથી"],
    "kn": ["ಇದು OpenLine ನ ಡೆಮೊ, ಫೋನ್ ಮೂಲಕ ಸಮೀಕ್ಷೆ ನಡೆಸುವ ಒಂದು AI. ಸುಮಾರು ಎರಡು ನಿಮಿಷ ಬೇಕಾಗುತ್ತದೆ. ಕರೆಯನ್ನು "
           "ರೆಕಾರ್ಡ್ ಮಾಡಲಾಗುತ್ತಿದೆ, ದಯವಿಟ್ಟು ನಿಜವಾದ ವೈಯಕ್ತಿಕ ಮಾಹಿತಿ ನೀಡಬೇಡಿ. ನಾವು ಶುರು ಮಾಡೋಣವೇ?",
           "ಸಮೀಕ್ಷೆ", "ನಿಮ್ಮ ವಯಸ್ಸು ಎಷ್ಟು?", "ದಯವಿಟ್ಟು 18 ರಿಂದ 100 ರ ನಡುವಿನ ವಯಸ್ಸು ಹೇಳಿ.",
           "ನಿಮ್ಮನ್ನೂ ಸೇರಿ ನಿಮ್ಮ ಮನೆಯಲ್ಲಿ ಎಷ್ಟು ಜನ ವಾಸಿಸುತ್ತಾರೆ?", "ದಯವಿಟ್ಟು 1 ರಿಂದ 30 ರ ನಡುವಿನ ಸಂಖ್ಯೆ ಹೇಳಿ.",
           "ನಿಮ್ಮ ಮನೆಯ ಯಾವುದಾದರೂ ಮಕ್ಕಳು ಶಾಲೆಗೆ ಹೋಗುತ್ತಾರೆಯೇ?", "ಅವರಲ್ಲಿ ಎಷ್ಟು ಮಕ್ಕಳು ಶಾಲೆಗೆ ಹೋಗುತ್ತಾರೆ?",
           "ಈ ಸಂಖ್ಯೆ ಕನಿಷ್ಠ 1 ಮತ್ತು ಮನೆಯ ಜನರಿಗಿಂತ ಕಡಿಮೆ ಇರಬೇಕು.",
           "ನಿಮ್ಮ ಮನೆಗೆ ಕುಡಿಯುವ ನೀರು ಹೆಚ್ಚಾಗಿ ಎಲ್ಲಿಂದ ಬರುತ್ತದೆ?", "ನಿಮ್ಮ ಪ್ರದೇಶದ ಅತಿ ದೊಡ್ಡ ಸಮಸ್ಯೆ ಏನು?",
           "ಹೌದು", "ಇಲ್ಲ", "ಗೊತ್ತಿಲ್ಲ", "ಉತ್ತರಿಸಲು ಇಷ್ಟವಿಲ್ಲ", "ಮನೆಯಲ್ಲಿ ನಲ್ಲಿ", "ಕೈಪಂಪು ಅಥವಾ ಬೋರ್‌ವೆಲ್", "ನೀರಿನ ಟ್ಯಾಂಕರ್", "ಬೇರೆ ಕಡೆಯಿಂದ"],
    "ml": ["ഇത് OpenLine-ന്റെ ഒരു ഡെമോ ആണ്, ഫോണിലൂടെ സർവേ നടത്തുന്ന ഒരു AI. ഏകദേശം രണ്ട് മിനിറ്റ് എടുക്കും. കോൾ "
           "റെക്കോർഡ് ചെയ്യുന്നുണ്ട്, അതിനാൽ യഥാർത്ഥ സ്വകാര്യ വിവരങ്ങൾ പറയരുത്. നമുക്ക് തുടങ്ങാമോ?",
           "സർവേ", "നിങ്ങളുടെ പ്രായം എത്രയാണ്?", "ദയവായി 18 നും 100 നും ഇടയിലുള്ള പ്രായം പറയൂ.",
           "നിങ്ങൾ ഉൾപ്പെടെ നിങ്ങളുടെ വീട്ടിൽ എത്ര പേർ താമസിക്കുന്നു?", "ദയവായി 1 നും 30 നും ഇടയിലുള്ള ഒരു സംഖ്യ പറയൂ.",
           "നിങ്ങളുടെ വീട്ടിലെ ഏതെങ്കിലും കുട്ടികൾ സ്കൂളിൽ പോകുന്നുണ്ടോ?", "അവരിൽ എത്ര കുട്ടികൾ സ്കൂളിൽ പോകുന്നു?",
           "ഈ സംഖ്യ കുറഞ്ഞത് 1 ഉം വീട്ടിലെ ആളുകളേക്കാൾ കുറവും ആയിരിക്കണം.",
           "നിങ്ങളുടെ വീട്ടിൽ കുടിവെള്ളം കൂടുതലും എവിടെ നിന്നാണ് ലഭിക്കുന്നത്?", "നിങ്ങളുടെ പ്രദേശത്തെ ഏറ്റവും വലിയ പ്രശ്നം എന്താണ്?",
           "അതെ", "ഇല്ല", "അറിയില്ല", "മറുപടി പറയാൻ താൽപ്പര്യമില്ല", "വീട്ടിൽ ടാപ്പ്", "കൈപ്പമ്പ് അല്ലെങ്കിൽ കുഴൽക്കിണർ", "വാട്ടർ ടാങ്കർ", "മറ്റെവിടെ നിന്നെങ്കിലും"],
    "mr": ["हा OpenLine चा डेमो आहे, फोनवर सर्वेक्षण करणारे एक AI. याला सुमारे दोन मिनिटे लागतील. कॉल रेकॉर्ड "
           "होत आहे, म्हणून कृपया खरी वैयक्तिक माहिती देऊ नका. आपण सुरू करूया का?",
           "सर्वेक्षण", "तुमचे वय किती आहे?", "कृपया 18 ते 100 मधील वय सांगा.",
           "तुमच्यासह तुमच्या घरात किती लोक राहतात?", "कृपया 1 ते 30 मधील संख्या सांगा.",
           "तुमच्या घरातील कोणी मूल शाळेत जाते का?", "त्यांपैकी किती मुले शाळेत जातात?",
           "ही संख्या किमान 1 आणि घरातील लोकांपेक्षा कमी असावी.",
           "तुमच्या घरी पिण्याचे पाणी मुख्यतः कुठून येते?", "तुमच्या भागातील सर्वात मोठी समस्या कोणती आहे?",
           "हो", "नाही", "माहीत नाही", "उत्तर द्यायचे नाही", "घरात नळ", "हातपंप किंवा बोअरवेल", "पाण्याचा टँकर", "इतर कुठूनतरी"],
    "pa": ["ਇਹ OpenLine ਦਾ ਡੈਮੋ ਹੈ, ਇੱਕ AI ਜੋ ਫ਼ੋਨ ਉੱਤੇ ਸਰਵੇ ਕਰਦਾ ਹੈ। ਇਸ ਵਿੱਚ ਲਗਭਗ ਦੋ ਮਿੰਟ ਲੱਗਣਗੇ। ਕਾਲ ਰਿਕਾਰਡ "
           "ਹੋ ਰਹੀ ਹੈ, ਇਸ ਲਈ ਕਿਰਪਾ ਕਰਕੇ ਅਸਲੀ ਨਿੱਜੀ ਜਾਣਕਾਰੀ ਨਾ ਦਿਓ। ਕੀ ਅਸੀਂ ਸ਼ੁਰੂ ਕਰੀਏ?",
           "ਸਰਵੇ", "ਤੁਹਾਡੀ ਉਮਰ ਕਿੰਨੀ ਹੈ?", "ਕਿਰਪਾ ਕਰਕੇ 18 ਤੋਂ 100 ਦੇ ਵਿਚਕਾਰ ਉਮਰ ਦੱਸੋ।",
           "ਤੁਹਾਡੇ ਸਮੇਤ ਤੁਹਾਡੇ ਘਰ ਵਿੱਚ ਕਿੰਨੇ ਲੋਕ ਰਹਿੰਦੇ ਹਨ?", "ਕਿਰਪਾ ਕਰਕੇ 1 ਤੋਂ 30 ਦੇ ਵਿਚਕਾਰ ਗਿਣਤੀ ਦੱਸੋ।",
           "ਕੀ ਤੁਹਾਡੇ ਘਰ ਦਾ ਕੋਈ ਬੱਚਾ ਸਕੂਲ ਜਾਂਦਾ ਹੈ?", "ਉਨ੍ਹਾਂ ਵਿੱਚੋਂ ਕਿੰਨੇ ਬੱਚੇ ਸਕੂਲ ਜਾਂਦੇ ਹਨ?",
           "ਇਹ ਗਿਣਤੀ ਘੱਟੋ-ਘੱਟ 1 ਅਤੇ ਘਰ ਦੇ ਲੋਕਾਂ ਤੋਂ ਘੱਟ ਹੋਣੀ ਚਾਹੀਦੀ ਹੈ।",
           "ਤੁਹਾਡੇ ਘਰ ਪੀਣ ਵਾਲਾ ਪਾਣੀ ਜ਼ਿਆਦਾਤਰ ਕਿੱਥੋਂ ਆਉਂਦਾ ਹੈ?", "ਤੁਹਾਡੇ ਇਲਾਕੇ ਦੀ ਸਭ ਤੋਂ ਵੱਡੀ ਸਮੱਸਿਆ ਕੀ ਹੈ?",
           "ਹਾਂ", "ਨਹੀਂ", "ਪਤਾ ਨਹੀਂ", "ਜਵਾਬ ਨਹੀਂ ਦੇਣਾ ਚਾਹੁੰਦੇ", "ਘਰ ਵਿੱਚ ਟੂਟੀ", "ਨਲਕਾ ਜਾਂ ਬੋਰਵੈੱਲ", "ਪਾਣੀ ਦਾ ਟੈਂਕਰ", "ਕਿਤੇ ਹੋਰ ਤੋਂ"],
    "ta": ["இது OpenLine-இன் டெமோ, தொலைபேசியில் கணக்கெடுப்பு நடத்தும் ஒரு AI. சுமார் இரண்டு நிமிடங்கள் ஆகும். "
           "அழைப்பு பதிவு செய்யப்படுகிறது, அதனால் உண்மையான தனிப்பட்ட விவரங்களைச் சொல்ல வேண்டாம். தொடங்கலாமா?",
           "கணக்கெடுப்பு", "உங்கள் வயது என்ன?", "தயவுசெய்து 18 முதல் 100 வரை உள்ள வயதைச் சொல்லுங்கள்.",
           "உங்களையும் சேர்த்து உங்கள் வீட்டில் எத்தனை பேர் வசிக்கிறார்கள்?", "தயவுசெய்து 1 முதல் 30 வரை உள்ள ஒரு எண்ணைச் சொல்லுங்கள்.",
           "உங்கள் வீட்டில் யாராவது குழந்தைகள் பள்ளிக்குச் செல்கிறார்களா?", "அவர்களில் எத்தனை குழந்தைகள் பள்ளிக்குச் செல்கிறார்கள்?",
           "இந்த எண் குறைந்தது 1 ஆகவும், வீட்டில் உள்ளவர்களை விடக் குறைவாகவும் இருக்க வேண்டும்.",
           "உங்கள் வீட்டிற்கு குடிநீர் பெரும்பாலும் எங்கிருந்து கிடைக்கிறது?", "உங்கள் பகுதியின் மிகப்பெரிய பிரச்சனை என்ன?",
           "ஆம்", "இல்லை", "தெரியாது", "பதில் சொல்ல விரும்பவில்லை", "வீட்டில் குழாய்", "கைப்பம்பு அல்லது ஆழ்துளைக் கிணறு", "தண்ணீர் லாரி", "வேறு இடத்திலிருந்து"],
    "te": ["ఇది OpenLine డెమో, ఫోన్‌లో సర్వేలు చేసే ఒక AI. దీనికి సుమారు రెండు నిమిషాలు పడుతుంది. కాల్ రికార్డ్ "
           "అవుతోంది, కాబట్టి దయచేసి నిజమైన వ్యక్తిగత వివరాలు చెప్పకండి. మనం మొదలుపెడదామా?",
           "సర్వే", "మీ వయస్సు ఎంత?", "దయచేసి 18 నుండి 100 మధ్య వయస్సు చెప్పండి.",
           "మీతో కలిపి మీ ఇంట్లో ఎంత మంది ఉంటారు?", "దయచేసి 1 నుండి 30 మధ్య ఒక సంఖ్య చెప్పండి.",
           "మీ ఇంట్లో పిల్లలు ఎవరైనా బడికి వెళ్తారా?", "వారిలో ఎంత మంది పిల్లలు బడికి వెళ్తారు?",
           "ఈ సంఖ్య కనీసం 1, ఇంట్లోని వ్యక్తుల కంటే తక్కువగా ఉండాలి.",
           "మీ ఇంటికి తాగునీరు ఎక్కువగా ఎక్కడి నుండి వస్తుంది?", "మీ ప్రాంతంలో అతి పెద్ద సమస్య ఏమిటి?",
           "అవును", "కాదు", "తెలియదు", "సమాధానం చెప్పదలచుకోలేదు", "ఇంట్లో కుళాయి", "చేతి పంపు లేదా బోరుబావి", "నీటి ట్యాంకర్", "వేరే చోటు నుండి"],
}
DEMO_KEYS = ["consent", "group", "age", "age_msg", "hh", "hh_msg", "school", "nchild", "nchild_msg", "water", "problem",
             "yes", "no", "dk", "refused", "piped", "handpump", "tanker", "other"]


def demo_form() -> None:
    """The public demo survey (/demo): short, in every call language, and built so each OpenLine feature has a place to show."""
    names = {"en": "English", "hi": "Hindi", "bn": "Bengali", "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam",
             "mr": "Marathi", "pa": "Punjabi", "ta": "Tamil", "te": "Telugu"}  # as in app/voice/i18n.py
    cols = [f"{names[c]} ({c})" for c in DEMO_TEXT]
    t = {c: dict(zip(DEMO_KEYS, DEMO_TEXT[c], strict=True)) for c in DEMO_TEXT}
    tr = lambda key: [t[c][key] for c in DEMO_TEXT]  # noqa: E731
    blank = [""] * len(cols)
    hdr = ["type", "name", *[f"label::{c}" for c in cols], "required", "relevant", "constraint",
           *[f"constraint_message::{c}" for c in cols]]

    def row(typ, name, label=None, required="", relevant="", constraint="", msg=None):
        return [typ, name, *(tr(label) if label else blank), required, relevant, constraint, *(tr(msg) if msg else blank)]

    survey = [
        hdr,
        row("start", "start"),
        row("end", "end"),
        row("select_one yesno", "consent", "consent", required="yes"),
        row("begin_group", "main", "group", relevant="${consent} = 'yes'"),
        row("integer", "age", "age", "yes", "", ". >= 18 and . <= 100", "age_msg"),
        row("integer", "hh_size", "hh", "yes", "", ". >= 1 and . <= 30", "hh_msg"),
        row("select_one yesno", "children_school", "school", "yes"),
        row("integer", "num_children", "nchild", "yes", "${children_school} = 'yes'", ". >= 1 and . < ${hh_size}", "nchild_msg"),
        row("select_one water", "water_source", "water", "yes"),
        row("text", "main_problem", "problem", "yes"),
        row("end_group", ""),
    ]
    choices = [["list_name", "name", *[f"label::{c}" for c in cols]]]
    for lst, name, key in [("yesno", "yes", "yes"), ("yesno", "no", "no"), ("yesno", "-98", "dk"), ("yesno", "-99", "refused"),
                           ("water", "piped", "piped"), ("water", "handpump", "handpump"), ("water", "tanker", "tanker"),
                           ("water", "other", "other"), ("water", "-98", "dk"), ("water", "-99", "refused")]:
        choices.append([lst, name, *tr(key)])
    settings = [["form_title", "form_id", "version", "default_language"],
                ["OpenLine demo survey", "openline_demo", "2", cols[0]]]
    write(OUT.parent / "demo" / "openline_demo.xlsx", {"survey": survey, "choices": choices, "settings": settings})


if __name__ == "__main__":
    clean_phone_ready()
    phone_rules_test()
    broken_form()
    kobo_extras_form()
    demo_form()
    print(f"Wrote test forms to {OUT}")
