# 気象・動的レイヤー（backend）

## 責務

Open-Meteo（気象一般・風グリッド）・気象庁（アメダス・警報/注意報・タイル系ナウキャスト・
WBGT・洪水予報）・環境省（WBGT）由来のデータを取得・キャッシュし、地点の天候・警報・
地図タイルとして配信する。

このモジュールが扱う情報は大きく2系統に分かれる:
1. **バッジ系**（警報・WBGT・洪水予報・アメダス）: 出発地点1点に対する現在の警戒状態を
   返す。いずれも取得失敗時は例外にせず「情報なし」を返すfail-open方針。
2. **地図レイヤー系**（風グリッド・JMAタイル系ナウキャスト）: 広域の格子点・タイルを
   まとめて配信する。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `jma_tile_specs.py`（配信元のズーム仕様レジストリ）・`weather.py`・`jma_amedas.py`・`jma_area.py`・`jma_warning.py`・`wbgt.py`・`wbgt_points.py`・`twilight.py`・`night.py`・`flood_forecast.py` |
| services | `weather_service.py`・`jma_amedas_service.py`・`wbgt_service.py`・`warning_service.py`・`flood_service.py`・`jma_tile_prewarm_service.py`（定期プリウォームバッチ） |
| infrastructure | `weather_client.py`・`jma_tile_client.py`・`jma_tile_redis_cache.py`（タイル本体のRedis cache-aside）・`jma_tile_interpolation.py`（配信元が持たないズームの補間）・`jma_tile_index.py`（在否インデックス）・`jma_amedas_client.py`・`jma_warning_client.py`・`wbgt_client.py`・`flood_client.py`・`basemap_client.py`・`gsi_relief_tile_client.py`・`simple_api_client.py`（後者4クライアントが共有する定型文、後述） |
| api | `weather.py`・`jma_tile.py`・`basemap.py`・`gsi_relief_tile.py` |

## domain層: 2つの異なる役割

| ファイル | 役割 | 消費側 |
|---|---|---|
| `weather.py` | Open-Meteo応答のPydanticモデル（`WeatherConditions`・`WeatherPeriodOutlook`） | `weather_service.py` |
| `jma_amedas.py` | JMAアメダスの16方位コード変換・体感温度計算（BOM式）・`AmedasObservation`モデル | `jma_amedas_service.py` |
| `jma_area.py` | 緯度経度→JMA警報エリアコード（class20→class15→class10→office）の親子関係解決 | `warning_service.py`・`flood_service.py` |
| `jma_warning.py` | JMA警報コード表・アクティブ警報抽出 | `warning_service.py` |
| `wbgt.py` | WBGT警戒レベル判定（熱中症予防運動指針の5段階閾値）・提供期間判定 | `wbgt_service.py` |
| `wbgt_points.py` | 緯度経度→最寄りWBGT情報提供地点（約840地点の総当たり最近傍探索） | `wbgt_service.py` |
| `flood_forecast.py` | JMA指定河川洪水予報コード表・アクティブ予報抽出 | `flood_service.py` |
| `twilight.py` | 市民薄明による夜間判定（`is_night`）・日の出日没計算（`sunrise_sunset_jst`） | `jma_amedas_service.py`（表示用）・[routing-engine.md](routing-engine.md)のroad_graphエンジン（night軸の動的化） |
| `night.py` | way_tagsからnight軸材料フラグ（`lit`・`has_tunnel`）を解決 | road_graphエンジン |

`twilight.py`・`night.py`の2ファイルは外部APIに依存しないローカルの天文計算のみで、
実際の主消費者は[routing-engine.md](routing-engine.md)が主管する`road_graph_engine.py`
である。

## API（`api/routers/weather.py`）

| エンドポイント | データ源 | fail時 | レート制限/分 |
|---|---|---|---|
| `GET /api/weather` | Open-Meteo（今日の見通し: 日次集計・weather_code・UV指数等） | 502 | 60 |
| `GET /api/weather/warnings` | 気象庁警報・注意報 | 空（200） | 30 |
| `GET /api/weather/wbgt` | 環境省WBGT | 空（200） | 30 |
| `GET /api/weather/flood-forecast` | 河川洪水予報 | 空（200） | 30 |
| `GET /api/weather/amedas` | 気象庁アメダス実測値（Redis読み取り専用） | 502 | 30 |
| `GET /api/weather/wind-grid`・`/wind-grid-detail` | Open-Meteo風グリッド | 全滅時のみ502 | 20／30 |

