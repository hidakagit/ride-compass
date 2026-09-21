# RideCompass アーキテクチャ設計

このドキュメントは**現状の姿**（技術選定・構成・API・データモデル・運用上の制約）を記す。
実装ステップの時系列・Road Graph移行の経緯といった**決定記録**は [decisions/](records/decisions/) へ分離した
（分離の経緯は改善計画T8参照）。本文はコード変更と同一コミットで更新し、常に最新へ保つこと。

- 実装ステップの時系列ログ: [decisions/step-log.md](records/decisions/step-log.md)
- Road Graph移行の経緯（Phase 0〜3・永続化・レビュー対応）: [decisions/road-graph-migration.md](records/decisions/road-graph-migration.md)
- 全体設計レビュー（2026-08-15）と改善実行計画: [design-review-2026-08-15.md](design-review-2026-08-15.md) / [improvement-plan.md](improvement-plan.md)

---

## 1. 技術選定

| 領域 | 採用technology | 備考 |
|---|---|---|
| Frontend | Next.js (App Router) + TypeScript + MapLibre GL JS | React 19 / Next.js 16 |
| Frontendスタイリング | Tailwind CSS v4（新規UI）+ CSS Modules（既存、機能改修時に段階移行）+ Radix UI + `frontend/src/components/ui/` | T252でTailwind併用導入、T299でRadix UI + 自前UIコンポーネント層（Button/Input/Card/Dialog/Checkbox）を新設。使い分け基準・Design Token一覧・意図的に作らないものは[frontend-design-system.md](frontend-design-system.md)参照 |
| Backend | Python + FastAPI | pytest でロジックを単体テスト |
| DB | PostgreSQL + PostGIS | PBF取込済みの生OSM層・Road Graph・路面タイル生成（ST_AsMVT）の第一系統として使用。取込範囲外はOverpassへ問い合わせず「データ未整備」として扱う（フォールバックを持たない）。`GraphService`は改善計画T222でDBなし構成（Overpassのみで動作する経路）自体を撤去済みのため、周回ルート生成には`DATABASE_URL`への実接続が必須（`road_graph_use_repository`は他の一部サービス[ElevationAttributeService/RegionService/AccidentService]のみに引き続き効く設定として残る。既定値はtrue）。SQLAlchemy+GeoAlchemy2経由（`infrastructure/database.py`, `road_graph_models.py`, `road_graph_repository.py`）。dev環境はネイティブのPostgreSQL 18.6＋PostGIS 3.6.2（Windowsサービス）で実接続検証済み（[decisions/road-graph-migration.md](records/decisions/road-graph-migration.md)「実PostGISでの動作検証（Phase 0）」参照） |
| ルーティングエンジン（周回ルート生成、`/api/routes/generate`） | **road_graph単一構成**（改善計画T462でopenrouteserviceエンジンを完全撤去、切替設定自体が廃止済み） | 周回生成戦略は単一の`RouteGenerator`（[backend/app/services/route_generator.py](../backend/app/services/route_generator.py)）が持ち、経路計算・評価を`RoadGraphEngine`（[backend/app/services/road_graph_engine.py](../backend/app/services/road_graph_engine.py)、自前ホスト・外部APIキー不要、`GraphService`・`domain/routing.py`の探索［一対全木・2点間探索ともnumbaでJITしたDijkstra/A*。出発からの経過時間をラベルとして持ち回るため、コストを辺の静的な属性とみなすライブラリは使えない］を使う）へ委譲する。改善計画T236（経路品質比較、致命的な差異なし）・T241（道路グラフの連結性、致命的な問題ではない）・T242〜T246（本番DBのmigration未適用・DELETE性能問題という本番実行不能の原因を解消、実データで検証済み）を経て既定値を`road_graph`へ切り替え（改善計画T247、2026-08-23）、以降の運用実績を踏まえてopenrouteserviceエンジン・`config.py`の`routing_engine`設定自体を完全撤去した（改善計画T462、2026-08-31）。詳細は[decisions/road-graph-migration.md](records/decisions/road-graph-migration.md)、撤去の経緯は下記「ルーティングエンジンの切り替え対応」節参照 |
| ルーティングエンジン（単一区間確認、`/api/routes/preview`） | **road_graph単一構成**（改善計画T462で切替設定を廃止） | Step3の疎通確認用エンドポイント。`dependencies.py: get_preview_builder`が`RoadGraphEngine.preview_segment`（評価軸重み付きコストで最短経路を1回探索、generateと同じコスト式）を組み立てる。`RoutingService`/`ORSClient`はT462で削除済み。previewはリクエストボディでの評価重み上書きに対応しない（既定値のみ使用） |
| 地図タイル | OpenFreeMap（`https://tiles.openfreemap.org/styles/liberty`、APIキー不要） | `tile.openstreetmap.org` は bulk/非ブラウザアクセスをブロックするポリシーがあり不採用（後述）。Step10でバックエンド経由のプロキシ＋ファイルキャッシュ（`BasemapClient`）を追加 |
| 天候 | **気象庁MSM**（Open-MeteoがAWS Open Dataで公開する前処理済み`.om`ファイルをローカル同期。外部の気象予報APIには依存しない） | `WeatherService`（[backend/app/services/weather_service.py](../backend/app/services/weather_service.py)）が`msm_client`経由で読む。`get_wind_grid`/`get_wind_forecast_series`が風の格子点マップとルート評価の風を、`get_conditions`が「今日の見通し」パネル用の現在値・日次集計・時間帯別の流れを組み立てる（天気コードは雲量・降水・気温から導出、日の出/日没は`domain/twilight.py`で計算） |
| 標高 | **国土地理院（GSI）DEMタイル**（APIキー不要、日本国内限定） | 取込（[backend/app/batch/source_adapters/gsi_dem_tile.py](../backend/app/batch/source_adapters/gsi_dem_tile.py)）がタイル1枚を1行として`source_features`へ入れ、派生（`batch/derive_raster_materials.py`）が区間ごとの標高属性を作る。**実行時にGSIへ取りに行く経路は無い**。ルート単位の獲得標高・最高/最低標高・最大勾配は`services/elevation_aggregation.py`が区間の属性から集約する |
| 標高（地域レイヤー） | **国土地理院 色別標高図**（ラスタタイル、APIキー不要） | `MapView.tsx`がMapLibreのraster sourceとして`GET /api/gsi-relief-tile/{path:path}`（`GsiTileClient`、改善計画T572）経由で重ね描き。候補ルートに紐づかない「地域全体」の標高表示用で、Step5の標高API（点ごとの数値取得）とは別用途 |
| 路面（地域レイヤー） | **PostGIS**（`ST_AsMVT`、`road_graph_use_repository=true`時）／DBなし構成では常に空タイル | `RegionService`（[backend/app/services/region_service.py](../backend/app/services/region_service.py)）が候補ルートに紐づかない「地域全体」の路面レイヤーを提供する。PBF取込済み範囲はPostGIS側（`road_graph_repository.py`の`_ROAD_SURFACE_TILE_MVT_SQL`）でMVT生成まで完結し、取込範囲外・DB障害・DBなし構成は空タイル（`infrastructure/vector_tile.py: encode_empty_road_surface_tile`）を返す。Overpass APIによる取得は改善計画T22で撤去済み |

### 地図タイルプロバイダに関する注記
当初 `tile.openstreetmap.org` のラスタタイルを想定していたが、bulk/プログラム的アクセスに対してブロックポリシー（`x-blocked` ヘッダーで拒否）があり、本番はもちろん開発環境でも安定して使えないことを実機検証で確認した。そのため、MapLibre GL JS向けにAPIキー無しで提供されている OpenFreeMap のベクタースタイルに切り替えた。本番運用時は利用規約を再確認し、必要に応じて専用プロバイダ（MapTiler等、APIキー方式）へ切り替えることを推奨する。

### フロントエンド実装上の注意（maplibre-gl バージョン固定）
`maplibre-gl` の最新メジャー（v6系）は、Web Worker のスクリプトURLを `new URL(`./${file}`, import.meta.url)` という動的テンプレートリテラルで解決する実装になっており、Next.js のバンドラ（Turbopack / Webpack のいずれも）がこれを静的解析できず、Workerが実際には空のページを読み込んでしまい、スタイル処理・タイル取得が永久に止まる（`isStyleLoaded()` が `true` にならない）現象を実機で確認した。回避策として `maplibre-gl` を `^5.24.0`（自己参照Blob方式のWorkerを使う、Next.js/Webpackとの互換実績が豊富なメジャーバージョン）に固定している。将来 v6系対応が改善された場合はアップグレードを検討する（追随の可否と、6系へ上げなくてもXSS到達経路を塞げることは[docs/records/tasks/T703.md](records/tasks/T703.md)。2026-09-11に6.9.0の配布物でこの制約が現在も有効であることを再確認した）。

