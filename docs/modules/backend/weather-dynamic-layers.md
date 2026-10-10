# 気象・動的レイヤー（backend）

## 責務

気象庁MSM（数値予報モデル。風・降水・気温の計算値）・気象庁（アメダス・警報/注意報・タイル系ナウキャスト・
洪水予報）・環境省（WBGT）由来のデータを取得・キャッシュし、地点の天候・警報・地図タイル
として配信する。外部の気象予報APIには依存しない（MSMはファイルをローカルへ同期して
読む）。

**外部タイルのプロキシ配信もここが持つ**（基礎地図・国土地理院）。気象のデータではないが、
「外部のタイルを中継してキャッシュする」という仕組みを気象庁タイルと共有しており（気象庁はRedis、
基礎地図・地理院はディスクの`tile_cache`）、
片方だけを別の文書へ移すと同じ仕組みの説明が二手に分かれる。標高そのものの取得（DEM→
Edge属性、ルート評価の入力）は[elevation.md](elevation.md)が持つ。

**モデルの計算値と実測の住み分け**: 先の時刻の値（風・降水の格子点マップ、ルート評価が使う時刻別の風、
「今日」のパネル）は気象庁MSMの前処理済みファイルをローカルへ同期して読む。実測（現在の気温・風速、降水
ナウキャスト）と防災情報（警報・注意報・洪水・キキクル）は気象庁の公開APIから取る。
MSMは数値予報モデルの出力で観測値・公式発表の代わりにはならないため、両者は統合しない。
**MSMの値から天気（晴れ・雨等）を導かない**——天気コードは観測（アメダスと推計気象分布）からだけ導く
（`domain/weather.py: derive_observed_weather_code`）。数値予報から天気を計算して出すことと、モデルの値を「予報」と
称して出すことは、気象庁の公式の説明が予報業務の許可の対象と書いている
（[data-sources.md](../../architecture/data-sources.md)「気象業務法の予報業務許可」節）。画面の文言の側の扱いは
[動的気象レイヤー（frontend）](../frontend/dynamic-weather-layers.md)「責務」。

このモジュールが扱う情報は大きく2系統に分かれる:
1. **バッジ系**（警報・WBGT・洪水予報・アメダス）: 出発地点1点に対する現在の警戒状態を
   返す。取得に失敗して分からないときは502で、空の応答（警報なし等）とは分ける。
2. **地図レイヤー系**（風グリッド・JMAタイル系ナウキャスト）: 広域の格子点・タイルを
   まとめて配信する。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `msm.py`（MSM格子の幾何・双一次補間）・`jma_tile_specs.py`（配信元の要素ごとの宣言`JMA_ELEMENTS`。要素1件がパスの系統・時刻一覧のファイルと読み方・タイルで配るならズームとベクタのレイヤー名と降水の段の色で塗った画像か・配信の遅れを持つ（遅れは画面だけが読み、プリウォームの読み方は持たないので、タイルで配る要素には宣言できない）。予測を持つ要素は予測が届く先（地図の説明の文と凡例が引く）も持つ。ほかに系統ごとの時刻一覧の更新間隔。読み方に従って時刻一覧の行をコマにする`read_target_times`と、配信元のパスの形——時刻一覧のパス・コマのパスのテンプレート`jma_url_template`・タイルのパスの組み立て`jma_tile_path`——も持つ）・`weather_elements.py`（動的気象で地図に描くものの宣言。要素ごとに、選んだ時刻に描くコマの規則と、自前の格子から描くなら読む値、配信元が段の色を焼き込むなら塗る段（`weather_display.py`の段の名前。画面の凡例と説明文がこれでまとめる）も持つ。時刻の段をつないだとき各段が最初に描くコマを求める`stage_first_frames`と、配信要素の予測が届く先を説明の文の語にする`forecast_reach`も持つ。画面へは生成物で届き、本番プロセスではプリウォームが温める要素をここから導く。**本番が読むため**、本番が読まない表示値の宣言`map_display.py`とは別のファイルに置く——デプロイの要否はファイル単位で決まる）・`weather.py`・`jma_amedas.py`・`jma_area.py`・`jma_warning.py`・`wbgt.py`・`twilight.py`・`flood_forecast.py`・`terrain_rgb.py`（Terrain-RGBの刻みと原点。画面が標高を読み戻す係数として生成物へ出る）・`gsi_tiles.py`（国土地理院タイルの製品ごとの事実——実データを持つズーム範囲・上流のパス・出典表記。中継ルートと画面へ配るURLは受ける層の`api/routers/gsi_tile.py`が上流のパスから導く）・`weather_display.py`（気象の値を色へ写す段と、天気コードの分類と名前。段は値の昇順でなければ読み込んだ時点で落とす——画面はこの順のまま塗り分けの式を組み、MapLibreの`step`式は昇順でないと式ごと失敗してレイヤーが黙って消える。画面へは`scripts/export_openapi.py`の生成物で届き、本番プロセスは気象庁の降水のタイルの塗り替え（`jma_tile_recolor.py`）で降水の段と気象庁の色を読む）・`warning_display.py`（警戒度バッジの出所ごとの段階の呼び名と色。呼び名はそれぞれの段階の宣言（`jma_warning.py`・`wbgt.py`・`flood_forecast.py`）から読む。本番プロセスは読まず、生成物`vocabulary.ts`だけが届く） |
| services | `weather_service.py`・`wind_grid_service.py`（風の格子の段取り。対象範囲を読む→格子点を作る→読む）・`jma_amedas_service.py`・`wbgt_service.py`・`warning_service.py`・`flood_service.py`・`jma_tile_prewarm_service.py`（定期プリウォームバッチ）・`jma_tile_proxy_service.py`（タイルの中継の段取り。キャッシュ→補間と書き戻し→上流）・`jma_tile_interpolation_service.py`（配信元が持たないズームの補間の段取り）・`terrain_tile_service.py`（地理院の標高タイルをTerrain-RGBへ変換して配信） |
| infrastructure | `msm_client.py`（MSMの同期・読み出し）・`jma_tile_client.py`・`jma_tile_redis_cache.py`（タイル本体のRedis cache-aside）・`jma_tile_paths.py`（配信元のパスをテンプレートに当ててタイルとして読み戻す・404が確定した事実かを決める）・`jma_tile_interpolation.py`（配信元が持たないズームの補間）・`jma_tile_index.py`（在否インデックス）・`jma_tile_content.py`（タイルが空かどうかの判定。キャッシュと在否インデックスが共有する）・`jma_tile_recolor.py`（気象庁の降水のタイルの色をアプリの降水の段の色へ塗り替える、後述）・`jma_amedas_client.py`・`jma_suikei_client.py`（推計気象分布（天気）の地点の天気の区分。時刻一覧とタイルのパス・地点を含むタイルと画素・凡例の色から区分への読み替えを持つ。地図に重ねる`JMA_ELEMENTS`のタイルとは画素数と座標の数え方が違うので、宣言に入れずに持つ。時刻一覧とタイルは`JmaTileClient`を通る）・`jma_amedas_store.py`（アメダスの観測値と1時間雨量の履歴のRedisの置き場。鍵・項目名・TTL・保存した形の検査を持ち、サービスとは値でやり取りする）・`jma_warning_client.py`（警報のコード→種別の名称の表（配信元のコード表の写し）と、状態の文字列→発表中か）・`wbgt_client.py`・`flood_client.py`（洪水予報のコード→段の表（配信元のコード表の写し））・`basemap_client.py`・`gsi_tile_client.py`・`simple_api_client.py`（TTLキャッシュで持つクライアントが共有する定型文、後述）・`gsi_dem_png.py`（地理院の標高タイルの画素を標高として読み、Terrain-RGBのPNGへ詰め直す、後述。読む部分は標高の取込も使う）・`jma_area_boundaries.py`（地点→区域のコード。気象庁の区域の境界をディスクから読む。引いた区域を地域マスタで警報のエリアまで辿る段取りも持ち、警報と洪水予報が共有する、後述） |
| api | `weather.py`・`jma_tile.py`・`basemap.py`・`gsi_tile.py` |
| scripts | `fetch_jma_area_boundaries.py`（気象庁の区域の境界を取得し、`jma_area_boundaries.py`が読む形で置く。デプロイが呼ぶ） |

## domain層: 2つの異なる役割

