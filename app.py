import os
import json
import uuid
import sqlite3
from datetime import datetime, timezone

import requests
import streamlit as st

# -------------------------
# Config / UI Theme
# -------------------------
st.set_page_config(
    page_title="CareerCraft Beta",
    page_icon="🧭",
    layout="centered",
    initial_sidebar_state="collapsed",
)

CUSTOM_CSS = """
<style>
.block-container { padding-top: 2.0rem; padding-bottom: 3rem; max-width: 880px; }
html, body, [class*="css"]  { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; }

.cc-card {
  border: 1px solid rgba(0,0,0,0.06);
  background: rgba(255,255,255,0.80);
  border-radius: 18px;
  padding: 16px 18px;
  box-shadow: 0 10px 30px rgba(2,6,23,0.06);
  margin-bottom: 14px;
}
.cc-title { font-size: 1.55rem; font-weight: 750; letter-spacing: -0.02em; margin-bottom: 0.2rem; }
.cc-sub { color: rgba(0,0,0,0.55); font-size: 0.95rem; margin-bottom: 0.1rem; }
.cc-pill {
  display:inline-block;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  font-size: 0.8rem;
  border: 1px solid rgba(0,0,0,0.08);
  background: rgba(99,102,241,0.08);
  color: rgba(67,56,202,1);
}
.stButton>button {
  border-radius: 14px !important;
  padding: 0.65rem 1.0rem !important;
  border: 1px solid rgba(0,0,0,0.08) !important;
}
.stTextInput input, .stTextArea textarea, .stSelectbox div, .stSlider div {
  border-radius: 14px !important;
}
header {visibility: hidden;}
footer {visibility: hidden;}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# -------------------------
# OpenRouter (requests)
# -------------------------
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openai/gpt-oss-120b:free"

def get_openrouter_key() -> str:
    key = None
    try:
        key = st.secrets.get("OPENROUTER_API_KEY")
    except Exception:
        pass
    key = key or os.getenv("OPENROUTER_API_KEY")
    if not key:
        st.error("Missing OPENROUTER_API_KEY. Add it to Streamlit Secrets or environment variables.")
        st.stop()
    return key

def openrouter_chat(messages, reasoning=False, temperature=0.5) -> str:
    """
    messages: list of {role, content, ...}
    reasoning: if True, requests reasoning details (do not display to users)
    """
    headers = {
        "Authorization": f"Bearer {get_openrouter_key()}",
        "Content-Type": "application/json",
        # Recommended by OpenRouter (helps routing/analytics):
        "HTTP-Referer": "https://careercraft-beta.streamlit.app",
        "X-Title": "CareerCraft Beta",
    }

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
    }

    if reasoning:
        payload["reasoning"] = {"enabled": True}

    r = requests.post(OPENROUTER_URL, headers=headers, data=json.dumps(payload), timeout=60)

    # Helpful error surface
    if r.status_code != 200:
        try:
            err = r.json()
        except Exception:
            err = {"raw": r.text}
        raise RuntimeError(f"OpenRouter error {r.status_code}: {err}")

    data = r.json()
    return data["choices"][0]["message"].get("content", "")

# -------------------------
# DB: SQLite (local file)
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
                created_at_utc TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS outputs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                output_type TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            )
        """)
        conn.commit()

def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()

def db_create_session(session_id: str, role: str, grade: int, consent_ack: int):
    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO sessions(session_id, started_at_utc, role, grade, consent_ack)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, now_utc_iso(), role, grade, consent_ack))
        conn.commit()

def db_save_response(session_id: str, q_key: str, question: str, answer: str):
    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO responses(session_id, q_key, question, answer, created_at_utc)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, q_key, question, str(answer), now_utc_iso()))
        conn.commit()

