---
title: ig-analytics データ・可視化リファレンス
description: 現状取得しているデータ(スプレッドシート構造)とLooker Studioダッシュボードのグラフ構成の記録
last_updated: 2026-09-01
---

# データソース

- リポジトリ: chongshengmiraimeta-glitch/ig-analytics (branch: main)
- 取得元API: Instagram Graph API v25.0
- 実行: `.github/workflows/fetch_insights.yml`（毎日 JST 9:00 / UTC 0:00、`fetch_insights.py` を実行。`workflow_dispatch` で手動実行も可）
- 書き込み先スプレッドシートID: `1SaVKe_sk7KAdjJlA0MEL7K71WnFEQ-i4Z85npcBzbzM`

## raw_data シート（アカウント全体の日次データ）

| 列 | 内容 |
|---|---|
| date / 日付 | 日付 |
| reach / リーチ数 | 当日のリーチ数 |
| follower_count_delta / フォロワー増減 | 当日のフォロワー増減数 |
| followers_total / フォロワー総数 | 最新日のみ実値、それ以外は既存値を維持 |

日付(A列)昇順でソートされる。当日分は集計未完了のため書き込み対象から除外される。

## post_data シート（投稿単位のデータ）

| 列 | 内容 |
|---|---|
| post_id / 投稿ID | メディアID |
| timestamp / 投稿日時 | 投稿日時 |
| media_type / 投稿タイプ | IMAGE / VIDEO / REELS 等 |
| caption / キャプション(先頭50文字) | 共同投稿の場合は🤝@usernameを先頭に付与 |
| like_count / いいね数 | いいね数 |
| comments_count / コメント数 | コメント数 |
| reach / リーチ数 | 投稿ごとのリーチ |
| saved / 保存数 | 保存数 |
| engagement_rate / エンゲージメント率(%) | (like+comments+saved)/followers_total×100 |

timestamp(B列)降順でソートされる。自分の投稿に加え、`COLLAB_USERNAMES`（okimira_seitokai, okimira_senmonrekei1）がタグ付けされた共同投稿も統合・重複除去して取り込む。

# Looker Studio ダッシュボード

- URL: https://datastudio.google.com/u/0/reporting/56d59152-8547-473f-8634-1163df0a4754/page/y7tzF
- タイトル: みらいAI&IT IGAnalytics
- ページ構成: 「無題のページ」が2つ存在するが、実際にグラフが配置されているのは1ページ目のみ（2ページ目は空・未使用）

## 1ページ目の掲載グラフ・指標

- 閲覧数（過去28日）: スコアカード
- 月間リーチ数（閲覧数の重複なし）: `reach_28d`（重複除去済みリーチ数）のスコアカード、確認時点で578,359
- 月間フォロワー増減数: `follower_count_delta`合計のスコアカード、確認時点で35
- 最新フォロワー数: `followers_total`最新値のスコアカード
- 日付別のリーチ数（閲覧数重複なし）: 折れ線グラフ（`reach`の日次推移）
- フォロワー数推移: 折れ線グラフ（`followers_total`の日次推移）
- 日付ごとのフォロワー数増減: 棒グラフ（`follower_count_delta`）
- 投稿の伸び速度ランキング（1日あたりのエンゲージメント数）: 横棒グラフ（`avg_velocity`、投稿ごとのランキング）
- 投稿ごとのコメント数＆いいね数: テーブル（投稿日時・キャプション先頭200文字・いいね数・コメント数など）
- 投稿ごとのいいね数の変動: 複数系列の折れ線グラフ（投稿別）
- 投稿ごとの閲覧数（リーチ数）の変動: 複数系列の折れ線グラフ（投稿別）

# 更新履歴

- 2026-09-01: 保守運用スキル整備に伴い、実データ・実ダッシュボードを確認した上で初版作成