| ファイル | 役割 | 消費側 |
|---|---|---|
| `weather.py` | 天候のPydanticモデル（`WeatherConditions`・`WeatherPeriodOutlook`。MSMの計算値）と「今日」のパネルの読み方（時系列の先頭と同じ暦日の時刻・日次の最大と範囲・一定間隔のコマ（間隔は応答にも載る））、アメダスの10分間の実測（降水量・気温）と推計気象分布の区分からWMO天気コードを導く`derive_observed_weather_code`（降っているかと雨・雪は観測所の実測が、降っていないときの晴れ・くもりは推計気象分布が決め、推計の雨・雪の区分はくもりに数える。日照時間は夜は空によらず0になるので使わない。「降っていない」の境`PRECIPITATION_MIN_MM`は、「今日」のパネルの降水量の「-」と地図の降水の塗りにも生成物で届く） | `weather_service.py`・`jma_amedas.py` |
| `jma_amedas.py` | 風の来る向き`WindDirection`（16方位コードからの読み替えは`jma_amedas_client.py`。静穏・欠測・範囲外のコードは方位なし。呼び名は`domain/geo.py: SIXTEEN_POINT_LABELS`から引く）・体感温度計算（BOM式）・`AmedasObservation`モデル（観測所名と観測の時刻は観測所ごとに決まり、Redisに持つ。天気コード`weather_code`はリクエストの地点の推計気象分布で決まるため、日の出・日没と同じく応答のたびにサービスが入れ、Redisには持たない） | `jma_amedas_service.py` |
| `jma_area.py` | 区域（class20）のコード→JMA警報エリア（class20→class15→class10→office）の親子関係解決。辿る地域マスタは`AreaMaster`（area.jsonの形は`jma_warning_client.py`が解く。区域の名前は読まず、二次細分区域は親の府県予報区があれば解決する） | `warning_service.py`・`flood_service.py` |
| `jma_warning.py` | サイクリングで出さない種別（名称で持つ。既定は出す）・電文1件`WarningBulletin`と、区域の種別の引き方（区域の項目が無い電文だけを二次細分区域で引く）・アクティブ警報抽出（電文の1地域ぶんの種別`AreaWarningKind`から。種別は名称と発表中かへ読み替え済みで届く）・警戒度の段と呼び名（`JMA_LEVEL_LABELS`。段は名称が含む呼び名から導く。危険警報＝警戒レベル4は警報と特別警報の間の段で、氾濫危険警報と同じ段） | `warning_service.py`・`warning_display.py` |
| `wbgt.py` | WBGT警戒レベル判定（熱中症予防運動指針の5段階閾値）・提供期間判定・段階の表示名（`WBGT_LEVEL_LABELS`）・情報提供地点`WbgtPoint`と予測値`WbgtForecast`・今の予測の選び方（`current_forecast`） | `wbgt_service.py`・`warning_display.py` |
| `flood_forecast.py` | アクティブ予報抽出（電文1件`FloodBulletin`から。電文の形とコード→段の読み替えは`flood_client.py`が持つ）・段階の表示名（`FLOOD_LEVEL_LABELS`） | `flood_service.py`・`warning_display.py` |
| `twilight.py` | 市民薄明による夜間判定（`night_mask`、時刻の配列をまとめて判定）・日の出日没計算（`sunrise_sunset_jst`） | `jma_amedas_service.py`（表示用）・[routing-engine.md](routing-engine.md)のroad_graphエンジン（night軸の動的化） |

`twilight.py`は外部APIに依存しないローカルの天文計算のみで、
実際の主消費者は[routing-engine.md](routing-engine.md)が主管する`road_graph_engine.py`
である。

## API（`api/routers/weather.py`）

| エンドポイント | データ源 | fail時 | レート制限/分 |
|---|---|---|---|
| `GET /api/weather` | 気象庁MSM（「今日」のパネル: 日次集計・一定間隔のコマ） | 502 | 60 |
| `GET /api/weather/warnings` | 気象庁警報・注意報 | 502 | 30 |
| `GET /api/weather/wbgt` | 環境省WBGT | 502 | 30 |
| `GET /api/weather/flood-forecast` | 河川洪水予報 | 502 | 30 |
| `GET /api/weather/amedas` | 気象庁アメダス実測値（Redis読み取り専用）と、天気コードの晴れ・くもりに推計気象分布（天気） | 502 | 30 |
| `GET /api/weather/wind-grid`・`/wind-grid-detail` | 気象庁MSM（ローカルの`.om`ファイル） | 全滅時と、対象範囲が読めないとき502 | 20／30 |

`/api/weather`は常設ヘッダー用ではなく、「今日」のパネル（日次集計・一定間隔のコマの
気温・降水量）専用。コマの間隔は応答の`today_period_interval_hours`で届き、画面はコマの並びの見出しに
それを出す（間隔を画面が文字で持つと、backendで間隔を変えたときに見出しだけが古くなる）。常設ヘッダー（気温・体感温度・風速風向の現在値）はアメダス実測を使う
`/api/weather/amedas`が担う。

**警報・WBGT・洪水予報の空の応答は「出ていない」だけを表す**（警報なし・予報なし・暑さ指数の段なし）。
地点を区域・情報提供地点へ解決できない、配信元から取れない等で出ているかが分からないときは502で返す
（詳細は文字列「取得できませんでした。」で、画面は出所の名前を前に付けて常設ヘッダーの「未取得」の印に出す）。
空で返すと、画面は警報が出ていないのと同じに見せる。空になるのは次のときだけ:
地点がどの区域にも入らない（遠い海上。陸の区域の警報・予報は当たらない）・取れた電文がその区域に
警報・予報を持たない・暑さ指数の提供期間の外で今の値が得られない（取得の失敗も含む）・値が「ほぼ安全」の段。

応答の`Cache-Control`は`api/cache_policy.py`の対応表が持つ（このモジュールのルーターは
ヘッダを書かない）。`/wind-grid`系は`SHORT`（5分）——応答が数十時間ぶんの時刻配列を持ち
どの時刻を描画するかはクライアントが選ぶうえ、上流（MSM）の更新は3時間ごとのため。
警報・WBGT・洪水予報・アメダスは`VOLATILE`（2分）、`/api/weather`は`SHORT`。502は2xxでは
ないためミドルウェアの対象外になる。

**格子を敷く範囲**: 粗い格子（`/wind-grid`）は対象範囲全体に、詳細格子は問い合わせ範囲を対象範囲へクリップした所に
敷く。対象範囲は取り込んだ道路の範囲で、`RegionService.get_ingested_area`が成功した最新の道路の取込の記録
（`source_runs.profile`の`target.bbox`）から読む——ルート生成の「取込範囲か」（`RoadGraphRepository.is_covered`）と
同じ行を読むので、取込範囲を広げれば風の格子・気象庁タイルのプリウォームも同じ範囲へ広がり、道路の無い所には敷かない。
取込の宣言`batch/source_profile.yaml`を直接読まないのは、webの層が`app.batch`を読まない（`backend/.importlinter`）ため。
範囲はリクエストごとにDBから読む（`source_runs`の1行を引くだけで、キャッシュは置いていない）。読むのは`WindGridService`で、
地域サービスを開き方で受けて読む間だけ開く（格子を読む間にDBの接続を持たない）。読めない（DB障害・道路を未取込）ときは
格子を組めないので502で、原因はWARNINGで残る。

**詳細格子の座標と間隔**（`domain/wind_grid.py`）: 格子の点は、問い合わせ範囲の角からも対象範囲の角からも数えず、
緯度・経度0度から間隔ずつ数えた固定のラティス（道の風の`domain/wind.py: WindLattice`と同じ数え方）のうち、範囲に
交差するものを選ぶ。画面は取り損ねた点を前回の値で補うとき点を緯度経度の一致で見分ける
（`windLayer.ts: mergeWindGridKeepingStale`）ため、パンで範囲がずれても、取込範囲が変わっても、重なる所が同じ座標で
返ることに依っている——範囲の角から数えると、前回の点が今回の点と重ならずに残り、ずれた点が重なって描かれる。受け付ける間隔は下限`WIND_GRID_DETAIL_MIN_SPACING_DEG`以上の有限の値で（下限未満は400、
無限大・NaNは型の検査で422）、どの間隔を求めるかは画面がズームの段ごとに決める（`windLayer.ts`）。下限は画面が最も
拡大したときの間隔で、元のMSMの格子（緯度0.05度・経度0.0625度）より20倍以上細かい——これより細かくしても補間の点が
増えるだけで情報は増えない。座標を小数4桁へ丸める（`_lattice_coordinate`）ので、下限を0.0001度未満へ下げると
別の格子点が同じ座標へ潰れ、画面の補い（緯度経度の一致で見分ける）が壊れる。原点と間隔を固定しても、利用者の間で共有される
キャッシュは無い——格子点の値は毎回手元のMSMから補間し、応答の`SHORT`はURL単位で、URLは表示範囲をそのまま含む。
点数の上限（`WIND_GRID_DETAIL_MAX_POINTS`、超えれば400）は、点を作る前に索引の範囲から数えて確かめる
（`count_wind_grid_detail_points`）。点を作る処理は同期でasyncのハンドラから呼ばれ、作っている間はイベントループが
止まるため、作ってから数えると、最小の間隔で関東全域を渡す1回の問い合わせが（上限で断られるにもかかわらず）
約98万点を作って数秒〜十数秒backend全体を止める。数える側と作る側は同じ索引の範囲（`_detail_index_ranges`）に従う。

