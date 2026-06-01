import os
import requests
import gspread
from google.oauth2.service_account import Credentials
import json

# --- 設定 ---
IG_ACCOUNT_ID = os.environ["IG_ACCOUNT_ID"]
ACCESS_TOKEN = os.environ["IG_PAGE_ACCESS_TOKEN"]
SPREADSHEET_ID = "1SaVKe_sk7KAdjJlA0MEL7K71WnFEQ-i4Z85npcBzbzM"

ACCOUNT_METRICS = ["reach", "follower_count"]

ACCOUNT_HEADERS = [
    "date / 日付",
    "reach / リーチ数",
    "follower_count_delta / フォロワー増減",
    "followers_total / フォロワー総数",
]

POST_HEADERS = [
    "post_id / 投稿ID",
    "timestamp / 投稿日時",
    "media_type / 投稿タイプ",
    "caption / キャプション（先頭50文字）",
    "like_count / いいね数",
    "comments_count / コメント数",
    "reach / リーチ数",
    "saved / 保存数",
    "engagement_rate / エンゲージメント率(%)",
]

# --- Google Sheets 認証 ---
def get_spreadsheet():
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

# --- アカウントインサイト取得 ---
def fetch_account_insights():
    url = f"https://graph.facebook.com/v25.0/{IG_ACCOUNT_ID}/insights"
    params = {
        "metric": ",".join(ACCOUNT_METRICS),
        "period": "day",
        "access_token": ACCESS_TOKEN,
    }
    res = requests.get(url, params=params)
    res.raise_for_status()
    return res.json()["data"]

# --- フォロワー総数取得 ---
def fetch_followers():
    url = f"https://graph.facebook.com/v25.0/{IG_ACCOUNT_ID}"
    params = {"fields": "followers_count", "access_token": ACCESS_TOKEN}
    res = requests.get(url, params=params)
    res.raise_for_status()
    return res.json()["followers_count"]

# --- 投稿一覧取得 ---
def fetch_media_list():
    url = f"https://graph.facebook.com/v25.0/{IG_ACCOUNT_ID}/media"
    params = {
        "fields": "id,timestamp,media_type,caption,like_count,comments_count",
        "limit": 50,
        "access_token": ACCESS_TOKEN,
    }
    res = requests.get(url, params=params)
    res.raise_for_status()
    return res.json().get("data", [])

# --- 投稿インサイト取得（reach・saved）---
def fetch_media_insights(media_id, media_type):
    url = f"https://graph.facebook.com/v25.0/{media_id}/insights"
    if media_type == "VIDEO" or media_type == "REELS":
        metrics = "reach,saved,plays"
    else:
        metrics = "reach,saved"
    params = {"metric": metrics, "access_token": ACCESS_TOKEN}
    res = requests.get(url, params=params)
    if res.status_code != 200:
        return {}
    result = {}
    for item in res.json().get("data", []):
        result[item["name"]] = item["values"][0]["value"] if item.get("values") else 0
    return result

# --- アカウントデータ書き込み ---
def write_account_data(sheet, followers_total):
    insights = fetch_account_insights()
    data_by_date = {}
    for metric in insights:
        name = metric["name"]
        for entry in metric["values"]:
            date_str = entry["end_time"][:10]
            if date_str not in data_by_date:
                data_by_date[date_str] = {}
            data_by_date[date_str][name] = entry["value"]

    existing = sheet.get_all_values()
    if not existing or not existing[0] or existing[0][0] != "date / 日付":
        sheet.insert_row(ACCOUNT_HEADERS, 1)

    sorted_dates = sorted(data_by_date.keys())
    for date_str in sorted_dates:
        d = data_by_date[date_str]
        total = followers_total if date_str == sorted_dates[-1] else ""
        sheet.append_row([
            date_str,
            d.get("reach", ""),
            d.get("follower_count", ""),
            total,
        ])
    print(f"アカウントデータ: {len(sorted_dates)}行を書き込みました")

# --- 投稿データ書き込み ---
def write_post_data(sheet, followers_total):
    media_list = fetch_media_list()

    # 既存の投稿IDを取得して重複書き込みを防ぐ
    existing = sheet.get_all_values()
    if not existing or not existing[0] or existing[0][0] != "post_id / 投稿ID":
        sheet.insert_row(POST_HEADERS, 1)
        existing_ids = set()
    else:
        existing_ids = {row[0] for row in existing[1:] if row}

    new_count = 0
    for media in media_list:
        media_id = media["id"]
        if media_id in existing_ids:
            continue

        media_type = media.get("media_type", "")
        insights = fetch_media_insights(media_id, media_type)

        like_count = media.get("like_count", 0)
        comments_count = media.get("comments_count", 0)
        reach = insights.get("reach", 0)
        saved = insights.get("saved", 0)

        # エンゲージメント率 = (いいね + コメント + 保存) / フォロワー総数 × 100
        if followers_total > 0:
            engagement_rate = round(
                (like_count + comments_count + saved) / followers_total * 100, 2
            )
        else:
            engagement_rate = ""

        caption = media.get("caption", "")[:50] if media.get("caption") else ""

        sheet.append_row([
            media_id,
            media.get("timestamp", "")[:19].replace("T", " "),
            media_type,
            caption,
            like_count,
            comments_count,
            reach,
            saved,
            engagement_rate,
        ])
        new_count += 1

    print(f"投稿データ: {new_count}件を書き込みました（既存{len(existing_ids)}件はスキップ）")

# --- メイン処理 ---
def main():
    spreadsheet = get_spreadsheet()
    raw_sheet = spreadsheet.worksheet("raw_data")
    post_sheet = spreadsheet.worksheet("post_data")
    followers_total = fetch_followers()

    write_account_data(raw_sheet, followers_total)
    write_post_data(post_sheet, followers_total)

if __name__ == "__main__":
    main()
