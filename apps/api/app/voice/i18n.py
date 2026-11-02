"""Fixed phrases the agent speaks itself (not taken from the form), in English and Hindi."""

PHRASES: dict[str, dict[str, str]] = {
    "en": {
        "greeting": "Hello! This is an automated survey call from {org} about {study}.",
        "goodbye": "That was the last question. Thank you very much for your time. Goodbye!",
        "refused_goodbye": "No problem at all. Thank you for your time. Goodbye!",
        "callback_goodbye": "Of course, we will call you back later. Thank you, goodbye!",
        "next_instance": "Now tell me about {label} number {n}.",
        "another": "Is there another {label} to tell me about?",
        "or": "or",
        "yes": "Yes",
        "no": "No",
        "required": "I need an answer to this question to continue.",
        "invalid": "That answer is not possible for this question.",
        "number": "Please tell me a number.",
        "whole_number": "Please tell me a whole number.",
        "option": "That doesn't match any of the options.",
        "still_there": "Sorry, I didn't hear you.",
        "resume": "We spoke earlier, so let's continue where we left off.",
        "move_on": "Let's move on to the next question.",
        "no_response_goodbye": "I can't hear you, so I'll end the call now. We'll try again later. Goodbye!",
    },
    "hi": {
        "greeting": "नमस्ते! यह {org} की ओर से {study} के बारे में एक स्वचालित सर्वे कॉल है।",
        "goodbye": "यह आख़िरी सवाल था। आपके समय के लिए बहुत-बहुत धन्यवाद। नमस्ते!",
        "refused_goodbye": "कोई बात नहीं। आपके समय के लिए धन्यवाद। नमस्ते!",
        "callback_goodbye": "ज़रूर, हम आपको बाद में फिर कॉल करेंगे। धन्यवाद, नमस्ते!",
        "next_instance": "अब {label} नंबर {n} के बारे में बताइए।",
        "another": "क्या कोई और {label} है जिसके बारे में आप बताना चाहेंगे?",
        "or": "या",
        "yes": "हाँ",
        "no": "नहीं",
        "required": "आगे बढ़ने के लिए मुझे इस सवाल का जवाब चाहिए।",
        "invalid": "इस सवाल के लिए यह जवाब संभव नहीं है।",
        "number": "कृपया एक संख्या बताइए।",
        "whole_number": "कृपया एक पूरी संख्या बताइए।",
        "option": "यह जवाब किसी विकल्प से मेल नहीं खाता।",
        "still_there": "माफ़ कीजिए, आपकी आवाज़ नहीं आई।",
        "resume": "हमने पहले बात की थी, तो जहाँ रुके थे वहीं से आगे बढ़ते हैं।",
        "move_on": "चलिए अगले सवाल पर चलते हैं।",
        "no_response_goodbye": "आपकी आवाज़ नहीं आ रही है, इसलिए अभी कॉल समाप्त की जा रही है। हम बाद में फिर कोशिश करेंगे। नमस्ते!",
    },
}

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi"}


def lang_code(lang: str) -> str:
    """'Hindi (hi)', 'hi-IN', 'hi' -> 'hi'. Unknown languages fall back to English."""
    low = lang.lower()
    for code in PHRASES:
        if f"({code})" in low or low.split("-")[0] == code or low.startswith(LANGUAGE_NAMES[code].lower()):
            return code
    return "en"


def phrase(lang: str, key: str, **kw) -> str:
    table = PHRASES[lang_code(lang)]
    return table.get(key, PHRASES["en"][key]).format(**kw)