### フロントエンド実装上の注意（`@maplibre/maplibre-gl-style-spec` の完全固定）
`@maplibre/maplibre-gl-style-spec` は `24.10.0` とキャレット無しで完全固定している。このパッケージの `createExpression` は、地図の paint/filter 式が正しいことをテストで検証するための評価器として使っており（`MapView.overlayFilters.test.ts`・`staticAttributeLayers.test.ts`）、**地図が実際に式を評価するのは `maplibre-gl` が内部に持つ同パッケージ**である。両者の版がずれると、テストが通る式が実機で別の意味になりうる（テストの評価器だけが新しい構文を受け付ける、等）。`maplibre-gl` 側の依存範囲（5.24.0 では `^24.8.1`）に収まる版を選び、キャレットで勝手に動かないよう固定する。`maplibre-gl` を上げるときは、上げた先が要求する範囲にこの固定版が収まっているかを併せて確認する。

### バックエンド運用上の注意（Windows: `uvicorn --reload` の多重プロセス）
Windows環境では `uvicorn --reload` はリローダー親プロセスとワーカー子プロセス（`multiprocessing.spawn`）に分かれる。親プロセスだけを `taskkill` すると子プロセスが孤児化して同じポートに残り続け、古い設定（環境変数など）のまま応答し続けることがある。`.env` を編集後にAPIの挙動が変わらない場合は、`netstat -ano | findstr :8000` で該当ポートを握っている全PIDを確認し、それら全てを `taskkill /F /PID <PID>` で終了してから起動し直すこと。また `.env` の変更は `--reload` のファイル監視対象外のため、変更後は必ずプロセスの完全な再起動が必要。また、複数ファイルを短時間に連続編集すると `watchfiles`（uvicornのリローダーが使うライブラリ）の再読み込みが1回分しか発火せず、古いコードのまま動き続けることが実機で確認された（`404 Not Found` になる等）。挙動が古いままに見える場合は一度プロセスを完全に再起動すること。

### デプロイの反映確認（backend/frontendで注入元が異なる点に注意）
デプロイ（`git push`からのビルド完了）が実際にサービスへ反映されたかを、デプロイ操作をしたブラウザ以外（別端末・CLI・監視ツール等）からでも確認できるようにするため、バックエンド・フロントエンドの両方にデプロイ識別情報を返すエンドポイントを用意している。改善計画T263（backendのOracle Cloud VM移行）により、**backendとfrontendで`commit`の注入元が異なる**点に注意（frontendは今もRender上で稼働、backendのみ移行済み）。

- **`commit`**:
  - **frontend（Render）**: RenderのWebサービス（gitリポジトリと連携したデプロイ）には`RENDER_GIT_COMMIT`（デプロイされたコミットのフルSHA）が自動的に環境変数として注入される（Render側の設定不要、`.env`にも書かない）
  - **backend（Oracle Cloud VM）**: Render固有の自動注入は使えないため、デプロイワークフロー（[.github/workflows/deploy-backend.yml](../.github/workflows/deploy-backend.yml)）がVM上で`git rev-parse HEAD`を実行し、`GIT_COMMIT`環境変数として`docker run`時に明示的に渡す（改善計画T263フォローアップ、T263完了直後は未実装で`commit`が恒久的に`null`になる回帰があった）
  - いずれもローカル開発環境ではこれらの環境変数が無いため`null`になる
- **`started_at`**: プロセス起動時刻（ISO8601、モジュール読み込み時に一度だけ評価）。デプロイのたびにプロセスが再起動される運用（Render・Oracle VM向けdeploy-backend.ymlのいずれも`docker stop`→`run`で再起動）のため、直近デプロイのおおよその時刻としても使える（`commit`が変わっていなくても、再起動自体が起きたかどうかの確認に有用）
- **バックエンド**: `GET /health`（`backend/app/api/routers/health.py`、`backend/app/config.py`の`Settings.git_commit`、`backend/app/version.py`の`STARTED_AT`）。`test_health.py`でcommitのnull/反映両パターンを検証済み
- **フロントエンド**: `GET /api/version`（[frontend/src/app/api/version/route.ts](../frontend/src/app/api/version/route.ts)、新規のRoute Handler）。`process.env.RENDER_GIT_COMMIT`を直接読み、バックエンドと同じレスポンス形（`status`/`commit`/`started_at`）を返す。`export const dynamic = "force-dynamic"`でビルド時の静的最適化・キャッシュを無効化し、リクエストのたびにサーバーの現在の状態を返すことを保証している（`next build`のルート一覧で`ƒ /api/version`＝動的レンダリングになっていることを確認済み）。`route.test.ts`（Vitest）でcommitのnull/反映両パターン・started_atの妥当性を検証
- **確認方法**: `curl https://<backendのURL、現在はOracle VM上のドメイン>/health`と`curl https://<render-frontend>.onrender.com/api/version`（またはブラウザで直接開く）でそれぞれ`commit`を取得し、ローカルの`git rev-parse HEAD`と比較する。両方一致していれば最新版が反映されている
- **タイルプロパティを削除する変更のデプロイ順序に注意**: backend・frontendは別サービスとして独立にデプロイされ、反映タイミングは同期しない（移行前後を通じて変わらない制約）。road-surface-tilesのプロパティ追加（v2〜v8）は常に後方互換だった（旧フロントは新プロパティを単に無視するだけ）が、v9（交通ストレスレシピ外出し基盤）は計算済みの`traffic_stress`プロパティを削除する初めての非互換変更。backendがv9を先に配信すると、まだ`["!", ["has","traffic_stress"]]`を使う旧フロントの凡例フィルタが全地物に一致し、交通ストレスレイヤーが全線「不明・他」（グレー）表示になる（数分〜デプロイ完了まで自己解消するが、その間は誤った見た目になる）。**frontendを先に（または同時に）デプロイし、backendのv9切替がfrontendの新実装より先に本番へ出ないようにする**こと。

### 本番PostgreSQLの設定（既定から変えたものと、その理由）

既定から変えた設定はここへ理由つきで残す。**理由の無い設定変更を増やさない**——
なぜそうなっているか分からない値は、次に誰かが戻すか、別の値を足して悪化させる。

**`jit = off`**（`ALTER DATABASE`で両DBへ設定）。材料を引くクエリは材料ごとにCASE式を
並べるため式が非常に多く、JITのコンパイル代を回収できない。PostgreSQL自身の出力:

```
JIT: Functions: 45
Timing: ... Optimization 369.2ms, Emission 440.7ms, Total 924.7ms
Execution Time: 1605.6 ms      （jit=off なら 678.6 ms）
```

実行1,605msのうち925msがコンパイルそのもので、実処理の678msより高い。発動条件の
jit_above_cost（PostgreSQLの設定）は推定コストの高さを見るが、推定コストは行数だけでなく**式の数**でも
上がるため、式が多いだけで行数はそこそこのクエリでも発動する。**式の少ないクエリは
ほぼ変わらず、式の多いクエリだけが1.7倍速くなる**という非対称が、この説明を裏づける。

`ALTER DATABASE`の設定は**新規接続から効く**。稼働中のコンテナの既存接続には
次のデプロイまで反映されない。

### Redisキャッシュ基盤とJMAアメダス連携

JMA（気象庁）のアメダス観測値を扱うため、Redisを新規インフラとして導入した。Redisは「TTL付きキャッシュ、またはPostGIS/実データ源へのフォールバックが
必ず効くcache-aside」専用の層で、正本データを持たない（`app/infrastructure/
redis_client.py`）。ローカル開発は`docker-compose.yml`のredisサービス、本番はOracle
Cloud VMへネイティブ（apt、PostgreSQLと同じ構成）で導入する想定（backendコンテナが
`--network=host`のため追加設定なしで到達できる）。

**メモリ上限**: 本番`/etc/redis/redis.conf`へ`maxmemory 2gb`・`maxmemory-policy volatile-lru`を
設定する（VM全体11GB中、PostgreSQL・backendアプリ[コンテナ`--memory=6g`上限]との共存を
考慮した値）。**上限を外すと、用途を広げたときに同居するVM全体のメモリを圧迫する**。
現行キーは全てTTL付きのため`volatile-lru`（TTL付きキーの中からLRUで退避）を選ぶ。

- **アメダス（`app/services/jma_amedas_service.py`）**: 気象データはPostGISへ書き込まず
  Redis上で完結させる（気象データは短命でディスクI/O向きではないため）。JMAの観測値
  エンドポイントは1地点だけを絞り込めず全国約1,300観測所ぶんを1レスポンスで返す仕様の
  ため、リクエストのたびに個別フェッチせず、`main.py`のAPScheduler定期バッチ
  （`AMEDAS_REFRESH_INTERVAL_MINUTES=10分`、気象庁の公式観測・配信周期に合わせた値）が
  全国分をまとめて取得しRedis Hash（`jma:amedas:{station_id}`、TTL 15分）へ書き戻す。
  リクエスト経路（`GET /api/weather/amedas`）はRedis読み取り専用で、JMAへは問い合わせない。
  体感温度はJMAが提供しないため、気温・湿度・風速からBOM（オーストラリア気象局）の
  Apparent Temperature式で自前計算する（`domain/jma_amedas.py:
  apparent_temperature_from_amedas`）。日照時間（`sunshine_10min_minutes`、frontend側の
  簡易天気アイコン判定に使う）もRedisへ含める。日の出/日没は外部に問い合わせず
  astralによるローカル計算（`domain/twilight.py: sunrise_sunset_jst`）で、クエリ地点
  そのもの・当日（JST）の値を`get_nearest_observation`が都度計算して合成する
  （Redisにはキャッシュしない。計算コストが無視できるほど軽いため）。
