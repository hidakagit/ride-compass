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
3. **すべてのログにリクエストIDが付く。** `%(request_id)s`はフォーマッタが自動で付ける
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

- カテゴリ名は`ドメイン:サービス名`形式（例: `weather:open-meteo`, `elevation:gsi-dem`,
  `basemap:openfreemap`）。
- キャッシュを挟む場合は`fields["cache"] = "hit" / "miss"`を必ず設定する（ヒット率集計の元）。
- 結果は`fields["result"] = "ok" / "error" / その他の状態`を設定する。HTTPステータスは
  `fields["status"]`、クォータ系ヘッダがあれば`fields["quota_remaining"]`等で残す。
- 「取得できないのが正常」なケース（GSIの守備範囲外等）はerror以外のresult値
  （例: `no_elevation`）にして、WARNINGでログを埋めない。
- 呼び出し元が例外を自前でcatchし、対象ID等より詳細な文脈付きの独自WARNINGを既に
  出している場合は、`fields["result"]="error"`に加えて`fields["warned"]=True`を設定する。
  `log_external_call`自身の二重WARNING出力だけ抑制しつつ、`/api/debug/stats`のerror集計には
  正しく計上される（`fields["lookup"]`等resultを避ける専用フィールド名にして集計自体を
  諦める必要はない）。あわせて`fields["error_type"] = error_type_label(exc)`も設定し、
  `error_types`集計が`"unknown"`一色にならないようにする。

### 429拒否 → `record_rate_limit_rejection`

レート制限・同時実行制限で429を返す箇所では`record_rate_limit_rejection(category, client_id, limit)`
を呼ぶ。抑制付きWARNINGと`/api/debug/stats`の`rate_limit_rejections`集計が付く。

### リクエストID

- ミドルウェア（`request_log.py`）が全リクエストへ付与し、レスポンスの`X-Request-ID`で返す。
- フロントの`services/*.ts`はレスポンスヘッダから読み、DebugConsoleのdetailと
  失敗時のエラーメッセージ（`（req: xxx）`）に含める。ユーザー報告のreq値でRenderのログを
  検索すれば当該リクエストの全ログが引ける。
- 新しいfetch呼び出しを追加する場合も同じパターンでrequestIdをdebugLogへ含めること。

### 処理ステージのサマリ

複数ステージからなる高コスト処理（ルート生成等）は、ステージ別所要時間と
**中間結果の減り方**（8方位→trace成功→距離フィルタ通過→候補数）を1行のINFOにまとめる
（`route_generator.py`参照）。ユーザーに何も返せない結果（候補0件等）はWARNINGへ昇格し、
原因の内訳（どの段で減ったか）を同じ行に含める。

## 観測エンドポイント

- `GET /health` — commit・起動時刻（デプロイ確認）
- `GET /api/debug/stats` — カテゴリ別の外部呼び出し統計・キャッシュヒット率・429拒否数。
  プロセス内カウンタのためデプロイ/再起動でリセットされる（`started_at`で起点判別）。
  集計値のみで秘匿情報を含まないため常時公開。

## その他の運用上の注意

- uvicorn標準のアクセスログは本番（`backend/Dockerfile`）では`--no-access-log`で無効化済み。
  アクセスサマリは`ridecompass.access`ロガーの1行ログが正。ローカル`uvicorn`起動では
  両方出るが実害はない。
- ロガー名は`ridecompass.<用途>`（`external` / `access` / `generate` / `startup`）。
  新しい用途を増やす場合も同じ接頭辞を使う。
- CPUバウンドの重い処理（グラフ構築・MVTエンコード等）を追加する場合も、外部APIと同様に
  所要時間を計測対象にする（過去にイベントループ停止の原因になった実績があるため）。
