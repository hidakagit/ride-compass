# RideCompass アーキテクチャ設計

このドキュメントは実装開始前に整理した技術選定・構成の記録。現状（Step 10完了時点）と将来計画を区別して記載する。

## 進捗ステータス

- ✅ Step 1: Next.js + MapLibre GL JS で地図表示（現在地 / 王子フォールバック）
- ✅ Step 2: FastAPI 疎通確認（`GET /health`）
- ✅ Step 3: openrouteservice接続（`POST /api/routes/preview`、単一区間のルート取得確認用の暫定エンドポイント）
- ✅ Step 4: 周回ルート生成（`POST /api/routes/generate`）。8方位×固定半径の候補地点をopenrouteserviceに並列問い合わせし、距離許容範囲でフィルタ。距離入力フォーム→候補リスト→地図ハイライト切り替えのUIまで実装
- ✅ Step 5: 獲得標高の計算。国土地理院（GSI）標高APIで各候補ルートをサンプリングし、獲得標高・最高/最低標高・最大勾配を算出。候補リストに獲得標高を表示
- ✅ Step 6: 天候表示。Open-Meteoで現在地の気温・風向風速・降水確率を取得・表示。`WeatherService`は「地点＋時刻」を受け取れる設計にし、将来ルート上の各点の推定通過時刻の天気を出す拡張に備える
- ✅ Step 7: 風評価。各候補ルートをサンプリングし、区間ごとの推定到達時刻の風（Step6の`WeatherService.get_conditions(point, at=...)`）と進行方位から`wind_score`（向かい風/追い風の度合い、符号付きm/s）を算出。候補リストに表示
- ✅ Step 8: 総合スコアリング。openrouteserviceの`extra_info=surface`（追加APIコール不要）から路面の舗装率`road_score`を算出し、距離の近さ・獲得標高・`wind_score`・`road_score`の4指標を候補集合内でmin-max正規化した上で`scoring.yaml`の重みで合成した`total_score`（0-100点）を算出。候補リストは`total_score`降順で表示
- ✅ Step 9: 候補ルートの難易度可視化。Step5-7-8で取得済みの標高・風・路面の生データ（区間ごとの詳細）を捨てずに`RouteCandidate.segments`として返し、地図上に区間ごとの難易度（絶対基準で0-100点）を色分けして重ね描き。区間クリックで到達予想時刻付きのポップアップ表示に対応
- ✅ UI再構成: 左サイドバー（操作パネル・候補一覧、折りたたみ可）＋右地図の2ペインレイアウトに変更。地図レイヤーを「変わらないデータ（標高・路面、全候補へ常時重ね描き可）」と「時間で変わるデータ（風、選択中候補にのみ動的表示）」に分離
- ✅ Step 10: 地域レイヤー（標高＝国土地理院 色別標高図のラスタタイル、路面＝自前生成のベクタタイル`GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf`）。Step5-9はいずれも「候補ルート沿い」に限定した標高・風・路面の取得だったのに対し、候補ルートの有無に関わらず**表示中の地図の範囲全体**に標高・OSM/Overpassの路面データを重ね描きできるようにした。「変わらないデータはタイル表示で統一する」方針のもと、標高は国土地理院の色別標高図タイルをそのまま重ね（バックエンドAPI不要）、路面はOverpassのデータをバックエンドでMVT（Mapbox Vector Tile）に変換し基礎地図タイルと同じファイルキャッシュで永続化して配信する方式にしており、**両者は排他ではなく同時に重ね表示できる**。あわせて地図タイル（OpenFreeMap）をバックエンド経由でプロキシ＋ファイルキャッシュする仕組み（`GET /api/basemap/{path}`, `POST /api/basemap/refresh`）も追加した
- ✅ フロントエンドUX改善: モバイル対応（[frontend/src/app/page.tsx](../frontend/src/app/page.tsx)・[frontend/src/hooks/useIsMobile.ts](../frontend/src/hooks/useIsMobile.ts)）とデバッグモード（[frontend/src/lib/debugLog.ts](../frontend/src/lib/debugLog.ts)等）を追加。画面幅640px以下（`useIsMobile`の`MOBILE_BREAKPOINT_PX`、`globals.css`の`@media`と一致させ、両者のズレをテストで自動検証）では左サイドバーを`position:fixed`のオーバーレイ式ドロワーに切り替え、背景タップ・Escapeキー・左スワイプで閉じられるようにした（`role="dialog"` `aria-modal`・背後ペインへの`inert`付与を含む）。あわせて、地図右下の「現在地に移動」ボタン（`useLocation.handleLocateMe`）でマウント時取得とは別に現在地を再取得できるようにし、失敗時はエラーメッセージを表示する。デバッグモード（サイドバーのチェックボックス、`localStorage`に永続化）をONにすると、地図のリクエスト/表示イベントと外部API呼び出しを画面下部の`DebugConsole`とブラウザコンソールに逐次ログする（`services/`配下の各fetchラッパー・`MapView.tsx`のmapイベントハンドラから`debugLog()`を呼ぶ形で計装）。UI確認用に`frontend/scripts/smoke-check.mjs`（Playwrightでトップページのスクリーンショットを撮る簡易スモークスクリプト）も追加した
- ⬜ Step 11以降: 未定（MVPの主要機能は一通り実装済み）
- ✅ Road Graph移行 Phase 1: Node/Directed Edgeという内部モデル（`domain/graph.py`）を新規導入。既存のルート探索（`RoutingService`/`RouteGenerator`、openrouteservice委譲）・地図表示（`RegionService`、路面MVTタイル）はいずれも無変更で、Road Graphは独立した並行構造として追加した（詳細は「Road Graph移行 Phase 1」参照）。Phase 0の現状調査結果は本ドキュメント末尾の「9. Road Graph移行（進行中）」を参照
- ✅ Road Graph移行 Phase 2: OSMのタグ語彙（`oneway`文字列等）の解釈を`domain/graph.py`から`domain/osm_adapter.py`（新規、OSM Adapter/Importer）へ分離。`build_road_graph`はデータソース非依存の`WaySpec`契約のみを受け取る形にした（詳細は「9. Road Graph移行（進行中）」参照）
- ✅ Road Graph移行 Phase 3: 標高・路面をRoad Attribute（`domain/attributes.py`のElevationAttribute/SurfaceAttribute）としてEdgeへ紐付ける仕組みを新規導入。既存のルート単位の評価（ElevationService/RouteGenerator）は無変更で、Edge単位の属性生成は独立した並行機能として追加した（詳細は「9. Road Graph移行（進行中）」参照）
- ✅ Road Graph移行 Phase 4: Road Attribute→Edge Costを算出するEvaluation Engine（`domain/evaluation.py`, `services/evaluation_service.py`）を新規導入。既存の`RouteScorer`/`domain/difficulty.py`（ルート単位の評価）には触れず、Edge単位の評価ロジックとして独立に追加した（詳細は「9. Road Graph移行（進行中）」参照）
- ✅ Road Graph移行 Phase 5: Evaluation Engineの重み（`RoutePreference`）を`route_preference.yaml`へ外部化。`scoring.yaml`/`load_scoring_weights`と同じパターンだが別ファイル・別関数として分離した（詳細は「9. Road Graph移行（進行中）」参照）
- ✅ Road Graph移行: 永続化（PostGIS）。SQLAlchemy+GeoAlchemy2でRoad Graph/Road AttributeをPostGISへ保存・読込できるようにし、GraphService/ElevationAttributeServiceにread-throughキャッシュとして配線した。実装当時は接続可能なPostGISが無く未検証だったが、**後日ローカルのPostgreSQL 18 + PostGIS 3.6に対する検証を完了**（「実PostGISでの動作検証（Phase 0）」参照）
- ✅ Road Graph移行: タイル境界依存の交差点分割不一致問題の根本修正。生のOSM Way/NodeデータとRoad Graph構築（交差点分割）を分離し、DB上の既知の生データ全体から近傍Wayを含めて都度計算する設計にした（詳細は「9. Road Graph移行（進行中）」参照）
- ✅ **Road Graphを実際のルーティングへ接続（完全移行）**: `/api/routes/generate`のルート生成をopenrouteservice委譲からRoad Graph + NetworkX（Dijkstra）ベースに全面置き換えた。Phase 6（Dynamic Data対応・風）もこの移行の一環として実装。実機検証で2つの重大な性能問題（8方位並列Overpass問い合わせがレート制限で全滅する、標高取得がRoad Graph全体に対して行われ非現実的に遅い）を発見・修正し、東京都内の実データで動作確認済み（詳細は「9. Road Graph移行（進行中）」参照）
- ✅ **ルーティングエンジンの切り替え対応**: Road Graphベースの自前ルーティング（経路探索そのもの）は将来拡張として並行開発を続けることとし、現状はマップの見える化・評価に必要な情報（標高・風・路面）の精査を優先するため、`/api/routes/generate`をopenrouteservice委譲でも動作するよう切り替え可能にした。完全移行で削除した`ElevationService`/`WindService`とopenrouteservice委譲版のルート生成ロジックを復元し、`config.py`の`routing_engine`設定（既定値`openrouteservice`）で`api/routes.py`の`get_route_generator`がどちらを注入するか切り替える（詳細は後述）
- ✅ **設計レビューと推奨アクション対応（ポート分割・評価値定義の統一・レート制限）**: エンジン切り替え導入直後に仕様書・実装全体の設計レビューを実施し、優先度上位4件を実装した。(1)周回生成戦略（8方位・距離フィルタ・スコアリング）を単一の`RouteGenerator`（`services/route_generator.py`）へ集約し、経路計算・評価を`LoopRoutingEngine`ポート（`OpenRouteServiceEngine`/`RoadGraphEngine`）として分離、(2)エンジン間で食い違っていた評価値の定義（road_scoreの不明路面の扱い・区間難易度の重みソース）を統一しレスポンスへ`engine`フィールドを追加、(3)最も高コストな`/api/routes/generate`へper-IPレート制限＋同時実行数ガードを追加、(4)`ORSClient`のコネクションをDI経由の共有方式へ統一（詳細は「ルーティングエンジンの切り替え対応」参照）
- ✅ **Renderデプロイの反映確認**: `GET /health`のレスポンスに`commit`（Renderが自動注入する`RENDER_GIT_COMMIT`）と`started_at`（プロセス起動時刻）を追加し、Render上に実際にデプロイされているコミットが手元のgit HEADと一致しているか外部から確認できるようにした（詳細は「Renderデプロイの反映確認」参照）
- ✅ **OSM PBF取込バッチ（Overpass依存解消のPhase 0-1）**: 利用するOSMデータをPBF（Geofabrik/BBBike抽出ファイル）からPostGISへ事前取込するバッチ（`backend/app/batch/import_pbf.py`、取込要素はプロファイルYAMLで宣言）を新規実装し、実PostGIS（ローカルPostgreSQL 18＋PostGIS 3.6）での永続化層の動作検証（Phase 0）と、東京都心の実データ取込→**Overpassへの問い合わせゼロでの`road_graph`ルート生成完走**（Phase 1 E2E）まで確認した。あわせて実データ規模で実用不能だった行単位UPSERT（レビュー指摘7）のバルク化・閉包クエリの空間検索化・`AsyncSession`同時使用バグの修正を実施（設計・詳細は docs/osm-pbf-import.md および9章「実PostGISでの動作検証（Phase 0）」「OSM PBF取込バッチ（Phase 1）」参照）
- ✅ **地域路面レイヤーのPostGIS化（Overpass依存解消のPhase 2）**: `RegionService`の路面ベクタタイル生成をPostGIS第一系統に変更した。表示タイル（z12-15）のz12祖先タイルが取込済みマークされていれば`osm_raw_ways.geom`の空間検索だけでMVTを生成し（Overpass問い合わせなし）、取込範囲外・DB障害時は`overpass_fallback_enabled`設定（既定true）に従いOverpassへフォールバックする。本番想定のSupabaseフリープラン（500MB）に対する容量予算300MBへ収めるため、未使用になっていたGINインデックス（28MB）を削除しDB実測284MBとした（詳細は9章「RegionServiceのPostGIS化（Phase 2）」参照）
- ✅ **Supabase取込とOverpass停止（Overpass依存解消のPhase 3）**: 本番想定DB＝Supabase（`.env`の`DATABASE_URL`）へPBF取込を実施し、`.env`で`ROAD_GRAPH_USE_REPOSITORY=true`＋`OVERPASS_FALLBACK_ENABLED=false`に設定した。**PostGISが唯一のOSMデータソースとなり、Overpassへの問い合わせは発生しない**（フォールバックのロジックはコードに併存させ、設定のみで無効化。ユーザー指示）。容量安全のため取込bboxはローカルの約7割（35.61,139.67-35.74,139.83）へ縮小し、Supabase実測196MB（生OSM層120MB＋ルート生成E2E由来の導出データ）で300MB予算内。`GraphService`にもフォールバック無効化フラグを追加した（詳細は9章「Supabase取込とOverpass停止（Phase 3）」参照）

---

## 1. 技術選定

| 領域 | 採用technology | 備考 |
|---|---|---|
| Frontend | Next.js (App Router) + TypeScript + MapLibre GL JS | React 19 / Next.js 16 |
| Backend | Python + FastAPI | pytest でロジックを単体テスト |
| DB | PostgreSQL + PostGIS | 既存のルート探索等（Step1-10）からは引き続き未接続。Road Graph移行の「永続化」で、SQLAlchemy+GeoAlchemy2経由の読み書きコードを追加（`infrastructure/database.py`, `road_graph_models.py`, `road_graph_repository.py`）。dev環境ではネイティブのPostgreSQL 18.6＋PostGIS 3.6.2（Windowsサービス）に対して実接続検証済み（9章「実PostGISでの動作検証（Phase 0）」参照） |
| ルーティングエンジン（周回ルート生成、`/api/routes/generate`） | **切り替え可能**（既定: openrouteservice API、`config.py`の`routing_engine`設定で`road_graph`にも切替可） | 周回生成戦略は単一の`RouteGenerator`（[backend/app/services/route_generator.py](../backend/app/services/route_generator.py)）が持ち、経路計算・評価だけを`LoopRoutingEngine`ポート経由で`OpenRouteServiceEngine`（[backend/app/services/openrouteservice_engine.py](../backend/app/services/openrouteservice_engine.py)、外部APIキー方式、Road Graph移行前の実装）または`RoadGraphEngine`（[backend/app/services/road_graph_engine.py](../backend/app/services/road_graph_engine.py)、自前ホスト・外部APIキー不要、`GraphService`・`EvaluationService`・`domain/routing.py`のNetworkX Dijkstraを使う）へ委譲する。ルーティング自体（自前の経路探索）は将来拡張として開発を続ける一方、現状はマップの見える化・評価に必要な情報の精査を優先するため既定値はopenrouteservice。レスポンスの`engine`フィールドでどちらが生成したかを識別できる。詳細は9章および「ルーティングエンジンの切り替え対応」参照 |
| ルーティングエンジン（単一区間確認、`/api/routes/preview`） | openrouteservice API（`cycling-road`プロファイル、外部APIキー方式） | Step3の疎通確認用エンドポイントは移行対象外のまま残置。`RoutingService`（[backend/app/services/routing_service.py](../backend/app/services/routing_service.py)）が`get_directions(waypoints: list[Coordinates])`を実装したクライアント（`ORSClient`）を受け取る形 |
| 地図タイル | OpenFreeMap（`https://tiles.openfreemap.org/styles/liberty`、APIキー不要） | `tile.openstreetmap.org` は bulk/非ブラウザアクセスをブロックするポリシーがあり不採用（後述）。Step10でバックエンド経由のプロキシ＋ファイルキャッシュ（`BasemapClient`）を追加 |
| 天候 | **Open-Meteo Forecast API**（APIキー不要） | `WeatherService`（[backend/app/services/weather_service.py](../backend/app/services/weather_service.py)）が`current`＋`hourly`をまとめて取得し、「地点＋時刻」で天候を引ける設計（後述） |
| 標高 | **国土地理院（GSI）標高API**（APIキー不要、日本国内限定） | `ElevationService`（[backend/app/services/elevation_service.py](../backend/app/services/elevation_service.py)）がルートを12点にサンプリングして問い合わせ、獲得標高・最高/最低標高・最大勾配を算出 |
| 標高（地域レイヤー） | **国土地理院 色別標高図**（ラスタタイル、`https://cyberjapandata.gsi.go.jp/xyz/relief/{z}/{x}/{y}.png`、APIキー不要） | `MapView.tsx`がMapLibreのraster sourceとして直接重ね描き。バックエンドAPIを介さない。候補ルートに紐づかない「地域全体」の標高表示用で、Step5の標高API（点ごとの数値取得）とは別用途 |
| 路面（地域レイヤー） | **Overpass API**（`overpass-api.de`公開インスタンス、APIキー不要）＋自前MVT生成 | `OverpassClient`（[backend/app/infrastructure/overpass_client.py](../backend/app/infrastructure/overpass_client.py)）が候補ルートに紐づかない「地域全体」のOSM道路データ（`highway`タグ）を取得。Step9までの路面評価（`road_score`）はopenrouteserviceの`extra_info=surface`を使っており、Overpassは地域レイヤー（Step10）専用。取得したデータは`mapbox-vector-tile`ライブラリ（[backend/app/infrastructure/vector_tile.py](../backend/app/infrastructure/vector_tile.py)）でMVTにエンコードし、MapLibreのvector sourceとして配信する |

### 地図タイルプロバイダに関する注記
当初 `tile.openstreetmap.org` のラスタタイルを想定していたが、bulk/プログラム的アクセスに対してブロックポリシー（`x-blocked` ヘッダーで拒否）があり、本番はもちろん開発環境でも安定して使えないことを実機検証で確認した。そのため、MapLibre GL JS向けにAPIキー無しで提供されている OpenFreeMap のベクタースタイルに切り替えた。本番運用時は利用規約を再確認し、必要に応じて専用プロバイダ（MapTiler等、APIキー方式）へ切り替えることを推奨する。

### フロントエンド実装上の注意（maplibre-gl バージョン固定）
`maplibre-gl` の最新メジャー（v6系）は、Web Worker のスクリプトURLを `new URL(`./${file}`, import.meta.url)` という動的テンプレートリテラルで解決する実装になっており、Next.js のバンドラ（Turbopack / Webpack のいずれも）がこれを静的解析できず、Workerが実際には空のページを読み込んでしまい、スタイル処理・タイル取得が永久に止まる（`isStyleLoaded()` が `true` にならない）現象を実機で確認した。回避策として `maplibre-gl` を `^5.24.0`（自己参照Blob方式のWorkerを使う、Next.js/Webpackとの互換実績が豊富なメジャーバージョン）に固定している。将来 v6系対応が改善された場合はアップグレードを検討する。

### バックエンド運用上の注意（Windows: `uvicorn --reload` の多重プロセス）
Windows環境では `uvicorn --reload` はリローダー親プロセスとワーカー子プロセス（`multiprocessing.spawn`）に分かれる。親プロセスだけを `taskkill` すると子プロセスが孤児化して同じポートに残り続け、古い設定（環境変数など）のまま応答し続けることがある。`.env` を編集後にAPIの挙動が変わらない場合は、`netstat -ano | findstr :8000` で該当ポートを握っている全PIDを確認し、それら全てを `taskkill /F /PID <PID>` で終了してから起動し直すこと。また `.env` の変更は `--reload` のファイル監視対象外のため、変更後は必ずプロセスの完全な再起動が必要。また、複数ファイルを短時間に連続編集すると `WatchFiles` の再読み込みが1回分しか発火せず、古いコードのまま動き続けることが実機で確認された（`404 Not Found` になる等）。挙動が古いままに見える場合は一度プロセスを完全に再起動すること。

### Renderデプロイの反映確認
Renderへのデプロイ（`git push`からのビルド完了）が実際にサービスへ反映されたかを、デプロイ操作をしたブラウザ以外（別端末・CLI・監視ツール等）からでも確認できるようにするため、バックエンド・フロントエンドの両方にデプロイ識別情報を返すエンドポイントを用意している。