`/api/weather`は常設ヘッダー用ではなく、「今日の見通し」パネル（日次集計・2時間おき8コマの
天気の流れ）専用。常設ヘッダー（気温・体感温度・風速風向の現在値）はアメダス実測を使う
`/api/weather/amedas`が担う。

fail-open方針の非対称性: 警報・WBGT・洪水予報は失敗時に警告なしとして返す。一方
`/api/weather`と`/api/weather/amedas`は取得失敗を502として明示的に伝える（表示の主対象に
なりうる数値のため）。

応答の`Cache-Control`は`api/cache_policy.py`の対応表が持つ（このモジュールのルーターは
ヘッダを書かない）。`/wind-grid`系は`SHORT`（5分）——応答が約48時間ぶんの時刻配列を持ち
どの時刻を描画するかはクライアントが選ぶうえ、上流（Open-Meteo）の更新は1時間ごとのため。
警報・WBGT・洪水予報・アメダスは`VOLATILE`（2分）、`/api/weather`は`SHORT`。502は2xxでは
ないためミドルウェアの対象外になる。

### JMAタイル系の共通プロキシ（`api/routers/jma_tile.py`）

`GET /api/jma-tile/{path:path}`が降水ナウキャスト・rasrf・雷/竜巻ナウキャスト・
キキクル・線状降水帯予測マップなど、気象庁のタイル系データを1つの汎用プロキシで中継する
（`path`をそのまま気象庁側へ引き渡す）。認証は無し。`JmaTileClient`はキャッシュ戦略を
2種類に分ける:

| 対象 | サーバー側キャッシュ方式 | TTL | 応答の`Cache-Control` |
|---|---|---|---|
| `targetTimes*.json`（`jma_tile_client.py: is_target_times_path`で判定） | プロセス内メモリ`TTLCache`（maxsize=16） | 2分 | `public, max-age=60` |
| タイル本体（ラスタPNG・洪水キキクルのベクタPBF） | `jma_tile_redis_cache.py`（Redis cache-aside、正本を持たない） | 20分 | `public, max-age=1200, immutable` |
| 404（`TileNotFound`） | 上記と同じキー・TTL | 20分 | `public, max-age=600` |
| 502（上流障害） | 保存しない | — | 付けない |

`Cache-Control`の値自体は`api/cache_policy.py`（`IMMUTABLE_TILE`・`JMA_TARGET_TIMES`・
`JMA_TILE_NOT_FOUND`）が持ち、このプロキシは1つのパスで性質の異なる3種類を返すため
対応表では`HANDLER_MANAGED`とし、どれを使うかだけを`jma_tile.py`が選ぶ
（[横断基盤](cross-cutting-infrastructure.md)「応答のCache-Control」参照）。

タイル本体のURLは`basetime`/`validtime`を含み内容が確定して以後変化しないため、`immutable`で
ブラウザに再検証させない。MapLibreはズームレベルの跨ぎ・画面外へのパン・`setTiles`による
ソース更新のたびに同じURLを引き直すため、この差が実リクエスト数に直結する。時刻一覧だけは
同じURLのまま内容が更新されるため`immutable`にできない。

**レート制限（300/分）の適用順序**: `jma_tile.py`は`JmaTileClient.get_cached(path)`で
まずキャッシュのみを参照し、ヒットすればレート制限を一切経由せず返す。ミスのときだけ
`enforce_rate_limit`→`JmaTileClient.fetch(path)`（外部フェッチ＋キャッシュ書き戻し）を
呼ぶ。`JmaTileClient.get(path)`（`get_cached`→ミスなら`fetch`の一括呼び出し）はレート
制限の適用順序を気にしない呼び出し元（プリウォームバッチ・テスト等）向けに残している。

**フェイルステータスの使い分け（改善計画T603）**: `fetch`は上流の404を`JmaTileNotFoundError`
として送出し、`jma_tile.py`はこれを404（他の失敗は502）として返す。降水・浸水想定区域等の
疎な格子状タイルは、ズームレベル・場所によって存在しないz/x/yが珍しくない正常系のため、
タイムアウト・5xx等の実際の障害と同列に502・WARNINGログ・`/api/debug/stats`のerror集計へは
乗せない。`get`（プリウォームバッチ等、404と他の失敗を区別する必要が無い呼び出し元向け）は
`JmaTileNotFoundError`をNoneへ揃えて返す（従来通り）。

