# ログ方針（実運用調査のためのログレベル・粒度）

本番のbackendコンテナのログだけで障害を調べ切れるようにする。新しい機能・外部連携・エンドポイントを足すときは、この方針でログを入れる。

## 基本原則

1. **エラーは常時出す。** `debug_mode`はDEBUGの詳細イベントを増やすスイッチで、エラー・警告の有無は切り替えない。本番は
   `debug_mode=False`で動くため、DEBUGでしか出ないエラーは無いのと同じ。
2. **1リクエスト=1行のサマリを常時(INFO)、イベント単位の詳細はdebug_mode時(DEBUG)。** タイル系は通常の操作でも毎分数百イベントになり、
   本番のコンテナのログは大きさに上限があって古い分から捨てる（`deploy-backend.yml`の`--log-opt`）。常時出す行は、あとで数えなくて済む
   集約済みの情報にする。
3. **すべてのログにリクエストIDが付く。** `%(correlation_id)s`はフォーマッタが付ける（`infrastructure/request_log.py`）ので、個々のログに書かない。
4. **常時出るログ(INFO以上)の座標は小数2桁(≈1km)へ丸める。** 道路のノードのOSMのid（`osm-node-…`）と、OSMの道のidを含む区間の鍵（`way-…`）も
   座標に数え、常時出るログとそこへ載る例外の文には書かない（idは公開の地図で地点・道をそのまま引ける）。ノードは小数2桁の地点で、区間は件数で書く。
   DEBUGはそのまま出してよい。APIキー・認証ヘッダはどのレベルでも出さない。

## レベルの使い分け

| レベル | 出力条件 | 用途 |
|---|---|---|
| ERROR | 常時 | 未処理例外（スタックトレース付き）、想定外の内部エラー |
| WARNING | 常時 | 外部API失敗、429拒否、候補0件などユーザー影響のある準異常。**同種の警告はカテゴリごとに毎分5件で抑制**（`debug_log.py: _throttled_warning`） |
| INFO | 常時 | リクエスト1件=1行のアクセスサマリ、ルート生成のステージサマリ、起動時の構成スナップショット |
| DEBUG | debug_mode時のみ | 外部API/キャッシュのイベント単位ログ、方位別のtrace失敗理由、距離フィルタの棄却詳細 |

## 使う仕組み（新規実装はこれらを使うこと）

### 外部API・キャッシュアクセス → `log_external_call`

`app/infrastructure/debug_log.py: log_external_call(category, **fields)`で囲む。成功はDEBUG、失敗（例外か`fields["result"]="error"`）は
抑制付きWARNINGが出て、`/api/debug/stats`の統計（呼び出し数・エラー数・キャッシュヒット率・平均/最大所要時間）にも入る。

- カテゴリ名は`ドメイン:サービス名`の形（例: `msm:read`, `weather:jma-tile`, `basemap:openfreemap`）。`log_throttled_warning`のカテゴリも同じ形にする。
- キャッシュを挟むなら`fields["cache"] = "hit" / "miss"`を必ず入れる（ヒット率の元）。
- 失敗は`fields["result"] = "error"`で示す（例外を捕まえて倒すときは下の`mark_failed`）。集計が失敗に数えるのはこれと捕まえずに送り出した例外だけで、
  `"ok"`等の状態は集計に効かない（ログに残したいときだけ書く）。HTTPステータスは`fields["status"]`、クォータ系ヘッダがあれば`fields["quota_remaining"]`等で残す。
- 取れないのが正常な場合（GSIの整備区域外等）は`fields["result"]`を`"error"`にせず、理由を別のフィールド（`fields["status"]=404`等）へ残し、
  WARNINGを出さない（`gsi_tile_client.py`の404の分岐）。
- 例外を捕まえて既定値（空・None）へ倒すときは、`debug_log.py: mark_failed`で失敗を記録する。抜けるときに`/api/debug/stats`のerror集計
  （例外の種別つき）へ入り、抑制付きWARNINGが`fields`（対象のタイル・ID等）と例外を添えて出る。独自のWARNINGを書き足さず、対象を示す値は
  `fields`に入れる。捕まえずに送り出す例外は何も書かなくてよい（`log_external_call`が同じことをする）。
- **タイル単位の口**（タイル1枚ごとに呼ばれる処理と、そこから呼ばれるキャッシュ等の下の層）では、呼び出しの失敗ではない劣化（入力の時刻が
  予報の範囲外・キャッシュを読めず取り直す・補間できない等）の警告を`debug_log.py: log_throttled_warning`で出し、`logger.warning`を直接書かない
  （地図の1画面ぶんのタイルが同時に当たる）。タイルでない口でも、利用者の要求ごとに通り、要求の中身に依らない原因（配信元の配色・コード・
  配信の止まり、置き場のファイル、プロキシの設定等）の警告は同じにする。1回の操作で1度しか通らない口（ルート生成・定期の同期・起動時の確認等）は、この限りでない。
