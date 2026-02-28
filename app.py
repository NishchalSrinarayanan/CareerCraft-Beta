import os
import json
import uuid
import sqlite3
import time
from datetime import datetime, timezone

import requests
import streamlit as st

st.set_page_config(
    page_title="CareerCraft Beta",
    page_icon="🧭",
    layout="centered",
    initial_sidebar_state="collapsed",
)

CUSTOM_CSS = """
<style>
.block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 880px; }
body {
  background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 50%, #2563eb 100%);
  color: white;
}
html, body, [class*="css"] { font-family: ui-sans-serif, system-ui; }

.cc-card {
  border: 1px solid rgba(255,255,255,0.08);
  background: rgba(255,255,255,0.08);
  backdrop-filter: blur(12px);
  border-radius: 18px;
  padding: 18px;
  box-shadow: 0 15px 35px rgba(0,0,0,0.25);
  margin-bottom: 18px;
  animation: fadeIn 0.4s ease-in-out;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.cc-title { font-size: 1.6rem; font-weight: 750; }
.cc-sub { color: rgba(255,255,255,0.7); }

.stButton>button {
  border-radius: 14px !important;
  padding: 0.7rem 1.2rem !important;
  background: #2563eb !important;
  color: white !important;
  border: none !important;
}

.stTextInput input, .stTextArea textarea {
  border-radius: 14px !important;
  background: rgba(255,255,255,0.1) !important;
  color: white !important;
}

header {visibility: hidden;}
footer {visibility: hidden;}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openai/gpt-oss-120b:free"

def get_key():
    key = None
    try:
        key = st.secrets.get("OPENROUTER_API_KEY")
    except:
        pass
    key = key or os.getenv("OPENROUTER_API_KEY")
    if not key:
        st.error("Missing OPENROUTER_API_KEY")
        st.stop()
    return key

def openrouter_chat(messages, reasoning=False):
    headers = {
        "Authorization": f"Bearer {get_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://careercraft-beta.streamlit.app",
        "X-Title": "CareerCraft Beta",
    }

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.5,
    }

    if reasoning:
        payload["reasoning"] = {"enabled": True}

    r = requests.post(OPENROUTER_URL, headers=headers, data=json.dumps(payload), timeout=60)

    if r.status_code != 200:
        raise RuntimeError(f"OpenRouter error {r.status_code}: {r.text}")

    return r.json()["choices"][0]["message"].get("content", "")

DB_PATH = "careercraft_beta.db"

def db_connect():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def db_init():
    with db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                started_at_utc TEXT,
                role TEXT,
                grade INTEGER,
                consent_ack INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                q_key TEXT,
                question TEXT,
                answer TEXT,
                created_at_utc TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS outputs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                output_type TEXT,
                content TEXT,
                created_at_utc TEXT
            )
        """)
        conn.commit()

def now():
    return datetime.now(timezone.utc).isoformat()

def db_create_session(sid, role, grade, consent):
    with db_connect() as conn:
        conn.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?, ?)",
                     (sid, now(), role, grade, consent))
        conn.commit()

def db_save_response(sid, key, q, a):
    with db_connect() as conn:
        conn.execute("INSERT INTO responses VALUES (NULL, ?, ?, ?, ?, ?)",
                     (sid, key, q, a, now()))
        conn.commit()

def db_save_output(sid, t, c):
    with db_connect() as conn:
        conn.execute("INSERT INTO outputs VALUES (NULL, ?, ?, ?, ?)",
                     (sid, t, c, now()))
        conn.commit()

YOUNGER_QS = [
    ("interests", "What are 3–5 things you genuinely enjoy?"),
    ("subjects", "Which school subjects feel easiest or most interesting?"),
    ("activities", "What activities/clubs do you do or want to try?"),
]

OLDER_QS = [
    ("interests", "What are 3–5 things you genuinely enjoy?"),
    ("strengths", "What are your strengths?"),
    ("career_curiosity", "List 3 careers you're curious about."),
    ("risk_tolerance", "Stable path or exploration?"),
]

def pick_questions(g):
    return YOUNGER_QS if g <= 9 else OLDER_QS

def build_prompt(profile):
    return f"""
You are CareerCraft AI.
Generate structured report with:
1 Snapshot
2 College vs alternatives
3 Career directions
4 College strategy
5 Roadmap

Profile:
{json.dumps(profile, indent=2)}
"""

def generate_report(profile):
    return openrouter_chat([
        {"role":"system","content":"You are CareerCraft."},
        {"role":"user","content":build_prompt(profile)}
    ])

db_init()

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "step" not in st.session_state:
    st.session_state.step = 0
if "profile" not in st.session_state:
    st.session_state.profile = {}
if "answers" not in st.session_state:
    st.session_state.answers = {}
if "report" not in st.session_state:
    st.session_state.report = ""

st.markdown("""
<div class="cc-card">
<div class="cc-title">CareerCraft</div>
<div class="cc-sub">Structured career clarity for teens</div>
</div>
""", unsafe_allow_html=True)

if st.session_state.step == 0:
    role = st.selectbox("User", ["Student", "Parent"])
    grade = st.slider("Grade", 6, 12, 9)
    consent = st.checkbox("Agree to beta data storage")

    if st.button("Start", disabled=not consent):
        st.session_state.profile = {"role": role, "grade": grade}
        db_create_session(st.session_state.session_id, role, grade, 1)
        st.session_state.step = 1
        st.rerun()

elif st.session_state.step == 1:
    questions = pick_questions(st.session_state.profile["grade"])

    if "q_index" not in st.session_state:
        st.session_state.q_index = 0

    idx = st.session_state.q_index
    total = len(questions)
    q_key, q_text = questions[idx]

    st.progress(idx / total)

    st.markdown(f'<div class="cc-card"><b>Question {idx+1} of {total}</b></div>', unsafe_allow_html=True)

    answer = st.text_area(q_text, value=st.session_state.answers.get(q_key, ""), height=140)

    col1, col2 = st.columns(2)

    with col1:
        if idx > 0:
            if st.button("Back", use_container_width=True):
                st.session_state.q_index -= 1
                st.rerun()

    with col2:
        if st.button("Next", use_container_width=True):
            st.session_state.answers[q_key] = answer
            db_save_response(st.session_state.session_id, q_key, q_text, answer)

            if idx + 1 < total:
                st.session_state.q_index += 1
            else:
                st.session_state.step = 2
            st.rerun()

elif st.session_state.step == 2:
    payload = {**st.session_state.profile, "answers": st.session_state.answers}

    with st.spinner("Generating your CareerCraft report..."):
        progress = st.progress(0)
        for i in range(1, 90):
            progress.progress(i)
            time.sleep(0.01)

        report = generate_report(payload)
        progress.progress(100)

    st.session_state.report = report
    db_save_output(st.session_state.session_id, "report", report)
    st.session_state.step = 3
    st.rerun()

elif st.session_state.step == 3:
    sections = st.session_state.report.split("\n\n")

    if "report_index" not in st.session_state:
        st.session_state.report_index = 0

    idx = st.session_state.report_index
    total = len(sections)

    st.markdown('<div class="cc-card">', unsafe_allow_html=True)
    st.markdown(sections[idx])
    st.markdown('</div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        if idx > 0:
            if st.button("Previous", use_container_width=True):
                st.session_state.report_index -= 1
                st.rerun()

    with col2:
        if idx < total - 1:
            if st.button("Next", use_container_width=True):
                st.session_state.report_index += 1
                st.rerun()