### JMAタイル系の共通プロキシ（`api/routers/jma_tile.py`）

`GET /api/jma-tile/{path:path}`が降水ナウキャスト・rasrf・雷/竜巻ナウキャスト・
キキクル・線状降水帯予測マップなど、気象庁のタイル系データを1つの汎用プロキシで中継する
（`path`をそのまま気象庁側へ引き渡す）。認証は無し。`JmaTileClient`はキャッシュ戦略を
2種類に分ける:

| 対象 | サーバー側キャッシュ方式 | TTL | 応答の`Cache-Control` |
|---|---|---|---|
| `targetTimes*.json`（`jma_tile_client.py: is_target_times_path`で判定） | プロセス内メモリ`TTLCache`（maxsize=16） | 2分 | `public, max-age=60` |
| タイル本体（ラスタPNG・洪水キキクルのベクタPBF。降水は塗り替えたあと） | `jma_tile_redis_cache.py`（Redis cache-aside、正本を持たない。鍵に塗り替えの版`jma_tile_recolor.py: RECOLOR_VERSION`を入れる） | 20分 | `public, max-age=1200, immutable` |
| 描くものが無いタイル（`EmptyTile`。上流の404、または200で返った空タイル） | 上記と同じキー・TTL（実体ではなくフラグ） | 20分 | `public, max-age=600` |
| 配信前のコマの地物（GeoJSON）の404 | 保存しない | — | `no-store` |
| 502（上流障害） | 保存しない | — | 付けない |

`Cache-Control`の値自体は`api/cache_policy.py`（`IMMUTABLE_TILE`・`JMA_TARGET_TIMES`・
`JMA_TILE_NOT_FOUND`・`JMA_NOT_YET_DELIVERED`）が持ち、このプロキシは1つのパスで性質の異なるものを返すため
対応表では`HANDLER_MANAGED`とし、どれを使うかだけを`jma_tile.py`が選ぶ
（[横断基盤](cross-cutting-infrastructure.md)「応答のCache-Control」参照）。

タイル本体のURLは`basetime`/`validtime`を含み内容が確定して以後変化しないため、`immutable`で
ブラウザに再検証させない。MapLibreはズームレベルの跨ぎ・画面外へのパン・`setTiles`による
ソース更新のたびに同じURLを引き直すため、この差が実リクエスト数に直結する。時刻一覧だけは
同じURLのまま内容が更新されるため`immutable`にできない。

**降水のタイルの塗り替え（`infrastructure/jma_tile_recolor.py`）**: 降水ナウキャストと降水短時間予報（宣言の
`JmaTileSpec.precipitation_colors`）のタイルは、配信元が降水の強さの段ごとに決まった色で塗ったパレット形式のPNGで、
段の区切りはアプリの降水の段（`domain/weather_display.py: PRECIPITATION_COLOR_STOPS`）と同じである。`JmaTileClient.fetch`が
上流から取ったタイルのパレットの色を、気象庁の色の並び（同じファイルの`JMA_PRECIPITATION_TILE_COLORS`）から同じ段のアプリの色へ
1対1で替えてからキャッシュへ書き、応答する。地図の色が凡例（同じ段から組み立てる）の行のどれかと一致し、自前の格子の
塗りとも同じ色で続く。補間（後述）は塗り替えたあとの親を切り出すので、補間したタイルも同じ色になる。段に無い色の画素は
替えずに残してWARNINGを出し（配信元が配色を変えた印）、読めない画像はWARNINGを出してそのまま配る。

**レート制限（300/分）の適用順序**: 中継の段取り（`services/jma_tile_proxy_service.py: proxied_tile`）は
`JmaTileClient.get_cached(path)`でまずキャッシュのみを参照し、ヒットすればレート制限を一切経由せず返す。
ミスのときだけ、`jma_tile.py`が渡した歯止め（`enforce_rate_limit`）を呼んでから、補間（後述）か
`JmaTileClient.fetch(path)`（外部フェッチ＋キャッシュ書き戻し）へ進む。`JmaTileClient.get(path)`（`get_cached`→ミスなら`fetch`の一括呼び出し）はレート
制限の適用順序を気にしない呼び出し元（プリウォームバッチ・テスト等）向けに残している。

**フェイルステータスの使い分け**: `fetch`は上流の404を`JmaTileNotFoundError`
として送出し、`jma_tile.py`はこれを404（他の失敗は502）として返す。降水・浸水想定区域等の
疎な格子状タイルは、ズームレベル・場所によって存在しないz/x/yが珍しくない正常系のため、
タイムアウト・5xx等の実際の障害と同列に502・WARNINGログ・`/api/debug/stats`のerror集計へは
乗せない。`get`（プリウォームバッチ等、404と他の失敗を区別する必要が無い呼び出し元向け）は
`JmaTileNotFoundError`を`EMPTY_TILE`へ揃えて返す（Noneは取得失敗だけを表す。平常時は
空が大半のため、失敗と混ぜるとエラー件数が常に大きくなり本物の障害が埋もれる）。

**「得るものが無い」の持ち方**: 上流は、データの無いタイルを404で返すことも、200で
全画素が透明なタイル（334バイトのRGBA PNG）・0バイトのMVTで返すこともある。**どちらも
利用者から見れば同じ**ため、サーバーは区別せず1つの事実として持つ——
`jma_tile_redis_cache.set_empty`が実際のタイルと同じキー・TTLで0バイトの値を保存し、
`get`は`EMPTY_TILE`センチネルを返す。空だと分かったタイルは`set`も実体を保存せずこの
フラグへ倒す（空の判定は`jma_tile_content.py: is_empty_tile`が唯一持ち、在否インデックスも
同じ判定を使う）。`targetTimes*.json`はプロセス内`TTLCache`へ直接`EMPTY_TILE`を積む。

`jma_tile.py`は`EmptyTile`を受け取ると上流へ再問い合わせせず即座に404を返す（レート制限も
消費しない）。クライアント側（`jmaTileProtocol.ts`）は404も空タイルも透明タイルへ倒すため、
200＋空タイルを返す必要はない。配信された`basetime`/`validtime`の一時点への結果のため、
この事実は再フェッチしても変わらない。

**配信前の地物の404は覚えない**: タイルで配らない要素のコマの地物（GeoJSON。例: 落雷の地点・線状降水帯の雨域）は、
配信元がそのコマを配信するまで404を返し、配信した後は地物が無くても200で空の集まりを返す。線状降水帯の雨域は
時刻一覧に載ってから約13.5分404が続く（2026-09-28の実測。その約1分後に時刻一覧の最新が次の`basetime`へ進む）。
画面は配信の遅れ（`domain/jma_tile_specs.py: JmaElement.data_delay_minutes`、公式の画面の`dataDelay`）のぶん
前の`basetime`を取るので配信前のコマを取りに行かないが、時刻の食い違いで取りに行く利用者が1人でもいると、覚えた404が
配信された後もその間は全員に「無い」を返す。そこで、404が確定した事実か
（`infrastructure/jma_tile_paths.py: is_final_absence`。パスの形が地物か）で分け、地物の404は`EmptyTile`として保存せず、
ブラウザへも`no-store`で返す。画面の側は[動的気象レイヤー（frontend）](../frontend/dynamic-weather-layers.md)
「配信の遅れを持つ要素は、時刻一覧のコマをそのまま取らない」。

**要素ごとのズーム上限（`domain/jma_tile_specs.py`）**: 配信元は要素ごとに`zoomUse`
（使用するズームの偶奇）と`maxNativeZoom`（画像が実在する最大ズーム）を持ち、**両方を
突き合わせないと実データの無いズームを指す**。`effective_max_zoom()`が
「`maxNativeZoom`以下で`zoomUse`の偶奇を満たす最大値」を導出し、MapLibreの`maxzoom`
（frontendへは動的気象の要素の宣言`domain/weather_elements.py: WEATHER_ELEMENTS`の生成物
`mapDisplay.weatherElements`の`tile`として配る）とプリウォームの対象ズームの両方が
この1箇所から決まる。ズームの仕様は配信要素の宣言`JMA_ELEMENTS`の1件がパスの系統（`risk`・`nowc`・`rasrf`）・
時刻一覧のファイルと読み方と一緒に持ち、タイルで配らない配信要素（落雷・線状降水帯の雨域のGeoJSON）はズームの仕様を持たない
（要素ごとの性質を表に分けて持つと、要素idを両方に書き、つながりをテストで守ることになる）。プリウォームの取得先はここから、画面の仮のURLと
データ層が組み立てる実データのURLは生成物の要素ごとの`jmaElements`（時刻の段の順に並んだ
配信要素id・時刻一覧のパス・コマのパスのテンプレート）から組み立てる。1つの名前付きソースが時刻によって別の配信要素
から届く（降水の`main`は`hrpns`→`rasrf`）ため段の並びで持ち、段の間でソースのズーム範囲が
食い違えば`weather_elements.weather_element_tile()`が生成時に落とす。

