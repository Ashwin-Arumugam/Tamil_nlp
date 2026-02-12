import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
import uuid
import time  # Added for rate-limit management

# =========================================================
# CONFIGURATION
# =========================================================

st.set_page_config(page_title="Model Comparison Tool", layout="wide")

conn = st.connection("gsheets", type=GSheetsConnection)

# MASTER SHEET GID
MASTER_SHEET_GID = 1905633307

# MODEL TAB GIDs
MODEL_SHEET_GIDS = {
    "A": 364113859,
    "B": 952136825,
    "C": 656105801,
    "D": 1630302691,
    "E": 803791042,
    "F": 141437423,
}

MODEL_MAP = {
    "A": "qwen",
    "B": "nemotron",
    "C": "ministral",
    "D": "kimik2",
    "E": "gpt",
    "F": "gemma"
}

# USER CORRECTION TAB GID
USER_CORRECTION_GID = 677241304

# =========================================================
# USER AUTH
# =========================================================

if "username" not in st.session_state:
    st.title("Welcome")
    st.markdown("Please sign in to begin evaluation.")
    with st.form("login_gate"):
        user_input = st.text_input("Full Name")
        if st.form_submit_button("Sign In") and user_input:
            st.session_state.username = user_input.strip()
            st.rerun()
    st.stop()

# =========================================================
# DATA LOADING (Optimized to prevent 429)
# =========================================================

@st.cache_data(show_spinner=False, ttl=300) # Cache for 5 mins to reduce reads
def load_master_data():
    df = conn.read(worksheet_id=MASTER_SHEET_GID)
    if df is None or df.empty:
        raise ValueError("Master sheet is empty or not accessible")
    df = df.dropna(how="all")
    unique_sentences = df["incorrect"].unique().tolist()
    return df, unique_sentences

# Load all model data into memory once to prevent repeated reads in the loop
def load_all_existing_data():
    if "existing_data" not in st.session_state:
        st.session_state.existing_data = {}
        for m_id, gid in MODEL_SHEET_GIDS.items():
            try:
                st.session_state.existing_data[m_id] = conn.read(worksheet_id=gid, ttl=60)
            except:
                st.session_state.existing_data[m_id] = pd.DataFrame()

try:
    master_df, unique_list = load_master_data()
    load_all_existing_data()
    st.success("Data synced successfully ✅")
except Exception as e:
    st.error("Error connecting to Google Sheets. Please wait a minute and refresh.")
    st.stop()

# =========================================================
# HELPER FUNCTIONS
# =========================================================

def get_existing_rating(m_id, u_idx):
    """Checks the locally cached data instead of calling the API every frame."""
    df_check = st.session_state.existing_data.get(m_id)
    if df_check is not None and not df_check.empty:
        if "unique_set_index" in df_check.columns:
            match = df_check[
                (df_check["unique_set_index"].astype(str) == str(u_idx))
                & (df_check["user"] == st.session_state.username)
            ]
            if not match.empty:
                return int(match.iloc[0]["rating"])
    return None

