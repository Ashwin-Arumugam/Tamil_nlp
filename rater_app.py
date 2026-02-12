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
# INTERNAL HELPERS (Fixes the 'worksheet_id' error)
# =========================================================

def get_sheet_name_by_gid(gid):
    """Internal helper to find the tab name from a GID."""
    try:
        # Access the underlying client to get spreadsheet metadata
        spreadsheet = conn._instance.client.open_by_key(st.secrets["connections"]["gsheets"]["spreadsheet"])
        for sheet in spreadsheet.worksheets():
            if str(sheet.id) == str(gid):
                return sheet.title
    except Exception as e:
        st.error(f"Metadata lookup failed: {e}")
    return None

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
# DATA LOADING
# =========================================================

@st.cache_data(show_spinner=False, ttl=300)
def load_master_data():
    df = conn.read(worksheet_id=MASTER_SHEET_GID)
    if df is None or df.empty:
        raise ValueError("Master sheet is empty or not accessible")
    df = df.dropna(how="all")
    unique_sentences = df["incorrect"].unique().tolist()
    return df, unique_sentences

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
    st.error("Error connecting to Google Sheets.")
    st.stop()

# =========================================================
# HELPER FUNCTIONS
# =========================================================

def get_existing_rating(m_id, u_idx):
    df_check = st.session_state.existing_data.get(m_id)
    if df_check is not None and not df_check.empty:
        if "unique_set_index" in df_check.columns and "user" in df_check.columns:
            match = df_check[
                (df_check["unique_set_index"].astype(str) == str(u_idx))
                & (df_check["user"] == st.session_state.username)
            ]
            if not match.empty:
                try: return int(match.iloc[0]["rating"])
                except: return None
    return None

def save_all_ratings(u_idx, current_incorrect, versions, ratings_dict, manual_fix):
    submission_uuid = str(uuid.uuid4())
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
            time.sleep(0.7)
            gid = MODEL_SHEET_GIDS[m_id]
            # Convert GID to Sheet Name for the update call
            sheet_name = get_sheet_name_by_gid(gid)
            
            existing_df = conn.read(worksheet_id=gid, ttl=0)
            
            if existing_df is not None and not existing_df.empty:
                if "unique_set_index" in existing_df.columns and "user" in existing_df.columns:
                    mask = (existing_df["unique_set_index"].astype(str) == str(u_idx)) & \
                           (existing_df["user"] == st.session_state.username)
                    existing_df = existing_df[~mask]
                updated_df = pd.concat([existing_df, new_entry], ignore_index=True)
            else:
                updated_df = new_entry
            
            # FIX: Use worksheet=sheet_name instead of worksheet_id
            conn.update(worksheet=sheet_name, data=updated_df.fillna(""))
            st.session_state.existing_data[m_id] = updated_df

        except Exception as e:
            st.error(f"Failed to update sheet for Model {m_id}: {str(e)}")

    if manual_fix.strip():
        user_entry = pd.DataFrame([{
            "submission_id": submission_uuid,
            "user": str(st.session_state.username),
            "unique_set_index": int(u_idx),
            "incorrect": str(current_incorrect),
            "user_corrected": str(manual_fix),
        }])

        try:
            time.sleep(0.7)
            u_sheet_name = get_sheet_name_by_gid(USER_CORRECTION_GID)
            df_user = conn.read(worksheet_id=USER_CORRECTION_GID, ttl=0)
            if df_user is not None and not df_user.empty:
                if "unique_set_index" in df_user.columns and "user" in df_user.columns:
                    mask = (df_user["unique_set_index"].astype(str) == str(u_idx)) & \
                           (df_user["user"] == st.session_state.username)
                    df_user = df_user[~mask]
                updated_user_df = pd.concat([df_user, user_entry], ignore_index=True)
            else:
                updated_user_df = user_entry
            
            # FIX: Use worksheet=u_sheet_name
            conn.update(worksheet=u_sheet_name, data=updated_user_df.fillna(""))
        except Exception as e:
            st.error(f"Failed to update manual correction: {str(e)}")

# =========================================================
# MAIN UI
# =========================================================

if "u_index" not in st.session_state:
    st.session_state.u_index = 0

if not unique_list or st.session_state.u_index >= len(unique_list):
    st.success("Evaluations complete.")
    st.stop()

current_incorrect = unique_list[st.session_state.u_index]
versions = master_df[master_df["incorrect"] == current_incorrect]

st.title("Evaluation Workspace")

# Navigation
c1, c2, c3 = st.columns([1, 8, 1])
with c1:
    if st.button("Previous") and st.session_state.u_index > 0:
        st.session_state.u_index -= 1
        st.rerun()
with c2:
    st.write(f"<center>Entry <b>{st.session_state.u_index + 1}</b> of {len(unique_list)}</center>", unsafe_allow_html=True)
    st.progress((st.session_state.u_index + 1) / len(unique_list))
with c3:
    if st.button("Next") and st.session_state.u_index < len(unique_list) - 1:
        st.session_state.u_index += 1
        st.rerun()

st.subheader("Original Text")
st.markdown(f"> {current_incorrect}")
st.divider()

current_ratings = {}
model_ids = sorted(MODEL_MAP.keys())

# Display Grid
for row_ids in [model_ids[:3], model_ids[3:]]:
    cols = st.columns(3)
    for i, m_id in enumerate(row_ids):
        with cols[i]:
            m_row = versions[versions["id"] == m_id]
            if not m_row.empty:
                st.markdown(f"**{MODEL_MAP[m_id].capitalize()}**")
                st.info(m_row.iloc[0]["corrected"])
                existing_val = get_existing_rating(m_id, st.session_state.u_index)
                current_ratings[m_id] = st.radio(
                    f"Rating {m_id}", range(1, 11),
                    index=existing_val - 1 if existing_val else None,
                    horizontal=True, key=f"rad_{m_id}_{st.session_state.u_index}",
                    label_visibility="collapsed"
                )

st.divider()
manual_fix = st.text_area("Ideal correction:", key=f"manual_{st.session_state.u_index}")

if st.button("Save and Continue", type="primary", use_container_width=True, 
             disabled=not all(current_ratings.get(m) for m in model_ids)):
    with st.spinner("Saving..."):
        save_all_ratings(st.session_state.u_index, current_incorrect, versions, current_ratings, manual_fix)
        st.session_state.u_index += 1
        st.rerun()
