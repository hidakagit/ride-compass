---
paths:
  - "backend/app/**"
  - "frontend/src/lib/**"
  - "frontend/src/hooks/useDebugLog.ts"
  - "frontend/src/components/DebugConsole/**"
---

# ログ方針（実運用調査のためのログレベル・粒度）

本番のbackendコンテナのログだけで障害調査を完結できるようにする。

## 基本原則

1. **エラーは常時出す。** `debug_mode`はDEBUGレベルの詳細イベントを増やすためのスイッチであり、
   エラー・警告の出力有無を切り替えるものではない。
2. **1リクエスト=1行のサマリを常時(INFO)、イベント単位の詳細はdebug_mode時(DEBUG)。**
   常時出す行は「あとで数えなくて済む」集約済みの情報にする。
3. **すべてのログにリクエストIDが付く。** `%(correlation_id)s`はフォーマッタが自動で付ける
   （`infrastructure/request_log.py`）ので、個々のログにIDを書き込まない。
4. **常時出るログ(INFO以上)の座標は小数2桁(≈1km)へ丸める。** 道路のノードのOSMのid（`osm-node-…`）と、OSMの道のidを
   含む区間の鍵（`way-…`）も座標に数え、常時出るログとそこへ載る例外の文には書かない。ノードは小数2桁の地点で、
   区間は件数で書く。DEBUGはそのまま出してよい。APIキー・認証ヘッダはどのレベルでも出さない。

## レベルの使い分け

| レベル | 出力条件 | 用途 |
|---|---|---|
| ERROR | 常時 | 未処理例外（スタックトレース付き）、想定外の内部エラー |
| WARNING | 常時 | 外部API失敗、429拒否、候補0件などユーザー影響のある準異常。**同種の警告はカテゴリごとに抑制**（`debug_log.py: log_throttled_warning`） |
| INFO | 常時 | リクエスト1件=1行のアクセスサマリ、ルート生成のステージサマリ、起動時の構成スナップショット |
| DEBUG | debug_mode時のみ | 外部API/キャッシュのイベント単位ログ、方位別のtrace失敗理由、距離フィルタの棄却詳細 |

## 使う仕組み（新規実装はこれらを使うこと）

### 外部API・キャッシュアクセス → `log_external_call`

`app/infrastructure/debug_log.py: log_external_call(category, **fields)`で囲む。
成功はDEBUG、失敗（例外 or `fields["result"]="error"`）は抑制付きWARNINGが自動で出て、
`/api/debug/stats`の統計（呼び出し数・エラー数・キャッシュヒット率・平均/最大所要時間）にも自動集計される。

- カテゴリ名は`ドメイン:サービス名`形式（例: `msm:read`, `weather:jma-tile`,
  `basemap:openfreemap`）。`log_throttled_warning`のカテゴリも同じ形にする。
- キャッシュを挟む場合は`fields["cache"] = "hit" / "miss"`を必ず設定する。
- 失敗は`fields["result"] = "error"`で示す（例外を捕まえて倒すときは下の`mark_failed`）。集計が失敗として
  数えるのはこれと捕まえずに送り出した例外だけで、ほかは成功に数える。`"ok"`等の状態は、ログに
  残したいときだけ書く。HTTPステータスは`fields["status"]`、クォータ系ヘッダがあれば`fields["quota_remaining"]`等で残す。
- 「取得できないのが正常」なケース（GSIの整備区域外等）は`fields["result"]`を`"error"`にせず
  理由を別フィールドへ残し（`fields["status"]=404`等）、WARNINGでログを埋めない
  （`gsi_tile_client.py: GsiTileClient.get`の404分岐が実例）。
- 例外を捕まえて既定値（空・None）へ倒すときは、`debug_log.py: mark_failed`で失敗を記録する。
  独自のWARNINGを書き足さない——対象を示す値（対象のタイル・ID等）は`log_external_call`へ渡す`fields`に入れる。
  捕まえずに送り出す例外は何も書かなくてよい。
- **タイル単位の口**（タイル1枚ごとに呼ばれる処理と、そこから呼ばれるキャッシュ等の下の層）では、
  呼び出しの失敗ではない劣化（入力の時刻が予報の範囲外・キャッシュを読めず取り直す・補間できない等）を
  知らせる警告を`debug_log.py: log_throttled_warning`で出し、`logger.warning`を直接書かない。タイルでない口でも、利用者の
  要求ごとに通り、要求の中身に依らない原因（配信元の配色・コード・配信の止まり、置き場のファイル、プロキシの設定等）を
  知らせる警告は同じにする。1回の操作で1度しか通らない口（ルート生成・定期の同期・起動時の確認等）は、この限りでない。
