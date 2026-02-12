import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
import uuid
import time

# =========================================================
# CONFIGURATION
# =========================================================
st.set_page_config(page_title="Model Comparison Tool", layout="wide")
conn = st.connection("gsheets", type=GSheetsConnection)

# MASTER SHEET GID (Used for loading the source data)
MASTER_SHEET_GID = 1905633307

# TAB NAMES (Crucial: These must match your Google Sheet tab names exactly)
MODEL_TABS = {
    "A": "qwen",
    "B": "nemotron",
    "C": "ministral",
    "D": "kimik2",
    "E": "gpt",
    "F": "gemma"
}
USER_CORRECTION_TAB = "user_corrections" 

MODEL_MAP = {
    "A": "qwen", "B": "nemotron", "C": "ministral",
    "D": "kimik2", "E": "gpt", "F": "gemma"
}

# =========================================================
# USER AUTH & DATA LOAD
# =========================================================
if "username" not in st.session_state:
    st.title("Welcome")
    with st.form("login_gate"):
        user_input = st.text_input("Full Name")
        if st.form_submit_button("Sign In") and user_input:
            st.session_state.username = user_input.strip()
            st.rerun()
    st.stop()

@st.cache_data(show_spinner=False)
def load_and_group_data():
    # Read the master sheet to get the sentences to evaluate
    df = conn.read(worksheet_id=MASTER_SHEET_GID)
    if df is None or df.empty:
        raise ValueError("Master sheet is empty or not accessible")
    # Get unique list of incorrect sentences for navigation
    return df, df["incorrect"].unique().tolist()

try:
    master_df, unique_list = load_and_group_data()
    st.success("Master sheet loaded ✅")
except Exception as e:
    st.error(f"Load Error: {e}")
    st.stop()

# =========================================================
# HELPER FUNCTIONS
# =========================================================

def get_existing_rating(m_id, u_idx):
    """Checks if the current user has already rated this specific entry."""
    try:
        df = conn.read(worksheet=MODEL_TABS[m_id], ttl=0)
        if df is not None and not df.empty:
            match = df[(df["unique_set_index"].astype(str) == str(u_idx)) & 
                       (df["user"] == st.session_state.username)]
            if not match.empty:
                return int(match.iloc[0]["rating"])
    except: 
        pass
    return None

def save_all_ratings(u_idx, current_incorrect, versions, ratings_dict, manual_fix):
    """Saves ratings for all models and the manual user correction."""
    submission_uuid = str(uuid.uuid4())
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Update individual Model Tabs
    for m_id, rating in ratings_dict.items():
        m_row_data = versions[versions["id"] == m_id].iloc[0]
        
        # Ensure all data types are standard Python types (not NumPy) to avoid TypeErrors
        new_entry = pd.DataFrame([{
            "submission_id": submission_uuid,
            "user": str(st.session_state.username),
            "unique_set_index": int(u_idx),
            "incorrect": str(current_incorrect),
            "corrected": str(m_row_data["corrected"]),
            "rating": int(rating),
            "timestamp": ts,
        }])

        try:
            tab_name = MODEL_TABS[m_id]
            existing_df = conn.read(worksheet=tab_name, ttl=0)
            
            if existing_df is not None and not existing_df.empty:
                # Remove previous entry by same user for this index to allow updates
                mask = (existing_df["unique_set_index"].astype(str) == str(u_idx)) & \
                       (existing_df["user"] == st.session_state.username)
                existing_df = existing_df[~mask]
                updated_df = pd.concat([existing_df, new_entry], ignore_index=True)
            else:
                updated_df = new_entry
            
            # Use .fillna("") because GSheets API rejects NaN values
            conn.update(worksheet=tab_name, data=updated_df.fillna(""))
            time.sleep(0.5) # Anti-throttle pause for Google API limits
        except Exception as e:
            st.error(f"Tab '{tab_name}' Update Failed: {e}")

    # 2. Update Manual Correction Tab
    if manual_fix.strip():
        user_entry = pd.DataFrame([{
            "submission_id": submission_uuid,
            "user": str(st.session_state.username),
            "unique_set_index": int(u_idx),
            "incorrect": str(current_incorrect),
            "user_corrected": str(manual_fix),
        }])
        try:
            df_user = conn.read(worksheet=USER_CORRECTION_TAB, ttl=0)
            if df_user is not None and not df_user.empty:
                mask = (df_user["unique_set_index"].astype(str) == str(u_idx)) & \
                       (df_user["user"] == st.session_state.username)
                df_user = df_user[~mask]
                updated_user_df = pd.concat([df_user, user_entry], ignore_index=True)
            else:
                updated_user_df = user_entry
            conn.update(worksheet=USER_CORRECTION_TAB, data=updated_user_df.fillna(""))
        except Exception as e:
            st.error(f"Manual Correction Tab Update Failed: {e}")

# =========================================================
# MAIN UI
# =========================================================

if "u_index" not in st.session_state:
    st.session_state.u_index = 0

if st.session_state.u_index >= len(unique_list):
    st.success("All evaluations completed. Thank you!")
    st.stop()

current_incorrect = unique_list[st.session_state.u_index]
versions = master_df[master_df["incorrect"] == current_incorrect]

st.title("Evaluation Workspace")

# Navigation Row
col_prev, col_mid, col_next = st.columns([1, 8, 1])
with col_prev:
    if st.button("← Previous") and st.session_state.u_index > 0:
        st.session_state.u_index -= 1
        st.rerun()

with col_mid:
    st.write(f"<center>Entry <b>{st.session_state.u_index + 1}</b> of {len(unique_list)}</center>", unsafe_allow_html=True)
    st.progress((st.session_state.u_index + 1) / len(unique_list))

with col_next:
    if st.button("Next →") and st.session_state.u_index < len(unique_list) - 1:
        st.session_state.u_index += 1
        st.rerun()

st.subheader("Original Text")
st.markdown(f"> {current_incorrect}")
st.divider()

# Model Outputs and Ratings
current_ratings = {}
model_ids = sorted(MODEL_TABS.keys())

# Display in a 3-column grid
for row_idx in range(0, len(model_ids), 3):
    cols = st.columns(3)
    for i, m_id in enumerate(model_ids[row_idx:row_idx+3]):
        with cols[i]:
            m_row = versions[versions["id"] == m_id]
            if not m_row.empty:
                st.markdown(f"**Model: {MODEL_MAP[m_id].capitalize()}**")
                st.info(m_row.iloc[0]["corrected"])
                
                # Fetch existing rating for the UI default
                existing_val = get_existing_rating(m_id, st.session_state.u_index)
                
                current_ratings[m_id] = st.radio(
                    f"Rating for {m_id}",
                    options=list(range(1, 11)),
                    index=existing_val - 1 if existing_val else None,
                    horizontal=True,
                    key=f"rad_{m_id}_{st.session_state.u_index}",
                    label_visibility="collapsed"
                )

st.divider()
st.subheader("Reference Correction")
manual_fix_input = st.text_area("Provide the ideal correction here:", key=f"manual_area_{st.session_state.u_index}")

# Validation: Check if all models are rated
all_rated = all(current_ratings.get(m) is not None for m in model_ids)

if st.button("Save & Continue", type="primary", use_container_width=True, disabled=not all_rated):
    with st.spinner("Writing to Google Sheets..."):
        save_all_ratings(
            st.session_state.u_index,
            current_incorrect,
            versions,
            current_ratings,
            manual_fix_input
        )
        st.session_state.u_index += 1
        st.rerun()
