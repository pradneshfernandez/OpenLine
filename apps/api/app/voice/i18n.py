"""Call languages (every language Gnani Prisma and Timbre support) and the fixed phrases the agent
speaks itself (not taken from the form).

English and Hindi phrases were written for the product; the other eight are first drafts and
should be checked by a native speaker before fieldwork.
"""

from __future__ import annotations

from typing import Literal

# code -> (English name, native name, BCP-47 locale used by Gnani)
LANGUAGES: dict[str, tuple[str, str, str]] = {
    "en": ("English", "English", "en-IN"),
    "hi": ("Hindi", "हिन्दी", "hi-IN"),
    "bn": ("Bengali", "বাংলা", "bn-IN"),
    "gu": ("Gujarati", "ગુજરાતી", "gu-IN"),
    "kn": ("Kannada", "ಕನ್ನಡ", "kn-IN"),
    "ml": ("Malayalam", "മലയാളം", "ml-IN"),
    "mr": ("Marathi", "मराठी", "mr-IN"),
    "pa": ("Punjabi", "ਪੰਜਾਬੀ", "pa-IN"),
    "ta": ("Tamil", "தமிழ்", "ta-IN"),
    "te": ("Telugu", "తెలుగు", "te-IN"),
}
CODES = tuple(LANGUAGES)
LangCode = Literal["en", "hi", "bn", "gu", "kn", "ml", "mr", "pa", "ta", "te"]
LANGUAGE_NAMES = {c: v[0] for c, v in LANGUAGES.items()}
NATIVE_NAMES = {c: v[1] for c, v in LANGUAGES.items()}
BCP47 = {c: v[2] for c, v in LANGUAGES.items()}

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
    "bn": {
        "greeting": "নমস্কার! এটি {org}-এর পক্ষ থেকে {study} বিষয়ে একটি স্বয়ংক্রিয় সমীক্ষা কল।",
        "goodbye": "এটাই শেষ প্রশ্ন ছিল। আপনার সময়ের জন্য অনেক ধন্যবাদ। নমস্কার!",
        "refused_goodbye": "কোনো অসুবিধা নেই। আপনার সময়ের জন্য ধন্যবাদ। নমস্কার!",
        "callback_goodbye": "অবশ্যই, আমরা পরে আবার কল করব। ধন্যবাদ, নমস্কার!",
        "next_instance": "এবার {label} নম্বর {n} সম্পর্কে বলুন।",
        "another": "আর কোনো {label} আছে কি, যার কথা বলতে চান?",
        "or": "বা",
        "yes": "হ্যাঁ",
        "no": "না",
        "required": "এগিয়ে যেতে এই প্রশ্নের উত্তর দরকার।",
        "invalid": "এই প্রশ্নের জন্য এই উত্তরটি সম্ভব নয়।",
        "number": "অনুগ্রহ করে একটি সংখ্যা বলুন।",
        "whole_number": "অনুগ্রহ করে একটি পূর্ণ সংখ্যা বলুন।",
        "option": "এই উত্তরটি কোনো বিকল্পের সঙ্গে মিলছে না।",
        "still_there": "দুঃখিত, আপনার কথা শুনতে পাইনি।",
        "resume": "আমরা আগে কথা বলেছিলাম, তাই যেখানে থেমেছিলাম সেখান থেকে শুরু করি।",
        "move_on": "চলুন পরের প্রশ্নে যাই।",
        "no_response_goodbye": "আপনার কথা শুনতে পাচ্ছি না, তাই এখন কলটি শেষ করছি। আমরা পরে আবার চেষ্টা করব। নমস্কার!",
    },
    "gu": {
        "greeting": "નમસ્તે! આ {org} તરફથી {study} વિશે એક સ્વયંસંચાલિત સર્વે કૉલ છે.",
        "goodbye": "આ છેલ્લો પ્રશ્ન હતો. તમારા સમય માટે ખૂબ ખૂબ આભાર. આવજો!",
        "refused_goodbye": "કોઈ વાંધો નહીં. તમારા સમય માટે આભાર. આવજો!",
        "callback_goodbye": "ચોક્કસ, અમે તમને પછી ફરી કૉલ કરીશું. આભાર, આવજો!",
        "next_instance": "હવે {label} નંબર {n} વિશે કહો.",
        "another": "શું બીજું કોઈ {label} છે જેના વિશે તમે કહેવા માંગો છો?",
        "or": "કે",
        "yes": "હા",
        "no": "ના",
        "required": "આગળ વધવા માટે મને આ પ્રશ્નનો જવાબ જોઈએ.",
        "invalid": "આ પ્રશ્ન માટે આ જવાબ શક્ય નથી.",
        "number": "કૃપા કરીને એક સંખ્યા કહો.",
        "whole_number": "કૃપા કરીને એક પૂર્ણ સંખ્યા કહો.",
        "option": "આ જવાબ કોઈ વિકલ્પ સાથે મેળ ખાતો નથી.",
        "still_there": "માફ કરશો, મને તમારો અવાજ સંભળાયો નહીં.",
        "resume": "આપણે પહેલાં વાત કરી હતી, તો જ્યાં અટક્યા હતા ત્યાંથી આગળ વધીએ.",
        "move_on": "ચાલો આગળના પ્રશ્ન પર જઈએ.",
        "no_response_goodbye": "મને તમારો અવાજ સંભળાતો નથી, તેથી હવે કૉલ પૂરો કરું છું. અમે પછી ફરી પ્રયત્ન કરીશું. આવજો!",
    },
    "kn": {
        "greeting": "ನಮಸ್ಕಾರ! ಇದು {org} ಕಡೆಯಿಂದ {study} ಕುರಿತು ಒಂದು ಸ್ವಯಂಚಾಲಿತ ಸಮೀಕ್ಷೆ ಕರೆ.",
        "goodbye": "ಇದು ಕೊನೆಯ ಪ್ರಶ್ನೆ. ನಿಮ್ಮ ಸಮಯಕ್ಕೆ ತುಂಬಾ ಧನ್ಯವಾದಗಳು. ನಮಸ್ಕಾರ!",
        "refused_goodbye": "ಪರವಾಗಿಲ್ಲ. ನಿಮ್ಮ ಸಮಯಕ್ಕೆ ಧನ್ಯವಾದಗಳು. ನಮಸ್ಕಾರ!",
        "callback_goodbye": "ಖಂಡಿತ, ನಾವು ನಿಮಗೆ ನಂತರ ಮತ್ತೆ ಕರೆ ಮಾಡುತ್ತೇವೆ. ಧನ್ಯವಾದ, ನಮಸ್ಕಾರ!",
        "next_instance": "ಈಗ {label} ಸಂಖ್ಯೆ {n} ಬಗ್ಗೆ ಹೇಳಿ.",
        "another": "ನೀವು ಹೇಳಲು ಬಯಸುವ ಇನ್ನೊಂದು {label} ಇದೆಯೇ?",
        "or": "ಅಥವಾ",
        "yes": "ಹೌದು",
        "no": "ಇಲ್ಲ",
        "required": "ಮುಂದುವರಿಯಲು ಈ ಪ್ರಶ್ನೆಗೆ ಉತ್ತರ ಬೇಕು.",
        "invalid": "ಈ ಪ್ರಶ್ನೆಗೆ ಈ ಉತ್ತರ ಸಾಧ್ಯವಿಲ್ಲ.",
        "number": "ದಯವಿಟ್ಟು ಒಂದು ಸಂಖ್ಯೆ ಹೇಳಿ.",
        "whole_number": "ದಯವಿಟ್ಟು ಒಂದು ಪೂರ್ಣ ಸಂಖ್ಯೆ ಹೇಳಿ.",
        "option": "ಈ ಉತ್ತರ ಯಾವುದೇ ಆಯ್ಕೆಗೆ ಹೊಂದುವುದಿಲ್ಲ.",
        "still_there": "ಕ್ಷಮಿಸಿ, ನಿಮ್ಮ ಧ್ವನಿ ಕೇಳಿಸಲಿಲ್ಲ.",
        "resume": "ನಾವು ಮೊದಲು ಮಾತನಾಡಿದ್ದೆವು, ನಿಲ್ಲಿಸಿದ ಕಡೆಯಿಂದ ಮುಂದುವರಿಯೋಣ.",
        "move_on": "ಮುಂದಿನ ಪ್ರಶ್ನೆಗೆ ಹೋಗೋಣ.",
        "no_response_goodbye": "ನಿಮ್ಮ ಧ್ವನಿ ಕೇಳಿಸುತ್ತಿಲ್ಲ, ಆದ್ದರಿಂದ ಈಗ ಕರೆಯನ್ನು ಮುಗಿಸುತ್ತಿದ್ದೇನೆ. ನಾವು ನಂತರ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸುತ್ತೇವೆ. ನಮಸ್ಕಾರ!",
    },
    "ml": {
        "greeting": "നമസ്കാരം! ഇത് {org} നടത്തുന്ന {study} സംബന്ധിച്ച ഒരു ഓട്ടോമേറ്റഡ് സർവേ കോൾ ആണ്.",
        "goodbye": "ഇതായിരുന്നു അവസാന ചോദ്യം. നിങ്ങളുടെ സമയത്തിന് വളരെ നന്ദി. നമസ്കാരം!",
        "refused_goodbye": "കുഴപ്പമില്ല. നിങ്ങളുടെ സമയത്തിന് നന്ദി. നമസ്കാരം!",
        "callback_goodbye": "തീർച്ചയായും, ഞങ്ങൾ പിന്നീട് വീണ്ടും വിളിക്കാം. നന്ദി, നമസ്കാരം!",
        "next_instance": "ഇനി {label} നമ്പർ {n} നെ കുറിച്ച് പറയൂ.",
        "another": "പറയാനുള്ള മറ്റൊരു {label} ഉണ്ടോ?",
        "or": "അല്ലെങ്കിൽ",
        "yes": "അതെ",
        "no": "ഇല്ല",
        "required": "മുന്നോട്ട് പോകാൻ ഈ ചോദ്യത്തിന് ഉത്തരം വേണം.",
        "invalid": "ഈ ചോദ്യത്തിന് ഈ ഉത്തരം സാധ്യമല്ല.",
        "number": "ദയവായി ഒരു സംഖ്യ പറയൂ.",
        "whole_number": "ദയവായി ഒരു പൂർണ്ണ സംഖ്യ പറയൂ.",
        "option": "ഈ ഉത്തരം ഒരു ഓപ്ഷനുമായും ചേരുന്നില്ല.",
        "still_there": "ക്ഷമിക്കണം, നിങ്ങൾ പറഞ്ഞത് കേട്ടില്ല.",
        "resume": "നമ്മൾ മുമ്പ് സംസാരിച്ചിരുന്നു, നിർത്തിയിടത്തു നിന്ന് തുടരാം.",
        "move_on": "അടുത്ത ചോദ്യത്തിലേക്ക് പോകാം.",
        "no_response_goodbye": "നിങ്ങളുടെ ശബ്ദം കേൾക്കുന്നില്ല, അതിനാൽ ഇപ്പോൾ കോൾ അവസാനിപ്പിക്കുന്നു. ഞങ്ങൾ പിന്നീട് വീണ്ടും ശ്രമിക്കാം. നമസ്കാരം!",
    },
    "mr": {
        "greeting": "नमस्कार! हा {org} कडून {study} बद्दलचा एक स्वयंचलित सर्वेक्षण कॉल आहे.",
        "goodbye": "हा शेवटचा प्रश्न होता. तुमच्या वेळेबद्दल खूप खूप धन्यवाद. नमस्कार!",
        "refused_goodbye": "काही हरकत नाही. तुमच्या वेळेबद्दल धन्यवाद. नमस्कार!",
        "callback_goodbye": "नक्की, आम्ही तुम्हाला नंतर पुन्हा कॉल करू. धन्यवाद, नमस्कार!",
        "next_instance": "आता {label} क्रमांक {n} बद्दल सांगा.",
        "another": "तुम्हाला सांगायचे असे आणखी कोणते {label} आहे का?",
        "or": "किंवा",
        "yes": "हो",
        "no": "नाही",
        "required": "पुढे जाण्यासाठी मला या प्रश्नाचे उत्तर हवे आहे.",
        "invalid": "या प्रश्नासाठी हे उत्तर शक्य नाही.",
        "number": "कृपया एक संख्या सांगा.",
        "whole_number": "कृपया एक पूर्ण संख्या सांगा.",
        "option": "हे उत्तर कोणत्याही पर्यायाशी जुळत नाही.",
        "still_there": "माफ करा, तुमचा आवाज आला नाही.",
        "resume": "आपण आधी बोललो होतो, तर जिथे थांबलो होतो तिथून पुढे जाऊया.",
        "move_on": "चला पुढच्या प्रश्नाकडे जाऊया.",
        "no_response_goodbye": "तुमचा आवाज येत नाही, म्हणून आता कॉल संपवत आहे. आम्ही नंतर पुन्हा प्रयत्न करू. नमस्कार!",
    },
    "pa": {
        "greeting": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ! ਇਹ {org} ਵੱਲੋਂ {study} ਬਾਰੇ ਇੱਕ ਆਟੋਮੈਟਿਕ ਸਰਵੇ ਕਾਲ ਹੈ।",
        "goodbye": "ਇਹ ਆਖਰੀ ਸਵਾਲ ਸੀ। ਤੁਹਾਡੇ ਸਮੇਂ ਲਈ ਬਹੁਤ ਬਹੁਤ ਧੰਨਵਾਦ। ਸਤ ਸ੍ਰੀ ਅਕਾਲ!",
        "refused_goodbye": "ਕੋਈ ਗੱਲ ਨਹੀਂ। ਤੁਹਾਡੇ ਸਮੇਂ ਲਈ ਧੰਨਵਾਦ। ਸਤ ਸ੍ਰੀ ਅਕਾਲ!",
        "callback_goodbye": "ਜ਼ਰੂਰ, ਅਸੀਂ ਤੁਹਾਨੂੰ ਬਾਅਦ ਵਿੱਚ ਫਿਰ ਕਾਲ ਕਰਾਂਗੇ। ਧੰਨਵਾਦ, ਸਤ ਸ੍ਰੀ ਅਕਾਲ!",
        "next_instance": "ਹੁਣ {label} ਨੰਬਰ {n} ਬਾਰੇ ਦੱਸੋ।",
        "another": "ਕੀ ਕੋਈ ਹੋਰ {label} ਹੈ ਜਿਸ ਬਾਰੇ ਤੁਸੀਂ ਦੱਸਣਾ ਚਾਹੋਗੇ?",
        "or": "ਜਾਂ",
        "yes": "ਹਾਂ",
        "no": "ਨਹੀਂ",
        "required": "ਅੱਗੇ ਵਧਣ ਲਈ ਮੈਨੂੰ ਇਸ ਸਵਾਲ ਦਾ ਜਵਾਬ ਚਾਹੀਦਾ ਹੈ।",
        "invalid": "ਇਸ ਸਵਾਲ ਲਈ ਇਹ ਜਵਾਬ ਸੰਭਵ ਨਹੀਂ ਹੈ।",
        "number": "ਕਿਰਪਾ ਕਰਕੇ ਇੱਕ ਗਿਣਤੀ ਦੱਸੋ।",
        "whole_number": "ਕਿਰਪਾ ਕਰਕੇ ਇੱਕ ਪੂਰੀ ਗਿਣਤੀ ਦੱਸੋ।",
        "option": "ਇਹ ਜਵਾਬ ਕਿਸੇ ਵੀ ਵਿਕਲਪ ਨਾਲ ਮੇਲ ਨਹੀਂ ਖਾਂਦਾ।",
        "still_there": "ਮਾਫ਼ ਕਰਨਾ, ਤੁਹਾਡੀ ਆਵਾਜ਼ ਨਹੀਂ ਆਈ।",
        "resume": "ਅਸੀਂ ਪਹਿਲਾਂ ਗੱਲ ਕੀਤੀ ਸੀ, ਤਾਂ ਜਿੱਥੇ ਰੁਕੇ ਸੀ ਉੱਥੋਂ ਅੱਗੇ ਚੱਲਦੇ ਹਾਂ।",
        "move_on": "ਚਲੋ ਅਗਲੇ ਸਵਾਲ ਵੱਲ ਚੱਲਦੇ ਹਾਂ।",
        "no_response_goodbye": "ਤੁਹਾਡੀ ਆਵਾਜ਼ ਨਹੀਂ ਆ ਰਹੀ, ਇਸ ਲਈ ਹੁਣ ਕਾਲ ਖਤਮ ਕਰ ਰਹੇ ਹਾਂ। ਅਸੀਂ ਬਾਅਦ ਵਿੱਚ ਫਿਰ ਕੋਸ਼ਿਸ਼ ਕਰਾਂਗੇ। ਸਤ ਸ੍ਰੀ ਅਕਾਲ!",
    },
    "ta": {
        "greeting": "வணக்கம்! இது {org} சார்பில் {study} பற்றிய ஒரு தானியங்கி கணக்கெடுப்பு அழைப்பு.",
        "goodbye": "இதுதான் கடைசி கேள்வி. உங்கள் நேரத்திற்கு மிக்க நன்றி. வணக்கம்!",
        "refused_goodbye": "பரவாயில்லை. உங்கள் நேரத்திற்கு நன்றி. வணக்கம்!",
        "callback_goodbye": "நிச்சயமாக, நாங்கள் பிறகு மீண்டும் அழைக்கிறோம். நன்றி, வணக்கம்!",
        "next_instance": "இப்போது {label} எண் {n} பற்றி சொல்லுங்கள்.",
        "another": "நீங்கள் சொல்ல விரும்பும் வேறு {label} ஏதாவது இருக்கிறதா?",
        "or": "அல்லது",
        "yes": "ஆம்",
        "no": "இல்லை",
        "required": "தொடர இந்தக் கேள்விக்கு பதில் தேவை.",
        "invalid": "இந்தக் கேள்விக்கு இந்த பதில் சாத்தியமில்லை.",
        "number": "தயவுசெய்து ஒரு எண்ணைச் சொல்லுங்கள்.",
        "whole_number": "தயவுசெய்து ஒரு முழு எண்ணைச் சொல்லுங்கள்.",
        "option": "இந்த பதில் எந்த விருப்பத்துடனும் பொருந்தவில்லை.",
        "still_there": "மன்னிக்கவும், நீங்கள் சொன்னது கேட்கவில்லை.",
        "resume": "நாம் முன்பு பேசினோம், நிறுத்திய இடத்திலிருந்து தொடரலாம்.",
        "move_on": "அடுத்த கேள்விக்குச் செல்லலாம்.",
        "no_response_goodbye": "உங்கள் குரல் கேட்கவில்லை, அதனால் இப்போது அழைப்பை முடிக்கிறேன். பிறகு மீண்டும் முயற்சிப்போம். வணக்கம்!",
    },
    "te": {
        "greeting": "నమస్కారం! ఇది {org} తరఫున {study} గురించి ఒక ఆటోమేటెడ్ సర్వే కాల్.",
        "goodbye": "ఇదే చివరి ప్రశ్న. మీ సమయానికి చాలా ధన్యవాదాలు. నమస్కారం!",
        "refused_goodbye": "పర్వాలేదు. మీ సమయానికి ధన్యవాదాలు. నమస్కారం!",
        "callback_goodbye": "తప్పకుండా, మేము మీకు తర్వాత మళ్ళీ కాల్ చేస్తాము. ధన్యవాదాలు, నమస్కారం!",
        "next_instance": "ఇప్పుడు {label} సంఖ్య {n} గురించి చెప్పండి.",
        "another": "మీరు చెప్పాలనుకునే మరో {label} ఉందా?",
        "or": "లేదా",
        "yes": "అవును",
        "no": "కాదు",
        "required": "ముందుకు వెళ్ళడానికి ఈ ప్రశ్నకు సమాధానం కావాలి.",
        "invalid": "ఈ ప్రశ్నకు ఈ సమాధానం సాధ్యం కాదు.",
        "number": "దయచేసి ఒక సంఖ్య చెప్పండి.",
        "whole_number": "దయచేసి ఒక పూర్ణ సంఖ్య చెప్పండి.",
        "option": "ఈ సమాధానం ఏ ఎంపికతోనూ సరిపోలడం లేదు.",
        "still_there": "క్షమించండి, మీరు చెప్పింది వినిపించలేదు.",
        "resume": "మనం ఇంతకు ముందు మాట్లాడాం, ఆగిన చోట నుండి కొనసాగిద్దాం.",
        "move_on": "తర్వాతి ప్రశ్నకు వెళ్దాం.",
        "no_response_goodbye": "మీ గొంతు వినిపించడం లేదు, అందుకే ఇప్పుడు కాల్ ముగిస్తున్నాను. మేము తర్వాత మళ్ళీ ప్రయత్నిస్తాము. నమస్కారం!",
    },
}