- **`GET /api/weather`と`GET /api/weather/amedas`は完全に独立**（2026-08-29、方針
  「常設エリアは実測値、今日の見通しは予測値」）: 実測と予報は取得経路から分かれており
  （`useWeatherConditions.ts`のweather/amedasが独立フェッチ）、`/api/weather`は常に予報の
  値を返す（TodayOutlook専用、マージしない）。
- **降水ナウキャスト・MSMはRedisを経由しない**: ナウキャストはフロントエンド
  （[precipitationNowcast.ts](../frontend/src/components/Map/precipitationNowcast.ts)）が
  `targetTimes_N1/N2.json`を直接取得してタイルURLを組み立てるため、バックエンド側に
  解決の経路を持たない。MSMのGRIB2解析は[T389](records/tasks/T389.md)（有償契約が前提、保留中）で
  扱う。
- **JMA動的タイル本体のRedis cache-aside（`app/infrastructure/jma_tile_redis_cache.py`、
  改善計画T510）**: 上記「降水ナウキャスト・MSMのRedis化は見送り済み」とは別物——あちらは
  「タイムスタンプ解決ヘルパー・GRIB2解析スケルトン」という新規機構の話で、こちらは
  既存の`jma_tile_client.py`（プロキシ＋キャッシュ、T412）が使っていたタイル本体の
  キャッシュ先を、ファイル永続キャッシュ（`tile_cache.py`、有効期限なし）からRedis
  cache-aside（TTL20分）へ差し替えただけ。動機は「キャッシュヒットでも
  `jma_tile.py`のレート制限を消費していたため、既に見た範囲を往復パンするだけで429に
  なっていた」という報告への対応で、(1)キャッシュ参照をレート制限より先に行う構成へ
  入れ替え、(2)アメダスと同じAPScheduler定期バッチ（`jma_tile_prewarm_service.py`）で
  実運用範囲（`WIND_GRID_BBOX`）ぶんを事前に温める、の2点をあわせて行った
  （[動的気象レイヤー](modules/backend/weather-dynamic-layers.md)「JMAタイル系の
  共通プロキシ」節参照）。正本を持たないcache-aside（JMAへ再フェッチ可能）で
  road_graph_tilesとは異なる。
- **Open-Meteo全面代替の可否（T645で達成済み）**: ルート評価（旧`WindService`、区間ごと・将来時刻の風速
  風向）と風の格子点マップは、任意地点×任意時刻の予報が必要なためアメダス（観測専用）・
  ナウキャスト（降水のみ・60分先まで）では代替できず、MSM実装後に改めて検証する
  （候補はMSMのみだが[T389](records/tasks/T389.md)は保留中）。降水短時間予報（`jmatile/data/
  rasrf/`、無料・公式、15時間先まで確認済み）は[T407](records/tasks/T407.md)、線状降水帯予測マップ
  （`sjfcstmap`、無料・公式）はキキクルと合わせて[T410](records/tasks/T410.md)で実装済み
  （いずれも「動的気象レイヤー」節参照）。UV指数・weather_code相当のJMAプロダクトは
  無料の代替が見つからずOpen-Meteo依存を継続していたが、T645でMSMのローカル同期へ移行し、
  weather_code相当は雲量・降水・気温からの導出（`domain/weather.py: derive_weather_code`）
  へ置き換え、UV指数は表示ごと廃止してOpen-Meteo依存を解消した。
- **ルート生成の経路にRedisを置かない（[T652](records/tasks/T652.md)）**: 探索が読む材料は自前のPostGISから復元でき、Redisは外部への負荷を肩代わりするものだけに使う（docs/conventions/caching.md）。

### ルーティングエンジン

**road_graph単一構成**。エンジンを切り替える仕組み（設定の旧`routing_engine`、複数値の
`RouteGenerateResponse.engine`、旧`OpenRouteServiceEngine`）は撤去済みで、探しても実装に
無い（切り替えが存在した期間の設計記録は[decisions/road-graph-migration.md](records/decisions/road-graph-migration.md)）。

## 2. ディレクトリ構成

トップは`backend/`（FastAPI）・`frontend/`（Next.js）・`docs/`・`scripts/`（リポジトリ横断の
CI/pre-commitスクリプト）。**個々のファイルがどのモジュールの責務かは
[docs/modules/README.md](modules/README.md)の対象ファイル表を見る**——そちらは
`scripts/review_checks.py`が「実装ファイルがどこにも載っていない」状態を機械的に検出するため、
新しいファイルが増えても静かに古くならない。ここでは層の役割と、層をまたぐときの約束だけを示す。

### backend（`backend/app/`）

依存の向きは `api → services → domain` と `api → services → infrastructure` の一方向で、
`domain`はどの層にも依存しない。

- **`api/`**: HTTPの境界。`routers/`がエンドポイント、`dependencies.py`がDI工場と
  レート制限、`admin_auth.py`が管理APIの認可境界、`cache_policy.py`が`Cache-Control`を
  一元管理する（新規エンドポイントの追加漏れは`tests/test_cache_policy.py`が全ルート走査で
  検出する）。タイル系エンドポイントが共有する座標検証と応答組み立ては`_tile_http.py`。
- **`domain/`**: 外部I/Oを持たない純粋なロジックと語彙の正本。評価軸・材料・一次属性の
  レジストリ、スコアリング、地理計算、気象の判定ロジックが属する。**「同じ概念の定義が
  2箇所にある」状態をここで解消する**のが層の役割で、SQL・タイル・frontendはここが持つ
  定義から導出する。
- **`services/`**: ユースケースの組み立て。ルート生成、タイル配信、気象取得のように
  「複数のinfrastructureとdomainを束ねて1つの応答を作る」処理が属する。
- **`infrastructure/`**: DB・外部API・キャッシュ・ログといった外側との接続。キャッシュの
  鍵の組み立ては`cache_identity.py`が唯一の正本（「無効化」の節参照）。
- **`batch/`**: PBF取込と事前計算。`refresh_derived.py`がPBF再取込を除く一式を1コマンドで
  実行し、登録漏れは`app/batch/precompute_*.py`をglobで引くテストが検出する。書き込みに
  成功したバッチは`derived_data_meta.revision`（DB）を進め、backendのディスクキャッシュが
  TTL付きでこれに追随する——バッチはデプロイを伴わないため、コード内の定数では表せない。

`backend/migrations/`はDDLのみを管理する（評価軸の行データはAPI経由で変更する。
CLAUDE.md「コミット時の同期ルール」参照）。`backend/scripts/`は運用・生成スクリプトで、
`export_openapi.py`がfrontend向けの生成物を書き出す。

### frontend（`frontend/src/`）

- **`app/`**: Next.js App Routerのページとroute handler（`/admin`配下の管理APIプロキシを含む）。
- **`components/`**: 機能単位のディレクトリ（`Map/`・`AxisStudio/`・`MapOverlayControls/`等）。
- **`hooks/`・`lib/`**: 画面をまたぐ状態・ユーティリティ。
- **`services/`**: backend APIを叩く薄い層。
- **`types/generated/`**: `export_openapi.py`の出力（OpenAPIスキーマと、軸カタログ・
  材料カタログ・タイル世代等の付随生成物）。コミット対象で、CIの`api-contract`ジョブが
  ドリフトを検知する。

**backendが持つ値の一覧・既定値をfrontendが手書きで複製しないこと**——複製すると片側だけ
変えても全テストが緑のまま通り、キー集合の完全一致を要求するAPIでは全リクエストが422に
なる等の形で本番に出る。必要な値は`types/generated/`経由の片側importで受け取る。

---

## 3. Docker構成

`docker-compose.yml`（ルート直下）で以下3サービスを定義:

- `frontend`: Next.jsアプリ（ポート3000）
- `backend`: FastAPIアプリ（ポート8000）
- `postgres`: `postgis/postgis` イメージ（ポート5432）。Step1-2ではバックエンドから未接続だが、将来のルート/POIデータ保存に備えて土台として用意。
- `redis`: `redis:7-alpine` イメージ（ポート6379、改善計画T387）。JMA気象データの短命
  キャッシュ・road_graph_tilesのcache-aside層専用（永続化ボリュームは持たない）。

Valhallaは自前構築の複雑さ（OSM PBF抽出・タイルビルド）を踏まえ、Step3実装時に改めて「Docker Composeに含めるか」「外部サービス(openrouteservice)を使うか」を判断する。現時点では暫定的にopenrouteservice APIを使う想定のため、Compose上のコンテナ化は不要。

---

## 4. API設計

### 現状