def db_save_output(session_id: str, output_type: str, content: str):
    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO outputs(session_id, output_type, content, created_at_utc)
            VALUES (?, ?, ?, ?)
        """, (session_id, output_type, content, now_utc_iso()))
        conn.commit()

# -------------------------
# Question Sets
# -------------------------
YOUNGER_QS = [
    ("interests", "What are 3–5 things you genuinely enjoy (even outside school)?"),
    ("subjects", "Which school subjects feel easiest or most interesting? Which feel hardest?"),
    ("activities", "What activities/clubs/sports do you do (or want to try)?"),
    ("learning_style", "Do you learn best by watching, reading, doing, or being coached?"),
    ("values", "What matters more to you right now: money, impact, stability, creativity, or freedom? Pick 2."),
    ("support", "What support do you have (family, teachers, coaches, friends)? What’s missing?"),
]

OLDER_QS = [
    ("interests", "What are 3–5 things you genuinely enjoy (even outside school)?"),
    ("strengths", "What do people consistently say you’re good at? What do you think you’re good at?"),
    ("subjects", "Which subjects are strongest for you (with recent grades if you know them)?"),
    ("constraints", "Any constraints? (budget, location, family expectations, time, etc.)"),
    ("career_curiosity", "List 3 careers/fields you’re curious about (even if unsure)."),
    ("risk_tolerance", "Do you prefer a clear path (stable) or exploring (higher risk/higher upside)?"),
    ("work_style", "Do you like leading, building, analyzing, helping, persuading, designing, or competing? Pick 2–3."),
    ("college_attitude", "How do you feel about college: excited, unsure, against it, or only for certain majors? Why?"),
    ("effort_habits", "What’s your biggest blocker: procrastination, focus, motivation, anxiety, or time?"),
]

def pick_questions(grade: int):
    return YOUNGER_QS if grade <= 9 else OLDER_QS

# -------------------------
# Report generation (OpenRouter)
# -------------------------
def build_llm_prompt(profile: dict) -> str:
    return f"""
You are CareerCraft, an AI career + college exploration coach for teens.
Be supportive, practical, and structured. Do NOT claim you can predict admissions outcomes.
Do NOT present medical/mental health diagnoses. Do NOT shame the user.

Profile JSON:
{json.dumps(profile, indent=2)}

Task:
Generate a professional report with these sections:

1) Snapshot (5 bullet points):
- what you infer about interests, strengths, constraints, work style, and current blockers.

2) College vs Alternatives (balanced, not preachy):
- give a reasoned estimate of whether college is a good fit RIGHT NOW.
- include alternative pathways (community college transfer, apprenticeships, certifications, bootcamps, entrepreneurship projects).
- include "when college is worth it" vs "when alternative paths might be better."

3) Career Directions (3–5 options):
For each: why it fits + what to test next (a project or experience).

4) College Strategy (if college is in play):
- Provide college "buckets" rather than a definitive list:
  a) Reach (very competitive)
  b) Match
  c) Likely/Safety
- For each bucket, provide 5–8 example schools as placeholders the student can swap later.
- Also include how to build the application: academics, activities, essays, recommendation strategy.
- Include a note: final college list requires GPA/test scores, location, cost, major, and preferences.

5) Roadmap:
- Next 14 days: 5 actions
- Next 90 days: 8 actions
- Next 12 months: 8 actions

Style:
- crisp headings
- bullets
- action-oriented
- confident but honest about uncertainty
"""

def generate_report(profile: dict) -> str:
    prompt = build_llm_prompt(profile)
    return openrouter_chat(
        messages=[
            {"role": "system", "content": "You are CareerCraft."},
            {"role": "user", "content": prompt},
        ],
        reasoning=False,  # keep False for user-facing output
        temperature=0.5,
    )

# -------------------------
# App State
# -------------------------
db_init()

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "step" not in st.session_state:
    st.session_state.step = 0  # 0=welcome, 1=profile, 2=questions, 3=report

if "profile" not in st.session_state:
    st.session_state.profile = {}

if "answers" not in st.session_state:
    st.session_state.answers = {}

if "report" not in st.session_state:
    st.session_state.report = ""

# -------------------------
# Header
# -------------------------
st.markdown(
    """
    <div class="cc-card">
      <div class="cc-pill">BETA</div>
      <div class="cc-title">CareerCraft</div>
      <div class="cc-sub">Career + college clarity for teens — structured, honest, and action-oriented. Created by Nishchal Srinarayanan.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# -------------------------
