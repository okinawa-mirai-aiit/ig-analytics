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
# 共同投稿として取り込むアカウント
COLLAB_USERNAMES = ["okimira_seitokai", "okimira_senmonrekei1"]

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

# --- 自分の投稿一覧取得 ---
def fetch_media_list():
    url = f"https://graph.facebook.com/v25.0/{IG_ACCOUNT_ID}/media"
    params = {
        "fields": "id,timestamp,media_type,media_product_type,caption,like_count,comments_count",
        "limit": 100,
        "access_token": ACCESS_TOKEN,
    }
    res = requests.get(url, params=params)
    res.raise_for_status()
    data = res.json().get("data", [])

    print(f"[DEBUG] media count returned: {len(data)}")
    for i, m in enumerate(data[:10]):
        print(f"[DEBUG] #{i+1} {m.get('timestamp')} | {m.get('media_type')} | product_type={m.get('media_product_type', 'N/A')} | {m.get('id')}")

    return data

# --- 共同投稿(タグ付け)取得 ---
import time

def fetch_tagged_media():
    """okinawa_ai_it が共同投稿者になっている投稿を取得"""
    url = f"https://graph.facebook.com/v25.0/{IG_ACCOUNT_ID}/tags"

    # フィールドを段階的に減らして試す(短いものから)
    field_sets = [
        "id,timestamp,username",
        "id,username",
        "id,timestamp",
    ]

    # 各フィールドセットで最大2回リトライ
    data = []
    used_fields = ""
    for fields in field_sets:
        for attempt in range(2):
            params = {
                "fields": fields,
                "limit": 10,
                "access_token": ACCESS_TOKEN,
            }
            res = requests.get(url, params=params)
            if res.status_code == 200:
                data = res.json().get("data", [])
                used_fields = fields
                print(f"[DEBUG] tagged fetched: {len(data)} items (fields='{fields}', attempt {attempt+1})")
                break
            else:
                print(f"[DEBUG] failed fields='{fields}' attempt {attempt+1}: {res.text[:200]}")
                if attempt == 0:
                    time.sleep(2)  # 2秒待ってリトライ
        if data:
            break

    if not data:
        print("[DEBUG] タグ付け投稿の取得に失敗(全パターンでエラー)")
        return []

    # 学校関連の共同投稿アカウントだけにフィルタ
    filtered = [m for m in data if m.get("username") in COLLAB_USERNAMES]
    print(f"[DEBUG] 共同投稿フィルタ後: {len(filtered)}/{len(data)}件")

    # 各投稿について、詳細情報を1件ずつ取得(可能な限り)
    enriched = []
    for m in filtered:
        media_id = m["id"]
        enriched_data = dict(m)  # コピー

        # 個別に詳細を取得(重いフィールドを個別に取る)
        detail_url = f"https://graph.facebook.com/v25.0/{media_id}"
        detail_params = {
            "fields": "media_type,media_product_type,caption,like_count,comments_count,permalink",
            "access_token": ACCESS_TOKEN,
        }
        detail_res = requests.get(detail_url, params=detail_params)
        if detail_res.status_code == 200:
            detail = detail_res.json()
            enriched_data.update(detail)
        else:
            # 失敗しても id, timestamp, username は残る
            print(f"[DEBUG] detail fetch failed for {media_id}: {detail_res.text[:150]}")

        enriched.append(enriched_data)
        time.sleep(0.3)  # レート制限対策で少し間隔をあける

    print(f"[DEBUG] enrich完了: {len(enriched)}件")
    for i, m in enumerate(enriched[:5]):
        print(f"[DEBUG] collab #{i+1}: {m.get('timestamp')} | {m.get('media_type', 'N/A')} | @{m.get('username')} | {m.get('id')}")

    return enriched

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
    update_batch = []
    append_batch = []

    for date_str in sorted_dates:
        d = data_by_date[date_str]
        # 最新日のみ実値、それ以外は既存値を維持（空文字で潰さない）
if date_str == sorted_dates[-1]:
    total = followers_total
elif date_str in existing_rows:
    row_idx = existing_rows[date_str] - 2
    total = existing[row_idx + 1][3] if len(existing[row_idx + 1]) > 3 else ""
else:
    total = ""
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

    if update_batch:
        sheet.batch_update(update_batch)
    if append_batch:
        sheet.append_rows(append_batch)

    print(f"アカウントデータ: 新規{len(append_batch)}行 / 更新{len(update_batch)}行")

# --- 投稿データ書き込み ---
def write_post_data(sheet, followers_total):
    # 自分の投稿と共同投稿の両方を取得
    media_list = fetch_media_list()
    tagged_list = fetch_tagged_media()

    # 統合(重複除去)
    all_media = media_list + tagged_list
    seen_ids = set()
    unique_media = []
    for m in all_media:
        mid = m.get("id")
        if mid and mid not in seen_ids:
            seen_ids.add(mid)
            unique_media.append(m)
    print(f"[DEBUG] 全投稿件数: 自分={len(media_list)} + 共同={len(tagged_list)} = ユニーク{len(unique_media)}件")

    existing = sheet.get_all_values()
    if not existing or not existing[0] or existing[0][0] != "post_id / 投稿ID":
        sheet.insert_row(POST_HEADERS, 1)
        existing_rows = {}
    else:
        existing_rows = {row[0]: idx + 2 for idx, row in enumerate(existing[1:]) if row and row[0]}

    update_batch = []
    append_batch = []

    for media in unique_media:
        media_id = media["id"]
        media_type = media.get("media_type", "")

        # 投稿インサイト取得(共同投稿の場合はオーナーじゃないので失敗する可能性あり、その場合は0)
        insights = fetch_media_insights(media_id, media_type)

        like_count = media.get("like_count", 0) or 0
        comments_count = media.get("comments_count", 0) or 0
        reach = insights.get("reach", 0)
        saved = insights.get("saved", 0)

        if followers_total > 0:
            engagement_rate = round(
                (like_count + comments_count + saved) / followers_total * 100, 2
            )
        else:
            engagement_rate = ""

        # キャプション処理(共同投稿には識別用プレフィックスを付ける)
        raw_caption = media.get("caption", "") or ""
        caption_body = raw_caption[:50] if raw_caption else ""

        collab_username = media.get("username")
        if collab_username and collab_username in COLLAB_USERNAMES:
            caption = f"🤝@{collab_username}: {caption_body}"
        else:
            caption = caption_body

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

    if update_batch:
        sheet.batch_update(update_batch)
    if append_batch:
        sheet.append_rows(append_batch)

    print(f"投稿データ: 新規{len(append_batch)}件 / 更新{len(update_batch)}件")

    # timestamp列(B列)で降順ソート、常に新しい投稿が一番上に来るようにする
    all_values = sheet.get_all_values()
    if len(all_values) > 1:
        data_rows = all_values[1:]
        data_rows.sort(key=lambda r: r[1] if len(r) > 1 else "", reverse=True)
        sheet.update(range_name=f"A2:I{len(all_values)}", values=data_rows)
        print("post_data を timestamp 降順でソートしました")

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