- **`commit`**: RenderのWebサービス（gitリポジトリと連携したデプロイ）には`RENDER_GIT_COMMIT`（デプロイされたコミットのフルSHA）が自動的に環境変数として注入される（Render側の設定不要、`.env`にも書かない）。ローカル開発環境ではこの環境変数が無いため`null`になる
- **`started_at`**: プロセス起動時刻（ISO8601、モジュール読み込み時に一度だけ評価）。Renderはデプロイのたびにプロセスを再起動するため、直近デプロイのおおよその時刻としても使える（`commit`が変わっていなくても、再起動自体が起きたかどうかの確認に有用）
- **バックエンド**: `GET /health`（`backend/app/api/routes.py`、`backend/app/config.py`の`Settings.render_git_commit`、`backend/app/version.py`の`STARTED_AT`）。`test_health.py`でcommitのnull/反映両パターンを検証済み
- **フロントエンド**: `GET /api/version`（[frontend/src/app/api/version/route.ts](../frontend/src/app/api/version/route.ts)、新規のRoute Handler）。`process.env.RENDER_GIT_COMMIT`を直接読み、バックエンドと同じレスポンス形（`status`/`commit`/`started_at`）を返す。`export const dynamic = "force-dynamic"`でビルド時の静的最適化・キャッシュを無効化し、リクエストのたびにサーバーの現在の状態を返すことを保証している（`next build`のルート一覧で`ƒ /api/version`＝動的レンダリングになっていることを確認済み）。`route.test.ts`（Vitest）でcommitのnull/反映両パターン・started_atの妥当性を検証
- **確認方法**: `curl https://<render-backend>.onrender.com/health`と`curl https://<render-frontend>.onrender.com/api/version`（またはブラウザで直接開く）でそれぞれ`commit`を取得し、ローカルの`git rev-parse HEAD`と比較する。両方一致していれば最新版が反映されている

### 周回ルート生成のアルゴリズムと既知の制約（Step4）
`RouteGenerator`＋`OpenRouteServiceEngine`（[backend/app/services/route_generator.py](../backend/app/services/route_generator.py)・[backend/app/services/openrouteservice_engine.py](../backend/app/services/openrouteservice_engine.py)、Step4当時は`route_generator.py`という単一ファイルだったが「ルーティングエンジンの切り替え対応」で戦略とエンジンに分離した）は、8方位それぞれについて「方位θの方向に半径R」「方位θ+45°の方向に半径R」の2経由地点を`domain/geo.py`の`destination_point`（球面三角法）で計算し、`[現在地, 経由地A, 経由地B, 現在地]`をopenrouteservice Directions APIに1回のリクエストで渡す。半径Rは`distance_km / 3`という固定ヒューリスティック。8方位分は`asyncio.gather`で並列実行し、失敗した方位はスキップする。

実機検証（王子駅付近、15km/30km指定）では8方位すべてが成功し、目標距離に対して+10〜+16%程度（許容差±5km以内）に収まった。ただし適応的な半径調整は行っていないため、道路網の形状次第では大きくずれる方位が出る可能性がある。将来の改善点:
- 半径を反復調整して目標距離に近づける適応的探索
- `distance_tolerance_km`のデフォルト値を、実データが蓄積された段階で仕様書どおりの±2km程度まで狭める
- 8方位に加え、方位内で複数の経由地点パターンを試す（候補数を増やす）

### 標高計算のアルゴリズムと既知の制約（Step5）
`ElevationService`（[backend/app/services/elevation_service.py](../backend/app/services/elevation_service.py)）は、各ルートのGeoJSON LineStringを`domain/geo.py`の`sample_line_coordinates`で始点・終点を含む12点にサンプリングし、国土地理院の標高API（1リクエスト=1地点）に問い合わせる。獲得標高は連続区間の正の標高差の合計、最大勾配は`|標高差| / 水平距離`の最大値（%、水平距離は`haversine_distance_km`で算出）。標高が取得できない区間（海上・データ範囲外・通信エラー）は`None`として扱い、有効な点が2点未満なら標高関連フィールドはすべて`None`を返す（ルート自体は除外しない）。

**パフォーマンス上の落とし穴（実機で発見・修正済み）**: 当初 `ElevationClient` がリクエストごとに新規`httpx.AsyncClient`を生成しておりTLSハンドシェイクを毎回やり直していたため、15km生成（8候補×12点=最大96リクエスト）に**約57秒**かかっていた。`httpx.AsyncClient`をFastAPIの依存性注入（`yield`付き）で1リクエストあたり1つ生成して使い回す形に直したところ**約7秒**まで短縮した。あわせて、同時リクエスト数を制限する`asyncio.Semaphore`が`get_profile`呼び出しごとに新規生成されており、意図していた「サービス全体で最大5並列」ではなく実質「候補ごとに最大5並列」（合計で最大40並列）になっていた点も、`ElevationService.__init__`でSemaphoreを1つだけ生成する形に修正した。

### 標高キャッシュ（SQLite永続化）
`ElevationClient`（[backend/app/infrastructure/elevation_client.py](../backend/app/infrastructure/elevation_client.py)）は、緯度経度を小数点以下4桁（日本付近で誤差約11m）に丸めたキーで標高値をキャッシュする。標高はほぼ不変のデータのため、`cache_db.py`（[backend/app/infrastructure/cache_db.py](../backend/app/infrastructure/cache_db.py)）経由でSQLite（`backend/data/ridecompass_cache.db`）に永続化しており、プロセス再起動やコンテナ再作成をまたいで再利用される（当初はモジュールレベルの辞書によるプロセス内メモ化のみだったが、Step5の時点でSQLite永続化に置き換え済み）。8方位の候補ルートは同じ起点から発しているため、起点付近のサンプル点が重複しやすく、実機検証では同一条件の再生成で約1.5秒（全体の約20%）短縮した。キャッシュの読み書き（`cache_db._get_elevation_sync`/`_set_elevation_sync`）はSQLiteのロック競合等の例外を握りつぶし「未キャッシュ」またはno-op扱いにフォールバックするため、DB側の障害がルート生成全体を失敗させることはない。サイズ上限・退避（LRU等）は無い簡易実装であり、以下は将来課題として残す:
- GSIのDEMタイル（ラスタ）を範囲ごと一括取得し、ローカルグリッドで補間する方式への発展（API呼び出し自体をほぼゼロにできる）
- キャッシュサイズの上限・退避（LRU等）

### 天候取得の設計と「地点＋時刻」対応（Step6）
`WeatherClient`（[backend/app/infrastructure/weather_client.py](../backend/app/infrastructure/weather_client.py)）はOpen-Meteo Forecast APIから`current`（現在の気象）と`hourly`（`forecast_days=2`分の時間別予報：気温・風速・風向・降水確率）を**1回のリクエストでまとめて取得**することを実機確認済み。標高と同じ「範囲でまとめて取得してキャッシュ」の原則を適用しているが、気象データは時間で変化するため**TTL付き**（30分、緯度経度は標高より粗い精度で丸める）にしている点が標高キャッシュとの違い。

`WeatherService.get_conditions(point, at: datetime | None = None)`（[backend/app/services/weather_service.py](../backend/app/services/weather_service.py)）は、`at=None`なら`current`ブロックを返し、未来時刻を渡すと`hourly`配列から最も近い時刻のデータを検索して返す。**Step6のUIでは`at`を渡さず現在地の現在の天候のみ表示するが**、この時刻指定インターフェースにより、将来「ルート上の各サンプル点＋推定通過時刻（`RouteCandidate`の距離・所要時間から按分計算できる）」を渡して「2時間後にその地点は雨か」を判定する拡張が、サービス層の設計変更なしで追加できる（ユーザー要望への対応）。既知の制約: `at`が取得済みhourly範囲（当日+翌日）を超える場合、現状は最も近い時刻を返してしまう（範囲外チェック未実装）ため、`at`を実際に使う機能を追加する際にガードを入れる必要がある。

### 方位ラベルの共通化（Step6）
風向（Open-Meteoからは69°のような任意角度で返る）を8方位ラベルに変換する必要が生じたため、`route_generator.py`に8方位専用でハードコードされていた`DIRECTION_LABELS`辞書を廃止し、`domain/geo.py`の汎用関数`compass_label(bearing_deg: float) -> str`に統一した（周回ルート候補の方位ラベルも同じ関数を使う）。

### 風評価（`wind_score`）の設計（Step7）
Step6で`WeatherService.get_conditions(point, at: datetime | None = None)`を「地点＋時刻」対応にしておいたのは、まさにこのStep7のため。`WindService`（[backend/app/services/wind_service.py](../backend/app/services/wind_service.py)）は候補ルートのgeometryを12点サンプリング（`ElevationService`と同じ密度）し、区間ごとに以下を行う。

1. 起点からの累積距離 ÷ 仮定巡航速度（`ASSUMED_SPEED_KMH = 20.0`、現状固定値。将来ユーザー設定可能にする拡張ポイント）で推定到達時刻を計算
2. 区間の進行方位を`domain/geo.py`の`bearing_between(a, b)`（新規追加、2点間の初期方位角を球面三角法で求める。`destination_point`の逆関数に相当）で算出
3. `WeatherService.get_conditions(point, at=推定到達時刻)`を各区間の始点について並列取得（`ElevationService`と同じ`asyncio.Semaphore`パターン。天候はTTLキャッシュ済みのため近接点は追加リクエストなしでヒットする）
4. `domain/wind.py`の`WindCalculator.wind_penalty(wind_speed_ms, wind_direction_deg, travel_bearing_deg)`＝`風速 × cos(風向 − 走行方位)`で区間ごとのペナルティを算出（`wind_direction_deg`は気象学の慣習で「風が吹いてくる方向」。走行方位と一致＝正面からの向かい風＝`cos(0)=1`で最大、180度差＝追い風＝`cos(180°)=-1`、90度差＝横風＝`cos(90°)=0`で走行への影響なし。進行方向に平行な風成分のみが影響するという物理的に妥当なモデル）
5. 区間距離で加重平均した値を`wind_score`（符号付きm/s、正=正味向かい風、負=正味追い風）として`RouteCandidate`にマージ

天候取得に失敗した区間はスキップし、有効な区間が無い場合は`wind_score=None`（標高と同じ「取得失敗は握りつぶしてnull」方針）。既知の制約: 推定到達時刻の計算は「サーバーのローカル時刻＝Asia/Tokyoのその時刻」という簡易近似（Open-Meteoの`hourly`もタイムゾーン付きでなくAsia/Tokyoのnaiveなローカル時刻文字列を返すため整合はしている）。`wind_score`は正規化・重み付けされていない生の物理量で、Step8の`total_score`算出時にスコアリング設定（`scoring.yaml`想定）で重み付けする。

### 路面評価（`road_score`）と総合スコア（`total_score`）の設計（Step8）
道路特性（`road_weight`）はOSM/Overpassの実データ連携が将来課題として残っていたが、openrouteserviceの`extra_info`パラメータを調査した結果、`cycling-road`プロファイルが`extra_info: ["surface"]`に対応しており、Step4-7から既に呼んでいるルート取得リクエスト（`ORSClient.get_directions`）1回に相乗りする形で、追加APIコールなしに区間ごとの路面種別内訳（`properties.extras.surface.summary`、`{value, distance, amount}`の配列。`value`はOSMのsurfaceタグ相当の0-18の路面種別ID）が取得できることが分かった。これにより当初のスコアリング設計（距離・標高・風・道路の4要素）をStep8内でそのまま実装できた。

- **`road_score`の算出**: `RoutingService.get_route`が`feature["properties"]["extras"]["surface"]["summary"]`を`RouteSegment.surface_summary`としてパースし（無くても`None`で許容、必須フィールドの欠如とは扱いを分けている）、`route_generator._build_candidate`で候補生成と同時に`domain/road.py`の`paved_percent(surface_summary)`を呼んで`road_score`（走行しやすい舗装路面＝Paved/Asphalt/Concrete/Paving Stones＝ID 1,3,4,14の`amount`合計、0-100%）を算出する。標高・風とは異なり別サービス呼び出しが不要な同期計算。
- **正規化方式**: `domain/scoring.py`の`normalize_min_max(values, higher_is_better)`が、**その回の`generate_loops`呼び出しで生成された候補集合内**でmin-max正規化して0-100点に変換する。絶対的なしきい値（獲得標高200mが何点か等）を決め打ちできる実データが無いため、候補同士の相対比較として設計している（異なるリクエスト間の`total_score`は比較不可）。値が`None`の候補はそのメトリクスを除外し、全候補が同値の場合は中立の100点とする。
- **重みの方向**: 距離は目標との差が小さいほど高得点、獲得標高は小さいほど高得点（MVPでは「走りやすさ」優先の解釈。ヒルクライム志向のユーザー向けに反転する余地は将来課題）、`wind_score`は小さい（追い風寄り）ほど高得点、`road_score`は舗装率が高いほど高得点。
- **`RouteScorer`**（[backend/app/services/route_scorer.py](../backend/app/services/route_scorer.py)）: I/Oを行わない純粋なクラス。`score(candidates, target_distance_km)`が4指標を正規化し、`backend/app/scoring.yaml`の重み（`distance_weight: 0.30, elevation_weight: 0.15, wind_weight: 0.30, road_weight: 0.25`）で加重合成して`total_score`を`RouteCandidate`にマージする。一部の指標が`None`の候補は、取得できた指標の重みだけで再正規化して合成する（1つも指標が無い候補のみ`total_score=None`。ただし距離は`RouteCandidate.distance_km`が必須フィールドのため実運用では常に値が存在する）。
- **最終ソート順の変更**: `RouteGenerator.generate_loops`の返却順は、Step7までの「目標距離との近さ」から`total_score`降順（良い候補が先頭）に変更した。

既知の制約: `total_score`は同一リクエスト内の相対評価であり、異なる`distance_km`や別日時のリクエスト結果と比較する指標ではない。路面データはOSMの`surface`タグが付与されていない区間があると実態より低く出る可能性がある。

### 候補ルートの難易度可視化の設計（Step9）
`total_score`は候補集合内の相対評価のため、数値だけでは「具体的にどこが走りにくいのか」が分からない。ユーザーからの要望で、候補選択時に地図上へ標高・風・路面を時系列（区間ごとの推定到達時刻）も考慮したレイヤーとして重ね描きし、走破の易しい/難しい区間を色分けする機能を追加した。

- **データ取得方針**: Step5-7-8で候補ごとに12点サンプリングして取得していた標高・風・路面の生データは、集約値（`elevation_gain_m`等）だけを残して区間ごとの詳細を捨てていた。Step9はこれを**捨てずに`RouteCandidate.segments`として返す**だけで実現しており、追加のAPIコール（GSI/Open-Meteo/openrouteservice）は一切発生しない。
- **サンプル点の共有化**: `ElevationService.get_profile`と`WindService.get_wind_score`はそれぞれ独立に`sample_line_coordinates`を呼んでいたが、区間ごとの標高・風・路面を1つの配列としてインデックス整合させるため、`route_generator.py`が`sample_line_points(geometry, SAMPLE_COUNT)`（新規、`domain/geo.py`。座標だけでなく元geometry内でのインデックスも返す）で一度だけ点を取得し、両サービスに共有するようリファクタした。シグネチャも`get_profile(points)` / `get_wind_profile(points, start_time)`に変更（`geometry`ではなく点列を直接受け取る）。
- **路面の位置対応**: openrouteserviceの`extras.surface.values`（`[[start_idx, end_idx, surface_id], ...]`、geometry内のインデックス範囲で路面種別を示す）を`RouteSegment.surface_values`として新たに保持し、`domain/road.py`の`surface_id_at_index(index, surface_values)`で各サンプル点のインデックスから路面種別を求める。
- **難易度の算出（絶対基準）**: `domain/difficulty.py`が、Step8の相対正規化とは異なり**絶対基準**（一般的なロードバイク走行の目安）で0-100点化する。`gradient_difficulty`（0-3%易しい〜9%以上激坂の区分的線形）、`wind_difficulty`（向かい風0-8m/sで0→100、追い風・無風は0）、`road_difficulty`（舗装路0・非舗装80、`domain/road.py`の`GOOD_SURFACE_IDS`と基準を統一）、`composite_difficulty`（重み付き平均、`None`の指標は除外して残りの重みで再正規化、`RouteScorer`と同じ考え方）。重みはStep8の`scoring.yaml`から`distance_weight`を除いた`elevation_weight`/`wind_weight`/`road_weight`をそのまま流用し、スコアリングの優先度と可視化の強調点を一致させている。地図の色分けは「候補間の相対比較」ではなく「客観的にどこが大変か」を示す目的のため、Step8のような候補集合内正規化ではなく絶対基準を採用した。
- **`RouteSegmentDetail`**（`domain/route.py`、`RouteCandidate.segments`）: 区間の始点/終点座標・累積距離・推定到達時刻に加え、表示用の生値（`gradient_percent`, `wind_penalty`, `road_surface_good`）と正規化済みの`*_difficulty`（`elevation_difficulty`, `wind_difficulty`, `road_difficulty`, 総合の`difficulty`）を両方保持する。正規化済みの値をフロントに渡すことで、閾値ロジックをフロント側に複製せず、UIは常に「0-100→緑〜赤」の単一の色変換関数だけで済む。
- **フロントエンド**（当初実装）: 選択中候補に`segments`があれば区間ごとの色分けレイヤーを追加し、モード切替ボタン（総合難易度/標高/風/路面）で`line-color`を切り替える形にした。この設計は後述のUI再構成でレイヤー構成ごと見直している。

既知の制約: サンプリング密度（12点＝11区間、Step5-7と同じ）がそのまま地図の色分けの粒度になる。密度を上げると滑らかになるが、GSI/Open-Meteoへの問い合わせ数が比例して増え生成時間が伸びるトレードオフがあるため、既存の密度を踏襲している。

### UI再構成: サイドバー＋地図レイヤーの静的/動的分離
Step9の可視化はモード切替（総合難易度/標高/風/路面のいずれか1つ）＋選択中候補のみという設計だったが、ユーザーから「データの性質（時間で変わる/変わらない）によって持ち方・見せ方を分けたい」「左に操作パネル、右に地図」という要望を受け、UIを再構成した。

- **レイアウト**（[frontend/src/app/page.tsx](../frontend/src/app/page.tsx)）: `display:flex; height:100vh`のルート要素の下に、折りたたみ可能な`<aside>`（左サイドバー: タイトル・`BackendStatus`・`WeatherPanel`・`LocationControl`・`RouteForm`・`MapLayerControls`・`RouteList`）と`flex:1`の地図ペイン（`MapView`）を並べる。位置情報（現在地取得・手動入力）の状態は`MapView`から`page.tsx`（`Home`）に引き上げ、`MapView`は`location`等をpropsで受け取る「地図描画に専念する」薄いコンポーネントにした。
- **レイヤー構成の分離**（[frontend/src/components/Map/MapView.tsx](../frontend/src/components/Map/MapView.tsx)）: 4種類のMapLibreレイヤーを常設する構成に変更。
  1. `route-candidates-line`（既存）: 全候補のベース表示（amber未選択/blue選択）。`staticLayer==="none"`のときのみ表示。
  2. `route-static-segments-line`（新規）: **全候補**のセグメントを`elevation_difficulty`/`road_difficulty`で色分け。選択に関わらず常時利用可能（`MapLayerControls`のチェックボックスでON/OFF）。
  3. `route-selected-outline-line`（新規）: 選択中候補の全体ジオメトリを太め・低不透明度のハローで最背面に描画し、①②のどちらの表示中でも選択中候補を常時識別できるようにする。
  4. `route-detail-segments-line`（既存を単純化）: 選択中候補のみ`wind_difficulty`で色分け。「風の影響を表示」チェックがONかつ選択中候補にセグメントがある場合のみ表示。従来あった総合難易度/標高/風/路面のモード切替は廃止し、風のみに絞った（総合スコアはルート一覧の`total_score`表示で代替）。
  - ①②は`visibility`レイアウトプロパティで排他的に切り替え、③は常時、④は最前面。クリック/ホバーの`queryRenderedFeatures`は②④の両方を対象にし、②のポップアップには所属候補が分かるよう`direction_label`を付与している。
