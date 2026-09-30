# ログ方針（実運用調査のためのログレベル・粒度）

RideCompassのログはRender（本番）のログストリームだけで障害調査を完結させることを目的とする。
**新しい機能・外部連携・エンドポイントを追加するときは、必ずこの方針に沿ってログを入れること。**

## 基本原則

1. **エラーは常時出す。** `debug_mode`はDEBUGレベルの詳細イベントを増やすためのスイッチであり、
   エラー・警告の出力有無を切り替えるものではない。実運用は`debug_mode=False`で動くため、
   DEBUGでしか出ないエラーは「存在しないログ」と同じ。
2. **1リクエスト=1行のサマリを常時(INFO)、イベント単位の詳細はdebug_mode時(DEBUG)。**
   タイル系は通常操作でも毎分数百イベントになるため、イベント単位ログを常時出すとRenderの
   ログが埋まる。常時出す行は「あとで数えなくて済む」集約済みの情報にする。
3. **すべてのログにリクエストIDが付く。** `%(correlation_id)s`はフォーマッタが自動で付ける
   （`infrastructure/request_log.py`）ので、個々のログにIDを書き込む必要はない。
4. **常時出るログ(INFO以上)の座標は小数2桁(≈1km)へ丸める。** ユーザーの現在地を必要以上に
   残さないため。DEBUGは調査精度を優先しそのまま出してよい。APIキー・認証ヘッダは
   どのレベルでも出さない。

## レベルの使い分け

| レベル | 出力条件 | 用途 |
|---|---|---|
| ERROR | 常時 | 未処理例外（スタックトレース付き）、想定外の内部エラー |
| WARNING | 常時 | 外部API失敗、429拒否、候補0件などユーザー影響のある準異常。**同種の警告はカテゴリごとに毎分5件で抑制**（`debug_log.py`の`_throttled_warning`） |
| INFO | 常時 | リクエスト1件=1行のアクセスサマリ、ルート生成のステージサマリ、起動時の構成スナップショット |
| DEBUG | debug_mode時のみ | 外部API/キャッシュのイベント単位ログ、方位別のtrace失敗理由、距離フィルタの棄却詳細 |

## 使う仕組み（新規実装はこれらを使うこと）

### 外部API・キャッシュアクセス → `log_external_call`

`app/infrastructure/debug_log.py`の`log_external_call(category, **fields)`で囲む。
成功はDEBUG、失敗（例外 or `fields["result"]="error"`）は抑制付きWARNINGが自動で出て、
`/api/debug/stats`の統計（呼び出し数・エラー数・キャッシュヒット率・平均/最大所要時間）にも
自動集計される。

- カテゴリ名は`ドメイン:サービス名`形式（例: `msm:read`, `elevation:gsi-dem`,
  `basemap:openfreemap`）。
- キャッシュを挟む場合は`fields["cache"] = "hit" / "miss"`を必ず設定する（ヒット率集計の元）。
- 結果は`fields["result"] = "ok" / "error" / その他の状態`を設定する。HTTPステータスは
  `fields["status"]`、クォータ系ヘッダがあれば`fields["quota_remaining"]`等で残す。
- 「取得できないのが正常」なケース（GSIの整備区域外等）は`fields["result"]="ok"`のまま
  理由を別フィールドへ残し（`fields["status"]=404`等）、WARNINGでログを埋めない
  （`gsi_tile_client.py`の404分岐が実例）。
- 例外を捕まえて既定値（空・None）へ倒すときは、`debug_log.py: mark_failed`で失敗を記録する。
  抜けるときに`/api/debug/stats`のerror集計（例外の種別つき）へ入り、抑制付きWARNINGが`fields`
  （対象のタイル・ID等）と例外を添えて出る。独自のWARNINGを書き足さない——対象を示す値は
  `log_external_call`へ渡す`fields`に入れれば警告に載る。捕まえずに送り出す例外は何も書かなくてよい
  （`log_external_call`が同じことをする）。
- 呼び出しの失敗ではない劣化（入力の時刻が予報の範囲外・観測の履歴が古い等）を知らせる警告は
  `debug_log.py: log_throttled_warning`で出す。**`logger.warning`を直接書かない**——タイル単位の口は
  地図の1画面ぶんのタイルが同時に当たるため、抑制の無い警告は1回の表示で数十行になる。