**恒久404のキャッシュ（改善計画T605）**: 確認済みの404は`basetime`/`validtime`が確定した
過去の一時点への結果のため再フェッチしても変わらない。`fetch`が404を確認した時点で、
タイル本体は`jma_tile_redis_cache.set_not_found`（`TILE_NOT_FOUND`センチネル、実際のタイルと
同じキー・TTLで`{"not_found": true}`を保存）、`targetTimes*.json`はプロセス内`TTLCache`へ
直接`TILE_NOT_FOUND`を積む。`get_cached`/`get`が`TileNotFound`を受け取った場合、
`jma_tile.py`は上流へ再問い合わせせず即座に404を返す（レート制限も消費しない）。

**要素ごとのズーム上限（`domain/jma_tile_specs.py`）**: 配信元は要素ごとに`zoomUse`
（使用するズームの偶奇）と`maxNativeZoom`（画像が実在する最大ズーム）を持ち、**両方を
突き合わせないと実データの無いズームを指す**。`effective_max_zoom()`が
「`maxNativeZoom`以下で`zoomUse`の偶奇を満たす最大値」を導出し、MapLibreの`maxzoom`
（frontendへは`jma-tile-config.json`として配る）とプリウォームの対象ズームの両方が
この1箇所から決まる。

| 要素 | zoomUse | maxNativeZoom | 導出される上限 |
|---|---|---|---|
| `land`・`rain_mesh`・`inund`・`flood`（キキクル） | even | 11 | 10 |
| `hrpns`（降水ナウキャスト） | even | 10 | 10 |
| `thns`・`trns`（雷・竜巻） | even | 9 | **8** |
| `sjfcstmap`（線状降水帯予測マップ） | even | 10 | 10 |

上限を超えるズームを指定すると、その要素のタイルは存在せず空タイル（334バイトのRGBA PNG、
ベクタは0バイト）が返るため、地図から色が消える。上限の内側にある「偶奇の合わないズーム」
（キキクル・降水のz5/z7/z9、雷竜巻のz5/z7）も同じく空になるため、そちらは下記の補間で埋める。`sjfcstmap`だけは配信元の設定ファイルを
一次情報で確認できておらず（公式ページが設定を外部化していない）、同系統の`hrpns`と同じ値を
暫定的に置いている（`JmaTileSpec.verified=False`）。

**配信元が持たないズームの補間（`infrastructure/jma_tile_interpolation.py`）**:
MapLibreのソース設定は連続したズーム区間しか表現できず「偶数だけ使う」を伝えられないため、
`jma_tile.py`が要求されたズームに実データが無い場合（`source_zoom_for_interpolation`が
親ズームを返す場合）、1段上のタイルから該当象限を切り出して2倍に拡大した画像を返す。

- 親タイルの取得は`JmaTileClient.get()`を通すため、Redisキャッシュ・レート制限・上流への
  秒間上限がそのまま効く。補間結果は`JmaTileClient.store()`で**元のパスのキー**へ書き戻し、
  2回目以降は補間をやり直さない。
- **最近傍で拡大する**。キキクル・ナウキャストは危険度や強度を離散的な色で塗り分けており
  凡例の色と1対1に対応するため、滑らかに拡大すると凡例のどの段階でもない中間色が地図に出る。
- ラスタ（PNG）のみが対象。洪水キキクルはベクタタイルでMVTのジオメトリ再エンコードが必要
  なため対象外（奇数ズームでは洪水線が出ないが、同じ領域にキキクル3種の面が出る）。
- 親タイルが取得できない場合は補間せず通常のフェッチ経路へ進む（補間の失敗で地図表示
  そのものを落とさない）。

**在否インデックス（`infrastructure/jma_tile_index.py`・`GET /api/jma-tile-index`）**:
JMA動的タイルは疎で、平常時はほぼ全てのタイルが空である。`basetime`が10分ごとに変わり
URLも変わるため、ブラウザキャッシュ（`api/cache_policy.py`）では救えない。プリウォームが
運用範囲のタイルを取得する過程で在否を判定し（**追加の取得は発生しない**）、Redisへ記録する。