- **静的レイヤーのチェックボックス**（[frontend/src/components/MapLayerControls/MapLayerControls.tsx](../frontend/src/components/MapLayerControls/MapLayerControls.tsx)）: 「標高」「路面」はそれぞれ独立したON/OFFのチェックボックス（`showElevation`, `showRoad`）で制御する。当初は同じ線の色を奪い合うという理由で`staticLayer: "none" | "elevation" | "road"`の単一値による排他制御にしていたが、Step10で標高がラスタタイル表示に変わったことで色の競合が解消されたため、Step10改訂時に独立制御へ変更した（詳細は後述の「地域レイヤー」設計を参照）。
- **`isStyleLoaded()`起因の描画スキップ**: 実装時、地図初期化直後や候補選択直後にレイヤーが表示されない不具合が実機確認（Playwright）で見つかった。原因は、各描画関数が使っていた「`map.isStyleLoaded()`がfalseなら`map.once("load", ...)`で待つ」というガード。`isStyleLoaded()`は初期スタイル読み込み後もタイル読み込み中は一時的にfalseを返すが、MapLibreの`load`イベントは初回読み込み時に一度しか発火しない。そのため、候補選択でカメラが動いてタイル読み込み中に描画関数が呼ばれると、`isStyleLoaded()===false`と判定されて`once("load", ...)`を登録するが、その`load`はもう二度と来ず、描画が永久にスキップされていた。スタイルが一度でも読み込まれたかどうかをmapインスタンス自身にフラグとして記録する`runWhenStyleReady`ヘルパーに置き換えて解消した。

### 地域レイヤー（標高・路面の常時オーバーレイ）と地図タイルキャッシュの設計（Step10）
Step5-9で実装した標高・風・路面はいずれも「生成済みの候補ルート沿い」に限定した評価だった。ユーザーから「候補を出す前に、そもそもどのあたりが走りやすい地形・路面なのか地図で見たい」という要望を受け、候補ルートの有無に関わらず**表示中の地図の範囲全体（ビューポート）**に標高・路面を重ね描きする機能を追加した。

#### 標高オーバーレイ（国土地理院 色別標高図、ラスタタイル）
初期実装では、標高もリクエストされたbboxを固定間隔（約500m）のグリッド点に分解し、既存の`ElevationClient`（Step5と共通の国土地理院標高API）へ問い合わせて`circle`レイヤーの点として描画していた。しかし実際にブラウザで確認したところ「疎らな点では地形の起伏が直感的に分かりにくい」ことが分かり、標高の点取得・グリッド生成・専用APIエンドポイント（`GET /api/region/elevation`）は撤去し、代わりに国土地理院が公開する**色別標高図**（ラスタタイル、`https://cyberjapandata.gsi.go.jp/xyz/relief/{z}/{x}/{y}.png`、APIキー不要、zoom 5-15）をMapLibreの`raster`ソースとして`MapView.tsx`が直接重ね描きする方式に変更した。

- **バックエンドを介さない**: 地理院タイルはブラウザへの直接埋め込みを想定して公開されているため、基礎地図タイル（OpenFreeMap）のようなプロキシ・キャッシュ層を設けていない。地理院タイルのオリジン（`cyberjapandata.gsi.go.jp`）は基礎地図タイル用に分離したフロントエンドオリジン（`:3000`）・API呼び出し用のバックエンドオリジン（`:8000`）のいずれとも異なるため、ブラウザのオリジン単位の同時接続数上限が競合する心配もない。
- **レイヤー順序**: `ensureGsiReliefLayer`（`MapView.tsx`）は地図初期化直後（他のカスタムレイヤーより先）に一度だけソース/レイヤーを追加し、以降はvisibilityの切替のみで表示・非表示を行う。先に追加しておくことで、後から追加される路面・ルート系のレイヤーが必ずこのラスタの上に重なり、道路線やラベルが標高オーバーレイに隠れないようにしている。不透明度は0.55で、基礎地図の道路・ラベルが透けて見える程度に抑えている。
- **ビューポート制限は不要**: 標高グリッドAPI（撤去済み）はGSIの点別APIへの問い合わせ数を抑えるため`MAX_REGION_DIAGONAL_KM`のズーム制限を課していたが、ラスタタイルはズームレベルに応じてタイルが自動的に切り替わる標準的なXYZタイルのため、この種の制限は不要になった（後述の路面データのみ制限が残る）。

#### 路面データ：自前生成のベクタタイル（`GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf`）
初期実装では、路面もビューポートのbboxを`GET /api/region/road-surface`にそのまま渡し、Overpassデータを`RoadSurfaceWay`のGeoJSON線としてまとめて返す設計だった（キャッシュはビューポート単位ではなく`domain/region.py`の`snap_cells`が列挙する固定グリッドセル＝約3km四方単位、SQLiteの`road_surface_cache`テーブルに保存）。しかし「標高と同様、変わらないデータはタイル表示に統一したい」という要望を受け、標準的なXYZベクタタイル（MVT）として配信する方式に作り直した。

- **タイル範囲の算出**: `domain/region.py`の`tile_bounds_lonlat(z, x, y)`が、標準的なスライピータイル座標式（Web Mercator）からタイルが覆う緯度経度範囲を求める。以前の`snap_cells`（緯度経度の固定グリッドに独自に丸める方式）とは異なり、MapLibre自身が使うタイル座標系そのものなので、キャッシュの単位とMapLibreが要求するタイルが一対一に対応する。
- **MVTエンコード**: `RegionService.get_road_surface_tile(z, x, y)`（[backend/app/services/region_service.py](../backend/app/services/region_service.py)）が、そのタイル1枚分のbboxでOverpassに問い合わせ（1リクエストにつき1タイル、複数セルをまたいで集約する処理は不要になった）、`infrastructure/vector_tile.py`の`encode_road_surface_tile`でMVTにエンコードする。エンコードは`mapbox-vector-tile`ライブラリ（新規依存、`requirements.txt`に追加）を使い、緯度経度→Web Mercator→タイルローカル座標（0-4096、`TILE_EXTENT`）への変換は自前で行う（`y_coord_down=True`を指定し、ライブラリ側の自動フリップを止めて、MVT仕様通り「原点がタイル左上・y軸下向き」の座標をそのまま渡す）。Overpassの取得範囲をタイル境界でクリップしていないため、タイル境界をまたぐ道路はタイルローカル座標が0-4096の範囲をわずかに超えることがあるが、MVT仕様上は許容される値であり、MapLibre側の描画時クリップに委ねている（実機確認で問題なく描画されることを確認済み）。取得したOSMの`surface`タグは`domain/road.py`の`classify_osm_surface`（Step8の`paved_percent`とは別語彙・別関数だが「走行しやすい舗装路面かどうか」という考え方は統一）で舗装/未舗装/不明の3値に分類し、`surface_good`プロパティとしてMVTの地物に埋め込む。
- **永続化層**: 生成したタイル（PBFバイナリ）は、**基礎地図タイルと同じファイルキャッシュ**（`infrastructure/tile_cache.py`、`region/road-surface/{z}/{x}/{y}.pbf`というパスで保存）にキャッシュする。専用のSQLiteテーブル（旧`road_surface_cache`）は不要になり削除した。「変わらないデータを更新」ボタン（`POST /api/basemap/refresh`）を押すと基礎地図タイルと路面タイルの両方が一括でクリアされる（同じ`tile_cache.clear_all()`を共有しているため）。Overpass取得に失敗した場合はキャッシュに保存しない（次回リクエストで再取得を試みる）点はStep10当初の実装を踏襲している。
- **安全弁**: bbox対角距離の代わりに、`domain/region.py`の`ROAD_TILE_MIN_ZOOM = 12` / `ROAD_TILE_MAX_ZOOM = 15`でズーム範囲を制限する。`api/routes.py`のエンドポイントはこの範囲外のzを400で拒否する（直接APIを叩かれた場合の安全弁。通常はMapLibre自身がvector sourceの`minzoom`/`maxzoom`設定によりこの範囲外のタイルを要求しないため、二重の防御になる）。標高（ラスタタイル）にはこの制限を適用していない。

#### 地図タイルのバックエンド経由プロキシ＋キャッシュ
`BasemapClient`（[backend/app/infrastructure/basemap_client.py](../backend/app/infrastructure/basemap_client.py)）がOpenFreeMap（`tiles.openfreemap.org`）のスタイルJSON・TileJSON・スプライト・グリフ・タイルを透過的にプロキシしつつ、ファイルシステム（`backend/data/tile_cache/`、[backend/app/infrastructure/tile_cache.py](../backend/app/infrastructure/tile_cache.py)）にキャッシュする（`GET /api/basemap/{path:path}`）。

- **同一オリジン維持とURL書き換え**: レスポンスがJSON（スタイルJSON/TileJSON）の場合、内包するOpenFreeMap本体への絶対URLを、自分自身（`settings.basemap_public_base_url`、既定値`http://localhost:3000/api/basemap`）への絶対URLに書き換えてから返す。MapLibreは相対URLをスタイル自身の取得元ではなく**ページのオリジン**に対して解決してしまう（spriteURLに至っては相対URLを明示的に拒否する）ため、絶対URLへの書き換えが必須。書き換え先はバックエンド自身のURL（`:8000`）ではなく、フロントエンドのURL（`:3000`）であることに注意（後述の接続数上限の問題を避けるため）。
- **既知の制約（キャッシュとURL書き換えの整合性）**: URL書き換え後の内容をそのままファイルキャッシュするため、`basemap_public_base_url`の設定値を変更しても、既にキャッシュ済みのスタイルJSONには古いURLが埋め込まれたまま残り続ける（キャッシュ自体は書き換え元の設定値を記録していないため、値の変更を自動検知できない）。実際に開発中、デバッグのため一時的にバックエンドへ直接アクセスする設定に切り替えた際、キャッシュに`:8000`のURLが焼き付いたまま残り、設定を正しい値（`:3000`）に戻した後もキャッシュ経由で古いURLが返り続ける事象を確認した。「変わらないデータを更新」ボタン（`POST /api/basemap/refresh`、`tile_cache.clear_all()`）でキャッシュを全消去すれば解消する。
- **同時接続数上限との競合（実機確認で発見・回避済み）**: 当初、地図タイルもAPI呼び出しもバックエンドの同一オリジン（`:8000`）から直接取得する構成を試したところ、地図初期化時に発生する数十件のタイル/フォント/スプライトリクエストがブラウザのオリジン単位の同時接続数上限（HTTP/1.1で6本程度）を埋めてしまい、ルート生成等のAPI呼び出しが数十秒単位で詰まる現象を確認した。対策として、Next.jsの`rewrites()`（[frontend/next.config.ts](../frontend/next.config.ts)）で`/api/basemap/*`と`/api/region/road-surface-tiles/*`（路面ベクタタイル、Step10改訂で追加）の両方をバックエンドへプロキシし、ブラウザからは常にフロントエンドと同一オリジン（`:3000`）に見えるようにした。これにより「タイル群（`:3000`経由）」と「API呼び出し（`:8000`直接）」が別オリジン扱いになり、接続枠が競合しなくなる。**フロントエンド側は`MapView.tsx`の`MAP_STYLE`定数（相対パス`/api/basemap/styles/liberty`）でこのrewriteを経由する必要があり、デバッグ目的で一時的にバックエンドへの絶対URLに変更した場合は元に戻し忘れないよう注意**（実際に前回セッションで戻し忘れており、動作確認時に発見・修正した）。
- **Windowsでのパスフラット化**: OpenFreeMapのURL構造には`planet`（TileJSON本体）と`planet/<version>/{z}/{x}/{y}.pbf`（実タイル）のように、同じセグメントがファイルとディレクトリ接頭辞の両方として使われるケースがある。パスをそのままディレクトリ階層にミラーリングすると、Windowsでは「同名のファイルがあるためディレクトリを作成できない」というエラーで実際にクラッシュすることを実機確認したため、`tile_cache.py`はパスをSHA-256でハッシュ化しフラットなファイル名（`<hash>.bin` / `<hash>.meta`）で保存する。副次的にディレクトリトラバーサル対策にもなる。
- **イベントループのブロッキング回避**: `tile_cache`の読み書きは同期的なディスクI/O。基礎地図読み込み時は数十件のタイル/フォントリクエストが同時に来るため、`asyncio.to_thread`を介さず直接呼ぶとイベントループ全体をブロックし、同時に処理中の他のリクエスト（ルート生成等）が数十秒単位で詰まることを実機確認した。`BasemapClient.get`・`RegionService.get_road_surface_tile`はいずれも`tile_cache.get`/`set`を必ず`asyncio.to_thread`経由で呼ぶ。
- **ベクタタイルの取得はWeb Worker内で行われる（実機確認で発見・修正済み）**: MapLibreはラスタタイル（`Image`要素、メインスレッド）とベクタタイル（`fetch`、Web Worker内）でタイルの取得方法が異なる。ラスタタイルのURL（`MAP_STYLE`や地理院タイルのURL）は相対パス・絶対パスいずれもページのオリジンに対して解決されるが、ベクタタイルのURLをWorker内から相対パスのまま渡すと`Failed to construct 'Request': Failed to parse URL from ...`のエラーで取得自体が失敗することを実機確認した（Workerの実行コンテキストはページとは別のベースURL解決になるため）。そのため路面ベクタタイルのURLは`window.location.origin`を使って呼び出し時に明示的に絶対URL化している（[frontend/src/services/regionApi.ts](../frontend/src/services/regionApi.ts)の`roadSurfaceTileUrl()`）。`window`はクライアントサイドでのみ参照可能なため、モジュール読み込み時に評価される定数ではなく、呼び出し時に評価される関数として実装してある点に注意（Next.jsのクライアントコンポーネントも初回はサーバー側でレンダリングされるため、モジュールの最上位で`window`を参照するとSSR時にクラッシュする）。

#### フロントエンドの表示制御（`MapLayerControls.tsx`, `MapView.tsx`）
標高・路面は「変わらないデータ（表示中の地域全体）」として、選択中候補とは独立したチェックボックス（`showElevation`, `showRoad`）で制御する。標高がラスタタイル表示になったことで路面の線と色を奪い合わなくなったため、**両者は排他ではなく同時にON/OFFできる**（初期実装では同じ線の色を奪い合うため`staticLayer: "none" | "elevation" | "road"`の単一値で排他制御していたが、Step10改訂時に独立制御へ変更した）。標高・路面のいずれも、チェックボックスの切替時はレイヤーのvisibilityを切り替えるだけ（`setGsiReliefVisibility` / `setRoadSurfaceTileVisibility`）で、明示的なデータ取得コードは書いていない。路面がベクタタイルになったことで、Step10当初にあった「地図の`moveend`イベント（パン/ズーム終了、500msデバウンス）を検知してビューポートのbboxを`/api/region/road-surface`にfetchする」という独自ロジックは丸ごと不要になった。タイルの取得・キャッシュ・パン/ズームへの追随はすべてMapLibre自身が面倒を見るため、フロントエンドのコードはソースを一度登録するだけでよい（標高ラスタと全く同じ扱いになった）。「表示範囲が広すぎます」の案内も、bbox対角距離の計算ではなく、路面ベクタタイルの`minzoom`（`ROAD_TILE_MIN_ZOOM = 12`）と`map.getZoom()`を比較するだけの単純な判定（`updateRoadZoomHint`）に置き換わった。判定は`zoom`イベントとチェックボックスの切替の両方をトリガーに行う（標高はラスタタイルのためこの判定の対象外）。

既知の制約: Overpassの取得範囲をタイル境界でクリップしていないため、タイル境界をまたぐ道路のジオメトリはタイルローカル座標が0-4096の範囲をわずかに超えることがある（前述、実害はない）。未キャッシュのタイルはOverpassへの実問い合わせが必要なため、初回表示時（特に一度に複数タイルを要求する広いビューポート）は数秒〜十数秒かかることがある（公開Overpassインスタンスの応答速度に依存。Step10当初のセル単位キャッシュと同様の性質で、2回目以降はタイル単位でキャッシュが効くため高速になる）。

### ルーティングエンジンの切り替え対応（openrouteservice ⇄ Road Graph）
「Road Graphを実際のルーティングへ接続する移行（完全移行）」で`/api/routes/generate`をopenrouteservice委譲からRoad Graph + NetworkX（Dijkstra）ベースへ全面置き換えたが、Road Graphの経路探索自体（ルーティングエンジンとしての精度・速度）はまだ発展途上で、今後も継続して手を入れる将来拡張と位置付けている。一方で、標高・風・路面といった「評価に必要な情報」の取得方法や地図上の見える化は、経路探索エンジンがどちらであっても検証を進めたい。そのため、経路探索エンジンを設定で切り替えられるようにし、openrouteservice委譲（外部APIキーのみで動く、枯れた実装）を使いながら評価まわりの精査を進められるようにした。

- **戦略（共通）とエンジン（差し替え可能）の分離**: 当初は「2つの`generate_loops`実装を丸ごと並行して残す」形で切り替えを導入したが、8方位・半径ヒューリスティック・距離許容フィルタ・`RouteScorer`適用・ソートという周回生成戦略が二重化し、仕様書5章の将来拡張（適応的半径調整・候補地点選定の改善等）を2回ずつ実装することになるため、直後の設計レビュー（後述）でポート分割へリファクタリングした。現在の構造:
  - **`RouteGenerator`**（[backend/app/services/route_generator.py](../backend/app/services/route_generator.py)、戦略層・単一実装）: 経由地点の計算（`destination_point`）、8方位分の`trace_loop`並列実行、距離許容範囲フィルタ、`RouteScorer`によるtotal_score付与・ソートを持つ。エンジンには`LoopRoutingEngine`（Protocol）として`prepare`（リクエスト単位の共有準備）／`trace_loop`（1方位分の経路と距離）／`evaluate_loops`（**距離フィルタ通過後の候補だけ**への標高・風・路面評価）の3段階で委譲する。評価を後段に分離しているのは、棄却済み候補への外部API問い合わせ（GSI標高等）を避けるため（旧openrouteservice版が持っていたクォータ節約の挙動を両エンジン共通の戦略として保証する形。Road Graph版は従来フィルタ前に標高を取得していたが、この分割でフィルタ後のみになった）
  - **`OpenRouteServiceEngine`**（[backend/app/services/openrouteservice_engine.py](../backend/app/services/openrouteservice_engine.py)）: 経路はopenrouteservice Directions API（`RoutingService`/`ORSClient`）へ1方位1リクエストで委譲し、評価は復元した`ElevationService`（12点サンプリング）・`WindService`（区間ごとの推定到達時刻の風）で行う
  - **`RoadGraphEngine`**（[backend/app/services/road_graph_engine.py](../backend/app/services/road_graph_engine.py)）: `prepare`でRoad Graphを1回だけ取得しEdge Cost・NetworkXグラフ・起点スナップ・出発時点の風を構築、`trace_loop`でDijkstra探索、`evaluate_loops`で経路上のEdgeだけに標高を取得する（完全移行時の実機検証で判明した性能問題への対応をポート3段階へ対応付けた形）
- **`domain/geo.py`/`domain/road.py`のサンプリング・路面判定関数も復元**: `sample_indices`/`sample_line_coordinates`/`sample_line_points`（`geo.py`）と`GOOD_SURFACE_IDS`/`paved_percent`/`surface_id_at_index`/`is_good_surface`（`road.py`）は、完全移行で「Road Graphエンジンからは参照されなくなった」という理由で削除されていたが、`OpenRouteServiceEngine`が引き続き必要とするため復元した。Road Graphエンジンは代わりに`domain/road.py`の`classify_osm_surface`（OSMタグ基準）を使っており、この2系統の路面判定関数群（openrouteserviceの数値ID基準 / OSMタグ基準）は今後も両方残る（意味の統一は後述）。
- **設定と既定値**: `config.py`に`routing_engine: Literal["openrouteservice", "road_graph"]`を追加した（`.env`の`ROUTING_ENGINE`で上書き可）。現状はマップの見える化・評価情報の精査を優先するという方針に合わせ、既定値は`openrouteservice`にした（Road Graphエンジンを使うには`.env`で明示的に`road_graph`を指定する）。
- **DI（`api/routes.py`の`get_route_generator`）**: `settings.routing_engine`の値に応じてどちらのエンジンを構築し`RouteGenerator`へ渡すかを切り替える。両エンジン分の依存を`Depends`パラメータとして宣言しているため、FastAPIの制約上、実際には使わない側の依存（`httpx.AsyncClient`等、いずれもこの時点では実I/Oを伴わない軽量なオブジェクト）も毎リクエスト構築されるが、条件分岐に応じて一部の`Depends`だけを解決する簡便な方法が無いため単純さを優先した（コード上のコメント参照）。
- **`/api/routes/preview`は無変更**: Step3の疎通確認用エンドポイントは元々`RoutingService`/`ORSClient`を直接使っており、今回のエンジン切り替えの対象外（従来通りopenrouteserviceのみ）。

