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

### Road Graphエンジンの探索性能

リクエストごとの重い処理を持たない構造にしてある。**どれか1つでも崩すと、探索の前に
数秒かかる状態へ戻る**（段階ごとの実測は[decisions/road-graph-migration.md](records/decisions/road-graph-migration.md)）。

- **探索フェーズはEdgeのgeometry（形状点列）を読まない**。トポロジだけを引く経路を持ち、
  `geom`列をSELECTしない。
- **標高は事前計算済みの`elevation_attributes`をキー参照する**（`app/batch/
  precompute_elevation_attributes.py`が全道路網ぶんを埋める）。探索中にGSIへ問い合わせない。
- **材料は1クエリへ統合して取得する**（`GraphService.get_search_materials_for_bbox`）。
  ボトルネックはラウンドトリップ回数ではなく、同じEdge集合に対してORMの行構築を何度も
  繰り返すことにある。
- **軸の評価はnumpyでベクトル化してある**（軸をテンプレートへ揃えたうえでの一括計算）。

**返す区間の粒度**: エンジンの`segments`はEdge単位（交差点間）で、30km級では1候補あたり
数百件になる。そのままではAPIのペイロードとフロントの描画コストが嵩むため、
`domain/route.py: aggregate_segments_into_bins`が約500m単位（`SEGMENT_BIN_DISTANCE_KM`）へ
集約してから返す。数値は距離加重平均、カテゴリ値は距離加重多数決で代表値にする
（`RouteSegmentDetail`型そのものは変えない）。

**周回の逆回り候補**: `evaluate_loops`は各方位について、確定した順方向の経路に加え、同じ
物理形状を逆順に辿る候補も合成できる場合は合成し、距離加重difficultyが低い方だけを残す
（両方向を別候補にはしない）。逆回りは**追加のDB問い合わせ・標高APIの再呼び出しを伴わない**
——Edge列は1リクエストにつき1回だけ作る`(from_node_id, to_node_id) → Edge`の逆引き表から引き、
標高は取得済みの順方向の値を代数的に変換する（獲得↔喪失の入替・勾配の符号反転）。経路に
一方通行区間が1つでもあれば逆回りは成立しないため、その方位は順方向のみを候補とする。


### 風・降水予報のローカル同期（`msm_client.py`）
`msm_client.py`（[backend/app/infrastructure/msm_client.py](../backend/app/infrastructure/msm_client.py)）は、気象庁MSM（メソ数値予報モデル）の前処理済みデータ（Open-MeteoがAWS Open Dataで公開する`.om`形式、CC-BY-4.0）をローカルへ同期し、風の格子点マップ・ルート評価の風をそのファイルから直接読む。REST APIを叩かないためレート制限・クォータの制約を受けない。同期は`main.py`のAPScheduler（既定30分間隔）が担い、ETagの条件付きGETで内容が変わったチャンクだけを取得する（3変数・日本全域・約114時間ぶんで34MB程度）。格子の原点・間隔・チャンク長・予報終端は配信元の`static/meta.json`と実データの形状から導出し、定数として持たない。詳細は[docs/modules/backend/weather-dynamic-layers.md](modules/backend/weather-dynamic-layers.md)参照。

### 天候取得の設計と「地点＋時刻」対応（Step6）
`WeatherService.get_conditions`（[backend/app/services/weather_service.py](../backend/app/services/weather_service.py)）は、MSMの時系列（1地点ぶん）の先頭を現在値として扱い、「今日の見通し」パネル用の値を組み立てる。天気コード（WMO相当）は`domain/weather.py: derive_weather_code`が降水量・雲量・気温から導き、日の出/日没は`domain/twilight.py`が天文計算で求める（いずれも外部への問い合わせを伴わない）。日次の集計（最高/最低気温・最大風速・最大降水量）は同じJST暦日の残り時間ぶんを対象にするため、朝に見た値と夕方に見た値は一致しない（これから走る人向けの見通しとして扱う）。時間帯別の流れ（today_periods）は現在時刻の正時から2時間おきに最大8コマで、予報の終端に達したらそこで打ち切る。

`WeatherService.get_conditions(point, at: datetime | None = None)`（[backend/app/services/weather_service.py](../backend/app/services/weather_service.py)）は、`at=None`なら`current`ブロックを返し、未来時刻を渡すと`hourly`配列から最も近い時刻のデータを検索して返す。**Step6のUIでは`at`を渡さず現在地の現在の天候のみ表示するが**、この時刻指定インターフェースにより、将来「ルート上の各サンプル点＋推定通過時刻（`RouteCandidate`の距離・所要時間から按分計算できる）」を渡して「2時間後にその地点は雨か」を判定する拡張が、サービス層の設計変更なしで追加できる（ユーザー要望への対応）。既知の制約: `at`が取得済みhourly範囲（当日+翌日）を超える場合、現状は最も近い時刻を返してしまう（範囲外チェック未実装）ため、`at`を実際に使う機能を追加する際にガードを入れる必要がある。

### UI再構成（第2段）: 地図上はON/OFF＋条件サマリ、細かな設定はサイドバーへ集約

「細かな設定はサイドバーで実施し、地図画面ではON/OFFと適用中の条件が簡潔に分かる程度にしたい」「今後の静的レイヤー追加（交通ストレス等、[static-road-attributes-plan.md](static-road-attributes-plan.md)）や動的レイヤー追加（天候等）を汎用的にやりやすくしたい」という要望を受け、レイヤー操作UIを再構成した（2026-08-15）。

- **レイヤーカタログ**（[frontend/src/components/Map/mapLayers.ts](../frontend/src/components/Map/mapLayers.ts)、新規）: 各レイヤーの`id`/`label`/`kind`（static=地域固定・時間で不変 / dynamic=ルート・時間で変わる）/`description`を宣言する単一ソース。地図上のチップ行とサイドバーのセクション枠はこの配列の列挙で描画されるため、レイヤー追加は「カタログに1エントリ＋`page.tsx`に初期値とサマリ対応＋サイドバーにセクション中身」で済む（この手順は本節が書かれた時点のもの。当時のサイドバー`MapLayersPanel`は撤去済みで、現在の分担は後述の節を参照）。
- **地図上**（[frontend/src/components/MapOverlayControls/MapOverlayControls.tsx](../frontend/src/components/MapOverlayControls/MapOverlayControls.tsx)）: ON/OFFチップ行と、ONのレイヤーに効いている条件の1行サマリ（例:「路面: アスファルトのみ／幹線道路以外」「ルート: 色分け: 風の影響」。路面はズーム不足の案内を優先）だけを置く。サマリのタップでサイドバーが開き、該当レイヤーの設定セクションへスクロール・フォーカスする。コンポーネント自体はレイヤー固有の知識を持たない汎用描画係になった（レイヤー追加時に変更不要）。**この1行サマリは現在は無い**——凡例を持つレイヤーは▶の中身が必ず凡例になり、サマリが画面へ出る経路が残っていなかったため撤去した（[T945](records/tasks/T945.md)）。いま▶の中身に出る文言は「ONにしても何も出ない」ときの案内だけで、レイヤーカタログが宣言する。

- **状態管理**（`page.tsx`）: レイヤーON/OFFは`layerVisibility: Record<MapLayerId, boolean>`でまとめて持つ（レイヤーごとに個別のstateを作らない）。


### 地域レイヤー（標高・路面の常時オーバーレイ）と地図タイルキャッシュの設計（Step10）
Step5-9で実装した標高・風・路面はいずれも「生成済みの候補ルート沿い」に限定した評価だった。ユーザーから「候補を出す前に、そもそもどのあたりが走りやすい地形・路面なのか地図で見たい」という要望を受け、候補ルートの有無に関わらず**表示中の地図の範囲全体（ビューポート）**に標高・路面を重ね描きする機能を追加した。

#### 標高オーバーレイ（国土地理院 色別標高図、ラスタタイル）
国土地理院が公開する**色別標高図**（ラスタタイル、APIキー不要、zoom 5-15）をMapLibreの`raster`ソースとして`MapView.tsx`が重ね描きする。**点の集合ではなく面で塗る**——疎らな点では地形の起伏が直感的に読めない。

- **バックエンド経由プロキシ＋キャッシュ**（改善計画T572）: `GsiTileClient`
  （[backend/app/infrastructure/gsi_tile_client.py](../backend/app/infrastructure/gsi_tile_client.py)）が`BasemapClient`と同じ「pathを丸ごとプロキシ＋`tile_cache.py`の永続ファイルキャッシュ」方式で国土地理院（`cyberjapandata.gsi.go.jp`）のタイルを中継する（`GET /api/gsi-relief-tile/{path:path}`、`next.config.ts`の`/api/gsi-relief-tile/*`rewritesで同一オリジン化）。地理院タイルは`basetime`/`validtime`のような時刻依存パラメータを持たない静的データのため、JMAタイル系のようなTTL付きキャッシュの分岐は不要。
- **レイヤー順序**: `ensureGsiReliefLayer`（`MapView.tsx`）は地図初期化直後に一度だけソース/レイヤーを追加し、以降はvisibilityの切替のみで表示・非表示を行う。面で塗るレイヤーは基礎地図の道路網の直前へ差し込まれる（`mapStyleOps.ts: areaLayerAnchor`）ため、基礎地図の道路線・ラベルも、後から追加される路面・ルート系のレイヤーも、必ずこのラスタの上に重なる。不透明度は面で塗るレイヤー共通の値（`AREA_LAYER_OPACITY`）で、こちらは面そのものが背景と区別できる濃さだけを決める。
- **起伏（陰影）は別レイヤー**: 色別標高図が「この場所が何mか」を面で塗るのに対し、起伏は「どこに坂があるか」だけを塗る。`GET /api/gsi-terrain-tile/{z}/{x}/{y}.png`が地理院の標高タイル（`xyz/dem_png`、z14まで）をTerrain-RGBへ移して返し（[backend/app/domain/terrain_rgb.py](../backend/app/domain/terrain_rgb.py)）、フロントは`raster-dem`ソース＋`hillshade`レイヤーとして描く。傾きが0の画素は透明になるため、平地では基礎地図の土地の色がそのまま残る。`hillshade`は不透明度のpaintプロパティを持たないため、面レイヤー共通の濃さは影・光の色のalphaとして渡す。計算方法は`igor`（既定の`standard`は傾きのsinに比例し、関東平野の傾きでは実効の不透明度が0.03を下回る。`basic`・`multidirectional`は平坦な画素にも光を塗るため使えない）。標高は`raster-dem`のcustom encodingの係数で垂直方向へ強調して読む——タイルの値は実際の標高のままで、読み方だけを変える。
- **ビューポート制限を持たない**: ラスタタイルはズームに応じて自動的に切り替わる標準的なXYZタイルのため、範囲を制限する必要がない（後述の路面データのみズーム範囲の制限を持つ）。