| 項目 | 内容 |
|---|---|
| 判定 | ラスタは全画素が透明か（`getchannel("A").getbbox()`）、ベクタは0バイトか |
| 判定不能時 | **「中身あり」に倒す**（誤って空と判定すると危険情報が表示されなくなる） |
| 保持 | `redis_json_cache`経由、固定キー1つにTTL20分。要素ごとに`basetime`が異なるためキーには含めず、ペイロード側の要素ごとに持たせる |
| `coverage` | インデックスが網羅する地理範囲。**この外は在否が不明**のためクライアントは従来どおり取得する |
| 未保存時 | `available: false`を返し、クライアントは従来どおり全タイルを取りに行く（インデックスが無いことで表示が欠けてはならない） |

**定期プリウォーム（`services/jma_tile_prewarm_service.py`）**: `main.py`のAPScheduler
（アメダスと同じ`interval`トリガー、`jma_tile_prewarm_interval_minutes`＝10分、
`next_run_time=datetime.now()`で起動直後にも即時実行）が、アプリの実運用範囲
（`domain/wind_grid.py: WIND_GRID_BBOX`）ぶんのタイルをあらかじめ`JmaTileClient.get()`
経由でRedisへ温める。対象ズームは上記`effective_max_zoom()`が導出した上限まで——超過
ズームはMapLibreがクライアント側で拡大表示するだけで追加の通信が発生しないため。雷/竜巻ナウキャストは
未来方向の予報フレームを複数持つが、プリウォームは直近の実況フレーム（1件）のみを
対象にする（キキクル・線状降水帯予測マップは元々未来フレームを持たないため対象外）。

**JMAへの実フェッチの秒間上限**: `jma_tile.py`の300/分（クライアント単位）とは別に、
`JmaTileClient.fetch`自身が実際にJMAへ問い合わせる直前で、プロセス全体で共有する
秒間上限（`settings.jma_tile_upstream_max_requests_per_second`、既定5.0）を守るよう
待機する。プリウォームバッチの同時実行数制御（`_MAX_CONCURRENCY=8`）だけでは総
スループット（秒間リクエスト数）自体は制御できないため、`fetch`という「実際にJMAへ
問い合わせる唯一の関数」1箇所に置くことで、プリウォーム・オンデマンドどちらの経路も
一律にこの上限へ従う。直前フェッチ時刻はモジュールレベルの状態として持つ
（`JmaTileClient`はリクエストごとに使い捨てでインスタンス化されるため）。

## 天候取得（`weather_service.py: WeatherService`）

| メソッド | 用途 | 時刻 | daily/weather_code |
|---|---|---|---|
| `get_conditions(point)` | `/api/weather`エンドポイント・`RoadGraphEngine`の起点判定 | 常に現在時刻 | 埋まる |
| `get_wind_forecast_series(point)` | `RoadGraphEngine`の探索前コスト合成（Edgeごとの通過予定時刻の風） | 時別風向・風速の系列（約48時間、JST）。`get_conditions`と同じ応答・キャッシュ | 対象外 |
| `get_wind_grid(points)` | 風グリッド・降水延長予報の地図レイヤー | 全hourly時系列（約48時間） | 対象外 |

## その他のサービス

- **`JmaAmedasService`（取得と配信の分離）**: `get_nearest_observation`は**Redis読み取り
  専用**（JMAへは問い合わせない）。`refresh_all_stations`が全国分を1回取得し観測所ごとに
  Redis Hash（`jma:amedas:{station_id}`、TTL 15分）へ書き戻す。

  **暗黙の前提**: `refresh_all_stations`はリクエスト経路からは呼ばれない。`app/main.py`の
  lifespan内でAPScheduler（`AsyncIOScheduler`）へ`interval`トリガー
  （`AMEDAS_REFRESH_INTERVAL_MINUTES`＝10分）で登録され、`next_run_time=datetime.now()`
  によりアプリ起動直後にも即時1回実行される。このサービスの可用性は
  「main.pyのスケジューラが正常に起動・稼働し続けているか」という、
  `jma_amedas_service.py`単体のコードからは読み取れない外部要因に依存する。バッチ失敗時は
  WARNINGでログされるのみで自動リトライは無く、次回の定期実行（最大10分後）まで観測値は
  更新されない（TTL 15分がバッチ間隔10分より長いため、1回の失敗では即502にならない）。

  日の出/日没（`sunrise`/`sunset`）はRedisへ保存せず、`get_nearest_observation`が
  クエリ地点（最寄り観測所ではなくリクエストの緯度経度そのもの）に対し都度
  `twilight.py: sunrise_sunset_jst`でローカル計算して埋め込む（地点依存のためバッチ
  時点では決定できない）。