# Words that accept or reject a read-back ("5?"), per language (native script and common romanisations).
YES_WORDS: dict[str, set[str]] = {
    "en": {"yes", "yeah", "yep", "yup", "correct", "right", "ok", "okay"},
    "hi": {"haan", "han", "ha", "ji", "sahi", "theek", "हाँ", "हां", "हा", "जी", "सही", "ठीक"},
    "bn": {"hyan", "hya", "thik", "হ্যাঁ", "হ্যা", "হাঁ", "ঠিক", "জি"},
    "gu": {"haa", "barabar", "saachu", "હા", "હાં", "બરાબર", "સાચું", "જી"},
    "kn": {"houdu", "howdu", "sari", "ಹೌದು", "ಸರಿ", "ಹೂಂ"},
    "ml": {"athe", "sheri", "uvvu", "അതെ", "ശരി", "ഉവ്വ്", "ഉം"},
    "mr": {"ho", "hoy", "barobar", "हो", "होय", "बरोबर", "हां"},
    "pa": {"haanji", "theek", "ਹਾਂ", "ਹਾਂਜੀ", "ਜੀ", "ਠੀਕ", "ਸਹੀ"},
    "ta": {"aama", "aamam", "sari", "ஆமா", "ஆமாம்", "ஆம்", "சரி"},
    "te": {"avunu", "sare", "అవును", "సరే", "ఔను"},
}
NO_WORDS: dict[str, set[str]] = {
    "en": {"no", "nope", "not", "wrong"},
    "hi": {"nahi", "nahin", "na", "galat", "नहीं", "नही", "ना", "गलत"},
    "bn": {"na", "noy", "bhul", "না", "নয়", "ভুল"},
    "gu": {"na", "nathi", "khotu", "ના", "નથી", "નહીં", "ખોટું"},
    "kn": {"illa", "beda", "tappu", "ಇಲ್ಲ", "ಬೇಡ", "ತಪ್ಪು"},
    "ml": {"illa", "alla", "thettu", "ഇല്ല", "അല്ല", "തെറ്റ്"},
    "mr": {"nahi", "nako", "chuk", "नाही", "नको", "चूक"},
    "pa": {"nahin", "na", "galat", "ਨਹੀਂ", "ਨਾ", "ਗਲਤ"},
    "ta": {"illa", "illai", "thappu", "இல்லை", "இல்ல", "இல்லே", "தப்பு"},
    "te": {"kaadu", "ledu", "tappu", "కాదు", "లేదు", "తప్పు"},
}


def lang_code(lang: str) -> str:
    """'Hindi (hi)', 'hi-IN', 'hi', 'हिन्दी' -> 'hi'. Unknown languages fall back to English."""
    low = (lang or "").strip().lower()
    for code, (name, native, _) in LANGUAGES.items():
        if (f"({code})" in low or low.split("-")[0] == code or low.startswith(name.lower())
                or (native != name and native in lang)):
            return code
    return "en"


def phrase(lang: str, key: str, **kw) -> str:
    table = PHRASES[lang_code(lang)]
    return table.get(key, PHRASES["en"][key]).format(**kw)


# Respondents mix languages, so a read-back accepts yes/no words from any of them.
ALL_YES_WORDS = set().union(*YES_WORDS.values())
ALL_NO_WORDS = set().union(*NO_WORDS.values())
