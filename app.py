import os
import io
import html
import logging
import streamlit as st
import speech_recognition as sr
from gtts import gTTS
from logic import (extract_json, offline_intent, compute_due, describe_due, now_ist)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dadi")

st.set_page_config(page_title="Dadi Sathi - Voice Assistant", page_icon="👵", layout="centered")

# ---------- config ----------
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))


def get_secret(key, default=None):
    if key in os.environ:
        return os.environ[key]
    try:
        return st.secrets[key]
    except Exception:
        return default


CONTACTS = ["बेटा", "बहू", "डॉक्टर"]
INBOX = [
    "बेटा राहुल का संदेश: पापा, हम शाम के छह बजे घरे आ जाएब।",
    "डॉक्टर साहब का संदेश: काल्ह सबेरे दस बजे जाँच खातिर आईं।",
]
VALID_INTENTS = {"set_reminder", "call", "read_messages", "chat"}

# Verify these model names are valid for your accounts.
CLAUDE_MODEL = get_secret("DADI_MODEL", "claude-haiku-5-5")
GROQ_MODEL = get_secret("GROQ_MODEL", "llama-3.3-70b-versatile")

SYSTEM = """You are 'Dadi Sathi', a warm voice assistant for elderly Bhojpuri-speaking people in eastern Uttar Pradesh.
The user's speech was transcribed by a Hindi speech recogniser, so it may be a Hindi/Bhojpuri mix with small errors. Be forgiving.
Current date and time (IST): {NOW}. Known contacts: {CONTACTS}.
Reply with ONE JSON object only, no markdown, no extra text:
{"intent": "set_reminder" | "call" | "read_messages" | "chat",
 "reminder_text": short string or null,
 "time": "HH:MM" in 24-hour format or null,
 "in_minutes": integer or null (use when the user says 'X minute/ghante baad', convert hours to minutes),
 "contact": one name from the contacts list or null,
 "reply": string}
Time rules: if the user gives no AM/PM, choose the next upcoming occurrence of that clock time.
Rules for "reply": write in Bhojpuri using Devanagari script, 1-2 short sentences, respectful (रउआ / राउर),
simple words, no English, no emojis.
If the request is unclear, ask one short clarifying question in Bhojpuri with intent "chat"."""

groq_client = None
if get_secret("GROQ_API_KEY"):
    try:
        from groq import Groq
        groq_client = Groq(api_key=get_secret("GROQ_API_KEY"))
    except Exception as e:
        log.warning("Groq init failed: %s", e)

claude_client = None
if get_secret("ANTHROPIC_API_KEY"):
    try:
        import anthropic
        claude_client = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))
    except Exception as e:
        log.warning("Anthropic init failed: %s", e)

# ---------- state ----------
for k, v in {"reminders": [], "alerts": [], "heard": "", "reply": "", "action": "",
             "audio_bytes": None, "play_audio": False, "last_audio_id": None}.items():
    if k not in st.session_state:
        st.session_state[k] = v


def tts_bytes(text):
    fp = io.BytesIO()
    gTTS(text=text, lang="hi").write_to_fp(fp)
    return fp.getvalue()


def think(text):
    now = now_ist()
    system = (SYSTEM.replace("{NOW}", now.strftime("%A %d %B %Y, %H:%M"))
                    .replace("{CONTACTS}", ", ".join(CONTACTS)))
    result = None
    if groq_client:
        try:
            resp = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": text}],
                temperature=0.2, max_tokens=300,
                response_format={"type": "json_object"})
            result = extract_json(resp.choices[0].message.content)
        except Exception as e:
            log.warning("Groq failed: %s", e)
    if result is None and claude_client:
        try:
            msg = claude_client.messages.create(
                model=CLAUDE_MODEL, max_tokens=300, system=system,
                messages=[{"role": "user", "content": text}])
            result = extract_json(msg.content[0].text)
        except Exception as e:
            log.warning("Claude failed: %s", e)
    if not isinstance(result, dict):
        result = offline_intent(text, now)
    if result.get("intent") not in VALID_INTENTS:
        result["intent"] = "chat"
    return result


