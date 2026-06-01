import os
import requests
import gspread
from google.oauth2.service_account import Credentials
import json

# --- 設定 ---
IG_ACCOUNT_ID = os.environ["IG_ACCOUNT_ID"]
ACCESS_TOKEN = os.environ["IG_PAGE_ACCESS_TOKEN"]
SPREADSHEET_ID = "1SaVKe_sk7KAdjJlA0MEL7K71WnFEQ-i4Z85npcBzbzM"
SHEET_NAME = "raw_data"

METRICS = [
    "reach",
    "follower_count",
]

HEADERS = [
    "date / 日付",
    "reach / リーチ数",
    "follower_count_delta / フォロワー増減",
    "followers_total / フォロワー総数",
]

# --- Google Sheets 認証 ---
def get_sheet():
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
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

# --- メイン処理 ---
def main():
    sheet = get_sheet()
    insights = fetch_insights()
    followers_total = fetch_followers()

    # 指標ごとにdate→valueの辞書を作成
    data_by_date = {}
    for metric in insights:
        name = metric["name"]
        for entry in metric["values"]:
            date_str = entry["end_time"][:10]
            if date_str not in data_by_date:
                data_by_date[date_str] = {}
            data_by_date[date_str][name] = entry["value"]

    sorted_dates = sorted(data_by_date.keys())

# ヘッダーがなければ追加
    existing = sheet.get_all_values()
    if not existing or existing[0][0] != "date / 日付":
        sheet.insert_row(HEADERS, 1)

    # 日付ごとに1行ずつ書き込み
    for date_str in sorted_dates:
        d = data_by_date[date_str]
        total = followers_total if date_str == sorted_dates[-1] else ""
        row = [
            date_str,
            d.get("reach", ""),
            d.get("follower_count", ""),
            total,
        ]
        sheet.append_row(row)
        print(f"{date_str}: {row}")

    print(f"合計 {len(sorted_dates)} 行を書き込みました")

if __name__ == "__main__":
    main()
