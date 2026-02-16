import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
import time

# =========================================================
# 1. CONFIGURATION & SETUP
# =========================================================

st.set_page_config(page_title="Model Eval Tool", layout="wide")

# Connect to Google Sheets
conn = st.connection("gsheets", type=GSheetsConnection)

# --- CONSTANTS ---
# 1. Master Data Sheet (Where we read sentences from)
MASTER_SHEET_GID = 1905633307

# 2. Model Output Sheets (Where we read/write model data)
# Keys (A-F) map to your specific Sheet GIDs
MODEL_SHEET_GIDS = {
    "A": 364113859,
    "B": 952136825,
    "C": 656105801,
    "D": 1630302691,
    "E": 803791042,
    "F": 141437423,
}

# 3. Model Tab Names (Exact names of tabs in Google Sheets)
MODEL_TAB_NAMES = {
    "A": "qwen",
    "B": "nemotron",
    "C": "ministral",
    "D": "kimik2",
    "E": "gpt",
    "F": "gemma"
}

# 4. User Corrections Sheet
USER_CORRECTION_GID = 677241304
USER_CORRECTION_TAB_NAME = "user_corrections"

# =========================================================
# 2. USER AUTHENTICATION
# =========================================================

if "username" not in st.session_state:
    st.title("🛡️ Evaluation Login")
    with st.form("login_gate"):
        user_input = st.text_input("Enter your Name or ID:")
        if st.form_submit_button("Start Evaluation") and user_input:
            st.session_state.username = user_input.strip()
            st.rerun()
    st.stop()

# =========================================================
# 3. DATA LOADING FUNCTIONS
# =========================================================

@st.cache_data(show_spinner=False, ttl=600)
def load_master_data():
    """Loads the source sentences and model outputs."""
    try:
        df = conn.read(worksheet_id=MASTER_SHEET_GID)
        if df is None or df.empty:
            st.error("Master sheet is empty.")
            st.stop()
        
        # Clean empty rows
        df = df.dropna(how="all")
        
        # Get list of unique sentences to iterate through
        unique_sentences = df["incorrect"].unique().tolist()
        return df, unique_sentences
    except Exception as e:
        st.error(f"Failed to load Master Sheet: {e}")
        st.stop()

def load_existing_ratings():
    """
    Loads current ratings from all sheets into session state.
    This allows us to 'remember' what you rated previously.
    """
    if "existing_data" not in st.session_state:
        st.session_state.existing_data = {}
        
        # Load Model Sheets
        for m_id, gid in MODEL_SHEET_GIDS.items():
            try:
                # ttl=0 ensures we get the latest data on startup
                df = conn.read(worksheet_id=gid, ttl=0)
                st.session_state.existing_data[m_id] = df
            except:
                st.session_state.existing_data[m_id] = pd.DataFrame()
        
        # Load User Corrections Sheet
        try:
            df_user = conn.read(worksheet_id=USER_CORRECTION_GID, ttl=0)
            st.session_state.existing_data["corrections"] = df_user
        except:
            st.session_state.existing_data["corrections"] = pd.DataFrame()

# Load Data on App Start
with st.spinner("Syncing with Google Sheets..."):
    master_df, unique_list = load_master_data()
    load_existing_ratings()

# =========================================================
# 4. HELPER LOGIC
# =========================================================

def get_nemotron_row_id(master_df, current_incorrect):
    """
    Calculates the Row ID based on Model B (Nemotron).
    Formula: Excel Row = Pandas Index + 2 (Header + 0-index)
    """
    mask = (master_df["incorrect"] == current_incorrect) & (master_df["id"] == "B")
    subset = master_df[mask]
    if not subset.empty:
        return subset.index[0] + 2
    return "Unknown"

def get_saved_rating(m_id, u_idx):
    """Retrieves a saved rating from session state for pre-filling the UI."""
    df = st.session_state.existing_data.get(m_id)
    if df is not None and not df.empty:
        # Check if columns exist
        if "unique_set_index" in df.columns and "user" in df.columns:
            # Filter for current User AND current Sentence Index
            mask = (df["unique_set_index"].astype(str) == str(u_idx)) & \
                   (df["user"] == st.session_state.username)
            match = df[mask]
            if not match.empty:
                try:
                    return int(match.iloc[0]["rating"])
                except:
                    return None
    return None

def save_entry_to_sheet(sheet_key, tab_name, new_entry_df, u_idx):
    """
    Generic function to Upsert (Update or Insert) data to GSheets.
    Prevents duplicate rows for the same user+sentence.
    """
    try:
        # Get current data from memory
        existing_df = st.session_state.existing_data.get(sheet_key)
        
        if existing_df is not None and not existing_df.empty:
            # 1. Identify if row exists
            mask = (existing_df["unique_set_index"].astype(str) == str(u_idx)) & \
                   (existing_df["user"] == st.session_state.username)
            
            # 2. If exists, delete old row. If not, keep all.
            if mask.any():
                existing_df = existing_df[~mask]
            
            # 3. Append new entry
            updated_df = pd.concat([existing_df, new_entry_df], ignore_index=True)
        else:
            updated_df = new_entry_df

        # 4. Write to Google Sheets
        conn.update(worksheet=tab_name, data=updated_df)
        
        # 5. Update Memory
        st.session_state.existing_data[sheet_key] = updated_df
        return True
        
    except Exception as e:
        st.error(f"Error saving to {tab_name}: {e}")
        return False