# Step 0: Welcome / Role selection
# -------------------------
if st.session_state.step == 0:
    st.markdown(
        """
        <div class="cc-card">
          <b>Quick start</b><br/>
          This beta asks a few questions and generates a structured plan.
          We store responses in a local database to improve the product later.
        </div>
        """,
        unsafe_allow_html=True,
    )

    role = st.selectbox("Who is using CareerCraft right now?", ["Student", "Parent/Guardian"])
    grade = st.slider("Student's grade", min_value=6, max_value=12, value=9, step=1)

    if role == "Parent/Guardian":
        st.info("Please hand the device to the student for the next questions. We want honest answers to help them best.")

    consent = st.checkbox("I understand this is a beta, and I’ll answer as honestly as possible. I understand responses are stored locally for improvement.")

    col1, col2 = st.columns([1, 1])
    with col1:
        start = st.button("Start", use_container_width=True, disabled=not consent)
    with col2:
        reset = st.button("Reset session", use_container_width=True)

    if reset:
        st.session_state.step = 0
        st.session_state.profile = {}
        st.session_state.answers = {}
        st.session_state.report = ""
        st.session_state.session_id = str(uuid.uuid4())
        st.rerun()

    if start:
        st.session_state.profile = {
            "user_role": "parent" if role == "Parent/Guardian" else "student",
            "grade": int(grade),
            "started_at_utc": now_utc_iso(),
        }
        db_create_session(
            session_id=st.session_state.session_id,
            role=st.session_state.profile["user_role"],
            grade=int(grade),
            consent_ack=1
        )
        st.session_state.step = 1
        st.rerun()

# -------------------------
# Step 1: Basic profile details
# -------------------------
elif st.session_state.step == 1:
    st.markdown('<div class="cc-card"><b>Basic info</b><br/>This takes ~3–5 minutes.</div>', unsafe_allow_html=True)

    name = st.text_input("First name (optional)", value=st.session_state.profile.get("name", ""))
    location = st.text_input("Location (city/state, optional)", value=st.session_state.profile.get("location", ""))
    goals = st.text_area("What do you want most in the next 2–3 years? (sports, academics, career, life)", value=st.session_state.profile.get("goals", ""), height=110)

    if st.button("Next", use_container_width=True):
        st.session_state.profile["name"] = name.strip()
        st.session_state.profile["location"] = location.strip()
        st.session_state.profile["goals"] = goals.strip()

        if name.strip():
            db_save_response(st.session_state.session_id, "name", "First name (optional)", name.strip())
        if location.strip():
            db_save_response(st.session_state.session_id, "location", "Location (optional)", location.strip())
        if goals.strip():
            db_save_response(st.session_state.session_id, "goals", "Goals (next 2–3 years)", goals.strip())

        st.session_state.step = 2
        st.rerun()

# -------------------------
# Step 2: Dynamic questions by grade
# -------------------------
elif st.session_state.step == 2:
    grade = int(st.session_state.profile.get("grade", 9))
    questions = pick_questions(grade)

    st.markdown(
        f'<div class="cc-card"><b>Questions</b><br/>Grade-based set: <span class="cc-pill">{grade}th</span></div>',
        unsafe_allow_html=True
    )

    with st.form("questions_form"):
        for q_key, q_text in questions:
            default_val = st.session_state.answers.get(q_key, "")
            if len(q_text) <= 80:
                ans = st.text_input(q_text, value=default_val, key=f"ans_{q_key}")
            else:
                ans = st.text_area(q_text, value=default_val, key=f"ans_{q_key}", height=110)
            st.session_state.answers[q_key] = ans

        submitted = st.form_submit_button("Generate my plan", use_container_width=True)

    if submitted:
        for q_key, q_text in questions:
            ans = st.session_state.answers.get(q_key, "").strip()
            if ans:
                db_save_response(st.session_state.session_id, q_key, q_text, ans)

        payload = {
            **st.session_state.profile,
            "answers": {k: v.strip() for k, v in st.session_state.answers.items() if str(v).strip()},
        }

        try:
            with st.spinner("Building your CareerCraft report..."):
                report = generate_report(payload)
        except Exception as e:
            st.error(str(e))
            st.stop()

        st.session_state.report = report
        db_save_output(st.session_state.session_id, "report", report)

        st.session_state.step = 3
        st.rerun()

# -------------------------
# Step 3: Report
# -------------------------
elif st.session_state.step == 3:
    st.markdown('<div class="cc-card"><b>Your CareerCraft Report</b><br/>This is a starting point. You can iterate it.</div>', unsafe_allow_html=True)

    st.markdown(st.session_state.report)

    colA, colB, colC = st.columns([1, 1, 1])
    with colA:
        if st.button("Restart (new session)", use_container_width=True):
            st.session_state.step = 0
            st.session_state.profile = {}
            st.session_state.answers = {}
            st.session_state.report = ""
            st.session_state.session_id = str(uuid.uuid4())
            st.rerun()

    with colB:
        st.download_button(
            "Download report (.txt)",
            data=st.session_state.report.encode("utf-8"),
            file_name="careercraft_report.txt",
            mime="text/plain",
            use_container_width=True
        )

    with colC:
        st.info("Responses are stored locally in `careercraft_beta.db`.")
