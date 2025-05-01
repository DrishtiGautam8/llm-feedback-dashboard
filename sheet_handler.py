import os
import json
import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

def load_google_sheet(sheet_url_or_id: str):
    """
    Connects to the given Google Sheet and returns the gspread worksheet object.
    """
    load_dotenv()
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")

    if not creds_path or not os.path.exists(creds_path):
        raise FileNotFoundError("Google Credentials JSON file not found or path not set correctly.")

    with open(creds_path, "r") as file:
        creds_info = json.load(file)

    credentials = Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    )
    client = gspread.authorize(credentials)

    if sheet_url_or_id.startswith("http"):
        spreadsheet = client.open_by_url(sheet_url_or_id)
    else:
        spreadsheet = client.open_by_key(sheet_url_or_id)

    return spreadsheet

# Example usage:
if __name__ == "__main__":
    sheet_url = os.getenv("QUERIES_PATH")
    sheet = load_google_sheet(sheet_url)
    worksheet = sheet.sheet1
    records = worksheet.get_all_records()
    print(records)