| 要素 | zoomUse | maxNativeZoom | 導出される上限 |
|---|---|---|---|
| `land`・`rain_mesh`・`inund`・`flood`（キキクル） | even | 11 | 10 |
| `hrpns`（降水ナウキャスト）・`rasrf`（降水短時間予報） | even | 10 | 10 |
| `thns`・`trns`（雷・竜巻） | even | 9 | **8** |
| `sjfcstmap`（線状降水帯予測マップ） | even | 10 | 10 |

出典は各要素を表示する公式ページ（`bosai/risk/`・`bosai/nowc/`・`bosai/kaikotan/`）が読み込む
`table/<ページ>.properties__<hash>.xml`。降水短時間予報と線状降水帯予測マップは「今後の雨」
（`bosai/kaikotan/`）の設定ファイルが持つ。

上限を超えるズームを指定すると、その要素のタイルは存在せず空タイル（334バイトのRGBA PNG、
ベクタは0バイト）が返るため、地図から色が消える。上限の内側にある「偶奇の合わないズーム」
（キキクル・降水のz5/z7/z9、雷竜巻のz5/z7）も同じく空になるため、そちらは下記の補間で埋める。
**仕様に無い要素は補間されない**——`source_zoom_for_interpolation`は仕様を持たない要素idに
Noneを返し、上流の空タイルがそのまま画面へ届く。

**時刻一覧の在り処**（同じファイル）: 配信元は系統ごとに時刻一覧のファイルを持つ（公式ページの
設定ファイルの`<dataRootUrl>`配下の`<timeFile>`）。`nowc`だけが複数のファイルに分かれ、どの要素が
どのファイルに載るかは設定ファイルに無く、各ファイルの行の`elements`で決まる（降水の実況・予測と、
雷・竜巻・落雷でファイルが違う）。そこで配信要素の宣言が、その要素の行が載るファイルを要素ごとに持つ
（`JmaElement.time_files`）。系統の全ファイルを読む形にしないのは、要素の行が1件も無いファイルの取得失敗まで
その要素の失敗に数えることになるため。プリウォームは`jma_target_times_paths()`から、画面は同じ関数の値を
生成物の`jmaElements[].targetTimesPaths`で受け取って時刻一覧を取りに行く。ファイル名を誤ると、配信元に無い時刻一覧を
取りに行ってその要素の取得が失敗する（どこかの表との突き合わせでは止めない）。

**配信元のパスの形**（同じファイル）: 根（`bosai/jmatile/data`）の下の、系統・時刻・系列・要素idの並びとその下のタイル座標
（またはタイルで配らない要素の地物のGeoJSON。例: 落雷の地点・線状降水帯の雨域）の形を1か所に持つ。`jma_url_template()`が要素ごとに系統・要素id・
拡張子（ベクタは`.pbf`、ラスタは`.png`）まで埋め、コマの項目（`JmaFrame`の項目名の`{basetime}`等）とタイル座標
（地図の`{z}/{x}/{y}`）を残したテンプレートを返す。プリウォームはこれを埋めて取りに行き（`jma_tile_path`）、
プロキシの補間はパスを同じテンプレートに当てて読み戻す（`infrastructure/jma_tile_paths.py: read_jma_tile_path`）。画面は同じテンプレートを生成物の
`jmaElements[].urlTemplate`で受け取り、コマで埋める（[動的気象レイヤー（frontend）](../frontend/dynamic-weather-layers.md)）。
**読み戻せるのは宣言のある、タイルで配る要素のパスだけ**——テンプレートに当てるので、宣言の無い要素id・大文字の
要素id・描き方と違う拡張子のパスはタイルとして読まれず、補間されずに上流へそのまま中継される。時刻一覧かどうかの
判定（`jma_tile_client.py: is_target_times_path`）だけはテンプレートを使わずファイル名の形で見る——プロキシは宣言に
無いパスも中継し、その応答のキャッシュの持ち方（時刻一覧はプロセス内で2分、タイルはRedisで`immutable`）を決める必要があるため。

**配信元が持たないズームの補間（`services/jma_tile_interpolation_service.py`、切り出しは`infrastructure/jma_tile_interpolation.py`）**:
MapLibreのソース設定は連続したズーム区間しか表現できず「偶数だけ使う」を伝えられないため、
要求されたズームに実データが無い場合（`source_zoom_for_interpolation`が
親ズームを返す場合）、1段上のタイルから該当象限を切り出して2倍にしたタイルを返す。
ラスタ（PNG）とベクタ（MVT）の両方が対象。段取り（親の取得・ラスタかベクタかの選択・失敗時の扱い）は
サービスが持ち、結果のキャッシュへの書き戻しは中継の段取り（`jma_tile_proxy_service.py`）が行う——同じ補間が要る
別の経路もルーターを経ずに作れる。

- 親タイルの取得は`JmaTileClient.get()`を通すため、Redisキャッシュ・レート制限・上流への
  秒間上限がそのまま効く。補間結果は`JmaTileClient.store()`で**元のパスのキー**へ書き戻し、
  2回目以降は補間をやり直さない。親が取れない・空・補間に失敗した（WARNING）ときは補間せず、
  上流フェッチへ進む。
- **ラスタは最近傍で拡大する**。キキクル・ナウキャストは危険度や強度を離散的な色で塗り分けて
  おり凡例の色と1対1に対応するため、滑らかに拡大すると凡例のどの段階でもない中間色が地図に出る。
- **ベクタ（洪水キキクル）は座標を変換して詰め直す**。画像と違い「拡大」という操作が無いため、
  親タイルの該当象限を切り出し、タイル内座標を2倍にして同じextentのタイルとしてエンコード
  し直す（属性はそのまま引き継ぐ）。**デコード後の座標系はy軸が上向きなのに対し、象限は
  タイルXY（yは南向き）で表される**ため、上下を入れ替えて対応付ける。線がタイルの継ぎ目で
  途切れないよう、切り出しは境界の外側へ少し余白を残す。切り出しで地物が複数の部分に割れても、
  元と同じ系統の部分を全部まとめて1つの地物（Multi系）として残し、縁に触れて混ざった別の系統の部分
  （線の端の点等）は落とす（MVTは系統の混ざった形をエンコードできない）。象限に地物が1つも掛からなければ
  0バイト（＝地物なし）を返し、これも書き戻して次回以降の上流問い合わせを省く。
- Content-Typeは親タイルのものをそのまま使う（配信元が返す値と揃え、拡張子から推測しない）。
- 親タイルが取得できない場合は補間せず通常のフェッチ経路へ進む（補間の失敗で地図表示
  そのものを落とさない）。

**在否インデックス（`infrastructure/jma_tile_index.py`・`GET /api/jma-tile-index`）**:
JMA動的タイルは疎で、平常時はほぼ全てのタイルが空である。`basetime`が10分ごとに変わり
URLも変わるため、ブラウザキャッシュ（`api/cache_policy.py`）では救えない。プリウォームが
運用範囲のタイルを取得する過程で在否を判定し（**追加の取得は発生しない**）、Redisへ記録する。