def save_all_ratings(u_idx, current_incorrect, versions, ratings_dict, manual_fix):
    submission_uuid = str(uuid.uuid4())
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Update Model Ratings
    for m_id, rating in ratings_dict.items():
        m_row_data = versions[versions["id"] == m_id].iloc[0]

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
            # We must read right before write to ensure no data loss, but we add a pause
            time.sleep(0.5) # Short sleep to avoid hitting 60 req/min
            existing_df = conn.read(worksheet_id=MODEL_SHEET_GIDS[m_id], ttl=0)
            
            if existing_df is not None and not existing_df.empty:
                mask = (existing_df["unique_set_index"].astype(str) == str(u_idx)) & \
                       (existing_df["user"] == st.session_state.username)
                existing_df = existing_df[~mask]
                updated_df = pd.concat([existing_df, new_entry], ignore_index=True)
            else:
                updated_df = new_entry
            
            updated_df = updated_df.fillna("")
            conn.update(worksheet_id=MODEL_SHEET_GIDS[m_id], data=updated_df)
            
            # Update local cache so the UI updates immediately
            st.session_state.existing_data[m_id] = updated_df

        except Exception as e:
            st.error(f"Failed to update sheet for Model {m_id}: {e}")

    # 2. Save User Manual Correction
    if manual_fix.strip():
        user_entry = pd.DataFrame([{
            "submission_id": submission_uuid,
            "user": str(st.session_state.username),
            "unique_set_index": int(u_idx),
            "incorrect": str(current_incorrect),
            "user_corrected": str(manual_fix),
        }])

        try:
            time.sleep(0.5)
            df_user = conn.read(worksheet_id=USER_CORRECTION_GID, ttl=0)
            if df_user is not None and not df_user.empty:
                mask = (df_user["unique_set_index"].astype(str) == str(u_idx)) & \
                       (df_user["user"] == st.session_state.username)
                df_user = df_user[~mask]
                updated_user_df = pd.concat([df_user, user_entry], ignore_index=True)
            else:
                updated_user_df = user_entry
            
            updated_user_df = updated_user_df.fillna("")
            conn.update(worksheet_id=USER_CORRECTION_GID, data=updated_user_df)
        except Exception as e:
            st.error(f"Failed to update manual correction sheet: {e}")

# =========================================================
# SESSION STATE
# =========================================================

if "u_index" not in st.session_state:
    st.session_state.u_index = 0

# =========================================================
# MAIN UI
# =========================================================

if not unique_list:
    st.info("No data loaded.")
    st.stop()

if st.session_state.u_index >= len(unique_list):
    st.success("All evaluations completed. Thank you.")
    if st.button("Start Over"):
        st.session_state.u_index = 0
        st.rerun()
    st.stop()

current_incorrect = unique_list[st.session_state.u_index]
versions = master_df[master_df["incorrect"] == current_incorrect]

st.title("Evaluation Workspace")

col_prev, col_mid, col_next = st.columns([1, 8, 1])

with col_prev:
    if st.button("Previous") and st.session_state.u_index > 0:
        st.session_state.u_index -= 1
        st.rerun()

with col_mid:
    st.write(
        f"<center>Entry <b>{st.session_state.u_index + 1}</b> of {len(unique_list)}</center>",
        unsafe_allow_html=True,
    )
    st.progress((st.session_state.u_index + 1) / len(unique_list))

with col_next:
    if st.button("Next") and st.session_state.u_index < len(unique_list) - 1:
        st.session_state.u_index += 1
        st.rerun()

st.subheader("Original Text")
st.markdown(f"> {current_incorrect}")
st.divider()

current_ratings = {}
rating_options = list(range(1, 11))
model_ids = sorted(MODEL_MAP.keys())

# Display models in 2 rows of 3 columns
rows = [model_ids[:3], model_ids[3:]]
for row_ids in rows:
    cols = st.columns(3)
    for i, m_id in enumerate(row_ids):
        with cols[i]:
            m_row = versions[versions["id"] == m_id]
            if not m_row.empty:
                st.markdown(f"**{MODEL_MAP[m_id].capitalize()} output**")
                st.info(m_row.iloc[0]["corrected"])

                existing_val = get_existing_rating(m_id, st.session_state.u_index)

                # Reset radio selection if no existing value
                default_idx = rating_options.index(existing_val) if existing_val in rating_options else None

                current_ratings[m_id] = st.radio(
                    f"Rating for {m_id}",
                    options=rating_options,
                    index=default_idx,
                    horizontal=True,
                    key=f"rad_{m_id}_{st.session_state.u_index}",
                    label_visibility="collapsed",
                )

st.divider()
st.subheader("Reference Correction")

manual_fix = st.text_area(
    "Provide ideal correction:",
    key=f"manual_{st.session_state.u_index}",
)

all_rated = all(
    current_ratings.get(m) is not None for m in model_ids if m in current_ratings
)

if st.button(
    "Save and Continue",
    use_container_width=True,
    type="primary",
    disabled=not all_rated,
):
    with st.spinner("Saving results..."):
        save_all_ratings(
            st.session_state.u_index,
            current_incorrect,
            versions,
            current_ratings,
            manual_fix,
        )
        st.session_state.u_index += 1
        st.rerun()