#### 路面データ：自前生成のベクタタイル（`GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf`）
標準的なXYZベクタタイル（MVT）として配信し、PostGISを第一系統とする（この方式に至る経緯は[decisions/pre-static-attributes-gate.md](records/decisions/pre-static-attributes-gate.md)参照）。

- **タイル範囲の算出**: `domain/region.py`の`tile_bounds_lonlat(z, x, y)`が、標準的なスライピータイル座標式（Web Mercator）からタイルが覆う緯度経度範囲を求める。MapLibre自身が使うタイル座標系そのものなので、キャッシュの単位とMapLibreが要求するタイルが一対一に対応する。
- **MVT生成**: `RegionService.get_road_surface_tile(z, x, y)`（[backend/app/services/region_service.py](../backend/app/services/region_service.py)）が、`repository`（PostGIS、`road_graph_use_repository=true`時）を渡されていればまずPostGIS側（`road_graph_repository.py`の`_ROAD_SURFACE_TILE_MVT_SQL`、`ST_AsMVT`）へ問い合わせる。要求タイルのz12祖先タイルが取込済みマークされていれば、SQL側でMVTバイナリまで丸ごと生成して返す（Pythonでの再エンコードは発生しない）。カバレッジ外・DB障害・`repository`未接続（DBなし構成）の場合は、`infrastructure/vector_tile.py`の`encode_empty_road_surface_tile`が返す道路フィーチャ0件の空タイルにフォールバックする（Overpassへの問い合わせは改善計画T22で撤去済み。ログ方針: 常時WARNING）。
- **永続化層**: 生成したタイル（PBFバイナリ）は、**基礎地図タイルと同じファイルキャッシュ**（`infrastructure/tile_cache.py`、`region/road-surface/v{ROAD_SURFACE_TILE_VERSION}/{z}/{x}/{y}.pbf`というパスで保存）にキャッシュする。管理画面`/admin`「データ保守」タブのタイルキャッシュ消去（`POST /api/admin/basemap/refresh`、Basic認証必須）を押すと基礎地図タイルと路面タイルの両方が一括でクリアされる（同じ`tile_cache.clear_all()`を共有しているため）。空タイル（カバレッジ外・DB障害）はキャッシュに保存しない（後からPBF取込された際に正しいタイルを再生成できるようにするため）。
- **安全弁**: bbox対角距離の代わりに、`domain/region.py`の`ROAD_TILE_MIN_ZOOM = 12` / `ROAD_TILE_MAX_ZOOM = 15`でズーム範囲を制限する。旧`api/routes.py`のエンドポイントはこの範囲外のzを400で拒否する（直接APIを叩かれた場合の安全弁。通常はMapLibre自身がvector sourceの`minzoom`/`maxzoom`設定によりこの範囲外のタイルを要求しないため、二重の防御になる）。標高（ラスタタイル）にはこの制限を適用していない。

#### 地図タイルのバックエンド経由プロキシ＋キャッシュ
`BasemapClient`（[backend/app/infrastructure/basemap_client.py](../backend/app/infrastructure/basemap_client.py)）がOpenFreeMap（`tiles.openfreemap.org`）のスタイルJSON・TileJSON・スプライト・グリフ・タイルを透過的にプロキシしつつ、ファイルシステム（`backend/data/tile_cache/`、[backend/app/infrastructure/tile_cache.py](../backend/app/infrastructure/tile_cache.py)）にキャッシュする（`GET /api/basemap/{path:path}`）。

- **同一オリジン維持とURL書き換え**: レスポンスがJSON（スタイルJSON/TileJSON）の場合、内包するOpenFreeMap本体への絶対URLを、自分自身（`settings.basemap_public_base_url`、既定値`http://localhost:3000/api/basemap`）への絶対URLに書き換えてから返す。MapLibreは相対URLをスタイル自身の取得元ではなく**ページのオリジン**に対して解決してしまう（spriteURLに至っては相対URLを明示的に拒否する）ため、絶対URLへの書き換えが必須。書き換え先は既定ではバックエンド自身のURL（`:8000`）ではなく、フロントエンドのURL（`:3000`）である（後述の接続数上限の問題を避けるため）。本番のようにタイルをbackendへ直接取りに行かせる構成（frontendの`NEXT_PUBLIC_TILE_BASE_URL`、[frontend/src/lib/tileBaseUrl.ts](../frontend/src/lib/tileBaseUrl.ts)）では、backend側の`BASEMAP_PUBLIC_BASE_URL`も同じbackendオリジン（`https://<backend>/api/basemap`）へ揃える——frontendはスタイルJSONの取得先だけを`tileBaseUrl()`で決め、その中のタイル・スプライト・グリフのURLはbackendが書き込むため、片方だけ変えるとタイルだけRender経由に戻る。
- **キャッシュとURL書き換えの整合性**: スタイルJSON/TileJSONは上流の内容（書き換え前）を`basemap-raw/`接頭辞のキャッシュキーで保存し、URL書き換えは返す直前に毎回行う。そのため`basemap_public_base_url`の設定値を変更しても、キャッシュを消さずに次の応答から新しいURLが返る（URL書き換え後の内容をキャッシュすると、設定変更後も古いURLを返し続けキャッシュの全消去が必要になる）。
- **タイルとAPIを同じオリジンに載せない**: 地図初期化で数十件のタイル/フォント/スプライトが同時に飛ぶため、APIと同居させるとブラウザのオリジン単位の同時接続数上限（HTTP/1.1で6本程度）を埋め、ルート生成が数十秒詰まる。Next.jsの`rewrites()`（[frontend/next.config.ts](../frontend/next.config.ts)）で`/api/basemap/*`と`/api/region/road-surface-tiles/*`（路面ベクタタイル、Step10改訂で追加）の両方をバックエンドへプロキシし、ブラウザからは常にフロントエンドと同一オリジン（`:3000`）に見えるようにした。これにより「タイル群（`:3000`経由）」と「API呼び出し（`:8000`直接）」が別オリジン扱いになり、接続枠が競合しなくなる。なお路面・POI・事故のベクタタイル、基礎地図のスタイルJSON、国土地理院色別標高図、JMA動的タイルは、`NEXT_PUBLIC_TILE_BASE_URL`（[frontend/src/lib/tileBaseUrl.ts](../frontend/src/lib/tileBaseUrl.ts)）を設定するとrewritesを経由せずbackendへ直接取りに行く（基礎地図のタイル本体はbackend側`BASEMAP_PUBLIC_BASE_URL`で追随させる）。この場合はAPI呼び出しと同じオリジンへタイルが載るため、backend前段のnginxがHTTP/2以上（多重化）で応答できる構成が前提になる（改善計画T580: 本番VMのnginxをHTTP/3＋HTTP/2対応へ差し替えた上で設定する）。**フロントエンド側は`MapView.tsx`の`MAP_STYLE`定数（相対パス`/api/basemap/styles/liberty`）でこのrewriteを経由する必要があり、デバッグ目的で一時的にバックエンドへの絶対URLへ書き換えたときは、必ず元へ戻す**（実際に前回セッションで戻し忘れており、動作確認時に発見・修正した）。
- **Windowsでのパスフラット化**: OpenFreeMapのURL構造には`planet`（TileJSON本体）と`planet/<version>/{z}/{x}/{y}.pbf`（実タイル）のように、同じセグメントがファイルとディレクトリ接頭辞の両方として使われるケースがある。パスをそのままディレクトリ階層にミラーリングすると、Windowsでは「同名のファイルがあるためディレクトリを作成できない」というエラーで実際にクラッシュすることを実機確認したため、`tile_cache.py`はパスをSHA-256でハッシュ化しフラットなファイル名（`<hash>.bin` / `<hash>.meta`）で保存する。副次的にディレクトリトラバーサル対策にもなる。
- **イベントループのブロッキング回避**: `tile_cache`の読み書きは同期的なディスクI/O。基礎地図読み込み時は数十件のタイル/フォントリクエストが同時に来るため、`asyncio.to_thread`を介さず直接呼ぶとイベントループ全体をブロックし、同時に処理中の他のリクエスト（ルート生成等）が数十秒単位で詰まることを実機確認した。`BasemapClient.get`・`RegionService.get_road_surface_tile`はいずれも`tile_cache.get`/`set`を必ず`asyncio.to_thread`経由で呼ぶ。
- **ベクタタイルの取得はWeb Worker内で行われる（実機確認で発見・修正済み）**: MapLibreはラスタタイル（`Image`要素、メインスレッド）とベクタタイル（`fetch`、Web Worker内）でタイルの取得方法が異なる。ラスタタイルのURL（`MAP_STYLE`や地理院タイルのURL）は相対パス・絶対パスいずれもページのオリジンに対して解決されるが、ベクタタイルのURLをWorker内から相対パスのまま渡すと`Failed to construct 'Request': Failed to parse URL from ...`のエラーで取得自体が失敗することを実機確認した（Workerの実行コンテキストはページとは別のベースURL解決になるため）。そのため路面ベクタタイルのURLは`window.location.origin`を使って呼び出し時に明示的に絶対URL化している（[frontend/src/services/regionApi.ts](../frontend/src/services/regionApi.ts)の`roadSurfaceTileUrl()`）。`window`はクライアントサイドでのみ参照可能なため、モジュール読み込み時に評価される定数ではなく、呼び出し時に評価される関数として実装してある点に注意（Next.jsのクライアントコンポーネントも初回はサーバー側でレンダリングされるため、モジュールの最上位で`window`を参照するとSSR時にクラッシュする）。

