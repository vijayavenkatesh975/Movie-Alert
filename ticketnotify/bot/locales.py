"""Multi-language localization dictionaries for TicketNotify (en, hi, ta, te, kn)."""

from typing import Dict, Any

MESSAGES: Dict[str, Dict[str, str]] = {
    "welcome": {
        "en": "👋 *Welcome to TicketNotify!*",
        "hi": "👋 *TicketNotify में आपका स्वागत है!*",
        "ta": "👋 *TicketNotify-க்கு நல்வரவு!*",
        "te": "👋 *TicketNotify కి స్వాగతం!*",
        "kn": "👋 *TicketNotify ಗೆ ಸುಸ್ವಾಗತ!*",
    },
    "intro": {
        "en": "We monitor cinema ticket counters and alert you the split second bookings open, with direct 1-tap booking links so you can grab the best seats.",
        "hi": "हम सिनेमा टिकट काउंटरों पर नजर रखते हैं और बुकिंग खुलते ही आपको तुरंत अलर्ट करते हैं।",
        "ta": "சினிமா முன்பதிவு தொடங்கிய அடுத்த நொடியே உங்களுக்கு உடனடி அறிவிப்பு அனுப்பி, சிறந்த இருக்கைகளை புக் செய்ய உதவுகிறோம்.",
        "te": "సినిమా టిక్కెట్ బుకింగ్ ప్రారంభమైన వెంటనే మీకు తక్షణ నోటిఫికేషన్ అందిస్తాము.",
        "kn": "ಸಿನಿಮಾ ಟಿಕೆಟ್ ಬುಕಿಂಗ್ ಪ್ರಾರಂಭವಾದ ಕ್ಷಣದಲ್ಲೇ ನಿಮಗೆ ತ್ವರಿತ ಅಧಿಸೂಚನೆ ಕಳುಹಿಸುತ್ತೇವೆ.",
    },
    "select_lang": {
        "en": "🌐 *Step 1: Please select your language:*",
        "hi": "🌐 *चरण 1: कृपया अपनी भाषा चुनें:*",
        "ta": "🌐 *படி 1: உங்கள் மொழியைத் தேர்ந்தெடுக்கவும்:*",
        "te": "🌐 *దశ 1: దయచేసి మీ భాషను ఎంచుకోండి:*",
        "kn": "🌐 *ಹಂತ 1: ದಯವಿಟ್ಟು ನಿಮ್ಮ ಭಾಷೆಯನ್ನು ಆಯ್ಕೆಮಾಡಿ:*",
    },
    "choose_city": {
        "en": "📍 *Step 2: Choose your movie city:*",
        "hi": "📍 *चरण 2: अपना सिनेमा शहर चुनें:*",
        "ta": "📍 *படி 2: உங்கள் திரைப்பட நகரத்தைத் தேர்ந்தெடுக்கவும்:*",
        "te": "📍 *దశ 2: మీ సినిమా నగరాన్ని ఎంచుకోండి:*",
        "kn": "📍 *ಹಂತ 2: ನಿಮ್ಮ ಸಿನಿಮಾ ನಗರವನ್ನು ಆಯ್ಕೆಮಾಡಿ:*",
    },
    "setup_complete": {
        "en": "🎉 *Setup Complete!*",
        "hi": "🎉 *सेटअप पूरा हुआ!*",
        "ta": "🎉 *அமைவு முடிந்தது!*",
        "te": "🎉 *సెటప్ పూర్తయింది!*",
        "kn": "🎉 *ಸೆಟಪ್ ಪೂರ್ಣಗೊಂಡಿದೆ!*",
    },
}


def get_text(key: str, lang: str = "en") -> str:
    """Returns localized string, falling back to English."""
    lang_dict = MESSAGES.get(key, {})
    return lang_dict.get(lang, lang_dict.get("en", key))