```
GET /health   # commit/started_atはデプロイ確認用（後述「デプロイの反映確認」参照）
→ 200 { "status": "ok", "commit": "a1b2c3d4e5f6...", "started_at": "2026-08-14T10:00:00+00:00" }
  # commit: デプロイワークフローが注入するGIT_COMMIT（デプロイされたコミットのフルSHA、
  #         改善計画T263でRender自動注入のRENDER_GIT_COMMITから改称）。
  #         ローカル開発環境では環境変数が無いためnull
  # started_at: プロセス起動時刻（UTC、ISO8601）。デプロイのたびにプロセスが
  #             再起動される運用のため、直近デプロイのおおよその時刻としても使える

GET /api/debug/stats   # 外部API呼び出し・キャッシュのカテゴリ別集計（呼び出し数/エラー数/ヒット率/所要時間、
                       # error_types内訳・last_error_type/at・last_success_at・retried_calls/
                       # retry_attempts_total・stale_fallback_used。夜間502調査（改善計画T92）で
                       # 「失敗の主な理由を推測できる程度の情報」として追加）と429拒否数のプロセス内
                       # スナップショット（infrastructure/debug_log.py）。error_typesはHTTPステータス
                       # （例: "http_429"）か例外クラス名のみの粗いラベルで、メッセージ本文・URL・
                       # 座標は含まないため、debug_modeに関わらず/healthと同様に常時公開。
                       # プロセス再起動でリセット
Response 200:
{ "commit": null, "started_at": "2026-08-14T10:00:00+00:00", "engine": "road_graph", "debug_mode": false,
  "external": { "msm:read": { "calls": 120, "errors": 8, "error_types": {"MsmUnavailableError": 6, "OSError": 2},
    "last_error_type": "MsmUnavailableError", "last_error_at": "2026-08-17T21:03:11+00:00",
    "last_success_at": "2026-08-17T21:04:02+00:00", "retried_calls": 15, "retry_attempts_total": 22,
    "stale_fallback_used": 3, "cache_hit_rate": 0.71, "avg_ms": 340, "max_ms": 4200 }, ... },
  "rate_limit_rejections": { ... } }

POST /api/routes/preview   # Step3: 単一区間のルート取得確認用（暫定エンドポイント。デバッグ・疎通確認用に残置。
                           # フロントエンドからは呼ばれない——クライアント関数も改善計画T677で撤去した）
Request:
{ "origin": {"latitude":35.7597,"longitude":139.7387}, "destination": {"latitude":35.71,"longitude":139.75} }
Response 200:
{ "distance_km": 6.85, "duration_minutes": 17.9, "geometry": { "type":"LineString","coordinates":[...] } }
Response 502（road_graphエンジンでの経路取得失敗時）:
{ "detail": "ルート取得に失敗しました: ..." }
Response 429（同一クライアントIPから1分あたり20リクエスト（`PREVIEW_RATE_LIMIT_PER_MINUTE`）を超えた場合）:
{ "detail": "リクエストが多すぎます。しばらく待ってから再試行してください。" }

POST /api/routes/generate   # Step4: 周回ルート候補生成、Step5: 標高フィールド追加、Step7: wind_score追加、Step8: road_score/total_score追加
                            # ルーティングエンジンはroad_graph一本（改善計画T462でopenrouteserviceエンジンを撤去）。
                            # レスポンスのengineフィールドは常に"road_graph"を返す（API互換性のため存置）。
                            # 改善計画T265: 冷パス（未splitな新規エリアへの初回アクセス、数十秒〜最大316秒
                            # [T248実測]）がブラウザのfetchを長時間ブロックしないよう、バックグラウンド
                            # ジョブ化した。本エンドポイントは即座（数百ms）にjob_idを返すのみで、実際の
                            # 生成は下のGET /api/routes/generate/{job_id}をポーリングして完了を待つ
                            # （frontend services/routeApi.ts: generateRoutes参照）。
Request:
{ "latitude":35.7597, "longitude":139.7387, "distance_km":30, "distance_tolerance_km":5, "route_type":"loop" }
Request（評価重みの上書き。研究用・省略可。docs/research-interface-review-2026-08-15.md §10-1）:
{ ...上記に加えて,
  # route_preferenceは公開軸のaxis_idを**全件**指定する（欠けると422。公開軸はDBが正本で
  # 軸スタジオから増減するため、現在のキーはGET /api/axis-catalogで引く）。
  "route_preference": { "<公開軸のaxis_id>": 0.15, ... },
  "penalty_strength": 1.0, "max_average_grade_percent": null,
  "hard_filters": { "no_bicycle":true, "motorway":true, "trunk":false } }
  # 省略時はAXIS_DEFINITIONSのdefault_weight（改善計画T316）。
  # 指定する場合はいずれも
  # 全フィールド必須・非負（部分指定でクラス既定値が黙って入る事故を防ぐ。
  # route_preference・hard_filtersは全フィールド必須の別モデルで、一部だけの指定は422になる。
  # route_preferenceのキーは公開軸のaxis_id集合（改善計画T221 Stage B・T292で軸ごとの
  # 固定フィールドからaxis_idキーの辞書へ一般化済み。AXIS_DEFINITIONSのis_published=True
  # の軸のみが対象で、car_stressを支える内部軸は含まない。7章参照）。改善計画T292で専用
  # Pythonレシピ（car_stress_recipe/road_suitability_recipe/motor_vehicle_density_recipe）は
  # 廃止され、car_stressを含む全軸の材料はAXIS_DEFINITIONSの内部軸階層（下記参照）へ
  # 一本化された。
  # penalty_strength（改善計画T218・T12 ADR原則1）はコスト式の割増率の強さ、
  # max_average_grade_percentは0次ハードフィルタの勾配しきい値で、いずれもroad_graph
  # エンジンのみに効く。
  # hard_filters（改善計画T266）は0次ハードフィルタ（`no_bicycle`/`motorway`/`trunk`、
  # domain/hard_filters.py: DEFAULT_HARD_FILTERS）の個別ON/OFF。route_preference等の
  # 「2次の重み」とは異なり、Falseにしたフィルタに該当する道路はコストを上げるのではなく
  # 探索グラフから除外しない＝候補に含める（0次＝スコア計算に一切登場しないハード制約）
Response 202（ジョブを受理、即座に返る）:
{ "job_id": "5f2e1a3b4c5d6e7f8a9b0c1d2e3f4a5b" }
Response 400（waypoints/destination指定がroad_graphエンジン以外の構成で送られた場合）:
{ "detail": "waypoints/destinationはroad_graphエンジンでのみ利用できます。" }

GET /api/routes/generate/{job_id}   # ジョブの状態をポーリングする（改善計画T265）。
                                    # POST側のper-IPレート制限・同時実行数上限は投稿時点のまま
                                    # （待ち行列化はしていない）。本エンドポイント自体は認可・
                                    # レート制限を課さない（job_idはUUID相当で推測困難、GET自体は
                                    # 軽量なメモリ参照のみのため）。
Response 200（status="queued"|"running"、結果はまだ無い）:
{ "status": "running", "result": null, "error": null }
Response 200（status="done"、resultにPOST側が従来返していた本文がそのまま入る）:
{
  "status": "done",
  "error": null,
  "result": {
  "routes": [
    {
      "id":"route-090", "direction_label":"東", "distance_km":32.7,
      "elevation_gain_m":12.8, "min_elevation_m":1.1, "max_elevation_m":9.6,
      "material_values": { "wind_drag_ratio":1.96, "gradient_percent":0.8 },
      "segments": [
        {
          "geometry": { "type":"LineString","coordinates":[...] },  /* 区間の道なり形状（ルートgeometryの部分列。地図の色分けはこれに沿って描く） */
          "start_latitude":35.7597, "start_longitude":139.7387,
          "end_latitude":35.7602, "end_longitude":139.7390,
          "cumulative_distance_km":0.0, "distance_km":1.16,
          "estimated_arrival_time":"2026-08-13T23:20:43",
          "material_values": { "gradient_percent":0.2, "wind_drag_ratio":-0.83 },
          "car_stress":2,
          /* ↑ 車ストレスの生値（P1）。material_valuesと
             同じく、難易度への寄与とは別に表示・研究モード用に生値も保持する */
          "axis_difficulties": { "gradient":2.0, "wind":0.0, "surface_q":0.0, "stop_density":5.0,
            "car_stress":25.0, "accident":0.0, "bicycle_infra_quality":0.0 },
          /* ↑ axis_id→difficulty(0-100)の汎用dict（改善計画T309）。評価できなかった軸は
             キー自体を省略する（例のnightのように非公開または材料欠損の軸）。軸スタジオでの
             公開軸の増減にそのまま追従し、固定7フィールドは持たない */
          "difficulty":4.6
        }
        /* ...区間の数だけ続く（road_graphエンジン: Edge数分） */
      ],
      "geometry": { "type":"LineString","coordinates":[...] },
      "overall_difficulty": 22.5,  /* segments.difficultyの距離加重平均（絶対基準、実験間比較用） */
      "axis_difficulties": { "gradient":1.8, "wind":0.4, "surface_q":0.0, "stop_density":4.2,
        "car_stress":22.0, "accident":0.0, "bicycle_infra_quality":0.0 }
      /* ↑ 改善計画T402。segments[]のaxis_difficultiesを候補全区間に集約したルート単位版
         （overall_difficultyと対）。BottomSheet「ルート全体プロファイル」（横棒グラフ一覧）が消費する */
    },
    ...（overall_difficultyが小さい順[改善計画T548]、最大8件）
  ],
  "engine": "road_graph",
  "conditions": {   /* この生成に実際に適用された条件のエコー（実験の記録・再現用。研究IF改善 §10-6）。
                       重みは上書き値またはAXIS_DEFINITIONS由来の既定値のうち実際に使われた方。route_preference・
                       hard_filtersとも常にこの形で全フィールドが埋まって返る
                       （GenerationConditions、上のRequest部分指定不可の説明と対応。改善計画T292で
                       専用Pythonレシピ3つは廃止済み） */
    "latitude":35.7597, "longitude":139.7387, "distance_km":30, "distance_tolerance_km":5,
    "route_preference": { "gradient":0.15, "surface_q":0.19, "wind":0.26, "stop_density":0.20,
      "car_stress":0.20, "accident":0.08, "night":0.0 },
    "penalty_strength": 1.0, "max_average_grade_percent": null,
    "hard_filters": { "no_bicycle":true, "motorway":true, "trunk":true },
    "generated_at": "2026-08-15T14:30:00+09:00"
  }
  }
}
Response 200（status="failed"、ジョブ内部で例外が発生した場合。バックグラウンドタスクの
             例外はHTTPレスポンスへ伝播できないため、ここへ記録して初めてクライアントが知る）:
{ "status": "failed", "result": null, "error": "..." }
Response 404（job_idが未知、または完了から10分経過して破棄された場合。
             infrastructure/job_registry.py: _JOB_TTL_SECONDS参照）:
{ "detail": "ジョブが見つかりません（完了から時間が経過して破棄された可能性があります）" }

（POST /api/routes/generate側のRate limit）
Response 429（per-IPで1分あたりGENERATE_RATE_LIMIT_PER_MINUTE=10回を超過、またはプロセス全体の
             同時実行数GENERATE_MAX_CONCURRENT=2に到達している場合。最も高コストなエンドポイントのため、
             PostGIS・外部サービス（GSI等）への負荷の積み上げを防ぐ。設計レビュー対応で追加）:
{ "detail": "リクエストが多すぎます。しばらく待ってから再試行してください。" }
```