#### フロントエンドの表示制御（`MapView.tsx`）
標高・路面は「変わらないデータ（表示中の地域全体）」として、選択中候補とは独立にON/OFFする。

既知の制約: PostGIS未取込範囲（またはDBなし構成）は常に空タイルになるため、その範囲では路面レイヤーが表示されない（Overpassフォールバックは改善計画T22で撤去済み）。取込済み範囲内であれば初回表示から高速（`ST_AsMVT`でPostGIS側がMVTバイナリまで生成するため、Pythonでの追加エンコード処理を挟まない）。

#### JMA動的タイル系レイヤーのバックエンド経由プロキシ＋キャッシュ
`JmaTileClient`（[backend/app/infrastructure/jma_tile_client.py](../backend/app/infrastructure/jma_tile_client.py)）が降水ナウキャスト・降水短時間予報（rasrf）・雷/竜巻ナウキャスト・キキクル・線状降水帯予測マップ（下記「動的気象レイヤー」節参照）が使うJMA bosaiエンドポイント（時刻一覧JSON・ラスタタイルPNG）を`BasemapClient`と同じ「pathを丸ごとプロキシ」方式（`GET /api/jma-tile/{path:path}`、`next.config.ts`の`/api/jma-tile/*`rewritesで同一オリジン化）でプロキシする。

- **経緯**: 従来これらは各ユーザーのブラウザがJMAの非公式内部API（`https://www.jma.go.jp/bosai/...`）へ直接fetchしており、バックエンド・キャッシュを一切経由しなかった。T410（キキクル）の実機フィードバック検討中、「防災級の情報は常時ONにすべきでは」という指摘を受け、常時ON化の前提として「利用者数に比例してJMAへの負荷が線形に増えない構成」への切り替えが必要と判断し、ユーザー方針「動的なデータはなるべくバックエンド経由に」に沿って実施した。
- **キャッシュ戦略の分岐**: `BasemapClient`のOpenFreeMapタイルと異なり、JMA側は2種類の更新頻度が混在する。①ラスタタイル本体（`basetime/validtime/z/x/y`が確定した時点で内容が不変）は`tile_cache.py`の永続ファイルキャッシュへそのまま乗せる。②`targetTimes*.json`（数分〜数十分単位で更新される時刻一覧）を同じ永続キャッシュへ乗せると更新後も古い内容を無期限に返し続けてしまうため、`jma_warning_client.py`と同じ`cachetools.TTLCache`（プロセス内、TTL=2分）を別途用意し、パスの末尾が`targetTimes*.json`かどうかで振り分ける。
- **横展開の検討**: JMA以外に同様の直接fetchが無いか調査した結果、国土地理院の色別標高図タイル（`cyberjapandata.gsi.go.jp`、`MapView.tsx`）のみ該当した。「ブラウザからの直接埋め込み利用を前提に国が公開している正式なAPI」でありJMAの「非公式の内部API」への配慮とは動機が異なるため負荷分散の観点では対象外だが、時刻に依存しない静的データのためレスポンス速度向上目的の永続キャッシュ化には価値があると判断し、改善計画T572で`BasemapClient`と同じ方式でバックエンド経由化した（上記「標高オーバーレイ」節参照）。

### 動的気象レイヤー（風・降水延長予報）の共通契約

Step10の標高・路面は「地域に固定・時間で変わらない」重ね描きだったが、ユーザー要望
「動的レイヤーについては今後もデータ追加があり得るので、それも見据えて拡張性がある
設計にしてほしい」を受け、**時刻によって内容が変わる**地域重ね描きレイヤー（気象庁
降水ナウキャスト・風の矢印・延長降水予報）を第三の種別として導入した。

- **共通契約（T184、T432でグループ内複数ソースへ一般化）**: [frontend/src/components/Map/dynamicWeather.ts](../frontend/src/components/Map/dynamicWeather.ts)が
  DOM/MapLibreを知らない純粋なデータ層として、(1) 表現は`rasterTile`（配信元描画済み画像）／
  `gridFill`（格子を色で塗る）／`gridMark`（格子中央にアイコン）の3種のみ、(2) ONの全レイヤーの
  フレーム時刻を`mergeFrameTimes`で1本のタイムラインへ統合し時刻スライダーを1本に共有、
  (3) 選択時刻がそのレイヤーのデータ範囲外なら`frameIndexForTime`が`null`を返し**描画しない**
  （旧設計は端のフレームへクランプして古いデータを見せ続けていた）、という3つの制約を定義する。
  **改善計画T432**: 当初`DynamicWeatherLayerId`（1グループ）は同時に1つのpayload（=1つの
  kind）しか持てなかったため、風の評価軸penalty面表示（windVectorの矢印と同時表示が必要）が
  この機構を迂回した個別実装になっていた。`DynamicWeatherGroupState`
  （ソースキー→`{visible, payload}`）を導入し「1グループ＝複数の名前付きソース、各ソースが
  独立してkind/payloadを持てる」形へ一般化し、当時は風の面塗りもこの機構へ統合していた
  （面塗りはユーザー指摘を受け撤去済み、§動的気象レイヤー参照）。線状降水帯予測マップは
  `precipitationNowcast`グループの4つ目のソース（`linearRainband`、既存3段=`main`と独立に
  重畳）として同じ機構を使う（詳細は下記「キキクル・線状降水帯予測マップ」節参照）。
  新しい動的要素の追加は「①`domain/wind_grid.py: WindGridPoint`へ値フィールド追加＋
  旧`msm_client.py: WIND_VARIABLES`へMSM変数追加（同期・読み出しは相乗り）
  ②要素専用のデータ層モジュール新設（フレーム列＋ペイロード関数）③`MapView.tsx:
  DYNAMIC_WEATHER_RENDERERS`へ描画スペック1エントリ追加（グループ内の新規ソースとして
  追加する場合はそのグループの既存エントリへソースキーを1つ足すだけでよい）④`mapLayers.ts`
  へチップ追加（既存グループへのソース追加の場合はチップ自体は不要）」という手順に一本化
  されている。`page.tsx`はこの契約に従い、旧5個の風/降水個別propsを
  `dynamicWeather: Partial<Record<DynamicWeatherLayerId, DynamicWeatherGroupState>>`単一propへ
  統合した。
- **風の格子点マップ（T178、フォローアップ）**: 気象庁MSM由来の`@openmeteo/weather-map-layer`
  （GPLv2）を当初採用したが、(1) GPLv2依存が避けられない、(2) 矢印の長さがライブラリ側で
  ズームレベル依存に固定され自由に表現できない、という制約に実機で行き当たり、ユーザー判断
  （2026-08-20）で自前実装へ切替。[backend/app/domain/wind_grid.py](../backend/app/domain/wind_grid.py)が
  関東本土全域の固定格子点（原点固定・0.1°間隔・約624点）を生成し、既存の
  `msm_client.read_series`（気象庁MSM、CC-BY-4.0）が全格子点ぶんをまとめて補間する。フロントは結果をMapLibre標準のGeoJSON source + symbolレイヤーで描画
  （矢印アイコンは`MapView.tsx: createWindArrowIcon`が独自定義。密度は矢印の大きさと色のコントラストで表す——背景を面で塗ると他のレイヤーと重なって見分けがつかない）。
- **詳細格子（T180・T185）**: ズームインした範囲だけ密な格子（`generate_wind_grid_detail_points`、
  `GET /api/weather/wind-grid-detail`）を追加取得する。座標は表示bboxの角ではなく固定原点
  からのオフセットで計算するため、近い範囲を見る別ユーザーとキャッシュを共有できる。
  格子間隔はズームに応じて4段階（0.02/0.01/0.005/0.0025度）に細かくなり
  （`WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEG`の離散値のみ許可、連続値だとラティスの絶対座標が
  ずれてキャッシュ共有が効かなくなるため）、値は`export_openapi.py`が書き出す
  `wind-grid-config.json`をフロント（`windLayer.ts`）が単一の情報源としてimportする
  （改善計画T198、旧「値を合わせること」というコメントのみの手動同期を廃止）。
- **応答の時刻配列を1本化（T203）**: `wind-grid`/`wind-grid-detail`の応答は`WindGridResponse
  {times: list[str], points: list[WindGridPoint]}`形（`WindGridPoint`自体は`times`を
  持たない）。全地点が同じforecast_days・timezoneで一括取得されるためhourly.timeは
  全地点で共通で、応答は`times`を1本だけ持つ（地点ごとに複製しない）。フロント内部（windLayer.ts/useWeatherGrid.ts/precipitationNowcast.ts）
  は「各点がtimesを持つ」既存表現のまま変えておらず、`services/weatherApi.ts`の
  `toWindGridPoints`がバックエンド応答を受け取った直後にtimesを各点へ合成し直すことで、
  ワイヤーフォーマット（削減対象）とフロント内部データモデル（既存ロジック）を分離した。
- **降水延長予報（T183・T407）**: 気象庁降水ナウキャスト（[frontend/src/components/Map/precipitationNowcast.ts](../frontend/src/components/Map/precipitationNowcast.ts)、
  実況〜+60分・5分刻み、`rasterTile`表現）は仕様上+60分が上限のため、それ以降を2段で
  継ぎ足す。①改善計画T407（2026-08-30）: +60分〜+15時間は気象庁 降水短時間予報
  （`rasrf`、`https://www.jma.go.jp/bosai/jmatile/data/rasrf/targetTimes.json`、
  数値予報モデルによる予測、`rasterTile`表現）。`member`フィールドが"immed"（直近0〜6時間、
  高頻度更新）と"none"（7〜15時間先、毎正時更新）の2系統を持ち、同一basetime配下に
  中間ランの単発validtimeや別プロダクト（線状降水帯予測マップ`sjfcstmap`、
  [T410](records/tasks/T410.md)で実装）の行が混在するため、`elements.includes("rasrf")`で
  絞り込んだ上で「異なるvalidtimeを複数持つ最新のbasetime」を選ぶ（`fetchRasrfFrames`）。
  ②+15時間より先（〜約48時間先）は上記の風と同じ格子点マップへ`precipitation`（mm/h）を
  相乗りさせ、`gridFill`表現（格子をセルとして塗る）で継ぎ足す。1回のフェッチで風・
  延長予報の両方を1回の読み出しで賄う。各段は前段の最終フレームより
  後の時刻だけを採用し、近い将来の二重表示を避ける（ナウキャスト→rasrf→延長予報の
  2つの境界とも同じロジック、`precipitationFrames`）。