#### 設計レビュー（エンジン切り替え後）と対応した推奨アクション

エンジン切り替え導入直後に仕様書・実装・将来拡張の観点で設計レビューを実施し、優先度上位4件を実装した。

1. **評価値の定義統一＋`engine`フィールド（レビュー指摘H2）**: エンジン間で同じフィールド名の数値の意味が食い違っていた3点のうち2点を統一した。
   - **road_scoreの不明路面の扱い**: openrouteservice数値ID版`paved_percent`は不明を分母に含めて実質減点していたが、OSMタグ版（`classify_osm_surface`ベースの距離加重集計）と同じ「**不明は分母から除外**（不明≠悪い路面）、全区間不明ならNone」へ統一した。あわせて`is_good_surface`もID 0（Unknown）を`False`ではなく`None`（判定不能）へ変更し、両語彙の3値判定（良い/悪い/不明）の意味を揃えた（`domain/road.py`冒頭の「正準定義」コメント参照）
   - **区間難易度（`segments[].difficulty`）の合成重み**: openrouteservice版は`scoring.yaml`（候補集合内の相対評価用）を流用しており、`route_preference.yaml`を使うRoad Graph版と地図の色分けが食い違っていた。**両エンジンとも`route_preference.yaml`（Edge単位の絶対評価用の重み）へ統一**した。`scoring.yaml`はルート単位のtotal_score専用となり、役割の境界が明確になった（副次効果として、旧openrouteservice版がリクエストごとに行っていた`load_scoring_weights()`のファイルI/Oも除去された）
   - **wind_scoreの意味の違いは意図的に残す**: openrouteservice版は区間ごとの推定到達時刻の風（時間変化あり）、Road Graph版は出発時点の風の一様適用（探索中は到達時刻が未確定という制約）。将来の時間展開対応まで統一できないため、レスポンスに**`engine`フィールド**（`RouteGenerateResponse.engine`、フロントの`types/route.ts`にも追加しデバッグログに出力）を追加し、どちらの定義の数値かを識別可能にした
2. **`/api/routes/generate`のレート制限・同時実行ガード（レビュー指摘H3)**: 最も高コストなエンドポイント（openrouteservice: 外部APIクォータ消費 / road_graph: コールド時40〜70秒＋Overpass/GSI大量問い合わせ）が無防備だったため、既存の`check_rate_limit`によるper-IP上限（`GENERATE_RATE_LIMIT_PER_MINUTE = 10`/分）と、プロセス全体の同時実行数上限（`GENERATE_MAX_CONCURRENT = 2`、`asyncio.Semaphore`）を追加した。上限超過は待たせず429で即座に返す（ブラウザのリトライ・連打による外部サービスへの負荷の積み上げ防止）
3. **`ORSClient`のコネクション共有（レビュー指摘M1）**: 呼び出しごとに新規`httpx.AsyncClient`を生成していた（8方位の周回生成でTLSハンドシェイク8回。`ElevationClient`で実測57秒→7秒の差を生んだのと同じパターン）ため、他のクライアントと同様にDI（`get_routing_service`）が生成する共有コネクションのコンストラクタ注入へ統一した
4. **ポート分割（レビュー指摘H1）**: 前述の「戦略（共通）とエンジン（差し替え可能）の分離」

レビューで指摘されたが今回は見送った項目（既知の課題として記録）:
- **Road Graph版の`segments`肥大化（M3）**: Edge=区間のため4kmで150〜230区間、30km×8候補では数千区間になりペイロード・描画コストが嵩む。表示用の集約（約500m単位のビン化等）をAPI境界で行う案
- **周回品質（M4）**: 両エンジンとも「行きと帰りが同じ道」の往復型周回を防ぐ仕組みが無い。Road Graph版は「前の脚で使ったEdgeのコストを一時的に引き上げる」ことで自前修正でき、自前エンジンの差別化ポイントになりうる
- **`find_nearest_node`の距離上限が無い（M5）**: 起点が道路網から極端に遠い場合も最近傍Nodeへ黙ってスナップする
- **`RoutingService`へのORS固有パース漏れ（M2）**: `properties.extras.surface`のパースはORS固有のため、将来Valhalla等へ差し替える際は`ORSClient`側へ移す必要がある
- **`WeatherService.get_conditions(at=...)`のhourly範囲外ガード未実装（L3）**: openrouteservice版が既定へ戻ったことで実使用中の既知制約となった（20km/h想定の周回では実害はほぼ無い）

---

## 2. ディレクトリ構成

```
RideCompass/
  docs/
    architecture.md          ✅
  backend/
    app/
      main.py                ✅ FastAPI app, CORS
      config.py               ✅ pydantic-settings（.env読込、basemap_public_base_url含む）。routing_engine（"openrouteservice" | "road_graph"、既定openrouteservice）を「ルーティングエンジンの切り替え対応」で追加。render_git_commit（Render自動注入のRENDER_GIT_COMMIT、ローカルはnull）を「Renderデプロイの反映確認」で追加
      version.py               ✅ STARTED_AT（プロセス起動時刻、インポート時に一度だけ評価）。/healthのデプロイ確認用（「Renderデプロイの反映確認」で新規）
      api/
        routes.py             ✅ GET /health, POST /api/routes/preview, POST /api/routes/generate（per-IPレート制限＋同時実行数ガード付き、設計レビュー対応）, GET /api/weather, GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf, GET /api/basemap/{path}, POST /api/basemap/refresh
      domain/
        route.py               ✅ Coordinates, RouteSegment（surface_summary/surface_values含む）, RouteSegmentDetail（Step9）, RouteCandidate（標高・wind_score・road_score・total_score・segments含む）
        weather.py               ✅ WeatherConditions
        errors.py               ✅ RoutingError
        geo.py                   ✅ destination_point, haversine_distance_km, sample_indices, sample_line_coordinates, sample_line_points, compass_label, bearing_between
        road.py                   ✅ paved_percent（Step8）, surface_id_at_index, is_good_surface（Step9）, classify_osm_surface（Step10）
        scoring.py               ✅ normalize_min_max（Step8）
        difficulty.py             ✅ gradient_difficulty, wind_difficulty, road_difficulty, composite_difficulty（Step9）
        wind.py                   ✅ WindCalculator.wind_penalty（Step7）
        region.py                 ✅ BoundingBox, tile_bounds_lonlat, ROAD_TILE_MIN_ZOOM/MAX_ZOOM（Step10改訂。標高グリッド・snap_cells・bbox対角距離関連は撤去済み）。ROAD_GRAPH_TILE_ZOOM, tiles_covering_bbox（Road Graphのタイル単位キャッシュ用、新規）
        graph.py                    ✅ Node, DirectedEdge, RoadGraph, WaySpec, build_road_graph（Road Graph移行Phase 1、新規。Phase 2でOSMタグ解釈を分離しWaySpec契約に一本化。Phase 3でWaySpec.surfaceを追加）
        osm_adapter.py               ✅ OSM Way（tags辞書）→WaySpecへの変換（Road Graph移行Phase 2、新規。OSM Adapter/Importer）
        attributes.py                 ✅ ElevationAttribute, SurfaceAttribute, compute_elevation_attribute, build_surface_attributes（Road Graph移行Phase 3、新規）
        evaluation.py                  ✅ RoutePreference, EdgeCostResult, is_edge_allowed, compute_edge_cost（Road Graph移行Phase 4、新規。Evaluation Engine）。compute_wind_penaltyを「完全移行」（Phase 6・Dynamic Data対応）で追加
        routing.py                     ✅ build_networkx_graph, find_nearest_node, shortest_path_node_ids, path_to_edge_ids, concat_node_paths（「完全移行」で新規。Route Engine、NetworkXのDijkstraをラップ）
      services/
        routing_service.py     ✅ ORSClient等をラップ（waypointsリスト対応、surface extras/valuesのパース含む）。`/api/routes/preview`専用に加え、`routing_engine=="openrouteservice"`のときは`OpenRouteServiceEngine`からも使われる
        route_generator.py     ✅ `RouteGenerator`（周回生成戦略、エンジン非依存）＋`LoopRoutingEngine`（Protocol）＋`TracedLoop`。8方位・距離許容フィルタ・RouteScorer適用を単一実装で持ち、経路計算・評価はエンジンへ委譲（設計レビュー対応でポート分割）
        openrouteservice_engine.py ✅ `OpenRouteServiceEngine`。経路はRoutingService（openrouteservice委譲）、評価はElevationService+WindService（ルート単位12点サンプリング）で行うエンジン（Road Graph移行前の実装をポート化）
        road_graph_engine.py   ✅ `RoadGraphEngine`。Road Graph + Evaluation Engine + Route Engine（domain/routing.py）で経路・評価を行うエンジン（「完全移行」の実装をポート化。prepareでRoad Graph1回取得、evaluate_loopsで経路上Edgeのみ標高取得）
        elevation_service.py    ✅ ルートのGeoJSON LineStringを12点サンプリングし、GSI標高APIで獲得標高・最高/最低標高・最大勾配を算出（Step5。「完全移行」でRoad Graphエンジンからは不要になり一度削除、「ルーティングエンジンの切り替え対応」で`OpenRouteServiceEngine`用に復元）
        wind_service.py         ✅ ルートのサンプル点ごとに推定到達時刻の風からwind_penalty/wind_scoreを算出（Step7。elevation_service.pyと同じ経緯で削除→復元）
        weather_service.py     ✅ 「地点＋時刻」で天候を取得（Step6）。RoadGraphEngineからは出発時点・起点付近の風を取得する用途で（「完全移行」）、OpenRouteServiceEngineからはWindService経由で区間ごとの推定到達時刻の風を取得する用途で、それぞれ呼ばれる
        route_scorer.py            ✅ 4指標を正規化・重み付け合成しtotal_scoreを算出（Step8）。「完全移行」後もRoad Graphベースの候補に対しそのまま再利用
        region_service.py          ✅ get_road_surface_tile(z,x,y)で路面ベクタタイル(PBF)を生成・tile_cacheに永続化（Step10改訂。標高はGSIラスタタイルとしてフロントエンドが直接取得するためバックエンドを介さない）
        graph_service.py            ✅ GraphService.build_graph_for_bbox(bbox)でOverpass取得+Road Graph構築を統合（Road Graph移行Phase 1、新規。Phase 3でbuild_graph_with_surface_tags_for_bboxを追加）。「完全移行」でRouteGeneratorから実際に参照されるようになった
        elevation_attribute_service.py ✅ ElevationAttributeService.get_attributes_for_graph(graph)でEdge単位の標高属性（形状点をGSI APIへ問い合わせ）を算出（Road Graph移行Phase 3、新規）。「完全移行」でRouteGeneratorから、確定した経路上のEdgeだけに絞って呼ばれるようになった（性能上の理由、9章参照）
        evaluation_service.py           ✅ EvaluationService.evaluate_graph(graph, elevation_attributes, surface_attributes, wind=None)でEdge Costを算出（Road Graph移行Phase 4、新規。Phase 5でload_route_preference()を追加。「完全移行」でwind引数を追加しRouteGeneratorから参照されるようになった）
      infrastructure/
        ors_client.py           ✅ openrouteservice Directions API（cycling-road、複数経由地対応、extra_info=surface）
        elevation_client.py     ✅ 国土地理院標高API（共有コネクション＋緯度経度メモ化キャッシュ）
        weather_client.py       ✅ Open-Meteo Forecast API（current+hourlyをまとめて取得、TTLキャッシュ）
        overpass_client.py         ✅ Overpass API（地域全体のOSM道路データ取得、Step10。get_ways_and_nodesをRoad Graph移行Phase 1で追加、Way/Node IDを保持したトポロジー取得用）
        vector_tile.py               ✅ 路面データをMVT（Mapbox Vector Tile）にエンコード（Web Mercator投影、Step10改訂）
        cache_db.py                 ✅ SQLite永続キャッシュ（標高のみ、Step5用。路面セルのキャッシュはStep10改訂でtile_cache.pyに統合し削除）
        tile_cache.py               ✅ 地図タイル・路面ベクタタイル共通のファイルキャッシュ（パスをSHA-256でフラット化、Step10）
        basemap_client.py           ✅ OpenFreeMapタイル/スタイルJSONのプロキシ＋URL書き換え（Step10）
        rate_limiter.py              ✅ プロセス内メモリのみの固定窓レート制限（`check_rate_limit`）。認証なしで叩ける`/api/region/road-surface-tiles/*`（120req/min）・`/api/basemap/*`（300req/min）に`api/routes.py`から適用し、超過時は429を返す
        debug_log.py                  ✅ `log_external_call`（contextmanager）。外部API呼び出し・タイルキャッシュアクセスの開始/完了/失敗をカテゴリ単位でDEBUGログに出力する。`settings.debug_mode`（`main.py`のlogging設定）がFalseの間は実質無出力
        database.py                  ✅ SQLAlchemy非同期エンジン・セッションファクトリ（Road Graph移行「永続化」、新規。DB未接続でも既存機能に影響なし）
        road_graph_models.py         ✅ road_nodes/road_edges/elevation_attributes/surface_attributesのSQLAlchemy ORMモデル（PostGIS Geometry型、Road Graph移行「永続化」、新規）。OsmRawNodeRow/OsmRawWayRow（生OSMデータ、配列型+GINインデックス）を「根本修正」で追加
        road_graph_repository.py     ✅ RoadGraphRepository（bbox空間検索・UPSERT・ドメインモデル⇔ORM行変換・is_tile_cached/mark_tile_cached）（Road Graph移行「永続化」、新規。実PostGIS未検証）。save_raw_ways/get_way_specs_with_closureを「根本修正」で追加、save_graphにway_ids_to_replaceによるdelete-then-reinsertを追加
        valhalla_client.py        ⬜ 将来
        osm_repository.py            ⬜（road_graph_repository.pyが実質この役割を担う）
    tests/
      test_health.py          ✅ status/started_at（ISO8601）の検証、commitがRENDER_GIT_COMMIT未設定時null・設定時はその値を反映すること（「Renderデプロイの反映確認」で追加）
      test_geo.py             ✅ destination_point / haversine_distance_km / compass_label / bearing_between / sample_indices / sample_line_coordinates / sample_line_pointsの検証（後者3つは「完全移行」で一度撤去、「ルーティングエンジンの切り替え対応」でOpenRouteServiceEngine用に復元）
      test_routing_service.py ✅ ORSClientをモックした単体テスト（surface_summary/surface_valuesのパース含む）
      test_routes_preview.py  ✅ RoutingServiceをDIでモックしたAPIテスト
      test_route_generator.py ✅ RouteGenerator（周回生成戦略、エンジン非依存）の検証: 経由地点が起点始点/終点の周回を成すこと・距離許容フィルタ・失敗方位のスキップ・prepare失敗時の空返却・**評価が距離フィルタ通過候補だけに行われること**・total_scoreソート・engine_name公開（設計レビュー対応のポート分割で新規）
      test_openrouteservice_engine.py ✅ OpenRouteServiceEngineのエンドツーエンド検証（RouteGenerator経由）: 8方位生成・経路取得失敗時スキップ・標高/風プロファイルのマージ・total_score算出・segments構築・engine_name（旧test_route_generator.pyのopenrouteservice版から改組）
      test_road_graph_engine.py ✅ RoadGraphEngineのエンドツーエンド検証（RouteGenerator経由）: 起点を中心とした「車輪」状のRoad Graphフィクスチャによる8方位生成・許容範囲フィルタ・経路探索失敗時スキップ・標高/路面/風の集計・segments構築・Overpass問い合わせが1回のみ・標高取得がパス上のEdgeだけ＆距離フィルタ通過候補だけに絞られること（性能回帰テスト）・engine_name（旧test_route_generator.pyのRoad Graph版から改組）
      test_routing.py          ✅ build_networkx_graph（Hard Constraint除外）・find_nearest_node・shortest_path_node_ids（コスト最小経路・到達不能・始点=終点）・path_to_edge_ids・concat_node_pathsの検証（「完全移行」で新規）
      test_routes_generate.py ✅ get_route_generatorをDIでモックしたAPIテスト（engineフィールドの返却・per-IPレート制限の429・同時実行上限の429・settings.routing_engineによるエンジン選択の検証を設計レビュー対応で追加）
      test_elevation_service.py ✅ 標高プロファイル（獲得標高・最高/最低標高・最大勾配）の算出・欠損値・有効点2点未満時の扱いの検証（Step5。elevation_service.pyと同じ経緯で削除→復元）
      test_wind_service.py    ✅ 区間ごとの推定到達時刻の計算・wind_penalty算出・天候取得失敗時の扱いの検証（Step7。wind_service.pyと同じ経緯で削除→復元）
      test_elevation_client_cache.py ✅ 同一/近傍座標でのキャッシュ再利用・遠方座標での再取得
      test_weather_service.py ✅ 現在/指定時刻の天候取得、取得失敗時の扱い
      test_weather_client_cache.py ✅ TTL内キャッシュ再利用・失効後再取得・取得失敗時の扱い
      test_weather_route.py   ✅ /api/weatherのDIモックテスト
      test_wind.py             ✅ WindCalculator.wind_penaltyの向かい風/追い風/横風の検証（domain/wind.py自体は「完全移行」後もdomain/evaluation.py: compute_wind_penaltyから再利用）
      test_road.py             ✅ classify_osm_surface（OSMタグ基準）とpaved_percent/surface_id_at_index/is_good_surface（openrouteservice数値ID基準、「完全移行」で一度撤去→「ルーティングエンジンの切り替え対応」で復元）の検証。不明路面（ID 0）の「分母から除外・None判定」への統一（設計レビュー対応）の検証を含む
      test_scoring.py         ✅ normalize_min_maxの方向反転・全同値時の中立100点・None扱いの検証
      test_route_scorer.py    ✅ RouteScorer.scoreの正常系・指標欠損時の重み再正規化の検証
      test_difficulty.py      ✅ gradient/wind/road_difficultyの閾値・composite_difficultyの再正規化の検証
      test_region.py           ✅ tile_bounds_lonlatの検証（zoom0で全世界を覆う・隣接タイルの境界一致など、Step10改訂）。tiles_covering_bboxの検証（単一/複数タイル・世界端でのクランプ）を追加（Road Graphのタイル単位キャッシュ導入時、新規）
      test_region_service.py  ✅ RegionService.get_road_surface_tileのタイルキャッシュ利用/未キャッシュ時の挙動の検証（Step10改訂）
      test_region_routes.py   ✅ /api/region/road-surface-tiles/{z}/{x}/{y}.pbfのDIモックテスト・ズーム範囲外リクエストの400（Step10改訂）
      test_overpass_client.py ✅ OverpassClient.get_roadsの正常系・エラー時のNone返却（Step10）。get_ways_and_nodesの検証をRoad Graph移行Phase 1で追加
      test_graph.py            ✅ build_road_graphのWay分割（交差点/端点/形状点）・direction処理・内部ID/OSM IDの分離・距離計算の検証（Road Graph移行Phase 1、新規。Phase 2でWaySpec契約に合わせて更新）
      test_osm_adapter.py      ✅ osm_way_to_way_specのonewayタグ解釈（yes/-1/大文字小文字・空白/未知の値）・highway受け渡し・ノード数不足時の除外の検証（Road Graph移行Phase 2、新規。Phase 3でsurfaceタグ受け渡しの検証を追加）
      test_attributes.py       ✅ compute_elevation_attribute（登り/下り/混在/欠損値/有効点不足）・build_surface_attributes（osm_way_id対応/未知way/way_id無し）の検証（Road Graph移行Phase 3、新規）
      test_elevation_attribute_service.py ✅ ElevationAttributeService.get_attributes_for_graphのDIモックテスト（複数Edge独立性・欠損値・空グラフ）（Road Graph移行Phase 3、新規）
      test_evaluation.py       ✅ is_edge_allowed（Hard Constraint）・compute_edge_cost（平坦舗装/激坂未舗装の比較・属性欠損時のフォールバック・重み変更）の検証（Road Graph移行Phase 4、新規）。compute_wind_penalty（向かい風/追い風）・風統合の検証を「完全移行」（Phase 6）で追加
      test_evaluation_service.py ✅ EvaluationService.evaluate_graphのDIモックテスト（Hard Constraint除外・属性欠損・空グラフ・カスタムRoutePreference）（Road Graph移行Phase 4、新規。Phase 5でload_route_preference（既定パス/カスタムパス）・設定ファイル経由デフォルトの検証を追加）
      test_graph_service.py   ✅ GraphService.build_graph_for_bboxのDIモックテスト（Road Graph移行Phase 1、新規）。get_or_build_graph_with_attributesのタイル単位キャッシュ動作（単一/複数タイル・部分キャッシュ・一部タイル取得失敗）の検証を追加
      test_vector_tile.py      ✅ encode_road_surface_tileのデコード可能性・座標範囲・surface_goodプロパティ・2点未満のway除外の検証（Step10改訂）
      test_cache_db.py        ✅ 標高のSQLite永続キャッシュ読み書きの検証（Step5用。路面セルのテストはStep10改訂で撤去）
      test_basemap_client.py  ✅ BasemapClientのプロキシ・URL書き換え・キャッシュ利用の検証（Step10）
      test_basemap_routes.py  ✅ /api/basemap/{path}, /api/basemap/refreshのDIモックテスト（Step10）
      test_tile_cache.py      ✅ ファイルキャッシュのパスフラット化・パストラバーサル耐性の検証（Step10）
      test_rate_limiter.py     ✅ check_rate_limitの固定窓レート制限（上限内許可・超過拒否・クライアント単位の独立性・ウィンドウ経過後のリセット）の検証
    scoring.yaml               ✅ total_score算出とStep9難易度可視化で共有する重み設定（Step8）
    route_preference.yaml       ✅ Evaluation Engine（Edge Cost算出）の既定の重み設定（Road Graph移行Phase 5、新規。scoring.yamlとは対象が別のため分離）
    data/                       ✅ SQLite永続キャッシュ（ridecompass_cache.db、標高用）・地図タイル/路面ベクタタイル共通キャッシュ（tile_cache/）の保存先。gitignore対象（Step10）
    requirements.txt          ✅ mapbox-vector-tile追加（路面のMVTエンコード用、Step10改訂）。sqlalchemy/asyncpg/geoalchemy2/shapelyをRoad Graph移行「永続化」で、networkxを「完全移行」（Route Engine）で追加
    Dockerfile                ✅
    .env.example              ✅
    pytest.ini                ✅ asyncio_mode = auto
  frontend/
    next.config.ts               ✅ `/api/basemap/*`と`/api/region/road-surface-tiles/*`をバックエンドへプロキシするrewrites（同一オリジン維持、Step10・Step10改訂）
    src/
      app/
        page.tsx               ✅ 左サイドバー（折りたたみ可）＋右地図の2ペインレイアウト統括。位置情報state・天候取得もここで保持（UI再構成）
        layout.tsx              ✅
        api/version/route.ts    ✅ GET /api/version。RENDER_GIT_COMMIT/起動時刻を返すRoute Handler（force-dynamic）。バックエンドの/healthと対になるRenderデプロイ確認用（「Renderデプロイの反映確認」で新規）
      components/
        Map/MapView.tsx         ✅ 地図描画に専念（controlled props）。全候補ベース表示・選択中ハロー・動的レイヤー（風、選択中候補のみ）・地域レイヤー（標高＝GSIラスタタイル/路面＝自前ベクタタイル、いずれもMapLibreのtile sourceとして常設、同時表示可）の構成（Step4, Step9, UI再構成, Step10, Step10改訂）
        LocationControl/LocationControl.tsx ✅ 現在地表示・手動緯度経度入力フォーム（UI再構成、MapViewから分離）
        MapLayerControls/MapLayerControls.tsx ✅ 標高/路面（独立チェックボックス、同時表示可）・風（チェックボックス）・凡例・地域が広すぎる場合の案内・タイルキャッシュ更新ボタン（UI再構成, Step10）
        BackendStatus.tsx        ✅
        RouteForm/RouteForm.tsx  ✅ 距離入力＋生成ボタン（Step4）
        RouteList/RouteList.tsx  ✅ 候補一覧・選択・獲得標高・風評価・路面・総合スコア表示（Step4-5-7-8）
        WeatherPanel/WeatherPanel.tsx ✅ 気温・風向風速・降水確率表示（Step6）
        DebugPanel/DebugPanel.tsx    ✅ サイドバーのデバッグモードON/OFFチェックボックス（フロントエンドUX改善）
        DebugConsole/DebugConsole.tsx ✅ デバッグモードON時、地図イベント・外部API呼び出しログを画面下部に表示（フロントエンドUX改善）
      hooks/
        useIsMobile.ts             ✅ `MOBILE_BREAKPOINT_PX`=640。`globals.css`の`@media`とのズレをテストで自動検証（フロントエンドUX改善）
        useLocation.ts              ✅ 現在地取得・手動入力・現在地への再取得（`handleLocateMe`）の状態を集約（UI再構成でMapViewから分離）
        useDebugLog.ts               ✅ `useDebugEnabled()`。`lib/debugLog.ts`の`localStorage`永続化フラグをReact stateとして購読
        useIsomorphicLayoutEffect.ts  ✅ SSR時の警告回避用ヘルパー
      lib/
        debugLog.ts                ✅ デバッグモードのON/OFF状態（`localStorage`永続化）とログ出力本体。`services/`配下の各fetchラッパー・`MapView.tsx`から呼ばれる（フロントエンドUX改善）
      services/
        healthApi.ts             ✅
        routeApi.ts               ✅ previewRoute() / generateRoutes()
        weatherApi.ts             ✅ getCurrentWeather()
        regionApi.ts               ✅ roadSurfaceTileUrl() / ROAD_TILE_MIN_ZOOM/MAX_ZOOM / refreshBasemapCache()（Step10改訂。路面がタイル化されJSON型を持たなくなったため`types/region.ts`は削除済み）
      types/
        route.ts                  ✅（Coordinates, RouteSegment, RouteSegmentDetail, RouteCandidate等）
        weather.ts                 ✅（WeatherConditions）
  docker-compose.yml            ✅ (frontend/backend/postgres)
  .env.example                  ✅
  .gitignore                    ✅
```

未実装のドメイン/サービス/インフラ層は、実際に使うStepに到達してから作成する方針（中途半端な空スタブは作らない）。

---

## 3. Docker構成

`docker-compose.yml`（ルート直下）で以下3サービスを定義:

- `frontend`: Next.jsアプリ（ポート3000）
- `backend`: FastAPIアプリ（ポート8000）
- `postgres`: `postgis/postgis` イメージ（ポート5432）。Step1-2ではバックエンドから未接続だが、将来のルート/POIデータ保存に備えて土台として用意。

Valhallaは自前構築の複雑さ（OSM PBF抽出・タイルビルド）を踏まえ、Step3実装時に改めて「Docker Composeに含めるか」「外部サービス(openrouteservice)を使うか」を判断する。現時点では暫定的にopenrouteservice APIを使う想定のため、Compose上のコンテナ化は不要。

---

## 4. API設計

### 現状

```
GET /health   # commit/started_atはRenderへのデプロイ確認用（後述「Renderデプロイの反映確認」参照）
→ 200 { "status": "ok", "commit": "a1b2c3d4e5f6...", "started_at": "2026-08-14T10:00:00+00:00" }
  # commit: Renderが自動注入するRENDER_GIT_COMMIT（デプロイされたコミットのフルSHA）。
  #         ローカル開発環境では環境変数が無いためnull
  # started_at: プロセス起動時刻（UTC、ISO8601）。Renderはデプロイのたびにプロセスを
  #             再起動するため、直近デプロイのおおよその時刻としても使える

POST /api/routes/preview   # Step3: 単一区間のルート取得確認用（暫定エンドポイント。デバッグ・疎通確認用に残置）
Request:
{ "origin": {"latitude":35.7597,"longitude":139.7387}, "destination": {"latitude":35.71,"longitude":139.75} }
Response 200:
{ "distance_km": 6.85, "duration_minutes": 17.9, "geometry": { "type":"LineString","coordinates":[...] } }
Response 502（openrouteservice呼び出し失敗時）:
{ "detail": "ルート取得に失敗しました: ..." }

POST /api/routes/generate   # Step4: 周回ルート候補生成、Step5: 標高フィールド追加、Step7: wind_score追加、Step8: road_score/total_score追加
                            # ルーティングエンジンはsettings.routing_engineで切り替え（既定openrouteservice、9章参照）。
                            # レスポンスのengineフィールドでどちらのエンジンが生成したかを識別できる
                            # （wind_score等はエンジンによって算出の意味が異なるため。設計レビュー対応で追加）。
Request:
{ "latitude":35.7597, "longitude":139.7387, "distance_km":30, "distance_tolerance_km":5, "route_type":"loop" }
Response 200:
{
  "routes": [
    {
      "id":"route-090", "direction_label":"東", "distance_km":32.7,
      "elevation_gain_m":12.8, "min_elevation_m":1.1, "max_elevation_m":9.6, "max_gradient_percent":0.8,
      "wind_score":0.15, "road_score":76.2, "total_score":73.8,
      "segments": [
        {
          "start_latitude":35.7597, "start_longitude":139.7387,
          "end_latitude":35.7602, "end_longitude":139.7390,
          "cumulative_distance_km":0.0, "distance_km":1.16,
          "estimated_arrival_time":"2026-08-13T23:20:43",
          "gradient_percent":0.2, "wind_penalty":-0.83, "road_surface_good":true,
          "elevation_difficulty":2.0, "wind_difficulty":0.0, "road_difficulty":0.0, "difficulty":0.4
        }
        /* ...区間の数だけ続く（openrouteserviceエンジン: 12点サンプリング＝11区間前後 / road_graphエンジン: Edge数分） */
      ],
      "geometry": { "type":"LineString","coordinates":[...] }
    },
    ...（total_scoreが高い順、最大8件）
  ],
  "engine": "openrouteservice"
}
Response 429（per-IPで1分あたりGENERATE_RATE_LIMIT_PER_MINUTE=10回を超過、またはプロセス全体の
             同時実行数GENERATE_MAX_CONCURRENT=2に到達している場合。最も高コストなエンドポイントのため、
             外部サービス（openrouteservice/Overpass/GSI）への負荷の積み上げを防ぐ。設計レビュー対応で追加）:
{ "detail": "リクエストが多すぎます。しばらく待ってから再試行してください。" }