- **`WarningService`**: 気象庁警報・注意報XML/JSONを地域コード（`ResolvedArea`）で解決。
  地点→市区町村（GSI逆ジオコーダ）→JMA警報エリア（`jma_area.resolve_area`）→電文取得の
  3段階すべてが失敗しうる箇所で、どこで失敗しても例外にせず空警報を返す。JMAは大雨・
  土砂災害・高潮・暴風/暴風雪・波浪・大雪・その他の注意報を別電文（VPWW55〜61）として
  発表するため、`_build_warnings`は電文配列全件を走査してcode単位で重複排除する。

- **`WbgtService`**: 環境省WBGT予報から最も近い時刻の値を選ぶ（`_pick_nearest_forecast`）。
  提供期間外（月単位の粗い判定、4〜10月）は取得自体を行わない事前フィルタを持つ（無駄な
  API呼び出しを避けるためだけの判定で、正確性の最終防線ではない）。複数の発表回
  （`reference_time`）が検索窓に混在しうるため、まず最新の発表回に絞ってから現在時刻に
  最も近い`forecast_time`を選ぶ2段階選択を行う。

- **`FloodService`**: 河川洪水予報。`WarningService`と同じ`jma_area.resolve_area`を
  再利用して地点解決する。JMA洪水予報はstatus文字列ではなく`item.code`自体が発表/継続/
  解除/引き下げを区別する。`status != "通常"`（訓練・試験電文）は明示的に除外する。

## レート制限（`config.py`）の設計方針

風の格子点マップ（`wind_grid`＝20/分）は624地点をまとめて取得する重いエンドポイントの
ため`/weather`（60/分）より低く抑える一方、詳細格子（`wind_grid_detail`＝30/分）は
パン・ズームのたびに呼ばれうるためやや高め——ただし固定ラティス由来のキャッシュ共有
（`domain/wind_grid.py: generate_wind_grid_detail_points`）により大半はOpen-Meteoへの
新規リクエストを伴わない。警報・WBGT・洪水予報・アメダス（いずれも30/分）は「地点変更時
デバウンス起点で呼ばれる」という共通の呼び出しパターンを前提に揃えられている。

## シンプルな外部APIクライアントの共通ヘルパー（`simple_api_client.py`）

`jma_amedas_client.py`・`jma_warning_client.py`・`wbgt_client.py`・`flood_client.py`は
tenacity再試行を持たない（更新頻度がOpen-Meteoほど高くない、または機械アクセスへの
配慮のためTTLキャッシュで呼び出し頻度自体を抑える設計）。これらが共有する
「`TTLCache`参照→ミス時のみfetch→エラー処理→キャッシュ書き戻し」という骨格を
`cached_fetch(cache, key, category, fetch, *, catch=..., **log_fields)`が1箇所へ
まとめている。呼び出し元は`fetch`（実際のhttpx呼び出し＋パース＋必要ならフォーマット
検証）だけを渡す。フォーマット不正（配列であるべきなのにそうでない等）は
`UnexpectedShapeError`（`ValueError`のサブクラス）を`fetch`内から送出すると、常に
固定文字列`error_type="unexpected_shape"`として記録される。呼び出し元によって
捕捉すべき例外の範囲が異なる（例: `fetch_municipality_code`は`AttributeError`も対象に
含める）ため、`catch`引数で個別に指定できる。`weather_client.py`（tenacity再試行・2段キャッシュ）・
`jma_tile_client.py`/`elevation_client.py`/`basemap_client.py`/`gsi_relief_tile_client.py`
（TTLCache以外のキャッシュバックエンド）は対象外のまま各自の実装を維持する。

## 基礎地図プロキシ（`basemap_client.py`・`api/routers/basemap.py`）