### 汎用ジョブレジストリ

`infrastructure/job_registry.py`は、`POST /api/routes/generate`の冷パス（上記参照）を
バックグラウンド化するために新設した、プロセス内メモリのみの汎用非同期ジョブ管理
（`create_job`/`get_job`/`set_running`/`set_done`/`set_failed`、完了から10分経過した
ジョブはTTLベースで自動パージ）。単一プロセスデプロイ前提（`axis_registry_service.py`の
push型更新と同じ前提）で、ルート生成の型（`RouteGenerateResponse`等）を一切知らない
汎用モジュールにしてある（`result`は`Any`型、`api/routers/routes.py`との循環importを
避けるため）。将来他の重い処理（例: 大規模バッチのオンデマンド実行）にも転用できる。

実行には`asyncio.create_task`を使う（FastAPIの`BackgroundTasks`ではない）——
`BackgroundTasks`はレスポンス送出が**完了してから**実行されるため、送出中の失敗
（クライアント切断・ミドルウェアの例外）でジョブが一度も起動せず、投稿時点で取得済みの
`_generate_semaphore`を解放するfinallyへ到達しない。`generate_max_concurrent`回これが
起きるとルート生成がプロセス再起動まで全断する。生成したタスクは
`_running_generate_tasks`（`api/routers/routes.py`）が参照を保持する——イベントループは
タスクへの強参照を持たないため、保持しないとGCが実行中のジョブごと回収しうる。テストから
ジョブの完了を待つ必要がある場合はこの集合をawaitする。

バックグラウンドタスクはFastAPIのリクエストスコープ外で実行されるため、
リクエストスコープのDBセッション（`Depends`経由）をそのまま使えない
（`graph_service.py: _warm_tile_cache_background`と同じ制約）。`api/dependencies.py:
open_route_generation_setup`（`@asynccontextmanager`）が、既存のDI用ジェネレータ関数を
`asynccontextmanager()`でラップして独立したセッションを開く（セッション開閉ロジックの
複製はしない）。「どのサービスをどのエンジンへどう組み立てるか」自体は
`_assemble_route_generation_setup`（純粋関数）へ一本化し、DIベースの旧経路・
バックグラウンドジョブの両方から呼ばれる。