GET /api/weather?latitude=35.7597&longitude=139.7387   # Step6: 現在地の天候
Response 200:
{ "temperature_c":24.6, "wind_speed_ms":1.93, "wind_direction_deg":69.0, "wind_direction_label":"東", "precipitation_probability_percent":100.0, "observed_at":"2026-08-13T21:15" }
Response 502（Open-Meteo呼び出し失敗時）:
{ "detail": "天候情報の取得に失敗しました" }

GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf   # Step10改訂: 表示中ビューポート全体の路面データ（OSM/Overpassを自前でMVTに変換したベクタタイル）
Response 200（Content-Type: application/vnd.mapbox-vector-tile）: バイナリのMVT。レイヤー名`road_surface`、各地物（LineString）は`surface_good`プロパティ（true=舗装/false=未舗装/null=不明）を持つ
Response 400（zがROAD_TILE_MIN_ZOOM=12未満、またはROAD_TILE_MAX_ZOOM=15を超える場合）:
{ "detail": "対応していないズームレベルです。" }
Response 400（x/yがそのズームレベルで存在しうる範囲 `0 <= x,y < 2**z` を外れる場合。直接APIを叩かれた場合の安全弁で、通常はMapLibreが範囲外のタイルを要求しないため到達しない）:
{ "detail": "タイル座標が範囲外です。" }
Response 429（同一クライアントIPから1分あたり120リクエスト（`ROAD_TILE_RATE_LIMIT_PER_MINUTE`）を超えた場合。`infrastructure/rate_limiter.py`によるプロセス内メモリのみの固定窓レート制限）:
{ "detail": "リクエストが多すぎます。しばらく待ってから再試行してください。" }

GET /api/basemap/{path}   # Step10: OpenFreeMapの地図タイル/スタイルJSON/スプライト/グリフのプロキシ＋キャッシュ
Response 200: 上流（OpenFreeMap）のContent-Typeをそのまま転送
Response 502（上流取得失敗時）:
{ "detail": "地図タイルの取得に失敗しました" }
Response 429（同一クライアントIPから1分あたり300リクエスト（`BASEMAP_RATE_LIMIT_PER_MINUTE`）を超えた場合。road-surface-tilesと同じ`rate_limiter.py`を使うが上限値は別）:
{ "detail": "リクエストが多すぎます。しばらく待ってから再試行してください。" }

POST /api/basemap/refresh   # Step10: 地図タイルキャッシュを全消去（フロントの「変わらないデータを更新」ボタン）
Response 200:
{ "status": "ok" }
```

標高の地域オーバーレイ（Step10）はバックエンドAPIを持たない。フロントエンドが国土地理院の色別標高図タイル（`https://cyberjapandata.gsi.go.jp/xyz/relief/{z}/{x}/{y}.png`）をMapLibreのraster sourceとして直接取得するため、上記のようなJSON APIは存在しない（詳細は「標高オーバーレイ（国土地理院 色別標高図、ラスタタイル）」を参照）。

これで仕様書18章に記載の最終形のレスポンス項目（距離・標高・風・道路特性・総合スコア）に加え、区間ごとの詳細（`segments`）、候補ルートに紐づかない地域全体の標高・路面レイヤー（Step10）も出揃った。

---

## 5. ルート生成アルゴリズム（仕様書7-11章より）

### Step4-5-7-8-9で実装済み
1. 現在地を中心に、指定距離から逆算した探索半径を設定（`distance_km / 3`の固定ヒューリスティック）
2. 8方向に方角を分割し、各方向について球面三角法で2つの経由地点（θ方向・θ+45°方向、半径R）を計算
3. `[現在地, 経由地A, 経由地B, 現在地]` をopenrouteserviceに1回のリクエストで問い合わせ、周回ルートを取得（8方位分は並列実行）
4. 合計距離が許容範囲外の候補を除外し、目標距離に近い順にソート
5. 残った候補それぞれについて、国土地理院APIから獲得標高・最高/最低標高・最大勾配を算出（12点サンプリング、並列取得）
6. 残った候補それぞれについて、区間ごとの推定到達時刻（仮定巡航速度から逆算）の風を`WeatherService.get_conditions(point, at=...)`から取得し、進行方位との関係から`wind_score`を算出（12点サンプリング、並列取得）。詳細は「風評価（`wind_score`）の設計（Step7）」を参照
7. 各候補について、openrouteserviceの`extra_info=surface`から`road_score`（舗装率）を算出し、距離の近さ・獲得標高・`wind_score`・`road_score`を候補集合内でmin-max正規化した上で重み付け合成した`total_score`を算出、`total_score`降順に並べ替え。詳細は「路面評価（`road_score`）と総合スコア（`total_score`）の設計（Step8）」を参照
8. 5-6で使った標高・風の生データと、7で使った路面のインデックス範囲データから、区間ごとの詳細（`segments`）を構築し各候補にマージ。詳細は「候補ルートの難易度可視化の設計（Step9）」を参照

### 将来実装予定
9. 半径を適応的に調整して距離精度を高める（現在は固定ヒューリスティックのみ、上記「既知の制約」を参照）
10. 候補地点を道路網の実データ（Overpass/OSM等）から選ぶ、候補数を増やす（現在は幾何学的な計算のみ）。Step10でOverpass APIを導入したのは「候補ルートに紐づかない地域全体の路面表示」のためであり、この項目（周回ルート生成そのものの候補地点選定）とは目的が異なる点に注意。ただし同じ`OverpassClient`をルート生成側でも再利用できる可能性はある

風評価（`wind_score`）はStep7で実装済み。「風評価（`wind_score`）の設計（Step7）」を参照。序盤/中盤/終盤で風負荷の重みを変える拡張（帰路の向かい風を重視）は設計上考慮するが、MVPでは必須としない（現状は区間距離での単純な加重平均のみ）。

総合スコアリング（Step8）の重みは `scoring.yaml` で管理し、コードにハードコードしていない（実際の設定ファイルは[backend/app/scoring.yaml](../backend/app/scoring.yaml)）：

```yaml
scoring:
  distance_weight: 0.30
  elevation_weight: 0.15
  wind_weight: 0.30
  road_weight: 0.25
```

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
  start_latitude: number;
  start_longitude: number;
  end_latitude: number;
  end_longitude: number;
  cumulative_distance_km: number;
  distance_km: number;
  estimated_arrival_time: string | null;
  gradient_percent: number | null;
  wind_penalty: number | null;
  road_surface_good: boolean | null;
  elevation_difficulty: number | null;
  wind_difficulty: number | null;
  road_difficulty: number | null;
  difficulty: number | null;
}

interface RouteCandidate {
  id: string;
  direction_label: string;
  distance_km: number;
  geometry: GeoJSON.LineString;
  elevation_gain_m: number | null;
  min_elevation_m: number | null;
  max_elevation_m: number | null;
  max_gradient_percent: number | null;
  wind_score: number | null;
  road_score: number | null;
  total_score: number | null;
  segments: RouteSegmentDetail[] | null;
}

