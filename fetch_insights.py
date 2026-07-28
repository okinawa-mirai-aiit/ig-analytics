import os
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone, timedelta
import json
import time

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
    "caption / キャプション(先頭200文字)",
    "like_count / いいね数",
    "comments_count / コメント数",
    "reach / リーチ数",
    "saved / 保存数",
    "engagement_rate / エンゲージメント率(%)",
]

# --- 投稿の日次スナップショット(伸びの速さを追うための時系列データ) ---
POST_HISTORY_SHEET_NAME = "post_history"
POST_HISTORY_HEADERS = [
    "post_id / 投稿ID",
    "post_date / 投稿日",
    "snapshot_date / 取得日",
    "like_count / いいね数",
    "comments_count / コメント数",
    "reach / リーチ数",
    "saved / 保存数",
    "days_since_post / 投稿からの経過日数",
]


# --- Google Sheets 認証 ---
def get_spreadsheet():
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)


# --- ワークシート取得(存在しなければヘッダー付きで新規作成) ---
def get_or_create_worksheet(spreadsheet, title, headers):
    try:
        sheet = spreadsheet.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        print(f"[DEBUG] シート '{title}' が存在しないため新規作成します")
        sheet = spreadsheet.add_worksheet(title=title, rows=2000, cols=len(headers))
        sheet.insert_row(headers, 1)
        return sheet

    existing = sheet.get_all_values()
    if not existing or not existing[0] or existing[0][0] != headers[0]:
        sheet.insert_row(headers, 1)
    return sheet


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


# --- Business Discovery API でコラボアカウントの投稿情報を一括取得 ---
def fetch_business_discovery_media(username, limit=25):
    """指定したコラボアカウント(クリエイター/ビジネスアカウント限定)の
    公開投稿一覧を取得する。自分のアクセストークンのみで、相手のトークン
    不要でいいね数・コメント数などの公開情報が取得できる。
    戻り値は {media_id: {like_count, comments_count, caption, ...}} の辞書。
    """
    url = f"https://graph.facebook.com/v25.0/{IG_ACCOUNT_ID}"
    fields = (
        f"business_discovery.username({username})"
        f"{{media.limit({limit}){{id,caption,comments_count,like_count,media_type,timestamp,permalink}}}}"
    )
    params = {"fields": fields, "access_token": ACCESS_TOKEN}
    res = requests.get(url, params=params)
    if res.status_code != 200:
        print(f"[DEBUG] business_discovery failed for @{username}: {res.text[:200]}")
        return {}

    media_list = (
        res.json()
        .get("business_discovery", {})
        .get("media", {})
        .get("data", [])
    )
    print(f"[DEBUG] business_discovery @{username}: {len(media_list)}件取得")
    return {m["id"]: m for m in media_list if "id" in m}


