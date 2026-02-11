import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
import uuid

# =========================================================
# CONFIGURATION
# =========================================================

st.set_page_config(page_title="Model Comparison Tool", layout="wide")

conn = st.connection("gsheets", type=GSheetsConnection)

# 🔥 MASTER SHEET GID (replace with your actual master gid)
MASTER_SHEET_GID = 1905633307

# 🔥 MODEL TAB GIDs (these are correct already)
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

# 🔥 USER CORRECTION TAB GID (replace with actual gid)
USER_CORRECTION_GID = 677241304  # change this to actual gid of manual_gold_corrections

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
# LOAD MASTER DATA
# =========================================================

@st.cache_data(show_spinner=False)
def load_and_group_data():
    df = conn.read(worksheet=MASTER_SHEET_GID)

    if df is None or df.empty:
        raise ValueError("Master sheet is empty or not accessible")

    df = df.dropna(how="all")

    if "incorrect" not in df.columns:
        raise KeyError(
            f"'incorrect' column not found. Columns available: {df.columns.tolist()}"
        )

    unique_sentences = df["incorrect"].unique().tolist()
    return df, unique_sentences



try:
    master_df, unique_list = load_and_group_data()
    st.success("Master sheet loaded successfully ✅")
except Exception as e:
    st.error("REAL ERROR BELOW ⬇️")
    st.exception(e)
    st.stop()


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def get_existing_rating(m_id, u_idx):
    try:
        df_check = conn.read(worksheet_id=MODEL_SHEET_GIDS[m_id])
        if not df_check.empty and "unique_set_index" in df_check.columns:
            match = df_check[
                (df_check["unique_set_index"] == u_idx)
                & (df_check["user"] == st.session_state.username)
            ]
            if not match.empty:
                return int(match.iloc[0]["rating"])
    except:
        pass
    return None


def save_all_ratings(u_idx, current_incorrect, versions, ratings_dict, manual_fix):

    submission_uuid = str(uuid.uuid4())

    for m_id, rating in ratings_dict.items():

        m_row_data = versions[versions["id"] == m_id].iloc[0]

        new_entry = pd.DataFrame(
            [
                {
                    "submission_id": submission_uuid,
                    "user": st.session_state.username,
                    "unique_set_index": u_idx,
                    "incorrect": current_incorrect,
                    "corrected": m_row_data["corrected"],
                    "rating": rating,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            ]
        )

        try:
            existing_df = conn.read(worksheet=MODEL_SHEET_GIDS[m_id])

            if not existing_df.empty and "unique_set_index" in existing_df.columns:
                mask = (
                    (existing_df["unique_set_index"] == u_idx)
                    & (existing_df["user"] == st.session_state.username)
                )
                existing_df = existing_df[~mask]

            updated_df = pd.concat([existing_df, new_entry], ignore_index=True)

        except:
            updated_df = new_entry

        conn.update(worksheet=MODEL_SHEET_GIDS[m_id], data=updated_df)

    # Save manual correction
    if manual_fix.strip():

        user_entry = pd.DataFrame(
            [
                {
                    "submission_id": submission_uuid,
                    "user": st.session_state.username,
                    "unique_set_index": u_idx,
                    "incorrect": current_incorrect,
                    "user_corrected": manual_fix,
                }
            ]
        )

        try:
            df_user = conn.read(worksheet_id=USER_CORRECTION_GID)

            if not df_user.empty and "unique_set_index" in df_user.columns:
                mask = (
                    (df_user["unique_set_index"] == u_idx)
                    & (df_user["user"] == st.session_state.username)
                )
                df_user = df_user[~mask]

            updated_user_df = pd.concat([df_user, user_entry], ignore_index=True)

        except:
            updated_user_df = user_entry

        conn.update(worksheet_id=USER_CORRECTION_GID, data=updated_user_df)


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
    st.stop()

current_incorrect = unique_list[st.session_state.u_index]
versions = master_df[master_df["incorrect"] == current_incorrect]

st.title("Evaluation Workspace")

# Navigation
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

for row_ids in [model_ids[:3], model_ids[3:]]:
    cols = st.columns(3)
    for i, m_id in enumerate(row_ids):
        with cols[i]:
            m_row = versions[versions["id"] == m_id]
            if not m_row.empty:
                st.markdown(f"**{MODEL_MAP[m_id].capitalize()} output**")
                st.info(m_row.iloc[0]["corrected"])

                existing_val = get_existing_rating(
                    m_id, st.session_state.u_index
                )

                current_ratings[m_id] = st.radio(
                    f"Rating for {m_id}",
                    options=rating_options,
                    index=rating_options.index(existing_val)
                    if existing_val in rating_options
                    else None,
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
    with st.spinner("Saving..."):
        save_all_ratings(
            st.session_state.u_index,
            current_incorrect,
            versions,
            current_ratings,
            manual_fix,
        )
        st.session_state.u_index += 1
        st.rerun()

if not all_rated:
    st.caption("Rate all models before proceeding.")

# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:
    st.header("Session Info")
    st.write(f"Logged in: **{st.session_state.username}**")

    st.divider()
    st.header("Leaderboard")

    try:
        prog_df = conn.read(worksheet=MODEL_SHEET_GIDS["A"])
        if not prog_df.empty:
            stats = (
                prog_df.groupby("user")["submission_id"]
                .nunique()
                .reset_index(name="Completed")
            )
            st.dataframe(
                stats.sort_values("Completed", ascending=False),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.write("Awaiting submissions.")
    except:
        st.write("Leaderboard initializing.")

    st.divider()
    st.header("Navigation")

    new_idx = st.number_input(
        "Go to index:",
        min_value=0,
        max_value=len(unique_list) - 1,
        value=st.session_state.u_index,
    )

    if st.button("Jump to Entry"):
        st.session_state.u_index = new_idx
        st.rerun()