- **雷ナウキャスト・竜巻発生確度ナウキャスト（T204）**: [frontend/src/components/Map/thunderNowcast.ts](../frontend/src/components/Map/thunderNowcast.ts)が
  降水と同じbosai/jmatile/data/nowc/系（プロダクトコード`thns`＝雷・`trns`＝竜巻）を
  `rasterTile`表現のみで重ねる。降水と異なり`targetTimes_N3.json`1本に実況〜+60分の予測が
  同居し（N1/N2のような分割が無い）、MSM側に相当するデータが無いため延長予報は
  持たない（60分より先は範囲外として描画しない、T184共通契約どおり）。雷・竜巻は同じ
  時刻一覧を共有しつつ、地図上は独立したON/OFFチップ2つに分ける（重ねると見分けにくいため）。
  「回避一択」の危険（設計判断は本節冒頭参照）のため評価軸には組み込まず警告表示のみ。
  JMAナウキャスト系に共通する時刻一覧の取得・整形（`fetchJmaTargetTimes`・
  `trimToCurrentAndFuture`・`parseValidtime`）は[frontend/src/components/Map/jmaNowcastFrames.ts](../frontend/src/components/Map/jmaNowcastFrames.ts)
  （降水・雷の2つ目の消費者が現れたことを受けT204でprecipitationNowcast.tsから抽出）が
  単一の情報源として持つ。
- **キキクル（危険度分布）・線状降水帯予測マップ（T410、T432で扱いが分岐）**: [frontend/src/components/Map/riskMap.ts](../frontend/src/components/Map/riskMap.ts)が
  気象庁キキクル（土砂`land`・大雨`rain_mesh`・浸水`inund`、`https://www.jma.go.jp/bosai/jmatile/data/risk/targetTimes.json`）と
  線状降水帯予測マップ（`sjfcstmap`、rasrfと同じ`targetTimes.json`にelements違いの別行として
  混在）のタイル・時刻取得を担う。要素コードは`properties.xml`記載の製品コードと実際の
  タイルパスが食い違う例があり（大雨は製品コードが`heavyrain`だが実タイルパスは
  `rain_mesh`）、必ずJMA公式ページ（`https://www.jma.go.jp/bosai/risk/`）をBrowserペインで
  操作し実ネットワークログで裏取りした（洪水`flood`は`.pbf`＝Mapbox Vector Tileで方式が
  異なるためスコープ外）。この4レイヤーは`validtime === basetime`（未来方向のフレームを
  一切持たない「現在のみ」のスナップショット、10分おき更新）という他の動的レイヤーに無い
  性質を持つ。**改善計画T432**: 当初T410はこの4レイヤーを「現在の防災リスク」として一括り
  にしていたが、データソースの系統（risk vs rasrf）と予報の性質が異なると判明したため
  訂正した:
  - **キキクル3種（土砂・大雨・浸水）**: 「防災」カテゴリとして`WarningBadge`
    （`frontend/src/components/WarningBadge`、T205）と同様の常時マウント（チップ無し・
    `layerVisibility`自体を持たない）。**防災情報は利用者の操作を待たずに出す**。

  - **線状降水帯予測マップ**: データソースが実はrisk系統ではなくrasrf系統（降水短時間予報
    と同じ）と判明したため「降水」チップ（`precipitationNowcast`グループ）の4つ目の
    ソース（`linearRainband`）へ再分類した。「今後3時間以内におそれ」という予報の性質に
    合わせ、共有タイムラインの選択時刻が現在〜3時間先の範囲内のときだけ、既存3段
    （ナウキャスト→rasrf→延長予報、`main`ソース）と独立に重畳表示する
    （`isWithinFutureWindow`、`dynamicWeather.ts`参照）。既存3段と異なり「降水」チップの
    ON/OFFのみに連動し、共有タイムラインとの連動は保ったまま。
  - 過去に検討し見送った「複数の危機を1つの防災アイコンへ集約する」案（T412調査時）は
    T432でも再確認したが判断は変わらず、既存のJMA警報・注意報バッジ（`WarningBadge`）が
    近い役割を果たすという整理のまま据え置いた（キキクルの現在警戒度を返すJSON APIが
    JMA側に存在せず、正確な判定にはピクセル解析等の新規実装が必要なため）。
- **night軸の動的化（T173）**: `domain/twilight.py: is_night`が`astral`ライブラリ（暦計算、
  外部通信なし）で市民薄明（太陽高度-6度）を判定し、区間の推定到達時刻がその外（夜間）なら
  night軸の重み（`RoutePreference.weights["night"]`）をそのまま、日中なら0倍にして合成する（night軸の難易度自体の算出は
  街灯・トンネルタグのみに基づき不変、重みの掛け替えだけで動的化）。`RoadGraphEngine`は
  出発時刻1点のみで全区間へ一様適用する（区間ごとの推定到達時刻は使わない）。風の
  探索コストは**到達時刻ごと**に持つ——レグを時刻ビンへ刻んでビンごとのコスト配列を
  合成し、探索が到達時刻をラベルとして運ぶ
  （`docs/modules/backend/routing-engine.md`「レグ内の時刻ビン」）。
- **Open-Meteo 429対策（T179・T194・T195。T645でMSMへ全面移行し、Open-Meteo依存自体が無くなったため解消済み）**: 本番（Render、共有の送信元IP）でのOpen-Meteo
  429常態化に対し、ユーザー提示の6段階ロードマップ（①複数座標の1リクエスト集約
  ②気象Gridの道路評価Gridからの分離③気象Gridの固定化④TTL付きDB永続キャッシュ⑤
  バックグラウンド更新⑥利用者増加時のOpen-Meteo自前運用）の実装到達点を調査・記録した
  （T194、④まで完了・⑤⑥は未着手のまま記録のみ）。④は旧`get_forecast_many`をL1（プロセス内
  メモリ）→L2（Redis）→実フェッチの順に問い合わせる形で実装し（T195）、
  TTLを30分→3時間、失敗時のstaleフォールバック許容幅を3時間→24時間へ拡大した。あわせてOracle Cloud VM上のリレープロキシ（旧`OPEN_METEO_BASE_URL`、
  T179）で送信元IPを本番の共有IPから分離する経路も用意済みだが、本番では未有効化（T182の
  調査でクォータ枯渇は送信元IP非依存の現象と判明したため）。
- **時刻依存レイヤーの表示時刻（T170・T188〜T193・T596・T611）**: 表示時刻は地図下部の条件バー[frontend/src/components/RideConditionBar/RideConditionBar.tsx](../frontend/src/components/RideConditionBar/RideConditionBar.tsx)の出発時刻（`dynamicLayerTargetTime`）と同じstate。ドラッグ/横スクロールで選ぶ`DynamicLayerTimeSlider`（左端固定インジケータ・正時/非正時で異なる目盛り幅・ArrowLeft/Right/Home/Endキー操作、Embla Carouselベース）と、`input[type=datetime-local]`による直接指定の2系統を両立させる。複数の時刻依存レイヤーが同時ONでも共有タイムライン1本（上記T184）に統合されているため、スライダー自体も1本のみマウントする。
- **フックへの抽出（T183フォローアップ）**: [frontend/src/hooks/useWeatherGrid.ts](../frontend/src/hooks/useWeatherGrid.ts)が、
  風の矢印・延長降水予報が共有する格子点マップのフェッチ・穴あき対策マージ・詳細格子への
  切替を1つのフックへ集約する（元はpage.tsx内に直接書かれていた風専用ロジックを、風と
  降水延長予報が共有できる形へ切り出した）。

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

### 材料カタログのレジストリ

> 経緯・教訓（display_only方針転換の紆余曲折、categorical dtype対応のGUI/backend乖離期間等）は
> [decisions/material-catalog-registry.md](records/decisions/material-catalog-registry.md)参照。

`domain/material_catalog.py: MaterialSpec`/`MATERIAL_CATALOG`が「材料」（軸が参照する
`MaterialTerm.material`等の文字列id）の単一の情報源。各材料は`material_id`・`label`・
`dtype`（"numeric"|"boolean"|"categorical"）に加え、内部専用の`tile_property`
（MVTタイルへの焼き込み済みプロパティ名、地図レイヤーのramp自動生成に使う）・
`display_only`（真なら軸スタジオの選択肢から除外する。地図表示には影響しない）を持つ。
登録済み材料の全件は生成物`material-catalog.json`（`domain/material_catalog.py`が正本）で
引ける。**材料自体をGUIから追加・編集・削除する
経路は無い**（ユーザー方針、増減は引き続きコード変更＋デプロイのみ）。

公開エンドポイント`GET /api/material-catalog`（認可不要、`material_id`/`label`/`dtype`のみ）を
`hooks/useMaterialCatalog.ts`がマウント時取得し（失敗時は`lib/axisMaterialsCatalog.ts`の
静的9件へフォールバック）、`AxisComposer.tsx`の材料選択ドロップダウンを構成する。管理API
（`axis_admin.py: AxisDefinitionPayload`）の`_check_materials_are_known`が、shapeが参照する
材料idの実在を422で検証する。

材料の値はSQL式（`MaterialSpec.value_sql`）として宣言し、DBが導出する。共通の判定
（タグの正規化・タグ値の一致・数値パース・件数の密度化・wayの行の有無）は
`domain/material_sql.py`の組み立て関数から作るため、材料ごとに式を書き写さない。
評価・地図タイル・欠損率の集計はすべてこの同じ式を読む。

