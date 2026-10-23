"""Pure helper logic for the Dadi voice assistant (no audio / GUI / network needed)."""
import re
import json
import datetime as dt
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist():
    return dt.datetime.now(IST)


HINDI_NUM = {"एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "पाच": 5,
             "छह": 6, "छः": 6, "छे": 6, "छ": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
             "ग्यारह": 11, "बारह": 12, "पंद्रह": 15, "पन्द्रह": 15, "बीस": 20,
             "तीस": 30, "चालीस": 40, "पैंतालीस": 45, "पचास": 50}

# words like "डेढ़ बजे" (1:30) and "ढाई बजे" (2:30)
SPECIAL_HOURS = {"डेढ़": (1, 30), "डेढ": (1, 30), "ढाई": (2, 30)}

CONTACT_WORDS = {"बेटे": "बेटा", "बेटा": "बेटा", "बहू": "बहू", "बहु": "बहू",
                 "डॉक्टर": "डॉक्टर", "डाक्टर": "डॉक्टर"}

PM_WORDS = ("शाम", "दोपहर", "दुपहर", "साँझ", "सांझ", "तीसरे पहर")
NIGHT_WORDS = ("रात", "राति", "रात्रि")
AM_WORDS = ("सुबह", "सबेरे", "सवेरे", "भोर")