# --- 共同投稿(タグ付け)取得 ---
def fetch_tagged_media():
    """okinawa_ai_it が共同投稿者になっている投稿を取得"""
    url = f"https://graph.facebook.com/v25.0/{IG_ACCOUNT_ID}/tags"

    # フィールドと件数を段階的に減らして試す
    attempts = [
        ("id,timestamp,username", 5),
        ("id,username", 3),
        ("id", 1),
    ]

    data = []
    for fields, limit in attempts:
        for attempt in range(2):
            params = {
                "fields": fields,
                "limit": limit,
                "access_token": ACCESS_TOKEN,
            }
            res = requests.get(url, params=params)
            if res.status_code == 200:
                data = res.json().get("data", [])
                print(f"[DEBUG] tagged fetched: {len(data)} items (fields='{fields}', limit={limit})")
                break
            else:
                print(f"[DEBUG] failed fields='{fields}' limit={limit} attempt {attempt+1}: {res.text[:200]}")
                if attempt == 0:
                    time.sleep(2)
        if data:
            break

    if not data:
        print("[DEBUG] タグ付け投稿の取得に失敗(全パターンでエラー)")
        return []

    # username が取れている場合のみフィルタ、取れていない場合は全件通す
    if any("username" in m for m in data):
        filtered = [m for m in data if m.get("username") in COLLAB_USERNAMES]
    else:
        filtered = data
    print(f"[DEBUG] 共同投稿フィルタ後: {len(filtered)}/{len(data)}件")

    # --- Business Discovery API でコラボアカウントの投稿情報(いいね数・コメント数)を一括取得 ---
    # /tags の情報だけではいいね数・コメント数が信頼できないため、各コラボ
    # アカウント(クリエイターアカウント化済み)の公開投稿一覧(最大25件)を
    # Business Discovery経由で取得し、media_idをキーにしたルックアップ辞書を作る。
    bd_lookup = {}
    for username in COLLAB_USERNAMES:
        bd_lookup.update(fetch_business_discovery_media(username))
        time.sleep(0.3)

    # 各投稿について詳細情報を付与
    enriched = []
    bd_hit_count = 0
    for m in filtered:
        media_id = m["id"]
        enriched_data = dict(m)

        if media_id in bd_lookup:
            # Business Discoveryで取得できた場合はそちらを優先
            # (いいね数・コメント数の取得成功率が高い)
            enriched_data.update(bd_lookup[media_id])
            bd_hit_count += 1
        else:
            # フォールバック: 直接メディアIDを叩く(所有者でないため失敗しやすい)
            detail_url = f"https://graph.facebook.com/v25.0/{media_id}"
            detail_params = {
                "fields": "media_type,media_product_type,caption,like_count,comments_count,permalink,timestamp,username",
                "access_token": ACCESS_TOKEN,
            }
            detail_res = requests.get(detail_url, params=detail_params)
            if detail_res.status_code == 200:
                enriched_data.update(detail_res.json())
            else:
                print(f"[DEBUG] detail fetch failed for {media_id}: {detail_res.text[:150]}")

        enriched.append(enriched_data)
        time.sleep(0.3)

    print(f"[DEBUG] enrich完了: {len(enriched)}件 (business_discovery一致: {bd_hit_count}件)")
    for i, m in enumerate(enriched[:5]):
        print(f"[DEBUG] collab #{i+1}: {m.get('timestamp')} | {m.get('media_type', 'N/A')} | @{m.get('username')} | {m.get('id')} | like={m.get('like_count')} | comments={m.get('comments_count')}")

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
        existing = sheet.get_all_values()

    # 当日は集計未完了のため除外
    today_utc = datetime.now(timezone.utc).date().isoformat()
    data_by_date.pop(today_utc, None)

    sorted_dates = sorted(data_by_date.keys())

    # --- タスクA: 同日重複行の防止 ---
    # 書き込み対象日(sorted_dates)と一致する既存行をすべて削除してから
    # 新しいデータを書き込み直すことで、シート内に同じ日付の行が
    # 複数残ってしまう不具合を防ぐ。
    target_dates = set(sorted_dates)
    existing_data_rows = [row for row in existing[1:] if row and row[0]]

    # 既存データから日付ごとの代表行(followers_total引き継ぎ用)を作る
    # 同日重複がすでに存在していた場合は最初に見つかった行を採用する
    existing_by_date = {}
    for row in existing_data_rows:
        existing_by_date.setdefault(row[0], row)

    # 書き込み対象日に該当する行はここで除外(=削除)する
    remaining_rows = [row for row in existing_data_rows if row[0] not in target_dates]

    new_rows = []
    for date_str in sorted_dates:
        d = data_by_date[date_str]

        # 最新日のみ実値、それ以外は既存値を維持(空文字で潰さない)
        if date_str == sorted_dates[-1]:
            total = followers_total
        elif date_str in existing_by_date:
            prev_row = existing_by_date[date_str]
            total = prev_row[3] if len(prev_row) > 3 else ""
        else:
            total = ""

        row_data = [
            date_str,
            d.get("reach", ""),
            d.get("follower_count", ""),
            total,
        ]
        new_rows.append(row_data)

    # 削除後の既存行 + 新規/更新行をまとめて date 昇順で並べ直す
    all_rows = remaining_rows + new_rows
    all_rows.sort(key=lambda r: r[0])
    all_rows = [(r + [""] * 4)[:4] for r in all_rows]

    # 既存範囲を一旦クリアしてから、重複のない状態で全行を書き込み直す
    clear_range_end = max(len(existing), len(all_rows) + 1)
    sheet.batch_clear([f"A2:D{clear_range_end}"])
    if all_rows:
        # value_input_option="USER_ENTERED" を指定し、"YYYY-MM-DD"文字列を
        # スプレッドシート上で日付型として認識させる(文字列型のままだと
        # Looker Studio側で日付として正しくソート・表示できないため)
        sheet.update(
            range_name=f"A2:D{len(all_rows) + 1}",
            values=all_rows,
            value_input_option="USER_ENTERED",
        )

    print(f"アカウントデータ: 対象{len(new_rows)}日分を書き込み(同日重複削除後、合計{len(all_rows)}行)")