`GET /api/admin/material-catalog/{material_id}/values`（HTTP Basic認可要）が、DBに実際に取り込まれている値の
一覧（`RawOsmRepository.get_distinct_material_values`、DB未接続時は空リストへグレースフル
デグレード）を返し、`AxisComposer.tsx`の値入力欄（`hooks/useMaterialValues.ts`）が自由テキスト
入力の隣に「値の候補」セレクトとして添える（値一覧が空の材料は従来どおり自由テキストのみ）。
各値の日本語ラベルは`domain/material_catalog.py: MaterialSpec.value_labels`が単一の情報源で、
`GET /api/material-catalog`の`value_labels`として配信される（frontend側は
`lib/evaluationAxes.ts`が受け取るだけで対訳表を持たない）。未知の値はタグ値そのままを
表示するフォールバック。

`GET /api/admin/material-catalog/coverage`（Basic認証必須、改善計画T577）が材料ごとの
欠損割合（元データ[OSMタグ・派生テーブル行]を持たないWay/Edgeの割合と、欠損を不明値と
して扱うか確定値として扱うかの区別）を返し、`/admin`の「材料」タブ
（`components/AxisStudio/MaterialCoveragePanel.tsx`）が表示する。材料id→判定式は
`infrastructure/material_coverage.py: MATERIAL_COVERAGE_SPECS`（対象外は
`MATERIAL_COVERAGE_EXCLUSIONS`に理由付きで列挙）の宣言テーブルで、全材料がどちらかに
載ることをテストで強制する。欠損を取込側で推測して埋めるのではなく、実態を見せて
埋めるかどうかの判断を軸定義側へ委ねる（詳細は`docs/modules/backend/evaluation-scoring.md`
「材料の欠損割合」節）。

### 静的レイヤー・タイル配信（フロント固定レイヤー＋レジストリ駆動の二次軸ランプレイヤー）

[frontend/src/components/Map/mapLayers.ts](../frontend/src/components/Map/mapLayers.ts)の
`buildMapLayers()`が実行時に組み立てるカタログは標高図・土地被覆・道路の種類・路面の種類（T165で「道路情報」から論理分割）・
車ストレス・自転車インフラ・指定路線・停止要因POI・補給休憩ポイント（T101）・
事故（警察庁統計）・ルートの固定レイヤー（旧・安全度レイヤーは改善計画T148で削除）に加え、
降水ナウキャスト・風（矢印）の2レイヤーが`kind="static"`（選択候補と無関係に常設）・
`dataNature="dynamic"`（値は時刻で変わる）として同じカタログに乗る（「動的気象レイヤー」節
参照）。交差点密度（次数3以上のroad_node）はバックエンドの
`poi-tiles`が引き続き焼き込むが、道路網を見れば概ね自明という判断（改善計画T96）により
地図上の独立可視化レイヤーとしては提供しない（旧`intersection_weight`のルーティング材料
としては引き続き使う）。色分け・凡例・絞り込み軸の定義は
[frontend/src/components/Map/staticAttributeLayers.ts](../frontend/src/components/Map/staticAttributeLayers.ts)
に集約（`buildStaticFilterAxes()`が絞り込みUIのカタログを軸カタログから組み立てる。
ビルド時の静的な定数ではない——公開軸は軸スタジオから増減するため、
`GET /api/axis-catalog`の実行時の中身に合わせないとレイヤーだけが残る）。
地図上チップ（`MapOverlayControls.tsx`）最上位のグルーピング（道路/環境/スポット）は
改善計画T406/T418により`MapOverlayGroup`が担う（「地図チップの最上位グルーピング
（道路/環境/スポット）」節参照）。凡例・絞り込みはチップの▶パネルが持つ（同じグルーピングを別のパネルへ二重に持たない）。

タイル配信の系統:

1. **`road-surface-tiles`**: highway・surface_good・
   smoothness・tunnel・bridgeに加え、`designation`・車ストレスの
   材料タグ（`maxspeed_kmh`/`lanes_count`/`motor_vehicle_no`。旧`cycleway_class`は
   改善計画T337で、`bicycle_infra`は改善計画T347で削除済み）と、night軸が参照する`lit`、改善計画T145b（下記
   「レジストリ駆動の二次軸ランプレイヤー」参照）が
   追加した`way_attribute_counts`由来のkm正規化密度（`accident_per_km`/
   `intersection_per_km`と停止要因POIの種別別密度`poi_*_per_km`、0はNULLIFでプロパティ
   自体を省略）をLineString地物へ追加
   （P1・T51・T145bで拡張）。世代v2=surface/highway追加、
   v3=surface正準拡充、v4=P0静的属性追加、v5=T51 designationプロパティ追加、
   v6=T74 designationのosm_way_id基準化・3値化（`both`追加）、
   v7=T90 osm_way_idプロパティ追加（区間クリック時の車ストレス内訳取得の識別子）、
   v8=T93（統合レビュー2026-08-17 F-1、T92の車ストレス判定ロジック変更の世代対上げ漏れ修正）、
   v9=車ストレスレシピ外出し基盤（当時の呼称は「交通ストレス」、改善計画T150で改称）。
   計算済みの`traffic_stress`最終値プロパティを廃止し、
   材料タグへ差し替え（最終値の計算はフロントエンドのMapLibre expressionへ移した）、
   v10=安全度レシピ（T148で軸自体を削除）。当時の材料タグ`shoulder`/`lit`を追加
   （tunnelは既存プロパティを再利用）、v11=T122（`shoulder`がP1実測0.0%の死に補正と判明し
   撤去。追加時と撤去時の両方で対上げが必要という教訓。`lit`はT139でnight軸へ転用され
   現在も使用中）、v12=T145b。`way_attribute_counts`のLEFT JOINで
   `accident_per_km`/`stop_per_km`/`intersection_per_km`を追加、v13=T289（一方通行`oneway`
   プロパティ追加。プロパティ追加のみでデプロイ順序制約なし）、v14=T337
   （評価軸・地図表示のどちらからも未参照になった旧`cycleway_class`プロパティを削除。
   非互換変更だが未使用のためデプロイ順序制約なし）、v15=T338フォローアップ
   （designationが畳み込む前の正規化フラグ`is_emergency_transport`/`is_critical_logistics`
   プロパティを追加。プロパティ追加のみでデプロイ順序制約なし）、**v16=T347。地図表示の
   専用レイヤー廃止・評価軸側の公開軸`bicycle_infra_quality`への置き換えに伴い、
   評価軸・地図表示のどちらからも未参照になった`bicycle_infra`プロパティを削除**
   （v14と同じく非互換変更だが未使用のためデプロイ順序制約なし）。v17以降の内訳は
   本節へ追従していない（現行値の正本は生成物`region-tile-config.json`。世代は焼き込みSQLから
   導出されるため、この一覧を人が維持する必要はもう無い）。**v24=T719。
   停止密度が種別別密度`poi_*_per_km`だけを材料にする形へ移った結果、読み手の無くなった
   `stop_per_km`プロパティを削除**（v14/v16と同じく非互換変更だが未使用のため
   デプロイ順序制約なし、現行）。
2. **`GET /api/region/poi-tiles/{z}/{x}/{y}.pbf`**:
   `osm_raw_pois`の点データを`kind`プロパティ付きで焼き込む1レイヤー（`stop_poi`）構成。
   停止要因（信号・横断歩道・一時停止・踏切）に加え、T101で補給・休憩ポイント
   （コンビニ・自販機・トイレ・給水・駐輪場）のkind値も同じテーブル・同じMVTクエリへ
   相乗りさせた（SQL自体は無改修、`kind`を無条件で焼き込む設計のため）。フロント側は
   `kind`値の集合でstopPoi/supplyPoiの2つの独立レイヤーへ絞り込む
   （`MapView.tsx`のbaseFilter、`legendFilter.ts`参照）。交差点密度（`degree`）は
   T96でフロント可視化を撤去、T97で配信自体も削除済み（ルーティング材料としては
   `_INTERSECTION_COUNTS_SQL`が別途独立に計算）。road-surface-tilesと同じ
   `ROAD_TILE_MIN_ZOOM`〜`MAX_ZOOM`のXYZタイル。
3. **`GET /api/region/accident-tiles/{z}/{x}/{y}.pbf`**:
   事故地点の点データ（`involves_bicycle`・`fatal`）。`AccidentService`
   （[backend/app/services/accident_service.py](../backend/app/services/accident_service.py)）・
   専用リポジトリ`infrastructure/accident_repository.py`が担当し、`region_service.py`とは
   別系統（データソースがOSM派生グラフではなく`accident_points`のため）。

4. **`GET /api/region/landcover-tiles/{z}/{x}/{y}.png`**（`LANDCOVER_TILE_VERSION`、T886）:
   土地被覆（Esri×Impact Observatory 10m LULC）のGeoTIFFを、要求されたタイルの範囲だけ
   読んでWeb Mercatorへ再投影し、クラスごとの色で塗ったPNGラスタ。上のMVT系と違いDBを
   読まず、VM上のGeoTIFFを直接読む（`infrastructure/landcover_raster.py`、rasterio）。
   再投影は最近傍で行う——画素値はクラス番号で、平均や補間は存在しないクラスを作る。
   ラスタ本体はリポジトリに持たず、デプロイが`scripts/fetch_lulc_raster.py`で配布元から
   取得してVMのディレクトリ（コンテナへは`/app/raster`として読み取り専用でマウント）へ
   置く。**どのクラスを塗るかはレジストリが宣言する**（`LandcoverClass.painted`）——
   建物は塗らない。市街地では画素の85〜95%がそのクラスで、塗ると地図が単色で覆われる
   だけになる（区間インスペクタの内訳には数値として出る）。
   URLの世代は配色レジストリ（`domain/landcover.py: LANDCOVER_CLASSES`）から
   導出されるため、色やクラス構成を変えれば自動で変わる。年次ラスタの差し替えだけは
   `cache_identity.py: LANDCOVER_REVISION`を手で上げる（画素は変わるのに形は変わらない）。
   **どのラスタを開いているかはURLの世代に入らない**——環境変数で環境ごとに違い、
   生成物をビルド機の設定で決めてしまうため。サーバー側のディスクキャッシュは
   ラスタ構成の指紋でディレクトリを分け、ブラウザ側は`immutable`を付けないことで
   再検証できるようにしてある（`docs/conventions/caching.md`のディスク保持の節参照）。