- **例外（`log_external_call`を使わないキャッシュ）**: `infrastructure/detour_ratio_cache.py`
  （プロセス内メモリのみのLRU）は、外部I/O自体を持たず失敗しうる経路が無いため対象外。
  `tile_persistent_cache.py`（ディスクI/O、失敗しうる）は`log_external_call`を経由せず専用loggerで
  直接「成功DEBUG・失敗WARNING常時」の同じ方針を実装している——`dynamic_way_value_cache.py`を
  読む配信サービス（`gradient_way_service.py`等）が`log_external_call`で囲み、そちらがhit/missを
  数えるため、下の層で二重に数えない。

### 429拒否 → `record_rate_limit_rejection`

レート制限・同時実行制限で429を返す箇所では`record_rate_limit_rejection(category, client_id, limit)`
を呼ぶ。抑制付きWARNINGと`/api/debug/stats`の`rate_limit_rejections`集計が付く。

### リクエストID

- ミドルウェア（`asgi_correlation_id`の`CorrelationIdMiddleware`、`main.py`で登録）が全リクエストへ
  付与し、レスポンスの`X-Request-ID`で返す。
- フロントの`lib/apiClient.ts`はレスポンスヘッダから読み、DebugConsoleのdetailに含める
  （画面へ出す失敗の文言には混ぜない）。DebugConsoleのreq値でbackendのログを検索すれば
  当該リクエストの全ログが引ける。
- backendを呼ぶ新しい呼び出しも`lib/apiClient.ts`の骨格（`requestApi`）を通す（requestIdのログは骨格が持つ）。

### ログの時刻

- backendのログ行は**JST＋オフセット付き**（`2026-09-18 09:00:30,840+0900`）。整形は
  `request_log.py: JstLogFormatter`が行い、書式（`LOG_FORMAT`）も同モジュールが1つだけ持つ。
- フロントのデバッグログはブラウザのローカル時刻。両者を並べて読むために時間帯を揃えてある。
- コンテナの`TZ`は変えない（素の`datetime.now()`の意味まで変わり、スケジューラ・DBへ書く
  時刻へ波及するため）。詳細は[modules/backend/cross-cutting-infrastructure.md]
  (modules/backend/cross-cutting-infrastructure.md)参照。

### 処理ステージのサマリ

複数ステージからなる高コスト処理（ルート生成等）は、ステージ別所要時間と
**中間結果の減り方**（折返し点候補→trace成功→距離フィルタ通過→上位n件）を1行のINFOに
まとめる（`route_generator.py`参照）。ユーザーに何も返せない結果（候補0件等）は
WARNINGへ昇格し、原因の内訳（どの段で減ったか）を同じ行に含める。

### 外部データの読み飛ばし

外部から配られるデータ（CSV・JSONの配列等）を読むパーサが、形の合わない記録を飛ばして
続けるときは、**飛ばした件数と総件数を取得1回につき1行のWARNING**で出す（1件でも
飛ばしたら）。行ごとには出さない——配布元の列構成が変わると全行に出る。配布元が宣言した
除外（運用終了済みの地点等）と空行は、飛ばした件数に数えない。全滅でなく一部が落ちる形は
表示も`/api/debug/stats`も正常に見えるため、このログでしか気づけない
（`infrastructure/wbgt_client.py: _parse_point_master`）。

## 観測エンドポイント

- `GET /health` — commit・起動時刻（デプロイ確認）
- `GET /api/debug/stats` — カテゴリ別の外部呼び出し統計・キャッシュヒット率・429拒否数。
  プロセス内カウンタのためデプロイ/再起動でリセットされる（`started_at`で起点判別）。
  集計値のみで秘匿情報を含まないため常時公開。

## その他の運用上の注意

- uvicorn標準のアクセスログは本番（`backend/Dockerfile`）では`--no-access-log`で無効化済み。
  アクセスサマリは`ridecompass.access`ロガーの1行ログが正。ローカル`uvicorn`起動では
  両方出るが実害はない。
- ロガー名は`ridecompass.<用途>`（`external` / `access` / `generate` / `startup`、
  モジュール固有のものは`ridecompass.<モジュール名>`）。新しい用途を増やす場合も同じ
  接頭辞を使う——接頭辞単位でレベルを制御したとき、別接頭辞のロガーだけが漏れるため。
  `tests/structure/test_canonical_definitions.py`が`getLogger`の引数を走査して機械的に検査する
  （外部ライブラリのロガーをレベル制御のために名指しする場合だけ`EXTERNAL_LIBRARY_LOGGERS`
  で除外する）。
- CPUバウンドの重い処理（グラフ構築・MVTエンコード等）を追加する場合も、外部APIと同様に
  所要時間を計測対象にする（過去にイベントループ停止の原因になった実績があるため）。