```
GET /api/weather?latitude=35.7597&longitude=139.7387   # Step6: 現在地の天候
Response 200:
{ "temperature_c":24.6, "apparent_temperature_c":27.1, "wind_speed_ms":1.93, "wind_direction_deg":69.0, "wind_direction_label":"東", "wind_gusts_ms":4.8, "precipitation_probability_percent":100.0, "precipitation_mm":0.2, "uv_index":6.2, "observed_at":"2026-08-13T21:15", "weather_code":3, "is_day":1, "sunrise":"2026-08-13T05:12", "sunset":"2026-08-13T18:41", "precipitation_probability_max_percent":80.0, "wind_speed_max_ms":5.5, "temperature_max_c":29.0, "temperature_min_c":23.0, "uv_index_max":8.5, "today_periods":[{"period":"20:00","weather_code":3,"temperature_c":25.0,"precipitation_probability_percent":50.0}, "... 観測時刻を含む2時間区間から2時間おき8コマ（日をまたぎうる）"] }
# weather_code/is_dayは改善計画T385（天気アイコン化、UV指数の夜間常時0.0問題への対応）、
# sunset・sunrise〜uv_index_maxは同T385「今日の見通し」パネル用（daily、forecast_days=2の
# index0=今日）。sunrise（T385フォローアップ2）は「夜明け前ならsunrise、それ以外は
# sunsetを表示」というfrontend側の切り替え判定用。today_periods（T385フォローアップ、
# WeatherPeriodOutlook配列）はhourlyから観測時刻（observed_at）を含む2時間区間を起点に
# 2時間おき8コマを抜き出した「今日の天気の流れ」（T385フォローアップ2で固定6時始まりから
# 現在時刻基準へ変更、日をまたいでも継続する）。periodは"HH:MM"の代表時刻文字列そのもので、
# 「朝/午後/夜」等の意味づけラベルへの整形はbackendが持たずfrontend（TodayOutlook.tsx）が担う。
# 判定ロジックはfrontend/weatherCode.tsに集約し、backendは生のweather_code/is_dayを
# 素通しするだけ。
Response 502（MSMを読めない場合。同期未完了・予報終端が現在時刻へ追いついた等）:
{ "detail": "天候情報の取得に失敗しました" }
Response 429（同一クライアントIPから1分あたり60リクエスト（`WEATHER_RATE_LIMIT_PER_MINUTE`）を超えた場合）:
{ "detail": "リクエストが多すぎます。しばらく待ってから再試行してください。" }
# このエンドポイントは常に予報（気象庁MSM）の値を返す（今日の見通しTodayOutlook専用）。
# 実測値はマージしない——常設ヘッダー（WeatherPanel）がGET /api/weather/amedasを直接呼ぶ。

GET /api/weather/amedas?latitude=...&longitude=...   # 最寄りアメダス観測所の直近観測値（改善計画T387、常設ヘッダー用）
Response 200:
{ "station_id":"44132", "station_name":"東京", "latitude":35.69, "longitude":139.76,
  "observed_at":"2026-08-29T12:00:00+09:00", "temperature_c":26.5, "apparent_temperature_c":27.8,
  "sunshine_10min_minutes":5.0, "sunrise":"2026-08-29T05:12:00+09:00", "sunset":"2026-08-29T18:41:00+09:00",
  "wind_speed_ms":3.5, "wind_direction_deg":180.0, "wind_direction_label":"南", "precipitation_10min_mm":0.0 }
Response 502（Redis未温間・最寄り観測所がセンサー未搭載等）:
{ "detail": "アメダス観測値の取得に失敗しました" }
Response 429（同一クライアントIPから1分あたり30リクエスト（`WEATHER_AMEDAS_RATE_LIMIT_PER_MINUTE`）を超えた場合）:
{ "detail": "リクエストが多すぎます。しばらく待ってから再試行してください。" }

GET /api/weather/wind-grid   # 風・降水延長予報の格子点マップ（改善計画T178フォローアップ、T183で降水追加、T203で応答形をtimes1本化。1章「動的気象レイヤー」参照）
Response 200: `WindGridResponse`（関東本土全域の固定格子点、約624点、取得失敗地点は除外。`times`は全格子点で共通の時刻配列を1本だけ持つ）。
{ "times":["2026-08-22T00:00", ...],
  "points":[{ "latitude":35.68, "longitude":139.77,
    "wind_speed_ms":[1.2, ...], "wind_direction_deg":[80.0, ...], "precipitation_mm":[0.0, ...] }] }
Response 429（`WIND_GRID_RATE_LIMIT_PER_MINUTE`超過）。

GET /api/weather/wind-grid-detail?min_lon=...&min_lat=...&max_lon=...&max_lat=...&spacing_deg=0.01   # 詳細格子（改善計画T180、ズームイン時の面表現用。T185でspacing_degをズーム依存に）
Response 200: `WindGridResponse`（表示範囲bboxに交差する密格子点）。
Request（`spacing_deg`省略時は`WIND_GRID_DETAIL_SPACING_DEG`=0.02。任意の連続値は許可せず`WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEG`の離散値のみ受け付ける、キャッシュ共有維持のため）。
Response 400（`spacing_deg`が許可値以外、または表示範囲が広すぎ`WIND_GRID_DETAIL_MAX_POINTS`=900を超える場合）:
{ "detail": "spacing_degの値が不正です。" } / { "detail": "表示範囲が広すぎます。ズームインしてください。" }
Response 429（`WIND_GRID_DETAIL_RATE_LIMIT_PER_MINUTE`超過）。

GET /api/weather/warnings?latitude=...&longitude=...   # JMA警報・注意報バッジ（改善計画T205）
Response 200: 出発地点近傍のサイクリング関連警報・注意報（大雨・洪水・暴風/強風・波浪・大雪・雷・土砂災害）。
{ "area_name":"東京地方", "report_datetime":"2026-08-22T18:09:00+09:00",
  "warnings":[{"code":"14","name":"雷注意報","level":"advisory","additions":["竜巻","ひょう"]}] }
警報が無い場合は`{"area_name":null,"report_datetime":null,"warnings":[]}`。地点→市区町村→JMA警報
エリアの解決（国土地理院逆ジオコーダ→JMA地域マスタarea.json→JMA警報API r8）のどこで失敗しても
例外にせず同じ空応答を返す（他の`/api/weather`系と異なりこのfail-openは意図的な仕様。安全側では
ないトレードオフをT174（WBGT警告）と共有する）。
Response 429（`WEATHER_WARNINGS_RATE_LIMIT_PER_MINUTE`超過）。

GET /api/weather/wbgt?latitude=...&longitude=...   # WBGT警告バッジ（改善計画T174）
Response 200: 出発地点近傍の暑さ指数（WBGT）警戒レベル（環境省「熱中症予防運動指針」の4段階＋非表示）。
{ "level":"advisory", "label":"注意", "value":24.0, "observed_at":"2026/08/22 21:00:00" }
提供期間外（11〜3月）・地点解決失敗・予測値取得失敗・「ほぼ安全」（暑さ指数21未満）のいずれも
`{"level":null,"label":null,"value":null,"observed_at":null}`（T205と共有するfail-open方針、502は
返さない）。地点解決は情報提供地点マスタ（アメダス観測所ベース、約840地点）への最近傍点探索
（JMA警報のような行政区画の親子関係が無いため）。
Response 429（`WEATHER_WBGT_RATE_LIMIT_PER_MINUTE`超過）。

GET /api/weather/flood-forecast?latitude=...&longitude=...   # 河川氾濫予報バッジ（改善計画T212、T176調査で発見）
Response 200: 出発地点近傍のJMA指定河川洪水予報（レベル2〜5、複数河川該当時は配列）。
{ "forecasts":[{"river_code":"830304004400","river_name":"神田川","level":4,
  "badge_level":"severe_warning","label":"神田川氾濫危険警報",
  "condition":"レベル４氾濫危険警報（発表）","report_datetime":"2026-08-22T17:50:00+09:00"}] }
対象河川が無い場合は`{"forecasts":[]}`。地点解決（T205のjma_area.py再利用）・洪水予報自体の
取得のどこで失敗しても例外にせず同じ空応答を返す（T205/T174と共有するfail-open方針）。
Response 429（`WEATHER_FLOOD_FORECAST_RATE_LIMIT_PER_MINUTE`超過）。

GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf   # 表示中ビューポート全体の路面データ（PostGIS/ST_AsMVTで生成したベクタタイル。取込範囲外は空タイル）
Response 200（Content-Type: application/vnd.mapbox-vector-tile）: バイナリのMVT。レイヤー名`road_surface`、各地物（LineString）は`surface_good`（true=舗装/false=未舗装/null=不明）に加え、
  highway/surface/smoothness/tunnel/bridge/`designation`/`oneway`/`osm_way_id`、車の圧迫感（car_stress、改善計画T292で内部軸5つ+公開軸1つの階層構造へ再実装）が
  参照する材料タグ`maxspeed_kmh`/`lanes_count`/`motor_vehicle_no`と、night軸が
  参照する`lit`（`shoulder`は実測0.0%の死に補正と分かり撤去済み）、
  km正規化密度`accident_per_km`/`intersection_per_km`と、停止要因POIの種別別密度
  `poi_*_per_km`（P0/P1/T51/T74/T90/T292/T145b/T655。7章参照）プロパティを持つ。
  車の圧迫感の最終値は（改善計画T292以降）タイルへ焼き込まず、フロントエンド
  （`axisLayers.ts`の汎用ramp機構、他の推定軸=停止密度・事故密度等と同じ経路。旧
  `carStressExpression.ts`は専用実装を廃止し統合済み）と
  ルート採点（`domain/axis_definitions.py: AXIS_DEFINITIONS['car_stress']`、内部軸5つの
  階層評価。旧`domain/traffic.py: car_stress_breakdown`は廃止）が
  それぞれ材料タグから計算する（7章参照）。`osm_way_id`は表示用ではなく、
  区間クリック時の全軸内訳取得（`POST /api/region/axis-inspector`）が
  クリックされたフィーチャーを曖昧さ無く引き直すための識別子（T90・T146）
Response 400（zがROAD_TILE_MIN_ZOOM=12未満、またはROAD_TILE_MAX_ZOOM=15を超える場合）:
{ "detail": "対応していないズームレベルです。" }
Response 400（x/yがそのズームレベルで存在しうる範囲 `0 <= x,y < 2**z` を外れる場合。直接APIを叩かれた場合の安全弁で、通常はMapLibreが範囲外のタイルを要求しないため到達しない）:
{ "detail": "タイル座標が範囲外です。" }
Response 429（同一クライアントIPから1分あたり120リクエスト（`ROAD_TILE_RATE_LIMIT_PER_MINUTE`）を超えた場合。`infrastructure/rate_limiter.py`によるプロセス内メモリのみの固定窓レート制限）:
{ "detail": "リクエストが多すぎます。しばらく待ってから再試行してください。" }

GET /api/region/poi-tiles/{z}/{x}/{y}.pbf   # 停止要因POI・交差点密度の点データ（T54、7章参照）。road-surface-tilesと同じズーム範囲・同じPostGIS第一系統
Response 200（Content-Type: application/vnd.mapbox-vector-tile）: レイヤー名`poi`。各地物（Point）は`kind`（停止要因の種別。正準集合は`domain/traffic.py: StopPoiKind`で、生成物`poi-kinds.json`経由でフロントへ渡す）または`degree`（接続路数、交差点密度）を持つ
Response 400/429: road-surface-tilesと同じ規約

GET /api/region/accident-tiles/{z}/{x}/{y}.pbf   # 警察庁交通事故統計オープンデータの発生地点（T50、7章参照）。`AccidentService`が担当し road-surface-tiles/poi-tiles とは別系統
Response 200（Content-Type: application/vnd.mapbox-vector-tile）: レイヤー名`accidents`。各地物（Point）は`involves_bicycle`（自転車関連か）・`fatal`（死亡事故か）プロパティを持つ
Response 400/429: road-surface-tilesと同じ規約（同時実行数上限は`accident_tile_max_concurrent`で別枠）

POST /api/region/axis-inspector   # 区間インスペクタ（T146）。クリックされた道路（osm_way_id）について、一次属性→取得可能な二次軸スコアの内訳→参考合成コストを返す
Request: `{ "osm_way_id": number }`に加え、地図が知っている指定を任意で送れる。GETでなく
  POST+JSONボディなのは、`/api/routes/generate`と同じ形に統一しているため。
  `feature_key`（路面タイルが焼いた鍵）を送ると、地図が区間単位で塗っているズームでは内訳も
  区間単位で読む——送らないと同じ場所で色と数字が食い違う。
  進行方向に依存する軸（勾配・風）は、**1本の道が往復2方向で違う値を持つ**ため走行方位が
  決まらないと算出できない。`z`/`x`/`y`・`bearing_deg`・`at`・`speed_kmh`（地図のレンズが
  `/api/region/dynamic-way-values/...`へ送っているものと同じ値）を一緒に送ると、
  同じ経路・同じキャッシュから引いた値で算出する。送らなければその軸はavailable=false。
Response 200: `AxisInspectorResult`（`highway`/`tags`/`landcover`/`axes: AxisInspectorAxis[]`（axis_id・difficulty・weight・available・contribution）/`composite_difficulty`/`covered_weight_fraction`）。
  取得できなかった軸は合成から除外し残りの重みで再正規化、`covered_weight_fraction`はその再正規化の対象になった重み割合（0-1）。該当wayが存在しない場合はnull。
  `axes`は公開軸（is_published=True）のみを返す（他の軸から参照される内部軸は、参照側の
  difficulty値へ既に合成済みで個別には現れない）
Response 422（osm_way_idが整数でない場合）
Response 429: タイル系とは別枠のレート制限（`AXIS_INSPECTOR_RATE_LIMIT_PER_MINUTE`）。
  地図を眺めてタイルを引いただけでクリックの内訳が引けなくなるのを避けるため、
  road-surface-tilesの枠とは結合しない

GET /api/basemap/{path}   # Step10: OpenFreeMapの地図タイル/スタイルJSON/スプライト/グリフのプロキシ＋キャッシュ
Response 200: 上流（OpenFreeMap）のContent-Typeをそのまま転送
Response 502（上流取得失敗時）:
{ "detail": "地図タイルの取得に失敗しました" }
Response 429（同一クライアントIPから1分あたり300リクエスト（`BASEMAP_RATE_LIMIT_PER_MINUTE`）を超えた場合。road-surface-tilesと同じ`rate_limiter.py`を使うが上限値は別）:
{ "detail": "リクエストが多すぎます。しばらく待ってから再試行してください。" }

POST /api/admin/basemap/refresh   # 地図タイルキャッシュを全消去（HTTP Basic認可要、管理画面/adminの「データ保守」タブ）
Response 200:
{ "status": "ok" }
Response 401（認証情報が無い・誤っている場合）:
{ "detail": "Not authenticated" }

GET /api/admin/tuning   # 較正値（走ってみて決める値）の一覧（HTTP Basic認可要、管理画面/adminの「較正値」タブ）
Response 200: 宣言（domain/tuning.py）の項目ごとに、id・ラベル・単位・既定値・範囲・
# 説明・いま効いている値・既定から動かしてあるか・変えたとき効くまでに何が要るか（effect）。
# **並べる項目は宣言から導く**ため、画面もこのAPIも項目の一覧を持たない。

PUT /api/admin/tuning/{param_id}   # 1件を上書きする（既定と同じ値を送ると上書きを消す）
Response 200: 更新後の同じ形
Response 404（宣言に無いid）／422（宣言の範囲の外）
```

