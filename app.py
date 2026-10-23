import os
import io
import datetime as dt
import streamlit as st
import speech_recognition as sr
from gtts import gTTS

from logic import extract_json, offline_intent, compute_due

st.set_page_config(page_title="Dadi Sathi - Voice Assistant", page_icon="👵", layout="centered")

MODEL = os.environ.get("DADI_MODEL", "claude-3-5-haiku-20241022")
CONTACTS = ["बेटा", "बहू", "डॉक्टर"]
INBOX = [
    "बेटा राहुल का संदेश: पापा, हम शाम के छह बजे घरे आ जाएब।",
    "डॉक्टर साहब का संदेश: काल्ह सबेरे दस बजे जाँच खातिर आईं।"
]

SYSTEM = """You are 'Dadi Sathi', a warm voice assistant for elderly Bhojpuri-speaking people in eastern Uttar Pradesh.
The user's speech was transcribed by a Hindi speech recogniser, so it may be a Hindi/Bhojpuri mix with small errors. Be forgiving.
Current date and time: {NOW}. Known contacts: {CONTACTS}.
Reply with ONE JSON object only, no markdown, no extra text:
{"intent": "set_reminder" | "call" | "read_messages" | "chat",
 "reminder_text": short string or null,
 "time": "HH:MM" in 24-hour format or null,
 "in_minutes": integer or null (use when the user says 'X minute baad'),
 "contact": one name from the contacts list or null,
 "reply": string}
Rules for "reply": write in Bhojpuri using Devanagari script, 1-2 short sentences, respectful (रउआ / राउर),
simple words, no English, no emojis.
If the request is unclear, ask one short clarifying question in Bhojpuri with intent "chat"."""

# Load .env file if running locally
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

GROQ_API_KEY = get_secret("GROQ_API_KEY")
GROQ_MODEL = get_secret("GROQ_MODEL", "qwen/qwen3.8-27b")
ANTHROPIC_API_KEY = get_secret("ANTHROPIC_API_KEY")

groq_client = None
if GROQ_API_KEY:
    try:
        from groq import Groq
        groq_client = Groq(api_key=GROQ_API_KEY)
    except Exception:
        pass

client = None
if ANTHROPIC_API_KEY:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except Exception:
        pass

if "reminders" not in st.session_state:
    st.session_state.reminders = []
if "heard" not in st.session_state:
    st.session_state.heard = ""
if "reply" not in st.session_state:
    st.session_state.reply = ""
if "action" not in st.session_state:
    st.session_state.action = ""
if "audio_bytes" not in st.session_state:
    st.session_state.audio_bytes = None
if "last_audio_id" not in st.session_state:
    st.session_state.last_audio_id = None

def tts_bytes(text):
    fp = io.BytesIO()
    gTTS(text=text, lang="hi").write_to_fp(fp)
    fp.seek(0)
    return fp.read()

def think(text):
    if groq_client:
        try:
            system = (SYSTEM.replace("{NOW}", dt.datetime.now().strftime("%A %d %B %Y, %H:%M"))
                            .replace("{CONTACTS}", ", ".join(CONTACTS)))
            resp = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": text}
                ],
                temperature=0.2,
                max_tokens=250,
                response_format={"type": "json_object"}
            )
            return extract_json(resp.choices[0].message.content)
        except Exception:
            pass
    elif client:
        try:
            system = (SYSTEM.replace("{NOW}", dt.datetime.now().strftime("%A %d %B %Y, %H:%M"))
                            .replace("{CONTACTS}", ", ".join(CONTACTS)))
            msg = client.messages.create(
                model=MODEL,
                max_tokens=300,
                system=system,
                messages=[{"role": "user", "content": text}]
            )
            return extract_json(msg.content[0].text)
        except Exception:
            pass
    return offline_intent(text)

def process_command(text):
    st.session_state.heard = text
    st.session_state.action = ""
    result = think(text)
    intent = result.get("intent", "chat")
    reply = result.get("reply") or "ठीक बा।"
    st.session_state.reply = reply

    full_speech = reply

    if intent == "set_reminder":
        due = compute_due(result)
        if due:
            label = result.get("reminder_text") or "दवाई"
            st.session_state.reminders.append({"text": label, "due": due, "fired": False})
    elif intent == "call":
        st.session_state.action = f"📞 {result.get('contact') or 'बेटा'} को फोन लग रहा है..."
    elif intent == "read_messages":
        st.session_state.action = "\n\n".join(["✉️ " + m for m in INBOX])
        full_speech = reply + " " + " ".join(INBOX)

    try:
        st.session_state.audio_bytes = tts_bytes(full_speech)
    except Exception as e:
        st.error(f"आवाज़ नहीं चली: {e}")

mode = "ONLINE: Groq (Ultra-Fast)" if groq_client else ("ONLINE: Claude" if client else "OFFLINE: keyword mode")
st.markdown(f"<h1 style='text-align: center; color: #FFB000;'>👵 दादी साथी ({mode})</h1>", unsafe_allow_html=True)

audio_val = st.audio_input("🎙️ बोलीं (Record your voice):")
if audio_val is not None:
    audio_id = hash(audio_val.getvalue())
    if audio_id != st.session_state.last_audio_id:
        st.session_state.last_audio_id = audio_id
        rec = sr.Recognizer()
        try:
            with sr.AudioFile(audio_val) as source:
                audio_data = rec.record(source)
            transcribed_text = rec.recognize_google(audio_data, language="hi-IN")
            process_command(transcribed_text)
        except sr.UnknownValueError:
            st.warning("ठीक से समझ ना आइल, फेर से बोलीं")
        except Exception as e:
            st.error(f"गड़बड़: {type(e).__name__} - नीचे लिख के भेजीं")

with st.form("text_form", clear_on_submit=True):
    typed_text = st.text_input("Backup: यहाँ लिख के भेजीं (Type here):")
    submitted = st.form_submit_button("भेजीं (Send)")
    if submitted and typed_text.strip():
        process_command(typed_text.strip())

if st.session_state.heard:
    st.markdown(f"<h3 style='text-align: center;'>🗣️ {st.session_state.heard}</h3>", unsafe_allow_html=True)

if st.session_state.reply:
    st.markdown(f"<h2 style='text-align: center; color: #7CFFB2;'>{st.session_state.reply}</h2>", unsafe_allow_html=True)

if st.session_state.action:
    st.info(st.session_state.action)

if st.session_state.audio_bytes:
    st.audio(st.session_state.audio_bytes, format="audio/mp3", autoplay=True)

now = dt.datetime.now()
for r in st.session_state.reminders:
    if not r["fired"] and r["due"] <= now:
        r["fired"] = True
        due_msg = f"दादी, {r['text']} के समय हो गइल बा। खा लीं।"
        st.warning(f"⏰ {due_msg}")
        try:
            st.audio(tts_bytes(due_msg), format="audio/mp3", autoplay=True)
        except Exception:
            pass

if st.session_state.reminders:
    st.subheader("⏰ याद दिलावे वाला सूची (Reminders)")
    for r in st.session_state.reminders[-5:]:
        icon = "✅" if r["fired"] else "⏰"
        st.write(f"{icon} **{r['text']}** - {r['due'].strftime('%I:%M %p')}")