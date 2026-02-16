import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
import time

# =========================================================
# CONFIGURATION
# =========================================================

st.set_page_config(page_title="Model Comparison Tool", layout="wide")

conn = st.connection("gsheets", type=GSheetsConnection)

# MASTER SHEET GID (Reading)
MASTER_SHEET_GID = 1905633307

# MODEL GIDs (Used for Reading)
MODEL_SHEET_GIDS = {
    "A": 364113859,
    "B": 952136825,
    "C": 656105801,
    "D": 1630302691,
    "E": 803791042,
    "F": 141437423,
}

# MODEL TAB NAMES (Writing targets)
MODEL_TAB_NAMES = {
    "A": "qwen",
    "B": "nemotron",
    "C": "ministral",
    "D": "kimik2",
    "E": "gpt",
    "F": "gemma"
}

# USER CORRECTION
USER_CORRECTION_GID = 677241304
USER_CORRECTION_TAB_NAME = "user_corrections"

# =========================================================
# USER AUTH
# =========================================================

if "username" not in st.session_state:
    st.title("Welcome")
    with st.form("login_gate"):
        user_input = st.text_input("Enter your unique ID / Name")
        if st.form_submit_button("Start Labelling") and user_input:
            st.session_state.username = user_input.strip()
            st.rerun()
    st.stop()

# =========================================================
# DATA LOADING
# =========================================================

@st.cache_data(show_spinner=False, ttl=600)
def load_master_data():
    # Read the master sheet
    df = conn.read(worksheet_id=MASTER_SHEET_GID)
    if df is None or df.empty:
        raise ValueError("Master sheet is empty")
    
    # Clean and get unique sentences (based on incorrect column)
    df = df.dropna(how="all")
    unique_sentences = df["incorrect"].unique().tolist()
    
    return df, unique_sentences

# Load existing ratings into session state to allow "Memory"
def load_all_existing_data():
    if "existing_data" not in st.session_state:
        st.session_state.existing_data = {}
        for m_id, gid in MODEL_SHEET_GIDS.items():
            try:
                # We use ttl=0 here to ensure we get the absolute latest when app starts
                df = conn.read(worksheet_id=gid, ttl=0)
                st.session_state.existing_data[m_id] = df
            except:
                st.session_state.existing_data[m_id] = pd.DataFrame()

try:
    master_df, unique_list = load_master_data()
    load_all_existing_data()
except Exception as e:
    st.error(f"Connection Error: {e}")
    st.stop()

# =========================================================
# LOGIC FUNCTIONS
# =========================================================

def get_nemotron_row_id(master_df, current_incorrect):
    """
    Finds the row index of Model B (Nemotron) for the current sentence.
    This creates the custom Submission ID part.
    """
    # Filter for the specific sentence and Model B
    mask = (master_df["incorrect"] == current_incorrect) & (master_df["id"] == "B")
    subset = master_df[mask]
    
    if not subset.empty:
        # Return the actual DataFrame index (row number) + 2 (header offset)
        return subset.index[0] + 2 
    return "Unknown"

def get_existing_rating(m_id, u_idx):
    """Check session state for a previously saved rating"""
    df_check = st.session_state.existing_data.get(m_id)
    
    if df_check is not None and not df_check.empty:
        # Ensure columns exist before filtering
        if "unique_set_index" in df_check.columns and "user" in df_check.columns:
            # Look for matching Index AND User
            match = df_check[
                (df_check["unique_set_index"].astype(str) == str(u_idx))
                & (df_check["user"] == st.session_state.username)
            ]
            if not match.empty:
                try:
                    return int(match.iloc[0]["rating"])
                except:
                    return None
    return None