interface RouteGenerateRequest {
  latitude: number;
  longitude: number;
  distance_km: number;
  distance_tolerance_km: number;
  route_type: "loop";
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

バックエンド側は `domain/route.py`, `domain/weather.py` に同等のPydanticモデルを実装済み。フィールド名はキャメルケースではなくAPIレスポンスに合わせたスネークケースにしている（フロント⇔バックエンドで変換不要にするため）。標高系・`wind_score`・`road_score`・`total_score`・`segments`内の各フィールドは取得失敗時に`null`になりうるため、フロント側も`null`許容で扱う。

候補ルートに紐づかない地域全体の標高・路面レイヤー（Step10）は、いずれもタイル形式（標高はGSIのラスタタイル、路面は自前生成のMVT）で配信するため、Step5-9のようなJSONのレスポンスモデルを持たない。バックエンド側の`domain/region.py`にはタイル範囲計算に使う`BoundingBox`（Pydanticモデル）が残っているが、これはOverpassへの問い合わせに使う内部的な値であり、フロントエンドとの間でJSONとしてやり取りするものではない（フロント側に対応する型定義は無い）。

これで仕様書18章記載の`RouteCandidate`の項目、地図可視化用の`segments`（Step9）、および候補ルートに紐づかない地域全体の標高・路面レイヤー（Step10）が出揃った。

---

## 9. Road Graph移行（進行中）

「OSMを基礎としたRoad Graphを中心に据え、そのRoad Graphへ各種属性を後から追加できる構造へ段階的に移行する」ための移行仕様書に基づく作業。Phase 0（現状調査）→Phase 1（Road Graph導入）まで完了。既存機能（Step1-10）は無変更。

### Phase 0で判明した現状（移行前）

- **Node/Edgeの概念が存在しなかった**: 道路は(1)ORSが返すGeoJSON LineString（`RouteCandidate.geometry`）、(2)等間隔12点サンプリングの`RouteSegmentDetail`、(3)Overpass由来でID破棄済みの路面MVTタイル、という3つの無関係な形でのみ扱われていた
- **経路探索は完全にopenrouteserviceへ委譲**: `RoutingService`/`RouteGenerator`はORSをブラックボックスとして使い、標高・風・路面の評価は「経路が返ってきた後」の後付けスコアリング（`RouteScorer`, `domain/difficulty.py`）に過ぎず、Edge Costが探索そのものに影響する仕組みは無かった
- **永続的なedge_id体系が無い**: `OverpassClient.get_roads`はOSM Way/Node IDを取得直後に破棄していた
- PostGIS（docker-compose）は用意されているが、backendコードから未接続

### Phase 1で実施した内容

既存のルート探索・地図表示には一切手を加えず、Road Graphを**独立した並行構造**として追加した。

- **`backend/app/domain/graph.py`**（新規）: `Node`（node_id, latitude, longitude, osm_node_id）、`DirectedEdge`（edge_id, from_node_id, to_node_id, geometry, distance_m, osm_way_id, highway）、`RoadGraph`（graph_version, nodes, edges）のPydanticモデルと、純粋関数`build_road_graph(osm_ways, osm_nodes) -> RoadGraph`を実装。
  - 分割地点（Node化する条件）は「各Wayの端点」または「複数Way間・同一Way内で複数回参照されるノード」とし、それ以外の中間点はNode化せずEdgeの`geometry`内の形状点として保持する（仕様書7・9章）
  - `oneway`タグ（`yes`/`-1`等）に応じて片方向のみ、それ以外は双方向（A→B, B→A）のDirected Edgeを生成する（仕様書8章）
  - 内部ID（`node-N`, `edge-N`の連番）とOSM ID（`osm_node_id`, `osm_way_id`）を明確に分離し、OSM IDをそのまま内部IDとして使わない（仕様書11章：「osm_way_idを永続的な道路の識別子として扱わないこと」）
  - `graph_version`は過剰なバージョン管理機構を導入せず、生成時刻ベースの文字列のみ（仕様書12章の方針どおり最小実装）
- **`backend/app/infrastructure/overpass_client.py`**: 新規メソッド`get_ways_and_nodes(client, bbox)`を追加。既存の`get_roads`（`out geom`でジオメトリのみ取得、ID破棄、地域路面レイヤー表示専用）とは別に、Way ID・Node IDとノード参照関係（トポロジー）を保持したまま取得する（`(._;>;); out body;`）。既存の`get_roads`・その呼び出し元（`RegionService`）は無変更
- **`backend/app/services/graph_service.py`**（新規）: `GraphService.build_graph_for_bbox(bbox)`がOverpass取得とグラフ構築を統合する。**Phase 1時点では永続化を行わない**（呼び出しのたびに構築、DB/ファイルキャッシュ未実装）。既存の`RouteGenerator`・`RegionService`のどちらからも参照されない、完全に独立したサービス
- **テスト**: `test_graph.py`（Way分割・交差点検出・oneway処理・ID分離・距離計算の単体テスト）、`test_graph_service.py`、`test_overpass_client.py`への追加分。既存を含む全147件がグリーン

### Phase 1で意図的に行わなかったこと（スコープ外の判断）

移行仕様書のPhase 1完了条件には「既存ルート探索がRoad Graphを利用できる」との記載があるが、これは仕様書34章「探索アルゴリズムを独断で変更しない」・39章「新しい経路探索アルゴリズムの独自実装は対象外」と直接競合する（現在の探索はORSへの完全委譲であり、内部Road Graphを実際の経路探索に使わせるには探索エンジンそのものの置き換えが必要になる）。そのため今回は「Road Graphを生成できる」ことのみを完了条件とし、`route_generator.py`/`routing_service.py`への組み込みは行っていない。Road GraphをEvaluation Engine・Route Engineへ接続する判断は、Phase 3（Road Attributes）・Phase 4（Evaluation Engine分離）以降で改めて提案する。

同様に、永続化（SQLite/PostGIS/ファイルキャッシュ）もPhase 1では未実装。DB選定（既存の未使用PostGISを採用するか、`cache_db.py`/`tile_cache.py`と同様の軽量方式を踏襲するか）はユーザー判断が必要な事項として残している（仕様書38章）。

### Phase 2で実施した内容

Phase 1時点では、`domain/graph.py: build_road_graph`が交差点分割などの純粋なグラフ構築ロジックと、OSMの`oneway`タグ文字列（`"yes"`/`"-1"`等）の解釈という**OSM固有の語彙知識**を同居させてしまっていた。これはPhase 2の目的（「OSMのデータ形式が変更されても、Road Graph内部モデルへの影響を最小化する」、仕様書22章）に反するため分離した。

- **`backend/app/domain/graph.py`**: `build_road_graph`の入力契約として`WaySpec`（データソース非依存、`osm_way_id`, `node_ids`, `highway`, `direction: "forward"|"backward"|"both"`）を新設。`ONEWAY_FORWARD_ONLY`/`ONEWAY_BACKWARD_ONLY`（OSMタグの生値）と、それを解釈する分岐は`domain/graph.py`から削除した。`build_road_graph`はもはや`tags`辞書という概念自体を知らない
- **`backend/app/domain/osm_adapter.py`**（新規、OSM Adapter/Importerに相当）: `osm_way_to_way_spec(raw_way: dict) -> WaySpec | None`が、OSMの`oneway`タグ（`yes`/`-1`/`reverse`等、大文字小文字・前後空白を無視）を`WaySpec.direction`へ変換し、`highway`タグをそのまま渡す。ノードが2未満のwayは経路探索上の区間になり得ないためNoneを返す（Adapter側でフィルタする）
- **`backend/app/services/graph_service.py`**: `GraphService.build_graph_for_bbox`が`OverpassClient.get_ways_and_nodes` → `osm_adapter.osm_ways_to_way_specs` → `build_road_graph`の順で配線するよう更新。責務の流れが仕様書47章の「OSM → OSM Adapter/Importer → Road Graph」と一致する形になった
- 既存の`OverpassClient.get_roads`（地域路面レイヤー用、Step10）は無変更。ルート探索・地図表示への影響なし
- テスト: `test_graph.py`を`WaySpec`ベースに更新（`oneway`文字列ではなく`direction`を直接指定する形に変更）、`test_osm_adapter.py`を新規作成（oneway解釈・highway受け渡し・ノード数フィルタの検証）。既存を含む全157件がグリーン

このリファクタリングにより、将来Overpassのクエリ形式が変わったり、OSM以外のデータソース（PBF一括抽出等）へ切り替える場合も、変更は`osm_adapter.py`（と対応する新Adapter）に閉じ、`build_road_graph`のグラフ構築アルゴリズムは無変更で使えることが期待される。

### Phase 3で実施した内容

標高・路面をRoad Attribute（仕様書13-16章）としてEdgeへ紐付ける仕組みを追加した。既存のルート単位の評価（`ElevationService`, `RouteGenerator`, `domain/road.py`のORS/Overpass由来のroad_score）は無変更で、Edge単位の属性生成は独立した並行機能として追加している。

- **`backend/app/domain/attributes.py`**（新規）: `ElevationAttribute`（edge_id, start/end_elevation_m, elevation_gain_m/loss_m, average/max/min_grade, data_source, data_version, calculated_at）と`SurfaceAttribute`（edge_id, surface_type, confidence, data_source, data_version, calculated_at）のPydanticモデル。仕様書13章の方針どおりEdge本体（`domain/graph.py`）とは別モデルとして定義し、`surface_type`はOSMタグの生値のみを保持し評価用スコア（`surface_score`等）は含まない（正規化・スコア化はPhase 4以降のEvaluation Engineの責務、仕様書24-26章）
  - `compute_elevation_attribute(edge_id, points, elevations, data_source)`: Edgeの形状点列とその標高値から獲得標高・喪失標高・符号付き勾配（average/max/min_grade）を算出する純粋関数。既存の`ElevationService.get_profile`（ルート単位、12点サンプリング用）とは別実装（意図的に非共有。既存の動いているルート生成フローに影響を与えないため、詳細は「Phase 3で意図的に行わなかったこと」参照）
  - `build_surface_attributes(graph, surface_by_way_id, data_source)`: RoadGraphの各EdgeへOSMの`surface`タグ（`osm_way_id`経由で対応付け）を割り当てる純粋関数。1つのOSM Wayが複数Edgeに分割されている場合は同じsurface_typeを共有する
- **`backend/app/domain/graph.py`**: `WaySpec`に`surface: str | None`フィールドを追加（`highway`と同様、OSM Adapterが抽出する生タグ）。`DirectedEdge`へは持たせない（Edge本体とRoad Attributeの分離を維持するため、仕様書10・13章）
- **`backend/app/domain/osm_adapter.py`**: `osm_way_to_way_spec`が`tags.get("surface")`も`WaySpec.surface`へ抽出するよう拡張
- **`backend/app/services/elevation_attribute_service.py`**（新規）: `ElevationAttributeService.get_attributes_for_graph(graph)`が、RoadGraphの各Edgeの形状点（`geometry`）を国土地理院APIへ問い合わせ、Edgeごとの`ElevationAttribute`を算出する。既存の`ElevationClient`（緯度経度キャッシュ、SQLite永続化）をそのまま再利用するため、ルート生成側で既に問い合わせ済みの地点はキャッシュヒットする
- **`backend/app/services/graph_service.py`**: 新規メソッド`build_graph_with_surface_tags_for_bbox(bbox)`を追加。Road Graph構築に使ったのと同じOverpass取得結果（1回のみ）から`RoadGraph`と`dict[osm_way_id, surface]`を同時に返す（Surface Attribute生成のために再度Overpassへ問い合わせることを避けるため）。既存の`build_graph_for_bbox`は無変更（内部実装のみ共通化）
- テスト: `test_attributes.py`（登り/下り/混在勾配・欠損値・osm_way_id対応の検証）、`test_elevation_attribute_service.py`（DIモック）を新規作成。`test_osm_adapter.py`・`test_graph_service.py`に追加分。既存を含む全173件がグリーン

### Phase 3で意図的に行わなかったこと（スコープ外の判断）

- **標高計算ロジックを既存`ElevationService`と共有しなかった**: `ElevationService.get_profile`はルート単位・12点サンプリングという既存の使われ方に最適化されており、獲得標高（gain）のみを返し喪失標高（loss）や符号付き勾配（min/max_grade）を持たない。これをEdge単位の要件に合わせて拡張・共有化することも検討したが、Step5-9から動いている既存ルート生成フローに影響を与えるリスクがあるため見送り、`compute_elevation_attribute`として独立した実装にした（約15行の計算ロジックの重複だが、既存機能への影響ゼロを優先）。将来的に共通化する場合は、まず`ElevationService`側のテストが厚く保たれていることを確認してから検討する
- **正規化・スコア化（surface_score等）は実装しなかった**: 仕様書24-26章のRaw AttributeとScoreの分離方針に従い、Phase 3は「属性の導入」までに留め、スコア化はPhase 4（Evaluation Engine分離）以降で改めて設計する
- **交通・自転車インフラ・信号密度の属性は追加しなかった**: 現時点でこれらのデータソースが存在しない（仕様書39章は新規データソース連携を今回のスコープ外としていないが、既存データの整理を優先する仕様書Phase 3の方針「新機能を大量に追加することよりも、既存データをRoad Graph中心に整理することを優先する」に従い、既存の標高・路面のみを対象とした）
- **APIエンドポイントは追加しなかった**: `GraphService`同様、Phase 3の属性生成機能もAPIやUIには未接続（内部的に呼び出し・テスト可能な状態に留めている）
- **永続化は引き続き未実装**: 属性もRoad Graphと同様、呼び出しのたびに計算する設計。DB選定（PostGIS採用か、軽量方式継続か）は依然ユーザー判断待ち

### Phase 4で実施した内容

Phase 4着手前に「Evaluation Engineを何に対して作るか」という設計判断が生じたため、ユーザーに確認した。選択肢は(a) Phase1-3で作ったRoad Graph/Road Attribute側に新設する、(b) 既存の`RouteScorer`/`domain/difficulty.py`（route_generator.py内、ルート単位）を独立モジュールとして抽出する、(c)両方、の3案を提示し、(a)（Road Graph側への新設、既存のライブなルート生成コードには触れない）を採用した。

- **`backend/app/domain/evaluation.py`**（新規、Evaluation Engine本体）:
  - `RoutePreference`（`elevation_weight`, `road_weight`）: 仕様書27章のRoute Preference。現時点で実装済みのRoad Attribute（標高・路面）のみを対象とし、交通・自転車インフラ・信号等、未実装の属性用の重みは追加していない。重みのYAML外部化は仕様書のPhase分割どおりPhase 5の作業として明示的に見送った（デフォルト値を持つPydanticモデルとしてのみ用意し、呼び出し元が差し替え可能な構造にした）
  - `is_edge_allowed(edge)`: Hard Constraint（仕様書29章）。`highway`タグが`motorway`/`motorway_link`/`trunk`/`trunk_link`のEdgeを自転車通行不可として除外する。Phase 1から`DirectedEdge.highway`が既に保持されていたため、新たなデータソースなしで実装できた
  - `compute_edge_cost(edge, elevation_attribute, surface_attribute, preference)`: Road Attributeから Edge Costを算出する。**Score部分は新しい正規化方式を発明せず、既存の`domain/difficulty.py`（`gradient_difficulty`, `road_difficulty`, `composite_difficulty`。Step9で地図の難易度レイヤー用に導入済み、0-100・値が大きいほど走りにくい絶対基準）をそのまま再利用した**。Cost自体は「difficulty(0-100)を距離への乗算ペナルティ（1.0〜2.0倍）に変換する」という初期実装で、仕様書31章の方針どおり将来別方式に差し替え可能な独立した関数にしてある
- **`backend/app/services/evaluation_service.py`**（新規）: `EvaluationService.evaluate_graph(graph, elevation_attributes, surface_attributes)`がRoadGraphの全Edgeに対し`compute_edge_cost`を適用する。I/Oを行わない点は既存の`RouteScorer`（`services/route_scorer.py`、docstringに「I/Oを行わない純粋なクラス」と明記）と同じ位置づけで、この既存の設計精神を踏襲した
- Edge Costは仕様書32章の方針どおりRoad Graphへ恒久保存しない（`EvaluationService`の戻り値としてのみ存在する使い捨てのdict）
- テスト: `test_evaluation.py`（Hard Constraint・平坦舗装と激坂未舗装の比較・属性欠損時のフォールバック・重み変更）、`test_evaluation_service.py`（DIモック）を新規作成。既存を含む全185件がグリーン

### Phase 5で実施した内容

Phase 4で導入した`RoutePreference`（重み）はPydanticモデルとしてのみ存在し、デフォルト値（0.5/0.5）がコードに埋め込まれていた。Phase 5でこれを設定ファイルへ外部化した。

- **`backend/app/route_preference.yaml`**（新規）: `route_preference.elevation_weight`/`road_weight`。既存の`scoring.yaml`（ルート単位・candidate集合内の相対評価、`RouteScorer`が使う4指標）とは対象が異なる別設定のため、Phase 4完了時点の引き継ぎ事項で検討課題としていた「共用するか分離するか」は**分離**を選択した。同じ「重み」という概念でも、一方はルート候補同士の相対比較（min-max正規化）、もう一方は単体のEdgeに対する絶対評価という異なる意味を持つため、混同を避けるため
- **`backend/app/services/evaluation_service.py`**: `load_route_preference(path: Path = ROUTE_PREFERENCE_CONFIG_PATH) -> RoutePreference`を追加（`route_scorer.py`の`load_scoring_weights`と同じI/Oパターン、YAML読み込みという性質上services層に配置）。`EvaluationService.__init__`のデフォルト値を、ハードコードされた`RoutePreference()`から`load_route_preference()`に置き換えた。`preference`引数を明示的に渡すこれまでの呼び出し方（テスト等）には影響しない
- 複数プロファイル（快適性重視/トレーニング重視等、仕様書27・45章）は今回実装しない（仕様書Phase 5の方針「UIから変更する必要は今回必須ではない。まずは内部的に変更可能な構造を作る」に従う）。`load_route_preference`が`path`引数を取る構造にしてあるため、将来的に`route_preference_comfort.yaml`等を追加してパスを切り替えるだけで対応でき、コード変更は不要という設計にしてある
- テスト: `load_route_preference`の既定パス・カスタムパス読み込み、`EvaluationService()`のデフォルトが設定ファイル経由になったことの検証を追加。既存を含む全188件がグリーン

### Road Graph・Road Attributeの永続化（PostGIS）

Phase 1-5完了時点の引き継ぎ事項だった「永続化方式の決定」について、ユーザーの意思決定によりPostGISを採用した。**このdev環境にはDocker/PostgreSQLが無く、実際のPostGISに接続しての動作確認ができていない**ことをユーザーに明示した上で、コード実装のみを先に進めることで合意して着手した（後述「未検証の範囲」を参照）。

#### 前提として必要になった修正: ID安定化

永続化キャッシュが機能するには、同じ現実の交差点・道路区間には常に同じ`node_id`/`edge_id`が振られる必要がある。しかしPhase 1時点の実装は`node_id`/`edge_id`をビルド呼び出しごとにリセットされる連番（`node-1`, `edge-1`...）で採番しており、同じ地域を2回ビルドしても内部IDが一致しない状態だった。これは永続化を実装する前提として`domain/graph.py`を修正した。

- `node_id`は`osm_node_id`から決定論的に導出（`osm-node-<id>`）
- `edge_id`は`osm_way_id`＋Way内でのセグメント順序＋方向から決定論的に導出（`way-<osm_way_id>-seg<n>-fwd/bwd`）
- 仕様書11章の「osm_way_idを永続的な道路の識別子として扱わないこと」は維持（内部IDはOSM IDの生値そのものではなく別表現にしている）
- 既存テスト（`node_id != str(osm_node_id)`等の「内部IDはOSM IDと別物」という検証）に変更なく通ることを確認。新たに「同一入力から複数回ビルドしても同じID集合になること」を検証するテストを追加

#### 実装内容

- **技術選定**: SQLAlchemy 2.0（非同期、asyncpgドライバ）+ GeoAlchemy2（PostGISのGeometry型）+ Shapely（Python側のジオメトリ操作）。このプロジェクトで初めてのORM/リレーショナルDB利用（既存のcache_db.pyはSQLiteの素の`sqlite3`モジュール、tile_cache.pyはファイルキャッシュで、いずれもリレーショナルではない）
- **マイグレーションツールは導入しない**: Alembic等は使わず、`create_tables()`が`Base.metadata.create_all`相当を実行するのみ（cache_db.pyの`CREATE TABLE IF NOT EXISTS`と同じ「必要最小限」の思想、仕様書12章）
- **`backend/app/infrastructure/road_graph_models.py`**（新規）: SQLAlchemy ORMモデル4種（`road_nodes`, `road_edges`, `elevation_attributes`, `surface_attributes`）。`elevation_attributes`/`surface_attributes`は`road_edges.edge_id`への外部キー（`ON DELETE CASCADE`）で、ドメインモデルと同じく「Edge本体とAttributeの分離」を維持
- **`backend/app/infrastructure/road_graph_repository.py`**（新規）: `RoadGraphRepository`クラス。`get_graph_in_bbox`（`ST_Intersects`/`ST_MakeEnvelope`によるbbox空間検索）、`save_graph`（`Session.merge`によるUPSERT、Node→Edgeの順でflushしFK制約を満たす）、標高/路面属性の取得・保存。ドメインのPydanticモデルとORM行の相互変換関数を持つ
- **`backend/app/infrastructure/database.py`**（新規）: 非同期エンジン・セッションファクトリ（アプリ全体で1エンジンを共有する標準的なSQLAlchemyの使い方）
- **`GraphService`**: 新規メソッド`get_or_build_graph_with_attributes(bbox)`を追加。`repository`（コンストラクタの新規オプション引数、既定`None`）を渡した場合のみキャッシュを使う。渡さなければPhase 1-5と全く同じ「毎回Overpassから構築する」挙動のまま（既存メソッド`build_graph_for_bbox`/`build_graph_with_surface_tags_for_bbox`も無変更）
- **`ElevationAttributeService`**: `get_attributes_for_graph`が`repository`（同じく既定`None`のオプション引数）指定時のみEdge単位でキャッシュを確認し、未取得のEdgeだけGSI APIへ問い合わせる。部分キャッシュ（一部Edgeだけキャッシュ済み）にも対応
- **`config.py`**: `database_url`を追加（既定値はdocker-compose.ymlのpostgresサービスに対応）。`docker-compose.yml`の`DATABASE_URL`をSQLAlchemy非同期エンジン用に`postgresql+asyncpg://`スキームへ修正（これまで一度も実際に使われていなかった値のため、書き換えても既存動作への影響なし）
- テスト: `test_graph.py`にID安定性の検証を追加。`test_graph_service.py`/`test_elevation_attribute_service.py`に、インメモリの`FakeRoadGraphRepository`/`FakeElevationAttributeRepository`を使ったキャッシュヒット/ミス/部分キャッシュのオーケストレーションロジックのテストを追加。既存を含む全199件がグリーン

#### 未検証の範囲（重要）→ 解消済み

**【後日解消】本節の未検証項目は、後述「実PostGISでの動作検証（Phase 0）」ですべて実機確認済み。** 以下は実装当時の記録として残す。

このdev環境にはDocker/PostgreSQLが無く、`road_graph_repository.py`のSQL/ORMマッピングは**実際のPostGISに対して一度も実行されていない**。以下で部分的に静的検証は行った。

- `Base.metadata.create_all`相当のDDLをpostgresqlダイアレクトでコンパイルし、`geometry(POINT,4326)`等の型・外部キー制約が意図通り生成されることを確認
- `get_graph_in_bbox`の`ST_Intersects`/`ST_MakeEnvelope`を使ったSELECT文をpostgresqlダイアレクトでコンパイルし、SQLとして正しい形になることを確認

ただし、実際のPostGISへの接続・PostGIS拡張の有効化・`Session.merge`によるUPSERT・GeoAlchemy2の`from_shape`/`to_shape`によるジオメトリ変換の往復（特に緯度経度の軸順の取り違えがないか）は未検証。**ユーザーがDocker等でPostGISを起動できるようになった時点で、実接続での動作確認が必須。**

#### 意図的な設計上の簡略化（既知の制約）

- Node/Edgeの更新（OSM側の変更に追従した再取得・古いデータの失効判定）は実装していない。`updated_at`列は保持しているが、TTLベースの失効等の利用はまだ無い
- 「bboxと交差するEdgeが1件でもDBにあればキャッシュヒット」という不正確な簡易判定は、後述のタイル単位キャッシュ導入により解消済み

### RegionServiceの路面データとSurfaceAttributeの統合検討 → タイル単位キャッシュの導入

ユーザーから「RegionServiceの路面データとSurfaceAttributeを統合できないか」という検討依頼を受け、以下の選択肢を分析した。

- **A. RegionServiceのデータソースをRoad Graph/PostGIS経由に完全移行**: 却下。RegionServiceは現在ゼロDB依存で動いている実運用機能であり、PostGIS必須にすると「PostGISが落ちている間、地図の路面表示という既存機能が丸ごと壊れる」。実際、このdev環境は今もPostGIS未接続であり、この方針は「既存機能を維持できることを最優先する」という大原則に反する
- **B. Overpassクエリ方式だけを統一**（RegionServiceも`get_ways_and_nodes`を使うよう変更）: 見送り。今この2つのサービスが同時に同じ地域へ問い合わせる実運用シナリオが存在しない（Road Graph側はまだどのAPI/UIからも呼ばれていない）ため、実運用コード（RegionService）を変更するリスクに見合う効果が今は無い
- **C. Road Graph側のキャッシュ単位をRegionServiceのタイル方式に合わせる**: **採用**。RegionServiceには一切手を入れず、Road Graph側だけをXYZタイル境界単位のキャッシュに変更する。これは「bboxの一部だけが過去に取得済みの場合に断片的なデータを返してしまう」という永続化Phase時点の既知の制約の解消と表裏一体であり、RegionServiceへの依存もリスクも生じさせない
- **D. 統合しない（現状維持）**: Cの実施により部分的に採用（データソース自体は統合しない）

#### Cの実装内容: Road Graphのタイル単位キャッシュ

- **`backend/app/domain/region.py`**: `ROAD_GRAPH_TILE_ZOOM = 12`（Road Graph専用の固定ズームレベル。RegionServiceの`ROAD_TILE_MIN_ZOOM`/`MAX_ZOOM`はMapLibreの表示ズームに追従するための範囲だが、Road Graphには「現在の表示ズーム」という概念が無いため単一の固定値とした）。`tiles_covering_bbox(bbox, z)`（新規）を追加。任意のbboxを覆う最小限のXYZタイル群の(x,y)一覧を返す純粋関数で、既存の`tile_bounds_lonlat`（その逆関数に相当）と対で使う
- **`backend/app/infrastructure/road_graph_models.py`**: `RoadGraphTileRow`（新規、`road_graph_tiles`テーブル）を追加。「このタイルはOverpassへの問い合わせを完了した」ことだけを記録する取得済みマーカー（`road_nodes`/`road_edges`にデータが実在するかどうかとは独立して判定する）
- **`backend/app/infrastructure/road_graph_repository.py`**: `is_tile_cached(zoom, x, y)`/`mark_tile_cached(zoom, x, y)`を追加
- **`backend/app/services/graph_service.py`**: `get_or_build_graph_with_attributes`を書き換え。要求bboxを`tiles_covering_bbox`でタイル群に分解し、タイルごとに`is_tile_cached`で正確に判定、未取得タイルだけをOverpassへ**順に**問い合わせて（公開Overpassインスタンスへの配慮として並列化しない、RegionServiceと同じ方針）永続化する。Overpass取得に失敗したタイルはマークしない（次回リクエストで再取得を試みる、RegionServiceの路面タイルキャッシュと同じ方針）。全タイルの取得を保証してから`get_graph_in_bbox`でDBを読むため、返るデータは常に要求bboxを正確にカバーする
- テスト: `test_region.py`に`tiles_covering_bbox`の検証（単一タイルに収まるケース・複数タイルにまたがるケース・世界の端でのクランプ）を追加。`test_graph_service.py`のタイルキャッシュ系テストを、実際のタイル境界（`tile_bounds_lonlat`から逆算した既知のbbox）を使う形に書き換え、複数タイルにまたがるリクエスト・部分キャッシュ・一部タイルのみ取得失敗するケースを検証。既存を含む全205件がグリーン

### 設計・実装レビュー（Phase 1-5・永続化・タイルキャッシュ一式）

ユーザーの依頼により、`backend/`のRoad Graph移行作業一式（frontend/は別プロセスが並行作業中のため対象外）をコードレビューした。7件の指摘のうち4件を修正し、3件は既知の制約として記録するに留めた（理由は各項目に記載）。

#### 修正した指摘

1. **`.env.example`のDATABASE_URLが同期スキーム（`postgresql://`）のままだった**: `database.py`が非同期エンジン（asyncpgドライバ）を要求するため、コメント「not yet used by the backend」も含めて`postgresql+asyncpg://`へ修正し、実態に合わせた説明に更新した。`config.py`のデフォルト値・`docker-compose.yml`は既に正しかったが、開発者が`.env.example`をコピーして使う際に接続エラーになる状態だった
2. **`get_or_build_graph_with_attributes`が「取得失敗」と「道路が無い地域を正常に確認できた」を区別できていなかった**: 海・公園など道路が1本も無い地域は、Overpass取得自体は成功して空のグラフを返すが、旧実装は`get_graph_in_bbox`が0件ヒット（=None）を返すケースを一律「失敗」として扱っていた。タイルは正しくキャッシュ済みとしてマークされ続けるため、**そのような地域へのリクエストは永久にNoneを返し続ける**バグだった。取得ループ中に実際の取得失敗（`any_tile_fetch_failed`）を追跡し、失敗が無ければ0件ヒットを「空だが正常」として扱うよう修正した
3. **`GraphService`のFK前提条件が`ElevationAttributeService`にドキュメント化されていなかった**: `repository`指定時、`ElevationAttributeService.get_attributes_for_graph`はEdgeがPostGISに保存済みであることを暗黙に要求する（`elevation_attributes.edge_id`が`road_edges.edge_id`への外部キーのため）。`GraphService.build_graph_for_bbox`（DB未保存）から得たRoadGraphと組み合わせると外部キー制約違反になる、現状は到達しないが将来の誤用を招きうる罠だったため、docstringに前提条件を明記した
4. **`_lonlat_to_tile_index`が範囲外の緯度でmath domain errorを起こしうる**: `BoundingBox`は`Coordinates`と異なり緯度の範囲を検証しないため、90度を超える値が渡された場合`math.log(負の値)`で`ValueError`を送出しうる状態だった。Web Mercatorの有効範囲（±85.0511度）へクランプするよう修正し、回帰テストを追加した

#### 既知の制約として記録するに留めた指摘（意図的に未修正）

5. ~~**タイル境界の位置によって、同じOSM Wayの交差点分割が取得タイミング次第で変わりうる**~~ → **根本修正済み**。詳細は次項「タイル境界依存の交差点分割不一致問題：根本修正」を参照
6. **同一タイルへの同時リクエストに対するロック機構が無い**: `is_tile_cached`確認→Overpass取得→`save_raw_ways`→`mark_tile_cached`の一連の流れはトランザクション分離されておらず、2つのリクエストが同時に同じ未取得タイルへアクセスすると両方がOverpassへ問い合わせてしまう（「並列化せず順に問い合わせる」という設計意図が単一リクエスト内でのみ有効）。ただし、これは既存の`RegionService`の路面タイルキャッシュ（`tile_cache.py`）も同じ弱点を持っており、このプロジェクトが既に許容している既知のリスクパターンと同等であるため、Road Graph側だけを先に対策することはしなかった
7. ~~**`save_graph`等がNode/Edge/Attributeごとに`Session.merge`を個別実行しており、1タイルあたり数百〜数千回のクエリになりうる**~~ → **解消済み（Phase 1で必須と判明し対応）**。都心部bbox（Edge十数万）で1リクエストが数十分オーダーになることをE2Eで確認し、全保存系をバルクUPSERT（`INSERT ... ON CONFLICT`、1000行/文）へ置き換えた（詳細は「OSM PBF取込バッチ（Phase 1）」参照）。当時の判断（実接続確認まで見送り）の記録として残す: バルクUPSERT（`INSERT ... ON CONFLICT DO UPDATE`）に置き換えれば改善するが、実PostGISに接続できないこの環境ではGeoAlchemy2のジオメトリ値を含むバルク文が正しく動くか検証できない。誤った書き換えを未検証のまま入れるより、パフォーマンス課題として記録し、実接続確認のタイミングで対応する方が安全と判断した

修正後、レビューで追加した回帰テスト（DATABASE_URLの整合性は自動テスト対象外、緯度クランプ・空地域の扱いの2件）を含め、既存を含む全207件がグリーン（この時点。後述の根本修正でさらに増える）。

### タイル境界依存の交差点分割不一致問題：根本修正

レビュー指摘5について、対応レベルをユーザーに確認したところ「根本修正」を選択。**生のOSMデータ（Way/Node）とRoad Graph構築（交差点分割）を分離する**設計に作り直した。

#### 設計

```
Overpass（タイル単位で問い合わせ）
    ↓
生のOSM Way/Nodeデータをそのまま永続化（osm_raw_ways / osm_raw_nodes）
    ↓ ※取得元タイルに依存しない安定した層。素直にUPSERTしてよい
    ↓
Road Graph構築リクエスト時、DB上の既知の生データ全体から
「要求bbox内にノードを持つWay（主対象）」と
「それらのWayが参照する全ノード（Way全長分）を1つでも共有するWay（近傍）」を取得
    ↓
build_road_graph（無変更）をこの結合されたWay集合に対して実行
    ↓
主対象Way分のEdgeのみをdelete-then-reinsertで永続化（近傍Wayの永続化には触れない）
```

- **`backend/app/infrastructure/road_graph_models.py`**: `OsmRawNodeRow`/`OsmRawWayRow`（新規）。`OsmRawWayRow.node_ids`はPostgreSQL配列型（`ARRAY(BigInteger)`）で保存し、GINインデックス（`&&`演算子による重なり検索）を張る。**実装中に発見した問題**: `osm_node_id`/`osm_way_id`を単一列の整数主キーにすると、SQLAlchemyが自動的に`BIGSERIAL`（自動採番）だと解釈してしまう（DDLコンパイルで確認）。これらは常にOSM側のIDを明示的に指定する値のため、`autoincrement=False`を明示して回避した
- **`backend/app/infrastructure/road_graph_repository.py`**:
  - `save_raw_ways(way_specs, node_coords)`: 生データのUPSERT。Wayのタグ・ノード列は取得元タイルに関わらず常に同じ内容になるため曖昧さが無い
  - `get_way_specs_with_closure(bbox)`: 主対象Way（bbox内にノードを持つ）→ それらの全ノード（Way全長分）→ それらのノードを共有する近傍Wayを2段階のクエリで取得する。戻り値は`(WaySpec一覧, ノード座標, 主対象WayのosmWay ID集合)`
  - `save_graph(graph, way_ids_to_replace)`: `way_ids_to_replace`を指定すると、そのosm_way_idを持つ既存Edge行を全削除してから挿入し直す（delete-then-reinsert）。これにより、Wayの分割結果が変わった場合でも孤立した古いEdge行が残らない
- **`backend/app/services/graph_service.py`**: `get_or_build_graph_with_attributes`を書き換え。タイル取得ループはEdge構築を一切行わず`save_raw_ways`のみ呼ぶ。全タイルの生データ取得を保証した後、`get_way_specs_with_closure`→`build_road_graph`（無変更）→ 主対象Way分のみを`save_graph(..., way_ids_to_replace=primary_way_ids)`で保存、という流れに変更した
- テスト: `test_graph_service.py`の`FakeRoadGraphRepository`を実際のclosureロジック（1ホップ近傍探索）で実装し直した。**新規回帰テスト`test_way_split_is_consistent_regardless_of_which_tile_reveals_the_shared_node`**で、Way Wがタイル境界をまたぎ側道Bと交差点を共有するケースを構築し、「Bを含むタイルを直接見た場合」と「Bを含まないタイルだけを見るがBは既に別途取得済みの場合」の両方で、Wが同じ分割結果（4 Edge、同じ距離集合）になることを確認した

#### この設計で解決されること・残る限界

- **解決**: 近傍Wayが既にDBに存在する限り（＝そのWayを含むタイルが過去に一度でも取得されていれば）、どのタイル経由で「主対象」の計算をトリガーしたかに関わらず、交差点の分割結果が一貫する
- **残る限界（結果整合的、1ホップに限定）**: 近傍探索は主対象Wayの全長分のノードから1ホップに限定している。近傍として取得したWay自身が、さらに別の（まだ近傍探索の対象外の）Wayと交差点を共有している場合、その交差点は近傍Way自身が別のリクエストで「主対象」として処理されるまで最新の状態に反映されない。道路網全体の連結成分を毎回たどる完全な整合性チェックはコストに見合わないと判断し、トレードオフとして許容した。実務上は、routeが実際に通る範囲を何度かリクエストするうちに自然と収束していく設計になっている
- **意図的に永続化しない対象**: 近傍Wayとして取得したWay自身のEdgeは、この呼び出しでは保存・更新しない（不完全な文脈で計算した分割結果によって、他のリクエストが正しく永続化したEdgeを誤って上書きしないため）

既存を含む全208件がグリーン（実PostGISへの接続・GIN索引の実動作・配列型のOverlap検索は引き続き未検証、DDL・クエリのコンパイルチェックのみ実施済み）。

### Road Graphを実際のルーティングへ接続する移行（完全移行）

ユーザーから「Road Graphを実際のルーティングに接続する、完全に移行する」との指示を受けた。これはPhase 1-5・「永続化」・「根本修正」で構築してきたRoad Graph/Road Attribute/Evaluation Engineを、これまでのように既存のopenrouteservice委譲（`route_generator.py`）と並行する独立構造のままにせず、**実際に`/api/routes/generate`のルート生成そのものを置き換える**作業。仕様書34章「探索アルゴリズムを独断で変更しない」との緊張関係があったため、着手前にユーザーへ3点確認した。

#### 着手前に確認した設計判断

1. **パスファインディングアルゴリズム**: 自前でDijkstraを実装 vs 標準ライブラリ（NetworkX）を導入 → **NetworkXを導入**を選択。「独自の経路探索アルゴリズムの実装はしない」という仕様書の原則と、標準ライブラリの利用は矛盾しないという判断
2. **移行範囲**: 経路探索の中核のみ置き換え（風は旧WindServiceを流用） vs 全面作り直し（標高・路面・風を含むルート生成ロジック全体をRoad Graph中心に再設計、風はEvaluation Engine未実装のため先にPhase 6実装が必要） → **全面作り直し**を選択。Phase 6（Dynamic Data対応・風）が前提として必要になることを理解した上での選択
3. **PostGIS前提**: 依存なしで先に動くように組む vs 先にPostGISを用意する → **依存なしで先に動くように組む**を選択。`repository`を注入しない構成（毎回Overpass/GSIへ問い合わせる）で、まず実際に動くことを検証する方針

#### 実施内容

- **Phase 6（Dynamic Data対応・風）を`domain/evaluation.py`へ実装**: `RoutePreference`に`wind_weight`を追加（デフォルト値をelevation:road:wind = 0.25:0.30:0.45に変更、`route_preference.yaml`も更新）。`compute_wind_penalty(edge, wind)`（新規）がEdgeの進行方向と風向風速から`domain/wind.py: WindCalculator`を使って（既存のまま再利用）wind_penaltyを算出し、`compute_edge_cost`のCost計算に組み込んだ。**既知の簡略化**: 出発時刻からの推定累積走行時間に応じた風の時間変化は見ない（探索中はまだ累積走行時間が確定しないため）。出発時点・起点付近の風をルート全体に一様適用する
- **`backend/app/domain/routing.py`（新規、Route Engine）**: `build_networkx_graph`（RoadGraph+Edge CostからNetworkXの`DiGraph`を構築、Hard Constraintで除外されたEdgeは含めない）、`find_nearest_node`（総当たりで指定地点に最も近いNodeを探す、PostGIS未使用のため空間インデックス無し）、`shortest_path_node_ids`（`nx.dijkstra_path`をそのまま利用）、`path_to_edge_ids`、`concat_node_paths`
- **`backend/app/services/route_generator.py`を全面書き換え**: `RoutingService`/`ElevationService`/`WindService`への依存を無くし、`GraphService`/`ElevationAttributeService`/`EvaluationService`/`WeatherService`/`RouteScorer`/`RoutePreference`を使う構成にした。8方位の候補地点をジオメトリで計算する部分（`destination_point`）は従来のまま流用。`RouteScorer`・`scoring.yaml`（ルート単位の総合スコアリング）も既存のまま再利用した（Evaluation Engineとは対象が異なる別の重み設定のため、混同しないという方針を維持）
- **`backend/app/api/routes.py`のDIを配線し直し**: `get_route_generator`が新しい依存関係を注入するよう変更。`/api/routes/preview`（Step3の疎通確認用エンドポイント）は引き続き`RoutingService`/`ORSClient`を使うため無変更
- **不要になったコードを削除**: `services/elevation_service.py`・`services/wind_service.py`（ルート単位・12点サンプリングの評価、Road Graph移行によりEdge単位の評価に置き換わったため）とそれぞれのテスト。`domain/geo.py`の`sample_indices`/`sample_line_coordinates`/`sample_line_points`（ルート単位サンプリング専用で他に呼び出し元が無くなったため）。`domain/road.py`の`paved_percent`/`surface_id_at_index`/`is_good_surface`/`GOOD_SURFACE_IDS`（openrouteserviceの`extra_info=surface`数値ID形式専用で、Road Graphへの移行によりOSMタグ形式の`classify_osm_surface`のみを使うようになったため）。削除前にGrep等で他に参照が無いことを確認した上で削除している
- **`requirements.txt`に`networkx==3.4.2`を追加**

#### 実機検証で発見・修正した2つの重大な性能問題

コードを書き終えた時点でテストは全てグリーンだったが、**実際にこのdev環境で動いているバックエンドへ生のリクエストを送ってみたところ、8方位すべてが失敗し空の結果が返る**という問題を発見した。単体テストは全てモックを使っており、この種の実運用上の問題は検出できなかった。以下の手順で原因を切り分けて修正した。

1. **8方位が並列にOverpassへ問い合わせて拒否される**: 当初の実装は方位ごとに個別のbboxを計算し、`GraphService.get_or_build_graph_with_attributes`を8並列（`asyncio.gather`）で呼んでいた。公開Overpassインスタンスへ8並列で問い合わせたところ、全て拒否・失敗する事象を実機で確認した。**修正**: 起点を中心とした単一の円（8方位分の経由地点をすべて覆う半径）でRoad Graphを1回だけ取得し、8方位全てで共有する設計に変更した。これにより`generate_loops`全体でOverpassへの問い合わせは1回のみになった（`OverpassClient`が既に持つ「未キャッシュのセルを並列化せず順に問い合わせる」という公開インスタンスへの配慮の精神を、方位間でも徹底する形）
2. **標高取得がRoad Graph全体に対して行われ非現実的に遅い**: 当初の実装は、経路探索前にRoad Graph全体（bboxによっては数万Edge）に対して`ElevationAttributeService.get_attributes_for_graph`を呼んでいた。実機検証で、200Edge分の標高取得に約12秒かかることを確認し、実際の対象（東京都心部で約6.5万Edge）に外挿すると1方位あたり1時間近くかかる計算になることが判明した。**修正**: 経路探索用のEdge Costからは標高を除外し（distance・路面・風のみで計算）、Dijkstra探索で最短路を確定した「後」に、その経路上のEdge（数十〜数百程度）だけに絞って標高を取得する設計に変更した。**この結果、標高（勾配）は実際の経路選択には影響せず、経路確定後の表示・スコアリング用途にのみ使われる**という重要な仕様変更を伴う（`RoutePreference.elevation_weight`は区間ごとの難易度表示や`RouteScorer`の総合スコアには反映されるが、Dijkstra探索自体には反映されない）

修正後、実機（このdev環境の実際のバックエンドプロセス、および直接`RouteGenerator`を呼び出すスクリプトの両方）で東京・王子駅付近、距離4km指定のリクエストが成功することを確認した。8方位全てで妥当な候補（距離4.46〜6.28km、獲得標高14〜44m、road_score=100.0、区間数154〜234）が生成され、`total_score`によるランキングも機能した。所要時間は約40〜70秒（PostGISキャッシュ無しのため、Overpass取得＋経路確定後の標高取得を毎回行う。パフォーマンス上の既知の制約として次項に記載）。

#### 新規/更新テスト

- `test_evaluation.py`: `compute_wind_penalty`の向かい風/追い風、`compute_edge_cost`への風統合の検証を追加
- `test_routing.py`（新規）: `build_networkx_graph`（Hard Constraint除外）、`find_nearest_node`、`shortest_path_node_ids`（コスト最小経路の選択・到達不能・始点=終点）、`path_to_edge_ids`、`concat_node_paths`の検証
- `test_route_generator.py`（全面書き換え）: 起点を中心とした「車輪」状のRoad Graphフィクスチャ（`build_loop_graph`）を新規構築。**フィクスチャ構築時に発見したバグ**: 隣接方位の経由地点が同一の実座標を指すにもかかわらず別々のNodeとして作ってしまい、最近接ノード探索が別方位のNodeへ誤ってスナップする問題があった（実データでは実在の交差点1つに収束するため起きない、テストフィクスチャ特有の問題）。共有Nodeを使う「スポーク＋アーク」構造に直して解決した。Overpass呼び出しが1回だけであること・標高取得がパス上のEdgeだけに絞られていること（フルグラフではないこと）を回帰テストとして明示的に追加
- `test_road.py`/`test_geo.py`: 削除した関数のテストを撤去
- 既存を含む全205件がグリーン

#### 既知の制約・次に検討すべきこと

- **標高が経路選択に影響しない**: 上記の性能問題への対応の結果、勾配がきついかどうかは経路の「選び方」には反映されず、確定した経路の「見せ方」（区間ごとの難易度表示、`RouteScorer`の総合スコア）にのみ反映される。PostGISキャッシュが有効になれば、標高もあらかじめEdge Attributeとして永続化されているため、探索時にも安価に参照できるようになり、この制約は解消できる可能性がある
- **1リクエストあたり40〜70秒**: PostGISキャッシュ無しの初期実装としては動作するが、実用的なレスポンス速度ではない。次の最優先事項は引き続き実際のPostGIS接続確認（次項参照）
- **風は出発時点の一様値**: Dynamic Data対応の簡略化として、Edgeごとの推定到達時刻による風の時間変化は見ていない
- **`_bbox_around_point`のマージン（`BBOX_MARGIN_RATIO`/`BBOX_MARGIN_MIN_KM`）は暫定値**: 実データでの検証は小さい距離（4km）でしか行っていない。大きい距離（15km・30km等、既存Step4での実機検証相当）でも同様に機能するかは未検証
- **NetworkXの`DiGraph`は同一ノード間の並行Edgeを1本しか保持できない**: 稀なケースで最安のEdgeが選ばれない可能性がある（`MultiDiGraph`への変更は今回未実施）

### 実PostGISでの動作検証（Phase 0）

OSMデータのPBF事前取込によるOverpass依存解消の設計検討（docs/osm-pbf-import.md）に着手するにあたり、その前提（同設計書「9. 段階的導入計画」のPhase 0）として、これまで未検証だった永続化層の実DB動作確認を実施した。

- **環境**: dev機にDockerは無いが、**ネイティブのPostgreSQL 18.6（Windowsサービス`postgresql-x64-18`、ポート5432）が稼働しており、PostGIS 3.6.2が利用可能**だったためこれを使用した（docker-compose.ymlの`postgis/postgis:16-3.4`は使っていない。イメージのPG16との差異は現時点で問題になっていない）。`ridecompass`ロール／`ridecompass` DB／PostGIS拡張／全7テーブルはローカルに作成済み
- **検証方法**: `backend/scripts/verify_postgis_phase0.py`（新規）。交差点共有・タイル境界外の近傍Way・一方通行を含む小さなフィクスチャ（実OSMと衝突しない910兆台の架空ID）を実DBへ書き込み、22項目を検証して終了時に全行削除する。再実行可能
- **結果**: 22/22 PASS（2026-08-14）。具体的に実機確認できたこと:
  - `create_tables()`の冪等性（既存スキーマ・PostGIS拡張ありでも成功）
  - `save_raw_ways`のUPSERT、GINインデックス（`node_ids`の`&&`検索）による`get_way_specs_with_closure`の主対象／1ホップ近傍の判定
  - `save_graph`の`Session.merge` UPSERT・FK制約（Node→Edge順）・delete-then-reinsertの冪等性
  - `ST_MakeEnvelope`/`ST_Intersects`によるbbox空間検索、GeoAlchemy2 `from_shape`/`to_shape`のジオメトリ往復で**緯度経度の軸順の取り違えが無い**こと（懸念事項だった）
  - elevation/surface attributesの保存・読込（timestamptzの往復含む）
  - `is_tile_cached`/`mark_tile_cached`、および`GraphService.get_or_build_graph_with_attributes`のオーケストレーション一式（初回はタイル数分だけデータソースへ問い合わせ、2回目はDBのみで完結し問い合わせゼロ）
- **注意（未決定事項）**: `backend/.env`の`DATABASE_URL`は現在**Supabase（クラウドPostgres）を指している**。今回の検証は環境変数`DATABASE_URL`で一時的にローカルDBへ上書きして実施した（.envは変更していない）。ローカルPG18とSupabaseのどちらを恒常的な開発用DBとするかは、PBF取込のPhase 1着手時に決める
- **残課題**: バルクUPSERT性能（レビュー指摘7、行単位`Session.merge`）は未対応のまま（PBF取込バッチはCOPY方式で最初から回避する設計）。ランタイムDI（`api/routes.py`への`repository`注入）も未配線

### OSM PBF取込バッチ（Phase 1）

Phase 0に続き、docs/osm-pbf-import.mdの設計に沿ってPBF取込バッチを実装し、E2E（Overpassゼロでのルート生成）まで検証した。

- **実装物**: `backend/app/batch/`（`import_pbf.py`＝CLI本体、`profile.py`＝取込プロファイルの読み込み/マッチング、`pbf_source.py`＝pyosmium依存を閉じ込めた読取層、`import_profile.yaml`＝既定プロファイル）。依存は`requirements-batch.txt`（`osmium==4.1.1`、webサービスには入れない）。スキーマは`osm_raw_ways.geom`列（実体化済みLINESTRING＋GiST索引＋旧データのバックフィル）と`osm_import_runs`テーブル（実行記録）を追加
- **DI配線**: `config.py`の`road_graph_use_repository`（既定false）。trueで`get_graph_service`/`get_elevation_attribute_service`へ`RoadGraphRepository`を注入する
- **実測（BBBike Tokyo抽出79MB、bbox=35.60,139.65,35.75,139.85）**: 取込150,265 way / 511,948ノード / 16タイル（z12）マーク、194秒。DBサイズは導出データ（road_edges 155,086行等）込みで約298MB
- **E2E（東京駅起点、4km周回、`scripts/verify_phase1_e2e.py`）**: 「呼ばれたら失敗するOverpassスタブ」を注入した状態で8方位すべての候補生成に成功し、**Overpass呼び出し0回**を確認。所要222.7秒（prepare 187s / trace 5.6s / evaluate 29s）
- **Phase 1で発見・修正した問題（実データ規模で初めて顕在化）**:
  1. **行単位`Session.merge`が実用不能（レビュー指摘7の顕在化）**: 都心bbox（主対象way約4.8万・Edge十数万）でE2Eが10分以上無応答。全保存系（`save_graph`/`save_raw_ways`/attributes）を複数行VALUESのバルクUPSERTへ置き換え（1000行/文、asyncpgのパラメータ上限32767を考慮したチャンク分割）
  2. **`get_way_specs_with_closure`のGIN配列検索がスケールしない**: 数十万要素の配列パラメータによる`&&`検索を、空間検索（主対象＝bboxと`ST_Intersects`するway、近傍＝主対象全長の`ST_Extent`と交差するway。旧semanticsの上位互換/上位集合で正しさは維持）へ置き換え。`osm_raw_ways.geom`が前提のため`create_tables()`に旧データのgeomバックフィルを追加
  3. **`AsyncSession`の同時使用クラッシュ**: `RoadGraphEngine.evaluate_loops`が候補ごとに`asyncio.gather`で並列実行するため、注入した`ElevationAttributeService`のrepository（単一セッション）が同時使用され`IllegalStateChangeError`で落ちることをE2Eで確認。repositoryアクセスのみ`asyncio.Lock`で直列化（GSIへのHTTP問い合わせは並列のまま）。再入検出フェイクによる回帰テストを追加
- **既知の制約・次の課題**:
  - ~~**prepareの187秒**: 大半は「タイル取得済みでも毎リクエスト、生データから交差点分割を再計算し全Edgeを再保存する」現設計のコスト（closureクエリ＋`build_road_graph`＋十数万行の再UPSERT）。生データが変わっていなければ`road_edges`を直接読む省略パスの導入が次の最適化候補~~ → **解消済み**。`RoadGraphRepository.is_split_up_to_date`＋`get_graph_in_bbox`による省略パスを実装（`osm_raw_ways.split_at`と`updated_at`の比較で鮮度判定。`save_raw_ways`のUPSERTを内容不変時のno-op化した上で導入。1つのWayが複数タイルにまたがると隣接タイル取得だけでstale誤判定する問題への対処）。実測値は`backend/benchmarks/README.md`参照
  - E2Eは東京都心（日本有数の道路密度）での数値。郊外ではway数が1桁少なくなり大幅に短くなる見込みだが未計測
  - 天候（Open-Meteo）・標高（GSI）は引き続き外部API（Phase 1の解消対象はOverpassのみ）

### RegionServiceのPostGIS化（Phase 2）

docs/osm-pbf-import.md「Phase B」の実施記録（2026-08-14）。地域路面レイヤー（路面ベクタタイル）のデータソースをPostGIS第一系統へ変更し、本番想定（Supabase）の容量予算にも対応した。

- **カバレッジ判定**: 表示タイル（z12-15）を`domain/region.py: tile_ancestor`（新規、右シフトによる祖先タイル計算）でz12へ丸め、`road_graph_tiles`の取得済みマークで「このタイルのデータはDBにあるか」を正確に判定する。PBF取込バッチとRoad Graphのタイル取得が同じマークを共有しているため、どちらで取得された範囲でも路面タイルはDBだけで生成できる
- **タイル生成**: `RoadGraphRepository.get_road_surface_tile_mvt`が`osm_raw_ways.geom`（Phase 1で実体化済み）の`ST_Intersects`検索とMVTエンコード（`ST_AsMVT`/`ST_AsMVTGeom`、surface3値分類のCASE式込み）を1クエリでPostGIS側にて実行し、完成済みタイル1個だけを転送する。ファイルキャッシュの既存方針は無変更（2026-08-15改修。当初のway行転送＋Pythonエンコード構成は、遠隔DBで1タイル数秒→パンのバースト時にNext.jsプロキシの30秒タイムアウト500を招いていた。Overpassフォールバック経路のみ従来の`encode_road_surface_tile`を使用）
- **フォールバック**: 取込範囲外・DB障害時は`settings.overpass_fallback_enabled`（新設、既定true）に従い従来のOverpass問い合わせへフォールバックする（「PostGIS停止が既存機能を丸ごと壊さない」という過去の選択肢A却下時の懸念への回答）。falseなら空タイルを返し**キャッシュには保存しない**（後から取込された際に再生成させるため）。フォールバック発動・範囲外アクセスはログ方針どおり常時WARNING
- **容量予算対応（ユーザー要件: Supabaseフリー500MB→安全枠300MB）**: 実測内訳を取り、閉包クエリの空間検索化（Phase 1）以降未使用になっていたGINインデックス`ix_osm_raw_ways_node_ids`（28MB）を`create_tables()`で冪等に削除。DB全体は313MB→**284MB**となり、現行取込bbox（東京都心35.60,139.65-35.75,139.85）が300MB予算内のプロトタイプ基準規模であることを確認した。取込バッチの完了サマリに`db_size_mb`を追加し、超過を取込時点で検知できるようにした
- **検証**: ユニットテスト追加（PostGIS系統/フォールバック有無/DB障害/`tile_ancestor`）で全367件グリーン、実DB検証`backend/scripts/verify_phase2_e2e.py`で9項目PASS（取込範囲内z14タイル: 3,304地物をOverpass呼び出し0回で生成、z12タイル・範囲外の両フォールバック分岐も確認）。Phase 0検証22項目も回帰PASS

### Supabase取込とOverpass停止（Phase 3）

docs/osm-pbf-import.md「Phase C」の実施記録（2026-08-14）。ユーザー要件: 本番はSupabase（フリープラン500MB、安全枠300MB以内でプロトタイプ実施）、**Overpassフォールバックは設定で無効化しロジックは併存させる**。

- **Supabase接続確認**: `.env`の`DATABASE_URL`（`?ssl=require`付きDirect connection）でSQLAlchemy+asyncpgから接続できることを確認（PostgreSQL 17.6、PostGIS 3.3.7導入済み、ベース19MB）。疎通チェック用に`backend/scripts/check_db_connection.py`を追加。取込バッチのasyncpg直結パスには`?ssl=require`→`?sslmode=require`のDSN正規化（`_asyncpg_dsn`）を追加した（`ssl=`はSQLAlchemyのasyncpgダイアレクト固有の書き方のため）
- **取込**: 容量試算（ローカル実測284MBが予算上限規模＋標高属性の将来増分）に基づき、**bboxを約7割へ縮小**（35.61,139.67-35.74,139.83。東京駅・新宿・渋谷・上野・池袋を含む）して取込んだ。実測: 116,336 way / 389,493ノード / z12タイル4枚 / 195秒 / 取込後120MB
- **`GraphService`のフォールバック無効化フラグ**: Phase 2で`RegionService`に入れた`overpass_fallback_enabled`を`GraphService`にも追加。無効時、未取込タイルを含むルート生成リクエストはOverpassへ行かず「データ未整備」としてNoneを返す（常時WARNING）。`repository`未注入の構成では両サービスともフラグに関わらず従来どおりOverpassを使う（DBなし構成の互換性維持）
- **設定**: `.env`を`ROAD_GRAPH_USE_REPOSITORY=true`＋`OVERPASS_FALLBACK_ENABLED=false`へ変更。**コードは無変更で`.env`の2行だけで切り戻せる**
- **検証（すべてSupabaseに対して実施）**: Phase 2検証9項目PASS（東京駅付近z14タイルはローカルと同一の3,304地物）、ルート生成E2E成功（8方位・Overpass呼び出し0回・336.6秒。prepare 295秒とローカル比+108秒はWANレイテンシ分）。ユニットテスト全370件グリーン
- **容量**: E2E後のSupabase実測196MB（予算300MBに対し余裕約100MB）。**導出データ（road_edges等）はルート生成が要求した地域ぶんだけ増える**が、生OSM層から再計算可能なキャッシュのため、逼迫時は該当行のDELETEが安全な圧力弁になる（docs/osm-pbf-import.md 10章）

### 次のPhaseへの引き継ぎ事項

- ~~**最優先**: 実際のPostGISに接続しての動作確認~~ → **完了**（Phase 0）
- ~~**PBF取込のPhase 2（RegionServiceのPostGIS第一系統化）・Phase 3（Supabase取込・Overpass停止）**~~ → **完了**（前2項）。Overpass依存解消の計画（docs/osm-pbf-import.md）は全Phase完了
- ~~**prepare 295秒（Supabase・都心）の短縮**: 生データ不変時の分割再計算・全量再保存の省略パス（`is_split_up_to_date`、上記参照）はローカルPostGISで実装・実測済みだが、Supabase（WAN経由）での実測はまだ行っていない。再保存の省略はWAN環境ほど効く見込みのため、Supabase環境での再計測が次のステップ~~ → **実測済み**。Supabase（WAN経由、東京都心実データ）でCOLD/WARM実測: 1km 126.0s→18.0s（約7.0倍）、4km 211.0s→27.9s（約7.6倍）。短縮の絶対値（108〜183秒）はローカルPostGIS実測（143〜137秒）と同等以上だが、短縮**倍率**はローカル（10〜14倍）よりむしろ低い — WARM側も`is_split_up_to_date`・`get_graph_in_bbox`・`get_surface_attributes`のラウンドトリップ回数分だけWAN遅延の影響を受ける（例: `is_split_up_to_date`単体がローカル20〜30msに対しSupabaseでは780〜810ms）ため、COLD側の一括UPSERTほどには短縮率が伸びない。詳細は`backend/benchmarks/README.md`参照
- **Renderデプロイへの反映**: Render側の環境変数に`DATABASE_URL`（Supabase）・`ROAD_GRAPH_USE_REPOSITORY`・`OVERPASS_FALLBACK_ENABLED`を設定すれば同じ姿勢で動く（未実施。Render→Supabase間のレイテンシは要実測）
- **OSMデータの更新運用**: 月次程度でPBF再取込（docs/osm-pbf-import.md 8章）。`--prune`（削除way掃除）は未実装のまま
- 大きい距離（15km・30km等）でのRoad Graphベースのルート生成の実機検証（現時点では4kmでのみ確認済み）
- `compute_edge_cost`のCost計算式（distanceへの乗算ペナルティ）は初期実装であり、仕様書31章が求める「複数のCost計算方式を比較検討できる」構造は、実際に2つ目の方式を試すタイミングでリファクタリングの必要性を再評価する
- 標高が経路選択に影響しない制約（前述）をPostGISキャッシュ有効化後に解消するかどうかの検討
- 複数のRoute Preferenceプロファイル（快適性重視/トレーニング重視等）を実際に追加する場合、`route_preference.yaml`をどう複数化するかは、実際にUI/APIから選択可能にするタイミングで改めて設計する
- `ROAD_GRAPH_TILE_ZOOM = 12`は暫定値（東京付近で1辺約8km）。実データが蓄積された段階で、Overpassへの問い合わせ回数とキャッシュ粒度のトレードオフを見直す余地がある
- RegionServiceとRoad Graphのデータソース統合（選択肢A）は、Road Graphが実際にRoute Engineへ接続され「本当に使われる」段階になった今、改めて検討の俎上に載る余地がある