| 項目 | 内容 |
|---|---|
| 判定 | ラスタは全画素が透明か（`getchannel("A").getbbox()`）、ベクタは0バイトか |
| 補間で埋めるズーム | プリウォームは実データのあるズームしか温めないが、**インデックスは「載っていないタイルは空」を意味する**ため、補間対象のズームを載せずにおくとクライアントがそこを一律「空」と見なし補間が一度も動かない。補間結果が空になるのは親が空のときだけなので、中身のある親タイルの4象限を子ズームの中身ありとして載せる（`domain/jma_tile_specs.py: with_interpolated_zooms`、追加の取得は発生しない） |
| 判定不能時 | **「中身あり」に倒す**（誤って空と判定すると危険情報が表示されなくなる） |
| 保持 | `redis_json_cache`経由、キー1つにTTL20分。要素ごとに`basetime`が異なるためキーには含めず、ペイロード側の要素ごとに持たせる。キーには型（`JmaTileIndex`）のJSON Schemaから導いた版を入れる——形を変えたコードは前の形の値を別のキーとして読まず（前のキーはTTLで消える）、読んだ値は常に今の型の検証を通る |
| フレームの照合 | 要素ごとに温めたフレームの`basetime`・`validtime`・`member`を持たせ、クライアントは3つが要求のタイルと一致するときだけ信用する。**1つの`basetime`に実況と複数の予測の`validtime`が載る**（降水ナウキャストの予測は最新の実況と同じ`basetime`、雷・竜巻も同様）ため、`basetime`だけで照合すると、実況で空だったタイルを予測のフレームでも取りに行かず、予測にだけある雨・雷が地図から消える。中身のあるタイルが1枚も無い要素（平常時の大半）も、照合のためフレームごと載る（座標は空） |
| `coverage` | インデックスが網羅する地理範囲。**この外は在否が不明**のためクライアントは従来どおり取得する |
| 未保存時 | `available: false`を返し、クライアントは従来どおり全タイルを取りに行く（インデックスが無いことで表示が欠けてはならない） |
| 型 | インデックスの形は`infrastructure/jma_tile_index.py: JmaTileIndex`だけが宣言し、組み立て（`_store_index`）・保存・応答が同じ型を使う。応答は在る／無いの共用体（`api/routers/jma_tile.py: JmaTileIndexAvailable`・`JmaTileIndexUnavailable`、`available`で判別）で、在る側は`JmaTileIndex`に判別の項目を足しただけの派生である。frontendは生成型をそのまま使い構造を手書きしない——形がずれても「表示は正常なまま間引きだけが黙って効かなくなる」形でしか現れないため、型の食い違いは型検査で止める |

**定期プリウォーム（`services/jma_tile_prewarm_service.py`）**: `main.py`のAPScheduler
（アメダスと同じ`interval`トリガー、`jma_tile_prewarm_interval_minutes`＝10分、
`next_run_time=datetime.now()`で起動直後にも即時実行）が、サービスの対象範囲
（風の格子と同じ`RegionService.get_ingested_area`。上の「格子を敷く範囲」）ぶんのタイルをあらかじめ`JmaTileClient.get()`
経由でRedisへ温める。範囲が読めない回は温めない（在否インデックスも書かない）。対象ズームは上記`effective_max_zoom()`が導出した上限まで——超過
ズームはMapLibreがクライアント側で拡大表示するだけで追加の通信が発生しないため。
温める要素は動的気象の要素の宣言（`WEATHER_ELEMENTS`）のうちタイルで描くものの配信要素すべてで、
宣言から導く（プリウォーム側に要素idの一覧を持たない。宣言へ1件足せば温まる）。
予報フレームを複数持つ要素（降水・雷・竜巻）も、温めるのは時刻の段ごとに1フレームだけ——
全フレームを温めるとタイル数が桁違いに膨らむ。選ぶのは**画面がその段で最初に描くフレーム**で、
画面と同じ手順で求める: 時刻一覧を`jma_tile_client.py: get_target_times`が行（コマと、そのコマのタイルがある
配信要素）へ解き、画面へ配るのと同じ読み方の宣言（`weather_element_deliveries()`の
`reader`）に従って`jma_tile_specs.read_target_times()`がコマにし、`weather_elements.stage_first_frames()`が
画面の`sourceTimeline`と同じつなぎ方で段をつないで、各段の最初のコマを返す。先頭の段では時系列の左端
（実況＋予測なら最新の実況、「現在」の単一値なら最新の行）、2段目以降（降水短時間予報）では前の段の最後の
`validtime`より後の最初のコマになる。前の段が取れなければ、画面と同じく後の段が最初から継ぐ。
**読み方もつなぎ方も画面と1つでも違えば、在否インデックスのフレームが画面のフレームと一致せず、画面は
インデックスを使わずに全タイルを取りに行く**（表示は壊れず、黙って遅くなる）。frontend（`jmaDelivery.ts`の
`READERS`・`weatherSources.ts: sourceTimeline`）とbackendは言語が違うため同じ手順を両方が持つ。両方が同じ答えを
出すことは、場面（別の要素の行が混ざる・実況が無い・中間ランの単発の行・段が重なる・途中の段が空等）ごとの入力と
backendの答え、タイルで配る要素ごとのタイルのパスを`scripts/cross_language_expectations.py: jma_expectations`が表に
して配り（生成物`jma-expectations.json`）、画面のテストが全行を通して確かめる（[テスト規約](../../../.claude/rules/testing-frontend.md)
「パターン11」）。読み方の種類を足すときは両方と表の場面に足す（backendは`read_target_times`の`match`が`assert_never`で、
足し忘れをmypyが止める）。

**JMAへの実フェッチの秒間上限**: `jma_tile.py`の300/分（クライアント単位）とは別に、
`JmaTileClient.fetch`自身が実際にJMAへ問い合わせる直前で、プロセス全体で共有する
秒間上限（`settings.jma_tile_upstream_max_requests_per_second`、既定5.0）を守るよう
待機する。プリウォームバッチの同時実行数制御（`_MAX_CONCURRENCY=8`）だけでは総
スループット（秒間リクエスト数）自体は制御できないため、`fetch`という「実際にJMAへ
問い合わせる唯一の関数」1箇所に置くことで、プリウォーム・オンデマンドどちらの経路も
一律にこの上限へ従う。直前フェッチ時刻は時刻一覧のキャッシュと一緒に`jma_tile_client.py: JmaTileSharedState`が持ち、
DI工場（`api/dependencies.py`）がプロセスに1つ持ってクライアントへ渡す（`JmaTileClient`はリクエストごとに使い捨てで
作られるため。アメダスのサービスが推計気象分布を読むクライアントも同じものを受ける）。プロセスをまたいでは
効かないため、ワーカーを複数にした起動は`single_process.py`が止める
（[横断的な基盤](cross-cutting-infrastructure.md)「1プロセスの境界」）。

## 天候取得（`weather_service.py: WeatherService`）

| メソッド | 用途 | 時刻 | 日次の値 |
|---|---|---|---|
| `get_conditions(point)` | `/api/weather`エンドポイント（「今日」のパネル） | 時系列の先頭（現在時刻の正時） | 同じJST暦日の残りの最大・最小。最低・最高気温は同じ系列から一緒に決まるため1つの任意の項目（`temperature_range`）で持ち、格子の欠損（NaN）を含めば丸ごとNone。日の出/日没は`twilight.py`で計算 |
| `get_departure_wind(point)` | `RoadGraphEngine`の出発時点の風（時別の系列が無いとき全区間へ一様に使う。`domain/wind.py: DepartureWind`） | 時系列の先頭（現在時刻の正時）。風速・風向を小数1桁に丸める | 対象外 |
| `get_wind_forecast_lattice(bbox)` | `RoadGraphEngine`の探索前コスト合成（Edgeごとの通過予定時刻・最寄りの格子点の風）と、ルートを出す前の地図の風（`WindWayService`） | 範囲を覆う格子点ごとの時別風向・風速の系列（JST）。格子は緯度・経度0度から数えた固定の線に揃う。MSMから読む | 対象外 |
| `get_wind_grid(points)` | 風グリッド・降水の格子の段の地図レイヤー | 予報期間ぶんの時系列。MSMから読む | 対象外 |
| `get_station_rain_materials(now)` | ルートを出す前の地図の雨（`RainWayService`）と`RoadGraphEngine`の気象の段 | 今の観測（アメダスの1時間雨量の履歴。`jma_amedas_service.py: load_station_rain_materials`）。求めた値は実体の中に5分持つので、DI工場（`api/dependencies.py: get_weather_service`）は実体をプロセスに1つ持つ | 対象外 |

## その他のサービス

