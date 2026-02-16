import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import time

# =========================================================
# 1. CONFIGURATION
# =========================================================

st.set_page_config(page_title="Model Eval Tool", layout="wide")
conn = st.connection("gsheets", type=GSheetsConnection)

# --- SHEET CONFIGURATION ---
MASTER_SHEET_GID = 1905633307

# Maps Model IDs (A-F) to their specific Sheet GIDs
MODEL_SHEET_GIDS = {
    "A": 364113859,
    "B": 952136825,
    "C": 656105801,
    "D": 1630302691,
    "E": 803791042,
    "F": 141437423,
}

# Maps Model IDs to Tab Names (for writing)
MODEL_TAB_NAMES = {
    "A": "qwen",
    "B": "nemotron",
    "C": "ministral",
    "D": "kimik2",
    "E": "gpt",
    "F": "gemma"
}

USER_CORRECTION_GID = 677241304
USER_CORRECTION_TAB_NAME = "user_corrections"

# =========================================================
# 2. DATA LOADING & STATE MANAGEMENT
# =========================================================

if "username" not in st.session_state:
    st.title("Login")
    with st.form("login"):
        user = st.text_input("Username")
        if st.form_submit_button("Start") and user:
            st.session_state.username = user.strip()
            # Clear any old data to force a fresh reload on login
            if "existing_data" in st.session_state:
                del st.session_state.existing_data
            st.rerun()
    st.stop()

@st.cache_data(show_spinner=False, ttl=600)
def load_master_data():
    """Loads the master sentences (read-only)."""
    df = conn.read(worksheet_id=MASTER_SHEET_GID)
    if df is None or df.empty:
        st.error("Master sheet is empty.")
        st.stop()
    df = df.dropna(how="all")
    unique_sentences = df["incorrect"].unique().tolist()
    return df, unique_sentences

def sync_existing_ratings():
    """
    Reads ALL rating sheets from GSheets into Session State.
    Uses ttl=0 to ensure we get the latest saved data (History).
    """
    if "existing_data" not in st.session_state:
        st.session_state.existing_data = {}
        
    # We iterate and load to ensure we have history for the UI
    for m_id, gid in MODEL_SHEET_GIDS.items():
        try:
            # ttl=0 is CRITICAL: It forces a fetch from Google, not cache.
            # This ensures 'Previous Responses' are actually seen.
            df = conn.read(worksheet_id=gid, ttl=0)
            st.session_state.existing_data[m_id] = df
        except:
            st.session_state.existing_data[m_id] = pd.DataFrame()
    
    # Load User Corrections
    try:
        df_user = conn.read(worksheet_id=USER_CORRECTION_GID, ttl=0)
        st.session_state.existing_data["corrections"] = df_user
    except:
        st.session_state.existing_data["corrections"] = pd.DataFrame()

# Load Data on App Start
with st.spinner("Syncing history..."):
    master_df, unique_list = load_master_data()
    # Only run full sync if we haven't loaded data yet
    if "existing_data" not in st.session_state or not st.session_state.existing_data:
        sync_existing_ratings()

# =========================================================
# 3. HELPER FUNCTIONS
# =========================================================

def get_nemotron_row_id(master_df, current_incorrect):
    mask = (master_df["incorrect"] == current_incorrect) & (master_df["id"] == "B")
    subset = master_df[mask]
    if not subset.empty:
        return subset.index[0] + 2
    return "Unknown"

def get_saved_rating(m_id, sub_id):
    """
    Checks session state to see if user previously rated this sentence.
    """
    df = st.session_state.existing_data.get(m_id)
    if df is not None and not df.empty:
        # Ensure columns exist
        if "submission_id" in df.columns and "user" in df.columns:
            # Filter for User + Submission ID
            mask = (df["submission_id"].astype(str) == str(sub_id)) & \
                   (df["user"] == st.session_state.username)
            match = df[mask]
            if not match.empty:
                try:
                    return int(match.iloc[0]["rating"])
                except:
                    return None
    return None

def get_saved_correction(sub_id):
    """Checks if user previously wrote a manual correction."""
    df = st.session_state.existing_data.get("corrections")
    if df is not None and not df.empty:
        if "submission_id" in df.columns and "user" in df.columns:
            mask = (df["submission_id"].astype(str) == str(sub_id)) & \
                   (df["user"] == st.session_state.username)
            match = df[mask]
            if not match.empty:
                try:
                    return str(match.iloc[0]["user_corrected"])
                except:
                    return ""
    return ""

