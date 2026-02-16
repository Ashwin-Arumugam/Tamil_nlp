import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
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
# 2. DATA LOADING
# =========================================================

if "username" not in st.session_state:
    st.title("Login")
    with st.form("login"):
        user = st.text_input("Username")
        if st.form_submit_button("Start") and user:
            st.session_state.username = user.strip()
            st.rerun()
    st.stop()

@st.cache_data(show_spinner=False, ttl=600)
def load_master_data():
    # Read strictly what is needed
    df = conn.read(worksheet_id=MASTER_SHEET_GID)
    if df is None or df.empty:
        st.error("Master sheet is empty.")
        st.stop()
    df = df.dropna(how="all")
    unique_sentences = df["incorrect"].unique().tolist()
    return df, unique_sentences

def load_existing_ratings():
    if "existing_data" not in st.session_state:
        st.session_state.existing_data = {}
        # Load Model Sheets
        for m_id, gid in MODEL_SHEET_GIDS.items():
            try:
                df = conn.read(worksheet_id=gid, ttl=0)
                # If the read dataframe has extra columns from a previous bad save, 
                # we don't worry about them here, but we will strip them before saving back.
                st.session_state.existing_data[m_id] = df
            except:
                st.session_state.existing_data[m_id] = pd.DataFrame()
        
        # Load User Corrections
        try:
            df_user = conn.read(worksheet_id=USER_CORRECTION_GID, ttl=0)
            st.session_state.existing_data["corrections"] = df_user
        except:
            st.session_state.existing_data["corrections"] = pd.DataFrame()

with st.spinner("Loading data..."):
    master_df, unique_list = load_master_data()
    load_existing_ratings()

# =========================================================
# 3. HELPER FUNCTIONS
# =========================================================

def get_nemotron_row_id(master_df, current_incorrect):
    """
    Finds the row number of the 'Nemotron' (id=B) version of this sentence.
    This serves as the unique 'submission_id' for the whole set.
    """
    mask = (master_df["incorrect"] == current_incorrect) & (master_df["id"] == "B")
    subset = master_df[mask]
    if not subset.empty:
        # Returns Excel Row Number (Index + 2)
        return subset.index[0] + 2
    return "Unknown"

def get_saved_rating(m_id, u_idx):
    df = st.session_state.existing_data.get(m_id)
    if df is not None and not df.empty:
        if "unique_set_index" in df.columns and "user" in df.columns:
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
    Upserts data while STRICTLY enforcing column schema.
    """
    try:
        existing_df = st.session_state.existing_data.get(sheet_key)
        
        # 1. CLEAN EXISTING DATA (Safety Step)
        # If existing data somehow got polluted with 'incorrect' columns, ignore them
        allowed_cols = ["submission_id", "user", "unique_set_index", "rating", "timestamp", "user_corrected"]
        
        if existing_df is not None and not existing_df.empty:
            # Filter existing DF to only keep relevant columns if they exist
            valid_existing_cols = [c for c in existing_df.columns if c in allowed_cols]
            existing_df = existing_df[valid_existing_cols]

            # Remove old entry for this user/sentence
            if "unique_set_index" in existing_df.columns and "user" in existing_df.columns:
                mask = (existing_df["unique_set_index"].astype(str) == str(u_idx)) & \
                       (existing_df["user"] == st.session_state.username)
                existing_df = existing_df[~mask]
            
            # Combine
            updated_df = pd.concat([existing_df, new_entry_df], ignore_index=True)
        else:
            updated_df = new_entry_df

        # 2. WRITE TO SHEET
        conn.update(worksheet=tab_name, data=updated_df)
        
        # 3. UPDATE SESSION STATE
        st.session_state.existing_data[sheet_key] = updated_df
        return True
        
    except Exception as e:
        st.error(f"Error saving to {tab_name}: {e}")
        return False

# =========================================================
# 4. UI
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

st.markdown(f"### User: {st.session_state.username}")
st.progress((st.session_state.u_index + 1) / len(unique_list))

# Navigation
c1, c2, c3 = st.columns([1, 6, 1])
if c1.button("⬅️ Prev") and st.session_state.u_index > 0:
    st.session_state.u_index -= 1
    st.rerun()
c2.markdown(f"<center><b>Sentence {st.session_state.u_index + 1}</b></center>", unsafe_allow_html=True)
if c3.button("Next ➡️") and st.session_state.u_index < len(unique_list) - 1:
    st.session_state.u_index += 1
    st.rerun()

st.info(f"**Original:** {current_incorrect}")
st.divider()

# Ratings
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
                if key not in st.session_state:
                    saved = get_saved_rating(m_id, st.session_state.u_index)
                    if saved: st.session_state[key] = saved
                
                st.pills("Rate", rating_options, key=key, label_visibility="collapsed")

st.divider()
manual_fix = st.text_area("Correction (Optional):", key=f"fix_{st.session_state.u_index}")

if st.button("Save Ratings", type="primary", use_container_width=True):
    with st.spinner("Saving clean data..."):
        # Calculate ID: Nemotron Row Number
        nem_row_id = get_nemotron_row_id(master_df, current_incorrect)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # SAVE RATINGS
        for m_id in model_ids:
            val = st.session_state.get(f"pills_{m_id}_{st.session_state.u_index}")
            if val is not None:
                # STRICT DATAFRAME CREATION
                # We define ONLY the columns we want. No 'incorrect' or 'corrected' text here.
                clean_entry = pd.DataFrame([{
                    "submission_id": int(nem_row_id) if nem_row_id != "Unknown" else 0,
                    "user": str(st.session_state.username),
                    "unique_set_index": int(st.session_state.u_index),
                    "rating": int(val),
                    "timestamp": ts
                }])
                save_entry_to_sheet(m_id, MODEL_TAB_NAMES[m_id], clean_entry, st.session_state.u_index)
        
        # SAVE MANUAL FIX
        if manual_fix:
            clean_user_entry = pd.DataFrame([{
                "submission_id": int(nem_row_id) if nem_row_id != "Unknown" else 0,
                "user": str(st.session_state.username),
                "unique_set_index": int(st.session_state.u_index),
                "user_corrected": str(manual_fix),
                "timestamp": ts
            }])
            save_entry_to_sheet("corrections", USER_CORRECTION_TAB_NAME, clean_user_entry, st.session_state.u_index)

    st.success("Saved!")
    time.sleep(0.5)
    if st.session_state.u_index < len(unique_list) - 1:
        st.session_state.u_index += 1
        st.rerun()