- **`JmaAmedasService`（取得と配信の分離）**: `get_nearest_observation`は観測値を**Redisから読むだけ**
  （アメダスの観測値はJMAへ問い合わせない。天気コードの晴れ・くもりは下の推計気象分布から読む）。`refresh_all_stations`が全国分を1回取得し観測所ごとに
  Redis Hash（`jma:amedas:{station_id}`、TTLはバッチ間隔＋5分の15分）へ書き戻す。気象庁の応答の形（キー名・
  [度, 分]の座標・[値, 品質フラグ]の観測値・16方位の風向のコード・URLに載せる時刻の書式）はクライアントが解き・組み立て
  （`jma_amedas_client.py: AmedasStation`・`jma_amedas_client.py: AmedasReading`。時刻は`datetime`で受け渡す）、
  Redisの鍵と保存する形は`jma_amedas_store.py`が持つ。サービスは値だけを読む。鍵の観測所idは値に持たず、書くときに観測所id→観測値で渡す。座標の無い観測所は
  観測所マスタの時点で落ちる（最寄りにも雨の履歴の座標にも使えないため）。名前（`kjName`）の無い観測所も落ちる（ヘッダーに観測所名を出すため。
  2026-10-07 の実物では全観測所が持つ）。観測所名と観測の時刻（最新の観測時刻）は、バッチが観測値と一緒に Hash へ書く。最寄りの観測所は、雨の材料・暑さ指数の
  情報提供地点と同じ`domain/geo.py: nearest_point_index`（球面の距離）で選ぶ。

  **天気コードの晴れ・くもり**: 応答のたびに、リクエストの地点を含む推計気象分布（天気）の最新のタイル
  （時刻一覧の最新の行。1時間ごとの実況）の画素の色を`jma_suikei_client.py: fetch_weather`が推計の区分（晴れ・くもり・雨・
  雨または雪・雪）に読み、`domain/weather.py: derive_observed_weather_code`が晴れ・くもりにする。時刻一覧とタイルは地図の気象庁タイルと同じ
  `JmaTileClient`のキャッシュ（時刻一覧はプロセス内で2分、タイルはRedisで20分）と気象庁への秒間上限を通る。
  推計の雨・雪の区分は空のくもりに数える（降っているかは観測所が決めるため）。時刻一覧・タイルが取れない・
  透明（推計の範囲の外）・凡例に無い色のときは空が分からず、降っていなければ天気コードだけがNoneになる
  （観測値は返す）。凡例に無い色は配信元が配色を変えた印なので抑制付きのWARNING（`log_throttled_warning`）を出す——応答のたびに通るため、
  抑制が無いと配色が変わった間は要求ごとに1行出る。時刻一覧・タイルを読めないときの警告も同じ。

  **暗黙の前提**: `refresh_all_stations`はリクエスト経路からは呼ばれない。`app/main.py`の
  lifespan内でAPScheduler（`AsyncIOScheduler`）へ`interval`トリガー
  （`jma_amedas_client.py: AMEDAS_REFRESH_INTERVAL_MINUTES`＝10分、気象庁の配信間隔）で登録され、`next_run_time=datetime.now()`
  によりアプリ起動直後にも即時1回実行される。このサービスの可用性は
  「main.pyのスケジューラが正常に起動・稼働し続けているか」という、
  `jma_amedas_service.py`単体のコードからは読み取れない外部要因に依存する。バッチ失敗時は
  WARNINGでログされるのみで自動リトライは無く、次回の定期実行（最大10分後）まで観測値は
  更新されない（TTL 15分がバッチ間隔10分より長いため、1回の失敗では即502にならない）。

  **1時間雨量の履歴（雨の材料の元）**: 同じバッチが、毎正時の1時間雨量（地図JSONの`precipitation1h`。
  その正時に終わる1時間の雨量）を観測所ごとに直近`RAIN_HISTORY_HOURS`本（`domain/rain.py`の窓の長さの
  一覧の最大）ぶん持つ。置き場はRedisの1キー（`jma:amedas:rain-history`、正時→観測所→mm）で、
  失うと気象庁へ全本を取り直すことになるためRedisに置く。バッチは欠けている正時だけをその正時の地図JSON
  （`data/map/YYYYMMDDHH0000.json`）から取る——平常時は新しく来た正時の1本、起動時にRedisが空なら全本
  （過去の地図JSONは2026-09-26の実測で76時間前の正時まで取れた。保持期間の公式の記載は未確認）。取れなかった正時は欠けたまま
  次のバッチで取り直す。地図JSONが取れても1時間雨量の値を持つ観測所が1つも無い正時も、取れなかったとして同じく取り直す
  （取れたとして残すと二度と取り直さず、その正時を含む窓が全国で値を持たないまま窓から外れるまで戻らない）。**Redisから履歴を読めない（冷却中・読みの失敗。置き場の読みが「取れない」を返す）ときは取りに行かない**
  （取り直しの判定が毎回「全本欠け」になり、10分ごとに全本を問い合わせ続けるため）。保存した形が今のコードで読めない履歴は、無いものとして扱う
  （WARNINGを出し、雨の材料は配らない）。値`[値, フラグ]`の値がnullのもの（欠測。フラグの公式の意味は
  未確認）は欠測として持ち、雨量の項目を持たない観測所（雨量計が無い）は載せない。
  読む側（`load_station_rain_materials`。`WeatherService.get_station_rain_materials`を通して、[動的材料・フィーチャー値配信](dynamic-way-values.md)の
  `RainWayService`と、ルートの探索範囲を組む`RoadGraphEngine`の気象の段が使う）は、最新の正時が
  `domain/rain.py: RAIN_HISTORY_MAX_AGE`より古い履歴を配らない——バッチが止まったまま古い雨量を今の値として塗らない・
  ルートの評価に使わないため。

  日の出・日没（`twilight`）はRedisへ保存せず、`get_nearest_observation`が
  クエリ地点（最寄り観測所ではなくリクエストの緯度経度そのもの）に対し都度
  `twilight.py: sunrise_sunset_jst`でローカル計算して埋め込む（地点依存のためバッチ
  時点では決定できない）。

- **`WarningService`**: 気象庁警報・注意報XML/JSONを地域コード（`ResolvedArea`）で解決。
  地点→区域（下の「警報の区域の境界」）→JMA警報エリア（`jma_area.resolve_area`）→電文取得の
  3段階すべてが失敗しうる箇所で、どこで失敗してもNone（ルーターが502）を返す。前の2段は
  `infrastructure/jma_area_boundaries.py: resolve_point_area`が持ち、区域が分からないこと（None）と地点が区域の外に
  あること（`OUTSIDE_AREAS`。警報なしとして返る）を分けて返す。JMAは大雨・
  土砂災害・高潮・暴風/暴風雪・波浪・大雪・その他の注意報を別電文（VPWW55〜61）として
  発表するため、`domain/jma_warning.py: collect_active_warnings`は電文配列全件を走査してcode単位で重複排除する。
  電文の形（`warning.class20Items`等）は`jma_warning_client.py`が`domain/jma_warning.py: WarningBulletin`（地域→種別）へ解き、
  コードを種別の名称へ、状態を発表中かへ読み替える（警報の無い地域の「なし」はコードを持たず、種別0件になる）。
  形の合わない電文・項目・種別は飛ばして残りで答え（付加事項だけが壊れた種別は付加事項を空にして残す）、飛ばした数を
  取得1回につき1行のWARNINGで出す。表に無いコードは載せず、そのうち発表中のもの（`jma_warning_client.py: WARNING_KINDS`）は、
  画面へは出さずに、そのコードを取得1回につき1行のWARNINGで出す（表の写しが古くなった印）。
  区域の項目がある電文はその中身（「なし」でも）を使い、区域の項目が無い電文だけを二次細分区域で探す（`WarningBulletin.kinds_for`）。

- **`WbgtService`**: 最寄りの情報提供地点（`domain/geo.py: nearest_point_index`）の環境省WBGT予報から、最も近い時刻の値を選ぶ（`domain/wbgt.py: current_forecast`）。
  配信元へは年間を通して問い合わせ、値があれば提供期間の外でも段を出す（配信元は発表の期間の外でも
  値を返す年がある）。提供期間は、今の時刻の値が得られないときに空と未取得を分けるためだけに使い、
  `domain/wbgt.py: provision_period`が日付で決める（環境省が年ごとに発表する運用期間は、4月第4水曜から
  26週後の水曜まで。終わりの水曜は10月の第3の年も第4の年もある）。期間の外は値が無いのが常
  （配信元はエラーではなく値の無い成功（`data`が空）を返す）なので、値が得られなければ取得の失敗でも
  空を返す。複数の発表回
  （`reference_time`）が検索窓に混在しうるため、まず最新の発表回に絞ってから現在時刻に
  最も近い`forecast_time`を選ぶ2段階選択を行う。現在時刻は呼び出し側（`/api/weather/wbgt`）が
  JSTで渡し、サービスは時計を読まない。検索窓は`datetime`で渡し、配信元の時刻の表記
  （JSTの`YYYYMMDDHHMMSS`）へはクライアントが直す。予測値の形（キー名・時刻の表記・10倍された暑さ指数）は
  `domain/wbgt.py: WbgtForecast`へ`wbgt_client.py`が解く。発表時刻の無い行は載せず、対象時刻・値が読めない行は
  その項目をNoneで持つ（最新の発表回を決めるのには数え、選ぶ対象からは外れる）。
  提供期間の中で地点マスタ・予測が取れない、検索窓に発表が無い、選んだ予測の値が読めないときは、今の警戒レベルが
  分からないとしてNone（ルーターが502）を返す。期間の中で発表が無いのは配信の止まりで、
  取得の失敗（クライアントがWARNINGを出す）とは別に抑制付きのWARNINGを出す（空の予測は1時間キャッシュされ、その間の要求ごとに通る）。期間初日は最初の発表
  （配信元の記録では3時）までの数時間、検索窓に発表が無く「未取得」になる。

