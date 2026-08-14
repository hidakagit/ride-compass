# 実装ステップの時系列ログ（決定記録）

docs/architecture.md から分離した経緯の記録（改善計画T8。現状の姿はarchitecture.md本体を参照）。
各項目は完了当時の記述をそのまま保存しており、**追記専用**とする（現状と食い違って見える場合は
architecture.md側が正）。

## ステップ一覧

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