# --- 投稿の日次スナップショットを post_history に追記 ---
def write_post_history(history_sheet, snapshot_rows):
    """post_id + snapshot_date の組で当日分をすでに記録済みならスキップし、
    重複行が積み上がらないようにする(手動再実行/1日複数回実行への対策)。
    days_since_post(H列)はPythonで計算した静的な値ではなく、シート上の
    数式 "=C{row}-B{row}"(取得日-投稿日)として書き込む。こうすることで
    タイムスタンプのパース失敗などがあっても空白にならず、常にB列・C列
    から自動計算される。"""
    existing = history_sheet.get_all_values()
    existing_keys = {
        (row[0], row[2]) for row in existing[1:] if len(row) > 2 and row[0]
    }

    append_batch = [
        row for row in snapshot_rows
        if (row[0], row[2]) not in existing_keys
    ]

    if append_batch:
        start_row = len(existing) + 1
        for i, row in enumerate(append_batch):
            sheet_row = start_row + i
            row[-1] = f"=C{sheet_row}-B{sheet_row}"
        history_sheet.append_rows(append_batch, value_input_option="USER_ENTERED")

    skipped = len(snapshot_rows) - len(append_batch)
    print(f"post_history: 新規{len(append_batch)}件を追記(本日分の重複{skipped}件はスキップ、days_since_postは数式で計算)")


# --- 投稿データ書き込み ---
def write_post_data(sheet, history_sheet, followers_total):
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
    history_rows = []
    today_str = datetime.now(timezone.utc).date().isoformat()

    for media in unique_media:
        media_id = media["id"]
        media_type = media.get("media_type", "")

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

        raw_caption = media.get("caption", "") or ""
        caption_body = raw_caption[:200] if raw_caption else ""

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

        # --- post_history 用スナップショット行を作成 ---
        # days_since_post(最後の要素)はここではプレースホルダとし、
        # write_post_history側でシート数式 "=C-B" として埋める。
        posted_date_str = media.get("timestamp", "")[:10]

        history_rows.append([
            media_id,
            posted_date_str,
            today_str,
            like_count,
            comments_count,
            reach,
            saved,
            "",
        ])

    if update_batch:
        sheet.batch_update(update_batch, value_input_option="USER_ENTERED")
    if append_batch:
        sheet.append_rows(append_batch, value_input_option="USER_ENTERED")

    print(f"投稿データ: 新規{len(append_batch)}件 / 更新{len(update_batch)}件")

    # post_history に日次スナップショットを追記(伸びの速さ計算用)
    if history_rows:
        write_post_history(history_sheet, history_rows)

    # timestamp列(B列)で降順ソート、常に新しい投稿が一番上に来るようにする
    time.sleep(2)
    all_values = sheet.get_all_values()
    if len(all_values) > 1:
        data_rows = [r for r in all_values[1:] if r and r[0]]
        data_rows.sort(key=lambda r: r[1] if len(r) > 1 else "", reverse=True)
        data_rows = [(r + [""] * 9)[:9] for r in data_rows]
        sheet.batch_clear([f"A2:I{len(all_values)}"])
        # timestamp列("YYYY-MM-DD HH:MM:SS")も日付型として認識させる
        sheet.update(
            range_name=f"A2:I{len(data_rows) + 1}",
            values=data_rows,
            value_input_option="USER_ENTERED",
        )
        print(f"post_data を timestamp 降順でソートしました ({len(data_rows)}行)")


# --- メイン処理 ---
def main():
    spreadsheet = get_spreadsheet()
    raw_sheet = spreadsheet.worksheet("raw_data")
    post_sheet = spreadsheet.worksheet("post_data")
    history_sheet = get_or_create_worksheet(
        spreadsheet, POST_HISTORY_SHEET_NAME, POST_HISTORY_HEADERS
    )
    followers_total = fetch_followers()
    write_account_data(raw_sheet, followers_total)
    write_post_data(post_sheet, history_sheet, followers_total)


if __name__ == "__main__":
    main()