- **hit/missを数えるのは、値を使う側の`log_external_call`の1か所**。その下のキャッシュの層（例: ディスクの
  `tile_cache.py`・`tile_persistent_cache.py`）は`log_external_call`で囲まず、失敗だけを`debug_log.py: log_throttled_warning`で
  出す（同じ読みを二重に数えない）。失敗しないプロセス内メモリだけの層（例: `infrastructure/detour_ratio_cache.py`）は
  どちらも出さない。

### 429拒否 → `record_rate_limit_rejection`

レート制限・同時実行制限で429を返す箇所では`record_rate_limit_rejection(category, client_id, limit)`を呼ぶ。

### リクエストID

- ミドルウェア（`asgi_correlation_id`の`CorrelationIdMiddleware`、`main.py`で登録）が全リクエストへ
  付与し、レスポンスの`X-Request-ID`で返す。
- フロントの`lib/apiClient.ts`はレスポンスヘッダから読み、DebugConsoleのdetailに含める
  （画面へ出す失敗の文言には混ぜない）。DebugConsoleのreq値でbackendのログを検索すれば、そのリクエストの全ログが引ける。
- backendを呼ぶ新しい呼び出しも骨格`lib/apiClient.ts: requestApi`を通す（requestIdのログは骨格が持つ）。

### ログの時刻

- backendのログ行は**JST＋オフセット付き**（`2026-09-18 09:00:30,840+0900`）。整形は
  `request_log.py: JstLogFormatter`が行い、書式は`request_log.py: LOG_FORMAT`の1つだけ。
- フロントのデバッグログはブラウザのローカル時刻。backendのログと並べて読めるよう、時間帯を揃える。
- コンテナの`TZ`は変えない（[modules/backend/cross-cutting-infrastructure.md](../../docs/modules/backend/cross-cutting-infrastructure.md)）。

### 処理ステージのサマリ

複数ステージからなる高コスト処理（ルート生成等）は、ステージ別所要時間と
**中間結果の減り方**（折返し点候補→trace成功→距離フィルタ通過→上位n件）を1行のINFOに
まとめる（`route_generator.py`参照）。ユーザーに何も返せない結果（候補0件等）は
WARNINGへ昇格し、原因の内訳（どの段で減ったか）を同じ行に含める。

### 外部データの読み飛ばし

外部から配られるデータ（CSV・JSONの配列等）を読むパーサが、形の合わない記録を飛ばして
続けるときは、**飛ばした件数と総件数を取得1回につき1行のWARNING**で出す（1件でも
飛ばしたら）。行ごとには出さない。配布元が宣言した除外（運用終了済みの地点等）と空行は、
飛ばした件数に数えない（`infrastructure/wbgt_client.py: _parse_point_master`）。

## 観測エンドポイント

障害調査で読む運用エンドポイント（例: デプロイ確認の`/health`・集計の`/api/debug/stats`）の応答の項目は
[cross-cutting-infrastructure.md](../../docs/modules/backend/cross-cutting-infrastructure.md)「運用エンドポイント（`api/routers/health.py`）」が持つ。
`/api/debug/stats`の集計はプロセス内のカウンタで、デプロイ・再起動で0へ戻る（起点は`started_at`）。

## その他の運用上の注意

- uvicorn標準のアクセスログは本番（`backend/Dockerfile`）では`--no-access-log`で無効化する。
  アクセスサマリは`ridecompass.access`ロガーの1行ログが正。
- ロガー名は`ridecompass.<用途>`（例: `ridecompass.access`・`ridecompass.generate`。
  モジュール固有のものは`ridecompass.<モジュール名>`）。新しい用途を増やす場合も同じ
  接頭辞を使う——接頭辞単位でレベルを制御したとき、別接頭辞のロガーだけが漏れるため。
  `tests/structure/test_canonical_definitions.py`が`getLogger`の引数を走査して機械的に検査する
  （外部ライブラリのロガーをレベル制御のために名指しする場合だけ
  `test_canonical_definitions.py: EXTERNAL_LIBRARY_LOGGERS`で除外する）。
- CPUバウンドの重い処理（グラフ構築・MVTエンコード等）を追加する場合も、外部APIと同様に所要時間を計測対象にする。
