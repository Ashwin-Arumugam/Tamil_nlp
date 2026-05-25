import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import time

# =========================================================
# 1. CONFIGURATION & CSS
# =========================================================

st.set_page_config(page_title="Model Eval Tool", layout="wide")

st.markdown(
    """
    <style>
    div[data-testid="stPills"] > div {
        flex-wrap: nowrap !important;
        gap: 2px !important; 
        overflow-x: auto !important; 
        padding-bottom: 4px; 
    }
    div[data-testid="stPills"] button {
        padding: 2px 6px !important; 
        min-width: 30px !important; 
        min-height: 32px !important;
        font-size: 14px !important;
    }
    div[data-testid="stPills"] button p {
        margin: 0px !important;
        padding: 0px !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

MODEL_TAB_NAMES = {
    "A": "qwen",
    "B": "nemotron",
    "C": "ministral",
    "D": "kimik2",
    "E": "gpt",
    "F": "gemma"
}

RATING_COLS = ["submission_id", "user", "rating", "reason"]
CORRECTION_COLS = ["submission_id", "user", "user_corrected"]
REASON_OPTIONS = ["spelling error", "not fluent enough", "grammar error"]

# =========================================================
# 2. STATE MANAGEMENT & LOADING
# =========================================================

if "username" not in st.session_state:
    st.title("Tamil NLP grammar correction")
    with st.form("entry_form"):
        user = st.text_input("Name")
        if st.form_submit_button("Continue") and user:
            st.session_state.username = user.strip()
            st.session_state.conn = st.connection("gsheets", type=GSheetsConnection)
            st.cache_data.clear()
            if "local_dfs" in st.session_state:
                del st.session_state.local_dfs
            st.rerun()
    st.stop()

if "local_dfs" not in st.session_state:
    st.session_state.local_dfs = {}

@st.cache_data(show_spinner=False, ttl=600)
def load_master_data(_conn):
    df = _conn.read(worksheet=0, ttl=0) 
    if df is None or df.empty:
        st.error("Master sheet is empty.")
        st.stop()
    df = df.dropna(how="all")
    unique_sentences = df["incorrect"].unique().tolist()
    return df, unique_sentences

def clean_rating_df(df):
    if df is None or df.empty: return pd.DataFrame(columns=RATING_COLS)
    df["submission_id"] = df["submission_id"].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
    df = df[~df["submission_id"].isin(["", "None", "nan"])]
    df["rating"] = pd.to_numeric(df["rating"], errors='coerce').fillna(0).astype(int)
    return df[RATING_COLS]

def load_all_tabs_into_variables(_conn):
    for m_id, tab_name in MODEL_TAB_NAMES.items():
        try:
            df = _conn.read(worksheet=tab_name, ttl=0)
            st.session_state.local_dfs[m_id] = clean_rating_df(df)
        except:
            st.session_state.local_dfs[m_id] = pd.DataFrame(columns=RATING_COLS)
    try:
        df = _conn.read(worksheet="user_corrections", ttl=0)
        st.session_state.local_dfs["corrections"] = df
    except:
        st.session_state.local_dfs["corrections"] = pd.DataFrame(columns=CORRECTION_COLS)

if not st.session_state.local_dfs:
    load_all_tabs_into_variables(st.session_state.conn)

master_df, unique_list = load_master_data(st.session_state.conn)

# =========================================================
# 3. HELPER FUNCTIONS (Updated Locking Logic)
# =========================================================

def is_locked_for_user(m_id, sub_id):
    """
    Logic:
    - 0 raters: Unlocked
    - 1 rater: Locked ONLY for that specific rater. Unlocked for everyone else.
    - 2+ raters: Unlocked for EVERYONE (UI unlocks completely).
    """
    df = st.session_state.local_dfs.get(m_id)
    if df is not None and not df.empty:
        match = df[df["submission_id"] == str(sub_id)]
        raters = match["user"].unique().tolist()
        
        if len(raters) == 1:
            # If I am the only one who rated, I am locked until someone else joins
            if st.session_state.username in raters:
                return True
        
        if len(raters) >= 2:
            return False # Fully unlocked for everyone
            
    return False

def get_all_previous_ratings(m_id, sub_id):
    df = st.session_state.local_dfs.get(m_id)
    if df is not None and not df.empty:
        match = df[df["submission_id"] == str(sub_id)]
        if not match.empty:
            ratings = [f"{row['user']} ({int(row['rating'])})" for _, row in match.iterrows() if row['rating'] > 0]
            return ", ".join(ratings)
    return ""

def get_existing_rating(m_id, sub_id):
    df = st.session_state.local_dfs.get(m_id)
    if df is not None and not df.empty:
        match = df[(df["submission_id"] == str(sub_id)) & (df["user"] == st.session_state.username)]
        if not match.empty: return int(match.iloc[0]["rating"])
    return None

def get_existing_reason(m_id, sub_id):
    df = st.session_state.local_dfs.get(m_id)
    if df is not None and not df.empty:
        match = df[(df["submission_id"] == str(sub_id)) & (df["user"] == st.session_state.username)]
        if not match.empty:
            r = str(match.iloc[0]["reason"])
            return [x.strip() for x in r.split(",") if x.strip() in REASON_OPTIONS]
    return []

def update_local_variable(key, new_row_df, sub_id):
    current_df = st.session_state.local_dfs.get(key)
    if current_df is not None and not current_df.empty:
        mask = (current_df["submission_id"] == str(sub_id)) & (current_df["user"] == st.session_state.username)
        current_df = current_df[~mask]
    st.session_state.local_dfs[key] = pd.concat([new_row_df, current_df], ignore_index=True)

def save_to_local_memory(current_incorrect, versions):
    for m_id in MODEL_TAB_NAMES.keys():
        m_row = versions[versions["id"] == m_id]
        if m_row.empty: continue
        sub_id = str(m_row.index[0] + 2)
        
        if is_locked_for_user(m_id, sub_id): continue # Skip saving if locked
        
        val = st.session_state.get(f"pills_{m_id}_{st.session_state.u_index}")
        if val:
            reason_list = st.session_state.get(f"reason_{m_id}_{st.session_state.u_index}", [])
            new_row = pd.DataFrame([{"submission_id": sub_id, "user": st.session_state.username, "rating": val, "reason": ",".join(reason_list)}])
            update_local_variable(m_id, new_row, sub_id)

    # Correction logic
    fix = st.session_state.get(f"fix_{st.session_state.u_index}")
    if fix and not versions.empty:
        sub_id = str(versions.index[0] + 2)
        new_row = pd.DataFrame([{"submission_id": sub_id, "user": st.session_state.username, "user_corrected": fix}])
        update_local_variable("corrections", new_row, sub_id)

def sync_to_cloud():
    save_bar = st.progress(0, text="Syncing...")
    for i, (key, df) in enumerate(st.session_state.local_dfs.items()):
        tab = MODEL_TAB_NAMES.get(key, "user_corrections" if key == "corrections" else None)
        if tab and not df.empty:
            st.session_state.conn.update(worksheet=tab, data=df)
            time.sleep(0.5)
        save_bar.progress((i+1)/len(st.session_state.local_dfs))
    save_bar.empty()

# =========================================================
# 4. MAIN UI
# =========================================================

if "u_index" not in st.session_state:
    st.session_state.u_index = 0

top_c1, top_c2 = st.columns([8, 2])
with top_c1: st.markdown(f"👤 Name: **{st.session_state.username}**")
with top_c2:
    if st.button("Save & Exit", type="primary"):
        save_to_local_memory(unique_list[st.session_state.u_index], master_df[master_df["incorrect"] == unique_list[st.session_state.u_index]])
        sync_to_cloud()
        st.session_state.clear()
        st.rerun()

st.divider()

if st.session_state.u_index >= len(unique_list):
    st.success("🎉 All sentences evaluated!")
    st.stop()

current_incorrect = unique_list[st.session_state.u_index]
versions = master_df[master_df["incorrect"] == current_incorrect]

# Check if the overall sentence is locked for this user
is_sentence_locked = False
for m_id in MODEL_TAB_NAMES.keys():
    m_row = versions[versions["id"] == m_id]
    if not m_row.empty and is_locked_for_user(m_id, str(m_row.index[0] + 2)):
        is_sentence_locked = True
        break

st.markdown(f"<center><h4>Sentence {st.session_state.u_index + 1} of {len(unique_list)}</h4></center>", unsafe_allow_html=True)

if is_sentence_locked:
    st.info("ℹ️ Your rating is submitted. Editing is locked until a second person annotates this sentence. Once 2+ ratings exist, it will unlock for everyone.")

st.info(f"**Original:** {current_incorrect}")

model_ids = sorted(MODEL_TAB_NAMES.keys())
rows = [model_ids[:3], model_ids[3:]]

for row_ids in rows:
    cols = st.columns(3)
    for i, m_id in enumerate(row_ids):
        with cols[i]:
            m_row = versions[versions["id"] == m_id]
            if not m_row.empty:
                sub_id = str(m_row.index[0] + 2)
                st.markdown(f"**{m_id}**")
                st.success(m_row.iloc[0]["corrected"])
                
                # Previous ratings are ALWAYS visible
                prev = get_all_previous_ratings(m_id, sub_id)
                if prev: st.caption(f"Ratings: {prev}")
                
                key = f"pills_{m_id}_{st.session_state.u_index}"
                if key not in st.session_state:
                    st.session_state[key] = get_existing_rating(m_id, sub_id)
                
                # Input is disabled if locked for this user
                lock = is_locked_for_user(m_id, sub_id)
                sel = st.pills("Rate", range(1, 11), key=key, disabled=lock, label_visibility="collapsed")
                
                if sel and sel <= 7:
                    r_key = f"reason_{m_id}_{st.session_state.u_index}"
                    if r_key not in st.session_state:
                        st.session_state[r_key] = get_existing_reason(m_id, sub_id)
                    st.multiselect("Why?", REASON_OPTIONS, key=r_key, disabled=lock)

st.divider()
st.text_area("Correction (Optional):", key=f"fix_{st.session_state.u_index}", disabled=is_sentence_locked)

# --- Navigation ---
b_c1, b_c2, b_c3, b_c4 = st.columns([2, 3, 2, 2])
with b_c1:
    if st.button("⬅️ Prev") and st.session_state.u_index > 0:
        save_to_local_memory(current_incorrect, versions)
        st.session_state.u_index -= 1
        st.rerun()
with b_c2:
    jump_val = st.number_input("Jump", 1, len(unique_list), st.session_state.u_index + 1, label_visibility="collapsed")
with b_c3:
    if st.button("🚀 Jump"):
        save_to_local_memory(current_incorrect, versions)
        st.session_state.u_index = jump_val - 1
        st.rerun()
with b_c4:
    if st.button("Next ➡️"):
        save_to_local_memory(current_incorrect, versions)
        st.session_state.u_index += 1
        st.rerun()