- **`FloodService`**: 河川洪水予報。`WarningService`と同じ`jma_area_boundaries.py: resolve_point_area`で
  地点解決する。JMA洪水予報はstatus文字列ではなく`item.code`自体が発表/継続/
  解除/引き下げを区別する。`status`が「通常」でない電文（訓練・試験）は`flood_client.py`が
  電文を解く時点で落とし、サービスへ渡さない。

### 警報の区域の境界（`infrastructure/jma_area_boundaries.py`・`scripts/fetch_jma_area_boundaries.py`）

地点が属する区域（area.jsonの`class20s`のキー）は、気象庁が「予報区等GISデータ」として配る
「市町村等（気象警報等）」の境界から手元で引く。区域は市町村と1対1ではない——市町村を分割した
区域（例: 仙台市東部・西部、奈良市西部・東部）があり、そのコードは市町村コードの末尾へ`00`を
付けた形にならない。市町村コードから区域を組み立てる方式ではこうした区域を1つも引けないため、
区域そのものの境界を持つ。

| 項目 | 内容 |
|---|---|
| 配布元の版 | `jma_area_boundaries.SOURCE_URL`（配布ページの版ごとのzip。ファイル名が版を表す） |
| 置き場 | `backend/data/jma_area/<版の名前>.json`（本番はホスト側へマウントされ、デプロイをまたいで残る）。区域のコード→境界（WKB） |
| 作る時機 | `scripts/fetch_jma_area_boundaries.py`。置き場に今の版があれば何もしない。デプロイがコンテナを入れ替える前に毎回呼ぶので、本番で効くのは初回と版を上げたときだけ。開発機では手で1回打つ（打つまで警報・洪水予報は502で、画面に「未取得」が出て、引くたびに抑制付きのWARNINGが出る） |
| 変換 | 配布元のシェープファイルを読み、コードが空の図形（北方領土・帰属の決まっていない埋立地等）を落とし、区域ごとに許容誤差`SIMPLIFY_TOLERANCE_DEG`で簡略化する。元の頂点は1,400万を超え、そのままではbackendのメモリを数百MB使う（簡略化後は置き場のファイルが約66MB、読み込むと常駐が約80MB増え、読み込みに5〜10秒。開発機の実測） |
| 引き方 | 含む区域を引き、無ければ`NEAREST_LIMIT_DEG`以内の最寄りの区域へ寄せる。簡略化で隣の区域との間に隙間ができるうえ、海岸の区域は岸壁・橋の上を含まないことがある。寄せる距離を超えて離れた地点（遠い海上）は区域なし |
| 読み込み | 最初に引いたときにプロセス内へ1回だけ読む（イベントループの外で）。読めなければ抑制付きのWARNINGを出して`AreaBoundariesUnavailableError`を送出する（区域なしとは分ける。区域なしは警報なしとして返る） |

**版の上げ方**（区域の変更・市町村の合併）: 配布ページの更新履歴に「市町村等（気象警報等）」の
更新が載ったら、`SOURCE_URL`を新しい版のzipへ書き換えてデプロイする。置き場の名前が変わるため
デプロイが新しい版を取り直し、古い版のファイルは同じスクリプトが消す。区域の境界と地域マスタ
（area.json、実行時に取得）は別々に配られるため、境界だけが古いと、境界が返したコードを地域マスタで
辿れなくなる——このとき`jma_area_boundaries.py: resolve_point_area`が抑制付きのWARNING（「地域マスタ(area.json)で警報のエリアへ辿れない」）を出す
（`jma_area.resolve_area`はdomainで、抑制の仕組み（infrastructure）を読めないため、Noneを返すだけにする）。
配布ページは発表区域の変更の前に、変更後の版を「以降」の注記付きで先に置くことがある。版を
選ぶときは注記の日付と、今の地域マスタのコードに合う版かを見る。

## レート制限（`config.py`）の設計方針

風の格子点マップ（`wind_grid_rate_limit_per_minute`＝20/分）は対象範囲全体の格子点ぶんの応答（数百KB）を組み立てる
エンドポイントのため`/weather`（60/分）より低く抑える一方、詳細格子
（`wind_grid_detail_rate_limit_per_minute`＝30/分）はパン・ズームのたびに呼ばれうるためやや高め——1回あたりの
地点数は`WIND_GRID_DETAIL_MAX_POINTS`で上限が掛かる。警報・WBGT・洪水予報・アメダス（いずれも30/分）は「地点変更時
デバウンス起点で呼ばれる」という共通の呼び出しパターンを前提に揃えられている。

## シンプルな外部APIクライアントの共通ヘルパー（`simple_api_client.py`）

`jma_amedas_client.py`・`jma_warning_client.py`・`wbgt_client.py`・`flood_client.py`は
再試行を持たない（更新頻度が高くない、または機械アクセスへの
配慮のためTTLキャッシュで呼び出し頻度自体を抑える設計）。これらが共有する
「`TTLCache`参照→ミス時のみfetch→エラー処理→キャッシュ書き戻し」という骨格を
`cached_fetch(category, fetch, *, cache=..., key=..., catch=..., **log_fields)`が1箇所へ
まとめている。呼び出し元は`fetch`（実際のhttpx呼び出し＋パース＋必要ならフォーマット
検証）だけを渡す。JSONを取って最上位が配列か辞書かを確かめるところは`get_json`が持つ。フォーマット不正（配列であるべきなのにそうでない等）は
`UnexpectedShapeError`（`ValueError`のサブクラス）を`fetch`内から送出すると、`catch`の指定に
関わらず常にNoneへ倒れ、失敗として記録される。呼び出し元によって
捕捉すべき例外の範囲が異なる（例: `.json()`を呼ばないアメダスの最新時刻は`httpx.HTTPError`だけを
対象にする）ため、`catch`引数で個別に指定できる。キャッシュは取得の関数が引数で受け、作り方（件数の上限・TTL）は
各クライアントの`new_…_cache`が持つ。リクエストをまたいで持つのはDI工場（`api/dependencies.py`）で、地域マスタ
（area.json）は警報と洪水予報が同じものを使う。`jma_tile_client.py`/
`basemap_client.py`/`gsi_tile_client.py`（TTLCache以外のキャッシュバックエンド）は
対象外のまま各自の実装を維持する。

## 基礎地図プロキシ（`basemap_client.py`・`api/routers/basemap.py`）

OpenFreeMapのスタイルJSON・TileJSON・スプライト・グリフ・タイルを透過的にプロキシし、
`tile_cache`（ディスク）へ保存する。JSON（スタイル/TileJSON）は上流のURLを
`settings.basemap_public_base_url`へ書き換えて返す。**絶対URLへの書き換えは省略できない**
——MapLibreはスタイルJSON内の相対URLを、スタイル自身の取得元ではなく**ページのオリジン**に
対して解決し、スプライトのURLに至っては相対URLを明示的に拒否する。書き換えた内容を
そのままキャッシュはせず、キャッシュには書き換え前の内容を
`basemap-raw/`接頭辞のキーで保存し、書き換えは返す直前に毎回行う（設定変更がキャッシュを
消さずに即座に反映される）。バイナリ（スプライト・グリフ・タイル）は無加工でパスそのままの
キーに保存する。パスそのままのキーにJSONが残っていた場合は**採用しない**——書き換え済みの
内容で、当時の`basemap_public_base_url`が焼き付いているため、採用すると設定を変えても
古い配信先が配られ続ける。配信元が持たない部品（用意されていない書体の範囲等）は404として
返し、上流障害（502）と分ける——分けないと、無いことが`/api/debug/stats`の障害率へ乗り、
本当の障害が埋もれる。`POST /api/admin/basemap/refresh`は`tile_cache.clear_all()`で路面タイル等も
含めたディスクキャッシュ全体を消す。全利用者へ影響するため管理API認可境界
（`require_admin_basic_auth`）の内側に置き、入口は管理画面`/admin`の「データ保守」タブ
（`TileCachePanel.tsx`）だけに持つ。

## 地理院タイルプロキシ（`gsi_tile_client.py`・`api/routers/gsi_tile.py`）

