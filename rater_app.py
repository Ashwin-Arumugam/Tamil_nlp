import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
import uuid

# --- CONFIG ---
st.set_page_config(page_title="Model Comparison Tool", layout="wide")

conn = st.connection("gsheets", type=GSheetsConnection)

# --- SHEET NAMES (MUST MATCH GOOGLE SHEET TABS EXACTLY) ---
MASTER_SHEET = "merged_master_sentences"
USER_CORRECTION_SHEET = "manual_gold_corrections"

MODEL_SHEETS = {
    "A": "qwen",
    "B": "nemotron",
    "C": "ministral",
    "D": "kimik2",
    "E": "gpt",
    "F": "gemma",
}

# --- USER LOGIN ---
if "username" not in st.session_state:
    st.title("Welcome")
    with st.form("login_gate"):
        user_input = st.text_input("Full Name")
        if st.form_submit_button("Sign In") and user_input:
            st.session_state.username = user_input.strip()
            st.rerun()
    st.stop()

# --- LOAD MASTER DATA ---
@st.cache_data
def load_master():
    df = conn.read(worksheet=MASTER_SHEET)
    df["incorrect"] = df["incorrect"].astype(str)
    return df, df["incorrect"].unique().tolist()

master_df, unique_list = load_master()

# --- HELPERS ---
def get_existing_rating(model_key, u_idx):
    try:
        df = conn.read(worksheet=MODEL_SHEETS[model_key])
        if df.empty:
            return None

        match = df[
            (df["unique_set_index"] == u_idx)
            & (df["user"] == st.session_state.username)
        ]
        if not match.empty:
            return int(match.iloc[0]["rating"])
    except:
        pass
    return None


def safe_update(sheet_name, new_row_df, u_idx):
    try:
        existing_df = conn.read(worksheet=sheet_name)

        if not existing_df.empty and "unique_set_index" in existing_df.columns:
            existing_df = existing_df[~(
                (existing_df["unique_set_index"] == u_idx)
                & (existing_df["user"] == st.session_state.username)
            )]

        updated_df = pd.concat([existing_df, new_row_df], ignore_index=True)
        conn.update(worksheet=sheet_name, data=updated_df)

    except:
        conn.update(worksheet=sheet_name, data=new_row_df)


def save_all_ratings(u_idx, current_incorrect, versions, ratings_dict, manual_fix):
    submission_uuid = str(uuid.uuid4())

    for model_key, rating in ratings_dict.items():

        model_rows = versions[versions["id"] == model_key]
        if model_rows.empty:
            continue

        m_row = model_rows.iloc[0]

        new_entry = pd.DataFrame([{
            "submission_id": submission_uuid,
            "user": st.session_state.username,
            "unique_set_index": u_idx,
            "incorrect": current_incorrect,
            "corrected": m_row["corrected"],
            "rating": rating,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }])

        safe_update(MODEL_SHEETS[model_key], new_entry, u_idx)

    if manual_fix.strip():
        user_entry = pd.DataFrame([{
            "submission_id": submission_uuid,
            "user": st.session_state.username,
            "unique_set_index": u_idx,
            "incorrect": current_incorrect,
            "user_corrected": manual_fix,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }])

        safe_update(USER_CORRECTION_SHEET, user_entry, u_idx)


# --- SESSION STATE ---
if "u_index" not in st.session_state:
    st.session_state.u_index = 0


# --- UI ---
if not unique_list:
    st.info("No data loaded.")
elif st.session_state.u_index < len(unique_list):

    current_incorrect = unique_list[st.session_state.u_index]
    versions = master_df[master_df["incorrect"] == current_incorrect]

    st.title("Evaluation Workspace")
    st.markdown(f"> {current_incorrect}")
    st.divider()

    ratings = {}

    model_keys = list(MODEL_SHEETS.keys())

    for row in [model_keys[:3], model_keys[3:]]:
        cols = st.columns(3)

        for i, model_key in enumerate(row):
            with cols[i]:

                model_rows = versions[versions["id"] == model_key]
                if model_rows.empty:
                    continue

                st.markdown(f"**{MODEL_SHEETS[model_key].capitalize()} Output**")
                st.info(model_rows.iloc[0]["corrected"])

                existing = get_existing_rating(model_key, st.session_state.u_index)

                ratings[model_key] = st.radio(
                    f"{model_key}",
                    options=list(range(1, 11)),
                    index=(existing - 1) if existing else None,
                    key=f"{model_key}_{st.session_state.u_index}",
                    horizontal=True,
                    label_visibility="collapsed",
                )

    st.divider()
    manual_fix = st.text_area("Reference Correction")

    if st.button(
        "Save and Continue",
        disabled=any(v is None for v in ratings.values()),
        use_container_width=True,
    ):
        save_all_ratings(
            st.session_state.u_index,
            current_incorrect,
            versions,
            ratings,
            manual_fix,
        )
        st.session_state.u_index += 1
        st.rerun()

else:
    st.success("All evaluations completed 🎉")


# --- SIDEBAR ---
with st.sidebar:
    st.write(f"User: **{st.session_state.username}**")
    st.divider()

    try:
        df = conn.read(worksheet=MODEL_SHEETS["A"])
        if not df.empty:
            stats = (
                df.groupby("user")["submission_id"]
                .nunique()
                .reset_index(name="Completed")
                .sort_values("Completed", ascending=False)
            )
            st.dataframe(stats, use_container_width=True)
        else:
            st.write("Leaderboard initializing…")
    except:
        st.write("Leaderboard initializing…")