# =========================================================
# 5. MAIN UI LAYOUT
# =========================================================

if "u_index" not in st.session_state:
    st.session_state.u_index = 0

# Check bounds
if st.session_state.u_index >= len(unique_list):
    st.success("🎉 You have completed all evaluations!")
    if st.button("Start Over"):
        st.session_state.u_index = 0
        st.rerun()
    st.stop()

# Get Current Sentence Data
current_incorrect = unique_list[st.session_state.u_index]
versions = master_df[master_df["incorrect"] == current_incorrect]

# --- Header & Progress ---
st.markdown(f"### Evaluation Portal | User: **{st.session_state.username}**")
st.progress((st.session_state.u_index + 1) / len(unique_list))

# --- Navigation Bar ---
c1, c2, c3 = st.columns([1, 6, 1])
with c1:
    if st.button("⬅️ Previous") and st.session_state.u_index > 0:
        st.session_state.u_index -= 1
        st.rerun()
with c2:
    st.markdown(f"<div style='text-align: center; font-weight: bold;'>Sentence {st.session_state.u_index + 1} of {len(unique_list)}</div>", unsafe_allow_html=True)
with c3:
    if st.button("Next ➡️") and st.session_state.u_index < len(unique_list) - 1:
        st.session_state.u_index += 1
        st.rerun()

# --- Content Display ---
st.info(f"**Original Text:** {current_incorrect}")
st.divider()

# --- Rating Grid ---
model_ids = sorted(MODEL_TAB_NAMES.keys())
rating_options = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

# Display in 2 rows of 3 columns
rows = [model_ids[:3], model_ids[3:]]

for row_ids in rows:
    cols = st.columns(3)
    for i, m_id in enumerate(row_ids):
        with cols[i]:
            m_row = versions[versions["id"] == m_id]
            if not m_row.empty:
                # Header
                st.markdown(f"**Model {m_id}** ({MODEL_TAB_NAMES[m_id]})")
                
                # Model Output Text
                st.success(m_row.iloc[0]["corrected"])
                
                # Dynamic Key for Widgets
                widget_key = f"pills_{m_id}_{st.session_state.u_index}"
                
                # Pre-fill Logic
                if widget_key not in st.session_state:
                    saved_val = get_saved_rating(m_id, st.session_state.u_index)
                    if saved_val:
                        st.session_state[widget_key] = saved_val
                
                # 1-10 Input Widget
                st.pills(
                    "Rating",
                    options=rating_options,
                    key=widget_key,
                    label_visibility="collapsed"
                )

st.divider()

# --- Manual Correction ---
correction_key = f"correction_{st.session_state.u_index}"
manual_fix = st.text_area("Suggest a better correction (Optional):", key=correction_key)

# --- Submit Logic ---
if st.button("💾 Save & Next", type="primary", use_container_width=True):
    
    with st.spinner("Saving data..."):
        # 1. Prepare Metadata
        nem_row = get_nemotron_row_id(master_df, current_incorrect)
        custom_sub_id = f"{nem_row}_{st.session_state.u_index}"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 2. Loop through models and save
        for m_id in model_ids:
            # Get value from widget state
            rating_val = st.session_state.get(f"pills_{m_id}_{st.session_state.u_index}")
            
            if rating_val is not None:
                new_entry = pd.DataFrame([{
                    "submission_id": custom_sub_id,
                    "user": st.session_state.username,
                    "unique_set_index": int(st.session_state.u_index),
                    "rating": int(rating_val),
                    "timestamp": ts
                }])
                
                # Save to specific model sheet
                save_entry_to_sheet(m_id, MODEL_TAB_NAMES[m_id], new_entry, st.session_state.u_index)

        # 3. Save Manual Correction (if exists)
        if manual_fix:
            user_entry = pd.DataFrame([{
                "submission_id": custom_sub_id,
                "user": st.session_state.username,
                "unique_set_index": int(st.session_state.u_index),
                "user_corrected": manual_fix,
                "timestamp": ts
            }])
            save_entry_to_sheet("corrections", USER_CORRECTION_TAB_NAME, user_entry, st.session_state.u_index)

    st.success("Saved successfully!")
    time.sleep(0.5)
    
    # Auto-Advance
    if st.session_state.u_index < len(unique_list) - 1:
        st.session_state.u_index += 1
        st.rerun()
    else:
        st.balloons()
        st.success("All done!")
