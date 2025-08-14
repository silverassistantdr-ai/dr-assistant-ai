# main.py
import os
import json
import base64
import tempfile
import requests
from fastapi import FastAPI, Request
from pydantic import BaseModel

import openai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- Load Telegram & OpenAI config ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")  # set in Deta/Render/Railway


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# --- Load Google service account from local base64 file ---
SECRET_FILE = os.path.join(os.path.dirname(__file__), "Service_Account/google_service_account.secret")
with open(SECRET_FILE, "r") as f:
    encoded_secret = f.read()

credentials_dict = json.loads(base64.b64decode(encoded_secret))

# --- Google Sheets setup ---
SHEET_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds_sheets = Credentials.from_service_account_info(credentials_dict, scopes=SHEET_SCOPES)
sheets_service = build("sheets", "v4", credentials=creds_sheets)
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")  # your sheet ID

# --- Google Drive setup ---
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
creds_drive = Credentials.from_service_account_info(credentials_dict, scopes=DRIVE_SCOPES)
drive_service = build("drive", "v3", credentials=creds_drive)

# --- FastAPI app ---
app = FastAPI()

class TelegramUpdate(BaseModel):
    message: dict

# --- Helper functions ---
def send_telegram_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

def transcribe_voice(file_url: str) -> str:
    r = requests.get(file_url)
    with tempfile.NamedTemporaryFile(suffix=".ogg") as f:
        f.write(r.content)
        f.flush()
        audio_file = open(f.name, "rb")
        transcript = openai.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )
    return transcript["text"]

def ask_openai(prompt: str) -> str:
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content

# --- Example function to write a value to Google Sheets ---
def write_to_sheet(range_name: str, values: list):
    sheets_service.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=range_name,
        valueInputOption="RAW",
        body={"values": values}
    ).execute()

# --- Telegram webhook endpoint ---
@app.post("/telegram-webhook")
async def telegram_webhook(update: TelegramUpdate):
    message = update.message
    chat_id = message["chat"]["id"]

    # Check if voice
    if "voice" in message:
        file_id = message["voice"]["file_id"]
        file_info = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}").json()
        file_path = file_info["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        text = transcribe_voice(file_url)
    elif "text" in message:
        text = message["text"]
    else:
        text = "Unsupported message type"

    # Send text to OpenAI
    answer = ask_openai(text)
    
    # Send reply to Telegram
    send_telegram_message(chat_id, answer)

    # Optional: log interaction to Google Sheet
    write_to_sheet("Sheet1!A1:B1", [[text, answer]])

    return {"status": "ok"}