DBから焼くタイル（上記のうちPNGラスタ以外）の世代は焼き込みSQLと、そこへあらかじめ束ねた値から導出される
（`app/infrastructure/cache_identity.py`）ため、プロパティを足す・消す・式を変える・
分類に使うタグ集合を変えれば自動で変わる。frontendへは`export_openapi.py`が
書き出す`generated/region-tile-config.json`が届け、ドリフト検知テスト
（`regionApi.test.ts`）が照合する。

**ただしタイルの中身は、焼き込むSQL（形）と、そのSQLが読むテーブルの中身（世代）の
2つで決まる**。形は上記が自動で署名するが、中身が作り直されたことを知っているのは
バッチが進める`derived_data_meta.revision`だけで、これはビルド時の生成物には入らない
（バッチはデプロイを伴わない）。この2つを繋いで実行時に世代を組み立てるのが
`app/services/tile_version_service.py`で、**手で書く定数を持たない**——手で書くと、
上げ忘れ（古い値を配り続ける）と、バッチ完了後にもう一度上げ直す必要（デプロイとバッチの
間に配信されたタイルが、新しい鍵のまま古い値でキャッシュへ載る）の両方が起きる。
組み立てた世代は`GET /api/axis-catalog`の応答へ相乗りさせてフロントへ配り、フロントは
タイルURLのクエリへ入れてブラウザのキャッシュを分ける（[T848](records/tasks/T848.md)）。

### レジストリ駆動の二次軸ランプレイヤー

上記10レイヤーとは別に、`domain/registry_defaults.py`の二次軸レジストリ（T137）から
自動生成される「ランプ」レイヤー（事故密度・停止密度の軸。`stop_density`というaxis_idは廃止）がある。設計方針は
「**事実はタイルに、解釈はクライアントに**」: レシピ非依存の事実（`way_attribute_counts`由来の
`accident_per_km`/`intersection_per_km`/`poi_*_per_km`）は
全ユーザー共有キャッシュのタイルへサーバー側で焼き込み、二次軸スコアへの変換（重み・
しきい値・凡例）はクライアント側のMapLibre expressionで行う（レシピ依存の解釈をキャッシュ
共有タイルへ焼き込めないという制約と、これらの軸の入力データがタイル外に
あるため元々クライアント計算が原理的に不可能という制約の両方を、この一方向で解決する）。

`export_openapi.py`がレジストリから`axis-catalog.json`（axis_id・ラベル・入力タイル
プロパティ・値域・凡例情報・表示方式`kind`=`ramp`/`bespoke`/`none`）を書き出し、フロントの
`frontend/src/components/Map/axisLayers.ts`が`kind=ramp`の軸から色分けexpression・凡例を
自動生成する（`RAMP_AXES`、`page.tsx`/`mapLayers.ts`/`MapView.tsx`が
`MapLayerId`の`axis:${string}`テンプレート型経由でチップ・パネル・凡例・地図レイヤーへ自動
合流。新しいramp軸はレジストリ登録＋タイル焼き込みだけで地図に現れる）。改善計画T292で
car_stress（内部軸5つの合成値、複数材料の重み付き結合のため`derive_ramp_inputs`の自動導出
対象外だが`tile_inputs`は手書きで`kind=ramp`登録済み。上記「停止密度・車ストレス...」節
参照）もこの汎用パスへ合流し、専用の手書きexpression（旧`carStressExpression.ts`）は
不要になった。現在`kind=bespoke`の軸は無く、gradient/surface_qは`kind=none`（既存の
標高図・道路情報レイヤーが代替）。night軸はT145a（データ充実待ちで保留）まで未生成。

### 動的材料の状態別表現契約とフィーチャー→動的値配信層

上記の二次軸ランプレイヤーは「事実はタイルに焼き込み、解釈（重み・しきい値）はクライアント側の
MapLibre expressionで行う」方式だが、風のように**道路自身に紐づかない外部条件（風向風速）が
関与する材料**は、レシピ非依存の事実そのものがタイル生成時点では定まらない（同じ道路でも
時刻によって値が変わる）ため、この方式に乗らない。

こうした「動的材料」は、材料非依存の共通**状態機械**（[docs/records/tasks/T400.md](records/tasks/T400.md)
「2.」節）に従う: ルート未確定時は「ユーザーが指定したパラメータ（風なら時刻＋走行方位）を
視界内の全道路へ一律適用」・ルート確定後は「ルート自身の実値（実進行方向・実到達時刻）で
ルート線のみへ着色」。**道路自身のOSM格納方向や現在時刻で評価してはならない**——利用者が
指定した向き・時刻と食い違い、同じ道が設定と無関係な色になる。

**ルート未確定時**（「環境」グループと評価軸としての風は同じ[時刻,向き]入力を共有する。
色分けを起動する場所はルート設定パネル[`RouteSettingsPanel.tsx`]だが、**向きの指定元は
「環境」グループのコンパススライダー[`WindBearingSlider`]**という分担）:

- **環境（面）**: 風は矢印のみを持ち、面塗り（`gridFill`）は持たない——矢印（絶対的な
  風向風速）とユーザー指定の走行方位に依存する相対値が同時に出ると見にくいため、走行方位に
  対する向かい風/追い風の強さは次項の評価軸（線）のみで確認する。走行方位に依存する材料は
  評価軸（線）だけが表示を持つ。
- **評価軸（線）**: `WindWayService.get_way_values(z, x, y, at, bearing_deg, speed_kmh)`
  （[wind_way_service.py](../backend/app/services/wind_way_service.py)）が、指定タイル内の
  フィーチャーの鍵一覧（`RoadGraphRepository.get_feature_keys_in_tile`）を取得し、
  最寄りの風グリッド格子点
  （`domain/wind_grid.py: nearest_grid_point`）の風向風速と、**ユーザーが指定した単一の
  走行方位**（全道路共通、道路自身の向きは計算に使わない）・想定速度から`wind_drag_ratio`
  （材料`wind_drag_ratio`、走行速度依存の二乗則、`speed_kmh`必須）で1回だけ計算し、
  タイル内の全フィーチャーへ同じ値を割り当てる（同じタイル内の全道路は常に同じ値を持つ——
  風グリッドをタイル中心1点で代表させる既存の近似＋走行方位が全道路共通のため）。
  計算結果は`(材料id, z, x, y, 時刻バケット, 向きバケット[5度刻み], 速度バケット[1km/h刻み])
  → 値`というタイル単位のキーで[dynamic_way_value_cache.py]
  (../backend/app/infrastructure/dynamic_way_value_cache.py)経由でRedisへキャッシュする
  （TTLは呼び出し元が気象データの新鮮さから渡す。風は3時間）。
  `GET /api/region/dynamic-way-values/wind/{z}/{x}/{y}`（§4参照、`bearing_deg`・`speed_kmh`
  クエリパラメータ必須）が`{feature_key: 地図表示値}`を返す（backendが軸定義で評価した難易度
  0〜100。勾配のような符号付き材料の軸だけ生値、`domain/dynamic_way_values.py:
  transform_dedicated_way_values`）——静的なroad-surface-tiles（MVT、変更なし）とは
  完全に別経路のJSONエンドポイント。
  フロントは`ROAD_TILE_SOURCE_ID`のvector sourceへ`promoteId: { [ROAD_TILE_SOURCE_LAYER]:
  "feature_key" }`を設定し、タイルの`feature_key`プロパティをMapLibreの`feature.id`へ
  昇格させる。**`osm_way_id`ではなく`feature_key`**なのは、タイルのフィーチャーがズームに
  よってway丸ごとにも区間にもなり（改善計画T918、`EDGE_UNIT_MIN_ZOOM`）、`feature_key`だけが
  その単位に追従するため。鍵は文字列のまま扱う（区間単位ではedge_idが入り、数値化すると
  一致しなくなる）。
  `hooks/useDedicatedWayValues.ts`が現在のビューポート（デバウンス後）を覆う道路タイル分を
  まとめてfetchし（`dynamicWayValues.ts: tilesCoveringViewport`）、`MapView.tsx`が
  `map.setFeatureState({source, sourceLayer, id: featureKey}, {windValue: value})`で道路タイル
  の地物へ後から値を差し込む。色分けは`["feature-state","windValue"]`を読むMapLibre
  expression（`dedicatedWayValueLayer.ts: dedicatedWayValueColorExpression`、しきい値・
  配色・単位は軸カタログの`map_value_kind`/`map_value_unit`/`display_thresholds_override`
  から`valueScale.ts`が決め、ルート確定後のルート線色分けと同じスケールになる）。

**ルート確定後**: 上記の風の評価軸の一律色分けは終了する
（`page.tsx`が`hasDetail`で`dedicatedWayValueVisibility`の各値をfalseへ倒す。
`MapView.tsx: clearRoadTileFeatureState`
（改善計画T440で旧`clearWindAxisFeatureState`/`clearGradientAxisFeatureState`という
重複した2関数を統合したもの）が`map.removeFeatureState`でそれまでの全道路ぶんの
feature-stateを明示的にクリアする）。
代わりに、既に実装済みだった`RouteSegmentDetail.axis_difficulties.wind`（ルート生成時点で
区間ごとの実進行方向・実到達時刻を使って計算済み、`routeStyleModesFromCatalogAxes`が
axis-catalogの公開軸から自動生成する`routeStyleModes`の"wind"モード、「ルート設定/結果
パネル」の「生成したルートの色分け」）が、ルート線のみへの正確な色分けを担う——これは
T400.md「3.」節の実装（T352）で既に存在しており、T414で新規に実装したものではない。

