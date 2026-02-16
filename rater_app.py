import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import time

# =========================================================
# 1. CONFIGURATION
# =========================================================

st.set_page_config(page_title="Model Eval Tool", layout="wide")
conn = st.connection("gsheets", type=GSheetsConnection)

MASTER_SHEET_GID = 1905633307

# Maps Model IDs to Sheet GIDs
MODEL_SHEET_GIDS = {
    "A": 364113859,
    "B": 952136825,
    "C": 656105801,
    "D": 1630302691,
    "E": 803791042,
    "F": 141437423,
}

# Maps Model IDs to Tab Names
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
# 2. DATA LOADING & TYPE CLEANING
# =========================================================

if "username" not in st.session_state:
    st.title("Login")
    with st.form("login"):
        user = st.text_input("Username")
        if st.form_submit_button("Start") and user:
            st.session_state.username = user.strip()
            # Clear cache on login to force fresh data
            st.cache_data.clear()
            if "existing_data" in st.session_state:
                del st.session_state.existing_data
            st.rerun()
    st.stop()

@st.cache_data(show_spinner=False, ttl=600)
def load_master_data():
    """Loads the master sentences."""
    df = conn.read(worksheet_id=MASTER_SHEET_GID)
    if df is None or df.empty:
        st.error("Master sheet is empty or could not be read.")
        st.stop()
    df = df.dropna(how="all")
    unique_sentences = df["incorrect"].unique().tolist()
    return df, unique_sentences

def clean_data_types(df):
    """
    CRITICAL FIX: Ensures columns are the correct type for matching.
    Google Sheets often sends numbers as floats (8.0), breaking the UI.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    
    # Force submission_id to String for robust matching
    if "submission_id" in df.columns:
        df["submission_id"] = df["submission_id"].astype(str)
    
    # Force rating to Int (handle 8.0 -> 8)
    if "rating" in df.columns:
        df["rating"] = pd.to_numeric(df["rating"], errors='coerce').fillna(0).astype(int)
        
    return df

def sync_existing_ratings():
    """Reads all sheets to populate history."""
    if "existing_data" not in st.session_state:
        st.session_state.existing_data = {}
        
    for m_id, gid in MODEL_SHEET_GIDS.items():
        try:
            # ttl=0 Forces fresh read from Google
            df = conn.read(worksheet_id=gid, ttl=0)
            st.session_state.existing_data[m_id] = clean_data_types(df)
        except Exception:
            st.session_state.existing_data[m_id] = pd.DataFrame()
            
    # Load Corrections
    try:
        df_user = conn.read(worksheet_id=USER_CORRECTION_GID, ttl=0)
        # Clean submission_id for corrections too
        if not df_user.empty and "submission_id" in df_user.columns:
            df_user["submission_id"] = df_user["submission_id"].astype(str)
        st.session_state.existing_data["corrections"] = df_user
    except:
        st.session_state.existing_data["corrections"] = pd.DataFrame()

# Initial Load
with st.spinner("Syncing history..."):
    master_df, unique_list = load_master_data()
    # If we haven't loaded data yet, do it now
    if "existing_data" not in st.session_state or not st.session_state.existing_data:
        sync_existing_ratings()

# =========================================================
# 3. HELPER FUNCTIONS
# =========================================================

def get_nemotron_row_id(master_df, current_incorrect):
    mask = (master_df["incorrect"] == current_incorrect) & (master_df["id"] == "B")
    subset = master_df[mask]
    if not subset.empty:
        return str(subset.index[0] + 2) # Return as STRING
    return "Unknown"

def get_saved_rating(m_id, sub_id):
    """Retrieves rating ensuring it returns an INTEGER or None."""
    df = st.session_state.existing_data.get(m_id)
    if df is not None and not df.empty:
        if "submission_id" in df.columns and "user" in df.columns:
            # String comparison for ID
            mask = (df["submission_id"] == str(sub_id)) & \
                   (df["user"] == st.session_state.username)
            match = df[mask]
            if not match.empty:
                try:
                    val = int(match.iloc[0]["rating"])
                    # If rating is 0 (from error filling), return None
                    return val if val > 0 else None
                except:
                    return None
    return None

def safe_save_to_sheet(sheet_key, tab_name, new_entry_df, sub_id, gid):
    """
    Reads fresh data -> Removes OLD user entry -> Prepends NEW entry -> Saves.
    """
    try:
        # 1. FRESH READ (Strictly ttl=0)
        try:
            current_sheet_df = conn.read(worksheet_id=gid, ttl=0)
        except Exception as e:
            st.error(f"⚠️ Could not read {tab_name}. Aborting save to prevent data loss.")
            return False

        # 2. CLEAN TYPES
        current_sheet_df = clean_data_types(current_sheet_df)

        # 3. FILTER (Remove old entry for this user + sentence)
        if not current_sheet_df.empty:
            # Ensure columns exist
            if "submission_id" in current_sheet_df.columns and "user" in current_sheet_df.columns:
                mask = (current_sheet_df["submission_id"] == str(sub_id)) & \
                       (current_sheet_df["user"] == st.session_state.username)
                # Keep everything that is NOT the old entry
                current_sheet_df = current_sheet_df[~mask]

        # 4. PREPEND (New entry goes to top)
        updated_df = pd.concat([new_entry_df, current_sheet_df], ignore_index=True)

        # 5. WRITE
        conn.update(worksheet=tab_name, data=updated_df)
        
        # 6. UPDATE LOCAL STATE
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
                
                # --- PRE-FILL LOGIC ---
                # Check if we have a saved rating for this ID
                if key not in st.session_state:
                    saved_val = get_saved_rating(m_id, nem_row_id)
                    if saved_val:
                        # Set session state so the widget sees it
                        st.session_state[key] = saved_val

                # Render Widget
                st.pills("Rate", rating_options, key=key, label_visibility="collapsed")

st.divider()

# --- Manual Correction ---
correction_key = f"fix_{st.session_state.u_index}"
manual_fix = st.text_area("Correction (Optional):", key=correction_key)

# --- Save Button ---
if st.button("Save Ratings", type="primary", use_container_width=True):
    with st.spinner("Saving data..."):
        
        # 1. SAVE RATINGS
        for m_id in model_ids:
            val = st.session_state.get(f"pills_{m_id}_{st.session_state.u_index}")
            
            # If user selected a rating, save it
            if val is not None:
                new_entry = pd.DataFrame([{
                    "submission_id": str(nem_row_id),
                    "user": str(st.session_state.username),
                    "rating": int(val)
                }])
                
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
                "submission_id": str(nem_row_id),
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
    
    # Auto-Advance
    if st.session_state.u_index < len(unique_list) - 1:
        st.session_state.u_index += 1
        st.rerun()