def safe_save_to_sheet(sheet_key, tab_name, new_entry_df, sub_id, gid):
    """
    Safe Save Strategy:
    1. Read the specific sheet FRESH from Google (ttl=0).
    2. Filter out the current user's OLD entry for this specific sentence (Update).
    3. Append the NEW entry to the top.
    4. Write back.
    """
    try:
        # 1. Fresh Read (Crucial to prevent overwriting others)
        try:
            current_sheet_df = conn.read(worksheet_id=gid, ttl=0)
        except:
            current_sheet_df = pd.DataFrame()

        # Define Allowed Columns
        allowed_cols = ["submission_id", "user", "rating", "user_corrected"]
        
        # 2. Modify
        if current_sheet_df is not None and not current_sheet_df.empty:
            # Keep only valid columns
            valid_cols = [c for c in current_sheet_df.columns if c in allowed_cols]
            current_sheet_df = current_sheet_df[valid_cols]

            # Remove OLD entry for this specific user & sentence
            if "submission_id" in current_sheet_df.columns and "user" in current_sheet_df.columns:
                mask = (current_sheet_df["submission_id"].astype(str) == str(sub_id)) & \
                       (current_sheet_df["user"] == st.session_state.username)
                current_sheet_df = current_sheet_df[~mask]
            
            # 3. Stack: New Entry on Top, Old Data Below
            updated_df = pd.concat([new_entry_df, current_sheet_df], ignore_index=True)
        else:
            updated_df = new_entry_df

        # 4. Write Back
        conn.update(worksheet=tab_name, data=updated_df)
        
        # Update Session State so UI reflects change immediately
        st.session_state.existing_data[sheet_key] = updated_df
        return True
        
    except Exception as e:
        st.error(f"Error saving to {tab_name}: {e}")
        return False

# =========================================================
# 4. UI LAYOUT
# =========================================================

if "u_index" not in st.session_state:
    st.session_state.u_index = 0

if st.session_state.u_index >= len(unique_list):
    st.success("All done!")
    if st.button("Restart"):
        st.session_state.u_index = 0
        st.rerun()
    st.stop()

current_incorrect = unique_list[st.session_state.u_index]
versions = master_df[master_df["incorrect"] == current_incorrect]
nem_row_id = get_nemotron_row_id(master_df, current_incorrect)

# --- Header ---
st.markdown(f"### User: {st.session_state.username}")
st.progress((st.session_state.u_index + 1) / len(unique_list))

# --- Navigation ---
c1, c2, c3 = st.columns([1, 6, 1])
if c1.button("⬅️ Prev") and st.session_state.u_index > 0:
    st.session_state.u_index -= 1
    st.rerun()
c2.markdown(f"<center><b>Sentence {st.session_state.u_index + 1} (ID: {nem_row_id})</b></center>", unsafe_allow_html=True)
if c3.button("Next ➡️") and st.session_state.u_index < len(unique_list) - 1:
    st.session_state.u_index += 1
    st.rerun()

st.info(f"**Original:** {current_incorrect}")
st.divider()

# --- Ratings Grid ---
model_ids = sorted(MODEL_TAB_NAMES.keys())
rating_options = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

rows = [model_ids[:3], model_ids[3:]]
for row_ids in rows:
    cols = st.columns(3)
    for i, m_id in enumerate(row_ids):
        with cols[i]:
            m_row = versions[versions["id"] == m_id]
            if not m_row.empty:
                st.markdown(f"**{MODEL_TAB_NAMES[m_id].capitalize()}**")
                st.success(m_row.iloc[0]["corrected"])
                
                key = f"pills_{m_id}_{st.session_state.u_index}"
                
                # PRE-FILL LOGIC (Shows previous response)
                # We check st.session_state first. If key not there, check loaded data.
                if key not in st.session_state:
                    saved_val = get_saved_rating(m_id, nem_row_id)
                    if saved_val:
                        st.session_state[key] = saved_val
                
                st.pills("Rate", rating_options, key=key, label_visibility="collapsed")

st.divider()

# --- Manual Correction ---
correction_key = f"fix_{st.session_state.u_index}"
# Pre-fill correction if exists
if correction_key not in st.session_state:
    saved_corr = get_saved_correction(nem_row_id)
    if saved_corr:
        st.session_state[correction_key] = saved_corr

manual_fix = st.text_area("Correction (Optional):", key=correction_key)

# --- Save Button ---
if st.button("Save Ratings", type="primary", use_container_width=True):
    with st.spinner("Saving data..."):
        
        # 1. SAVE RATINGS
        for m_id in model_ids:
            val = st.session_state.get(f"pills_{m_id}_{st.session_state.u_index}")
            if val is not None:
                new_entry = pd.DataFrame([{
                    "submission_id": int(nem_row_id) if nem_row_id != "Unknown" else 0,
                    "user": str(st.session_state.username),
                    "rating": int(val)
                }])
                
                # Use the SAFE save function
                safe_save_to_sheet(
                    m_id, 
                    MODEL_TAB_NAMES[m_id], 
                    new_entry, 
                    nem_row_id, 
                    MODEL_SHEET_GIDS[m_id]
                )
        
        # 2. SAVE MANUAL FIX
        if manual_fix:
            user_entry = pd.DataFrame([{
                "submission_id": int(nem_row_id) if nem_row_id != "Unknown" else 0,
                "user": str(st.session_state.username),
                "user_corrected": str(manual_fix)
            }])
            safe_save_to_sheet(
                "corrections", 
                USER_CORRECTION_TAB_NAME, 
                user_entry, 
                nem_row_id, 
                USER_CORRECTION_GID
            )

    st.success("Saved!")
    time.sleep(0.5)
    if st.session_state.u_index < len(unique_list) - 1:
        st.session_state.u_index += 1
        st.rerun()