風の評価軸レイヤー自体（表示ON/OFF・実際の地図描画）は、改善計画T672で軸カタログ由来の
汎用機構（`buildMapLayers`/`buildStaticOverlayLayers`が`dedicatedAxes`から生成し、
表示は`dedicatedWayValueVisibility`が持つ）に一本化されており、旧`windAxis`という軸専用の
定数・propは持たない。起動UIは改善計画T418で地図上チップから撤去した。

#### 勾配（gradient）と配信機構の汎用化

勾配も標高データ自体は既に永続化済み（`elevation_attributes`テーブル、T218a）のため同じ状態
機械に乗る（[T423](records/tasks/T423.md)、2026-08-30完了）。風・勾配の2例が揃ったことをトリガーに、
[T411](records/tasks/T411.md)（バックエンド配信機構の汎用化検討）も同時に実施した。

**風との違い（設計上の要点）**: 風は「道路自身の向きが不要」という訂正を経た材料（T414）だが、
勾配は逆に**道路自身の向きが本質的に必要**——`gradient_percent`自体が道路の始点→終点方向を
基準にした符号付き値のため。この違いを吸収するため、汎用化した配信機構は「1タイルにつき
スカラー値1個を鍵の一覧全件へbroadcastする」（風）と「1タイルにつき鍵ごとに異なる値を
持つ」（勾配）の両方を同じキャッシュ表現（`dict[feature_key, float]`のJSON）で扱えるようにした。

**符号補正**: `effective_gradient`は**走行方位で符号だけを決め、坂の急さは変えない**
（道路の向き寄りならそのまま、逆向き寄りなら登り下りを入れ替える。
[domain/gradient.py](../backend/app/domain/gradient.py): `GradientCalculator.
effective_gradient`）。角度差を係数に掛ける（cos投影）形は採らない——道路は道路に沿って
しか走れず、辿る以上は坂の急さをそのまま受けるため、15%の坂はどの方位を選んでいても15%の
坂である。代わりに、**どちら向きに辿るかが決まらない直角付近の帯**
（`LENS_PERPENDICULAR_BAND_DEG`）は`shows_gradient`が落とし、値そのものを配らない。
**この判定を取り除くと、直角付近の急坂が符号を選べないまま「平坦」の段の色で塗られる。**
同じ道路の逆方向のroad_edges行（forward/backward）のどちらを使っても結果は変わらない
（道路の向き±180度と`gradient_percent`の符号反転が同時に起き、二重に反転して相殺する）。

**T411の実施内容（汎用化）**:
- **エンドポイント**: `GET /api/region/dynamic-way-values/wind/{z}/{x}/{y}`という風専用の
  固定パスを`GET /api/region/dynamic-way-values/{axis_id}/{z}/{x}/{y}`
  （[region.py](../backend/app/api/routers/region.py): `region_dedicated_way_values`）へ
  一本化した。`material_id`は[domain/dynamic_way_values.py](../backend/app/domain/dynamic_way_values.py):
  `dedicated_way_value_axes()`（`AXIS_DEFINITIONS`の`dedicated_way_value_layer=True`
  な軸から`needs_time`/`needs_bearing`を導出する関数、改善計画T458。勾配は
  `needs_time=False`）で検証し、未知のidは404・向き依存の軸でbearing_deg省略は422。
  DI（`api/dependencies.py: get_dedicated_way_value_service`）は`axis_id`パスパラメータを
  直接受け取り、軸に応じたサービス（`WindWayService`/`GradientWayService`）をDBセッション
  1つだけで組み立てる（両方を毎回Dependsすると2重にセッションを開いてしまうため）。
  パスパラメータ・ファクトリのキー・キャッシュの名前空間はいずれも**軸id**で、サービスが
  返す生値の**材料id**（`WindWayService.material_id="wind_drag_ratio"`等）とは別の名前空間
  （改善計画T672）。
- **キャッシュ層**: 旧`wind_way_penalty_cache.py`（風専用、キーは`(z,x,y,時刻,向き)`→
  スカラー値1個）を[dynamic_way_value_cache.py](../backend/app/infrastructure/dynamic_way_value_cache.py)
  （材料id駆動、キーは`(axis_id,z,x,y,時刻,向き)`→`{feature_key: 値}`のJSON）へ汎用化した。
  風は従来どおり全ての鍵へ同値をbroadcastしたdictを渡すだけで動作は変わらない。
- **サービス層**: `WindWayService`（風専用、風グリッド取得＋旧`headwind_component_ms`）
  と[GradientWayService](../backend/app/services/gradient_way_service.py)（勾配専用、
  `RoadGraphRepository.get_feature_gradient_inputs_in_tile`でフィーチャー単位の
  `(gradient_percent, road_bearing_deg)`を取得しフィーチャー単位で
  `GradientCalculator.effective_gradient`を計算）は、
  どちらも`get_way_values(z, x, y, at, bearing_deg) -> dict[str, float]`という統一
  インターフェースを持つ（`at`は勾配側では無視するが、router側の材料非依存な呼び出しを
  可能にするため受け取る）。材料ごとの計算式自体は各サービスの専用ロジックのまま——
  2具体例しかない現時点で共通のProvider抽象を無理に導入せず、キャッシュ層という実際に
  共有できる部分だけを汎用化した（複雑度平衡の原則）。
- **フロント**: タイル座標計算・複数タイル応答統合（`tilesCoveringViewport`/
  `mergeDynamicWayValues`）を[dynamicWayValues.ts](../frontend/src/components/Map/dynamicWayValues.ts)
  へ抽出し、色式・凡例は`dedicatedWayValueLayer.ts`（風・勾配共通、軸カタログの表示宣言
  `DedicatedWayValueDisplay`だけから組み立てる）と`valueScale.ts`（種類ごとの既定
  しきい値・配色、ルート確定後の`routeStyleModes.ts`と共有）が持つ。フェッチ本体は`services/regionApi.ts:
  fetchDynamicWayValues(axisId, ...)`（1タイル1軸ぶん）・状態管理は
  `hooks/useDedicatedWayValues.ts: useDedicatedWayValues(axes, ...)`（専用way値配信軸の
  一覧を受け取り、軸ごとの結果を`ReadonlyMap`で返す）として統合してある。風・勾配
  どちらもこの1本のフック・1本のfetch関数を使い、軸ごとの分岐を持たない。

**向き指定UI**: `WindBearingSlider`をそのまま再利用した（新規コンポーネント無し）——
value/onChange/ariaLabelという既存propsが元々「向きだけ」を扱う汎用的な形（時刻は
コンポーネントの外[`DynamicLayerTimeSlider`]で完結する）。
`page.tsx`は風・勾配で単一の共有state`travelBearingDeg`を持ち、地図上の
`TravelBearingControl`1箇所からのみ`WindBearingSlider`をマウントする
（詳細は[docs/modules/frontend/page-composition.md](modules/frontend/page-composition.md)
「動的材料（風・勾配）の状態別表現契約」参照）。

**preprocess="abs"対応（改善計画T404の先送り分）**: T423での調査の結果、実装しないことを
最終決定した——absを使う軸は`gradient`のみで、`gradient`が参照する材料`gradient_percent`は
`tile_property_direction_dependent=True`（方向依存材料）でもあり、方向依存材料を含む軸は
`derive_ramp_inputs`がこの時点で`None`を返すよう既に設計されている。つまりabs対応を実装
しても`gradient`のkind="ramp"化には一切寄与しない（2つの独立した制約が両方ともこの軸を
弾く）——かつ`gradient`の地図表示は上記のとおりRedis経由のフィーチャー→値配信という別経路に
決着しており、そもそもramp（MVTタイル焼き込み）を必要としない。詳細は
[domain/axis_display.py](../backend/app/domain/axis_display.py)のモジュールdocstring参照。

**ルート確定後**（勾配）: T423時点では`routeStyleModes.ts`の旧`STATIC_MODES`が持つ固定の
`"gradient"`モードだったが、**改善計画T440（2026-08-30）でこの旧`STATIC_MODES`という
仕組み自体を撤去した**。以下、T440時点の設計を記す。

**T440（軸スタジオのデータを唯一の正としてルート結果の色分けを完全に駆動する）**:
T352〜T434の間、"wind"は`supports_route_coloring`経由で動的に生成される一方、
"gradient"/"road"/"difficulty"は撤去済みの`STATIC_MODES`という固定配列としてフロントに直書き
されたままだった（表示する/しないの判定・しきい値・ラベル・色のいずれも軸スタジオの
データを見ていなかった）。T440はこれを解消し、以下の設計へ全面的に作り直した:

- `AxisDefinition.shape`（`kind`/`preprocess`/`terms`、軸スタジオで軸を定義する時点で
  既に選ぶ既存データ）から、backendの`domain/dynamic_way_values.py: map_value_kind`
  （`shape.kind=="breakpoint_linear" and preprocess=="abs" and len(terms)==1`なら
  `signed_material`）が「符号付き値を直接読むべきか」を判定し、`GET /api/axis-catalog`の
  `map_value_kind`として配信する。frontendは判定を持たない。`axis.axis_id==="gradient"`という文字列
  比較は使わない——gradientの実データがたまたまこの条件を満たすだけで、条件を満たす軸が
  将来増えてもコード変更なしに同じ経路へ乗る。真の場合は`shape.terms[0].material`
  （gradientの場合`"gradient_percent"`、`RouteSegmentDetail`のフィールド名と一致する
  文字列）を直接読む。偽の場合（wind・surface_q等）は従来どおり
  `axis_difficulties[axis_id]`（abs差難易度0-100）を読む。
- `buildRangeSteppedMode`: 境界値配列（軸スタジオの`display_thresholds_override`、
  未設定時は経路ごとの既定値）の**長さがそのまま段階数を決める**汎用関数。ラベルは
  境界値の実際の数字から機械的に生成する（「易しい/普通/難しい」「下り/上り」のような
  固定語彙は使わない）。色は`bandColorsFor(kind, boundaries)`
  （HSL色空間の補間、符号付き材料は0を境に下り側・上り側で別の配色）で生成するため、
  固定の色配列を持たない。