- **例外（`log_external_call`を使わないキャッシュ）**: `infrastructure/detour_ratio_cache.py`（プロセス内メモリのみのLRU）は外部I/Oを持たないので対象外。
  `tile_persistent_cache.py`（ディスクI/O）は成功を専用loggerのDEBUG、失敗を`log_throttled_warning`で出し、hit/missは`dynamic_way_value_cache.py`を
  読む配信サービス（`gradient_way_service.py`）の`log_external_call`が数える（下の層で二重に数えない）。`tile_cache.py`（タイルの生バイトのディスクキャッシュ）も
  同じ形で、hit/missは読むクライアント（`basemap_client.py`等）の`log_external_call`が数える。

### 429拒否 → `record_rate_limit_rejection`

レート制限・同時実行制限で429を返す箇所では`record_rate_limit_rejection(category, client_id, limit)`を呼ぶ。抑制付きWARNINGと
`/api/debug/stats`の`rate_limit_rejections`集計が付く。

### リクエストID

- ミドルウェア（`asgi_correlation_id`の`CorrelationIdMiddleware`、`main.py`で登録）が全リクエストへ付け、レスポンスの`X-Request-ID`で返す。
- フロントの`lib/apiClient.ts`はレスポンスヘッダから読み、DebugConsoleのdetailに含める（画面へ出す失敗の文言には混ぜない）。DebugConsoleのreq値で
  backendのログを検索すれば、そのリクエストの全ログが引ける。
- backendを呼ぶ新しい呼び出しも`lib/apiClient.ts`の骨格（`requestApi`）を通す（requestIdのログは骨格が持つ）。

### ログの時刻

- backendのログ行は**JST＋オフセット付き**（`2026-09-18 09:00:30,840+0900`）。整形は`request_log.py: JstLogFormatter`が行い、書式（`LOG_FORMAT`）も
  同じモジュールが1つだけ持つ。
- フロントのデバッグログはブラウザのローカル時刻で、両者を並べて読めるよう時間帯を揃えてある。
- コンテナの`TZ`は変えない（素の`datetime.now()`の意味が変わり、スケジューラ・DBへ書く時刻へ及ぶ）。詳細は
  [modules/backend/cross-cutting-infrastructure.md](../modules/backend/cross-cutting-infrastructure.md)。

### 処理ステージのサマリ

複数ステージからなる高コストの処理（ルート生成等）は、ステージ別の所要時間と**中間結果の減り方**（折返し点候補→trace成功→距離フィルタ通過→上位n件）を
1行のINFOにまとめる（`route_generator.py`）。ユーザーに何も返せない結果（候補0件等）はWARNINGにし、どの段で減ったかを同じ行に含める。

### 外部データの読み飛ばし

外部から配られるデータ（CSV・JSONの配列等）を読むパーサが、形の合わない記録を飛ばして続けるときは、**飛ばした件数と総件数を取得1回につき1行のWARNING**で
出す（1件でも飛ばしたら）。行ごとには出さない。配布元が宣言した除外（運用終了済みの地点等）と空行は、飛ばした件数に数えない。一部だけ落ちる形は表示も
`/api/debug/stats`も正常に見えるため、このログでしか気づけない（例: `infrastructure/wbgt_client.py: _parse_point_master`）。

## 観測エンドポイント

- `GET /health` — commit・起動時刻（デプロイの確認）
- `GET /api/debug/stats` — カテゴリ別の外部呼び出し統計・キャッシュヒット率・429拒否数。プロセス内のカウンタで、デプロイ・再起動で戻る（`started_at`で起点を見る）。
  集計値だけで秘匿情報を含まないため常時公開。

## その他の運用上の注意

- uvicorn標準のアクセスログは本番（`backend/Dockerfile`）では`--no-access-log`で切ってある。アクセスサマリは`ridecompass.access`ロガーの1行が正。
  ローカルの`uvicorn`では両方出る。
- ロガー名は`ridecompass.<用途>`（`external` / `access` / `generate` / `startup`、モジュール固有のものは`ridecompass.<モジュール名>`）。新しい用途も
  同じ接頭辞にする（接頭辞単位でレベルを絞ると、別の接頭辞のロガーだけが漏れる）。`tests/structure/test_canonical_definitions.py`が`getLogger`の引数を
  走査して検査する（外部ライブラリのロガーをレベル制御のために名指しする場合だけ`EXTERNAL_LIBRARY_LOGGERS`で除外する）。
- CPUバウンドの重い処理（グラフ構築・MVTエンコード等）を足すときも、外部APIと同じく所要時間を計測する（イベントループを止める原因になりうる）。