def process_command(text):
    st.session_state.heard = text
    st.session_state.action = ""
    now = now_ist()
    result = think(text)
    intent = result["intent"]
    reply = result.get("reply") or "ठीक बा।"

    if intent == "set_reminder":
        due = compute_due(result, now)
        if due:
            label = result.get("reminder_text") or "दवाई"
            st.session_state.reminders.append({"text": label, "due": due, "fired": False})
            # Confirmation built from the REAL computed time, not the model's guess.
            reply = f"ठीक बा, {label} खातिर {describe_due(due, now)} याद दिला देब।"
        else:
            reply = "कवन बजे याद दिलाईं? फेर से बोलीं।"
    full_speech = reply
    if intent == "call":
        st.session_state.action = f"📞 {result.get('contact') or 'बेटा'} को फोन लग रहा है..."
    elif intent == "read_messages":
        st.session_state.action = "\n\n".join("✉️ " + m for m in INBOX)
        full_speech = reply + " " + " ".join(INBOX)

    st.session_state.reply = reply
    try:
        st.session_state.audio_bytes = tts_bytes(full_speech)
        st.session_state.play_audio = True
    except Exception as e:
        st.session_state.audio_bytes = None
        st.error(f"आवाज़ नहीं चली: {e}")


# ---------- UI ----------
mode = ("ONLINE: Groq" if groq_client else "ONLINE: Claude" if claude_client else "OFFLINE: keyword mode")
st.markdown(f"<h1 style='text-align:center;color:#FFB000;'>👵 दादी साथी ({mode})</h1>", unsafe_allow_html=True)

audio_val = st.audio_input("🎙️ बोलीं (Record your voice):")
if audio_val is not None:
    audio_id = hash(audio_val.getvalue())
    if audio_id != st.session_state.last_audio_id:
        st.session_state.last_audio_id = audio_id
        rec = sr.Recognizer()
        try:
            with sr.AudioFile(audio_val) as source:
                audio_data = rec.record(source)
            process_command(rec.recognize_google(audio_data, language="hi-IN"))
        except sr.UnknownValueError:
            st.warning("ठीक से समझ ना आइल, फेर से बोलीं")
        except Exception as e:
            log.exception("speech failed")
            st.error(f"गड़बड़: {type(e).__name__} - नीचे लिख के भेजीं")

with st.form("text_form", clear_on_submit=True):
    typed_text = st.text_input("Backup: यहाँ लिख के भेजीं (Type here):")
    if st.form_submit_button("भेजीं (Send)") and typed_text.strip():
        process_command(typed_text.strip())

if st.session_state.heard:
    st.markdown(f"<h3 style='text-align:center;'>🗣️ {html.escape(st.session_state.heard)}</h3>",
                unsafe_allow_html=True)
if st.session_state.reply:
    st.markdown(f"<h2 style='text-align:center;color:#7CFFB2;'>{html.escape(st.session_state.reply)}</h2>",
                unsafe_allow_html=True)
if st.session_state.action:
    st.info(st.session_state.action)

if st.session_state.audio_bytes:
    # autoplay only once, so later reruns don't replay the old reply
    st.audio(st.session_state.audio_bytes, format="audio/mp3", autoplay=st.session_state.play_audio)
    st.session_state.play_audio = False


# Re-runs by itself every 5s, so reminders fire even if nobody touches the page.
@st.fragment(run_every="5s")
def reminder_panel():
    now = now_ist()
    newly = []
    for r in st.session_state.reminders:
        if not r["fired"] and r["due"] <= now:
            r["fired"] = True
            msg = f"दादी, {r['text']} के समय हो गइल बा।"
            st.session_state.alerts.append(msg)
            newly.append(msg)

    for msg in st.session_state.alerts[-3:]:
        st.warning(f"⏰ {msg}")
    if st.session_state.alerts:
        if st.button("ठीक बा (Dismiss)"):
            st.session_state.alerts = []
    for msg in newly:
        try:
            st.audio(tts_bytes(msg), format="audio/mp3", autoplay=True)
        except Exception as e:
            log.warning("alert tts failed: %s", e)

    if st.session_state.reminders:
        st.subheader("⏰ याद दिलावे वाला सूची (Reminders)")
        for r in st.session_state.reminders[-5:]:
            icon = "✅" if r["fired"] else "⏰"
            when = r["due"].astimezone(now.tzinfo)
            fmt = "%I:%M %p" if when.date() == now.date() else "%d %b, %I:%M %p"
            st.write(f"{icon} **{r['text']}** - {when.strftime(fmt)}")


reminder_panel()