標高の地域オーバーレイ（Step10）は`GET /api/gsi-relief-tile/{path:path}`（改善計画T572）を
経由する。JSON応答を持つAPIではなく、`BasemapClient`と同じ「pathを丸ごとプロキシ」方式の
ラスタタイル配信のため、上記のようなJSONレスポンス例は無い（詳細は「標高オーバーレイ
（国土地理院 色別標高図、ラスタタイル）」を参照）。起伏（陰影）は
`GET /api/gsi-terrain-tile/{z}/{x}/{y}.png`で、地理院の標高タイルをTerrain-RGBへ移して
返す（同じく丸ごとプロキシではなく**変換して**返すため、上流のpathをそのまま受けない。
詳細は1章「起伏（陰影）は別レイヤー」を参照）。

これで仕様書18章に記載の最終形のレスポンス項目（距離・標高・風・道路特性・総合スコア）に加え、区間ごとの詳細（`segments`）、候補ルートに紐づかない地域全体の標高・路面レイヤー（Step10）も出揃った。

## 5. ルート生成アルゴリズム（仕様書7-11章より）

### 現状

周回・経由地・目的地の各生成戦略と、road_graphエンジン（自前Road Graph、状態＝有向区間の
探索［一対全木・2点間探索ともnumbaのDijkstra/A*］、タイル単位のスコア行列とレグ別コスト配列）の実装は
[docs/modules/backend/routing-engine.md](modules/backend/routing-engine.md)が正本。

8方位ぶんの経由地点を球面三角法で作りopenrouteserviceへ問い合わせていた候補生成、および
候補集合内でmin-max正規化して合成していた`wind_score`・`road_score`・`total_score`はいずれも撤去済み
（改善計画T462でroad_graphエンジンへ一本化、重みを持っていた`scoring.yaml`はT548で撤去済み）。
当時の各Stepが何を実装したかは[decisions/step-log.md](records/decisions/step-log.md)が記録している。

### 評価重みのリクエスト上書きと評価モデル研究時の構成（研究インターフェース改善 Phase 1）

評価モデルの探索・研究（[research-interface-review-2026-08-15.md](research-interface-review-2026-08-15.md)）のため、
`RoutePreference`（Edge評価・区間難易度・絶対、既定値は`domain/axis_definitions.py:
AXIS_DEFINITIONS`のdefault_weight、改善計画T316）の重みは`/api/routes/generate`のリクエスト
ボディでリクエスト単位に上書きできる（§10-1）。実際に適用された値はレスポンスの`conditions`に
エコーされ（§10-6）、レスポンスJSONを保存すればそのまま再現条件になる。

- 配線: `dependencies.py: open_route_generation_setup`（`@asynccontextmanager`）が
  検証済みの上書き値（無ければNone→既定値）を受け取り、独立したDBセッションの上で
  `RouteGenerationSetup`を組み立てる（組み立て自体は純粋関数`_assemble_route_generation_setup`
  へ一本化）。リクエストスコープ外で走るバックグラウンドジョブから呼ぶための形。
  `route_preference`側の既定値は軸スタジオでの公開軸・default_weight編集がサーバー再起動なしで
  即座に反映される（`AxisRegistryAdminService`の書き込み直後リフレッシュ、改善計画T221 Stage D）
- 上書きは全フィールド必須・非負（部分指定でクラス既定値が黙って入る事故を防ぐ）
- **研究時の重みの効き方**: road_graphエンジン（改善計画T462で唯一のエンジンに一本化）では
  `route_preference`がEdge Cost→Dijkstra探索に直接効くため、重みの変更はルート形状そのものに
  反映される（ただし勾配は探索コストに含まれない既知の制約がある。road_graph_engine.pyの
  docstring参照）

---

## 6. データモデル

### 実装済み（`frontend/src/types/route.ts`, `backend/app/domain/route.py`）

```ts
interface Coordinates {
  latitude: number;
  longitude: number;
}

interface RouteSegment {
  distance_km: number;
  duration_minutes: number;
  geometry: GeoJSON.LineString;
  surface_summary: object[] | null;
  surface_values: unknown[][] | null;
}

interface RouteSegmentDetail {
  geometry: GeoJSON.LineString | null;  // 区間の道なり形状（ルートgeometryの部分列。null時は始点・終点の直線で代替描画）
  start_latitude: number;
  start_longitude: number;
  end_latitude: number;
  end_longitude: number;
  cumulative_distance_km: number;
  distance_km: number;
  estimated_arrival_time: string | null;
  car_stress: number | null;          // 0-4、P1残り（生値。自転車インフラの寄与は
                                       // bicycle_infra_quality側が持つ）
  axis_difficulties: { [axisId: string]: number };  // axis_id→difficulty(0-100)。軸ごとの
    // 固定フィールドは持たない。評価できなかった軸・
    // 非公開の軸はキー自体を持たない（評価経路と同じ規約）。軸スタジオでの
    // 公開軸の増減にそのまま追従する
  axis_contributions: { [axisId: string]: number };  // axis_id→重み付き寄与度（改善計画T550）
  material_values: { [materialId: string]: number };  // 材料id→値（改善計画T592で
    // gradient_percent/wind_drag_ratio等の固定フィールドから汎用dictへ置換。重み>0の公開軸が
    // 参照する材料、または地図のレンズが指す符号付き材料の軸の材料のみキーを持つ）
  difficulty: number | null;              // 公開軸の合成値（絶対基準0-100）
}

interface RouteCandidate {
  id: string;
  direction_label: string;
  distance_km: number;
  geometry: GeoJSON.LineString;
  elevation_gain_m: number | null;
  min_elevation_m: number | null;
  max_elevation_m: number | null;
  segments: RouteSegmentDetail[] | null;
  overall_difficulty: number | null;  // segments.difficultyの距離加重平均（絶対基準）。改善計画T548で
    // 候補タブの並び順の基準にもなった（昇順、算出不能なnullは末尾）。旧`total_score`・
    // 旧`score_breakdown`（研究IF改善§10-2の候補集合内相対スコア、RouteScoreComponent[]）は
    // 改善計画T548（2026-09-03）で撤去済み
  axis_difficulties: { [axisId: string]: number };  // axis_id→difficulty(0-100)。改善計画T402で新設。
    // RouteSegmentDetail.axis_difficultiesと同じ汎用dictを候補の全区間へ集約したもの
    // （merge_axis_difficultiesをビン単位ではなく候補全体に1回適用するだけ）。軸スタジオの
    // 軸増減に自動追従する。フロントのBottomSheet「ルート全体プロファイル」（横棒グラフ一覧）が
    // 消費する。旧来の軸1対1固定設計の名残だった個別フィールド群（stop_density・
    // car_stress_score・bicycle_infra_score・intersection_density・accident_density）は
    // 改善計画T431でフロントエンドの末端消費者ゼロを確認した上で撤去済み
  axis_contributions: { [axisId: string]: number };  // RouteSegmentDetail.axis_contributionsと
    // 同じ集約方法（merge_axis_contributions）で候補全体へ1回適用したもの（改善計画T550）
  material_values: { [materialId: string]: number };  // RouteSegmentDetail.material_valuesと
    // 同じ集約方法（merge_material_values）で候補全体へ1回適用したもの。改善計画T592で
    // wind_score/road_score/max_gradient_percentから置換
}

interface RouteGenerateRequest {
  latitude: number;
  longitude: number;
  distance_km: number;
  distance_tolerance_km: number;
  route_type: "loop";
  route_preference?: RoutePreferenceWeights; // 評価重みの上書き（研究用・省略可、§10-1。Edge評価・
    // 区間難易度の重み、axis_idキーの辞書。
    // 改善計画T292でcar_stress_recipe等の専用Pythonレシピ上書きは廃止し、公開軸の重みのみで表現する）
  penalty_strength?: number | null;  // コスト式の割増率の強さ（改善計画T218・T12 ADR原則1、
    // 省略時はリクエスト処理時に較正値から読む（`domain/evaluation.py:
    // resolve_penalty_strength`）。スキーマ側に既定値を置かないのは、import時に束ねると
    // 管理画面から変えた値が効かなくなるため。ここへ数値を書き写さない）
  max_average_grade_percent?: number | null; // 0次ハードフィルタの勾配しきい値（改善計画T218a・T12 ADR原則5、省略時は除外なし）
  hard_filters?: HardFilterOverride; // 0次ハードフィルタの個別ON/OFF（改善計画T266）。
    // 一般向けルート設定画面（frontend/src/components/RouteSettingsPanel、改善計画T267）が
    // 常時操作する（省略時と同じ既定値を常に明示送信するため実質的に常に指定される）
}