OpenFreeMapのスタイルJSON・TileJSON・スプライト・グリフ・タイルを透過的にプロキシし、
`tile_cache`（ファイル）へ保存する。JSON（スタイル/TileJSON）は上流のURLを
`settings.basemap_public_base_url`へ書き換えて返すが、キャッシュには書き換え前の内容を
`basemap-raw/`接頭辞のキーで保存し、書き換えは返す直前に毎回行う（設定変更がキャッシュを
消さずに即座に反映される）。バイナリ（スプライト・グリフ・タイル）は無加工でパスそのままの
キーに保存する。`POST /api/basemap/refresh`は`tile_cache.clear_all()`で路面タイル等も含めた
ファイルキャッシュ全体を消す。

## 色別標高図タイルプロキシ（`gsi_relief_tile_client.py`・`api/routers/gsi_relief_tile.py`）

国土地理院の色別標高図タイル（`{z}/{x}/{y}.png`）を透過的にプロキシしつつ`tile_cache`
（ファイル）へキャッシュする。`basemap_client.py`と同じ「pathを丸ごとプロキシ＋
`tile_cache`の永続ファイルキャッシュ」方式だが、タイルはPNG単体でJSON応答を持たないため
URL書き換えは不要。地理院タイルは`basetime`/`validtime`のような時刻依存パラメータを持たない
静的データのため、TTL付きキャッシュも不要。

**恒久404のキャッシュ（改善計画T605）**: 色別標高図の整備区域外（404）は珍しくない正常系
（`elevation_client.py`のDEMタイル・`_CoverageGap`と同じ状況）で、他の失敗（タイムアウト・
5xx等）と区別して502・WARNINGログ・`/api/debug/stats`のerror集計へは乗せない。確認済みの
404は`ReliefTileNotFound`センチネルとしてプロセス内メモリのみ（上限付きLRU、キー=path）に
記憶し、`tile_cache.py`の永続ファイルキャッシュへは書かない（将来GSI側の整備区域が広がった
場合、プロセス再起動だけで再取得の機会が来るようにするため）。`api/routers/gsi_relief_tile.py`
は`ReliefTileNotFound`を受け取ると404（それ以外の`None`は502）を返す。

## Open-Meteo呼び出しの信頼性対策（`weather_client.py`）

1. **リクエスト集約**: `get_forecast_many`が複数地点を1リクエストへまとめる（GET→POST化、
   624地点でのURI長制限[414]回避を含む）。
2. **tenacityによる再試行**: 429のみ`Retry-After`ヘッダを尊重、それ以外は指数バックオフ
   ＋ジッター（`RETRY_JITTER_RANGE`）で同時再試行の同期を避ける。`stop_after_attempt`
   （最大4回）と`stop_after_delay`（予算8秒）のOR。
3. **2段キャッシュ（L1メモリ＋L2 Redis）**: `_wind_forecast_cache`（プロセス内）が
   ミスした分だけ`wind_forecast_cache.py`（Redis）を引く。プロセス再起動をまたいで
   生存する。
4. **stale fallback**: 再試行を尽くしても失敗した地点は、TTL切れ後も
   `WIND_GRID_STALE_FALLBACK_MAX_AGE_SECONDS`（24時間）以内のキャッシュがあれば代用する。
5. **変数を絞る**: `get_forecast_many`は`WIND_GRID_VARIABLES`（風速・風向・降水量のみ）に
   限定する。`get_forecast`（単発、`/api/weather`用）は表示項目のため全変数を維持する。
6. **応答エントリの対応付けは座標ベース**: Open-Meteoの複数地点応答は件数・順序がリクエストと
   一致する保証が無い。位置（index）だけで対応付けると1件の省略だけで以降の全地点がズレて
   誤った地点の天気を割り当ててしまうため、各エントリ自身が返す`latitude`/`longitude`
   （Open-Meteoの複数地点応答の標準フィールド）で対応するリクエスト地点を引き直す。座標を
   持たない/一致しないエントリ（テストフィクスチャ等）は位置対応へフォールバックする。
   対応付けできなかった地点は`results[key] = None`になり、`fields["result"] = "error"`で
   WARNINGログへ記録される（`missing_locations`件数付き、`log_external_call`参照）。

`open_meteo_base_url`は本番では自前ホスト（Oracle Cloud VM）上のnginxリレープロキシへ
向けられており、Render→Open-Meteo直叩きによる送信元IP共有問題を回避している。
