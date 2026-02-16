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
USER_CORRECTION_GID = 677241304

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

# =========================================================
# 2. STATE MANAGEMENT (The "Separate Variables" Logic)
# =========================================================

if "username" not in st.session_state:
    st.title("Login")
    with st.form("login"):
        user = st.text_input("Username")
        if st.form_submit_button("Start") and user:
            st.session_state.username = user.strip()
            # Force reload of all data on login
            st.cache_data.clear()
            if "local_dfs" in st.session_state:
                del st.session_state.local_dfs
            st.rerun()
    st.stop()

# Initialize the Dictionary to hold separate DataFrames
if "local_dfs" not in st.session_state:
    st.session_state.local_dfs = {}

@st.cache_data(show_spinner=False, ttl=600)
def load_master_data():
    df = conn.read(worksheet_id=MASTER_SHEET_GID)
    if df is None or df.empty:
        st.error("Master sheet is empty.")
        st.stop()
    df = df.dropna(how="all")
    unique_sentences = df["incorrect"].unique().tolist()
    return df, unique_sentences

def clean_df(df):
    """Ensures consistent types for the local variables."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["submission_id", "user", "rating"])
    
    if "submission_id" in df.columns:
        df["submission_id"] = df["submission_id"].astype(str)
    if "rating" in df.columns:
        df["rating"] = pd.to_numeric(df["rating"], errors='coerce').fillna(0).astype(int)
    return df

def load_all_tabs_into_variables():
    """
    Loads EVERY tab into its own key in st.session_state.local_dfs
    This happens once (or on refresh) to populate the 'variables'.
    """
    # 1. Load Model Tabs
    for m_id, gid in MODEL_SHEET_GIDS.items():
        try:
            # Read from Cloud
            df = conn.read(worksheet_id=gid, ttl=0)
            # Store in Variable
            st.session_state.local_dfs[m_id] = clean_df(df)
        except Exception:
            st.session_state.local_dfs[m_id] = pd.DataFrame(columns=["submission_id", "user", "rating"])

    # 2. Load Corrections Tab
    try:
        df_corr = conn.read(worksheet_id=USER_CORRECTION_GID, ttl=0)
        if "submission_id" in df_corr.columns:
            df_corr["submission_id"] = df_corr["submission_id"].astype(str)
        st.session_state.local_dfs["corrections"] = df_corr
    except:
        st.session_state.local_dfs["corrections"] = pd.DataFrame(columns=["submission_id", "user", "user_corrected"])

# Trigger Load if empty
if not st.session_state.local_dfs:
    with st.spinner("Initializing variables from cloud..."):
        load_master_data()
        load_all_tabs_into_variables()

master_df, unique_list = load_master_data()

# =========================================================
# 3. HELPER FUNCTIONS
# =========================================================

def get_nemotron_row_id(master_df, current_incorrect):
    mask = (master_df["incorrect"] == current_incorrect) & (master_df["id"] == "B")
    subset = master_df[mask]
    if not subset.empty:
        return str(subset.index[0] + 2)
    return "Unknown"

def get_existing_rating(m_id, sub_id):
    """Reads from the LOCAL variable, not the cloud."""
    df = st.session_state.local_dfs.get(m_id)
    if df is not None and not df.empty:
        mask = (df["submission_id"] == str(sub_id)) & (df["user"] == st.session_state.username)
        match = df[mask]
        if not match.empty:
            try:
                val = int(match.iloc[0]["rating"])
                return val if val > 0 else None
            except:
                return None
    return None

def update_local_variable(key, new_entry_df, sub_id):
    """
    Updates the specific dataframe in the local_dfs dictionary.
    Removes old entry for this user/id, appends new one.
    """
    current_df = st.session_state.local_dfs.get(key)
    
    # Filter out OLD entry for this specific sentence & user
    if current_df is not None and not current_df.empty:
        if "submission_id" in current_df.columns and "user" in current_df.columns:
            mask = (current_df["submission_id"] == str(sub_id)) & \
                   (current_df["user"] == st.session_state.username)
            current_df = current_df[~mask]
    else:
        # If empty, initialize
        current_df = pd.DataFrame()

    # Append NEW entry to top
    updated_df = pd.concat([new_entry_df, current_df], ignore_index=True)
    
    # Save back to State Variable
    st.session_state.local_dfs[key] = updated_df

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
nem_row_id = get_nemotron_row_id(master_df, current_incorrect)

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

# --- Ratings ---
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
                
                # Check Local Variable for previous rating
                key = f"pills_{m_id}_{st.session_state.u_index}"
                if key not in st.session_state:
                    saved_val = get_existing_rating(m_id, nem_row_id)
                    if saved_val:
                        st.session_state[key] = saved_val
                
                st.pills("Rate", rating_options, key=key, label_visibility="collapsed")

st.divider()
manual_fix = st.text_area("Correction (Optional):", key=f"fix_{st.session_state.u_index}")

# --- SAVE LOGIC ---
if st.button("Save Ratings", type="primary", use_container_width=True):
    save_bar = st.progress(0, text="Updating variables...")
    
    # 1. Update LOCAL Variables first
    # -----------------------------
    for m_id in model_ids:
        val = st.session_state.get(f"pills_{m_id}_{st.session_state.u_index}")
        if val is not None:
            # Create Row
            new_row = pd.DataFrame([{
                "submission_id": str(nem_row_id),
                "user": str(st.session_state.username),
                "rating": int(val)
            }])
            # Append to variable
            update_local_variable(m_id, new_row, nem_row_id)
            
    if manual_fix:
        user_row = pd.DataFrame([{
            "submission_id": str(nem_row_id),
            "user": str(st.session_state.username),
            "user_corrected": str(manual_fix)
        }])
        update_local_variable("corrections", user_row, nem_row_id)

    # 2. Write Variables to Cloud
    # ---------------------------
    total_tabs = len(model_ids) + 1
    current_tab = 0
    
    # Loop through keys in our local variable dictionary
    for key, df in st.session_state.local_dfs.items():
        if not df.empty:
            # Determine Tab Name
            if key in MODEL_TAB_NAMES:
                tab_name = MODEL_TAB_NAMES[key]
            elif key == "corrections":
                tab_name = "user_corrections"
            else:
                continue # Skip unknown keys
            
            save_bar.progress((current_tab / total_tabs), text=f"Writing {tab_name}...")
            
            try:
                conn.update(worksheet=tab_name, data=df)
                time.sleep(1.0) # Pause to prevent API mixing
            except Exception as e:
                st.error(f"Failed to write {tab_name}: {e}")
            
            current_tab += 1

    save_bar.progress(1.0, text="Done!")
    st.success("Saved!")
    time.sleep(0.5)
    
    # Advance
    if st.session_state.u_index < len(unique_list) - 1:
        st.session_state.u_index += 1
        st.rerun()
