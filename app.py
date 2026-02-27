import os
import json
import uuid
import sqlite3
from datetime import datetime, timezone

import streamlit as st
from openai import OpenAI

# -------------------------
# Config / UI Theme
# -------------------------
st.set_page_config(
    page_title="CareerCraft Beta",
    page_icon="🧭",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# -------------------------
# OpenRouter Config
# -------------------------
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
MODEL = "openai/gpt-oss-120b:free"

def get_openrouter_client():
    key = None
    try:
        key = st.secrets.get("OPENROUTER_API_KEY")
    except:
        pass
    key = key or os.getenv("OPENROUTER_API_KEY")

    if not key:
        st.error("Missing OPENROUTER_API_KEY")
        st.stop()

    return OpenAI(
        base_url=OPENROUTER_BASE,
        api_key=key,
    )

def openrouter_chat(messages, reasoning=False):
    client = get_openrouter_client()

    extra_body = {"reasoning": {"enabled": True}} if reasoning else None

    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        extra_body=extra_body,
        extra_headers={
            "HTTP-Referer": "http://localhost:8501",
            "X-Title": "CareerCraft Beta",
        },
        temperature=0.5,
    )

    return resp.choices[0].message.content

# -------------------------
# DB
# -------------------------
DB_PATH = "careercraft_beta.db"

def db_connect():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def db_init():
    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                started_at_utc TEXT NOT NULL,
                role TEXT NOT NULL,
                grade INTEGER NOT NULL,
                consent_ack INTEGER NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                q_key TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS outputs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                output_type TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            )
        """)
        conn.commit()

def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()

def db_create_session(session_id, role, grade, consent):
    with db_connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?, ?)",
            (session_id, now_utc_iso(), role, grade, consent)
        )
        conn.commit()

def db_save_response(session_id, key, q, a):
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO responses VALUES (NULL, ?, ?, ?, ?, ?)",
            (session_id, key, q, a, now_utc_iso())
        )
        conn.commit()

def db_save_output(session_id, t, c):
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO outputs VALUES (NULL, ?, ?, ?, ?)",
            (session_id, t, c, now_utc_iso())
        )
        conn.commit()

# -------------------------
# Question Sets
# -------------------------
YOUNGER_QS = [
    ("interests","What are 3–5 things you genuinely enjoy?"),
    ("subjects","Which school subjects feel easiest or most interesting?"),
    ("activities","What activities/clubs do you do or want to try?"),
    ("learning_style","How do you learn best?"),
]

OLDER_QS = [
    ("interests","What are 3–5 things you genuinely enjoy?"),
    ("strengths","What are your strengths?"),
    ("career_curiosity","List 3 careers you're curious about."),
    ("risk_tolerance","Stable path or exploration?"),
    ("effort_habits","Biggest blocker?"),
]

def pick_questions(g):
    return YOUNGER_QS if g <= 9 else OLDER_QS

# -------------------------
# LLM prompt
# -------------------------
def build_prompt(profile):
    return f"""
You are CareerCraft AI.
Provide structured report with:
1 Snapshot
2 College vs alternatives
3 Career directions
4 College strategy
5 Roadmap

Profile:
{json.dumps(profile,indent=2)}
"""

def generate_report(profile):
    msg = openrouter_chat(
        [
            {"role":"system","content":"You are CareerCraft."},
            {"role":"user","content":build_prompt(profile)}
        ],
        reasoning=False
    )
    return msg

# -------------------------
# App State
# -------------------------
db_init()

if "session_id" not in st.session_state:
    st.session_state.session_id=str(uuid.uuid4())
if "step" not in st.session_state:
    st.session_state.step=0
if "profile" not in st.session_state:
    st.session_state.profile={}
if "answers" not in st.session_state:
    st.session_state.answers={}
if "report" not in st.session_state:
    st.session_state.report=""

# -------------------------
# Header
# -------------------------
st.title("CareerCraft Beta")

# -------------------------
# Step 0
# -------------------------
if st.session_state.step==0:
    role=st.selectbox("User",["Student","Parent"])
    grade=st.slider("Grade",6,12,9)
    consent=st.checkbox("Agree to beta data collection")

    if st.button("Start",disabled=not consent):
        st.session_state.profile={"role":role,"grade":grade}
        db_create_session(st.session_state.session_id,role,grade,1)
        st.session_state.step=1
        st.rerun()

# -------------------------
# Step 1
# -------------------------
elif st.session_state.step==1:
    questions=pick_questions(st.session_state.profile["grade"])
    with st.form("q"):
        for k,q in questions:
            st.session_state.answers[k]=st.text_input(q)
        if st.form_submit_button("Generate"):
            for k,q in questions:
                db_save_response(st.session_state.session_id,k,q,st.session_state.answers[k])

            payload={**st.session_state.profile,"answers":st.session_state.answers}
            with st.spinner("Generating report"):
                report=generate_report(payload)

            st.session_state.report=report
            db_save_output(st.session_state.session_id,"report",report)
            st.session_state.step=2
            st.rerun()

# -------------------------
# Step 2
# -------------------------
elif st.session_state.step==2:
    st.markdown(st.session_state.report)
    if st.button("Restart"):
        st.session_state.clear()
        st.rerun()
