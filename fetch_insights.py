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

METRICS = [
    "reach",
    "impressions",
    "accounts_engaged",
    "follower_count",
    "website_clicks",
]

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
        "metric": ",".join(METRICS),
        "period": "day",
        "access_token": ACCESS_TOKEN,
    }
    res = requests.get(url, params=params)
    res.raise_for_status()
    return res.json()["data"]

# --- フォロワー総数取得 ---
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
    existing = sheet.get_all_values()
    if not existing:
        sheet.append_row([
            "date",
            "reach / リーチ数",
            "impressions / インプレッション数",
            "accounts_engaged / エンゲージメント数",
            "follower_count_delta / フォロワー増減",
            "website_clicks / サイトクリック数",
            "followers_total / フォロワー総数",
        ])
    for row in rows:
        sheet.append_row(row)
    print(f"{len(rows)}行を書き込みました")

# --- メイン処理 ---
def main():
    sheet = get_sheet()
    insights = fetch_insights()
    followers_total = fetch_followers()

    # 指標ごとにデータを整理
    data_by_date = {}
    for metric in insights:
        name = metric["name"]
        for entry in metric["values"]:
            date_str = entry["end_time"][:10]
            if date_str not in data_by_date:
                data_by_date[date_str] = {}
            data_by_date[date_str][name] = entry["value"]

    rows = []
    sorted_dates = sorted(data_by_date.keys())
    for date_str in sorted_dates:
        d = data_by_date[date_str]
        total = followers_total if date_str == sorted_dates[-1] else ""
        rows.append([
            date_str,
            d.get("reach", ""),
            d.get("impressions", ""),
            d.get("accounts_engaged", ""),
            d.get("follower_count", ""),
            d.get("website_clicks", ""),
            total,
        ])

    write_to_sheet(sheet, rows)

if __name__ == "__main__":
    main()
