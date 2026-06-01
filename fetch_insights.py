import os
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone, timedelta
import json

# --- 設定 ---
IG_ACCOUNT_ID = os.environ["IG_ACCOUNT_ID"]
ACCESS_TOKEN = os.environ["IG_PAGE_ACCESS_TOKEN"]
SPREADSHEET_ID = "1SaVKe_sk7KAdjJlA0MEL7K71WnFEQ-i4Z85npcBzbzM"
SHEET_NAME = "raw_data"

# --- Google Sheets 認証 ---
def get_sheet():
    creds_json = os.environ["GOOGLE_CREDENTIALS"]
    creds_dict = json.loads(creds_json)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

# --- Instagram API からインサイト取得 ---
def fetch_insights():
    url = f"https://graph.facebook.com/v25.0/{IG_ACCOUNT_ID}/insights"
    params = {
        "metric": "reach,follower_count",
        "period": "day",
        "access_token": ACCESS_TOKEN,
    }
    res = requests.get(url, params=params)
    res.raise_for_status()
    return res.json()["data"]

# --- フォロワー数取得 ---
def fetch_followers():
    url = f"https://graph.facebook.com/v25.0/{IG_ACCOUNT_ID}"
    params = {
        "fields": "followers_count",
        "access_token": ACCESS_TOKEN,
    }
    res = requests.get(url, params=params)
    res.raise_for_status()
    return res.json()["followers_count"]

# --- スプレッドシートに書き込み ---
def write_to_sheet(sheet, rows):
    # ヘッダーがなければ追加
    existing = sheet.get_all_values()
    if not existing:
        sheet.append_row(["date", "reach", "follower_count_delta", "followers_total"])

    for row in rows:
        sheet.append_row(row)
    print(f"{len(rows)}行を書き込みました")

# --- メイン処理 ---
def main():
    sheet = get_sheet()
    insights = fetch_insights()
    followers_total = fetch_followers()

    # insightsからreach・follower_countを取り出す
    reach_data = {}
    follower_delta_data = {}

    for metric in insights:
        name = metric["name"]
        for entry in metric["values"]:
            date_str = entry["end_time"][:10]  # YYYY-MM-DD
            if name == "reach":
                reach_data[date_str] = entry["value"]
            elif name == "follower_count":
                follower_delta_data[date_str] = entry["value"]

    # 日付をまとめてrows作成（直近2日分）
    rows = []
    for date_str in sorted(reach_data.keys()):
        reach = reach_data.get(date_str, 0)
        delta = follower_delta_data.get(date_str, 0)
        # 最新日のみ followers_total を記録
        total = followers_total if date_str == sorted(reach_data.keys())[-1] else ""
        rows.append([date_str, reach, delta, total])

    write_to_sheet(sheet, rows)

if __name__ == "__main__":
    main()
