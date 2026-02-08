import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
import uuid

# --- CONFIGURATION ---
st.set_page_config(page_title="Model Comparison Tool", layout="wide")
conn = st.connection("gsheets", type=GSheetsConnection)

MODEL_MAP = {
    "A": "qwen_A", "B": "nemotron_B", "C": "ministral_C",
    "D": "kimik2_D", "E": "gpt_E", "F": "gemma_F"
}
USER_CORRECTION_TAB = "manual_gold_corrections"

# --- USER AUTHENTICATION ---
if 'username' not in st.session_state:
    st.title("Welcome")
    st.markdown("Please sign in with your name to begin the evaluation process.")
    with st.form("login_gate"):
        user_input = st.text_input("Full Name:")
        if st.form_submit_button("Sign In") and user_input:
            st.session_state.username = user_input.strip()
            st.rerun()
    st.stop()

# --- DATA LOADING ---
@st.cache_data(ttl=10)
def load_and_group_data():
    master_df = conn.read(worksheet="merged_master_sentences")
    unique_sentences = master_df['incorrect'].unique().tolist()
    return master_df, unique_sentences

master_df, unique_list = load_and_group_data()

# --- HELPER FUNCTIONS ---
def get_existing_rating(m_id, u_idx):
    try:
        df_check = conn.read(worksheet=MODEL_MAP[m_id])
        if not df_check.empty and 'unique_set_index' in df_check.columns:
            match = df_check[(df_check['unique_set_index'] == u_idx) & (df_check['user'] == st.session_state.username)]
            if not match.empty:
                return int(match.iloc[0]['rating'])
    except:
        pass
    return None

def save_all_ratings(u_idx, current_incorrect, versions, ratings_dict, manual_fix):
    submission_uuid = str(uuid.uuid4())
    
    for m_id, rating in ratings_dict.items():
        tab_name = MODEL_MAP[m_id]
        m_row_data = versions[versions['id'] == m_id].iloc[0]
        
        new_entry = pd.DataFrame([{
            "submission_id": submission_uuid,
            "unique_set_index": u_idx,
            "user": st.session_state.username,
            "incorrect": current_incorrect,
            "corrected": m_row_data['corrected'],
            "rating": rating,
            "timestamp": str(datetime.now())
        }])

        try:
            existing_df = conn.read(worksheet=tab_name)
            mask = (existing_df['unique_set_index'] == u_idx) & (existing_df['user'] == st.session_state.username)
            if mask.any():
                existing_df = existing_df[~mask]
            updated_df = pd.concat([existing_df, new_entry], ignore_index=True)
            conn.update(worksheet=tab_name, data=updated_df)
        except:
            conn.update(worksheet=tab_name, data=new_entry)

    if manual_fix.strip():
        user_entry = pd.DataFrame([{
            "submission_id": submission_uuid,
            "unique_set_index": u_idx, 
            "user": st.session_state.username,
            "incorrect": current_incorrect, 
            "user_corrected": manual_fix
        }])
        try:
            df_user = conn.read(worksheet=USER_CORRECTION_TAB)
            mask = (df_user['unique_set_index'] == u_idx) & (df_user['user'] == st.session_state.username)
            if mask.any():
                df_user = df_user[~mask]
            updated_user_df = pd.concat([df_user, user_entry], ignore_index=True)
            conn.update(worksheet=USER_CORRECTION_TAB, data=updated_user_df)
        except:
            conn.update(worksheet=USER_CORRECTION_TAB, data=user_entry)

# --- SESSION STATE ---
if 'u_index' not in st.session_state:
    st.session_state.u_index = 0

# --- UI LOGIC ---
if not unique_list:
    st.info("No datasets are currently available.")
elif st.session_state.u_index < len(unique_list):
    current_incorrect = unique_list[st.session_state.u_index]
    versions = master_df[master_df['incorrect'] == current_incorrect]

    st.title("Evaluation Workspace")

    col_prev, col_mid, col_next = st.columns([1, 8, 1])
    with col_prev:
        if st.button("Previous"):
            if st.session_state.u_index > 0:
                st.session_state.u_index -= 1
                st.rerun()
    with col_mid:
        st.write(f"<center>Entry <b>{st.session_state.u_index + 1}</b> of {len(unique_list)}</center>", unsafe_allow_html=True)
        st.progress((st.session_state.u_index + 1) / len(unique_list))
    with col_next:
        if st.button("Next"):
            if st.session_state.u_index < len(unique_list) - 1:
                st.session_state.u_index += 1
                st.rerun()

    st.subheader("Source Text")
    st.markdown(f"> {current_incorrect}")
    st.divider()

    current_ratings = {}
    model_ids = sorted(MODEL_MAP.keys())
    rating_options = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

    # Grid Display
    for row_ids in [model_ids[:3], model_ids[3:]]:
        cols = st.columns(3)
        for i, m_id in enumerate(row_ids):
            with cols[i]:
                m_row = versions[versions['id'] == m_id]
                if not m_row.empty:
                    st.markdown(f"**Model {m_id} Output**")
                    st.info(m_row.iloc[0]['corrected'])
                    
                    existing_val = get_existing_rating(m_id, st.session_state.u_index)
                    current_ratings[m_id] = st.radio(
                        f"Score for Model {m_id}", options=rating_options,
                        index=rating_options.index(existing_val) if existing_val in rating_options else None,
                        horizontal=True, key=f"rad_{m_id}_{st.session_state.u_index}",
                        label_visibility="collapsed"
                    )
                else:
                    st.caption(f"Model {m_id} data missing.")

    st.divider()
    st.subheader("Reference Correction")
    manual_fix = st.text_area("If none of the models are perfect, provide the ideal version here:", placeholder="Enter the corrected sentence...", key=f"manual_{st.session_state.u_index}")

    all_rated = all(current_ratings[m] is not None for m in current_ratings)

    if st.button("Save and Continue", use_container_width=True, type="primary", disabled=not all_rated):
        save_all_ratings(st.session_state.u_index, current_incorrect, versions, current_ratings, manual_fix)
        st.session_state.u_index += 1
        st.rerun()

    if not all_rated:
        st.caption("Please provide a rating for each model to enable the save button.")
else:
    st.success("You have completed all available evaluations. Thank you for your time.")

# --- SIDEBAR ---
with st.sidebar:
    st.header("Account")
    st.write(f"Logged in as: **{st.session_state.username}**")
    st.divider()
    
    st.header("Team Progress")
    try:
        prog_df = conn.read(worksheet="qwen_A")
        if not prog_df.empty:
            stats = prog_df.groupby("user")["submission_id"].nunique().reset_index(name="Completed")
            st.dataframe(stats.sort_values("Completed", ascending=False), hide_index=True, use_container_width=True)
        else:
            st.write("Initial recordings in progress.")
    except:
        st.write("Leaderboard is initializing.")
    
    st.divider()
    st.header("Navigation")
    new_idx = st.number_input("Go to entry index:", 0, len(unique_list) - 1, value=st.session_state.u_index)
    if st.button("Jump to Entry"):
        st.session_state.u_index = new_idx
        st.rerun()