def save_ratings(u_idx, current_incorrect, versions, ratings_dict, manual_fix):
    
    # 1. Generate the Custom Submission ID
    # logic: NemotronRow_SentenceIndex
    nem_row = get_nemotron_row_id(master_df, current_incorrect)
    custom_sub_id = f"{nem_row}_{u_idx}"
    
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 2. Iterate through each model and save ONLY specific columns
    for m_id, rating in ratings_dict.items():
        
        # Define the EXACT columns you want to write
        new_row_data = {
            "submission_id": custom_sub_id,
            "user": str(st.session_state.username),
            "unique_set_index": int(u_idx),
            "rating": int(rating),
            "timestamp": ts
        }
        
        new_entry = pd.DataFrame([new_row_data])

        try:
            tab_name = MODEL_TAB_NAMES[m_id]
            
            # Get current data from session state (fastest) or fetch fresh
            existing_df = st.session_state.existing_data.get(m_id)
            
            if existing_df is not None and not existing_df.empty:
                # Check if this user already rated this sentence
                # We create a mask to find the specific row
                mask = (existing_df["unique_set_index"].astype(str) == str(u_idx)) & \
                       (existing_df["user"] == st.session_state.username)
                
                if mask.any():
                    # UPDATE EXISTING ROW: Drop the old one, append the new one
                    # This prevents "output at the end" duplication
                    existing_df = existing_df[~mask]
                    updated_df = pd.concat([existing_df, new_entry], ignore_index=True)
                else:
                    # APPEND NEW ROW
                    updated_df = pd.concat([existing_df, new_entry], ignore_index=True)
            else:
                updated_df = new_entry
            
            # Write to Google Sheets
            conn.update(worksheet=tab_name, data=updated_df)
            
            # CRITICAL: Update Session State immediately so UI reflects the save
            st.session_state.existing_data[m_id] = updated_df

        except Exception as e:
            st.error(f"Failed to save Model {m_id}: {e}")

    # 3. Handle Manual Corrections (Optional)
    if manual_fix:
        # User corrections might need different columns, adjust as needed
        user_row_data = {
             "submission_id": custom_sub_id,
             "user": str(st.session_state.username),
             "unique_set_index": int(u_idx),
             "user_corrected": manual_fix,
             "timestamp": ts
        }
        user_entry = pd.DataFrame([user_row_data])
        
        # Similar Update logic for corrections sheet
        try:
             # Fetch fresh just to be safe for corrections
            df_user = conn.read(worksheet=USER_CORRECTION_TAB_NAME, ttl=0)
            
            if df_user is not None and not df_user.empty:
                mask = (df_user["unique_set_index"].astype(str) == str(u_idx)) & \
                       (df_user["user"] == st.session_state.username)
                df_user = df_user[~mask]
                updated_user_df = pd.concat([df_user, user_entry], ignore_index=True)
            else:
                updated_user_df = user_entry
                
            conn.update(worksheet=USER_CORRECTION_TAB_NAME, data=updated_user_df)
            
        except Exception as e:
            st.error(f"Failed to save correction: {e}")

# =========================================================
# UI LAYOUT
# =========================================================

if "u_index" not in st.session_state:
    st.session_state.u_index = 0

current_incorrect = unique_list[st.session_state.u_index]
versions = master_df[master_df["incorrect"] == current_incorrect]

st.title("Evaluation Workspace")
st.progress((st.session_state.u_index + 1) / len(unique_list))

# Navigation
c1, c2, c3 = st.columns([1, 6, 1])
if c1.button("⬅️ Previous") and st.session_state.u_index > 0:
    st.session_state.u_index -= 1
    st.rerun()

c2.markdown(f"<h4 style='text-align: center'>Sentence {st.session_state.u_index + 1}</h4>", unsafe_allow_html=True)

if c3.button("Next ➡️") and st.session_state.u_index < len(unique_list) - 1:
    st.session_state.u_index += 1
    st.rerun()

st.info(f"**Original:** {current_incorrect}")

# Rating Form
with st.form(key=f"rating_form_{st.session_state.u_index}"):
    current_ratings = {}
    model_ids = sorted(MODEL_TAB_NAMES.keys())
    
    # Display logic (Grid of models)
    rows = [model_ids[:3], model_ids[3:]]
    for row_ids in rows:
        cols = st.columns(3)
        for i, m_id in enumerate(row_ids):
            with cols[i]:
                m_row = versions[versions["id"] == m_id]
                if not m_row.empty:
                    st.markdown(f"**Model {m_id} ({MODEL_TAB_NAMES[m_id]})**")
                    st.success(m_row.iloc[0]["corrected"])
                    
                    # Pre-fill if exists
                    existing_val = get_existing_rating(m_id, st.session_state.u_index)
                    
                    current_ratings[m_id] = st.slider(
                        f"Rate {m_id}", 1, 10, 
                        value=existing_val if existing_val else 5,
                        key=f"slider_{m_id}_{st.session_state.u_index}"
                    )

    st.divider()
    manual_fix = st.text_area("Suggested Correction (Optional):")
    
    # Submit Button
    submit = st.form_submit_button("Save Ratings", type="primary", use_container_width=True)

if submit:
    with st.spinner("Saving to Google Sheets..."):
        save_ratings(st.session_state.u_index, current_incorrect, versions, current_ratings, manual_fix)
    
    st.success("Saved!")
    time.sleep(0.5) # Brief pause to show success
    
    # Auto-advance
    if st.session_state.u_index < len(unique_list) - 1:
        st.session_state.u_index += 1
        st.rerun()