- `AxisCatalogEntry`（`GET /api/axis-catalog`）へ`shape`・`display_thresholds_override`を
  追加した——「個別フィールドを都度追加するのではなく、軸スタジオで決められること全部を
  まとめて返す」方針（ユーザー指摘を受けた設計判断）。
- `road`という名前の専用モードは無くなり、`surface_q`が他の動的モードと同じ
  `${axis.label}の影響`という汎用ラベルで現れる。旧`road_surface_good`
  （route_generator側が表示する真偽値）と`surface_q`軸が読む材料`surface_good`
  （`material_catalog.py`の`surface_good`）は、どちらも`classify_osm_surface()`
  由来の同一材料で、`surface_q`軸の`true_value=0.0/false_value=80.0`という材料設計
  により、汎用の絶対値差難易度経路（abs差3段階相当）へそのまま乗せても実質2値
  （0か80）にしかならず表示は壊れない。
- `difficulty`（総合難易度）だけは、単一軸ではなく全軸の重み付き合成コスト（評価
  エンジンが出す合成スコアそのもの）を表示するモードで、特定のaxis_idに紐づかない
  ため軸スタジオと同期する対象にならない——ルート結果の色分けメニューにフロント側の
  固定要素として残る唯一の例外。
- `filterRouteStyleModesByPreference(modes, routePreference)`: `mode.id`が
  `routePreference`のキーと一致するモード（gradient/wind/surface_q等）は重み>0の
  ときだけ残す。`routePreference`にはルート**生成時**の値（`conditions.route_preference`、
  バックエンドが元々レスポンスへ含めていた値）を使う——ルート設定パネルの生きた
  （ライブな）重みをそのまま使うと、生成後に重みだけ変更（再生成せず）した場合に、
  表示中のルートの実際の評価内容とメニューがズレるため（`page.tsx`:
  `generatedRoutePreference`）。
- プレルート側（地図上チップのグルーピング）の同種のaxis_idハードコード分岐
  （`mapLayers.ts: isAxisStudioLayer`）も、`AxisDefinition.dedicated_way_value_layer`
  （この軸が専用のフィーチャー→値配信レイヤーを持つかの宣言）で判定する。
  `isAxisStudioLayer`は`mapOverlayGroupFor`という広く呼ばれる純粋関数の内部で使われる
  ため、ライブなaxis-catalogを動的注入する設計は採らず、`RAMP_AXES`/`AXIS_LABELS`と同じ
  「ビルド時静的axis-catalog.jsonからの片側import」パターン
  （`axisLayers.ts: DEDICATED_WAY_VALUE_AXES`）に揃えてある。

### 地図チップの最上位グルーピング（道路/環境/スポット）と一次/二次命名

> 経緯・教訓（T167の自動ON連動導入→T181/T214での撤去、T215のタッチスクロール不具合対応等）は
> [decisions/map-chip-primary-secondary-registry.md](records/decisions/map-chip-primary-secondary-registry.md)参照。

一次属性・二次軸の命名・材料の単一ソースは`domain/registry.py`/`registry_defaults.py`（T163）で、
`export_openapi.py`が`axis-catalog.json`へ書き出す。フロント側は
[frontend/src/components/Map/primaryAttributes.ts](../frontend/src/components/Map/primaryAttributes.ts)が
1次→2次・2次→1次の導出を片側importで行う（T164、T308で情報源を実行時APIへ更新。詳細は
上記T308節）。

**地図上チップ（`MapOverlayControls.tsx`）の最上位グルーピング**は改善計画T406（2026-08-30）で
「観測データ/推定指標（合成）/動的データ」（データの出自による3分類）から「道路/評価軸/環境/
スポット」（対象＝何についての情報かによる4分類）へ再編し
（[docs/records/tasks/T400.md](records/tasks/T400.md)「1. パネルの最上位グルーピング」節・
[docs/records/tasks/T406.md](records/tasks/T406.md)参照）、続く改善計画T418（2026-08-30）で「評価軸」チップ
自体を地図UIから撤去し「道路/環境/スポット」の3分類になった
（[docs/records/tasks/T418.md](records/tasks/T418.md)参照）。評価軸（`car_stress`等のramp軸・専用way値配信軸
[風・勾配]）は、道路・環境・スポットと違い**ルートの状態と常に結び付いた道具**（ルート生成前は
重み配分を検討する材料、生成後は結果を分析する材料）であり、ルートの有無に関係なく意味が
一定な「地図そのものの見え方」設定として常設チップに置くこと自体が目的と合っていなかった、
という判断による。評価軸の色分けは、ルート未確定時はルート設定パネル
（`RouteSettingsPanel.tsx`、下記）の軸ごとの行から、ルート確定後は「生成したルートの色分け」
（`routeStyleModes.ts`）から、それぞれ起動する。

`mapLayers.ts: mapOverlayGroupFor()`が既存の`category`/`dataNature`フィールドから機械的に
導出する（道路=`category==="roadCondition"`、環境=`category==="terrain"||"weather"`、
スポット=`category==="trafficSafety"||"amenity"`）。軸スタジオ由来のレイヤー
（`isAxisStudioLayer()`、`dataNature==="composite"`のramp軸・記述子の`axisStudioLayer`が
立つ専用way値配信軸）はcategory判定より先に除外され、地図上チップ・サイドバーのどちらにも一切現れない
（`MapOverlayControls.tsx: buildChipGroups`が単独チップへのフォールバックからも明示的に
除外する）。「道路」はT406時点は「評価軸」と幾何[線]を共有する排他ドメインだったが、T418で
評価軸チップ自体が撤去されたため単独ドメインになった（`mapOverlayExclusiveDomainFor()`が
返す`"line"|"area"|"point"`の3ドメイン、`page.tsx: handleLayerToggle`がONにする操作のとき
同じドメインの他レイヤーを自動でOFFにする——チップ本体のON/OFF＝`ChipButton`の`onTap`を
ラジオボタン化したもので、ⓘボタンの「表示する項目を選ぶ」設定パネル[下記]は対象外）。
「環境」（面）・「スポット」（点）はそれぞれ独立した排他ドメイン。ルート本体
（category未指定）・軸スタジオ由来のレイヤーはどの排他ドメインにも属さない——ただし軸
スタジオ由来のレイヤー同士は、同じ道路ジオメトリへ線を重ねて見にくくなることを防ぐという
排他ドメインの元々の目的に沿い、`page.tsx: handleLayerToggle`が地図上チップの3ドメインとは
独立に「軸スタジオ由来レイヤー同士は1つだけ選べる」という排他制御を維持する。

**最上位のグルーピングは`mapOverlayGroupFor`が単一ソース**で、道路/環境/スポットの3分類。
見出しは地図上チップと揃える（`MapLayerDataNature`[観測/推定/動的]で別立てにしない）。

道路/環境/スポットグループの地図チップはタイル状のマトリックス（▶=メンバー個々の凡例展開／
▼=グループ自体の縦積み展開、T169）。グループ見出しのⓘボタンから「表示する項目を選ぶ」
設定パネル（`MapOverlayControls.tsx`の`renderVisibilitySettings`）を開け、非表示に選んだ
メンバーのIDは`hiddenIds`（`${scope}:${id}`、scope="road"|"environment"|"spot"、T406で
旧"raw"|"composite"|"dynamic"から改名、T418で"axis"を撤去）へ記録し、対応レイヤーが表示中
（ON）だった場合は`toggleHidden`がその場でOFFにする（T181）。非表示IDのSetという設計
（表示IDのSetではなく）により、新規レイヤーは既定で全件表示のまま自動的に見える。グループ
本体の開閉（`GROUP_VISIBILITY_KEYS`）と`hiddenIds`は`useStoredState`でlocalStorage永続化
（T216）。個々の凡例展開は「今ちょっと確認のための」一時的なUI状態のため永続化の対象外。

1次「素材」レイヤー（道路種別/路面の合成・自転車インフラ・指定路線）は`line-offset`で道路に
並行する複数トラックへ分離（`ROAD_MATERIAL_TRACK_LAYER_IDS`、同時ONでも互いを覆い隠さない）、
2次（car_stress・ramp軸）はそれより太く半透明な「下敷き」として1次の下に重ねる（「梅・竹・松」）。
下敷き幅（`SECONDARY_AXIS_CASING_WIDTH`）は1次トラック数×オフセット間隔＋自身の太さから
計算式で導出する（設計原則2の「導出できる関係」拡張）。

一次属性の推定軸への連動ON/OFF（材料選択でレイヤーが自動ON等）は導入後に不整合が判明し撤去済み
（T167→T181/T214）。現状は推定軸タイル展開時に「材料: ○○」として関連する一次属性を常に
表示するのみで、自動ONはしない。トンネル（T217）・一方通行（T289）は評価軸に組み込まない
表示専用の一次属性として、他の観測レイヤーと同じ独立レイヤー構成（`PRIMARY_ATTRIBUTE_LAYER_IDS`）で
追加済み。

## 9. Road Graph移行

経緯・フェーズ別の詳細は [decisions/road-graph-migration.md](records/decisions/road-graph-migration.md) へ移動した。
現状の要点:

- `/api/routes/generate`はRoad Graph＋numbaでJITしたDijkstra/A*の単一構成（改善計画T247で既定化、改善計画T462でopenrouteservice委譲・切替設定自体を完全撤去、1章「ルーティングエンジンの切り替え対応」参照）
- OSMデータはPBF取込バッチ（`app/batch/import_pbf.py`）でPostGISへ事前取込済みの範囲を第一系統とし、Overpassフォールバックは改善計画T22で撤去済み（取込範囲外は空タイル/データ未整備扱い。docs/osm-pbf-import.md、[decisions/pre-static-attributes-gate.md](records/decisions/pre-static-attributes-gate.md)参照）
- 永続化層の構造（生OSM層／派生グラフ／属性／表示用MVTの4リポジトリ＋ファサード、トランザクション境界の規約）は`infrastructure/road_graph_repository.py`のdocstring参照
