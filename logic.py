"""Pure helper logic for the Dadi voice assistant (no audio / GUI / network needed)."""
import re
import json
import datetime as dt

HINDI_NUM = {"एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "पाच": 5,
             "छह": 6, "छः": 6, "छे": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
             "ग्यारह": 11, "बारह": 12}

CONTACT_WORDS = {"बेटे": "बेटा", "बेटा": "बेटा", "बहू": "बहू", "बहु": "बहू",
                 "डॉक्टर": "डॉक्टर", "डाक्टर": "डॉक्टर"}


def extract_json(text):
    """Pull the first JSON object out of a model reply (tolerates ```json fences)."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON found")
    return json.loads(text[start:end + 1])


def _find_hour(t):
    m = re.search(r"(\d{1,2})\s*बजे", t)
    if m:
        hour = int(m.group(1))
    else:
        m = re.search(r"(\S+)\s+बजे", t)
        if not m or m.group(1) not in HINDI_NUM:
            return None
        hour = HINDI_NUM[m.group(1)]
    if 1 <= hour <= 11 and any(w in t for w in ("शाम", "दोपहर")):
        hour += 12
    if any(w in t for w in ("रात", "रात्रि")):
        if hour == 12:
            hour = 0
        elif 6 <= hour <= 11:
            hour += 12
    return hour % 24


def offline_intent(text):
    """Keyword-based fallback when there is no internet / API key."""
    out = {"intent": "chat", "reminder_text": None, "time": None,
           "in_minutes": None, "contact": None,
           "reply": "माफ करीं, हमरा ठीक से समझ ना आइल। फेर से बोलीं।"}
    t = text.strip()

    if any(w in t for w in ("दवाई", "दवा", "याद")):
        out["intent"] = "set_reminder"
        out["reminder_text"] = "दवाई"
        m = re.search(r"(\d+)\s*मिनट", t)
        if m:
            out["in_minutes"] = int(m.group(1))
            out["reply"] = f"ठीक बा, {m.group(1)} मिनट बाद दवाई के याद दिला देब।"
        else:
            hour = _find_hour(t)
            if hour is not None:
                out["time"] = f"{hour:02d}:00"
                out["reply"] = f"ठीक बा, {hour % 12 or 12} बजे दवाई के याद दिला देब।"
            else:
                out["intent"] = "chat"
                out["reply"] = "कवन बजे दवाई के याद दिलाईं? फेर से बोलीं।"
    elif any(w in t for w in ("फोन", "कॉल", "call", "लगा")):
        out["intent"] = "call"
        out["contact"] = next((v for k, v in CONTACT_WORDS.items() if k in t), "बेटा")
        out["reply"] = f"{out['contact']} के फोन लगावत बानी, तनी रुकीं।"
    elif any(w in t for w in ("मैसेज", "संदेश", "message", "पढ़", "पढ")):
        out["intent"] = "read_messages"
        out["reply"] = "राउर संदेश सुनावत बानी।"
    elif any(w in t for w in ("नमस्ते", "प्रणाम", "नमस्कार", "राम राम", "hello", "hi")):
        out["intent"] = "chat"
        out["reply"] = "प्रणाम! खुश रहीं। हम रउआ का सेवा कर सकीं?"
    elif any(w in t for w in ("कइसन", "हाल", "कैसी", "कैसे")):
        out["intent"] = "chat"
        out["reply"] = "हम एकदम ठीक बानी! रउआ बताईं, तबीयत पानी कइसन बा?"
    elif any(w in t for w in ("कौन", "के हउ", "नाम", "who")):
        out["intent"] = "chat"
        out["reply"] = "हम दादी साथी हईं, राउर घरेलु सहायक।"
    elif any(w in t for w in ("समय", "टाइम", "time", "केतना बज")):
        now = dt.datetime.now()
        h = now.hour % 12 or 12
        m = now.minute
        out["intent"] = "chat"
        out["reply"] = f"अहिले घड़ी में {h} बज के {m} मिनट हो रहल बा।"
    return out


def compute_due(result, now=None):
    """Turn {'in_minutes': n} or {'time': 'HH:MM'} into a datetime (or None)."""
    now = now or dt.datetime.now()
    try:
        if result.get("in_minutes"):
            return now + dt.timedelta(minutes=int(result["in_minutes"]))
        if result.get("time"):
            h, m = map(int, str(result["time"]).split(":")[:2])
            due = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if due <= now:
                due += dt.timedelta(days=1)
            return due
    except (ValueError, TypeError):
        pass
    return None
