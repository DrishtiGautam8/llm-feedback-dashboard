import gspread
import pandas as pd
import random
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
import os

#SERVICE_ACCOUNT = os.getenv("SERVICE_ACCOUNT")
SERVICE_ACCOUNT = st.secrets["SERVICE_ACCOUNT"]


def get_gspread_client():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        credentials = Credentials.from_service_account_info(st.secrets["SERVICE_ACCOUNT"], scopes=scopes)
        gc = gspread.authorize(credentials)
        return gc
    except Exception as e:
        raise RuntimeError(f"❌ Failed to connect with Google Sheets: {e}")

# def get_gspread_client():
#     try:
#         scopes = ["https://www.googleapis.com/auth/spreadsheets"]
#         credentials = Credentials.from_service_account_file(SERVICE_ACCOUNT, scopes=scopes)
#         gc = gspread.authorize(credentials)
#         return gc
#     except Exception as e:
#         raise RuntimeError(f"❌ Failed to connect with {SERVICE_ACCOUNT}: {e}")

# Initialize client
gc = get_gspread_client()

# Load Sheets
QUERY_SHEET_ID = st.secrets["SPREADSHEET_IDS"]["QUERY_SHEET_ID"]
FEEDBACK_SHEET_ID = st.secrets["SPREADSHEET_IDS"]["FEEDBACK_SHEET_ID"]
# QUERY_SHEET_ID = os.getenv("QUERY_SHEET_ID")
# FEEDBACK_SHEET_ID = os.getenv("FEEDBACK_SHEET_ID")

query_sheet = gc.open_by_key(QUERY_SHEET_ID).worksheet("Sheet1")
feedback_sheet = gc.open_by_key(FEEDBACK_SHEET_ID).worksheet("Sheet1")

# Load data functions
@st.cache_data(ttl=300)
def load_query_data():
    return pd.DataFrame(query_sheet.get_all_records())

@st.cache_data(ttl=300)
def load_feedback_data():
    headers = feedback_sheet.row_values(1)
    return pd.DataFrame(feedback_sheet.get_all_records(expected_headers=headers))

# Load or initialize session state
if "query_df" not in st.session_state:
    st.session_state.query_df = load_query_data()

if "feedback_df" not in st.session_state:
    st.session_state.feedback_df = load_feedback_data()

query_df = st.session_state.query_df
feedback_df = st.session_state.feedback_df

# Clean columns
def clean_columns(df):
    df.columns = [str(col).strip().lower().replace(' ', '_') for col in df.columns]
    df.columns = pd.Series(df.columns).str.replace(r'[^a-z0-9_]', '_', regex=True)
    return df

query_df = clean_columns(query_df)
feedback_df = clean_columns(feedback_df)

# Determine unrated queries
evaluated_queries = feedback_df["query_no"].unique().tolist() if "query_no" in feedback_df.columns else []
unrated_df = query_df[~query_df["query_no"].isin(evaluated_queries)]

# Select one random query
selected_queries = random.sample(unrated_df["query_no"].unique().tolist(), min(1, len(unrated_df)))

# Updated rubric criteria
rubrics = ["accuracy", "helpfulness", "readability"]

# --- Streamlit UI ---
st.title("🔍 LLM Evaluation Dashboard")

if "loaded_queries" not in st.session_state:
    st.session_state.loaded_queries = selected_queries
if "submissions" not in st.session_state:
    st.session_state.submissions = []

if unrated_df.empty:
    st.success("✅ All queries have been evaluated.")
else:
    st.markdown("### 📝 Instructions")
    st.write("""
        Rate each model's response based on the rubrics below.
        Then, select the best model for the query.
    """)

    for q_no in st.session_state.loaded_queries:
        grouped = query_df[query_df["query_no"] == q_no]
        query_text = grouped.iloc[0]["query"]

        st.markdown(f"---\n### 📌 Query No: {q_no}")
        st.markdown(f"**Query:** {query_text}")
        responses = grouped.reset_index(drop=True)

        response_ratings = []

        for idx, row in responses.iterrows():
            with st.expander(f"Model: {row['model_used']}"):
                st.markdown(f"**Response:** {row['model_response']}")
                rating_entry = {"model_used": row["model_used"], "rubrics": {}}
                cols = st.columns(len(rubrics))
                valid = True

                for i, rubric in enumerate(rubrics):
                    selected_rating = cols[i].radio(
                        f"{rubric.replace('_', ' ').title()} (Model: {row['model_used']})",
                        [1, 2, 3, 4, 5],
                        index=None,
                        key=f"{q_no}_{idx}_{rubric}"
                    )
                    if selected_rating is None:
                        valid = False
                    rating_entry["rubrics"][rubric] = selected_rating

                rating_entry["valid"] = valid
                response_ratings.append(rating_entry)

        best_model = st.radio(
            f"🏆 Best Model for Query {q_no}",
            options=[r["model_used"] for r in response_ratings],
            index=None,
            key=f"best_model_{q_no}"
        )

        st.session_state.submissions.append({
            "query_no": q_no,
            "response_ratings": response_ratings,
            "best_model": best_model
        })

# --- Submit Block ---
if st.button("✅ Submit Feedback"):
    feedback_data = []

    # Refresh latest feedback
    try:
        feedback_df = load_feedback_data()
        feedback_df = clean_columns(feedback_df)
        st.session_state.feedback_df = feedback_df
    except Exception as e:
        st.error(f"❌ Error refreshing feedback: {e}")

    try:
        max_s_no = pd.to_numeric(feedback_df["s_no"], errors="coerce").max()
        start_s_no = 1 if pd.isna(max_s_no) else int(max_s_no) + 1
    except:
        start_s_no = 1

    existing_rows = feedback_df[["query_no", "model_used"]] if "model_used" in feedback_df.columns else pd.DataFrame()

    for submission in st.session_state.submissions:
        query_no = submission["query_no"]
        best_model = submission["best_model"]

        if best_model is None:
            continue

        for response in submission["response_ratings"]:
            if not response.get("valid"):
                continue

            model_used = response["model_used"]

            if not existing_rows.empty and ((existing_rows["query_no"] == query_no) & (existing_rows["model_used"] == model_used)).any():
                st.warning(f"⚠️ Duplicate skipped: Query {query_no} - Model {model_used}")
                continue

            entry = [
                start_s_no,
                query_no,
                response["rubrics"]["accuracy"],
                response["rubrics"]["helpfulness"],
                response["rubrics"]["readability"],
                model_used,
                best_model
            ]
            feedback_data.append(entry)
            start_s_no += 1

    # Submit to Google Sheet
    if feedback_data:
        try:
            def find_first_empty_row(sheet):
                col_values = sheet.col_values(1)
                return len(col_values) + 1  # next empty row after last non-empty S.No

            headers = feedback_sheet.row_values(1)
            for entry in feedback_data:
                data_dict = dict(zip(headers, entry))
                row_num = find_first_empty_row(feedback_sheet)
    
                for col_idx, header in enumerate(headers, start=1):
                    value = data_dict.get(header, "")
                    feedback_sheet.update_cell(row_num, col_idx, value)

            st.success("✅ Feedback submitted successfully!")
            st.session_state.submissions = []
            st.session_state.loaded_queries = []
            st.rerun()
        except Exception as e:
            st.error(f"❌ Error writing to sheet: {e}")
    else:
        st.warning("⚠️ No valid feedback to submit.")
