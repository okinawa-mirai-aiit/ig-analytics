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
    "caption / キャプション(先頭50文字)",
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

    # 過去7日分を since/until で明示
    now = datetime.now(timezone.utc)
    until_ts = int(now.timestamp())
    since_ts = int((now - timedelta(days=7)).timestamp())

    params = {
        "metric": ",".join(ACCOUNT_METRICS),
        "period": "day",
        "since": since_ts,
        "until": until_ts,
        "access_token": ACCESS_TOKEN,
    }
    res = requests.get(url, params=params)
    print(f"[DEBUG] account insights status: {res.status_code}")
    res.raise_for_status()
    return res.json().get("data", [])
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
        "fields": "id,timestamp,media_type,media_product_type,caption,like_count,comments_count",
        "limit": 100,  # 50 → 100 に増やす（念のため）
        "access_token": ACCESS_TOKEN,
    }
    res = requests.get(url, params=params)
    res.raise_for_status()
    data = res.json().get("data", [])

    # 診断用ログ
    print(f"[DEBUG] media count returned: {len(data)}")
    for i, m in enumerate(data[:10]):
        print(f"[DEBUG] #{i+1} {m.get('timestamp')} | {m.get('media_type')} | product_type={m.get('media_product_type', 'N/A')} | {m.get('id')}")

    return data
# --- 投稿インサイト取得 ---
def fetch_media_insights(media_id, media_type):
    url = f"https://graph.facebook.com/v25.0/{media_id}/insights"
    if media_type in ("VIDEO", "REELS"):
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
        if "total_value" in metric:
            today_str = datetime.now(timezone.utc).date().isoformat()
            data_by_date.setdefault(today_str, {})[name] = metric["total_value"].get("value", 0)
        elif "values" in metric:
            for entry in metric["values"]:
                date_str = entry.get("end_time", "")[:10]
                if not date_str:
                    continue
                data_by_date.setdefault(date_str, {})[name] = entry.get("value", 0)

    print(f"[DEBUG] data_by_date: {data_by_date}")

    existing = sheet.get_all_values()
    if not existing or not existing[0] or existing[0][0] != "date / 日付":
        sheet.insert_row(ACCOUNT_HEADERS, 1)
        existing_rows = {}
    else:
        existing_rows = {row[0]: idx + 2 for idx, row in enumerate(existing[1:]) if row and row[0]}

    sorted_dates = sorted(data_by_date.keys())
    update_batch = []  # 既存行の更新をまとめる
    append_batch = []  # 新規行の追加をまとめる

    for date_str in sorted_dates:
        d = data_by_date[date_str]
        total = followers_total if date_str == sorted_dates[-1] else ""
        row_data = [
            date_str,
            d.get("reach", ""),
            d.get("follower_count", ""),
            total,
        ]
        if date_str in existing_rows:
            row_num = existing_rows[date_str]
            update_batch.append({
                "range": f"A{row_num}:D{row_num}",
                "values": [row_data]
            })
        else:
            append_batch.append(row_data)

    # 一括書き込み（API呼び出しを最小化）
    if update_batch:
        sheet.batch_update(update_batch)
    if append_batch:
        sheet.append_rows(append_batch)

    print(f"アカウントデータ: 新規{len(append_batch)}行 / 更新{len(update_batch)}行")

# --- 投稿データ書き込み ---
def write_post_data(sheet, followers_total):
    media_list = fetch_media_list()

    existing = sheet.get_all_values()
    if not existing or not existing[0] or existing[0][0] != "post_id / 投稿ID":
        sheet.insert_row(POST_HEADERS, 1)
        existing_rows = {}
    else:
        existing_rows = {row[0]: idx + 2 for idx, row in enumerate(existing[1:]) if row and row[0]}

    update_batch = []
    append_batch = []

    for media in media_list:
        media_id = media["id"]
        media_type = media.get("media_type", "")
        insights = fetch_media_insights(media_id, media_type)

        like_count = media.get("like_count", 0)
        comments_count = media.get("comments_count", 0)
        reach = insights.get("reach", 0)
        saved = insights.get("saved", 0)

        if followers_total > 0:
            engagement_rate = round(
                (like_count + comments_count + saved) / followers_total * 100, 2
            )
        else:
            engagement_rate = ""

        caption = media.get("caption", "")[:50] if media.get("caption") else ""

        row_data = [
            media_id,
            media.get("timestamp", "")[:19].replace("T", " "),
            media_type,
            caption,
            like_count,
            comments_count,
            reach,
            saved,
            engagement_rate,
        ]

        if media_id in existing_rows:
            row_num = existing_rows[media_id]
            update_batch.append({
                "range": f"A{row_num}:I{row_num}",
                "values": [row_data]
            })
        else:
            append_batch.append(row_data)

    # 一括書き込み (429対策)
    if update_batch:
        sheet.batch_update(update_batch)
    if append_batch:
        sheet.append_rows(append_batch)

    print(f"投稿データ: 新規{len(append_batch)}件 / 更新{len(update_batch)}件")

    # timestamp列（B列）で降順ソート、常に新しい投稿が一番上に来るようにする
    all_values = sheet.get_all_values()
    if len(all_values) > 1:
        data_rows = all_values[1:]
        data_rows.sort(key=lambda r: r[1] if len(r) > 1 else "", reverse=True)
        sheet.update(range_name=f"A{row_num}:D{row_num}", values=[row_data])
        print("post_data を timestamp 降順でソートしました")
    
def fetch_tagged_media():
    """okinawa_ai_it がタグ付け or 共同投稿者になっている投稿を取得"""
    url = f"https://graph.facebook.com/v25.0/{IG_ACCOUNT_ID}/tags"
    params = {
        "fields": "id,timestamp,media_type,media_product_type,caption,like_count,comments_count",
        "limit": 50,
        "access_token": ACCESS_TOKEN,
    }
    res = requests.get(url, params=params)
    if res.status_code != 200:
        print(f"[DEBUG] tags endpoint error: {res.text[:300]}")
        return []
    data = res.json().get("data", [])
    print(f"[DEBUG] tagged media count: {len(data)}")
    for i, m in enumerate(data[:5]):
        print(f"[DEBUG] tagged #{i+1} {m.get('timestamp')} | {m.get('media_type')} | {m.get('id')}")
    return data
# --- メイン処理 ---
# --- メイン処理 ---
def main():
    spreadsheet = get_spreadsheet()
    raw_sheet = spreadsheet.worksheet("raw_data")
    post_sheet = spreadsheet.worksheet("post_data")
    followers_total = fetch_followers()
    write_account_data(raw_sheet, followers_total)
    write_post_data(post_sheet, followers_total)

    # ▼ 診断: /tags エンドポイントで共同投稿が取れるかテスト
    print("=" * 50)
    print("=== タグ付け投稿の取得テスト ===")
    fetch_tagged_media()

if __name__ == "__main__":
    main()