interface WeatherConditions {
  temperature_c: number;
  wind_speed_ms: number;
  wind_direction_deg: number;
  wind_direction_label: string;
  precipitation_probability_percent: number | null;
  observed_at: string;
}

```

バックエンド側は `domain/route.py`, `domain/weather.py` に同等のPydanticモデルを実装済み。フィールド名はキャメルケースではなくAPIレスポンスに合わせたスネークケースにしている（フロント⇔バックエンドで変換不要にするため）。標高系・`overall_difficulty`・`segments`内の各フィールドは取得失敗時に`null`になりうるため、フロント側も`null`許容で扱う。

候補ルートに紐づかない地域全体の標高・路面レイヤー（Step10）は、いずれもタイル形式（標高はGSIのラスタタイル、路面はPostGIS/ST_AsMVTで生成したMVT）で配信するため、Step5-9のようなJSONのレスポンスモデルを持たない。バックエンド側の`domain/region.py`にはタイル範囲計算に使う`BoundingBox`（Pydanticモデル）が残っているが、これはPostGISクエリ・（DBなし構成での）Overpass問い合わせに使う内部的な値であり、フロントエンドとの間でJSONとしてやり取りするものではない（フロント側に対応する型定義は無い）。

これで仕様書18章記載の`RouteCandidate`の項目、地図可視化用の`segments`（Step9）、および候補ルートに紐づかない地域全体の標高・路面レイヤー（Step10）が出揃った。

---

## 7. 静的道路属性と評価軸モデル（P0/P1、外部静的データソースT50/T51）

Step8時点の評価（距離・標高・風・路面の4指標）に加え、OSMタグ・警察庁事故統計・国土数値情報
（KSJ）を材料とした指標を追加し、区間難易度（`RoutePreference`）・地図の静的レイヤーの
両方に反映した（`static-road-attributes-plan.md` P0/P1、
[external-data-sources-review-2026-08-16.md](external-data-sources-review-2026-08-16.md)）。
旧scoring.yaml（total_score、改善計画T548で撤去済み）には含めない（stop_weightと同じ
スコープ判断、後述）。

**自転車インフラは独立した公開軸を持たず、車ストレス側へ統合している**（8軸）。車ストレスの
cycleway補正（内部軸`car_stress_bicycle_infra_adjustment`）が既に自転車インフラの情報を
反映しており、独立軸にすると同じ情報を二重に数えることになるため。
ルート集約統計`bicycle_infra_score`・区間ごとの生値`RouteSegmentDetail.bicycle_infra`はいずれも撤去済みで、
`axis_difficulties["bicycle_infra_quality"]`が正（下記「自転車インフラの独立公開軸化」節参照）。

**安全度も独立した軸を持たない。** highway・cycleway・maxspeed・lanes・指定路線由来の部分は
車ストレスが持ち、街灯・トンネル由来の部分は`domain/night.py: night_difficulty`が持つ
（night軸の既定重みは0.0。街灯・トンネルを気にするユーザーが研究モードで個別に重みを上げる
想定）。事故実績は元から独立軸（`accident`）。
`domain/safety.py`・`safety_recipe.yaml`・`POST /api/region/safety-breakdown`・地図の安全度レイヤーは撤去済み
（跡地の`lit`タイルプロパティは車ストレス・night軸へ転用済みのため残る）。

続く改善計画T149（設計プロンプト改訂2026-08-18「現行9軸からの帰属先」）で、交差点密度
（旧`intersection_weight`）の独立軸を廃止し停止密度側へ統合した。`domain/difficulty.py:
stop_difficulty`が、停止要因POI（信号・横断歩道・一時停止・踏切・車止め・減速構造）の
密度に加え、次数3以上のタグなし交差点の密度を低い重み（0.3、signal等を1.0とした相対値）で
加算する（8軸→7軸）。
ルート単位の交差点密度（`RouteCandidate.intersection_density`）は改善計画T431でフロント
エンド末端消費者ゼロを確認した上で削除済み。

続く改善計画T347で、自転車インフラをT138とは逆方向に「独立公開軸」として復活させた
（7軸→8軸）。T138時点は自転車インフラの寄与を車ストレス側へ統合する（重みを分離しない）
判断だったが、専用の自転車インフラを重視したいユーザーが車ストレス全体の重みとは別に
自転車インフラだけを調整したいという需要が明らかになったため、新設の公開軸
`bicycle_infra_quality`（`domain/axis_definitions.py`、既定重み0.15、`show_map_icon=false`
のため専用の地図レイヤーは持たない）として切り出した。当初（T347時点）は材料として車ストレス側の
内部軸`car_stress_bicycle_infra_adjustment`（cycleway補正、4フラグ材料から算出）を1つの材料として
参照する階層構成（改善計画T292の内部軸参照パターンを踏襲）にし、生の材料を二重に持たなかった。
これは`domain/axis_definitions.py: check_material_exclusivity`（各公開軸が同じ生材料を直接参照
することを禁じるガード）を、自転車インフラだけの専用属性を新設する対症療法ではなく既存の
階層合成パターンで自然に満たすためだった。その後**改善計画T353**でこの1材料1軸原則
（`check_material_exclusivity`）自体の優先順位が見直され、`car_stress_bicycle_infra_adjustment`
は廃止（車ストレスから自転車インフラ由来の調整を完全排除）、`bicycle_infra_quality`が
4フラグ材料（`highway_is_cycleway`/`cycleway_has_track`/`cycleway_has_lane`/
`cycleway_has_shared`）を直接参照する現在の構成へ再設計された（詳細は
「停止密度・車ストレス・自転車インフラ・交差点密度」節・
[material-normalization-for-axis-composition.md](records/decisions/material-normalization-for-axis-composition.md)参照）。
この再設計に伴い、
`RouteSegmentDetail.bicycle_infra`（7値分類の生値）・`classify_bicycle_infrastructure`
（分類関数）・MVTタイルの`bicycle_infra`プロパティ・専用地図レイヤー（旧`bicycleInfra`）は
いずれも削除した。`RouteCandidate.bicycle_infra_score`（ルート集約統計）も改善計画T431で
`ComparisonPanel`が`axis_difficulties`駆動へ移行したことで末端消費者ゼロになり削除済み。

## 9. Road Graph移行

経緯・フェーズ別の詳細は [decisions/road-graph-migration.md](records/decisions/road-graph-migration.md) へ移動した。
現状の要点:

- `/api/routes/generate`はRoad Graph＋numbaでJITしたDijkstra/A*の単一構成（改善計画T247で既定化、改善計画T462でopenrouteservice委譲・切替設定自体を完全撤去、1章「ルーティングエンジンの切り替え対応」参照）
- OSMデータはPBF取込バッチ（`app/batch/import_pbf.py`）でPostGISへ事前取込済みの範囲を第一系統とし、Overpassフォールバックは改善計画T22で撤去済み（取込範囲外は空タイル/データ未整備扱い。docs/osm-pbf-import.md、[decisions/pre-static-attributes-gate.md](records/decisions/pre-static-attributes-gate.md)参照）
- 永続化層の構造（生OSM層／派生グラフ／属性／表示用MVTの4リポジトリ＋ファサード、トランザクション境界の規約）は`infrastructure/road_graph_repository.py`のdocstring参照
