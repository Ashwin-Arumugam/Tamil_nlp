import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
import uuid

# ---------------- CONFIG ----------------
st.set_page_config(page_title="Model Comparison Tool", layout="wide")
conn = st.connection("gsheets", type=GSheetsConnection)

# ---------------- GIDS ----------------
MASTER_SHEET_GID = 1905633307
USER_CORRECTION_GID = 677241304

MODEL_SHEET_GIDS = {
    "A": 364113859,
    "B": 952136825,
    "C": 656105801,
    "D": 1630302691,
    "E": 803791042,
    "F": 141437423,
}

# ---------------- LOGIN ----------------
if "username" not in st.session_state:
    st.title("Welcome")
    with st.form("login"):
        name = st.text_input("Full Name")
        if st.form_submit_button("Sign In") and name:
            st.session_state.username = name.strip()
            st.rerun()
    st.stop()

# ---------------- LOAD DATA ----------------
def load_master():
    df = conn.read(worksheet_id=MASTER_SHEET_GID)
    df["incorrect"] = df["incorrect"].astype(str)
    return df, df["incorrect"].unique().tolist()

master_df, unique_list = load_master()

# ---------------- HELPERS ----------------
def read_sheet(gid):
    try:
        return conn.read(worksheet_id=gid)
    except:
        return pd.DataFrame()

def write_sheet(gid, df):
    conn.update(worksheet_id=gid, data=df)

def get_existing_rating(model_id, u_idx):
    df = read_sheet(MODEL_SHEET_GIDS[model_id])
    if df.empty:
        return None
    row = df[
        (df["unique_set_index"] == u_idx)
        & (df["user"] == st.session_state.username)
    ]
    return int(row.iloc[0]["rating"]) if not row.empty else None

def upsert(gid, new_row, u_idx):
    df = read_sheet(gid)
    if not df.empty and "unique_set_index" in df.columns:
        df = df[~(
            (df["unique_set_index"] == u_idx)
            & (df["user"] == st.session_state.username)
        )]
    write_sheet(gid, pd.concat([df, new_row], ignore_index=True))

def save_all(u_idx, incorrect, versions, ratings, manual_fix):
    sid = str(uuid.uuid4())

    for m_id, rating in ratings.items():
        row = versions[versions["id"] == m_id].iloc[0]
        entry = pd.DataFrame([{
            "submission_id": sid,
            "user": st.session_state.username,
            "unique_set_index": u_idx,
            "incorrect": incorrect,
            "corrected": row["corrected"],
            "rating": rating,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }])
        upsert(MODEL_SHEET_GIDS[m_id], entry, u_idx)

    if manual_fix.strip():
        entry = pd.DataFrame([{
            "submission_id": sid,
            "user": st.session_state.username,
            "unique_set_index": u_idx,
            "incorrect": incorrect,
            "user_corrected": manual_fix,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }])
        upsert(USER_CORRECTION_GID, entry, u_idx)

# ---------------- STATE ----------------
if "u_index" not in st.session_state:
    st.session_state.u_index = 0

# ---------------- UI ----------------
if st.session_state.u_index >= len(unique_list):
    st.success("All evaluations completed 🎉")
    st.stop()

incorrect = unique_list[st.session_state.u_index]
versions = master_df[master_df["incorrect"] == incorrect]

st.title("Evaluation Workspace")
st.markdown(f"> {incorrect}")
st.divider()

ratings = {}
for row in [["A","B","C"], ["D","E","F"]]:
    cols = st.columns(3)
    for i, m in enumerate(row):
        with cols[i]:
            out = versions[versions["id"] == m]
            if out.empty:
                continue
            st.info(out.iloc[0]["corrected"])
            prev = get_existing_rating(m, st.session_state.u_index)
            ratings[m] = st.radio(
                m,
                range(1,11),
                index=(prev-1) if prev else None,
                key=f"{m}_{st.session_state.u_index}",
                horizontal=True,
                label_visibility="collapsed",
            )

manual_fix = st.text_area("Reference Correction")

if st.button("Save and Continue", disabled=any(v is None for v in ratings.values())):
    save_all(
        st.session_state.u_index,
        incorrect,
        versions,
        ratings,
        manual_fix,
    )
    st.session_state.u_index += 1
    st.rerun()