def extract_json(text):
    """Pull the first JSON object out of a model reply (tolerates ```json fences and <think> blocks)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"```(?:json)?", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON found")
    return json.loads(text[start:end + 1])


def _to_int(tok):
    tok = tok.strip()
    if re.fullmatch(r"\d+", tok):
        return int(tok)
    return HINDI_NUM.get(tok)


def _find_time(t):
    """Return (hour, minute, explicit_period) found in text, or None.

    explicit_period is True when the speaker said सुबह/शाम/रात etc.,
    so the hour is already resolved to 24-hour format.
    """
    m = re.search(r"(?:(साढ़े|साढे|सवा|पौने)\s*)?(\d{1,2}|[^\s\d]+)\s*बजे", t)
    if not m:
        return None
    prefix, tok = m.group(1), m.group(2)

    if tok in SPECIAL_HOURS:
        hour, minute = SPECIAL_HOURS[tok]
    else:
        hour = _to_int(tok)
        if hour is None or not (0 <= hour <= 24):
            return None
        minute = 0
        if prefix in ("साढ़े", "साढे"):
            minute = 30
        elif prefix == "सवा":
            minute = 15
        elif prefix == "पौने":
            hour, minute = hour - 1, 45
            if hour <= 0:
                hour = 12

    explicit = False
    if any(w in t for w in PM_WORDS):
        explicit = True
        if 1 <= hour <= 11:
            hour += 12
    elif any(w in t for w in NIGHT_WORDS):
        explicit = True
        if hour == 12:
            hour = 0
        elif 6 <= hour <= 11:
            hour += 12
    elif any(w in t for w in AM_WORDS):
        explicit = True
        if hour == 12:
            hour = 0
    return hour % 24, minute, explicit


def _find_relative_minutes(t):
    """'10 मिनट बाद', 'दो घंटे बाद', 'आधा घंटा बाद' -> minutes, or None."""
    if re.search(r"आधा\s*घ[ंण]्?टा|आधे\s*घ[ंण]्?टे", t):
        return 30
    m = re.search(r"(\d+|[^\s\d]+)\s*(मिनट|घ[ंण]्?टा|घ[ंण]्?टे)", t)
    if not m:
        return None
    n = _to_int(m.group(1))
    if n is None:
        return None
    return n * 60 if m.group(2).startswith("घ") else n


def offline_intent(text, now=None):
    """Keyword-based fallback when there is no internet / API key."""
    now = now or now_ist()
    out = {"intent": "chat", "reminder_text": None, "time": None,
           "in_minutes": None, "contact": None,
           "reply": "माफ करीं, हमरा ठीक से समझ ना आइल। फेर से बोलीं।"}
    t = text.strip()
    t_low = t.lower()

    if any(w in t for w in ("दवाई", "दवा", "याद")):
        out["intent"] = "set_reminder"
        out["reminder_text"] = "दवाई"
        mins = _find_relative_minutes(t)
        if mins:
            out["in_minutes"] = mins
            out["reply"] = "ठीक बा, याद दिला देब।"
        else:
            found = _find_time(t)
            if found:
                hour, minute, explicit = found
                if not explicit and 1 <= hour <= 12:
                    # No "सुबह/शाम" said: pick whichever (AM or PM) comes next.
                    cands = []
                    for h in {hour % 12, hour % 12 + 12}:
                        c = now.replace(hour=h, minute=minute, second=0, microsecond=0)
                        if c <= now:
                            c += dt.timedelta(days=1)
                        cands.append(c)
                    best = min(cands)
                    hour, minute = best.hour, best.minute
                out["time"] = f"{hour:02d}:{minute:02d}"
                out["reply"] = "ठीक बा, याद दिला देब।"
            else:
                out["intent"] = "chat"
                out["reply"] = "कवन बजे दवाई के याद दिलाईं? फेर से बोलीं।"
    elif any(w in t for w in ("फोन", "कॉल", "लगा")) or re.search(r"\bcall\b", t_low):
        out["intent"] = "call"
        out["contact"] = next((v for k, v in CONTACT_WORDS.items() if k in t), "बेटा")
        out["reply"] = f"{out['contact']} के फोन लगावत बानी, तनी रुकीं।"
    elif any(w in t for w in ("मैसेज", "संदेश", "पढ़", "पढ")) or "message" in t_low:
        out["intent"] = "read_messages"
        out["reply"] = "राउर संदेश सुनावत बानी।"
    elif any(w in t for w in ("नमस्ते", "प्रणाम", "नमस्कार", "राम राम")) or re.search(r"\b(hello|hi)\b", t_low):
        out["reply"] = "प्रणाम! खुश रहीं। हम रउआ का सेवा कर सकीं?"
    elif any(w in t for w in ("कइसन", "हाल", "कैसी", "कैसे")):
        out["reply"] = "हम एकदम ठीक बानी! रउआ बताईं, तबीयत पानी कइसन बा?"
    elif any(w in t for w in ("समय", "टाइम", "केतना बज")) or re.search(r"\btime\b", t_low):
        h = now.hour % 12 or 12
        out["reply"] = f"अभी घड़ी में {h} बज के {now.minute} मिनट हो रहल बा।"
    elif any(w in t for w in ("कौन", "के हउ", "नाम")) or re.search(r"\bwho\b", t_low):
        out["reply"] = "हम दादी साथी हईं, राउर घरेलू सहायक।"
    return out


def _as_int(v):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def compute_due(result, now=None):
    """Convert {'in_minutes': n} or {'time': 'HH:MM'} into a timezone-aware IST datetime (or None)."""
    now = now or now_ist()
    now = now.replace(tzinfo=IST) if now.tzinfo is None else now.astimezone(IST)

    minutes = _as_int(result.get("in_minutes"))
    if minutes is not None and minutes > 0:
        return now + dt.timedelta(minutes=minutes)

    tm = result.get("time")
    if tm:
        m = re.match(r"^\s*(\d{1,2})\s*[:.]\s*(\d{1,2})", str(tm))
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            if 0 <= h <= 23 and 0 <= mi <= 59:
                due = now.replace(hour=h, minute=mi, second=0, microsecond=0)
                if due <= now:
                    due += dt.timedelta(days=1)
                return due
    return None


def describe_due(due, now=None):
    """Bhojpuri phrase for when a reminder will fire, e.g. '10 मिनट बाद' / 'शाम 6 बजे'."""
    now = now or now_ist()
    mins = round((due - now).total_seconds() / 60)
    if mins < 60:
        return f"{max(mins, 1)} मिनट बाद"
    h = due.hour
    period = ("सबेरे" if 4 <= h < 12 else "दुपहर" if 12 <= h < 16
              else "शाम" if 16 <= h < 20 else "रात")
    h12 = h % 12 or 12
    clock = f"{h12}:{due.minute:02d}" if due.minute else f"{h12}"
    day = ""
    if due.date() != now.date():
        day = "काल्ह " if (due.date() - now.date()).days == 1 else due.strftime("%d %b ")
    return f"{day}{period} {clock} बजे"