国土地理院のタイルを**パスで指定して**透過的にプロキシしつつ`tile_cache`（ディスク）へ
キャッシュする。`basemap_client.py`と同じ「pathを丸ごとプロキシ＋`tile_cache`の永続ディスク
キャッシュ」方式だが、タイルはPNG単体でJSON応答を持たないためURL書き換えは不要。地理院タイルは
`basetime`/`validtime`のような時刻依存パラメータを持たない静的データのため、TTL付きキャッシュも
不要。クライアントは製品ごとの解釈を持たない——現在は色別標高図（`xyz/relief/…`、
`GET /api/gsi-relief-tile/{path}`がそのまま中継）と標高タイル（`xyz/dem_png/…`、下記）が使う。

### 標高タイルの変換（`services/terrain_tile_service.py`・`infrastructure/gsi_dem_png.py`）

`GET /api/gsi-terrain-tile/{z}/{x}/{y}.png`は、地理院の標高タイルをMapLibreの`raster-dem`が
読むTerrain-RGBへ移して返す（フロントはこれを`hillshade`レイヤーの入力にする）。
**配信元のエンコードのままでは渡せない**——地理院はセンチメートル単位の符号付き整数を2の補数で
置き、標高が無い画素に決め打ちの値（2^23）を入れるが、Terrain-RGBは-10000mを原点とする0.1m
刻みの符号なし整数で、無効値の表し方を持たない。無効値をそのまま大きな数として渡すと、標高の
ある画素との境界がすべて数万メートルの崖になり陰影が黒い縁で埋まるため、海抜0mへ倒す。
Terrain-RGBの刻みと原点は製品の定義として`domain/terrain_rgb.py`が持ち、画面が標高を読み戻す係数として
生成物へも出る。地理院の書式の読み取りとPNGの読み書きは`infrastructure/gsi_dem_png.py`が持つ。

変換後のタイルはキャッシュしない（ネットワークを使う変換前の取得だけが`tile_cache`に載る。
変換自体はタイル1枚ぶんの配列演算とPNGの書き出しで、同じものを二重に置く価値が無い）。
配信元が実データを持つのはz14まで（`domain/gsi_tiles.py: TERRAIN_MAX_ZOOM`）。

**恒久404のキャッシュ**: 色別標高図の整備区域外（404）は珍しくない正常系
で、他の失敗（タイムアウト・
5xx等）と区別して502・WARNINGログ・`/api/debug/stats`のerror集計へは乗せない。確認済みの
404は`GsiTileNotFound`センチネルとしてプロセス内メモリのみ（上限付きLRU、キー=path）に
記憶し、`tile_cache.py`の永続ディスクキャッシュへは書かない（将来GSI側の整備区域が広がった
場合、プロセス再起動だけで再取得の機会が来るようにするため）。`api/routers/gsi_tile.py`
は`GsiTileNotFound`を受け取ると404（それ以外の`None`は502）を返す。

## 気象庁MSMの同期と読み出し（`msm_client.py`・`domain/msm.py`）

風・降水の予報はREST APIではなく、Open-MeteoがAWS Open Dataで公開している前処理済みの
MSM（`.om`形式、CC-BY-4.0）をローカルへ同期して読む。予報を参照するたびに外部APIを
叩かないため、レート制限・クォータの制約を受けない。

| 項目 | 内容 |
|---|---|
| 配信元 | `settings.msm_base_url`（既定はopenmeteo.s3.amazonaws.comのjma_msm） |
| 同期対象 | `msm_client.py: FORECAST_VARIABLES`（消費するものだけ。例: 風の東西成分・南北成分・降水量）の、現在時刻から`msm_forecast_hours`先までを覆うチャンク |
| 読み出しの戻り値 | `msm_client.py: MsmSeries`（時刻列（タイムゾーン無しのJSTの`datetime`）と、項目ごとの[地点数, 時刻数]の配列）。配信元の変数名は持たない——変数名と項目の対応は`FORECAST_VARIABLES`だけが持ち、サービスは項目で読む |
| チャンク | 変数ごとに日本全域・`chunk_time_length`時間ぶんを1ファイルにまとめたもの。1ファイル十数MB |
| 保存先 | `backend/data/msm/`（本番はコンテナへマウントされるホスト側ディレクトリのため、デプロイをまたいで残る） |
| 更新の検出 | ETagによる条件付きGET。内容が変わっていなければ304で転送自体が起きない |
| 不要ファイル | 予報窓の外に出たチャンクと、`FORECAST_VARIABLES`から外した変数のチャンクは同期のたびに削除する（置き場の全ディレクトリを見る） |
| 定期実行 | `main.py`のAPScheduler（`msm_sync_interval_minutes`、`next_run_time=now`で起動直後にも1回） |
| 配信停止の検知 | 同期のたびに`freshness_from_meta`で最新run・予報終端を見て`warn_if_stale`がWARNINGを出す。値は`GET /api/debug/stats`の`msm`にも載る |

**配信が止まったことの検知**: 配信元が新しいrunを出さなくても同期そのものは成功する
（ETagで304になり取得0件）。「取得0件」は正常時と区別がつかないため、件数ではなく配信元
メタ情報の時刻で判定する。

| 条件 | しきい値 | 意図 |
|---|---|---|
| 新しいrunが公開されない | 最新runの**公開時刻**からの経過が、配信元の更新間隔の2倍以上 | 公開の更新を2本連続で落とした状態 |
| 予報が尽きかけ | 予報終端まで12時間未満 | 予報終端が現在時刻へ追いつくと風グリッドが読めなくなる。その手前で気づく |

**経過を測る起点はrun初期時刻ではなく公開時刻**（`last_run_availability_time`）。run初期
時刻からの経過は公開遅れ（実測3.5〜5時間）を含み、しかも次のrunが公開されるまで伸び続ける
ため、正常時でも「更新間隔＋公開遅れ」まで育つ。そこを境目にすると毎サイクルの末尾で発報する。
更新間隔を時間数として書き写さず配信元のメタから取るのは、格子の幾何と同じ理由（後述）。
判定結果は`GET /api/debug/stats`の`msm`にも載り、`/admin`のシステム状況パネルが表示する。

**格子の幾何を定数として持たない**: 緯度・経度の原点と間隔は、配信元が公開するメタ情報（S3上の static/meta.json）が
持つbbox（`crs_wkt`。WKTの表記から範囲を読むのは`msm_client.py`）と実データ配列の形状から
`MsmGrid.from_bbox_and_shape`が導出する。
定数として書き写すと、配信元が格子を変更したときにここだけ古い値が残り、エラーにならない
まま全地点の値が静かにずれる。チャンクの長さ・予報の終端・run更新間隔も同じメタ情報から取る。

**補間**: アプリ側の格子点（0.1度間隔）はMSMの格子（緯度0.05度・経度0.0625度）と一致しない
ため、周囲4点からの双一次補間で求める（`domain/msm.py: MsmWindow.interpolate`）。最近傍だと
アプリ側の格子の方が粗いぶん値が飛び飛びになる。切り出す索引範囲と対象地点は
`MsmGrid.window()`が1つの`MsmWindow`にまとめて返し、補間もその窓が行う——索引と地点を
別々の引数として渡せるようにすると、取り違えても例外にならないまま全地点の値がずれる。
風速・風向は東西/南北成分から求め
（`wind_speed_and_direction`）、風向は「吹いてくる方位」で返す。

**読めないときの振る舞い**: 同期が済んでいない・配信元の予報終端が現在時刻へ追いついた・置き場のファイルが
読めない場合は`MsmUnavailableError`（サービスはこの1つだけを受ける）。`WeatherService.get_wind_grid`は全地点を1回で読むので、
これを格子ごと読めない（None）へ変換し、`WindGridService`がそれを`WindGridUnavailable`にして、ルーターが502を返す。格子の欠損（NaN）は値ごとにNoneで返し、
画面はその時刻の点を飛ばす。ルート評価の風
（`get_wind_forecast_lattice`）はNoneを返し、呼び出し元は出発時点の値（`get_departure_wind`）へ倒すが、
そちらも同じMSMを読むため同時に読めず、**所要時間は無風で計算される**。候補はそのことを`wind_unavailable`で持ち、画面が候補の中身で知らせる
（`domain/leg_costs.py: LegCostComposer.wind_unavailable`。時別の系列も出発時点の値も無いとき）。読めなかった原因は、`read_series`を囲む`log_external_call`
（カテゴリ`msm:read`）が抑制付きWARNINGで残す。

**予報の長さ**: MSMはrunごとに39時間先（00/12UTCのrunは78時間先）まで持ち、配信は
run初期時刻から数時間遅れる。そのため現在時刻から先の長さはrunのタイミングによって
変動し、`msm_forecast_hours`（48時間）に満たないことがある。応答の時刻配列はその時点で
読める長さになり、フロントは配列長からスライダーの範囲を決める。
