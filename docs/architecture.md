# RideCompass アーキテクチャ設計

このドキュメントは**現状の姿**（技術選定・構成・API・データモデル・運用上の制約）を記す。
実装ステップの時系列・Road Graph移行の経緯といった**決定記録**は [decisions/](decisions/) へ分離した
（分離の経緯は改善計画T8参照）。本文はコード変更と同一コミットで更新し、常に最新へ保つこと。

- 実装ステップの時系列ログ: [decisions/step-log.md](decisions/step-log.md)
- Road Graph移行の経緯（Phase 0〜3・永続化・レビュー対応）: [decisions/road-graph-migration.md](decisions/road-graph-migration.md)
- 全体設計レビュー（2026-08-15）と改善実行計画: [design-review-2026-08-15.md](design-review-2026-08-15.md) / [improvement-plan.md](improvement-plan.md)

---

## 1. 技術選定

| 領域 | 採用technology | 備考 |
|---|---|---|
| Frontend | Next.js (App Router) + TypeScript + MapLibre GL JS | React 19 / Next.js 16 |
| Frontendスタイリング | Tailwind CSS v4（新規UI）+ CSS Modules（既存、機能改修時に段階移行）+ Radix UI + `frontend/src/components/ui/` | T252でTailwind併用導入、T299でRadix UI + 自前UIコンポーネント層（Button/Input/Card/Dialog/Checkbox）を新設。使い分け基準・Design Token一覧・意図的に作らないものは[frontend-design-system.md](frontend-design-system.md)参照 |
| Backend | Python + FastAPI | pytest でロジックを単体テスト |
| DB | PostgreSQL + PostGIS | PBF取込済みの生OSM層・Road Graph・路面タイル生成（ST_AsMVT）の第一系統として使用。Overpassフォールバックは改善計画T22で撤去済みのため、取込範囲外はOverpassへ問い合わせず「データ未整備」として扱う。`GraphService`は改善計画T222でDBなし構成（Overpassのみで動作する経路）自体を撤去済みのため、周回ルート生成には`DATABASE_URL`への実接続が必須（`road_graph_use_repository`は他の一部サービス[ElevationAttributeService/RegionService/AccidentService]のみに引き続き効く設定として残る。既定値はtrue[改善計画T283、2026-08-29——以前は既定falseだったため、新環境構築時にこの設定を明示し忘れると「ルート生成は動くのに地図レイヤーがすべて空」という気づきにくい縮退になっていた。DB未接続環境では既存の空タイルフォールバックが効くため、既定trueのままでも安全側に倒れる]）。SQLAlchemy+GeoAlchemy2経由（`infrastructure/database.py`, `road_graph_models.py`, `road_graph_repository.py`）。dev環境はネイティブのPostgreSQL 18.6＋PostGIS 3.6.2（Windowsサービス）で実接続検証済み（[decisions/road-graph-migration.md](decisions/road-graph-migration.md)「実PostGISでの動作検証（Phase 0）」参照） |
| ルーティングエンジン（周回ルート生成、`/api/routes/generate`） | **road_graph単一構成**（改善計画T462でopenrouteserviceエンジンを完全撤去、切替設定自体が廃止済み） | 周回生成戦略は単一の`RouteGenerator`（[backend/app/services/route_generator.py](../backend/app/services/route_generator.py)）が持ち、経路計算・評価を`RoadGraphEngine`（[backend/app/services/road_graph_engine.py](../backend/app/services/road_graph_engine.py)、自前ホスト・外部APIキー不要、`GraphService`・`EvaluationService`・`domain/routing.py`のscipy.sparse.csgraph Dijkstraを使う）へ委譲する。改善計画T236（経路品質比較、致命的な差異なし）・T241（道路グラフの連結性、致命的な問題ではない）・T242〜T246（本番DBのmigration未適用・DELETE性能問題という本番実行不能の原因を解消、実データで検証済み）を経て既定値を`road_graph`へ切り替え（改善計画T247、2026-08-23）、以降の運用実績を踏まえてopenrouteserviceエンジン・`config.py`の`routing_engine`設定自体を完全撤去した（改善計画T462、2026-08-31）。詳細は[decisions/road-graph-migration.md](decisions/road-graph-migration.md)、撤去の経緯は下記「ルーティングエンジンの切り替え対応」節参照 |
| ルーティングエンジン（単一区間確認、`/api/routes/preview`） | **road_graph単一構成**（改善計画T462で切替設定を廃止） | Step3の疎通確認用エンドポイント。`dependencies.py: get_preview_builder`が`RoadGraphEngine.preview_segment`（評価軸重み付きコストで最短経路を1回探索、generateと同じコスト式）を組み立てる。`RoutingService`/`ORSClient`はT462で削除済み。previewはリクエストボディでの評価重み上書きに対応しない（既定値のみ使用） |
| 地図タイル | OpenFreeMap（`https://tiles.openfreemap.org/styles/liberty`、APIキー不要） | `tile.openstreetmap.org` は bulk/非ブラウザアクセスをブロックするポリシーがあり不採用（後述）。Step10でバックエンド経由のプロキシ＋ファイルキャッシュ（`BasemapClient`）を追加 |
| 天候 | **Open-Meteo Forecast API**（APIキー不要） | `WeatherService`（[backend/app/services/weather_service.py](../backend/app/services/weather_service.py)）の`get_conditions`が起点1点の現在気象を`current`＋`hourly`から取得する（`RoadGraphEngine`は起点判定に1回だけ呼ぶ、候補ごとの並列呼び出しはしない）。地図の風グリッドレイヤーは`get_wind_grid`が複数地点をまとめて`get_forecast_many`（TTLキャッシュ付き）で取得する（改善計画T462でopenrouteserviceエンジン専用だった候補間prefetch経路[`WeatherService.prefetch`/`WindService`]を削除済み） |
| 標高 | **国土地理院（GSI）標高API**（APIキー不要、日本国内限定） | `ElevationService`（[backend/app/services/elevation_service.py](../backend/app/services/elevation_service.py)）がルートを距離連動の点数（約1km間隔・12〜32点、`sample_count_for_distance`）でサンプリングして問い合わせ、獲得標高・最高/最低標高・最大勾配を算出 |
| 標高（地域レイヤー） | **国土地理院 色別標高図**（ラスタタイル、`https://cyberjapandata.gsi.go.jp/xyz/relief/{z}/{x}/{y}.png`、APIキー不要） | `MapView.tsx`がMapLibreのraster sourceとして直接重ね描き。バックエンドAPIを介さない。候補ルートに紐づかない「地域全体」の標高表示用で、Step5の標高API（点ごとの数値取得）とは別用途 |
| 路面（地域レイヤー） | **PostGIS**（`ST_AsMVT`、`road_graph_use_repository=true`時）／DBなし構成では常に空タイル | `RegionService`（[backend/app/services/region_service.py](../backend/app/services/region_service.py)）が候補ルートに紐づかない「地域全体」の路面レイヤーを提供する。PBF取込済み範囲はPostGIS側（`road_graph_repository.py`の`_ROAD_SURFACE_TILE_MVT_SQL`）でMVT生成まで完結し、取込範囲外・DB障害・DBなし構成は空タイル（`infrastructure/vector_tile.py: encode_empty_road_surface_tile`）を返す。Overpass APIによる取得は改善計画T22で撤去済み（当初はOverpass API＋自前Python MVTエンコードだったが、PostGIS移行に伴い不要になった。経緯は[decisions/pre-static-attributes-gate.md](decisions/pre-static-attributes-gate.md)参照） |

### 地図タイルプロバイダに関する注記
当初 `tile.openstreetmap.org` のラスタタイルを想定していたが、bulk/プログラム的アクセスに対してブロックポリシー（`x-blocked` ヘッダーで拒否）があり、本番はもちろん開発環境でも安定して使えないことを実機検証で確認した。そのため、MapLibre GL JS向けにAPIキー無しで提供されている OpenFreeMap のベクタースタイルに切り替えた。本番運用時は利用規約を再確認し、必要に応じて専用プロバイダ（MapTiler等、APIキー方式）へ切り替えることを推奨する。

### フロントエンド実装上の注意（maplibre-gl バージョン固定）
`maplibre-gl` の最新メジャー（v6系）は、Web Worker のスクリプトURLを `new URL(`./${file}`, import.meta.url)` という動的テンプレートリテラルで解決する実装になっており、Next.js のバンドラ（Turbopack / Webpack のいずれも）がこれを静的解析できず、Workerが実際には空のページを読み込んでしまい、スタイル処理・タイル取得が永久に止まる（`isStyleLoaded()` が `true` にならない）現象を実機で確認した。回避策として `maplibre-gl` を `^5.24.0`（自己参照Blob方式のWorkerを使う、Next.js/Webpackとの互換実績が豊富なメジャーバージョン）に固定している。将来 v6系対応が改善された場合はアップグレードを検討する。

### バックエンド運用上の注意（Windows: `uvicorn --reload` の多重プロセス）
Windows環境では `uvicorn --reload` はリローダー親プロセスとワーカー子プロセス（`multiprocessing.spawn`）に分かれる。親プロセスだけを `taskkill` すると子プロセスが孤児化して同じポートに残り続け、古い設定（環境変数など）のまま応答し続けることがある。`.env` を編集後にAPIの挙動が変わらない場合は、`netstat -ano | findstr :8000` で該当ポートを握っている全PIDを確認し、それら全てを `taskkill /F /PID <PID>` で終了してから起動し直すこと。また `.env` の変更は `--reload` のファイル監視対象外のため、変更後は必ずプロセスの完全な再起動が必要。また、複数ファイルを短時間に連続編集すると `WatchFiles` の再読み込みが1回分しか発火せず、古いコードのまま動き続けることが実機で確認された（`404 Not Found` になる等）。挙動が古いままに見える場合は一度プロセスを完全に再起動すること。

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

### 周回ルート生成のアルゴリズムと既知の制約（Step4）
`RouteGenerator`＋`OpenRouteServiceEngine`（[backend/app/services/route_generator.py](../backend/app/services/route_generator.py)・[backend/app/services/openrouteservice_engine.py](../backend/app/services/openrouteservice_engine.py)、Step4当時は`route_generator.py`という単一ファイルだったが「ルーティングエンジンの切り替え対応」で戦略とエンジンに分離した）は、8方位それぞれについて「方位θの方向に半径R」「方位θ+45°の方向に半径R」の2経由地点を`domain/geo.py`の`destination_point`（球面三角法）で計算し、`[現在地, 経由地A, 経由地B, 現在地]`をopenrouteservice Directions APIに1回のリクエストで渡す。半径Rは`distance_km / 3`という固定ヒューリスティック。8方位分は`asyncio.gather`で並列実行し、失敗した方位はスキップする。

実機検証（王子駅付近、15km/30km指定）では8方位すべてが成功し、目標距離に対して+10〜+16%程度（許容差±5km以内）に収まった。ただし適応的な半径調整は行っていないため、道路網の形状次第では大きくずれる方位が出る可能性がある。将来の改善点:
- 半径を反復調整して目標距離に近づける適応的探索
- `distance_tolerance_km`のデフォルト値を、実データが蓄積された段階で仕様書どおりの±2km程度まで狭める
- 8方位に加え、方位内で複数の経由地点パターンを試す（候補数を増やす）

**経由地（中継地）指定ルート（改善計画T364）**: 上記の固定三角形waypoint生成は「特定の
経由地を通るルート形状」をそもそも表現できない制約があるため、ユーザーが地図上で
指定した経由地を順に通る単一経路を生成する別経路`RouteGenerator.generate_via_waypoints`
を追加した（`generate_loops`とは独立、8方位探索・距離フィルタを通らない）。
`TracedLoop.bearing`が`None`のときがこの経由地ルートを表す規約で、`candidate_identity`は
`id="route-waypoints"`・`direction_label="経由地ルート"`を返す。`road_graph_engine.py`の
`trace_loop`は中間経由地を任意個数受け取れる汎用ループへ
一般化されており（waypoints=2点の8方位探索は従来と同じ3ペアに帰着）、`prepare`は
経由地指定時のみ`_bbox_covering_points`（複数点の外接矩形、`preview_segment`と同じ）で
bboxを組む。`_build_best_candidate`のT274逆回り最適化（周回の向きに意味が無い8方位探索
向け）は、経由地ルートでは訪問順序の保持が要件そのものなので`bearing is None`のとき
スキップする。road_graphエンジンのみ対応（改善計画T462でopenrouteserviceエンジンを
撤去し唯一のエンジンになったため、この制約自体が解消済み）。

### 標高計算のアルゴリズムと既知の制約（Step5）
`ElevationService`（[backend/app/services/elevation_service.py](../backend/app/services/elevation_service.py)）は、各ルートのGeoJSON LineStringから始点・終点を含む点列（当初は12点固定。現在はエンジンが`sample_count_for_distance`で距離連動の約1km間隔・12〜32点を決めて渡す。Step9で点列を直接受け取るシグネチャへ変更）をサンプリングし、国土地理院の標高API（1リクエスト=1地点）に問い合わせる。獲得標高は連続区間の正の標高差の合計、最大勾配は`|標高差| / 水平距離`の最大値（%、水平距離は`haversine_distance_km`で算出）。標高が取得できない区間（海上・データ範囲外・通信エラー）は`None`として扱い、有効な点が2点未満なら標高関連フィールドはすべて`None`を返す（ルート自体は除外しない）。

**パフォーマンス上の落とし穴（実機で発見・修正済み）**: 当初 `ElevationClient` がリクエストごとに新規`httpx.AsyncClient`を生成しておりTLSハンドシェイクを毎回やり直していたため、15km生成（8候補×12点=最大96リクエスト）に**約57秒**かかっていた。`httpx.AsyncClient`をFastAPIの依存性注入（`yield`付き）で1リクエストあたり1つ生成して使い回す形に直したところ**約7秒**まで短縮した。あわせて、同時リクエスト数を制限する`asyncio.Semaphore`が`get_profile`呼び出しごとに新規生成されており、意図していた「サービス全体で最大5並列」ではなく実質「候補ごとに最大5並列」（合計で最大40並列）になっていた点も、`ElevationService.__init__`でSemaphoreを1つだけ生成する形に修正した。

### 標高DEMタイルキャッシュ（改善計画T10、`elevation_client.py`）
`ElevationClient`（[backend/app/infrastructure/elevation_client.py](../backend/app/infrastructure/elevation_client.py)）は、以前はGSI点標高API（`getelevation.php`、1リクエスト=1地点）を緯度経度4桁丸めのSQLiteキャッシュ（`cache_db.py`の`elevation_cache`テーブル）でラップしていたが、T218aでRoad Graph全体（数万エッジ）へ標高を付与する必要が生じ、点API逐次呼び出しでは非現実的な回数（実測: 480エッジに対し2,880回）の外部呼び出しが必要になると判明した。T10でGSIのDEMタイル（`https://cyberjapandata.gsi.go.jp/xyz/{type}/{z}/{x}/{y}.txt`、z=14固定）を範囲ごと取得しローカルで双線形補間する方式へ切り替えた。**当初は`dem`（サフィックス無し）がDEM5A/5B/5C/10Bを統合しGSIサーバー側で優先順位フォールバックすると判断していたが、2026-08-23の再検証（ユーザー指摘）で誤りと判明**——実タイル比較の結果、`dem`はDEM5A等を統合したものではなくDEM10B相当の別データセット（z=15で404、DEM10Bの公式最大ズーム14と一致）であり、同一タイルで`dem5a`と異なる値を返すことを都心部で確認した。`dem5a`/`dem5b`/`dem5c`はそれぞれ独立にクエリでき非対応エリアではタイル丸ごと404を返すため、アプリ側で`DEM_TYPE_PRIORITY = ("dem5a", "dem5b", "dem5c", "dem")`の順に多段フォールバックする（`elevation_client.py`）。タイル本文（256行×256列のカンマ区切り、単位m、欠測は`"e"`）は`infrastructure/tile_cache.py`（基礎地図・路面タイルと共通のファイルキャッシュ、TTL無し。DEMは不変データのため）へ永続化し、さらにプロセス内メモリ（`_tile_grid_cache`、パース済みグリッド）にも保持する。呼び出し側インターフェース（`get_elevation(client, point, refresh=False) -> float | None`）はT10前後で変わらない。旧`elevation_cache`テーブル・`get_elevation`/`set_elevation`（`cache_db.py`）は削除済み。

### Road Graphエンジンの探索性能（改善計画T218・T218a・T219、T12 ADR）
`RoadGraphEngine.prepare`（[backend/app/services/road_graph_engine.py](../backend/app/services/road_graph_engine.py)）は、リクエスト毎の重い処理を段階的に排除してきた。

- **T218（Stage 0）**: 探索フェーズはEdgeのgeometry（形状点列）を必要としないため、`geom`列を一切SELECTしない軽量版`get_graph_topology_in_bbox`を新設（geometryは最終候補のみ`get_edges_with_geometry`で後付け取得）。風評価も`edge.bearing_deg`（`build_road_graph`が事前計算）を直接使う形にし、geometry依存を除去した。事前集計済み`edge_attribute_counts`（T144）への読み取り配線も行い、3種の空間結合クエリを1クエリへ集約した。
- **T218a（Stage 0.5）**: `app/batch/precompute_elevation_attributes.py`（全道路網一括、T10のDEMタイル方式を利用）が事前計算した`elevation_attributes`（average_grade等）を、`prepare`が単純なキー参照で読み探索コストのgradient軸へ組み込む。0次ハードフィルタへ勾配しきい値（`max_average_grade_percent`）も追加した。
- **T219（Stage 1）**: `GraphService.get_search_materials_for_bbox`が、トポロジ＋材料一式（surface/edge_attribute_counts/way_tags/elevation_attributes/designated_edge_ids）をz12タイル単位（`domain/region.py: ROAD_GRAPH_TILE_ZOOM`）でプロセス内メモリへLRUキャッシュする（`infrastructure/graph_material_cache.py`）。**無効化はバージョン管理せずプロセス寿命のみ**（PBF再取込・各precomputeバッチは手動・低頻度操作であり、デプロイのたびにプロセスが再起動される前提。T10のDEMタイルキャッシュと同じ割り切り）。ローカル実測（東京都心4km四方相当）でキャッシュヒット時は約7.2秒→約0.06秒（約100倍）。あわせて`find_nearest_node`（1リクエストにつき最大17回呼ばれる、`prepare`で1回＋`trace_loop`で方位ごとに2回）を、都度の線形探索から`NodeSpatialIndex`（緯度経度グリッドバケット、`domain/routing.py`）を1回だけ構築して使い回す方式へ変更した（外部ライブラリは追加していない）。
- **T220（Stage 2）**: T219完了後の実測（キャッシュ温、69,216エッジ規模）で「evaluate_graph＋build＋Dijkstra24回」が約5.8秒と目標超過だったため着手。Dijkstra本体をNetworkX（Python実装）からscipy.sparse.csgraph（C実装、`domain/routing.py: SparseRoadGraph`/`build_sparse_graph`/`shortest_path_node_ids_sparse`）へ置換（同一ノード間の並行Edgeは後勝ちで1本化、NetworkX版と同じ挙動）。`_RoadGraphContext.nx_graph`は既存テスト・区間表示ロジック互換のため引き続き構築するが、`trace_loop`の探索本体は`sparse_graph`を使う。あわせて`compute_edge_cost`が毎Edge`preference_to_axis_weights`を再計算していた（pydantic `model_dump`込みで無視できないオーバーヘッド）のを、`evaluate_graph`側で1回だけ計算し渡す形に変更。実測（同条件）で合計約5.8秒→約2.3秒（Dijkstra部分は約2.8秒→約0.08秒）。新規依存: `numpy`・`scipy`。
- **T239（軸のテンプレート化）→T240（evaluate_graphのnumpyベクトル化）**: T220完了メモが提案した「軸を4テンプレートへ統一してからベクトル化する」の順で実施。T239で`domain/axis_templates.py`を新設し、7軸の変換ロジックが実質「区分線形補間・カテゴリ→定数・フラグ加算・レシピ→レベル→区分線形補間」の4パターンへ還元できることを確認、`domain/difficulty.py`・`domain/night.py`の各`*_difficulty`関数の内部実装をこれらのテンプレート呼び出しへ差し替えた（外部シグネチャ・挙動は不変）。T240で`EvaluationService.evaluate_graph`を、Edge毎に`compute_edge_cost`を呼ぶPythonループから、`domain/evaluation.py: compute_edge_costs_bulk`（抽出フェーズ＝1回のPythonループでnumpy配列へ集約、計算フェーズ＝7軸のdifficulty配列を`*_difficulty_array`関数で求め重み付き合成→costまでPythonループ無しの配列演算）へ切り替えた。**実装中に判明した重要な制約**: Python 3.12以降の組み込み`sum()`はfloat列をNeumaier補償加算（Kahan加算の改良版）で合計するため、単純な逐次`+=`やnumpyの`.sum(axis=1)`では合成difficultyの最終丸め（1桁）がスカラー版の`composite_difficulty`と.X5境界でごく稀に食い違う（実データで確認）。`compute_edge_costs_bulk`はNeumaier加算を配列でまとめて行う`_neumaier_accumulate`でこれを再現し、さらに`np.round`自体の内部誤差（×10→rint→÷10）がPython組み込み`round()`と食い違いうる問題を最終cost/difficultyの丸めのみ`axis_templates.py: round1_array`（要素ごとのPython`round()`）で回避している（軸別スコア単体の丸めは実データで不一致が出なかったため速度を優先し`np.round`のまま）。実データ12万Edge超（東京都心2エリア）でスカラー版との全Edge一致（cost/difficulty/allowed）を確認済み。**実測速度**: 68,120エッジで約1.18秒→約1.02秒、121,800エッジで約2.12秒→約1.83秒（約14%短縮）。抽出フェーズ（車ストレス等のタグ解析）とpydantic`model_construct`が依然としてEdge数に比例するコストの大半を占めており、「合成計算自体のベクトル化」による短縮効果は当初期待より小さいというのが実測に基づく正直な結論（ボトルネックの所在はcProfileで確認済み）。
- **T11**: road_graphエンジンが返す`segments`はEdge単位（交差点間、1候補あたり150〜230件、
  30km級）のままではAPIペイロード・フロント描画コストが嵩むため、`domain/route.py:
  aggregate_segments_into_bins`で約500m単位（`SEGMENT_BIN_DISTANCE_KM`）へ集約してから
  返す（road_graph_engine.py: `prepare`が生成した候補へ適用）。集約はgradient/wind_penalty/car_stress等を
  距離加重平均、road_surface_good等のカテゴリ値を距離加重多数決で代表値化し、
  `RouteSegmentDetail`型自体は変えない（フロント型・OpenAPI契約への影響なし）。
- **T274（周回ルートの逆回り候補評価）**: `evaluate_loops`は各方位につき、`trace_loop`が
  確定した順方向の経路に加え、同じ物理形状を逆順に辿る「逆回り」候補も合成できる場合は
  合成し、`distance_weighted_difficulty`（segmentsの距離加重平均）が低い方だけを最終候補
  として残す（両方向を別候補として追加はしない）。逆回りEdge列（`_reverse_traced_edges`）は
  `context.graph`から1リクエストにつき1回だけ構築する`(from_node_id, to_node_id) → Edge`
  逆引き表（`_RoadGraphContext.node_pair_index`）を使い、標高（`_reverse_elevation_attribute`、
  獲得標高↔喪失標高の入替・勾配の符号反転等の代数変換）も既に取得済みの順方向の値から
  導出するため、追加のDB問い合わせ・GSI標高APIの再呼び出しは発生しない
  （bearing_deg等の進行方向依存値のみ`context.graph`から引く。geometryは順方向で
  hydrate済みの値を反転して使う）。経路中に一方通行（逆方向Edgeが存在しない）区間が
  1つでもあれば逆回りは物理的に成立しないため、その方位は順方向のみを候補とする。

### 気象グリッドのRedis永続キャッシュ（`wind_forecast_cache.py`、改善計画T398）
`wind_forecast_cache.py`（[backend/app/infrastructure/wind_forecast_cache.py](../backend/app/infrastructure/wind_forecast_cache.py)）は、`WeatherClient.get_forecast_many`（下記）が、プロセス内メモリキャッシュ（L1、`_wind_forecast_cache`）でヒットしなかったキーだけをここ（L2）から引く2段構成のL2キャッシュ。プロセス再起動・コンテナ再作成をまたいで再利用する目的は変わらないが、2026-08-30（T398）にファイルベースのSQLite（旧`cache_db.py`、`backend/data/ridecompass_cache.db`）から、JMAアメダス連携（T387）で導入済みのRedisキャッシュ基盤（下記「Redisキャッシュ基盤とJMAアメダス連携」節）へ一本化した。理由は、同居するVM上に既にRedisが稼働しているため、SQLiteファイルという別系統の永続化を並行して維持する意義が薄れたこと。road_graph_tilesのRedis cache-asideと異なりPostGIS等の正本フォールバックは持たない（Open-Meteoへの再フェッチが常に可能なため）。キー`wind:forecast:{lat}:{lon}`・TTLは`WIND_GRID_STALE_FALLBACK_MAX_AGE_SECONDS`（24時間、下記）に合わせている。Redis自体が疎通不能な場合は空辞書を返すfail-openで、`WeatherClient`側は「未キャッシュ」として実フェッチへ進む（機能は止まらず、Open-Meteoへの再取得頻度が上がるだけ）。旧SQLite実装（`cache_db.py`、`test_cache_db.py`）は本移行で削除済み。

### 天候取得の設計と「地点＋時刻」対応（Step6）
`WeatherClient`（[backend/app/infrastructure/weather_client.py](../backend/app/infrastructure/weather_client.py)）はOpen-Meteo Forecast APIから`current`（現在の気象）と`hourly`（`forecast_days=2`分の時間別予報：気温・風速・風向・降水確率・weather_code/is_day）、`get_forecast`（単一地点、/api/weather用）はさらに`daily`（今日・明日の日次見通し：夜明け・日没・降水確率最大・最大風速・気温レンジ・UV指数最大、改善計画T385「今日の見通し」パネル用）を**1回のリクエストでまとめて取得**することを実機確認済み（`get_forecast_many`＝WindService用の複数地点一括取得は`daily`を含まず`hourly`もwind_speed_10m/wind_direction_10m/precipitationのみに絞る。クォータ削減のため意図的に変数を絞っており、日次見通し・天気アイコン・天気の流れはルート評価に使わないため）。hourlyのweather_code（T385フォローアップ）は「今日の見通し」パネルの天気の流れ（today_periods、観測時刻を含む2時間区間から2時間おき8コマ、T385フォローアップ2で固定6時始まりから現在時刻基準へ変更）が使う。標高と同じ「範囲でまとめて取得してキャッシュ」の原則を適用しているが、気象データは時間で変化するため**TTL付き**（`get_forecast`＝単一地点/api/weatherパネル用は30分、緯度経度は標高より粗い精度で丸める）にしている点が標高キャッシュとの違い。

`get_forecast_many`（複数地点をまとめて取得、風の格子点マップ・降水延長予報が使う）は、TTLを3時間・キャッシュをメモリ（L1、プロセス内、高速）＋Redis（L2、`wind_forecast_cache.py`、プロセス再起動をまたいで永続化。改善計画T398、旧SQLite）の2段構成にしている（T194〜T195、「改善計画」参照）。Open-Meteoが本番（Render、共有の送信元IP）で429を返す事象が繰り返し発生しており、L1のみだとプロセス再起動・コンテナ再作成のたびにキャッシュが消え無駄な再取得（＝日次クォータの消費）が発生していたため、再起動をまたいでも直前の値をL2から復元できるようにした。L1に無い/古いキーだけL2を引き、見つかった分（新鮮・陳腐問わず）をL1へ書き戻してから既存のTTL判定・障害時のstale fallback判定に合流させる設計のため、呼び出し側（`WindService`・`get_wind_grid`）のインターフェースは変わらない。

`WeatherService.get_conditions(point, at: datetime | None = None)`（[backend/app/services/weather_service.py](../backend/app/services/weather_service.py)）は、`at=None`なら`current`ブロックを返し、未来時刻を渡すと`hourly`配列から最も近い時刻のデータを検索して返す。**Step6のUIでは`at`を渡さず現在地の現在の天候のみ表示するが**、この時刻指定インターフェースにより、将来「ルート上の各サンプル点＋推定通過時刻（`RouteCandidate`の距離・所要時間から按分計算できる）」を渡して「2時間後にその地点は雨か」を判定する拡張が、サービス層の設計変更なしで追加できる（ユーザー要望への対応）。既知の制約: `at`が取得済みhourly範囲（当日+翌日）を超える場合、現状は最も近い時刻を返してしまう（範囲外チェック未実装）ため、`at`を実際に使う機能を追加する際にガードを入れる必要がある。

### 方位ラベルの共通化（Step6）
風向（Open-Meteoからは69°のような任意角度で返る）を8方位ラベルに変換する必要が生じたため、`route_generator.py`に8方位専用でハードコードされていた`DIRECTION_LABELS`辞書を廃止し、`domain/geo.py`の汎用関数`compass_label(bearing_deg: float) -> str`に統一した（周回ルート候補の方位ラベルも同じ関数を使う）。

### 風評価（`wind_score`）の設計（Step7）
Step6で`WeatherService.get_conditions(point, at: datetime | None = None)`を「地点＋時刻」対応にしておいたのは、まさにこのStep7のため。`WindService`（[backend/app/services/wind_service.py](../backend/app/services/wind_service.py)）は候補ルートのサンプル点列（`ElevationService`と同じ点集合。当初12点固定、現在は距離連動の約1km間隔・12〜32点）について、区間ごとに以下を行う。

1. 起点からの累積距離 ÷ 仮定巡航速度（`ASSUMED_SPEED_KMH = 20.0`、現状固定値。将来ユーザー設定可能にする拡張ポイント）で推定到達時刻を計算
2. 区間の進行方位を`domain/geo.py`の`bearing_between(a, b)`（新規追加、2点間の初期方位角を球面三角法で求める。`destination_point`の逆関数に相当）で算出
3. `WeatherService.get_conditions(point, at=推定到達時刻)`を各区間の始点について並列取得（`ElevationService`と同じ`asyncio.Semaphore`パターン。天候はTTLキャッシュ済みのため近接点は追加リクエストなしでヒットする）
4. `domain/wind.py`の`WindCalculator.wind_penalty(wind_speed_ms, wind_direction_deg, travel_bearing_deg)`＝`風速 × cos(風向 − 走行方位)`で区間ごとのペナルティを算出（`wind_direction_deg`は気象学の慣習で「風が吹いてくる方向」。走行方位と一致＝正面からの向かい風＝`cos(0)=1`で最大、180度差＝追い風＝`cos(180°)=-1`、90度差＝横風＝`cos(90°)=0`で走行への影響なし。進行方向に平行な風成分のみが影響するという物理的に妥当なモデル）
5. 区間距離で加重平均した値を`wind_score`（符号付きm/s、正=正味向かい風、負=正味追い風）として`RouteCandidate`にマージ

天候取得に失敗した区間はスキップし、有効な区間が無い場合は`wind_score=None`（標高と同じ「取得失敗は握りつぶしてnull」方針）。既知の制約: 推定到達時刻の計算は「サーバーのローカル時刻＝Asia/Tokyoのその時刻」という簡易近似（Open-Meteoの`hourly`もタイムゾーン付きでなくAsia/Tokyoのnaiveなローカル時刻文字列を返すため整合はしている）。`wind_score`は正規化・重み付けされていない生の物理量で、`RouteCandidate`へそのまま残る（Step8時点の重み付け先だった`total_score`は改善計画T548で撤去済み、次節参照）。

### 路面評価（`road_score`）と総合スコア（`total_score`）の設計（Step8、**改善計画T548・2026-09-03で総合スコアリング部分を撤去**）
道路特性（`road_weight`）はOSM/Overpassの実データ連携が将来課題として残っていたが、openrouteserviceの`extra_info`パラメータを調査した結果、`cycling-road`プロファイルが`extra_info: ["surface"]`に対応しており、Step4-7から既に呼んでいるルート取得リクエスト（`ORSClient.get_directions`）1回に相乗りする形で、追加APIコールなしに区間ごとの路面種別内訳（`properties.extras.surface.summary`、`{value, distance, amount}`の配列。`value`はOSMのsurfaceタグ相当の0-18の路面種別ID）が取得できることが分かった。これにより当初のスコアリング設計（距離・標高・風・道路の4要素）をStep8内でそのまま実装できた。

- **`road_score`の算出**: `RoutingService.get_route`が`feature["properties"]["extras"]["surface"]["summary"]`を`RouteSegment.surface_summary`としてパースし（無くても`None`で許容、必須フィールドの欠如とは扱いを分けている）、`route_generator._build_candidate`で候補生成と同時に`domain/road.py`の`paved_percent(surface_summary)`を呼んで`road_score`（走行しやすい舗装路面＝Paved/Asphalt/Concrete/Paving Stones＝ID 1,3,4,14の`amount`合計、0-100%）を算出する。標高・風とは異なり別サービス呼び出しが不要な同期計算。`RouteCandidate.road_score`フィールド自体は現在も残る（研究インターフェースの物理量表示用、後述`ComparisonPanel`参照）。
- **重みの方向（Step8当時）**: 距離は目標との差が小さいほど高得点、獲得標高は小さいほど高得点（MVPでは「走りやすさ」優先の解釈。ヒルクライム志向のユーザー向けに反転する余地は将来課題）、`wind_score`は小さい（追い風寄り）ほど高得点、`road_score`は舗装率が高いほど高得点。
- **`RouteScorer`（撤去済み）**: 旧`backend/app/services/route_scorer.py`が`score(candidates, target_distance_km)`でdistance/difficultyの2指標を候補集合内min-max正規化し、旧`backend/app/scoring.yaml`の重みで加重合成して`total_score`（`RouteCandidate.total_score`・`score_breakdown`）を算出していた（**改善計画T401**でelevation/wind/roadの個別ハードコード計算から`overall_difficulty`ベースの2指標へ単純化した経緯を持つ）。ユーザーから「おすすめ度の数字が極端で、ルート生成ロジックの距離誤差でほぼ決まっており参考にならない」という指摘を受け、**改善計画T548（2026-09-03）でtotal_score算出機構（`RouteScorer`・`domain/scoring.py`・`scoring.yaml`・`RouteCandidate.total_score`/`score_breakdown`・API境界の`scoring_weights`/`ScoringWeights`・フロントの`WeightPanel`）を丸ごと撤去**した。
- **最終ソート順（改善計画T548で変更）**: `RouteGenerator.generate_loops`/`generate_via_waypoints`の返却順は、旧`total_score`降順から**`overall_difficulty`（絶対基準0-100の総合難易度）昇順**（易しい候補が先頭、算出不能な`None`は末尾）へ変更した。この基準は異なるリクエスト間でも比較可能な絶対値のため、候補集合内でしか意味を持たなかった旧`total_score`降順より単純で分かりやすい。

既知の制約: 路面データはOSMの`surface`タグが付与されていない区間があると実態より低く出る可能性がある。

**（後日追加: 改善計画T21・2026-08-15で撤去）** ここまでに書いたopenrouteservice `extra_info=surface`・`RouteSegment.surface_summary`・`paved_percent`は、評価のエンジン非依存化（後述「ルーティングエンジンの切り替え対応」）に伴い撤去済み。`road_score`は現在、両エンジンとも`domain/road.py`の`classify_osm_surface`（OSMタグ語彙）と`distance_weighted_road_score`（距離加重集計、共通関数）で算出する。ORSエンジンはサンプル点を`RoadGraphRepository.get_nearest_surface_tags`で自前DBのEdgeへ空間マッチしてタグを読む（詳細は後述）。

### 候補ルートの難易度可視化の設計（Step9）
`total_score`は候補集合内の相対評価のため、数値だけでは「具体的にどこが走りにくいのか」が分からない。ユーザーからの要望で、候補選択時に地図上へ標高・風・路面を時系列（区間ごとの推定到達時刻）も考慮したレイヤーとして重ね描きし、走破の易しい/難しい区間を色分けする機能を追加した。

- **データ取得方針**: Step5-7-8で候補ごとに12点サンプリングして取得していた標高・風・路面の生データは、集約値（`elevation_gain_m`等）だけを残して区間ごとの詳細を捨てていた。Step9はこれを**捨てずに`RouteCandidate.segments`として返す**だけで実現しており、追加のAPIコール（GSI/Open-Meteo/openrouteservice）は一切発生しない。
- **サンプル点の共有化**: `ElevationService.get_profile`と`WindService.get_wind_score`はそれぞれ独立に`sample_line_coordinates`を呼んでいたが、区間ごとの標高・風・路面を1つの配列としてインデックス整合させるため、`route_generator.py`が`sample_line_points(geometry, SAMPLE_COUNT)`（新規、`domain/geo.py`。座標だけでなく元geometry内でのインデックスも返す）で一度だけ点を取得し、両サービスに共有するようリファクタした。シグネチャも`get_profile(points)` / `get_wind_profile(points, start_time)`に変更（`geometry`ではなく点列を直接受け取る）。
- **路面の位置対応（2026-08-15、改善計画T21で撤去・置換）**: 当初はopenrouteserviceの`extras.surface.values`（`[[start_idx, end_idx, surface_id], ...]`）を`RouteSegment.surface_values`として保持し`surface_id_at_index`で求めていたが、現在はサンプル点を`RoadGraphRepository.get_nearest_surface_tags`で自前DBのEdgeへ空間マッチして`classify_osm_surface`で判定する方式に統一済み（後述「ルーティングエンジンの切り替え対応」）。
- **難易度の算出（絶対基準）**: `domain/difficulty.py`が、Step8の相対正規化とは異なり**絶対基準**（一般的なロードバイク走行の目安）で0-100点化する。`gradient_difficulty`（0-3%易しい〜9%以上激坂の区分的線形）、`wind_difficulty`（向かい風0-8m/sで0→100、追い風・無風は0）、`road_difficulty`（舗装路0・非舗装80、`domain/road.py`の`GOOD_SURFACE_IDS`と基準を統一）、`composite_difficulty`（重み付き平均、`None`の指標は除外して残りの重みで再正規化）。当時（Step9時点）は重みをStep8の旧`scoring.yaml`から`distance_weight`を除いた`elevation_weight`/`wind_weight`/`road_weight`のまま流用していたが、現在の重みの単一の情報源は`domain/axis_definitions.py: AXIS_DEFINITIONS`の`default_weight`（改善計画T316）である（旧`scoring.yaml`自体が改善計画T548で撤去済み）。地図の色分け・候補タブの並び順は「候補間の相対比較」ではなく「客観的にどこが大変か」を示す目的のため、Step8のような候補集合内正規化ではなく絶対基準を採用した（改善計画T548で候補タブの並び順もこの絶対基準＝`overall_difficulty`昇順へ統一）。
- **`RouteSegmentDetail`**（`domain/route.py`、`RouteCandidate.segments`）: 区間の始点/終点座標・累積距離・推定到達時刻に加え、表示用の生値（`gradient_percent`, `wind_penalty`, `road_surface_good`, `car_stress`）と正規化済みの軸別内訳（当初のStep9時点は`elevation_difficulty`等の固定4〜7フィールドだったが、改善計画T309で`axis_difficulties`＝axis_id→difficultyの汎用dict＋総合の`difficulty`へ置換済み。正準定義は下記「6. データモデル」の`RouteSegmentDetail`インターフェース参照）を両方保持する。正規化済みの値をフロントに渡すことで、閾値ロジックをフロント側に複製せず、UIは常に「0-100→緑〜赤」の単一の色変換関数だけで済む。
- **フロントエンド**（当初実装）: 選択中候補に`segments`があれば区間ごとの色分けレイヤーを追加し、モード切替ボタン（総合難易度/標高/風/路面）で`line-color`を切り替える形にした。この設計は後述のUI再構成でレイヤー構成ごと見直している。

既知の制約と改善（区間表示の粒度・形状）: 当初はサンプリング密度が12点固定（＝11区間、Step5-7と同じ）で、30kmルートでは1区間約2.7kmと粗く、さらに区間の線は始点・終点を直線で結んでいたためカーブ区間で色分け線が道路から外れていた。「区間が荒すぎて実態が分からない」というフィードバックを受け、次の2点を改善した（2026-08-15）: ①**区間の道なり形状**: `RouteSegmentDetail.geometry`にルートgeometryの部分列（サンプル点インデックスで切り出し。road_graphエンジンはEdge形状点列）を持たせ、フロントはそれをそのまま描画する（追加APIコール無し。geometryがnullの場合のみ従来の直線代替）。②**距離連動サンプリング**: `sample_count_for_distance`（openrouteservice_engine.py）が約1km間隔になるよう点数を決める（下限12点=従来密度、上限32点=外部API問い合わせの安全弁。最悪でも8候補×32点=256 GSIリクエスト/生成。風はTTL＋座標丸めキャッシュにより点数増の影響がほぼ無い）。密度をさらに上げる場合はGSI問い合わせ数とのトレードオフになる（DEMタイル化T10が根本対策）。

### UI再構成: サイドバー＋地図レイヤーの静的/動的分離
Step9の可視化はモード切替（総合難易度/標高/風/路面のいずれか1つ）＋選択中候補のみという設計だったが、ユーザーから「データの性質（時間で変わる/変わらない）によって持ち方・見せ方を分けたい」「左に操作パネル、右に地図」という要望を受け、UIを再構成した。

- **レイアウト**（[frontend/src/app/page.tsx](../frontend/src/app/page.tsx)）: `display:flex; height:100vh`のルート要素の下に、折りたたみ可能な`<aside>`（左サイドバー: タイトル・`WeatherPanel`・`LocationControl`・`MapLayersPanel`・`RouteForm`・候補ごとのタブ（`RouteAxisProfile`、改善計画T545）・`BackendStatus`等）と`flex:1`の地図ペイン（`MapView`＋地図上の`MapOverlayControls`）を並べる。位置情報（現在地取得・手動入力）の状態は`MapView`から`page.tsx`（`Home`）に引き上げ、`MapView`は`location`等をpropsで受け取る「地図描画に専念する」薄いコンポーネントにした。
- **レイヤー構成の分離**（[frontend/src/components/Map/MapView.tsx](../frontend/src/components/Map/MapView.tsx)）: 4種類のMapLibreレイヤーを常設する構成に変更。
  1. `route-candidates-line`（既存）: 全候補のベース表示（amber未選択/blue選択）。`staticLayer==="none"`のときのみ表示。
  2. `route-static-segments-line`（新規）: **全候補**のセグメントを`elevation_difficulty`/`road_difficulty`で色分け。選択に関わらず常時利用可能（`MapOverlayControls`のチェックボックスでON/OFF）。
  3. `route-selected-outline-line`（新規）: 選択中候補の全体ジオメトリを太め・低不透明度のハローで最背面に描画し、①②のどちらの表示中でも選択中候補を常時識別できるようにする（**訂正・改善計画T518/T524（2026-09-01）**: この「常時」は本節が書かれた時点の設計。T518以降は候補線・方向矢印と合わせ、地図上「ルート」チップ[`layerVisibility.route`]のON/OFFに連動する——チップOFFで完全非表示になる、詳細は[docs/tasks/T518.md](tasks/T518.md)参照）。
  4. `route-detail-segments-line`（既存を単純化）: 選択中候補のみ、色分けモード（`routeStyleModes.ts`。改善計画T440時点では軸スタジオの`supports_route_coloring`軸から動的生成される各モード＋固定の総合難易度[`difficulty`]。いずれも`segments`に返却済みの値のみ使い追加取得なし）で色分け。ルートレイヤーがONかつ選択中候補にセグメントがある場合のみ表示（一時期は風のみに絞っていたが、その後勾配を追加し、研究インターフェース改善 §10-5で路面・総合難易度も追加、T440でモード集合自体が動的化された）。
  - ①②は`visibility`レイアウトプロパティで排他的に切り替え、③は（本節が書かれた時点では）常時、④は最前面（③の現状はT518/T524の訂正注記参照）。クリック/ホバーの`queryRenderedFeatures`は②④の両方を対象にし、②のポップアップには所属候補が分かるよう`direction_label`を付与している。
- **静的レイヤーのON/OFF**: 「標高図」「路面」はそれぞれ独立にON/OFFできる。当初は同じ線の色を奪い合うという理由で`staticLayer: "none" | "elevation" | "road"`の単一値による排他制御にしていたが、Step10で標高がラスタタイル表示に変わったことで色の競合が解消されたため、Step10改訂時に独立制御へ変更した（詳細は後述の「地域レイヤー」設計を参照）。ON/OFFの操作UIはその後のUI再構成（第2段、後述）で地図上のチップ＋サイドバーのスイッチに変わったが、「独立して同時表示可」という性質は変わっていない。
- **`isStyleLoaded()`起因の描画スキップ**: 実装時、地図初期化直後や候補選択直後にレイヤーが表示されない不具合が実機確認（Playwright）で見つかった。原因は、各描画関数が使っていた「`map.isStyleLoaded()`がfalseなら`map.once("load", ...)`で待つ」というガード。`isStyleLoaded()`は初期スタイル読み込み後もタイル読み込み中は一時的にfalseを返すが、MapLibreの`load`イベントは初回読み込み時に一度しか発火しない。そのため、候補選択でカメラが動いてタイル読み込み中に描画関数が呼ばれると、`isStyleLoaded()===false`と判定されて`once("load", ...)`を登録するが、その`load`はもう二度と来ず、描画が永久にスキップされていた。スタイルが一度でも読み込まれたかどうかをmapインスタンス自身にフラグとして記録する`runWhenStyleReady`ヘルパーに置き換えて解消した。

### UI再構成（第2段）: 地図上はON/OFF＋条件サマリ、細かな設定はサイドバーへ集約

「細かな設定はサイドバーで実施し、地図画面ではON/OFFと適用中の条件が簡潔に分かる程度にしたい」「今後の静的レイヤー追加（交通ストレス等、[static-road-attributes-plan.md](static-road-attributes-plan.md)）や動的レイヤー追加（天候等）を汎用的にやりやすくしたい」という要望を受け、レイヤー操作UIを再構成した（2026-08-15）。

- **レイヤーカタログ**（[frontend/src/components/Map/mapLayers.ts](../frontend/src/components/Map/mapLayers.ts)、新規）: 各レイヤーの`id`/`label`/`kind`（static=地域固定・時間で不変 / dynamic=ルート・時間で変わる）/`description`を宣言する単一ソース。地図上のチップ行とサイドバーのセクション枠はこの配列の列挙で描画されるため、レイヤー追加は「カタログに1エントリ＋`page.tsx`に初期値とサマリ対応＋`MapLayersPanel`にセクション中身」で済む（詳細手順は同ファイル冒頭コメント）。
- **地図上**（[frontend/src/components/MapOverlayControls/MapOverlayControls.tsx](../frontend/src/components/MapOverlayControls/MapOverlayControls.tsx)）: ON/OFFチップ行と、ONのレイヤーに効いている条件の1行サマリ（例:「路面: アスファルトのみ／幹線道路以外」「ルート: 色分け: 風の影響」。路面はズーム不足の案内を優先）だけを置く。サマリのタップでサイドバーが開き、該当レイヤーの設定セクションへスクロール・フォーカスする（`layerSectionDomId`）。旧実装にあった⚙ボタン＋絞り込みモーダル（`RoadFilterDialog`）は廃止。コンポーネント自体はレイヤー固有の知識を持たない汎用描画係になった（レイヤー追加時に変更不要）。サマリ文言は`legendFilter.ts`の`summarizeLegendFilters`（軸の凡例定義だけに依存する汎用関数）が生成する。
- **サイドバー**（[frontend/src/components/MapLayersPanel/MapLayersPanel.tsx](../frontend/src/components/MapLayersPanel/MapLayersPanel.tsx)、新規。旧`MapLegendPanel`と旧`RoadFilterDialog`を統合して置き換え）: `kind`ごとのグループ見出し（「地域レイヤー（変わらないデータ）」「ルートレイヤー（時間・選択で変わるデータ）」）の下に、レイヤーごとのセクション（見出し＋表示スイッチ＋凡例・設定）を並べる。路面の絞り込み編集は`RoadFilterEditor`（同ディレクトリ）が担い、モーダル時代の**下書き→適用**方式を維持する（チェックのたびに地図へ即時反映すると複数条件の組み合わせ編集がしづらい、という過去のフィードバックによる。ルート凡例のような単純なチェックは即時反映のままで使い分け）。絞り込みはOFF中でも編集でき、適用するとレイヤーが自動でONになる（旧ダイアログと同じ挙動）。
- **状態管理**（`page.tsx`）: レイヤーON/OFFは個別のuseState（`showElevation`等）から`layerVisibility: Record<MapLayerId, boolean>`へ一般化した。`MapView`のprops（`showElevation`/`showRoad`/`routeLayerOn`）は従来のまま`layerVisibility`から導出して渡すため、`MapView.tsx`は無変更。

### 地域レイヤー（標高・路面の常時オーバーレイ）と地図タイルキャッシュの設計（Step10）
Step5-9で実装した標高・風・路面はいずれも「生成済みの候補ルート沿い」に限定した評価だった。ユーザーから「候補を出す前に、そもそもどのあたりが走りやすい地形・路面なのか地図で見たい」という要望を受け、候補ルートの有無に関わらず**表示中の地図の範囲全体（ビューポート）**に標高・路面を重ね描きする機能を追加した。

#### 標高オーバーレイ（国土地理院 色別標高図、ラスタタイル）
初期実装では、標高もリクエストされたbboxを固定間隔（約500m）のグリッド点に分解し、既存の`ElevationClient`（Step5と共通の国土地理院標高API）へ問い合わせて`circle`レイヤーの点として描画していた。しかし実際にブラウザで確認したところ「疎らな点では地形の起伏が直感的に分かりにくい」ことが分かり、標高の点取得・グリッド生成・専用APIエンドポイント（`GET /api/region/elevation`）は撤去し、代わりに国土地理院が公開する**色別標高図**（ラスタタイル、`https://cyberjapandata.gsi.go.jp/xyz/relief/{z}/{x}/{y}.png`、APIキー不要、zoom 5-15）をMapLibreの`raster`ソースとして`MapView.tsx`が直接重ね描きする方式に変更した。

- **バックエンドを介さない**: 地理院タイルはブラウザへの直接埋め込みを想定して公開されているため、基礎地図タイル（OpenFreeMap）のようなプロキシ・キャッシュ層を設けていない。地理院タイルのオリジン（`cyberjapandata.gsi.go.jp`）は基礎地図タイル用に分離したフロントエンドオリジン（`:3000`）・API呼び出し用のバックエンドオリジン（`:8000`）のいずれとも異なるため、ブラウザのオリジン単位の同時接続数上限が競合する心配もない。
- **レイヤー順序**: `ensureGsiReliefLayer`（`MapView.tsx`）は地図初期化直後（他のカスタムレイヤーより先）に一度だけソース/レイヤーを追加し、以降はvisibilityの切替のみで表示・非表示を行う。先に追加しておくことで、後から追加される路面・ルート系のレイヤーが必ずこのラスタの上に重なり、道路線やラベルが標高オーバーレイに隠れないようにしている。不透明度は0.55で、基礎地図の道路・ラベルが透けて見える程度に抑えている。
- **ビューポート制限は不要**: 標高グリッドAPI（撤去済み）はGSIの点別APIへの問い合わせ数を抑えるため`MAX_REGION_DIAGONAL_KM`のズーム制限を課していたが、ラスタタイルはズームレベルに応じてタイルが自動的に切り替わる標準的なXYZタイルのため、この種の制限は不要になった（後述の路面データのみ制限が残る）。

#### 路面データ：自前生成のベクタタイル（`GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf`）
標準的なXYZベクタタイル（MVT）として配信する（当初はビューポート単位のGeoJSON→固定グリッドセルキャッシュ、その後Overpassのタイル単位問い合わせを経て、現在はPostGIS第一系統。経緯は[decisions/pre-static-attributes-gate.md](decisions/pre-static-attributes-gate.md)参照）。

- **タイル範囲の算出**: `domain/region.py`の`tile_bounds_lonlat(z, x, y)`が、標準的なスライピータイル座標式（Web Mercator）からタイルが覆う緯度経度範囲を求める。MapLibre自身が使うタイル座標系そのものなので、キャッシュの単位とMapLibreが要求するタイルが一対一に対応する。
- **MVT生成**: `RegionService.get_road_surface_tile(z, x, y)`（[backend/app/services/region_service.py](../backend/app/services/region_service.py)）が、`repository`（PostGIS、`road_graph_use_repository=true`時）を渡されていればまずPostGIS側（`road_graph_repository.py`の`_ROAD_SURFACE_TILE_MVT_SQL`、`ST_AsMVT`）へ問い合わせる。要求タイルのz12祖先タイルが取込済みマークされていれば、SQL側でMVTバイナリまで丸ごと生成して返す（Pythonでの再エンコードは発生しない）。カバレッジ外・DB障害・`repository`未接続（DBなし構成）の場合は、`infrastructure/vector_tile.py`の`encode_empty_road_surface_tile`が返す道路フィーチャ0件の空タイルにフォールバックする（Overpassへの問い合わせは改善計画T22で撤去済み。ログ方針: 常時WARNING）。
- **永続化層**: 生成したタイル（PBFバイナリ）は、**基礎地図タイルと同じファイルキャッシュ**（`infrastructure/tile_cache.py`、`region/road-surface/v{ROAD_SURFACE_TILE_VERSION}/{z}/{x}/{y}.pbf`というパスで保存）にキャッシュする。「地図データを再読み込み」ボタン（`POST /api/basemap/refresh`）を押すと基礎地図タイルと路面タイルの両方が一括でクリアされる（同じ`tile_cache.clear_all()`を共有しているため）。空タイル（カバレッジ外・DB障害）はキャッシュに保存しない（後からPBF取込された際に正しいタイルを再生成できるようにするため）。
- **安全弁**: bbox対角距離の代わりに、`domain/region.py`の`ROAD_TILE_MIN_ZOOM = 12` / `ROAD_TILE_MAX_ZOOM = 15`でズーム範囲を制限する。`api/routes.py`のエンドポイントはこの範囲外のzを400で拒否する（直接APIを叩かれた場合の安全弁。通常はMapLibre自身がvector sourceの`minzoom`/`maxzoom`設定によりこの範囲外のタイルを要求しないため、二重の防御になる）。標高（ラスタタイル）にはこの制限を適用していない。

#### 地図タイルのバックエンド経由プロキシ＋キャッシュ
`BasemapClient`（[backend/app/infrastructure/basemap_client.py](../backend/app/infrastructure/basemap_client.py)）がOpenFreeMap（`tiles.openfreemap.org`）のスタイルJSON・TileJSON・スプライト・グリフ・タイルを透過的にプロキシしつつ、ファイルシステム（`backend/data/tile_cache/`、[backend/app/infrastructure/tile_cache.py](../backend/app/infrastructure/tile_cache.py)）にキャッシュする（`GET /api/basemap/{path:path}`）。

- **同一オリジン維持とURL書き換え**: レスポンスがJSON（スタイルJSON/TileJSON）の場合、内包するOpenFreeMap本体への絶対URLを、自分自身（`settings.basemap_public_base_url`、既定値`http://localhost:3000/api/basemap`）への絶対URLに書き換えてから返す。MapLibreは相対URLをスタイル自身の取得元ではなく**ページのオリジン**に対して解決してしまう（spriteURLに至っては相対URLを明示的に拒否する）ため、絶対URLへの書き換えが必須。書き換え先はバックエンド自身のURL（`:8000`）ではなく、フロントエンドのURL（`:3000`）であることに注意（後述の接続数上限の問題を避けるため）。
- **既知の制約（キャッシュとURL書き換えの整合性）**: URL書き換え後の内容をそのままファイルキャッシュするため、`basemap_public_base_url`の設定値を変更しても、既にキャッシュ済みのスタイルJSONには古いURLが埋め込まれたまま残り続ける（キャッシュ自体は書き換え元の設定値を記録していないため、値の変更を自動検知できない）。実際に開発中、デバッグのため一時的にバックエンドへ直接アクセスする設定に切り替えた際、キャッシュに`:8000`のURLが焼き付いたまま残り、設定を正しい値（`:3000`）に戻した後もキャッシュ経由で古いURLが返り続ける事象を確認した。「変わらないデータを更新」ボタン（`POST /api/basemap/refresh`、`tile_cache.clear_all()`）でキャッシュを全消去すれば解消する。
- **同時接続数上限との競合（実機確認で発見・回避済み）**: 当初、地図タイルもAPI呼び出しもバックエンドの同一オリジン（`:8000`）から直接取得する構成を試したところ、地図初期化時に発生する数十件のタイル/フォント/スプライトリクエストがブラウザのオリジン単位の同時接続数上限（HTTP/1.1で6本程度）を埋めてしまい、ルート生成等のAPI呼び出しが数十秒単位で詰まる現象を確認した。対策として、Next.jsの`rewrites()`（[frontend/next.config.ts](../frontend/next.config.ts)）で`/api/basemap/*`と`/api/region/road-surface-tiles/*`（路面ベクタタイル、Step10改訂で追加）の両方をバックエンドへプロキシし、ブラウザからは常にフロントエンドと同一オリジン（`:3000`）に見えるようにした。これにより「タイル群（`:3000`経由）」と「API呼び出し（`:8000`直接）」が別オリジン扱いになり、接続枠が競合しなくなる。**フロントエンド側は`MapView.tsx`の`MAP_STYLE`定数（相対パス`/api/basemap/styles/liberty`）でこのrewriteを経由する必要があり、デバッグ目的で一時的にバックエンドへの絶対URLに変更した場合は元に戻し忘れないよう注意**（実際に前回セッションで戻し忘れており、動作確認時に発見・修正した）。
- **Windowsでのパスフラット化**: OpenFreeMapのURL構造には`planet`（TileJSON本体）と`planet/<version>/{z}/{x}/{y}.pbf`（実タイル）のように、同じセグメントがファイルとディレクトリ接頭辞の両方として使われるケースがある。パスをそのままディレクトリ階層にミラーリングすると、Windowsでは「同名のファイルがあるためディレクトリを作成できない」というエラーで実際にクラッシュすることを実機確認したため、`tile_cache.py`はパスをSHA-256でハッシュ化しフラットなファイル名（`<hash>.bin` / `<hash>.meta`）で保存する。副次的にディレクトリトラバーサル対策にもなる。
- **イベントループのブロッキング回避**: `tile_cache`の読み書きは同期的なディスクI/O。基礎地図読み込み時は数十件のタイル/フォントリクエストが同時に来るため、`asyncio.to_thread`を介さず直接呼ぶとイベントループ全体をブロックし、同時に処理中の他のリクエスト（ルート生成等）が数十秒単位で詰まることを実機確認した。`BasemapClient.get`・`RegionService.get_road_surface_tile`はいずれも`tile_cache.get`/`set`を必ず`asyncio.to_thread`経由で呼ぶ。
- **ベクタタイルの取得はWeb Worker内で行われる（実機確認で発見・修正済み）**: MapLibreはラスタタイル（`Image`要素、メインスレッド）とベクタタイル（`fetch`、Web Worker内）でタイルの取得方法が異なる。ラスタタイルのURL（`MAP_STYLE`や地理院タイルのURL）は相対パス・絶対パスいずれもページのオリジンに対して解決されるが、ベクタタイルのURLをWorker内から相対パスのまま渡すと`Failed to construct 'Request': Failed to parse URL from ...`のエラーで取得自体が失敗することを実機確認した（Workerの実行コンテキストはページとは別のベースURL解決になるため）。そのため路面ベクタタイルのURLは`window.location.origin`を使って呼び出し時に明示的に絶対URL化している（[frontend/src/services/regionApi.ts](../frontend/src/services/regionApi.ts)の`roadSurfaceTileUrl()`）。`window`はクライアントサイドでのみ参照可能なため、モジュール読み込み時に評価される定数ではなく、呼び出し時に評価される関数として実装してある点に注意（Next.jsのクライアントコンポーネントも初回はサーバー側でレンダリングされるため、モジュールの最上位で`window`を参照するとSSR時にクラッシュする）。

#### フロントエンドの表示制御（`MapView.tsx`）
標高・路面は「変わらないデータ（表示中の地域全体）」として、選択中候補とは独立にON/OFFする（操作UIは「UI再構成（第2段）」参照。`MapView`へは従来どおり`showElevation`/`showRoad`のpropsで渡る）。標高がラスタタイル表示になったことで路面の線と色を奪い合わなくなったため、**両者は排他ではなく同時にON/OFFできる**（初期実装では同じ線の色を奪い合うため`staticLayer: "none" | "elevation" | "road"`の単一値で排他制御していたが、Step10改訂時に独立制御へ変更した）。標高・路面のいずれも、表示切替時はレイヤーのvisibilityを切り替えるだけ（`setGsiReliefVisibility` / `setRoadSurfaceTileVisibility`）で、明示的なデータ取得コードは書いていない。路面がベクタタイルになったことで、Step10当初にあった「地図の`moveend`イベント（パン/ズーム終了、500msデバウンス）を検知してビューポートのbboxを`/api/region/road-surface`にfetchする」という独自ロジックは丸ごと不要になった。タイルの取得・キャッシュ・パン/ズームへの追随はすべてMapLibre自身が面倒を見るため、フロントエンドのコードはソースを一度登録するだけでよい（標高ラスタと全く同じ扱いになった）。「表示範囲が広すぎます」の案内も、bbox対角距離の計算ではなく、路面ベクタタイルの`minzoom`（`ROAD_TILE_MIN_ZOOM = 12`）と`map.getZoom()`を比較するだけの単純な判定（`updateRoadZoomHint`）に置き換わった。判定は`zoom`イベントと表示切替の両方をトリガーに行う（標高はラスタタイルのためこの判定の対象外）。

既知の制約: PostGIS未取込範囲（またはDBなし構成）は常に空タイルになるため、その範囲では路面レイヤーが表示されない（Overpassフォールバックは改善計画T22で撤去済み）。取込済み範囲内であれば初回表示から高速（`ST_AsMVT`でPostGIS側がMVTバイナリまで生成するため、Pythonでの追加エンコード処理を挟まない）。

#### JMA動的タイル系レイヤーのバックエンド経由プロキシ＋キャッシュ（改善計画T412）
`JmaTileClient`（[backend/app/infrastructure/jma_tile_client.py](../backend/app/infrastructure/jma_tile_client.py)）が降水ナウキャスト・降水短時間予報（rasrf）・雷/竜巻ナウキャスト・キキクル・線状降水帯予測マップ（下記「動的気象レイヤー」節参照）が使うJMA bosaiエンドポイント（時刻一覧JSON・ラスタタイルPNG）を`BasemapClient`と同じ「pathを丸ごとプロキシ」方式（`GET /api/jma-tile/{path:path}`、`next.config.ts`の`/api/jma-tile/*`rewritesで同一オリジン化）でプロキシする。

- **経緯**: 従来これらは各ユーザーのブラウザがJMAの非公式内部API（`https://www.jma.go.jp/bosai/...`）へ直接fetchしており、バックエンド・キャッシュを一切経由しなかった。T410（キキクル）の実機フィードバック検討中、「防災級の情報は常時ONにすべきでは」という指摘を受け、常時ON化の前提として「利用者数に比例してJMAへの負荷が線形に増えない構成」への切り替えが必要と判断し、ユーザー方針「動的なデータはなるべくバックエンド経由に」に沿って実施した。
- **キャッシュ戦略の分岐**: `BasemapClient`のOpenFreeMapタイルと異なり、JMA側は2種類の更新頻度が混在する。①ラスタタイル本体（`basetime/validtime/z/x/y`が確定した時点で内容が不変）は`tile_cache.py`の永続ファイルキャッシュへそのまま乗せる。②`targetTimes*.json`（数分〜数十分単位で更新される時刻一覧）を同じ永続キャッシュへ乗せると更新後も古い内容を無期限に返し続けてしまうため、`jma_warning_client.py`と同じ`cachetools.TTLCache`（プロセス内、TTL=2分）を別途用意し、パスの末尾が`targetTimes*.json`かどうかで振り分ける。
- **横展開の検討と対象外の判断**: JMA以外に同様の直接fetchが無いか調査した結果、国土地理院の色別標高図タイル（`cyberjapandata.gsi.go.jp`、`MapView.tsx`）のみ該当したが、これは「ブラウザからの直接埋め込み利用を前提に国が公開している正式なAPI」であり、JMAの「非公式の内部API」への配慮とは動機が異なるため対象外とした（Open-Meteo・基礎地図・路面/事故/POIタイルは既にバックエンド経由のためそもそも対象外）。ただし色別標高図は時刻に依存しない静的データのため、レスポンス速度向上目的の永続キャッシュ化は別途軽量タスクとして検討する余地がある。

### 動的気象レイヤー（風・降水延長予報）の共通契約（改善計画T170〜T195）

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
  kind）しか持てなかったため、風の評価軸penalty面表示（`windPenaltyFill`、windVectorの矢印と
  同時表示が必要）がこの機構を迂回した個別実装になっていた。`DynamicWeatherGroupState`
  （ソースキー→`{visible, payload}`）を導入し「1グループ＝複数の名前付きソース、各ソースが
  独立してkind/payloadを持てる」形へ一般化したことで、`windPenaltyFill`を汎用機構へ統合し
  （`windVector`グループの`arrow`+`penaltyFill`の2ソース）、線状降水帯予測マップも
  `precipitationNowcast`グループの4つ目のソース（`linearRainband`、既存3段=`main`と独立に
  重畳）として実現した（詳細は下記「キキクル・線状降水帯予測マップ」節参照）。
  新しい動的要素の追加は「①`domain/wind_grid.py: WindGridPoint`へ値フィールド追加＋
  `weather_client.py: WIND_GRID_VARIABLES`へOpen-Meteo変数追加（フェッチは相乗り）
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
  `weather_client.get_forecast_many`（CC-BY-4.0、TTLキャッシュ・429リトライ込み）で
  まとめて取得する。フロントは結果をMapLibre標準のGeoJSON source + symbolレイヤーで描画
  （矢印アイコンは`MapView.tsx: createWindArrowIcon`が独自定義。当初はヒートマップ状の
  背景セル塗り（T180）も併用していたが、「背景色が他レイヤーと重なると見分けにくい」
  フィードバックを受け撤去し、現在は矢印の大きさ・色コントラストのみで密度を表現する）。
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
  全地点で共通であり、以前は624地点ぶん同じ`times`配列を複製していた（非圧縮応答の
  約54%を占めていた、実測）。バックエンドはGZipMiddlewareを持たないため本番でも
  非圧縮配信の可能性が高く、圧縮下でも実害は限定的というレビュー時の想定を覆す形と
  なったため実装した。フロント内部（windLayer.ts/useWeatherGrid.ts/precipitationNowcast.ts）
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
  [T410](tasks/T410.md)で実装）の行が混在するため、`elements.includes("rasrf")`で
  絞り込んだ上で「異なるvalidtimeを複数持つ最新のbasetime」を選ぶ（`fetchRasrfFrames`）。
  ②+15時間より先（〜約48時間先）は上記の風と同じ格子点マップへ`precipitation`（mm/h）を
  相乗りさせ、`gridFill`表現（格子をセルとして塗る）で継ぎ足す。1回のフェッチで風・
  延長予報の両方を賄うためOpen-Meteoクォータは増えない。各段は前段の最終フレームより
  後の時刻だけを採用し、近い将来の二重表示を避ける（ナウキャスト→rasrf→延長予報の
  2つの境界とも同じロジック、`precipitationFrames`）。
- **雷ナウキャスト・竜巻発生確度ナウキャスト（T204）**: [frontend/src/components/Map/thunderNowcast.ts](../frontend/src/components/Map/thunderNowcast.ts)が
  降水と同じbosai/jmatile/data/nowc/系（プロダクトコード`thns`＝雷・`trns`＝竜巻）を
  `rasterTile`表現のみで重ねる。降水と異なり`targetTimes_N3.json`1本に実況〜+60分の予測が
  同居し（N1/N2のような分割が無い）、Open-Meteo側に相当するデータが無いため延長予報は
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
    `layerVisibility`自体を持たない）へ変更した。以前は「12時間後の雷が常時マップに警告
    されているのは嫌」という実機フィードバックを受け「共有タイムラインのスライダーが
    『現在』位置にある間だけ表示」（isAtNow判定）にしていたが、チップ・スライダーの
    どちらとも接続しない独立表示になったことで当時の懸念は構造的に発生しなくなり、
    isAtNowゲーティング自体を撤回した。`useDynamicWeatherLayers.ts`が常にフェッチし、
    `frames[0]`があれば常に表示する。地図上チップ・「地図の見え方」パネルどちらにも
    個別の行は現れない（色の意味を確認する専用の凡例表示は撤去済み、既知の制約）。
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
  night軸の重み（`RoutePreference.weights["night"]`）をそのまま、日中なら0倍にして合成する（`night_difficulty`自体の算出は
  街灯・トンネルタグのみに基づき不変、重みの掛け替えだけで動的化）。`RoadGraphEngine`は
  出発時刻1点のみで全区間へ一様適用する（探索中は到達時刻が未確定という制約のため、
  区間ごとの推定到達時刻は使わない。wind評価と同じ簡略化）。
- **Open-Meteo 429対策（T179・T194・T195）**: 本番（Render、共有の送信元IP）でのOpen-Meteo
  429常態化に対し、ユーザー提示の6段階ロードマップ（①複数座標の1リクエスト集約
  ②気象Gridの道路評価Gridからの分離③気象Gridの固定化④TTL付きDB永続キャッシュ⑤
  バックグラウンド更新⑥利用者増加時のOpen-Meteo自前運用）の実装到達点を調査・記録した
  （T194、④まで完了・⑤⑥は未着手のまま記録のみ）。④は`get_forecast_many`をL1（プロセス内
  メモリ）→L2（当初は`cache_db.py`のSQLite、2026-08-30のT398でRedis
  `wind_forecast_cache.py`へ移行）→実フェッチの順に問い合わせる形で実装し（T195）、
  TTLを30分→3時間、失敗時のstaleフォールバック許容幅を3時間→24時間へ拡大した。あわせてOracle Cloud VM上のリレープロキシ（`OPEN_METEO_BASE_URL`、
  T179）で送信元IPを本番の共有IPから分離する経路も用意済みだが、本番では未有効化（T182の
  調査でクォータ枯渇は送信元IP非依存の現象と判明したため）。
- **時刻スライダーのルーラー化（T170・T188〜T193）**: [frontend/src/components/DynamicLayerTimeSlider/DynamicLayerTimeSlider.tsx](../frontend/src/components/DynamicLayerTimeSlider/DynamicLayerTimeSlider.tsx)は
  当初ネイティブ`input[type=range]`だったが、「横スクロールで目盛りの方が動くように」という
  実機フィードバックを受け、横スクロールのルーラー（左端固定インジケータ・正時/非正時で
  異なる目盛り幅・Pointer Events自前ドラッグ・マウスホイールの横スクロール変換・
  ArrowLeft/Right/Home/Endキー操作）へ全面置き換えた。複数の時刻依存レイヤーが同時ONでも
  共有タイムライン1本（上記T184）に統合されているため、スライダー自体も1本のみマウントする。
- **フックへの抽出（T183フォローアップ）**: [frontend/src/hooks/useWeatherGrid.ts](../frontend/src/hooks/useWeatherGrid.ts)が、
  風の矢印・延長降水予報が共有する格子点マップのフェッチ・穴あき対策マージ・詳細格子への
  切替を1つのフックへ集約する（元はpage.tsx内に直接書かれていた風専用ロジックを、風と
  降水延長予報が共有できる形へ切り出した）。

### Redisキャッシュ基盤とJMAアメダス連携（改善計画T387）

Open-Meteo（上記）に加え、JMA（気象庁）のアメダス観測値を扱うため、Redisを新規インフラ
として導入した。Redisは「TTL付きキャッシュ、またはPostGIS/実データ源へのフォールバックが
必ず効くcache-aside」専用の層で、正本データを持たない（`app/infrastructure/
redis_client.py`）。ローカル開発は`docker-compose.yml`のredisサービス、本番はOracle
Cloud VMへネイティブ（apt、PostgreSQLと同じ構成）で導入する想定（backendコンテナが
`--network=host`のため追加設定なしで到達できる）。

**メモリ上限（改善計画T393、2026-08-29）**: 本番`/etc/redis/redis.conf`へ
`maxmemory 2gb`・`maxmemory-policy volatile-lru`を設定済み（VM全体11GB中、PostgreSQL・
backendアプリ[コンテナ`--memory=6g`上限]との共存を考慮した保守的な値）。導入当初
（T387）はこの上限が未設定（`maxmemory=0`＝無制限・`noeviction`）のままだったため、
Redisの用途を広げる際に上限なくメモリを消費し、同居するVM全体のメモリを圧迫する
リスクがあった。現行キーは全てTTL付きのため`volatile-lru`（TTL付きキーの中からLRUで
退避）を選んでいる。

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
  簡易天気アイコン判定に使う）もRedisへ含める。日の出/日没はJMA/Open-Meteoに問い合わせず
  astralによるローカル計算（`domain/twilight.py: sunrise_sunset_jst`）で、クエリ地点
  そのもの・当日（JST）の値を`get_nearest_observation`が都度計算して合成する
  （Redisにはキャッシュしない。計算コストが無視できるほど軽いため）。
- **気象グリッド（`app/infrastructure/wind_forecast_cache.py`、改善計画T398）**: アメダスとは異なり、こちらはOpen-Meteo（上記）の`get_forecast_many`（風・降水延長予報の格子点マップ）が使うL2永続キャッシュで、詳細は上記「気象グリッドのRedis永続キャッシュ」節参照。正本を持たないcache-aside（Open-Meteoへ再フェッチ可能なため）である点がroad_graph_tilesとの違い。
- **`GET /api/weather`と`GET /api/weather/amedas`は完全に独立**（2026-08-29、方針
  「常設エリアは実測値、今日の見通しは予測値」）: 当初は`/api/weather`が内部でアメダスの
  現在値を上書きマージしていたが、frontend側で常設ヘッダー（WeatherPanel、実測値専用）と
  今日の見通し（TodayOutlook、Open-Meteo予報専用）のデータ取得自体を分離した
  （`useWeatherConditions.ts`のweather/amedasが独立フェッチ）結果、`/api/weather`側の
  マージは誰も参照しなくなったため削除した。`/api/weather`は常にOpen-Meteoの値をそのまま
  返す（TodayOutlook専用）。
- **降水ナウキャスト・MSMのRedis化は見送り済み（2026-08-29）**: 当初はナウキャストの
  タイムスタンプ解決ヘルパー（`jma_tile_service.py`）とMSMのRedis保存スケルトン
  （`jma_msm_service.py`）も実装したが、(1) ナウキャストはフロントエンド
  （[precipitationNowcast.ts](../frontend/src/components/Map/precipitationNowcast.ts)）が
  既に独自に`targetTimes_N1/N2.json`を直接取得しタイルURLを組み立てており、バックエンド側
  ヘルパーは完全に重複・未使用だったため削除、(2) MSMはGRIB2解析が
  [T389](tasks/T389.md)（JMBSCとの有償契約が前提、保留中）に切り出されており実体を伴わない
  スケルトンのままだったため削除した。
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
- **Open-Meteo全面代替の可否**: ルート評価（`WindService`、区間ごと・将来時刻の風速
  風向）と風の格子点マップは、任意地点×任意時刻の予報が必要なためアメダス（観測専用）・
  ナウキャスト（降水のみ・60分先まで）では代替できず、MSM実装後に改めて検証する
  （候補はMSMのみだが[T389](tasks/T389.md)は保留中）。降水短時間予報（`jmatile/data/
  rasrf/`、無料・公式、15時間先まで確認済み）は[T407](tasks/T407.md)、線状降水帯予測マップ
  （`sjfcstmap`、無料・公式）はキキクルと合わせて[T410](tasks/T410.md)で実装済み
  （いずれも「動的気象レイヤー」節参照）。UV指数・weather_code相当のJMAプロダクトは
  無料の代替が見つからずOpen-Meteo依存を継続している。
- **road_graph_tilesのRedis cache-aside（`app/infrastructure/road_graph_tile_cache.py`）**:
  `road_graph_tiles`（タイル取得済みマーカー、9章参照）はPostGIS上の一時的な揮発データの
  代表例だが、**PostGISを正本のまま維持し、Redisは読み取り高速化のための派生キャッシュに
  限定した**（フルRedis移行はしない）。理由: このマーカーはルート生成のゲーティングに
  使われ、失うと該当bboxのルート生成が「データ未整備」として拒否される
  （改善計画T22でOverpassフォールバックを撤去済みのため自動復旧手段が無い）。Redisは
  永続化設定を持たない前提のキャッシュ層のため、ここを正本にすると再起動・エビクション
  のたびに広範囲のルート生成が壊れる重大な後退になる。読み取り時にRedisへキーが
  無ければPostGISへフォールバックし、見つかった分をRedisへ書き戻す。
  - **性能**: `GraphService._ensure_tiles_cached`（ルート生成のリクエストごとに実行される
    ホットパス）のPostGIS往復をRedisで肩代わりする狙い。実測（開発機、12タイル×30回）:
    Redis疎通不能時は当初4,066ms/回という致命的な遅延が判明し（Windows環境、TCP接続
    タイムアウトの既定値起因）、`redis_client.py`へ短い接続タイムアウト（0.2秒）と
    サーキットブレーカー（直近失敗から10秒はRedis接続自体を試みない）を追加して
    18ms/回（初回のみ約200ms、以降はPostGIS単体の実測約12ms/回相当）まで改善した。
    Redis障害時にPostGIS単独より遅く・不安定になってはならないという設計上の要請から、
    このタイムアウト・サーキットブレーカーは全JMA用途のRedisアクセスにも共通適用している。
    Redis正常時の実測（本番OCI VM、同一手法・12タイル×30回、2026-08-29）:
    PostGIS単体 平均1.03ms/回（中央値0.87ms）に対しRedisキャッシュヒット 平均0.17ms/回
    （中央値0.16ms）で約5.9倍高速。開発機実測（約12ms/回）よりPostGIS単体自体が大幅に
    速いのは、本番はアプリ・PostGIS・Redisが同一VM上（`--network=host`）でネットワーク
    往復がほぼ無いため。詳細はdocs/tasks/T387.md参照。
- **split鮮度マーカー・edge geometryのRedis cache-aside（改善計画T390）**: T387完了後の
  ユーザー指示「評価ロジックで使う一時的なPostGISデータをRedis化できないか、DB全般を
  見直して」を受け、PostGIS全読み取りパスを棚卸しした結果、road_graph_tilesと同じ
  「in-processキャッシュ（`graph_material_cache.py`）がヒットする最速パスでも必ず
  PostGISへ問い合わせる」性質を持つ2箇所を追加でRedis化した（本番実測、docs/tasks/
  T390.md参照）:
  1. **`is_split_up_to_date`**（`DerivedGraphRepository.is_split_up_to_date`）:
     `GraphService._ensure_split_up_to_date`が`road_graph_tile_cache.py`の
     split鮮度マーカー（`road:tile:split-fresh:{zoom}:{x}:{y}`、TTL 1時間）を介して
     cache-aside化。bbox内の主対象Wayが1件でも未splitならFalseを返す判定のため
     タイル単位でTrue/Falseへ分解できず、**覆う全タイルにマーカーが揃っている場合のみ
     PostGISを省略する**（部分ヒットでは正しさを優先してPostGISへフォールバックする）。
     本番実測（着手前・PostGIS単体）: 中央値1.52ms/回。デプロイ後の実効果
     （Redisキャッシュヒット時）: 平均0.22ms/回（約7倍高速化、`get_cached_tiles`
     [T387、0.17ms]と同水準）。
  2. **`get_edges_with_geometry`**（`DerivedGraphRepository.get_edges_with_geometry`、
     `trace_loop`が8方位ぶん`asyncio.gather`で呼ぶホットパス）: edge_id単位で
     `infrastructure/road_edge_geometry_cache.py`にcache-aside化（TTL 24時間）。
     `DirectedEdge`（domain/graph.py）はshapelyジオメトリを含まないプレーンなPydantic
     モデルのためJSON化するだけで済む。本番実測（着手前・PostGIS単体）: 100 edgesの
     バッチで平均4.69ms/回（1リクエスト最大8回）。デプロイ後の実効果
     （Redisキャッシュヒット時）: 平均1.37ms/回（約3.4倍高速化）。
  - **無効化（正しさの担保）**: 両キャッシュともTTLは取りこぼしに対する自己修復用の
    安全網に過ぎず、正しさは書き込み側のprecise invalidationが担う。
    `GraphService.get_or_build_graph_with_attributes`が`save_graph`成功直後にそのbboxの
    split鮮度マーカーを書き戻し、`DerivedGraphRepository.save_graph`が今回保存した
    edge_idぶんのgeometryキャッシュを無条件で無効化する（同じedge_idが再split後に
    異なる形状で再利用されるケースに備える）。`app/batch/import_pbf.py: _mark_tiles`は
    PBF再importのたびに対象タイルのsplit鮮度マーカーを無効化する（`osm_raw_ways`が
    変わりPostGIS側のroad_edgesが古くなりうるため、次回アクセスで確実にPostGISへ
    再確認させる）。
  - **設計上見送った箇所**: `graph_material_cache.py`（z12タイル単位の道路グラフ
    トポロジ・材料一式、いわゆる「splitデータ」本体）は既に単一ワーカーのプロセス内
    LRUキャッシュでカバー済みのため対象外とした。単一ワーカー稼働の現状でこれを
    Redis化すると「ゼロコストのdict参照」を「ネットワーク往復」に変える純粋な悪化に
    しかならない（T388のjob_registryと同じ「マルチワーカー化まではトリガー未到達」の
    構図）。デプロイ再起動でこのプロセス内キャッシュが消える問題への対策としての価値は
    あるが、`RoadGraphLike`はshapelyジオメトリ等を含み素直にシリアライズできないため
    実装コストと釣り合わない。

### ルーティングエンジンの切り替え対応（openrouteservice ⇄ Road Graph、2026-08-23〜2026-08-31の間存在した仕組み。改善計画T462でopenrouteserviceエンジンを完全撤去し、以降はroad_graphが唯一のエンジン）

**現在はroad_graph単一構成**（`OpenRouteServiceEngine`・`config.py`の`routing_engine`設定・`RouteGenerateResponse.engine`の複数値識別はすべて撤去済み）で、`RouteGenerator`（[backend/app/services/route_generator.py](../backend/app/services/route_generator.py)、戦略層）が`LoopRoutingEngine`ポート経由で`RoadGraphEngine`（[backend/app/services/road_graph_engine.py](../backend/app/services/road_graph_engine.py)）1本だけへ委譲する。詳細は[docs/modules/backend/routing-engine.md](modules/backend/routing-engine.md)参照。

**エンジン切り替えが存在した期間（2026-08-23〜2026-08-31）の設計経緯・レビュー対応の詳細記録は[decisions/road-graph-migration.md](decisions/road-graph-migration.md)「ルーティングエンジンの切り替え対応」節へ移設した（改善計画T428）。**

### 道路種別（highway）の3つのスコープと路面（surface）語彙の正準定義

道路種別・路面の語彙は目的の異なる複数の定義が共存する。混同・片側だけの変更を防ぐため、関係をここへ集約する（改善計画T7）。

**道路種別（highway）— 3つのスコープは目的が異なる別定義（統一しない）:**

| スコープ | 定義場所 | 内容 | 変更理由 |
|---|---|---|---|
| 取込スコープ | [backend/app/batch/import_profile.yaml](../backend/app/batch/import_profile.yaml) | trunk〜residential・cycleway・track等（footway/pedestrian/steps/service/motorway系は除外） | データ容量・表示/探索の少なくとも一方で使うか |
| ルーティング可否（Hard Constraint、〇次フィルタ） | `domain/evaluation.py: HARD_FILTER_HIGHWAY_TYPES`（改善計画T140、旧`DISALLOWED_HIGHWAY_TYPES`） | motorway/trunk系を自転車通行不可として探索から除外（`motorway`/`trunk`の2フィルタに命名分離、既定は両方有効） | 法規・実務判断（後述7章末尾参照） |
| 表示グルーピング | [frontend/src/components/Map/roadFilterAxes.ts](../frontend/src/components/Map/roadFilterAxes.ts) `HIGHWAY_GROUPS` | 幹線/主要道/生活道路/自転車・歩行者道/農道・林道の5分類＋不明 | 地図の見やすさ |

- **trunkは取り込むが走らせない**: 地図表示（幹線道路の把握・回避判断）のために取込対象だが、ルート探索ではHard Constraintで除外される。矛盾ではなく意図的な役割分担
- **フロント凡例にはfootway/pedestrian/steps等の値も含まれる**が、これらは取込対象外のためタイルには現れない（Overpassフォールバックは改善計画T22で撤去済みのため、現れる経路自体が無い）。凡例定義を取込プロファイルへ機械的に合わせることはしない（取込スコープ変更時に凡例が壊れないことを優先）
- いずれかを変更する場合はこの表と各定義場所のコメントを同時に更新すること

**路面（surface）— 正準は1箇所、他はすべて追従:**

- 正準定義: `domain/road.py` の `GOOD_OSM_SURFACE_TAGS` / `BAD_OSM_SURFACE_TAGS`（3値分類の意味はファイル冒頭の「正準定義」コメント参照）
- PostGIS側のMVT生成SQL（`road_graph_repository.py`）は正準集合をバインドパラメータとして直接参照（二重定義なし）
- フロントの表示グループ（`roadFilterAxes.ts: SURFACE_GROUPS`）は、`backend/scripts/export_openapi.py` が書き出す `frontend/src/types/generated/surface-tags.json` と `roadFilterAxes.test.ts` で突き合わせて整合を検証する（「表示グループの全タグ＝正準分類済みタグ全体」「舗装系グループはgoodのみ・未舗装系はbadのみ」。CIのapi-contractジョブがドリフト検知）
- 「石畳・敷石」グループのみgood/bad混在の意図的な中立グループ（材質として同類のため。色も良し悪しを示さない紫）
- タグ集合を変更したら路面タイルの世代（`region_service.py: _tile_cache_path` と `regionApi.ts: ROAD_SURFACE_TILE_VERSION` の対）を上げること（surface_goodの焼き込み値が変わるため）
- ルート評価（`road_score`/`segments[].road_surface_good`）もこの正準集合に統一済み（改善計画T21、2026-08-15）。以前はopenrouteserviceエンジンだけ数値ID語彙の別定義を持っていたが、ORS産geometryのサンプル点を`RoadGraphRepository.get_nearest_surface_tags`で自前DBのEdgeへ空間マッチしてこの正準集合で判定する方式へ置き換え、数値ID語彙は削除した（詳細は「ルーティングエンジンの切り替え対応」）

---

## 2. ディレクトリ構成

```
RideCompass/
  docs/
    architecture.md          ✅
  backend/
    app/
      main.py                ✅ FastAPI app, CORS
      config.py               ✅ pydantic-settings（.env読込、basemap_public_base_url含む）。routing_engine（"openrouteservice" | "road_graph"、既定road_graph。改善計画T247で既定値をopenrouteserviceから切替）を「ルーティングエンジンの切り替え対応」で追加。git_commit（デプロイワークフローが注入するGIT_COMMIT、ローカルはnull。改善計画T263でRender自動注入のRENDER_GIT_COMMITから改称）を「デプロイの反映確認」で追加
      version.py               ✅ STARTED_AT（プロセス起動時刻、インポート時に一度だけ評価）。/healthのデプロイ確認用（「デプロイの反映確認」で新規）
      api/
        admin_auth.py           ✅ 管理API共通の認可境界（`require_admin_basic_auth`、HTTP Basic認証）。元はaxis_admin.pyにのみ定義されていたが、改善計画T379でdebug_admin.pyも同じ認可を必要としたため複製を避けてここへ切り出した
        dependencies.py        ✅ DI工場（get_route_generator等のDependsファクトリ）とclient_id（per-IPレート制限キー）。旧routes.pyの分割（改善計画T5）
        routers/               ✅ エンドポイント群（main.pyはrouters/__init__.pyのapi_routerをinclude）。health.py（GET /health, GET /api/debug/stats）/ routes.py（POST /api/routes/preview, POST /api/routes/generate。per-IPレート制限＋同時実行数ガード付き）/ weather.py（GET /api/weather、GET /api/weather/wind-grid・wind-grid-detail＝T178フォローアップ・T180・T183・T185、動的気象レイヤー参照）/ region.py（GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf）/ basemap.py（GET /api/basemap/{path}, POST /api/basemap/refresh）/ jma_tile.py（GET /api/jma-tile/{path}、改善計画T412、JMA動的タイル系のプロキシ）/ axis_admin.py（/api/admin/axis-definitionsのCRUD、改善計画T221 Stage D、HTTP Basic認可要[T272]）/ axis_catalog.py（GET /api/axis-catalog、改善計画T269、認可不要）/ material_catalog.py（GET /api/material-catalog、改善計画T277、認可不要。GET /api/material-catalog/{material_id}/values＝改善計画T340、highway/surface/smoothnessの実データ値一覧、DB読み取りはRegionService.get_material_values経由）/ accidents.py（GET /api/accidents/tiles/{z}/{x}/{y}.pbf）/ debug_admin.py（/api/admin/debug、改善計画T379、HTTP Basic認可要。debug_modeのランタイム切替[POST /mode]・現在値確認[GET /mode]・直近ログ取得[GET /logs]、本番でSSHせずに一時的なDEBUGログ調査を行うための運用API）。レート制限・同時実行の上限値はconfig.pyのSettingsへ外部化済み（.envで上書き可）。改善計画T321（デッドコード監査）: ズーム範囲・座標範囲チェック＋レート制限（`math.sinh`のOverflowError回避が根拠）がaccidents.py/region.pyへ別々に手書きされ表記が乖離していたため、`_tile_validation.py`（`check_tile_rate_limit`/`validate_tile_coords`）へ共通化した
      domain/
        route.py               ✅ Coordinates, RouteSegment, RouteSegmentDetail（Step9）, RouteCandidate（標高・wind_score・road_score・overall_difficulty・segments・axis_difficulties含む。改善計画T431でstop_density等旧来の軸1対1固定フィールド5個を削除済み、改善計画T548でtotal_score・score_breakdown・RouteScoreComponentを削除済み）
        weather.py               ✅ WeatherConditions
        errors.py               ✅ RoutingError
        geo.py                   ✅ destination_point, haversine_distance_km, compass_label, bearing_between（sample_indices/sample_line_coordinates/sample_line_pointsはOpenRouteServiceEngine専用だったため改善計画T462の撤去に伴い削除済み）
        road.py                   ✅ classify_osm_surface, GOOD_OSM_SURFACE_TAGS, BAD_OSM_SURFACE_TAGS（両エンジン共通の唯一の路面判定語彙）, distance_weighted_road_score（距離加重集計、改善計画T21で両エンジン共通化）
        difficulty.py             ✅ gradient_difficulty, wind_difficulty, road_difficulty, composite_difficulty（Step9。scoring.py/normalize_min_maxは改善計画T548で撤去済み）
        wind.py                   ✅ WindCalculator.wind_penalty（Step7）
        region.py                 ✅ BoundingBox, tile_bounds_lonlat, ROAD_TILE_MIN_ZOOM/MAX_ZOOM（Step10改訂。標高グリッド・snap_cells・bbox対角距離関連は撤去済み）。ROAD_GRAPH_TILE_ZOOM, tiles_covering_bbox（Road Graphのタイル単位キャッシュ用、新規）
        graph.py                    ✅ Node, DirectedEdge, RoadGraph, WaySpec, build_road_graph（Road Graph移行Phase 1、新規。Phase 2でOSMタグ解釈を分離しWaySpec契約に一本化。Phase 3でWaySpec.surfaceを追加）
        osm_adapter.py               ✅ OSM Way（tags辞書）→WaySpecへの変換（Road Graph移行Phase 2、新規。OSM Adapter/Importer）
        attributes.py                 ✅ ElevationAttribute, SurfaceAttribute, compute_elevation_attribute, build_surface_attributes（Road Graph移行Phase 3、新規）
        recipe.py                      ✅ 改善計画T122: タグ由来の材料タグを正規化する純関数群（parse_lanes/parse_maxspeed/cycleway_values/tag_value_is/bicycle_infra_flags[T336]）。旧`RoadSuitabilityRecipe`等の専用Pythonレシピ採点構造（clamp_level/threshold_adjustment/cycleway_adjustment/flag_adjustment/validate_threshold_order）は改善計画T292でcar_stress軸をAXIS_DEFINITIONSの内部軸階層へ再設計した際に削除済み。cycleway_class関数は改善計画T337で削除済み（唯一の呼び出し元だった同名材料が評価軸・地図表示のどちらからも未使用だったため）。改善計画T347: `bicycle_infra_flags_or_none(tags, highway)`（tagsがNone、またはhighwayがNoneかつ全フラグFalseの場合のみNoneを返す「データ欠落＝unknown」判定を一箇所に集約）を追加。material_catalog.py/evaluation.py/openrouteservice_engine.py/road_graph_engine.pyの4箇所が個別に手書きしていた同等の判定（旧`classify_bicycle_infrastructure`のhighway=None最終catch-all分岐を暗黙に踏襲していたが、フラグベースの新ロジックへ移行した際に4箇所とも独自に再実装が必要になっていた）をこの1関数へ統一
        traffic.py                     ✅ 静的道路属性P1: classify_stop_poi、STOP_POI_MATCH_MAX_DISTANCE_M/INTERSECTION_MATCH_MAX_DISTANCE_M/INTERSECTION_DEGREE_THRESHOLD（7章参照）。材料タグ正規化はrecipe.pyへ切り出し済み（改善計画T122）。専用レシピ（旧car_stress_breakdown/car_stress_level）は改善計画T292でAXIS_DEFINITIONSの軸階層へ再設計済み（domain/axis_definitions.py参照）。classify_supply_poi（コンビニ・自販機・トイレ・給水・駐輪場、改善計画T101、表示専用でEdge Costには組み込まない）も同ファイル。改善計画T347: `classify_bicycle_infrastructure`（7値分類、改善計画T150で「交通ストレス」から改称）は評価軸・地図表示のどちらからも参照されなくなったため削除。改善計画T431: `distance_weighted_stop_density`/`distance_weighted_intersection_density`/`distance_weighted_bicycle_infra_score`/`is_dedicated_bicycle_infra`（旧`RouteCandidate`個別フィールド集約用）はフロントエンド末端消費者ゼロを確認した上で削除済み。区間ごとの評価軸（axis_difficulties）は`domain/evaluation.py`が直接材料合成する
        accident.py                     ✅ 外部静的データソースT50: ACCIDENT_MATCH_MAX_DISTANCE_M, KANTO_PREFECTURE_CODES（NPA採番）, ACCIDENT_FATAL_WEIGHT（7章参照）。改善計画T431: `distance_weighted_accident_density`（旧`RouteCandidate.accident_density`集約用）はフロントエンド末端消費者ゼロを確認した上で削除済み
        designation.py                   ✅ 外部静的データソースT51: DESIGNATION_BUFFER_WIDTH_M/DESIGNATION_MATCH_MIN_RATIO/DESIGNATION_IMPORT_KINDS/CAR_STRESS_DESIGNATION_KINDS（7章参照）
        evaluation.py                  ✅ RoutePreference（7軸の重み、7章参照）, EdgeCostResult, is_edge_allowed, compute_edge_cost（Road Graph移行Phase 4、新規。Evaluation Engine）。compute_wind_penaltyを「完全移行」（Phase 6・Dynamic Data対応）で追加。compute_edge_costs_bulk（改善計画T240、evaluate_graphのnumpyベクトル化本体、抽出フェーズ＋計算フェーズの2段。scalar版compute_edge_costは回帰テストオラクルとして存続）
        axis_templates.py                ✅ 改善計画T221 Stage A/T239、T396で2プリミティブへ再編: evaluate_breakpoint_linear（連続演算、旧evaluate_flag_sum/evaluate_recipe_then_breakpoint_linearを統合）・evaluate_categorical（離散演算）。スカラー・numpy配列の両方を受け付ける。round1_array（T240、Python組み込みround()とビット単位で一致させる配列丸め、compute_edge_costs_bulkの最終cost/difficultyのみに使用）も同居
        axis_definitions.py              ✅ 改善計画T221 Stage B/C: 評価軸の定義データAXIS_DEFINITIONS（axis_id・材料・shape・shape_params・default_weight。breakpoints等の変換パラメータの単一ソース）と、定義を読んでスコアを返す汎用評価関数evaluate_axis_scalar/evaluate_axis_array。既存テンプレート＋既存材料で表現できる新しい軸は定義データの追加だけでスカラー/配列両経路へ同時反映される（7章参照）
        material_catalog.py              ✅ 改善計画T277: 材料（MaterialTerm.material等が参照するid）の正式レジストリMaterialSpec/MATERIAL_CATALOG（material_id・label・dtype[numeric/boolean/categorical、T290でcategorical追加]・内部専用tile_property/tile_property_inverted/tile_property_needs_runtime_scale[T278追加]）。改善計画T290で9→20材料へ拡張（MVTタイル焼き込み済みだが評価軸未使用の生データを網羅登録、categorical材料は登録のみで評価軸未対応）。改善計画T336で自転車インフラの正規化フラグ材料4件（highway_is_cycleway/cycleway_has_track/cycleway_has_lane/cycleway_has_shared）を追加し20→24材料（tile_property非依存、抽出は`domain/recipe.py: bicycle_infra_flags`が単一ソース）。改善計画T337で評価軸・地図表示のどちらからも未使用だったcycleway_class材料を削除し24→23材料（MVTタイルのcycleway_classプロパティ・`domain/recipe.py: cycleway_class`関数も同時に削除、ROAD_SURFACE_TILE_VERSION対上げ）。改善計画T338でdisplay_onlyフィールドを追加しdesignation材料を軸スタジオの選択肢（`GET /api/material-catalog`）から除外（`axis_studio_materials()`、地図表示には影響しない）。改善計画T339で単純パターンのextractorを汎用ファクトリ（raw_way_tag_extractor/tag_equals_extractor/way_tag_parser_extractor/count_per_km_extractor）へ置き換え、実証用にtracktype材料を追加し23→24材料（専用のPython関数を書かず宣言のみで抽出可能にできることを実証、「材料抽出の宣言駆動化」節参照）。改善計画T338フォローアップ（2026-08-26、ユーザー指摘）でdesignationを正規化フラグ材料is_emergency_transport[N10]/is_critical_logistics[N12]へも分解し24→26材料へ拡張（bicycle_infra→cycleway_has_track等[T336]と同じ設計思想、「表示専用材料の除外」節参照）。改善計画T347で7値categorical材料`bicycle_infra`自体（`classify_bicycle_infrastructure`の分類結果を保持していた、材料としては使用者無し）を削除し26→25材料。同時に`highway_is_cycleway`の`primary_attribute_id`を`highway`から`cycleway`へ再割当て（4フラグ材料全てが`cycleway`一次属性を共有する形に統一し、`highway`はcar_stress_highway_base専用のまま非共有を維持）、4フラグ材料全てへ`bool_default="nan"`を追加（ベクトル化評価経路`compute_edge_costs_bulk`が欠落値を`False`へ丸めて「データ無し」を「確認済みでインフラ無し」と誤判定していた回帰を修正、`surface_good`の既存踏襲）。材料の追加はコード変更＋デプロイのみ、GUIからの追加・編集・削除は不可（「材料カタログの正式レジストリ化」節参照）
        axis_display.py                  ✅ 改善計画T278: derive_ramp_inputs()。AXIS_DEFINITIONSの軸とMATERIAL_CATALOGから地図ramp表示（tile_inputs/thresholds）を自動導出する（安全に導出できるCategorical/FlagSum/単一材料BreakpointLinearのみ、詳細は「地図表示ルール（kind=ramp）の自動導出」節参照）
        difficulty.py                    ✅ AxisDifficulties（axis_idキーの軸別difficulty辞書＋composite、T221 Stage Bでdict化）, evaluate_axis_difficulties（AXIS_DEFINITIONSをループする薄い関数）, accident_difficulty/gradient_difficulty等の軸別difficulty互換ラッパ（Noneガード・負値ガードのみ担い変換はaxis_definitions.pyへ委譲）。composite_difficulty/distance_weighted_difficultyも同居（7章参照）
        night.py                         ✅ 改善計画T139: night_difficulty（街灯なし・トンネルの難易度変換、7章参照）。T221 Stage B/Cでnight_materials（lit/tunnelタグ→材料フラグ解決）へ再編、加点値はaxis_definitions.pyのnight軸定義へ移動
        twilight.py                      ✅ 改善計画T173: is_night（astralライブラリで市民薄明を判定、動的気象レイヤー参照）
        wind_grid.py                     ✅ 改善計画T178フォローアップ・T183: 風・降水延長予報の格子点マップ（固定格子生成、外部API非依存の純粋座標計算。動的気象レイヤー参照）
        jma_warning.py                    ✅ 改善計画T205: JMA警報コード対応表（気象庁公式コード表を典拠）とサイクリング関連種別への絞り込み、3段階レベル導出、電文kinds配列からのActiveWarning抽出
        jma_area.py                        ✅ 改善計画T205: 市区町村コード→JMA警報エリア（class20/class10/office）の解決（area.jsonの親子関係を辿る）
        wbgt.py                            ✅ 改善計画T174: 暑さ指数（WBGT）の値→4段階＋非表示の判定（環境省「熱中症予防運動指針」を典拠）、提供期間（4〜10月）判定
        wbgt_points.py                     ✅ 改善計画T174: 情報提供地点（アメダス観測所ベース、約840地点）への最近傍点探索
        flood_forecast.py                  ✅ 改善計画T212: JMA指定河川洪水予報のコード対応表（気象庁公式コード表を典拠、item.code自体が発表/継続/警報解除/完全解除を区別）とレベル2〜5→バッジ4段階への対応、電文からのActiveFloodForecast抽出
        routing.py                     ✅ build_sparse_graph/shortest_path_node_ids_sparse/path_to_edge_ids_sparse（T220、scipy.sparse.csgraph版）・build_node_spatial_index/find_nearest_node_indexed・concat_node_paths。NetworkX版（build_networkx_graph/find_nearest_node/shortest_path_node_ids/path_to_edge_ids、「完全移行」時点の実装）はscipy移行後実行時経路から呼ばれなくなっていたため改善計画T321（デッドコード監査）で削除、networkx依存自体もrequirements.txtから撤去
      services/
        route_generator.py     ✅ `RouteGenerator`（周回生成戦略、エンジン非依存）＋`LoopRoutingEngine`（Protocol）＋`TracedLoop`。8方位・距離許容フィルタ・`overall_difficulty`昇順ソート（改善計画T548、旧`RouteScorer`降順ソートを置換）を単一実装で持ち、経路計算・評価はエンジンへ委譲（設計レビュー対応でポート分割）。改善計画T364で経由地指定ルート専用の`generate_via_waypoints`を追加
        road_graph_engine.py   ✅ `RoadGraphEngine`。Road Graph + Evaluation Engine + Route Engine（domain/routing.py）で経路・評価を行うエンジン（「完全移行」の実装をポート化。prepareでRoad Graph1回取得、evaluate_loopsで経路上Edgeのみ標高取得）。改善計画T462でopenrouteserviceエンジンを撤去し唯一のエンジン実装になった
        weather_service.py     ✅ 「地点＋時刻」で天候を取得（Step6）。RoadGraphEngineからは出発時点・起点付近の風を取得する用途で（「完全移行」）呼ばれる
        warning_service.py     ✅ 改善計画T205: 緯度経度→市区町村→JMA警報エリアの解決とr8警報APIの電文配列集約でWeatherWarningsを組み立てる。地点解決・警報取得のどこで失敗しても空応答（警報なし）を返す
        wbgt_service.py         ✅ 改善計画T174: 緯度経度→最寄りWBGT地点の解決と予測値APIの取得でWbgtStatusを組み立てる。提供期間外・地点解決失敗・取得失敗・「ほぼ安全」のいずれもlevel=nullを返す
        flood_service.py         ✅ 改善計画T212: T205のjma_area.resolve_areaを再利用した地点解決と洪水予報APIの電文集約でFloodForecastsを組み立てる。地点解決・取得のどこで失敗しても空応答を返す
        region_service.py          ✅ get_road_surface_tile(z,x,y)で路面ベクタタイル(PBF)を生成・tile_cacheに永続化（Step10改訂。標高はGSIラスタタイルとしてフロントエンドが直接取得するためバックエンドを介さない）。get_poi_tile(z,x,y)で停止要因POI・交差点密度の点タイルを生成（T54）。カバレッジ内タイル配信のたびにz12祖先タイルの道路グラフ未構築・古さを確認しバックグラウンド構築を起動（T59、7章参照）
        accident_service.py          ✅ 事故点のタイル生成（accident_repository.py経由）。region_service.pyとは別系統（外部静的データソースT50、7章参照）
        graph_service.py            ✅ GraphService.get_or_build_graph_with_attributes(bbox)でPostGIS（`repository`必須）からRoad Graphを取得・構築（Road Graph移行Phase 1〜3、新規）。「完全移行」でRouteGeneratorから実際に参照されるようになった。当初はrepository未接続時にOverpassから都度構築するDBなし構成を持っていたが、改善計画T222で撤去済み（本番・dev環境は常にrepositoryを注入するため未到達だった）。改善計画T321（デッドコード監査）: T219のタイルキャッシュ導入でホットパスが`_build_search_materials_from_tile_cache`へ移った後、`lean`引数と依存する分岐が実行時到達不能のまま残っていたため削除。T248の材料取得統合（`get_edge_materials_batch`）後に呼び出し元を失っていた素通しラッパー4本（`get_way_tags`/`get_edge_attribute_counts`/`get_elevation_attributes`/`get_designated_edge_ids`）も削除
        elevation_aggregation.py    ✅ 改善計画T321（デッドコード監査）: 標高集約（獲得標高・最高/最低標高・最大勾配）の最終集約ロジック（sum_or_none/min_or_none/max_or_none）を`elevation_service.py`と`road_graph_engine.py: _aggregate_elevation`の二重実装から切り出して共通化
        tile_serving.py             ✅ 改善計画T321（デッドコード監査）: タイル配信（キャッシュ確認→fetch_tile→キャッシュ書込/空タイルフォールバック）の骨格を`region_service.py: _get_tile`と`accident_service.py: get_accident_tile`の二重実装から切り出して共通化
        elevation_attribute_service.py ✅ ElevationAttributeService.get_attributes_for_graph(graph)でEdge単位の標高属性（形状点をGSI APIへ問い合わせ）を算出（Road Graph移行Phase 3、新規）。「完全移行」でRouteGeneratorから、確定した経路上のEdgeだけに絞って呼ばれるようになった（性能上の理由、decisions/road-graph-migration.md参照）
        evaluation_service.py           ✅ EvaluationService.evaluate_graph(graph, elevation_attributes, surface_attributes, wind=None)でEdge Costを算出（Road Graph移行Phase 4、新規。Phase 5でload_route_preference()を追加。「完全移行」でwind引数を追加しRouteGeneratorから参照されるようになった）。改善計画T240で内部実装をcompute_edge_costs_bulk（domain/evaluation.py、numpyベクトル化）へ切り替え（シグネチャ・戻り値型は不変）
      infrastructure/
        elevation_client.py     ✅ 国土地理院標高API（共有コネクション＋緯度経度メモ化キャッシュ）
        weather_client.py       ✅ Open-Meteo Forecast API（current+hourlyをまとめて取得、TTLキャッシュ。get_forecast_manyはL1メモリ+L2永続化の2段、T194〜T195。L2は当初SQLiteだったが2026-08-30のT398でRedis[wind_forecast_cache.py]へ移行）
        jma_warning_client.py    ✅ 改善計画T205: 国土地理院逆ジオコーダ（緯度経度→市区町村コード）・JMA地域マスタarea.json（24時間TTL）・JMA警報API r8（10分TTL）の3クライアント。いずれも失敗時はNoneを返す（tenacity再試行は無し）。TTLキャッシュは`cachetools.TTLCache`を使用（改善計画T244、flood/wbgtクライアントと同型のキャッシュ実装重複を解消）
        wbgt_client.py            ✅ 改善計画T174: 環境省WBGT情報提供地点マスタCSV（24時間TTL）・暑さ指数予測値WebAPI（1時間TTL、直近6時間の発表時刻を検索範囲とする連続期間指定）の2クライアント。サイト側の「自動化ツールからの高頻度アクセスは控えて」注記に配慮しtenacity再試行は無し。TTLキャッシュは`cachetools.TTLCache`使用（改善計画T244）
        flood_client.py            ✅ 改善計画T212: JMA指定河川洪水予報API（10分TTL、全国分を1回のGETで取得）のクライアント。tenacity再試行は無し。TTLキャッシュは`cachetools.TTLCache`使用（改善計画T244）
        vector_tile.py               ✅ 路面データをMVT（Mapbox Vector Tile）にエンコード（Web Mercator投影、Step10改訂）
        wind_forecast_cache.py       ✅ 気象グリッド（風・降水延長予報）のRedis永続キャッシュ（改善計画T398。標高キャッシュ・路面セルキャッシュは無関係、それぞれtile_cache.py・DEMタイル化[T10]参照。旧SQLite実装cache_db.pyはこの移行で削除済み）
        tile_cache.py               ✅ 地図タイル・路面ベクタタイル共通のファイルキャッシュ（パスをSHA-256でフラット化、Step10。T398でDATA_DIR定数の定義元になった）
        basemap_client.py           ✅ OpenFreeMapタイル/スタイルJSONのプロキシ＋URL書き換え（Step10）
        jma_tile_client.py           ✅ 改善計画T412: JMA動的タイル系（降水ナウキャスト・rasrf・雷/竜巻ナウキャスト・キキクル・線状降水帯予測マップ）のプロキシ。basemap_client.pyと同じpath丸ごとプロキシ方式だが、タイル本体はjma_tile_redis_cache.py（Redis cache-aside、T510でtile_cache.pyから移行）・targetTimes*.jsonはTTLCache（2分）とキャッシュ戦略を分岐する。get_cached（キャッシュのみ参照）/fetch（外部フェッチのみ）/get（両方の一括呼び出し）の3メソッドへ分割し、jma_tile.py側がget_cachedのヒット判定をレート制限より先に行えるようにした（T510、429の直接原因への対応）
        jma_tile_redis_cache.py      ✅ 改善計画T510: JMAタイル本体（ラスタPNG・洪水キキクルのベクタPBF）のRedis cache-aside。wind_forecast_cache.pyと同じfail-open設計、TTL20分、値はbase64化してJSON文字列としてRedisへ保存する（redis_client.pyがdecode_responses=Trueのため生バイト列を直接保存できない）
        rate_limiter.py              ✅ プロセス内メモリのみの固定窓レート制限（`check_rate_limit`）。認証なしで叩ける`/api/region/road-surface-tiles/*`（120req/min）・`/api/basemap/*`（300req/min）に`api/routes.py`から適用し、超過時は429を返す
        debug_log.py                  ✅ `log_external_call`（contextmanager）。外部API呼び出し・タイルキャッシュアクセスの開始/完了/失敗をカテゴリ単位でDEBUGログに出力する。`settings.debug_mode`（`main.py`のlogging設定）がFalseの間は実質無出力
        debug_control.py             ✅ 改善計画T379。`set_debug_mode`（`settings.debug_mode`とルートロガーのレベルをランタイムで切替、`.env`は書き換えず再起動不要）と、ルートロガーへ追加するリングバッファ`logging.Handler`（直近最大1000件を保持、`get_recent_logs`で`limit`/`contains`絞り込み取得）。`api/routers/debug_admin.py`から呼ばれる。本番でSSHせずにdebug_modeの一時有効化・DEBUGログ取得を行うための運用機構（T318の調査で判明した運用上のボトルネックへの対応）
        database.py                  ✅ SQLAlchemy非同期エンジン・セッションファクトリ（Road Graph移行「永続化」、新規。DB未接続でも既存機能に影響なし）。`get_engine`/`get_session_factory`（command_timeout=20、元は路面タイル配信のハング検知用）と、road_graphエンジンの経路生成専用`get_route_generation_engine`/`get_route_generation_session_factory`（command_timeout=180、改善計画T243）の2系統のエンジンを持つ。未splitエリアの初回タッチ時に発生しうる重い再構築が前者の短いタイムアウトでキャンセルされる本番実測不具合への対応
        migrate.py                   ✅ 最小マイグレーション機構（`apply_pending_migrations`。改善計画T17、decisions/pre-static-attributes-gate.md 決定3）。`../migrations/`配下の番号付きSQLを`schema_migrations`テーブルで適用管理する。`create_tables`（新規DB向けの基本スキーマのみ）とは役割分離。標準ブートストラップ順は`create_tables()`→`apply_pending_migrations()`（import_pbf.py等）で、0001〜0009は`CREATE TABLE IF NOT EXISTS`/`ADD COLUMN IF NOT EXISTS`を徹底しこの順序を前提に設計されているが、0010〜0019はこの規約が崩れて素の`CREATE TABLE`/`ADD COLUMN`になっており、新規DBでは`create_tables()`が先に同じテーブル・カラムを作るため0010で`DuplicateTableError`となり以降が未適用のまま中断する欠陥があった（改善計画T321のデッドコード監査で発見、フレッシュDBでの実機検証は誰も踏んでいなかった）。改善計画T321で0010〜0019にも`IF NOT EXISTS`を追加して修正済み（フレッシュDBで19件全適用・axis_definitions 13行のシード投入まで実機検証済み）
        road_graph_models.py         ✅ road_nodes/road_edges/elevation_attributes/surface_attributesのSQLAlchemy ORMモデル（PostGIS Geometry型、Road Graph移行「永続化」、新規）。OsmRawNodeRow/OsmRawWayRow（生OSMデータ、配列型+GINインデックス）を「根本修正」で追加
        road_graph_repository.py     ✅ 責務別4リポジトリ＋ファサード（改善計画T6で分割）: RawOsmRepository（生OSM層・タイルマーカー）/ DerivedGraphRepository（road_nodes/edges・split_at鮮度判定）/ AttributeRepository（標高・路面属性）/ RoadSurfaceTileQuery（表示用MVT）/ RoadGraphRepository（既存公開APIを保つファサード、DI注入点）。**書き込みメソッドはcommitせず、サービス層が操作のまとまりごとにcommit()を呼ぶ規約**（トランザクション境界の詳細はモジュールdocstring参照）。save_raw_ways/get_way_specs_with_closureは「根本修正」で追加、save_graphはway_ids_to_replaceによるdelete-then-reinsert対応。save_graphは改善計画T245でステージ別所要時間（node_upsert_ms/delete_ms/edge_upsert_ms/total_ms）のINFOログを追加（本番実測でDELETE段の想定外の長時間化を検知したが原因未特定のまま、次回発生時にログで追跡できるようにするため）。改善計画T246で真因（`NOT (edge_id = ANY(new_edge_ids))`除外条件をチャンクごとに毎回再評価していた）を特定し、除外対象を一時テーブル（PK付き）へ1回だけ投入しNOT EXISTS（反結合）で参照する形へ変更、あわせてこの操作専用に`SET LOCAL work_mem`を引き上げ。本番DBのグローバルwork_memも4MB→16MBへ変更済み（`postgresql.conf`、SSH経由）。改善計画T321（デッドコード監査）: `RawOsmRepository.is_tile_cached`/`mark_tile_cached`とその委譲メソッドを削除。実際にタイル取得済みマークを書くのは`app/batch/import_pbf.py: _mark_tiles`（生asyncpgのON CONFLICT DO NOTHING）のみで、削除した2メソッド（ORM UPSERT版、競合時にfetched_atを更新する点で挙動が異なっていた）は実行時未使用の重複実装だった
        valhalla_client.py        ⬜ 将来
        osm_repository.py            ⬜（road_graph_repository.pyが実質この役割を担う）
        accident_repository.py       ✅ AccidentTileQuery（事故点のMVT生成、accident_points専用。road_graph_repository.pyとは別系統）
        designation_models.py        ✅ route_designations/designation_attributes/designation_import_runsのSQLAlchemy ORMモデル（外部静的データソースT51）
      batch/                    ✅ PostGIS事前取込バッチ群（`.venv\Scripts\python.exe -m app.batch.<module>`で実行、いずれも--dry-run対応）
        _common.py                ✅ asyncpg_dsn（SQLAlchemy URL→asyncpg DSN変換）, download_to_path（ZIP/CSV取得の共通骨格）。4バッチが参照する共通ヘルパ（改善計画T80）
        import_pbf.py              ✅ OSM PBF→osm_raw_ways/osm_raw_nodes/osm_raw_pois取込（Road Graph移行「永続化」、詳細はdocs/osm-pbf-import.md）
        import_accidents.py         ✅ 警察庁交通事故統計本票CSV→accident_points取込（外部静的データソースT50、7章参照）
        import_designations.py       ✅ 国土数値情報N10/N12→route_designations取込（外部静的データソースT51、7章参照）
        match_designations.py         ✅ route_designations→osm_raw_waysバッファマッチ事前計算（designation_attributes、外部静的データソースT51、改善計画T74で対象をroad_edgesからosm_raw_waysへ変更、7章参照）
    scripts/                    ✅ 単発実行の検証・計測スクリプト群（`.venv\Scripts\python.exe scripts\<module>.py`で実行、batch/と違いDB書き込みを伴わない読み取り専用が主）。verify_postgis_phase0.py（Phase 0検証）/ apply_migrations.py（migrate.pyの手動起動）/ check_db_connection.py（接続確認）/ export_openapi.py（OpenAPIスキーマ・フロント契約フィクスチャの書き出し）/ measure_tag_coverage.py（改善計画T102、PBF直読みのタグ付与率実測）。改善計画T292で専用Pythonレシピ（car_stress_level等）を廃止したのに伴い、車ストレスのcalibration研究スクリプト3本（measure_axis_stats.py・measure_axis_correlation.py・analyze_jartic_calibration.py）は削除した。collect_jartic.py（改善計画T53、JARTIC WFS収集）も、唯一の消費先だったanalyze_jartic_calibration.py削除後は較正データを読む者がいない無意味な処理になっていたため改善計画T321（デッドコード監査）で削除した
    tests/
      test_health.py          ✅ status/started_at（ISO8601）の検証、commitがGIT_COMMIT未設定時null・設定時はその値を反映すること（「デプロイの反映確認」で追加）
      test_geo.py             ✅ destination_point / haversine_distance_km / compass_label / bearing_betweenの検証
      test_routes_preview.py  ✅ get_preview_builderをDIでモックしたAPIテスト。per-IPレート制限（20回/分）の429検証を追加
      test_route_generator.py ✅ RouteGenerator（周回生成戦略、エンジン非依存）の検証: 経由地点が起点始点/終点の周回を成すこと・距離許容フィルタ・失敗方位のスキップ・prepare失敗時の空返却・**評価が距離フィルタ通過候補だけに行われること**・`overall_difficulty`昇順ソート（改善計画T548で降順`total_score`ソートから変更）・engine_name公開（設計レビュー対応のポート分割で新規）
      test_road_graph_engine.py ✅ RoadGraphEngineのエンドツーエンド検証（RouteGenerator経由）: 起点を中心とした「車輪」状のRoad Graphフィクスチャによる8方位生成・許容範囲フィルタ・経路探索失敗時スキップ・標高/路面/風の集計・segments構築・graph_serviceへの問い合わせが1回のみ・標高取得がパス上のEdgeだけ＆距離フィルタ通過候補だけに絞られること（性能回帰テスト）・engine_name（旧test_route_generator.pyのRoad Graph版から改組）
      test_routing.py          ✅ build_sparse_graph/shortest_path_node_ids_sparse/path_to_edge_ids_sparse（コスト最小経路・到達不能・始点=終点・Hard Constraint除外）・build_node_spatial_index/find_nearest_node_indexed・concat_node_pathsの検証（T321でNetworkX版のテストは実装ごと削除）
      test_routes_generate.py ✅ get_route_generation_builderをDIでモックしたAPIテスト（engineフィールドの返却・per-IPレート制限の429・同時実行上限の429に加え、研究IF改善Phase 1で重み上書きの伝搬・conditionsエコー・上書きバリデーション422・既定値へのフォールバックの検証を追加）
      test_elevation_client_cache.py ✅ 同一/近傍座標でのキャッシュ再利用・遠方座標での再取得
      test_weather_service.py ✅ 現在/指定時刻の天候取得、取得失敗時の扱い
      test_weather_client_cache.py ✅ TTL内キャッシュ再利用・失効後再取得・取得失敗時の扱い
      test_weather_route.py   ✅ /api/weatherのDIモックテスト。per-IPレート制限（60回/分）の429検証を追加
      test_wind.py             ✅ WindCalculator.wind_penaltyの向かい風/追い風/横風の検証（domain/wind.py自体は「完全移行」後もdomain/evaluation.py: compute_wind_penaltyから再利用）
      test_road.py             ✅ classify_osm_surface（OSMタグ基準、両エンジン共通）とdistance_weighted_road_score（距離加重集計、改善計画T21で両エンジン共通化）の検証。不明路面の「分母から除外・None判定」（設計レビュー対応）の検証を含む
      test_difficulty.py      ✅ gradient/wind/road_difficultyの閾値・composite_difficultyの再正規化の検証
      test_axis_templates.py   ✅ 改善計画T239、T396で2プリミティブへ再編: 連続演算（区分線形補間、boolean材料の重み付き和も含む）・離散演算（カテゴリ→定数）のスカラー/配列両モードの一致・NaN伝播の検証
      test_region.py           ✅ tile_bounds_lonlatの検証（zoom0で全世界を覆う・隣接タイルの境界一致など、Step10改訂）。tiles_covering_bboxの検証（単一/複数タイル・世界端でのクランプ）を追加（Road Graphのタイル単位キャッシュ導入時、新規）
      test_region_service.py  ✅ RegionService.get_road_surface_tileのタイルキャッシュ利用/未キャッシュ時の挙動の検証（Step10改訂）
      test_region_routes.py   ✅ /api/region/road-surface-tiles/{z}/{x}/{y}.pbfのDIモックテスト・ズーム範囲外リクエストの400（Step10改訂）
      test_graph.py            ✅ build_road_graphのWay分割（交差点/端点/形状点）・direction処理・内部ID/OSM IDの分離・距離計算の検証（Road Graph移行Phase 1、新規。Phase 2でWaySpec契約に合わせて更新）
      test_osm_adapter.py      ✅ osm_way_to_way_specのonewayタグ解釈（yes/-1/大文字小文字・空白/未知の値）・highway受け渡し・ノード数不足時の除外の検証（Road Graph移行Phase 2、新規。Phase 3でsurfaceタグ受け渡しの検証を追加）
      test_attributes.py       ✅ compute_elevation_attribute（登り/下り/混在/欠損値/有効点不足）・build_surface_attributes（osm_way_id対応/未知way/way_id無し）の検証（Road Graph移行Phase 3、新規）
      test_elevation_attribute_service.py ✅ ElevationAttributeService.get_attributes_for_graphのDIモックテスト（複数Edge独立性・欠損値・空グラフ）（Road Graph移行Phase 3、新規）
      test_evaluation.py       ✅ is_edge_allowed（Hard Constraint）・compute_edge_cost（平坦舗装/激坂未舗装の比較・属性欠損時のフォールバック・重み変更）の検証（Road Graph移行Phase 4、新規）。compute_wind_penalty（向かい風/追い風）・風統合の検証を「完全移行」（Phase 6）で追加
      test_evaluation_bulk.py  ✅ 改善計画T240: compute_edge_cost（Edge毎）とcompute_edge_costs_bulk（numpyベクトル化）の全Edge一致（highway種別・タグ組み合わせ・欠損データパターンを網羅する合成グラフ、wind/max_average_grade_percent/penalty_strengthの組み合わせ）の検証。実データ（dev DB、東京都心12万Edge超）での追加突き合わせもT240完了条件として実施済み（テストファイル外、improvement-plan.md参照）
      test_evaluation_service.py ✅ EvaluationService.evaluate_graphのDIモックテスト（Hard Constraint除外・属性欠損・空グラフ・カスタムRoutePreference）（Road Graph移行Phase 4、新規。Phase 5でload_route_preference（既定パス/カスタムパス）・設定ファイル経由デフォルトの検証を追加）
      test_graph_service.py   ✅ GraphService.build_graph_with_surface_tags_for_bboxのDIモックテスト（Road Graph移行Phase 1、新規）。get_or_build_graph_with_attributesのタイル単位キャッシュ動作（単一/複数タイル・部分キャッシュ・一部タイル取得失敗）の検証を追加
      test_vector_tile.py      ✅ encode_road_surface_tileのデコード可能性・座標範囲・surface_goodプロパティ・2点未満のway除外の検証（Step10改訂）
      test_wind_forecast_cache.py ✅ 気象グリッドのRedis永続キャッシュ読み書きの検証（改善計画T398。フェイクRedis使用、実I/Oなし。旧SQLite版test_cache_db.pyはこの移行で削除）
      test_basemap_client.py  ✅ BasemapClientのプロキシ・URL書き換え・キャッシュ利用の検証（Step10）
      test_basemap_routes.py  ✅ /api/basemap/{path}, /api/basemap/refreshのDIモックテスト（Step10）。basemap/refreshのper-IPレート制限（6回/分）の429検証を追加
      test_jma_tile_client.py ✅ 改善計画T412: JmaTileClientのプロキシ・キャッシュ戦略の分岐（タイル本体=Redis cache-aside／targetTimes*.json=TTLCache）の検証。T510でget_cached/fetch/getの3メソッド分割の検証を追加
      test_jma_tile_redis_cache.py ✅ 改善計画T510: jma_tile_redis_cacheのget/set往復・fail-open（Redis障害/未接続/壊れたエントリ）の検証。フェイクRedis使用、実I/Oなし
      test_jma_tile_prewarm_service.py ✅ 改善計画T510: targetTimes.jsonからの現在エントリ選定（risk/rasrf=element絞り込み、nowc=直近実況優先）・タイル列挙・プリウォーム本体の重複フェッチ回避の検証
      test_jma_tile_routes.py ✅ 改善計画T412: /api/jma-tile/{path}のDIモックテスト。502エラー・per-IPレート制限（300回/分）の429検証。T510でキャッシュヒットがレート制限を消費しないことの検証を追加
      test_tile_cache.py      ✅ ファイルキャッシュのパスフラット化・パストラバーサル耐性の検証（Step10）
      test_rate_limiter.py     ✅ check_rate_limitの固定窓レート制限（上限内許可・超過拒否・クライアント単位の独立性・ウィンドウ経過後のリセット）の検証。_sweep（アクセス途絶クライアントの定期削除、メモリリーク対策）の検証を追加
      test_migrate.py          ✅ apply_pending_migrationsの検証: 新規ファイルの適用・記録、2回目呼び出しでの冪等（再実行なし）、一部ファイルが適用済みの場合に残りだけ適用されること（改善計画T17）
    migrations/                 ✅ 番号付きSQLファイル（`infrastructure/migrate.py`が適用。改善計画T17）。列追加・インデックス・データバックフィルはここへファイルを1つ足して行う。`create_tables`への追記は禁止（decisions/pre-static-attributes-gate.md 決定3）。0001_legacy_backfill_and_indexes.sql: 旧create_tables内にあったALTER/インデックス/バックフィルの移設（内容無変更）。0006_add_accident_points.sql: accident_points/accident_import_runs（T50）。0007_add_route_designations.sql: route_designations/designation_attributes/designation_import_runs（T51）。0008_stale_way_partial_index.sql: is_split_up_to_date用の部分GiST索引（T68、性能対策）。0009_designation_attributes_osm_way_id.sql: designation_attributesのキーをedge_id（road_edges FK）からosm_way_id（osm_raw_ways FK）へ変更（T74、DROP→再作成）
    data/                       ✅ 地図タイル/路面ベクタタイル共通キャッシュ（tile_cache/）の保存先。gitignore対象（Step10）。旧SQLite永続キャッシュ（ridecompass_cache.db）はT398でRedisへ移行し撤去済み
    requirements.txt          ✅ mapbox-vector-tile追加（路面のMVTエンコード用、Step10改訂）。sqlalchemy/asyncpg/geoalchemy2/shapelyをRoad Graph移行「永続化」で追加。astral（T173、暦計算・外部通信なし）・tenacity（Open-Meteo再試行、改善計画）を動的気象レイヤー関連で追加。cachetools（改善計画T244、flood/jma_warning/wbgt各クライアントが個別実装していたTTLキャッシュを標準ライブラリへ統一）を追加。networkxは「完全移行」（Route Engine）時に追加したが、T220でDijkstra本体がscipy.sparse.csgraphへ移行した後もNetworkX版の関数群が実行時経路から呼ばれないまま残っていたため、改善計画T321（デッドコード監査）で依存ごと削除した
    Dockerfile                ✅
    .env.example              ✅
    pytest.ini                ✅ asyncio_mode = auto
  frontend/
    next.config.ts               ✅ `/api/basemap/*`と`/api/region/road-surface-tiles/*`、`/api/jma-tile/*`（改善計画T412）をバックエンドへプロキシするrewrites（同一オリジン維持、Step10・Step10改訂）
    src/
      proxy.ts                   ✅ 改善計画T272: `/admin`ルーティング境界のHTTP Basic認証（Next.js 16の`middleware.ts`改称後の規約名、frontend/AGENTS.md参照）。環境変数ADMIN_BASIC_AUTH_USERNAME/PASSWORD未設定時は常に到達不可
      app/
        page.tsx               ✅ 左サイドバー（折りたたみ可）＋右地図の2ペインレイアウト統括。位置情報state・天候取得もここで保持（UI再構成）。改善計画T270で研究・開発者セクションを/adminへ移設済み（地図インスタンスに紐づく「地図データを再読み込み」ボタンのみ「開発者」に残る）
        layout.tsx              ✅
        admin/page.tsx           ✅ 改善計画T270: 軸スタジオ・研究・開発者ツールをまとめた独立URLの管理画面。権限制御（改善計画T272、2026-08-24完了）は`src/proxy.ts`がこのルーティング境界（`/admin/:path*`）でHTTP Basic認証を敷く。研究モードの評価重みstateはlocalStorage経由でpage.tsxと共有する（useStoredJsonStateのstorageKey、hooks/参照）
        admin/api/axis-definitions/route.ts, [axisId]/route.ts, [axisId]/unpublish/route.ts
                                   ✅ 改善計画T305で新設。軸CRUD管理APIの同一オリジンproxy（lib/adminApiProxy.ts本体、「管理画面の権限制御」節参照）。`/admin/:path*`に含まれるためproxy.tsのBasic認証ゲートを自動的に通り、ブラウザが/admin読込時の認証情報を自動転送する
        api/version/route.ts    ✅ GET /api/version。RENDER_GIT_COMMIT（frontendは今もRender稼働のため据え置き）/起動時刻を返すRoute Handler（force-dynamic）。バックエンドの/healthと対になるデプロイ確認用（「デプロイの反映確認」で新規）
      components/
        Map/MapView.tsx         ✅ 地図描画に専念（controlled props）。全候補ベース表示・選択中ハロー・動的レイヤー（風、選択中候補のみ）・地域レイヤー（標高＝GSIラスタタイル/路面＝自前ベクタタイル、いずれもMapLibreのtile sourceとして常設、同時表示可）の構成（Step4, Step9, UI再構成, Step10, Step10改訂）
        LocationControl/LocationControl.tsx ✅ 現在地表示・手動緯度経度入力フォーム（UI再構成、MapViewから分離）
        Map/mapLayers.ts        ✅ 地図レイヤーのカタログ（id/label/kind/description、単一ソース）。チップ行とサイドバーのセクション枠はこの列挙で描画（UI再構成 第2段で新規）
        MapOverlayControls/MapOverlayControls.tsx ✅ 地図上のON/OFFチップ行＋▶で開く凡例内訳パネル（レイヤー固有の知識を持たない汎用描画係。UI再構成 第2段で全面書き換え、旧⚙ボタン・RoadFilterDialogは廃止。凡例パネルは実機フィードバックを受け位置ズレ・展開挙動を反復修正済み）
        Map/staticAttributeLayers.ts ✅ P1/T50/T51の静的レイヤー色分け・凡例・絞り込み軸カタログ（DESIGNATION/TUNNEL/ONEWAY/STOP_POI/SUPPLY_POI/ACCIDENT、STATIC_FILTER_AXES。7章参照）。buildCategoricalLayerDefsで同型3組を共通化（T82）。car_stressを含むramp軸（停止密度・事故密度等）の凡例はRAMP_AXES（axisLayers.ts）から自動合流し、STATIC_FILTER_AXESへの手書きは不要（改善計画T292でcar_stress分の手書きエントリを廃止）。改善計画T347: BICYCLE_INFRA（専用地図レイヤー）は評価軸bicycle_infra_qualityへの置き換えに伴い削除
        Map/icons.tsx              ✅ 地図上チップ用の自作SVGアイコン群（レイヤー数増加に伴う新規）
        Map/useLayerDataStatus.ts   ✅ 改善計画T123: レイヤーデータ状態（loading/empty/error、改善計画T87）の算出・追跡（computeLayerDataStatus/clearStaleTrackedSourceErrors＋状態管理フック）。MapView.tsxから抽出（2026-08-17レビューDEFER(a)の履行）
        Map/dynamicWeather.ts        ✅ 改善計画T184: 動的気象レイヤー（風・降水）の共通契約（表現3種・共有タイムライン・範囲外非描画・追加4ステップの1本道。DOM/MapLibre非依存の純粋データ層。「動的気象レイヤー」節参照）
        Map/windLayer.ts             ✅ 改善計画T178フォローアップ・T183・T185・T198: 風の格子点マップのデータ層（フレーム変換・色スケール・詳細格子間隔のズーム依存化。wind-grid-config.jsonの間隔定数をimportし手動同期を廃止）
        Map/precipitationNowcast.ts   ✅ 改善計画T171・T183: 気象庁降水ナウキャスト（実況〜+60分）＋延長予報（+60分以降、風と共通の格子点マップへ相乗り）のデータ層
        Map/jmaNowcastFrames.ts        ✅ 改善計画T204: JMAナウキャスト系（降水・雷/竜巻）に共通する時刻一覧の取得・整形（fetchJmaTargetTimes/trimToCurrentAndFuture/parseValidtime）。precipitationNowcast.tsから抽出、両ファイルが単一の情報源として参照
        Map/thunderNowcast.ts          ✅ 改善計画T204: 雷ナウキャスト（thns）・竜巻発生確度ナウキャスト（trns）のデータ層。両者は共有の時刻一覧（targetTimes_N3.json）を使うが独立したON/OFFチップに分ける
        Map/riskMap.ts                 ✅ 改善計画T410: キキクル（土砂land・大雨rain_mesh・浸水inund）・線状降水帯予測マップ（sjfcstmap）のタイル・時刻取得データ層。全て「現在のみ」のスナップショット（未来フレームを持たない）。改善計画T432でキキクル3種は「防災」カテゴリとして共有タイムラインと無関係な常時マウントへ、線状降水帯予測マップは「降水」チップ傘下（現在〜3時間先のみisWithinFutureWindowで重畳）へそれぞれ再分類
        Map/primaryAttributes.ts       ✅ 改善計画T163〜T168: 一次属性カタログ（axis-catalog.jsonのprimary_attributesが単一の情報源）と2次→1次/1次→2次の双方向導出（片側import、設計原則2）
        DynamicLayerTimeSlider/       ✅ 改善計画T170・T188〜T193: 時刻依存レイヤー共通の時刻スライダーUI（横スクロールルーラー、Pointer Events自前ドラッグ）。レイヤー固有の時刻形式を知らない汎用コンポーネント
        MapLayersPanel/          ✅ サイドバーのレイヤー設定パネル（MapLayersPanel.tsx: kind別グループ＋レイヤーごとの表示スイッチ・凡例・panelHint説明文（T84カタログ集約） / RoadFilterEditor.tsx: 路面絞り込みの下書き→適用編集 / WidthSwatch.tsx: 太さプレビュー）。旧MapLegendPanel＋旧RoadFilterDialogの統合置き換え（UI再構成 第2段）
        BackendStatus.tsx        ✅
        RouteForm/RouteForm.tsx  ✅ 距離入力＋生成ボタン（Step4）
        RouteSettingsPanel/RouteSettingsPanel.tsx ✅ 改善計画T267: 一般ユーザー向けルート設定（0次の除外チップ・軸ごとのチェックボックス＋重みスライダー・重み配分の積み上げバー）。常時表示。route_preference（weightOverrideEnabled）はpage.tsxとlocalStorage経由で状態を共有し、withAutoEnableで操作すると自動的に上書きが有効になる。hard_filtersは常時送信（省略時と同じ既定値のため挙動は変わらない）。改善計画T306: 当初のT267設計は軸を観測/推定/動的の3カテゴリへ見出し付きでグルーピング表示していたが、T305で軸スタジオのGUI作成軸がcategory="推定"固定になった結果「観測/動的グループはコード内蔵の既定軸のみ」という非対称が生まれたため撤去し、公開済み軸をフラットな1本のリストで表示する構成へ変更した（category自体はbackend側に残置、§「軸カタログ公開API・表示名のDB化」参照）。プリセットボタン（「バランス」等）は2026-08-27に撤去済み（重み配分の根拠が不明瞭なため、ユーザー判断）。改善計画T418: 各軸の行末尾に「この条件で地図を色分け」トグル（`renderMapColorToggle`）を追加し、地図上チップから撤去した評価軸の色分け起動をこのパネルへ移設した。専用の表示レイヤーを持つ軸（kind="ramp"、`catalog.secondaryAxes`のlayerId）・風（`wind`、axisIdで直接`windAxis`へ紐付け）・改善計画T423で追加した勾配（`gradient`、axisIdで直接`gradientAxis`へ紐付け）だけがトグルを持ち、持たない軸とルート確定後の風・勾配は押せない案内表示になる
        RouteAxisProfile/RouteAxisProfile.tsx ✅ 改善計画T402: 選択中ルートの`RouteCandidate.axis_difficulties`
          を軸ごとの横棒グラフ一覧で表示（レーダーチャートは不採用）。軸の並び順・ラベルは
          useAxisCatalog().axesから取得しハードコード辞書は持たない。バー色は
          Map/axisLayers.tsのrampColorForBand(Math.round(value), 101)を再利用し地図の段階配色
          （緑→黄→橙→赤）と一致させる。既存のBottomSheet（page.tsx: routeProfileOpen、
          mobileSheetの3タブ排他ドメインとは独立）から開く導線
        WeatherPanel/WeatherPanel.tsx ✅ 気温・風向風速・降水量・天気アイコン・日の出/日没
          表示（Step6、改善計画T387フォローアップで大幅刷新）。改善計画T387フォローアップ
          （2026-08-29、方針「常設エリアは実測値、今日の見通しは予測値」）: データ源を
          Open-Meteo（`GET /api/weather`、旧`WeatherConditions`）から最寄りアメダス観測所の
          実測値（`GET /api/weather/amedas`、`AmedasObservation`）へ切替え、TodayOutlookとは
          独立にフェッチする（`useWeatherConditions.ts`のamedas/amedasLoading/amedasError）。
          これにより常設ヘッダーの表示がOpen-Meteoの障害・遅延から影響を受けなくなった。
          降水確率（予報）はアメダスに相当データが無いため実測降水量（mm/10分）へ意味を
          変更、天気アイコンはOpen-Meteoのweather_codeではなくアメダスの日照時間
          （sunshine_10min_minutes）・降水量・気温から晴れ/くもり/雨/雪を簡易判定する
          専用ロジック（同ディレクトリのamedasWeatherIcon.ts、weatherCode.tsとは別物・
          霧雷雨は判別不可）。突風はアメダスの速報値レスポンスに突風フィールドが存在しない
          （実データ確認済み）ため非表示。日の出/日没チップを新規追加（予報不要のため
          backend側でastralによるローカル計算、TodayOutlookから移設）。
        TodayOutlook/TodayOutlook.tsx ✅ 改善計画T385: 「今日の見通し」二次パネル
          （今日の降水確率最大・最大風速・気温レンジ・UV指数最大、今日の天気の流れ）。
          常設ヘッダーには項目を足さず、WarningBadgeと同じRadix Popoverパターンでタップ時
          のみ開く（T384調査「場所・季節を問わず常に意味を持つ値」だけに絞った日次見通し）。
          データ源は引き続きOpen-Meteo（`weather`）のみで、予報専用パネルという位置づけ。
          T385フォローアップ: UV指数最大値の追加（常設ヘッダーのtitle属性はスマホの
          タップでは実質見えないため、確実に見えるここへ追加）と、「今日の天気の流れ」
          （today_periods、現在時刻を含む2時間区間から2時間おき8コマ、時刻・天気アイコン・
          気温・降水確率を横スクロール可能な帯で表示。weatherCode.tsのアイコン判定を再利用）
          を追加した。T385フォローアップ2: パネル幅を15.5rem→19rem（スマホ横幅を塞ぎ切らない
          範囲で拡張）。T387フォローアップ（2026-08-29）: 日の出/日没は常設ヘッダー
          （WeatherPanel）へ移設したため本パネルから撤去。取得失敗（error）時は警戒色の
          トリガーで気づけるようにした（旧実装はweather===nullを「取得失敗」「読み込み中」
          「意味のある値が無い」の区別なく同じ扱い＝トグル非表示にしていた）。
        WarningBadge/WarningBadge.tsx ✅ 改善計画T205・T174・T212: 警報・注意報バッジ（地図レイヤーではなくバッジで表現する警告表示の共通コンポーネント）。JMA固有の型に依存しない汎用item形で、T174（WBGT警告）・T212（河川氾濫予報）も同じコンポーネントを再利用する。levelは4段階（advisory/warning/severe_warning/emergency_warning）で、JMA警報は3段階のみ・WBGT/河川氾濫予報は4段階全て使う
        DebugPanel/DebugPanel.tsx    ✅ デバッグモードON/OFFチェックボックス（フロントエンドUX改善）。改善計画T270で表示場所を/adminへ移設（コンポーネント自体はメインページ非依存のため変更なし）
        DebugConsole/DebugConsole.tsx ✅ デバッグモードON時、地図イベント・外部API呼び出しログを表示（フロントエンドUX改善）。改善計画T270で/adminへ移設
        AxisStudio/               ✅ 改善計画T270（T221 Stage E）: 軸スタジオ本体（/admin専用）。AxisStudio.tsx: 一覧取得・作成・更新・削除・非公開化の状態管理（/admin/api/axis-definitions、改善計画T305で同一オリジンproxy化。編集・複製・新規作成はcomponents/ui/Dialogのモーダルで開く） / AxisComposer.tsx: **改善計画T332で単一フォームから4ステップのウィザードへ再設計**（UIレビュー2026-08-25のF-2「変換テンプレート4択が数式的な語彙のまま」への対応。ステップ順に「基本情報(basic)」表示名・説明・既定重み→「点数のつけ方を選ぶ(shape_kind)」→「点数の詳細を設定(shape_params)」選んだカードに応じた材料・折れ点等の入力→「地図表示・公開(display_publish)」show_map_icon・chip_label等。各ステップは`validateStep()`で個別に検証し、明示的な保存ボタンを押すまで`onSave`は呼ばれない。**「点数のつけ方を選ぶ」の中身は改善計画T396/T397（2026-08-29、shapeの2プリミティブ化節を参照）で作り直された**——保存時の`kind`は常に`breakpoint_linear`または`categorical`の2プリミティブへ正規化し、選択カードは技術名ではなく利用者視点の3枚「なめらか評価」（区分線形・旧flag_sumを吸収）・「ぴったり評価」（categorical）・「かけあわせ評価」（他軸を重みで組み合わせる、旧recipe_then_breakpoint_linear相当、内部軸参照という上級者向け用途のため`advanced`表示）へ整理した。T332時点の「4種のテンプレート（categorical/breakpoint_linear/flag_sum/recipe_then_breakpoint_linear）」という記述はT396/T397で古くなっている点に注意（改善計画T449で訂正）。）。axis_id（改善計画T305で自動採番へ変更、入力欄なし）・category（同じくaxis_id経由で作る軸は常に「推定」固定、入力欄なし）は非表示。材料候補は改善計画T277でhooks/useMaterialCatalog.ts（GET /api/material-catalog、backend/app/domain/material_catalog.py: MATERIAL_CATALOGが単一の情報源）から動的取得する形へ置き換え済み（取得失敗時はlib/axisMaterialsCatalog.tsの静的9件へフォールバック）。categorical材料の値入力欄は改善計画T340でhooks/useMaterialValues.ts（GET /api/material-catalog/{material_id}/values）＋lib/materialValueLabels.tsが「値の候補」セレクトを添える（値一覧が空の材料は従来どおり自由テキスト入力のみ、詳細は「軸スタジオの値入力UX改善」節参照）
      hooks/
        useIsMobile.ts             ✅ `MOBILE_BREAKPOINT_PX`=640。`globals.css`の`@media`とのズレをテストで自動検証（フロントエンドUX改善）
        useLocation.ts              ✅ 現在地取得・手動入力・現在地への再取得（`handleLocateMe`）の状態を集約（UI再構成でMapViewから分離）
        useDebugLog.ts               ✅ `useDebugEnabled()`。`lib/debugLog.ts`の`localStorage`永続化フラグをReact stateとして購読
        useIsomorphicLayoutEffect.ts  ✅ SSR時の警告回避用ヘルパー
        useStoredState.ts              ✅ localStorage永続化付きuseState（page.tsxの保存付き状態を抽出。改善計画T47 R-6の閾値到達時対応）。改善計画T270でJSON直列化の薄いラッパー`useStoredJsonState`を追加（page.tsx/admin/page.tsx間の評価重みstate共有に使う）。改善計画T321（デッドコード監査）: `reloadKey`オプションを追加。`layerVisibility`の`deserialize`がビルド時静的な軸集合しか走査せず軸スタジオ公開軸のON状態がリロードで消える実バグがあったため、`axisCatalog.loaded`を`reloadKey`に渡すことで「マウント直後は静的フォールバック集合、カタログ取得完了後は実行時軸集合」の2段階でlocalStorageから再復元できるようにした（page.tsx側の対応、下記1831行目周辺参照）
        useWeatherGrid.ts               ✅ 改善計画T183フォローアップ: 風・延長降水予報が共有する格子点マップのフェッチ・穴あき対策マージ・詳細格子切替を集約（元page.tsx内の風専用ロジックを共有可能な形へ抽出）
        useAxisCatalog.ts               ✅ 改善計画T269: マウント時にGET /api/axis-catalogを1回取得。取得完了まで/失敗時は既存7軸の静的フォールバック（axis-catalog.json＋evaluationAxes.tsの手書きラベル）を返す
        useMaterialCatalog.ts           ✅ 改善計画T277: マウント時にGET /api/material-catalogを1回取得。取得完了まで/失敗時はlib/axisMaterialsCatalog.tsの静的9件をフォールバックとして返す（useAxisCatalog.tsと同型のパターン）。改善計画T321（デッドコード監査）: `response.materials.length > 0`ガードが「取得中/失敗」と「取得成功0件」を同一視し後者でも静的フォールバックが残り続けるT318と同型のバグとして残存していたため、useAxisCatalog.tsと同じ形へ修正
      lib/
        debugLog.ts                ✅ デバッグモードのON/OFF状態（`localStorage`永続化）とログ出力本体。`services/`配下の各fetchラッパー・`MapView.tsx`から呼ばれる（フロントエンドUX改善）
        adminApiProxy.ts            ✅ 改善計画T305で新設（旧adminToken.ts・useAdminCredentials.tsは撤去）: 軸CRUD管理APIのサーバー側プロキシ本体。`app/admin/api/axis-definitions/`配下の各route handlerから呼ばれ、サーバー環境変数ADMIN_BASIC_AUTH_USERNAME/PASSWORDからbackend宛Authorizationヘッダを組み立てて転送する（「管理画面の権限制御」節参照）
        axisMaterialsCatalog.ts      ✅ 改善計画T270で新設、T277でGET /api/material-catalogの取得失敗時フォールバックへ役割縮小。軸コンポーザーの材料選択候補（既存9件のスナップショット）。単一の情報源はbackend/app/domain/material_catalog.py: MATERIAL_CATALOGへ移行済みで、通常利用時はこのファイルの更新不要（動的取得が失敗した場合のみ古いまま表示される）
      services/
        healthApi.ts             ✅
        routeApi.ts               ✅ previewRoute() / generateRoutes()。previewRouteは`/api/routes/preview`
                                    （Step3の疎通確認用エンドポイント）向けのクライアント関数で、
                                    現状どのUIコンポーネントからも呼ばれていない（テストのみが参照）
        weatherApi.ts             ✅ getCurrentWeather()
        regionApi.ts               ✅ roadSurfaceTileUrl() / ROAD_TILE_MIN_ZOOM/MAX_ZOOM / refreshBasemapCache()（Step10改訂。路面がタイル化されJSON型を持たなくなったため`types/region.ts`は削除済み）
        axisCatalogApi.ts           ✅ 改善計画T269: getAxisCatalog()。GET /api/axis-catalog（認可不要）のクライアント関数、fetchJson共通ヘルパー経由
        materialCatalogApi.ts       ✅ 改善計画T277: getMaterialCatalog()。GET /api/material-catalog（認可不要）のクライアント関数、fetchJson共通ヘルパー経由
        axisAdminApi.ts             ✅ 改善計画T270: listAxisDefinitions()/createAxisDefinition()/updateAxisDefinition()/deleteAxisDefinition()/unpublishAxisDefinition()。改善計画T305で呼び出し先を同一オリジンの`/admin/api/axis-definitions`（Next.js route handler、lib/adminApiProxy.ts参照）へ変更し、Authorizationヘッダの手動付与を撤去（ブラウザの認証キャッシュが自動付与するため）。PUT/DELETE対応が必要なためfetchJson[GET専用]ではなく自前実装。改善計画T277でshapeが参照する材料id（terms/flags/categoricalのmaterial）が未知の場合、backend側が422を返すようになった
      types/
        generated/                 ✅ backendのOpenAPIスキーマからの生成物（openapi.json＝backend/scripts/export_openapi.pyが出力、api.d.ts＝npm run generate:apiが生成）。コミット対象で、CIのapi-contractジョブがドリフトを検知する。axis-catalog.json（一次属性・二次軸カタログ、T145b/T163）・wind-grid-config.json（風格子間隔・上限点数、改善計画T198）・route-generate-config.json（`{"max_distance_km": 100}`、backend `api/routers/routes.py: MAX_ROUTE_DISTANCE_KM`が正準定義、改善計画T471。`RouteForm.tsx`/`page.tsx`の距離上限ハードコードの重複を解消する片側import）等の付随生成物も同じ仕組みでドリフト検知される
        route.ts                  ✅ generated/api.d.tsの再エクスポート＋GeoJSON型の補正（Coordinates, RouteSegment, RouteSegmentDetail, RouteCandidate等。手書きの型二重管理を廃止、改善計画T4）
        weather.ts                 ✅ 同上（WeatherConditions）
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
  "external": { "weather:open-meteo": { "calls": 120, "errors": 8, "error_types": {"http_429": 6, "ConnectTimeout": 2},
    "last_error_type": "http_429", "last_error_at": "2026-08-17T21:03:11+00:00",
    "last_success_at": "2026-08-17T21:04:02+00:00", "retried_calls": 15, "retry_attempts_total": 22,
    "stale_fallback_used": 3, "cache_hit_rate": 0.71, "avg_ms": 340, "max_ms": 4200 }, ... },
  "rate_limit_rejections": { ... } }

POST /api/routes/preview   # Step3: 単一区間のルート取得確認用（暫定エンドポイント。デバッグ・疎通確認用に残置。
                           # フロントエンドの実運用UIからは呼ばれない。frontend/src/services/routeApi.ts:
                           # previewRoute()は用意されているが未使用）
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
  "route_preference": { "gradient":0.15, "surface_q":0.19, "wind":0.26, "stop_density":0.20,
    "car_stress":0.20, "accident":0.08, "night":0.0 },
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
  # penalty_strength（改善計画T218・T12 ADR原則1）は
  # 0次ハードフィルタの勾配しきい値で、いずれもroad_graphエンジンのみに効く。
  # hard_filters（改善計画T266）は0次ハードフィルタ（`no_bicycle`/`motorway`/`trunk`、
  # domain/evaluation.py: DEFAULT_HARD_FILTERS）の個別ON/OFF。route_preference等の
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
      "elevation_gain_m":12.8, "min_elevation_m":1.1, "max_elevation_m":9.6, "max_gradient_percent":0.8,
      "wind_score":0.15, "road_score":76.2,
      "segments": [
        {
          "geometry": { "type":"LineString","coordinates":[...] },  /* 区間の道なり形状（ルートgeometryの部分列。地図の色分けはこれに沿って描く） */
          "start_latitude":35.7597, "start_longitude":139.7387,
          "end_latitude":35.7602, "end_longitude":139.7390,
          "cumulative_distance_km":0.0, "distance_km":1.16,
          "estimated_arrival_time":"2026-08-13T23:20:43",
          "gradient_percent":0.2, "wind_penalty":-0.83, "road_surface_good":true,
          "car_stress":2,
          /* ↑ 車ストレスの生値（P1）。road_surface_goodと
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

### 汎用ジョブレジストリ（改善計画T265）

`infrastructure/job_registry.py`は、`POST /api/routes/generate`の冷パス（上記参照）を
バックグラウンド化するために新設した、プロセス内メモリのみの汎用非同期ジョブ管理
（`create_job`/`get_job`/`set_running`/`set_done`/`set_failed`、完了から10分経過した
ジョブはTTLベースで自動パージ）。単一プロセスデプロイ前提（`axis_registry_service.py`の
push型更新と同じ前提）で、ルート生成の型（`RouteGenerateResponse`等）を一切知らない
汎用モジュールにしてある（`result`は`Any`型、`api/routers/routes.py`との循環importを
避けるため）。将来他の重い処理（例: 大規模バッチのオンデマンド実行）にも転用できる。

実行にはFastAPIの`BackgroundTasks`（`asyncio.create_task`ではなく）を使う——本番の
ASGIサーバーはレスポンス送出後にタスクを実行するため「即座に返す」要件を満たしつつ、
`TestClient`はリクエストサイクル内でバックグラウンドタスクまで同期的に実行するため、
テストが`asyncio.sleep`によるポーリング待ちを必要とせず決定的になる（`tests/
test_routes_generate.py`参照）。

バックグラウンドタスクはFastAPIのリクエストスコープ外（レスポンス送出後）で実行される
ため、リクエストスコープのDBセッション（`Depends`経由）をそのまま使えない
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
Response 502（Open-Meteo呼び出し失敗時）:
{ "detail": "天候情報の取得に失敗しました" }
Response 429（同一クライアントIPから1分あたり60リクエスト（`WEATHER_RATE_LIMIT_PER_MINUTE`）を超えた場合）:
{ "detail": "リクエストが多すぎます。しばらく待ってから再試行してください。" }
# 改善計画T387フォローアップ（2026-08-29）: 以前はここでアメダス実測値を上書きマージ
# していたが、常設ヘッダー（WeatherPanel）がGET /api/weather/amedasを直接呼ぶよう分離
# したため削除した。このエンドポイントは常にOpen-Meteoの値をそのまま返す
# （今日の見通しTodayOutlook専用）。

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
  参照する`lit`（`shoulder`は改善計画T122でP1実測0.0%の死に補正と判明し撤去済み。かつて安全度
  レシピが使っていたが軸自体はT148で削除、`lit`のみT139でnight軸へ転用され現在も使用中）、
  改善計画T145bが追加したkm正規化密度3種`accident_per_km`/`stop_per_km`/`intersection_per_km`
  （P0/P1/T51/T74/T90/T292/T145b、現行タイル世代v16。7章参照）プロパティを持つ。
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
Response 200（Content-Type: application/vnd.mapbox-vector-tile）: レイヤー名`poi`。各地物（Point）は`kind`（traffic_signals/crossing/stop/give_way/level_crossing、停止要因）または`degree`（接続路数、交差点密度）を持つ
Response 400/429: road-surface-tilesと同じ規約

GET /api/region/accident-tiles/{z}/{x}/{y}.pbf   # 警察庁交通事故統計オープンデータの発生地点（T50、7章参照）。`AccidentService`が担当し road-surface-tiles/poi-tiles とは別系統
Response 200（Content-Type: application/vnd.mapbox-vector-tile）: レイヤー名`accidents`。各地物（Point）は`involves_bicycle`（自転車関連か）・`fatal`（死亡事故か）プロパティを持つ
Response 400/429: road-surface-tilesと同じ規約（同時実行数上限は`accident_tile_max_concurrent`で別枠）

POST /api/region/axis-inspector   # 区間インスペクタ（T146）。クリックされた道路（osm_way_id）について、一次属性→取得可能な二次軸スコア（車の圧迫感を含む全軸）の内訳→参考合成コストを返す
Request: `{ "osm_way_id": number }`。GETでなくPOST+JSONボディなのは、
  `/api/routes/generate`と同じ形に統一しているため（改善計画T292: かつての
  レシピ上書きパラメータ（旧`car_stress_recipe`/`road_suitability_recipe`/
  `motor_vehicle_density_recipe`）は、専用Pythonレシピの廃止（旧`POST /api/region/
  car-stress-breakdown`・`CarStressBreakdown`も本エンドポイントへ統合・廃止）に伴い削除した）
Response 200: `AxisInspectorResult`（`highway`/`tags`/`is_designated`/`axes: AxisInspectorAxis[]`（axis_id・difficulty・weight・available）/`composite_difficulty`/`covered_weight_fraction`）。
  gradient/windは単独wayでは算出不能なため常に`available=false`（ルート内の正確な値はルート生成結果のsegmentsを見る）。取得できなかった軸は合成から除外し残りの重みで再正規化、`covered_weight_fraction`はその再正規化の対象になった重み割合（0-1）。該当wayが存在しない場合はnull。
  `axes`は公開軸（is_published=True）のみを返す（car_stressの内部軸5つはaxes.car_stressの
  difficulty値へ既に合成済みで、個別には現れない）
Response 422（osm_way_idが整数でない場合）
Response 429: road-surface-tilesと同じレート制限（`ROAD_TILE_RATE_LIMIT_PER_MINUTE`）を流用

GET /api/basemap/{path}   # Step10: OpenFreeMapの地図タイル/スタイルJSON/スプライト/グリフのプロキシ＋キャッシュ
Response 200: 上流（OpenFreeMap）のContent-Typeをそのまま転送
Response 502（上流取得失敗時）:
{ "detail": "地図タイルの取得に失敗しました" }
Response 429（同一クライアントIPから1分あたり300リクエスト（`BASEMAP_RATE_LIMIT_PER_MINUTE`）を超えた場合。road-surface-tilesと同じ`rate_limiter.py`を使うが上限値は別）:
{ "detail": "リクエストが多すぎます。しばらく待ってから再試行してください。" }

POST /api/basemap/refresh   # Step10: 地図タイルキャッシュを全消去（フロントの「変わらないデータを更新」ボタン）
Response 200:
{ "status": "ok" }
Response 429（同一クライアントIPから1分あたり6リクエスト（`BASEMAP_REFRESH_RATE_LIMIT_PER_MINUTE`）を超えた場合。
             全キャッシュ削除という重い操作かつ連打の意味が薄いため、他のbasemapエンドポイントより低い上限にしている）:
{ "detail": "リクエストが多すぎます。しばらく待ってから再試行してください。" }
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
5. 残った候補それぞれについて、国土地理院APIから獲得標高・最高/最低標高・最大勾配を算出（距離連動サンプリング＝約1km間隔・12〜32点、並列取得）
6. 残った候補それぞれについて、区間ごとの推定到達時刻（仮定巡航速度から逆算）の風を`WeatherService.get_conditions(point, at=...)`から取得し、進行方位との関係から`wind_score`を算出（標高と同じ距離連動サンプリング、並列取得）。詳細は「風評価（`wind_score`）の設計（Step7）」を参照
7. 各候補について、openrouteserviceの`extra_info=surface`から`road_score`（舗装率）を算出し、距離の近さ・獲得標高・`wind_score`・`road_score`を候補集合内でmin-max正規化した上で重み付け合成した`total_score`を算出、`total_score`降順に並べ替え。詳細は「路面評価（`road_score`）と総合スコア（`total_score`）の設計（Step8）」を参照
8. 5-6で使った標高・風の生データと、7で使った路面のインデックス範囲データから、区間ごとの詳細（`segments`）を構築し各候補にマージ。詳細は「候補ルートの難易度可視化の設計（Step9）」を参照

### 将来実装予定
9. 半径を適応的に調整して距離精度を高める（現在は固定ヒューリスティックのみ、上記「既知の制約」を参照）
10. 候補地点を道路網の実データ（PostGIS上のRoad Graph等）から選ぶ、候補数を増やす（現在は幾何学的な計算のみ）。Step10でOverpass APIを導入したのは「候補ルートに紐づかない地域全体の路面表示」のためであり、この項目（周回ルート生成そのものの候補地点選定）とは目的が異なる点に注意（Overpass自体は改善計画T222でGraphServiceのDBなし構成撤去に伴いコードから削除済み、現在はPostGIS第一系統のみ）

風評価（`wind_score`）はStep7で実装済み。「風評価（`wind_score`）の設計（Step7）」を参照。序盤/中盤/終盤で風負荷の重みを変える拡張（帰路の向かい風を重視）は設計上考慮するが、MVPでは必須としない（現状は区間距離での単純な加重平均のみ）。

総合スコアリング（Step8の`total_score`算出機構）が使っていた`scoring.yaml`は
**改善計画T548（2026-09-03）で撤去済み**（前節「路面評価と総合スコアの設計（Step8）」参照）。

### 評価重みのリクエスト上書きと評価モデル研究時の構成（研究インターフェース改善 Phase 1）

評価モデルの探索・研究（[research-interface-review-2026-08-15.md](research-interface-review-2026-08-15.md)）のため、
`RoutePreference`（Edge評価・区間難易度・絶対、既定値は`domain/axis_definitions.py:
AXIS_DEFINITIONS`のdefault_weight、改善計画T316）の重みは`/api/routes/generate`のリクエスト
ボディでリクエスト単位に上書きできる（§10-1）。実際に適用された値はレスポンスの`conditions`に
エコーされ（§10-6）、レスポンスJSONを保存すればそのまま再現条件になる。

- 配線: `dependencies.py: get_route_generation_builder`がビルダー（`RouteGenerationSetup`を返す呼び出し可能）を
  DIで供給し、エンドポイントが検証済みの上書き値（無ければNone→既定値）を渡して組み立てを完了する。
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
  gradient_percent: number | null;
  wind_penalty: number | null;
  road_surface_good: boolean | null;
  car_stress: number | null;          // 0-4（T353以前は1-5）、P1残り（生値。T353で自転車インフラの
                                       // 寄与はbicycle_infra_quality側へ分離済み）
  axis_difficulties: { [axisId: string]: number };  // axis_id→difficulty(0-100)。改善計画T309で
    // 固定7フィールド（elevation_difficulty等）から汎用dictへ置換。評価できなかった軸・
    // 非公開の軸はキー自体を持たない（`compute_edge_axis_scores`と同じ規約）。軸スタジオでの
    // 公開軸の増減にそのまま追従する
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
  max_gradient_percent: number | null;
  wind_score: number | null;
  road_score: number | null;
  segments: RouteSegmentDetail[] | null;
  overall_difficulty: number | null;  // segments.difficultyの距離加重平均（絶対基準）。改善計画T548で
    // 候補タブの並び順の基準にもなった（昇順、算出不能なnullは末尾）。旧`total_score`・
    // `score_breakdown`（研究IF改善§10-2の候補集合内相対スコア、RouteScoreComponent[]）は
    // 改善計画T548（2026-09-03）で撤去済み
  axis_difficulties: { [axisId: string]: number };  // axis_id→difficulty(0-100)。改善計画T402で新設。
    // RouteSegmentDetail.axis_difficultiesと同じ汎用dictを候補の全区間へ集約したもの
    // （merge_axis_difficultiesをビン単位ではなく候補全体に1回適用するだけ）。軸スタジオの
    // 軸増減に自動追従する。フロントのBottomSheet「ルート全体プロファイル」（横棒グラフ一覧）が
    // 消費する。旧来の軸1対1固定設計の名残だった個別フィールド群（stop_density・
    // car_stress_score・bicycle_infra_score・intersection_density・accident_density）は
    // 改善計画T431でフロントエンドの末端消費者ゼロを確認した上で撤去済み
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
  penalty_strength?: number;         // コスト式の割増率の強さ（改善計画T218・T12 ADR原則1、省略時1.0）
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

バックエンド側は `domain/route.py`, `domain/weather.py` に同等のPydanticモデルを実装済み。フィールド名はキャメルケースではなくAPIレスポンスに合わせたスネークケースにしている（フロント⇔バックエンドで変換不要にするため）。標高系・`wind_score`・`road_score`・`overall_difficulty`・`segments`内の各フィールドは取得失敗時に`null`になりうるため、フロント側も`null`許容で扱う。

候補ルートに紐づかない地域全体の標高・路面レイヤー（Step10）は、いずれもタイル形式（標高はGSIのラスタタイル、路面はPostGIS/ST_AsMVTで生成したMVT）で配信するため、Step5-9のようなJSONのレスポンスモデルを持たない。バックエンド側の`domain/region.py`にはタイル範囲計算に使う`BoundingBox`（Pydanticモデル）が残っているが、これはPostGISクエリ・（DBなし構成での）Overpass問い合わせに使う内部的な値であり、フロントエンドとの間でJSONとしてやり取りするものではない（フロント側に対応する型定義は無い）。

これで仕様書18章記載の`RouteCandidate`の項目、地図可視化用の`segments`（Step9）、および候補ルートに紐づかない地域全体の標高・路面レイヤー（Step10）が出揃った。

---

## 7. 静的道路属性と7軸評価モデル（P0/P1、外部静的データソースT50/T51）

Step8時点の評価（距離・標高・風・路面の4指標）に加え、OSMタグ・警察庁事故統計・国土数値情報
（KSJ）を材料とした指標を追加し、区間難易度（`RoutePreference`）・地図の静的レイヤーの
両方に反映した（`static-road-attributes-plan.md` P0/P1、
[external-data-sources-review-2026-08-16.md](external-data-sources-review-2026-08-16.md)）。
旧scoring.yaml（total_score、改善計画T548で撤去済み）には含めない（stop_weightと同じ
スコープ判断、後述）。

自転車インフラは改善計画T138（評価システムの層構造再設計）で独立軸（`infra_weight`）を
廃止し車ストレス側へ統合済み（9軸→8軸。当時の車ストレス判定（旧`car_closeness()`、
改善計画T292で内部軸`car_stress_bicycle_infra_adjustment`へ再設計）のcycleway補正が既に
自転車インフラの情報を反映しているため、独立に同じ情報を二重に持たない設計）。
ルート集約統計（`bicycle_infra_score`、専用インフラ区間の距離加重率%）は改善計画T431で
フロントエンド末端消費者ゼロを確認した上で削除済み（`axis_difficulties["bicycle_infra_quality"]`
が正）。区間ごとの生値（`RouteSegmentDetail.bicycle_infra`、7値分類）は改善計画T347で削除した
（下記「自転車インフラの独立公開軸化」節参照）。

続く改善計画T139で、安全度軸（旧`safety_weight`）自体を廃止した。highway・cycleway・
maxspeed・lanes・指定路線由来の部分は既にT138で車ストレス側へ吸収済みのため重複実装せず、
街灯・トンネル由来の部分のみ`domain/night.py: night_difficulty`として独立させた
（night軸の既定重み0.0で運用。街灯・トンネルを気にするユーザーが研究モードで
個別に重みを上げる想定）。事故実績は元から独立軸（`accident`）のため変更なし。
`domain/safety.py`・`safety_recipe.yaml`・関連API・地図の安全度レイヤーは表示用途
（研究モードの内訳確認等）として一時的に残置していたが、本番投入前で移行リスクが
無いことを踏まえ、改善計画T148で削除した（跡地はrecipe.pyの判定プリミティブ・
`lit`タイルプロパティ等、車ストレス・night軸に転用済みのためそのまま残る）。

続く改善計画T149（設計プロンプト改訂2026-08-18「現行9軸からの帰属先」）で、交差点密度
（旧`intersection_weight`）の独立軸を廃止し停止密度側へ統合した。`domain/difficulty.py:
stop_difficulty`が、信号・横断歩道・一時停止・踏切の密度に加え、次数3以上のタグなし
交差点の密度を低い重み（0.3、signal等を1.0とした相対値）で加算する（8軸→7軸）。
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
[material-normalization-for-axis-composition.md](decisions/material-normalization-for-axis-composition.md)参照）。
この再設計に伴い、
`RouteSegmentDetail.bicycle_infra`（7値分類の生値）・`classify_bicycle_infrastructure`
（分類関数）・MVTタイルの`bicycle_infra`プロパティ・専用地図レイヤー（旧`bicycleInfra`）は
いずれも削除した。`RouteCandidate.bicycle_infra_score`（ルート集約統計）も改善計画T431で
`ComparisonPanel`が`axis_difficulties`駆動へ移行したことで末端消費者ゼロになり削除済み。

### 8軸の一覧と重み

`domain/difficulty.py: evaluate_axis_difficulties`が材料値の辞書と重み辞書から軸別difficulty・
合成difficulty（区間の`difficulty`、絶対基準0-100）を算出する（改善計画T221 Stage B/Cで
`AXIS_DEFINITIONS`をループする形へ再編、軸ごとの変換パラメータは
`domain/axis_definitions.py`が単一ソース）。重みは
`domain/axis_definitions.py: AXIS_DEFINITIONS`の`default_weight`（改善計画T316で
`route_preference.yaml`の手書きミラーを撤廃、軸スタジオが唯一の情報源になった）：

| 軸 | axis_id（重み辞書のキー） | 既定値 | 生値の単位 | 算出元 |
|---|---|---|---|---|
| 標高（勾配） | `gradient` | 0.15 | %（区間勾配） | Step5（`ElevationService`/`ElevationAttribute`） |
| 路面 | `surface_q` | 0.19 | good/bad/unknown | Step8（`domain/road.py: classify_osm_surface`） |
| 風 | `wind` | 0.26 | m/s（正=向かい風） | Step7（`WindCalculator`） |
| 停止密度（交差点密度込み） | `stop_density` | 0.20 | 回/km | P1（信号・横断歩道・一時停止・踏切、`osm_raw_pois`。T149で旧`intersection_weight`0.05を合算） |
| 車ストレス | `car_stress` | 0.20 | 0-4（T353以前は自転車インフラ込みで1-5） | 推定（改善計画T292で`axis_definitions`の内部軸5つ+公開軸1つの階層構造へ再設計（旧専用Pythonレシピ`car_stress_level`から移行）。改善計画T150で呼称をtraffic→car_stressへ統一。改善計画T353で自転車インフラ由来の調整を`bicycle_infra_quality`側へ完全分離し、表示スケールも0-4へ再較正） |
| 事故密度 | `accident` | 0.08 | 件/(km・年) | T50（警察庁交通事故統計） |
| 夜間 | `night` | 0.0 | 0-100 | 改善計画T139（`domain/night.py: night_difficulty`、街灯なし・トンネル） |
| 自転車インフラ | `bicycle_infra_quality` | 0.15 | -4.0〜0.0（4フラグ材料の重み付き和） | 改善計画T347で独立公開軸化、T353で正規化フラグ材料4件（`highway_is_cycleway`等）を直接参照する構成へ再設計。`show_map_icon=false`のため専用地図レイヤーなし |

重みのキーは改善計画T221 Stage Bで旧`elevation_weight`等のフィールド名からaxis_idへ統一した
（`RoutePreference`はaxis_idキーの重み辞書`weights`を持ち、既定値は
`domain/axis_definitions.py: AXIS_DEFINITIONS`の`default_weight`が単一ソース
（改善計画T316でこの既定値の情報源を一本化、`route_preference.yaml`の手書きミラーは撤廃済み）。
APIの`route_preference`・フロントの重みUIもすべて同じaxis_idキー）。

旧`scoring.yaml`（total_score・候補集合内相対評価）は**改善計画T401**でdistance/difficultyの
2指標へ単純化され、その後**改善計画T548（2026-09-03）で総合スコアリング機構自体が撤去**された。
現在の候補タブの並び順は`overall_difficulty`（この8軸すべてを`RoutePreference.weights`で
重み付け合成した値）の昇順で、8軸全てが軸スタジオで設定した重みどおりに反映される（P1着手
時点では距離・標高・風・路面の4指標のみを候補順位に使うというスコープ判断だったが、「候補は
軸スタジオで決めた尺度で比較されるべき」というユーザー方針を受けT401で撤回・一本化し、
「並び順はoverall_difficultyのみでよい」というさらなるユーザー判断を受けT548でtotal_score
自体を撤去した）。**軸を追加するときは
必ずこの1本道を通す**（`CLAUDE.md`参照）: 取込（`import_profile.yaml`/`ALLOWED_WAY_TAGS`等）
→ 材料の解決（既存材料で足りない場合のみ。スカラー経路`compute_edge_axis_scores`は
引き続き手書き。配列経路`compute_edge_costs_bulk`は改善計画T280で`domain/material_catalog.py:
MaterialSpec.extractor`宣言駆動化済みのため、抽出方法がタグ判定・件数密度等の既知パターンに
収まる材料なら`material_catalog.py`へ抽出関数を1件足すだけで済み、`compute_edge_costs_bulk`
自体の変更は不要。既知パターンに収まらない場合や`AttributeRepository`側の事前集計が
無い場合は従来どおりファサード対称委譲から必要）→
`domain/axis_definitions.py: AXIS_DEFINITIONS`への定義データ追加（改善計画T221 Stage B/C。
既存テンプレート＋既存材料の組み合わせならこの1エントリでスカラー/配列両経路の評価・
区間インスペクタ・`evaluate_axis_difficulties`・既定重み（改善計画T316で
`route_preference.yaml`の手書きミラーを撤廃したため、この1エントリだけで自動反映される）
へ同時反映される）→ フロント`evaluationAxes.ts`のカタログ。エンジンファイルに軸固有の知識（SQL・タグ解釈）を
書き足さない。区間詳細表示（`RouteSegmentDetail.axis_difficulties`、改善計画T309で
axis_id→difficultyの汎用dictへ置換済み）も両エンジンの区間ビルダーからaxis_scores/
axis_difficultiesをそのまま渡すだけで自動反映され、軸ごとの手書き追記は不要
（フロント`routeStyleModes.ts`の色分けモードは改善計画T440で`supports_route_coloring`
軸から動的に生成する形へ一本化したため、新規軸を軸スタジオで公開し`supports_route_
coloring`をtrueにするだけでコード変更なしにモードが増える。固定で残るのは`difficulty`
[総合難易度、対応する軸を持たない唯一の例外]のみ）。
**この1本道はコスト計算
（ルーティング・研究モードの重みパネル）の配線経路であり、地図表示（レイヤーパネル・凡例）への
反映は別経路（下記「一次属性レジストリ・二次軸レジストリ」参照）** — 両者は現状レジストリ
登録`register_axis()`を挟んで独立しており、軸を追加する際は両方を行う必要がある
（改善計画T154、統合レビュー2026-08-19 overall F-2・consistency F-3。軸ID集合の
片側更新漏れは`test_registry_defaults.py`がAXIS_DEFINITIONSとの突き合わせで機械検知する）。

### 評価軸定義のDB化＋管理API（改善計画T221 Stage D）

`AXIS_DEFINITIONS`（上記1本道の到達点）はStage Dで、Pythonファイルの定数から
PostGISテーブル`axis_definitions`（+版数管理用`axis_registry_meta`、
`migrations/0014_axis_definitions.sql`）を実データソースとする形へ昇格した。
**改善計画T350で`domain/axis_definitions.py`のPython辞書リテラル自体も撤去し、
DBが軸全ての唯一の正本になった**（軸数は変遷している。現在値は`GET /api/axis-catalog`
またはDBそのものを一次情報とすること、下記参照）。同モジュールに残るのは型定義
（`AxisDefinition`等のPydanticモデル）と評価用の純粋関数（`evaluate_axis_scalar`等）
のみで、実データは一切持たない。

**軸の行データ（追加・削除・shape_params調整すべて）はaxis_admin API経由でのみ行う
（改善計画T361、T350から方針変更）**: T350時点では「新規追加・削除はmigration、
shape_params調整のみAPI」という使い分けだったが、T353がAPI直接操作で軸を変更した
結果、fresh bootstrap（まっさらなDBへ全migration適用）が再現する内容と実際のDB
（本番/dev）の内容が乖離する不整合が発生した（T360）。「軸定義の変更経路がmigrationと
APIの2つ存在する限り、両者の同期漏れは構造的に再発し続ける」という根本原因に対応し、
`backend/migrations/`は`axis_definitions`/`axis_registry_meta`の**テーブル構造（DDL）
のみ**を管理する運用へ変更した（0014〜0022の過去の行データ入りmigrationは、この
プロジェクトの標準運用どおり書き換えず、以降の新規migrationへ軸の行データを追加する
こともしない）。T348で導入した`backend/scripts/generate_axis_migration_sql.py`は
T350時点で既に撤去済み。

fresh bootstrap（CI・新規開発環境・disaster recovery）の実データは、
`backend/fixtures/axis_definitions_snapshot.json`（現在の実DBの内容を
`backend/scripts/dump_axis_definitions_snapshot.py`でダンプしたスナップショット）から
用意する。`backend/scripts/bootstrap_fresh_db.py`（新規環境用、`create_tables()`→
`apply_pending_migrations()`→スナップショット読み込みの一連を実行する）・
`backend/scripts/bootstrap_ci_db.py`（CI用）が、`app/infrastructure/
axis_definitions_snapshot.py: load_axis_definitions_snapshot`でテーブルを丸ごと
スナップショットの内容へ置き換える。この関数は**無条件に**テーブルを空にしてから
投入するため、fresh bootstrap専用ツールからのみ呼ぶ——通常のアプリ起動経路
（`main.py`のlifespan・`refresh_axis_definitions`）や、稼働中のDBへ繰り返し実行される
`app/batch/import_pbf.py`等からは呼ばない（誤って本番の生きた軸データを
スナップショットの内容で上書きする事故を防ぐため）。`refresh_axis_definitions`の
「テーブルが空なら`AxisDefinitionSyncError`で起動自体を失敗させる」というfail-fast方針
（T349/T350）はこの変更後も維持する——fresh bootstrapツールを踏まずにアプリを
起動しようとした場合、自動修復せず起動が落ちるのが正しい挙動という判断を引き続き
踏襲する。スナップショットの更新は手動運用（本番/devでAPI経由の軸変更を行った後、
`dump_axis_definitions_snapshot.py`を都度手動実行してリフレッシュしコミットする。
低頻度な操作のためデプロイパイプラインへの自動組み込みはしない）。

構造化JSON表現（`shape_params`）の手書き（軸スタジオのフォーム経由）に対しては、
`AxisShape`のPydanticバリデーションと下記のブートストラップ構造検証が引き続き効く。
`tests/test_migrate.py::test_bootstrap_from_empty_db_create_tables_then_migrate_succeeds`
は、まっさらなDBへ全migration適用→スナップショット読み込みまでの一連の流れについて
「軸数がスナップショットの件数と一致すること」「全軸の材料/軸参照が既知であること
（未知参照が無いこと）」という**構造検証のみ**を行う回帰テストとして機能する
（postgis統合テストのためDB接続が要る、`pytest -m "not postgis"`実行時はスキップ
される）。DB値が特定の数値であることを検証するテスト（例: `weights["gradient"] ==
0.15`）は意図的に持たない——可変であることを前提にDBへ置いているデータを固定検証
すると、正当なチューニングのたびに無意味な失敗を生むだけで実際のバグを検知しないため。

評価ホットパス（`evaluation.py`/`difficulty.py`等）は従来どおり`AXIS_DEFINITIONS`を
同期的なモジュールレベル辞書として読む——この既存の読み出し方法は一切変えていない。
`services/axis_registry_service.py: refresh_axis_definitions`が、(1)アプリ起動時
（`main.py`のlifespan）と(2)管理API書き込み直後の2箇所だけで、同じdictオブジェクトを
`.clear()`+`.update()`でin-place更新する「push型」の設計にしたため（再代入すると
`from ... import AXIS_DEFINITIONS`で束縛済みの参照先が更新されない）。**このpush型
更新が唯一のロード経路になったため、`AXIS_DEFINITIONS`は起動直後の一瞬（lifespan内で
`refresh_axis_definitions`が呼ばれるまで）は空のままである点に注意**（`main.py`の
lifespanが同期的にawaitするため、リクエストを受け付け始める時点では既に埋まっている）。

**DBを唯一の実行時ソースとするfail-fast設計（改善計画T349、T350で単純化）**:
DB未接続・テーブル未migration・0行（＝migration未適用）・未知の材料/軸参照
（T294〜T295）のいずれかを検出すると`AxisDefinitionSyncError`を送出し、`main.py`の
lifespanがこれを捕捉しないため**アプリの起動自体が失敗する**（fail-fast）。T349時点
では「Pythonリテラルへ安全側フォールバックする」という選択肢自体が存在したが（当初は
WARNING/ERRORログを出しコード内蔵の既定値のまま動作を続けていた。この設計は「検知が
起動ログの目視のみに依存し、次に同種の障害が起きても気づかれないまま放置される」という
構造的な弱点を持ち[T294→T295で2回、検知条件を1つ足す対応を繰り返したが解決しなかった]、
複雑度平衡性レビュー[2026-08-26、F-1・P0。結果ファイル`history/2026-08-26_complexity.md`
は保存されておらず未確認[T356]、詳細は改善計画T349本文参照]で指摘を受けてT349で
撤去した）、T350で
Pythonリテラル自体を撤去したことで「フォールバックしない」ではなく「フォールバック先が
物理的に存在しない」という、より単純で取り違えようのない構造になった。これに伴い、
`.github/workflows/deploy-backend.yml`へ`docker build`直後・旧コンテナ停止前に
migration適用ステップ（`scripts/apply_migrations.py`）を追加し、通常のデプロイ経路では
migration未適用のまま新コンテナが起動を試みてクラッシュループする事態を避けている
（`backend/Dockerfile`も`migrations/`・`scripts/`をイメージへ同梱するよう変更済み）。

管理API（`/api/admin/axis-definitions`、`api/routers/axis_admin.py`）は軸定義の
CRUDのみを提供する（GUI編集画面は改善計画T270で実装済み、`frontend/src/app/admin/`
「材料の排他帰属チェック・軸カタログ公開API」「Stage E実装」節参照）。書き込みでルート生成の
振る舞いを直接変えられるため、他のバックエンドAPI（認証機構が無い）と異なりHTTP Basic認証
（`require_admin_basic_auth`、環境変数`ADMIN_BASIC_AUTH_USERNAME`/`ADMIN_BASIC_AUTH_
PASSWORD`。以前は共有トークンheader[X-Admin-Token]だったが改善計画T272でBasic認証へ
差し替え済み、下記「軸の公開フローと統治ルール」節の次「管理画面の権限制御」節参照）に
よる認可を要求する。認可判定はこの1関数へ集約し差し替え可能にしている。
妥当性検証は型・範囲チェックのみ（極端な重み設定への意味的な歯止めは設けない、
2026-08-24ユーザー判断）。ただし「最後の1軸は削除できない」制約だけは例外的に持つ
（レジストリを空にできてしまうと削除後の`refresh_axis_definitions`が0行を検知し
`AxisDefinitionSyncError`を送出する[改善計画T349]ため、重みの妥当性とは別次元の
構造的な安全策として設ける）。

既存のAPIリクエストが参照するaxis_idを管理API経由で削除した場合の整合性チェックは
意図的に実装していない（改善計画T316: 上書き無しの既定値は常にAXIS_DEFINITIONS由来へ
一本化済みのため、この経路は上書きしているクライアントのみが対象）。ただし削除は
公開済み軸には及ばない
（下記「軸の公開フローと統治ルール」の不変制約により、削除できるのは常に下書き軸のみ）ため、
削除時点で一般ユーザーの保存設定がそのaxis_idを参照している状況自体が起こらない
（改善計画T302で確定、旧記述は「Stage EでGUI編集が実利用される段階で改めて検討」だったが
そのタイミングが実際に到来したため決着した）。

`export_openapi.py`が生成する`axis-catalog.json`（フロントのビルド時静的import）は
`_try_load_axis_definitions_from_db()`がDBから読み込んだ`AXIS_DEFINITIONS`を著述元に
生成する（正確には`axes[]`/`primary_attributes[]`は下記`registry.py`由来、
`preference_defaults`のみ`AXIS_DEFINITIONS`由来。T269実装メモ参照）。改善計画T350で
Python内蔵の既定値というフォールバック先が無くなったため、CIの`api-contract`ジョブ
（`.github/workflows/ci.yml`）にも`postgres`サービスコンテナを追加し、本番と同じ
ブートストラップ経路（`create_tables`→`apply_pending_migrations`、`backend/scripts/
bootstrap_ci_db.py`）でmigration適用後のDBから生成するよう変更した（以前はDB接続に
失敗してもコード内蔵の既定値へ黙ってフォールバックできていたが、そのフォールバック
自体が撤去対象だったため、生成そのものに実DBが必須になった）。

### shapeの2プリミティブ化（改善計画T396）

軸スタジオの設計精査（ユーザーとのセッション、2026-08-29）で、`AxisShape`の旧4種
（`breakpoint_linear`/`recipe_then_breakpoint_linear`/`categorical`/`flag_sum`）は
実質2つの独立した原型に還元できると判明し、以下へ再編した。

- **連続演算**（`BreakpointLinearShape`、kind不変）: 材料（または他軸のスコア）を
  `terms`で重み付き結合し、`breakpoints`の区分線形カーブ（両端クランプ）でスコア化する。
  `recipe_then_breakpoint_linear`（他軸参照を表す別名kind、実装は本shapeのエイリアス
  だった）は撤去した——`MaterialTerm.material`は元々材料id・軸idのどちらも区別なく
  指せる設計のため、別kindを持たせる理由が無かった。旧`FlagSumShape`（真偽値フラグの
  加点合計、`flags`+`cap`）も本shapeへ統合した——全termがboolean材料の場合として
  `terms`（`weight`が旧`points`）＋`breakpoints=[[0,0],[cap,cap]]`（恒等クランプ）で
  表現する。
- **離散演算**（`CategoricalShape`、変更なし）: 単一の離散値（bool/カテゴリ文字列）を
  `mapping`でテーブル引きしスコア化する。

「合成」（他軸のスコアを次の軸の入力として使う階層構造、改善計画T292）は独立した
プリミティブではなく、連続演算の結合ステップの性質——`terms`の各materialが材料id・
他軸のaxis_idのどちらも区別なく指せることから生じる。`topological_axis_order`
（依存順評価、上記「軸の階層」節参照）はこの整理でも変更していない。

**移行**: night軸（唯一の`flag_sum`利用軸）は`axis_definitions`テーブル・
`backend/fixtures/axis_definitions_snapshot.json`とも新形状へ移行済み（本番・dev
両方、行データはT361の運用どおりaxis_admin API相当の経路——本件は既存データの型
移行のためPydantic検証を経由できず、`shape_params`カラムを直接UPDATEする一時
スクリプトで実施し実行後に削除した）。`domain/axis_display.py: derive_ramp_inputs`
（地図ramp表示の自動導出）は、旧`FlagSumShape`という型で分岐していた閾値計算
（達成しうる合計値の部分和・隣接中間点）を、「`BreakpointLinearShape`で全termが
boolean材料か」という構造判定へ書き換えることで、night軸の地図表示を維持した
（材料が20件超だと部分和の組合せ爆発を避けるため自動導出対象外にする安全弁付き）。

**フロント（改善計画T397で3カードへ再設計、T396時点では暫定的に4カードのまま互換維持
していた）**: `AxisComposer.tsx`のUIを「なめらか評価」（旧「数値の大きさに応じて」＋旧
「複数の要素の有無を数えて」[flag_sum]を吸収）・「ぴったり評価」（旧「はい/いいえ、
または種類ごとに」）・「かけあわせ評価」（旧「他の軸を重みで足し合わせて」）の3枚へ
整理した。保存時の`kind`は常に`breakpoint_linear`または`categorical`へ正規化する
（表側の選択肢数と裏のprimitive数を一致させる必要は無いという判断）。編集で開いた
ときにどのカードを初期選択するかは、保存済み`kind`だけでは判別できないため、
`draftFromExisting`が`terms`の構造（全termが他軸参照か）から「かけあわせ評価」かどうかを
推定し直す（旧flag_sum検出用だった「全termがboolean材料かつbreakpointsが恒等クランプか」
の判定は、そのケースも「なめらか評価」へ統合されたことでT397で不要になり撤去した）。
「かけあわせ評価」は純粋な重み付き結合（nX + mY）に絞り、下ごしらえ・折れ点の編集UIを
出さない（保存時は常に`preprocess="identity"`・恒等クランプ`[[0,0],[100,100]]`）。
係数・スコアの入力は`SliderNumberField`（スライダー+数値入力、同じstateを共有）、
下ごしらえ（そのまま/絶対値）は`<select>`から2択のラジオボタンへ、折れ点は既存の
数値入力行に加えて`BreakpointCurveEditor`（ドラッグで調整できるSVG曲線、同じ
`breakpoints` stateを共有）を追加した。

### 軸の公開フローと統治ルール（改善計画T271）

一般ユーザーの保存設定（`RouteSettingsPanel`のプリセット・重み、`localStorage`永続化）は
`axis_id`キーで再現されるため、公開後の軸の破壊的変更・削除は他ユーザーの設定を黙って
壊す。`AxisDefinition.is_published: bool`（既定`False`＝下書き、`migrations/
0016_axis_definitions_is_published.sql`。既存7行は本番稼働中のためbackfillで`True`）が
公開状態を持ち、以下2点を構造的に強制する:

- **公開済み軸は編集不変**: `domain/axis_definitions.py: check_publish_immutability`が
  `AxisRegistryAdminService.update`/`delete`の冒頭で呼ばれ、`is_published=True`の軸への
  更新・削除要求は`AxisPublishedImmutableError`（`ValueError`のサブクラス）で拒否される
  （管理APIは自動的に409を返す）。改良したい場合は軸スタジオの「複製して新規作成」で
  新しい`axis_id`の下書きを作り、そちらを検証・公開する（元の公開済み軸はそのまま残る）。
  `api/routers/axis_admin.py: update_axis_definition`にこれまで欠けていた`ValueError`
  ハンドラも本タスクで追加した（従来は更新時の材料衝突[T268]が想定外の500になっていた
  抜け穴も合わせて塞いだ）。
- **公開済み軸を下書きへ戻すunpublish**（改善計画T302で追加。当初のT271は「unpublishは
  無い、複製して新規作成のみ」という一方向設計だったが、ユーザー要望を受けて追加した）:
  `AxisRegistryAdminService.unpublish()`・`POST /api/admin/axis-definitions/{axis_id}/
  unpublish`が、`is_published`のみをFalseへ反転する（他フィールドは一切変更しない、
  `update()`の一般的な緩和ではなく専用アクション）。下書きへ戻った軸は通常の`update()`
  経路で自由に再編集・再公開でき、削除も上記の不変制約により可能になる
  （「unpublish→delete」の2段階が正式な削除フロー）。フロント（`RouteSettingsPanel`）は
  `GET /api/axis-catalog`の返す公開軸集合の変化に合わせて、保存済み`routePreference`の
  キー集合を双方向に同期する（新しい軸のキーを補う・消えた軸のキーを削除する）。これが
  無いと、unpublish直後に旧設定を保持したブラウザで`RoutePreferenceWeights`のキー完全
  一致検証（`routers/routes.py`）が422になる。ただしこの同期は`RouteSettingsPanel`が
  マウントされたときにしか走らないため、モバイルで同パネル（「ルート詳細」タブ）を
  一度も開かずに生成ボタン（T250でヘッダーへ分離済み）を押す経路には残課題がある
  （改善計画T303、トリガー未到達）。
- **下書き軸は一般ユーザーに見えない**: `GET /api/axis-catalog`（T269、`RouteSettingsPanel`
  が読む）は`is_published=True`の軸のみを返す。下書きの一覧・編集は認可必須の
  `GET /api/admin/axis-definitions`（軸スタジオ）側でのみ行う。

軸スタジオ（`components/AxisStudio/AxisStudio.tsx`）は各軸に「公開済み/下書き」バッジを
表示し、公開済み軸の「編集」「削除」ボタンをdisabledにする（バックエンドの拒否に加えて
UI側でも先回りして防ぐ）。公開済み軸には「非公開に戻す」ボタン（改善計画T302）も表示され、
押すとバッジが「下書き」へ切り替わり「削除」ボタンが活性化する。「複製して新規作成」
ボタンは公開済み・下書きどちらの軸からも使え、`AxisComposer.tsx: draftFromDuplicate`が
既存定義の内容をコピーしつつ`axis_id`を新規に自動採番（改善計画T305、`generateAxisId()`）・
`is_published`を`false`に強制する。新規作成フォームには「公開する」チェックボックス
（既定OFF）があり、送信時のpayloadへ`is_published`として含まれる。

### 管理画面の権限制御（改善計画T272）

Phase 3のもう1件。以前は`/admin`ページ本体（軸スタジオ・研究モード・開発者ツールを
まとめた独立URL、T270）自体には認可が一切無く、誰でも到達できた（軸CRUD APIだけが
共有トークンで保護されていた）。ユーザー方針（2026-08-24、着手時に決定：「将来的には
アカウント制としたいが、現状は動作確認・研究用のためBasic認証として後から拡張する」）
に基づき、HTTP Basic認証で以下2箇所を独立に保護する:

1. **`/admin`ページ本体**: `frontend/src/proxy.ts`（Next.js 16でファイル名が
   `middleware.ts`から`proxy.ts`へ改称された、`frontend/AGENTS.md`参照）が
   `matcher: ["/admin", "/admin/:path*"]`でルーティング境界を敷く。環境変数
   `ADMIN_BASIC_AUTH_USERNAME`/`ADMIN_BASIC_AUTH_PASSWORD`（frontend側）と照合し、
   未設定または不一致ならブラウザの標準Basic認証ダイアログを起動させる
   `WWW-Authenticate: Basic`ヘッダ付き401を返す。研究モード・開発者ツールも`/admin`配下
   のため、このゲート1つで一般ユーザーの導線から到達不可能になる。
2. **軸スタジオの管理API**（`GET/POST/PUT/DELETE /api/admin/axis-definitions`、
   `POST /api/admin/axis-definitions/{axis_id}/unpublish`）:
   backend側`require_admin_basic_auth`（環境変数`ADMIN_BASIC_AUTH_USERNAME`/
   `ADMIN_BASIC_AUTH_PASSWORD`、backend側）が`secrets.compare_digest`でタイミング
   攻撃を避けつつ検証する。

**2箇所を1回のブラウザ認証で満たす仕組み（改善計画T305で改訂）**: 当初（T272時点）は
`axisAdminApi.ts`の管理API呼び出しが`NEXT_PUBLIC_API_URL`（backendの別オリジン）へ直接
飛んでおり、ブラウザが1.のBasic認証資格情報を自動転送しない（同一オリジンにのみ
キャッシュされる仕様）ため、軸スタジオUI自体に専用の資格情報入力フォーム
（ユーザー名・パスワードの2フィールド、`localStorage`保存）を持っていた。しかし
「`/admin`へは既に認証済みなのに、画面内でもう一度ログインを求められる」という実機
フィードバックを受け、二重ログインUIを撤去した。

代わりに、軸CRUD APIは同一オリジンのNext.js route handler
（`frontend/src/app/admin/api/axis-definitions/`配下、`lib/adminApiProxy.ts`）を経由する。
このパスは1.のproxy.ts matcher（`/admin/:path*`）に含まれるため、ブラウザは`/admin`
読込時に一度入力したBasic認証資格情報を、同一オリジン・同一realmへの後続リクエスト
（`fetch`の既定`credentials`モード）へブラウザ自身の認証キャッシュから自動付与する。
route handler側は自分のサーバー環境（frontend側の`ADMIN_BASIC_AUTH_USERNAME`/
`PASSWORD`、1.と同じ値）から2.のbackend宛`Authorization: Basic`ヘッダを組み立てて
転送するため、backend向けの資格情報がブラウザへ一切露出しない。運用上両側のenvへ
同じ値を設定する既存の方針（バックエンド側の値が正、フロント側`proxy.ts`の値が
食い違うとページ本体は入れるがAPI呼び出しだけ500/401になる——設定時は両者を必ず
揃えること）はT272から変わらない。

研究モードの表示切替（`lib/researchMode.ts`、実験スロット記録・比較タブ等の表示ON/OFFを
選ぶだけのUI用トグル）は元々認可の意味を持たない簡易フラグだったが、`/admin`ページ
自体が認証済みユーザーしか到達できなくなったため、意味の重複が解消された（このトグル
自体はT272で変更していない、単なる表示設定として残る。改善計画T519でトグル本体は
一般公開ページのヘッダーメニューへ移設済み、詳細はdocs/modules/frontend/
developer-research-tools.md参照）。

### 材料の排他帰属チェック（改善計画T268）

`registry.py: register_axis`が持つ「1つの材料は原則1つの軸だけが使う」排他制約
（`AxisInputConflictError`）は表示用レジストリ（下記）にしか無く、実際にルーティング
計算を駆動する`AXIS_DEFINITIONS`側には存在しなかった。`domain/axis_definitions.py:
check_material_exclusivity`が同じ原則を計算系へ移植し、`AxisRegistryAdminService.create`/
`update`（管理API書き込み経路）の冒頭で呼ぶ。既存軸が使用中の材料を新軸が黙って再利用し
評価の二重計上が混入する事故を構造的に防ぐ（`AxisMaterialConflictError`、`ValueError`の
サブクラスのため管理APIは自動的に409を返す）。現行8軸の材料には`registry.py`の
`shared=True`相当（複数軸が参照してよい共通コンテキスト）が存在しないため`shared`
フラグは持たせていない。

### 軸カタログ公開API・表示名のDB化（改善計画T269）

`AxisDefinition`（`domain/axis_definitions.py`）へ`label: str`（必須）・
`description: str`・`category`（`"観測"|"推定"|"動的"`）を追加した
（`migrations/0015_axis_definitions_label.sql`、`0014`が本番適用済みのため追加カラム＋
backfillという安全な別migrationとした）。これにより、軸スタジオ（T270）がGUIから
作った新規軸も表示名を持てる——`registry.py`はDBを持たずGUI作成軸を表現できないため、
DB化済みの`AXIS_DEFINITIONS`側を表示名の単一ソースにした。

新規公開エンドポイント`GET /api/axis-catalog`（`api/routers/axis_catalog.py`、認可不要、
読み取り専用）が、プロセス内キャッシュ`AXIS_DEFINITIONS`（push型更新済み、上記Stage D
設計）をそのまま`{axis_id, label, description, category, default_weight}[]`として返す。
フロントは`hooks/useAxisCatalog.ts`がマウント時に1回取得し、取得完了まで・失敗時は
既存8軸の静的フォールバック（`axis-catalog.json`の`preference_defaults`＋
`evaluationAxes.ts`の手書きラベル）を返す。一般向けルート設定画面
（`components/RouteSettingsPanel/`）がこのhookを使う。研究モードの`WeightPanel`は
本タスクの時点では旧`axis-catalog.json`静的読み込みのまま（T270でWeightPanel自体を
置き換える際に統合する想定）。

### 材料カタログの正式レジストリ化（改善計画T277〜T340・T290）

> 経緯・教訓（display_only方針転換の紆余曲折、categorical dtype対応のGUI/backend乖離期間等）は
> [decisions/material-catalog-registry.md](decisions/material-catalog-registry.md)参照。

`domain/material_catalog.py: MaterialSpec`/`MATERIAL_CATALOG`が「材料」（軸が参照する
`MaterialTerm.material`等の文字列id）の単一の情報源。各材料は`material_id`・`label`・
`dtype`（"numeric"|"boolean"|"categorical"）に加え、内部専用の`tile_property`
（MVTタイルへの焼き込み済みプロパティ名、地図レイヤーのramp自動生成に使う）・
`tile_property_inverted`・`display_only`（軸スタジオの選択肢から除外、地図表示には影響しない。
現状`designation`のみ該当）を持つ。全25材料（うち`categorical`は`highway`・`surface`・
`designation`・`smoothness`・`tracktype`の5件。`bicycle_infra`は改善計画T347で正規化フラグ
材料[`highway_is_cycleway`・`cycleway_has_track`・`cycleway_has_lane`・`cycleway_has_shared`]へ
分解され材料としては撤去済み）。**材料自体をGUIから追加・編集・削除する
経路は無い**（ユーザー方針、増減は引き続きコード変更＋デプロイのみ）。

公開エンドポイント`GET /api/material-catalog`（認可不要、`material_id`/`label`/`dtype`のみ）を
`hooks/useMaterialCatalog.ts`がマウント時取得し（失敗時は`lib/axisMaterialsCatalog.ts`の
静的9件へフォールバック）、`AxisComposer.tsx`の材料選択ドロップダウンを構成する。管理API
（`axis_admin.py: AxisDefinitionPayload`）の`_check_materials_are_known`が、shapeが参照する
材料idの実在を422で検証する。

抽出ロジックは汎用パターン（単一タグ生値取得・タグ値一致判定・数値パース・件数密度計算）を
パラメータ化したextractorファクトリ関数（`raw_way_tag_extractor`/`tag_equals_extractor`/
`way_tag_parser_extractor`/`count_per_km_extractor`）で宣言的に組み立てる（`MaterialSpec`宣言の
場で`extractor=tag_equals_extractor("bridge", "yes")`のように直接呼ぶ）。優先順位付き分類等の
複雑な組み合わせロジック（`bicycle_infra`）のみ専用関数を持つ。

`GET /api/material-catalog/{material_id}/values`（認可不要）が、DBに実際に取り込まれている値の
一覧（`RawOsmRepository.get_distinct_material_values`、DB未接続時は空リストへグレースフル
デグレード）を返し、`AxisComposer.tsx`の値入力欄（`hooks/useMaterialValues.ts`）が自由テキスト
入力の隣に「値の候補」セレクトとして添える（値一覧が空の材料は従来どおり自由テキストのみ）。
日本語ラベルはbackend側では持たず、frontend側`lib/materialValueLabels.ts`が単一の情報源
（highway/surfaceは`roadFilterAxes.ts`のHIGHWAY_GROUPS/SURFACE_GROUPSから導出、smoothnessは
OSM標準8値を新規定義、未知の値・材料idはタグ値そのまま表示するフォールバック）。

### 地図表示ルール（kind=ramp）の自動導出（改善計画T278）

新規`domain/axis_display.py: derive_ramp_inputs(definition) -> RampInputs | None`が、
`AXIS_DEFINITIONS`の軸の材料が全て`MATERIAL_CATALOG`で`tile_property`保持済み（かつ
`tile_property_needs_runtime_scale=False`）であれば、地図ramp表示の`tile_inputs`/
`thresholds`を自動導出する。**安全に自動導出できるケースに限定する**設計:

- `CategoricalShape`（真偽値材料1件）: 2値の中間点を閾値とする2段階ramp。
- `FlagSumShape`（真偽値フラグN件）: 達成しうる合計値（部分和の全組合せ、cap適用後）の
  隣接中間点を閾値とする（例: night軸の2フラグ×50点→部分和{0,50,100}→閾値[25,75]）。
- `BreakpointLinearShape`で単一材料・weight=1.0・preprocess="identity"の場合のみ:
  既存breakpointsのx値（先頭除く）をそのまま閾値に流用。

それ以外（複数材料の重み付き結合・abs前処理・他の軸を参照する材料・実行時スケール変換が
必要な材料を含む軸）は`None`を返し自動導出対象外のまま（地図に出ない、既存軸を壊さない
安全側の判断）。現行8軸では`surface_q`（材料`surface_good`、以前はkind="none"に手書き
固定していたが「既存の道路情報レイヤーと重複するため出したくない」という理由は
UI側の表示/非表示切替で運用する方針へ変更）・`night`（材料`no_lit`・`has_tunnel`、
以前はkind="bespoke"でフロントにexpressionが無く実質レイヤー無し）の2軸が対象になり、
`registry_defaults.py`の`display`がこの自動導出値へ置き換わった。`gradient`（材料が
タイル非依存）・`stop_density`（複数材料の重み付き結合、既存thresholds`[1,2,4]`は
統計的経験則で単純な折れ点流用では再現不可）・`car_stress`（改善計画T292以降、他の5内部軸
[`car_stress_highway_base`等、`MaterialTerm.material`として他axis_idを参照]を合成する
`BreakpointLinearShape`のため、参照先も材料であることを前提とする`derive_ramp_inputs`では
解決できない）・`accident`（材料`accident_count_per_km_year`が収録年数[実行時にDBから
取得、`accident_import_runs`]で正規化済みだがタイル生値`accident_per_km`は年正規化前で
静的な変換係数を持てない、`MaterialSpec.tile_property_needs_runtime_scale=True`で
明示的に自動導出対象外とマークしている）は自動導出の対象外のまま手書きの`display`を
維持する（`car_stress`・`stop_density`・`accident`はいずれも`kind="ramp"`自体は手書きで
維持しており、地図に出ない・レイヤー無しという意味の対象外ではない）。

`export_openapi.py`のaxis-catalog.json生成は、`registry.all_axes()`（手書き登録済みの
既存軸）に加えて「`AXIS_DEFINITIONS`にあるが`registry.py`未登録の軸」も走査し、
`derive_ramp_inputs()`がramp化可能と判定した場合のみ`inputs=[]`（一次属性の対応は
registry.py側の別語彙のため空のまま）・自動生成`display`で追加する。これにより将来
軸スタジオが作る新規軸のうち、真偽値材料またはシンプルな単一数値材料のものは
再デプロイ後に自動で地図へ現れる（ただしDB上の軸データがビルド時静的生成物である
axis-catalog.jsonへ反映されるのは再デプロイ後、という既存の制約はそのまま残る）。

フロント`components/Map/axisLayers.ts`の`AxisTileInput`/`buildAxisRampValueExpression`は
真偽値材料に対応する`boolean`/`invert`/`trueValue`/`falseValue`を追加した。MVTの真偽値
プロパティは`["==",["get",property],true]`のような比較でしか読めず、既存の数値
`Σproperty×weight`結合が成立しないため、`boolean=true`の入力は
`["case", 真偽比較, trueValue, falseValue]`で組み立てる（既存の数値材料分岐とは独立、
後方互換）。`components/Map/secondaryAxes.ts`の`SECONDARY_AXIS_LAYER_IDS`は、
`display.kind==="ramp"`の軸を`axisMapLayerId(axis_id)`で自動算出するよう一般化した
——ramp軸が増えるたびに個別追記していた手動同期ペアを1つ解消した。`MapView.tsx`・
`mapLayers.ts`・`staticAttributeLayers.ts`は`RAMP_AXES`を汎用的に走査する既存実装のままで
変更不要だった（`RAMP_AXES`の要素数が2→4に増えるだけで、レイヤー生成・凡例・絞り込みの
ロジックはそのまま新しい2軸を拾う）。改善計画T292でcar_stressも`kind="bespoke"`から
`kind="ramp"`へ移行し、`carStressExpression.ts`等の手書きフロントコードを廃止して同じ
`RAMP_AXES`汎用パスへ合流した（下記「停止密度・車ストレス...」節参照）。

### 推定軸の地図表示・実行時配信化とmaterials統一（改善計画T308）

T278（上記）の自動導出は実装されていたが、導出結果の配信経路がビルド時静的生成物
`axis-catalog.json`のみだった（`export_openapi.py`実行→コミット→デプロイを経て初めて
反映）。加えてその生成元`registry.py`の`register_axis()`登録は既存7軸のみのハードコードで、
軸スタジオ（GUI）で新規作成・公開した軸を走査する経路が無く、GUI軸には地図表示が
一切届かなかった（配信経路のギャップ、T278の導出ロジック自体とは別問題）。T308でこれを
解消した:

- **`GET /api/axis-catalog`への`display`フィールド追加**: `axis_catalog.py`が
  `axis_display_for(definition)`（`axis_display.py`、`AXIS_DEFINITIONS`/`MATERIAL_CATALOG`
  のみを見る純関数、DB/IO無し）を全公開軸へ適用し、レスポンスへ`AxisDisplaySpec`
  （`kind`/`tile_inputs`/`thresholds`/`unit`等）を含める。`STOP_DENSITY_DISPLAY`/
  `ACCIDENT_DISPLAY`/`CAR_STRESS_DISPLAY`（自動導出対象外の手書きdisplay）は
  `registry_defaults.py`から`axis_display.py`へ移設し単一ソース化した。
- **フロントの実行時フェッチ化**: `RAMP_AXES`/`AXIS_LABELS`（`axisLayers.ts`）・
  `MAP_LAYERS`/`ROAD_SURFACE_SHARED_LAYER_IDS`（`mapLayers.ts`）・`SECONDARY_AXES`
  （`secondaryAxes.ts`）・`STATIC_FILTER_AXES`（`staticAttributeLayers.ts`）を、
  それぞれ`buildX(rampAxes)`形の純関数＋静的フォールバック定数（旧`axis-catalog.json`
  ベースの値をそのまま計算した後方互換値）へ変換した。`useAxisCatalog.ts`が
  マウント時の`GET /api/axis-catalog`取得結果からこれらを`useMemo`で算出し、
  取得完了/失敗時は静的フォールバックを返す（`useMaterialCatalog.ts`と同型のパターン、
  T269の踏襲）。`page.tsx`/`MapView.tsx`/`MapLayersPanel.tsx`/`MapOverlayControls.tsx`は
  これらをpropとして受け取るよう変更（`MapView.tsx`はマップ初期化useEffectが一度しか
  走らない制約のため、`redrawPropsRef`/`interactiveLayerIdsRef`という「refで最新値を
  参照するクロージャ」パターンで対応）。これにより、軸スタジオで新規公開した軸が
  **再デプロイなしに**地図・凡例・チップへ現れるようになった（旧来の「axis-catalog.json
  へ反映されるのは再デプロイ後」という制約はライブ取得側では解消。ビルド時静的
  生成物自体は取得失敗時フォールバックとして引き続き生成・コミットする）。
- **改善計画T321（デッドコード監査）**: 上記の`MAP_LAYERS`/`ROAD_SURFACE_SHARED_LAYER_IDS`
  （`mapLayers.ts`）・`STATIC_FILTER_AXES`（`staticAttributeLayers.ts`）・
  `STATIC_OVERLAY_LAYERS`/`LAYER_DATA_SOURCES`（`MapView.tsx`）は、`build*(RAMP_AXES)`を
  静的引数で事前計算してexportしたものだったが、上記の実行時フェッチ化で本体コードの
  消費者が全て`build*(catalog.rampAxes)`直呼びへ移行済みで、exportされた定数側は
  テストからしか参照されなくなっていた。定数自体を削除し、テストは`build*(RAMP_AXES)`を
  明示的に呼ぶ形＋軸スタジオのGUI作成軸を含む拡張カタログでの反映確認テストへ書き換えた
  （`build*()`関数自体・`RAMP_AXES`フォールバック機構はそのまま存続）。
- **materials統一（primary_attribute_id/primary_attribute_ids）**: 上記実装中に
  「軸スタジオ作成軸には材料の共起ケーシング・材料一覧ノートUIが効かない」という
  別ギャップが判明した。`primaryAttributes.ts`の`axisMaterials()`/
  `axisMaterialLayerIds(axisId)`が、静的`axis-catalog.json`専用の`inputs`
  フィールド（各軸の生一次属性id配列）だけを情報源にしていたため。
  `MaterialSpec`（`material_catalog.py`）へ`primary_attribute_id: str | None`
  （material_id→attr_idの対応、registry.pyの一次属性語彙への写像）を追加し、
  `AxisCatalogEntry`へ`primary_attribute_ids: list[str]`を追加。バックエンドの
  `_primary_attribute_ids_for(definition)`（`axis_catalog.py`）は`car_stress`のような
  「他axis_idを`MaterialTerm.material`として参照する内部軸階層」（T292）を`visited`
  集合で再帰的に解決する。フロントは`axisMaterials`/`axisMaterialLayerIds`を廃し、
  ライブ/フォールバックいずれの`primary_attribute_ids`も直接渡せる純関数
  `primaryAttributeIdsToLayerIds(attrIds: readonly string[])`へ置き換えた。
- 上記に伴い、既存軸だけを特別扱いしていた静的定義（`AXES_WITH_INPUTS`・
  `CatalogAxisInputs`等）は死んだコードとして削除した。動的ramp（時刻依存の合成表示、
  例: 風＋路面の推進力軸を時間スライダーに連動させる表現）・向き依存材料の地図表現は
  引き続きスコープ外（T278の`tile_property_direction_dependent`フラグにより該当軸は
  安全側で`kind="none"`のまま）。

### 地図チップ表示要素の軸スタジオ登録化（改善計画T310）

T308完了時点でも、地図チップのアイコン・略称・地図の見え方パネル向け説明文・代役案内・
ramp閾値の手書き上書きの5点は、既存6〜7軸限定の軸id→値のハードコード辞書
（フロント`SECONDARY_AXIS_ICONS`/`RAMP_AXIS_PANEL_HINTS`/`SECONDARY_AXIS_CHIP_LABELS`/
`SECONDARY_AXIS_PROXY_HINTS`、backend`axis_display.py`の`STOP_DENSITY_DISPLAY`等）として
残っていた（汎用フォールバックがあり機能自体は壊れないため、T308の完了条件からは意図的に
除外していた）。T310でこれらを全廃し、軸自身のデータ（`AxisDefinition`のフィールド、
軸スタジオ経由でDBへ登録可能）へ移設した（「代役案内」`proxy_hint`はT318で
`show_map_icon`という真偽値ON/OFFへ置き換わり撤去済み、詳細は本節末尾参照）:

- **`AxisDefinition`（`axis_definitions.py`）へ`icon_id`/`chip_label`/`panel_hint`
  （いずれも`str | None`）・`display_override`（`registry.py: AxisDisplaySpec
  | None`、地図ramp表示のtile_inputs/thresholds/unit/noteをまとめて上書きする既存の型を
  再利用）を追加した。既存6軸（gradient/surface_q/night/stop_density/car_stress/
  accident）はこれらを自軸のエントリへ直接記述する（`label`/`description`と同じ、
  軸自身の宣言データとして単一ソース化）。`car_stress`の`display_override`は内部軸5つの
  カテゴリカルmapping/breakpointsを参照するため、`AXIS_DEFINITIONS`辞書リテラルの
  構築中に自分自身を参照できない制約を避けて、共有定数（`_CAR_STRESS_HIGHWAY_BASE_
  MAPPING`等）をモジュール先頭で先出しし、内部軸の評価shape・car_stressのdisplay_
  overrideの両方から同じ定数を参照する形で単一ソースを保った。
- **`axis_display_for()`（`axis_display.py`）は完全に軸id非依存になった**: 優先順位
  ①`definition.display_override`（設定されていれば）②`derive_ramp_inputs()`の自動導出
  ③`kind="none"`、という3行の純粋関数のみが残り、軸idを分岐条件に持つコードは無い。
  `registry_defaults.py`（ビルド時静的axis-catalog.json生成用の別レジストリ、T137）も
  `AXIS_DEFINITIONS[axis_id].display_override`を参照する形へ揃えた。
- **`GET /api/axis-catalog`**（`axis_catalog.py: AxisCatalogEntry`）へ`icon_id`/
  `chip_label`/`panel_hint`を追加（`display_override`は`axis_display_for()`
  の出力[`display`フィールド]に統合済みのため別フィールド化しない）。
- **フロント**: `RampAxis`（`axisLayers.ts`）・`SecondaryAxisSummary`（`secondaryAxes.ts`）
  へ`iconId`/`panelHint`/`chipLabel`を追加し、旧ハードコード辞書は全廃した。
  アイコンは新設の`axisIconPalette.tsx`（固定パレット、`icon_id`→アイコンコンポーネント
  のフラットな辞書）から`axisIconFor(iconId)`で引く——未知/未設定は汎用`AxisRampIcon`へ
  安全側フォールバックする。
- **アイコン登録方式（ユーザー判断、2026-08-25）**: GUIから任意のSVGを登録させる方式
  （スタイル一貫性・XSSサニタイズのコストが高い）、ラベル頭文字のモノグラム自動生成
  （既存の手描きアイコンが持つ「形だけで意味が伝わる」性質を失う）と比較検討した結果、
  あらかじめ用意した固定パレットから`icon_id`を選ぶ方式を採用した。既存6軸の意匠に加え
  新規軸向けのスペア6種（wind-flow/thermometer/shield/target/clock/layers）を含む計12種
  を用意（軸スタジオの`AxisComposer.tsx`がドロップダウンで選択・プレビュー表示する）。
  新しいアイコン形状の追加は引き続き`axisIconPalette.tsx`への1件追加＋コード変更を要する
  （軸スタジオ側はicon_idを選ぶだけで再デプロイ不要）。
- **既存軸データの本番DB backfill**（ユーザー指示、2026-08-25）: 上記5フィールドの
  DBカラム追加（`migrations/0019_axis_definitions_display_fields.sql`）に続けて、
  既存6軸の値を`AXIS_DEFINITIONS`から`model_dump(mode="json")`で機械的に生成した
  `UPDATE`文でbackfillする。他のmigration（0014〜0018）と同じく、未適用の環境では
  Pythonフォールバック（`AXIS_DEFINITIONS`の内蔵既定値）のまま安全に動作する。
- **chip_labelの4文字制約**（ユーザー指摘、2026-08-25）: 地図チップは4文字以下を前提と
  した固定サイズのタイル（`MapOverlayControls.module.css`）のため、`AxisDefinitionPayload`
  （`axis_admin.py`）へ`field_validator`を追加し、5文字以上のchip_labelを422で拒否する
  （フロントの`AxisComposer.tsx`も`maxLength={4}`で入力段階から防ぐ）。chip_label未設定
  時のフォールバックは`label`（正式名）だが、`label`が4文字を超える軸（例:「車の圧迫感」
  5文字）は必ずchip_labelを設定する運用とする。
- **スコープ外として明記**: `display_override`はTileInputSpecの構造が複雑なため
  `AxisComposer.tsx`（GUIフォーム）に編集UIを持たず、管理API直接編集のみ対応
  （データ層は軸自身のフィールドとして特別扱いを解消済みだが、GUIからの閾値調整は
  引き続き軸スタジオの範囲外）。ルート詳細のセグメント別内訳（`RouteSegmentDetail`の
  既存7軸固定フィールド）は別タスク（T309）として切り出し、後日
  `axis_difficulties`汎用dictへ置換して解消済み（下記7章・6章参照）。

#### `proxy_hint`撤去と`show_map_icon`の追加（改善計画T318、2026-08-25）

ユーザー判断（「軸スタジオで、地図マップ上にアイコン表示するかどうかON/OFFできるように
して。代役案内文(proxy_hint)は不要になるので消して」）を受け、`proxy_hint`（専用地図
レイヤーを持たない軸向けの代役案内文）を全廃し、`show_map_icon: bool`（既定`true`、
`migrations/0020_axis_definitions_show_map_icon.sql`でカラム追加と同時にDROP）へ
置き換えた。

- 判定・除外は1箇所に集約: `secondaryAxes.ts: secondaryAxesFromCatalogAxes()`の
  フィルタへ`axis.show_map_icon !== false`を足すだけで、`show_map_icon=false`の軸は
  地図上チップ（`MapOverlayControls.tsx`）・地図の見え方パネル（`MapLayersPanel.tsx`）
  の両方から丸ごと除外される。専用レイヤーの有無（`display.kind`）に関わらず一律に効く
  ため、kind別の分岐を新設する必要が無い。
- `show_map_icon=true`のまま専用レイヤーを持たない軸（例: gradient）は、以前は
  無効化タイルのツールチップ・展開パネルに`proxy_hint`の文言を出していたが、その表示は
  単純に撤去した（代替の説明文は用意しない——存在理由が自明でなくなった場合は
  `show_map_icon=false`にして表示自体を止める、というのが新しい設計判断）。
  `MapLayersPanel.tsx: renderProxyAxisSection()`も同様に見出し（h3）のみへ簡略化した。

#### `time_scope`/`supports_route_coloring`の追加（改善計画T352、2026-08-28）

`road_graph_engine.py`/`openrouteservice_engine.py`のT173ロジック（市民薄明の外なら
`night`軸の重みそのまま、日中なら0倍）とfrontend `routeStyleModes.ts`の`RouteStyleModeId`
（`"wind"`固定）が、それぞれ`"night"`/`"wind"`というaxis_idを直接ハードコード分岐して
いた。これを`AxisDefinition`の2つの宣言的フィールドへ汎用化した
（`migrations/0023_axis_definitions_time_scope_route_coloring.sql`でカラム追加、
既存軸はnight/windのみ明示的にbackfill）。

- **`time_scope: "always" | "night_only"`（既定`"always"`）**: この軸の重みが常に有効か、
  特定の時間帯でのみ有効かの宣言。`domain/axis_definitions.py: time_scoped_weights()`が
  `AXIS_DEFINITIONS`を走査し、`time_scope`が`"always"`以外かつ現在の`active_scopes`に
  含まれない軸の重みを0にする。`RoutePreference.with_time_scope()`（`evaluation.py`）が
  これをラップし、road_graph_engine.pyの2箇所（探索コスト・区間表示）は`night_active`を
  `active_scopes`へ変換して渡すだけになった。openrouteservice_engine.pyも同じ関数を
  区間ごとに呼ぶ形へ置き換えた。将来別の時間帯依存軸（例: 通勤ラッシュ限定）を追加する
  場合も、このフィールドへ新しい値を1つ増やすだけでよく、エンジン側のコード変更は不要。
- **`supports_route_coloring: bool`（既定`false`）**: この軸のdifficulty（0-100、または
  改善計画T440で追加した符号付き経路）を、ルート地図の色分けモード（`routeStyleModes.ts`）
  の選択肢として使えるかの宣言。`GET /api/axis-catalog`
  （`AxisCatalogEntry.supports_route_coloring`）経由でフロントへ渡り、
  `routeStyleModesFromCatalogAxes()`が該当軸から色分けモードを動的に組み立てる
  （`useAxisCatalog`の`routeStyleModes`フィールド、フェッチ完了までは静的axis-catalog.json
  由来のフォールバック）。**T440（2026-08-30）でgradient/surface_qも
  `supports_route_coloring=true`へ変更した**——当初`gradient`は「向き（登り/下り）を
  区別するため符号付きの生材料`gradient_percent`を直接読む必要があり、単純な
  `axis_difficulties[axis_id]`（abs差難易度）を3段階で塗るという本フラグの汎用機構では
  表現できない」という理由でこの機構の対象外として固定エントリのまま据え置かれていたが、
  この非対称自体がaxis_idのハードコード分岐（`if (axis.axis_id === "gradient")`）を
  招いていた。現在は`routeColorableModeFromAxis`が軸データ（`shape.kind===
  "breakpoint_linear" && shape.preprocess==="abs"`）を見て符号付き経路へ自動的に
  振り分けるため、gradientも`supports_route_coloring`経由の同じ動的機構に完全に乗る。
  `road`という名前のモードも無くなり、`surface_q`（`road_surface_good`と同一材料由来）が
  同じ機構で現れる。固定のまま残るのは`difficulty`（全軸の重み付き合成コスト、単一軸に
  紐づかないため軸スタジオと同期する対象にならない）のみ
  （`RouteStyleModeId`型は`"difficulty" | (string & {})`という「固定1種＋任意の軸id」の
  形になった）。
- **削除禁止ガードの縮小**: `services/axis_registry_service.py: _CODE_COUPLED_AXIS_IDS`
  から`night`/`wind`を除いた（`car_stress`/`gradient`はそれぞれ別の理由で対象外のまま
  残る）。上記の汎用化により、これらのaxis_idを削除してもハードコード参照によるcrashが
  起きなくなったため。
- **軸スタジオの編集UI**: `display_override`と同様、現時点で編集UIを持たない
  （`AxisComposer.tsx`は既存値をpayloadへ素通しするのみ、管理API直接編集のみ対応）。

### `display_override`廃止（改善計画T404、2026-08-30）

T310時点の`axis_display_for()`優先順位（①`display_override` ②`derive_ramp_inputs()`の
自動導出 ③`kind="none"`）・「`car_stress`/`stop_density`/`accident`は自動導出対象外の
まま手書き`display_override`を維持する」という上記の記述はT404で刷新した。

- **`derive_ramp_inputs()`の拡張**（`domain/axis_display.py`）: 2点の制約を緩和した。
  - **軸参照の再帰解決**: `MaterialTerm.material`が材料idではなく別の軸id（`car_stress`が
    参照する5つの内部軸のような階層構造、改善計画T292）を指す場合、
    `_resolve_referenced_axis_tile_input()`が参照先を再帰的に解決する。安全に変換できる
    のは(a) 参照先が`CategoricalShape`（値をそのまま返す、追加変換なし）、(b) 参照先が
    単一term・weight=1.0・preprocess="identity"の`BreakpointLinearShape`
    （`TileInputSpec.breakpoints`の自己変換材料としてそのまま表現できる）の2パターンのみ
    （それ以外は安全側でNone、`visited`集合で循環参照からも保護）。これにより`car_stress`
    （highway/maxspeed_kmh/lanes_count/designation/motor_vehicle_noの5材料へ展開）が
    手書き`display_override`無しで自動導出できるようになった。
  - **実行時スケール変換の定数化**: `tile_property_needs_runtime_scale=True`な材料
    （`accident_count_per_km_year`）も自動導出の対象に含める。タイル生値→材料スケールの
    静的な変換係数は持てないため、`TileInputSpec.needs_runtime_scale`で印を付けるに
    とどめ、実際のスケール係数（収録年数の逆数）は`GET /api/axis-catalog`が
    `material_runtime_scales`（tile property名→係数、リクエスト毎に`RegionService.
    get_accident_years_covered()`で解決）として別途返し、フロントの
    `axisLayers.ts: rampAxesFromCatalogAxes()`が構築時に一度だけ`weight`へ掛け合わせて
    解決する（未解決時はweight=0の安全側デグレード）。これにより`accident`も自動導出
    できるようになった。
  - `is_designated`材料（`material_catalog.py`）へ`tile_property="designation"`・新設の
    `tile_property_categorical_true_values`（dtype="boolean"だがタイル側は複数値の
    文字列プロパティで表現される材料向け）を追加し、`car_stress_designation_adjustment`
    内部軸（従来タイル非依存だった）もタイル駆動で自動導出できるようにした。
- **色分けしきい値の粒度問題は別フィールドへ分離**: `derive_ramp_inputs()`の`thresholds`は
  `AxisDefinition.shape.breakpoints`のX軸値をそのまま流用するため、複数材料の組み合わせ
  （car_stress）や単純な線形正規化（stop_density/accident）では粗い色分けしか作れない
  （車の圧迫感2段階・停止密度/事故密度2段階）。これは`tile_inputs`の自動導出能力の問題
  ではなく「色分け段階の刻み方の好み」の問題のため、新設した`AxisDefinition.
  display_thresholds_override: list[float] | None`（`axis_definitions`テーブルへ
  `migrations/0025_axis_definitions_display_thresholds_override.sql`でカラム追加）へ
  切り出した。T404時点の`axis_display_for()`の優先順位は①`derive_ramp_inputs()`成功＋
  `display_thresholds_override`設定→自動導出tile_inputsとこのしきい値を組み合わせる、
  ②成功＋未設定→自動導出のしきい値そのまま、③`derive_ramp_inputs()`失敗時のみ旧
  `display_override`を後方互換フォールバックとして使用、④どちらも無ければ`kind="none"`
  だった（`display_override`自体は削除せず残し、実際に不要になったことを確認したうえで
  DBカラム削除する後続タスクT409へ切り出した——このセクション末尾「`display_override`の
  完全撤去」節でT409完了後の状態へ更新済み）。
- **軸スタジオGUI**（`AxisComposer.tsx`）へ「地図の色分けしきい値」編集項目を追加した。
  生JSON編集が必要な`display_override`と異なり、数値配列の追加/削除/編集のみの
  シンプルなUI（`AxisDefinitionResponse.display_thresholds_override`）。管理API
  （`axis_admin.py`）は昇順・非空をバリデーションする。あわせて`AxisDefinitionResponse`
  へ`display`（`axis_display_for()`の計算結果）を新設した——下書き軸は
  `GET /api/axis-catalog`に現れないため、軸スタジオが「この軸は地図表示用のデータ取得
  経路が無い（`kind="none"`）」という注記を編集画面に出すには、この管理APIのレスポンス
  経由でしか判定できないため。
- **dev DBの移行**: `car_stress`/`stop_density`/`accident`の3軸の`display_override`を
  NULL化し`display_thresholds_override`（car_stress: `[2,3,4]`・stop_density:
  `[1,2,4]`・accident: `[0.133,0.267,0.5]`——旧`[0.4,0.8,1.5]`はタイル生値スケール
  [年正規化前]だったため、材料スケール[年正規化後]への移行に伴い収録年数3で除算して
  再較正）へ、`axis_admin` API相当の`AxisRegistryAdminService`経由（unpublish→update→
  再publish）で移行した。副産物として、`car_stress`の`highway`系tile_inputsが従来の
  手書き13値（`footway`/`path`が漏れていた、改善計画T359のドリフト）から正しい15値
  （`car_stress_highway_base`の実際のmapping）へ自動的に修正された。

詳細はdocs/tasks/T404.md参照。

#### `display_override`の完全撤去（改善計画T409、2026-08-30）

T404で残した後方互換の`display_override`（フィールド・DBカラムとも）を、car_stress/
stop_density/accidentの3軸が実際に不要になったことを確認したうえで削除した。**現状**
（T404時点の上記の3行・4段階の優先順位の記述は本節で置き換わる）:

- `AxisDefinition`（`axis_definitions.py`）は`display_override`フィールドを持たない
  （`display_thresholds_override`のみ）。
- `axis_display_for()`の優先順位は2段階のみ: ①`derive_ramp_inputs()`成功＋
  `display_thresholds_override`設定→自動導出tile_inputsとこのしきい値を組み合わせる
  （未設定なら自動導出のしきい値そのまま）、②`derive_ramp_inputs()`失敗→`kind="none"`。
- `axis_definitions`テーブルの`display_override`列は`migrations/
  0026_axis_definitions_drop_display_override.sql`（`DROP COLUMN`、DDLのみ）で削除した。
  `AxisDefinitionRow`・`axis_definition_repository.py`の(逆)シリアライズ・
  `axis_admin.py`のPayload/Responseフィールドも同一コミットで削除済み。
  `AxisDisplaySpec`（`registry.py`）自体は`axis_display_for()`の戻り値・
  `AxisDefinitionResponse.display`の型として引き続き使われているため削除していない。
- フロント（`AxisComposer.tsx`）の`displayOverride`素通し保持コードも削除した
  （`displayThresholdsOverride`は影響なく残る）。

詳細はdocs/tasks/T409.md参照。

### 一次属性レジストリ・二次軸レジストリ（改善計画T137）

`domain/registry.py`が一次属性（`PrimaryAttributeSpec`）・二次軸（`AxisSpec`）の宣言的な
登録簿を提供する。`register_axis()`は、登録しようとする軸の`inputs`（参照する一次属性の
`attr_id`一覧）のうち`shared=False`のものが既存の別軸と重複していれば
`AxisInputConflictError`を送出する「排他制約の機械的チェック」が設計の核（T142実装中に
`surface_q`軸の`transform_fn`誤参照を実際に検出した実績がある）。

**改善計画T320: `domain/registry_defaults.py: _register_axes()`を軸id直書きの手動列挙から
AXIS_DEFINITIONS走査へ一本化した**。以前は`gradient`/`surface_q`/`stop_density`/
`car_stress`/`accident`/`night`の6軸を1軸ずつ`if axis_id in AXIS_DEFINITIONS: register_axis(
AxisSpec(axis_id="gradient", ...))`のように手書きしており（`wind`は意図的に未登録）、
①組み込み軸がAXIS_DEFINITIONSから削除されるとKeyErrorでビルドが落ちる、②軸スタジオが
新規追加した軸はこの一覧に含まれず`axis-catalog.json`（ビルド時静的生成物）へ永遠に現れない
——という2つの不整合があった（後者は`scripts/export_openapi.py`側の別ループ
`_auto_ramp_axes`で部分的に穴埋めしていたが、これ自体が同じロジックの二重実装という
別の問題だった）。現在は`AXIS_DEFINITIONS.items()`を走査し、公開軸すべて（`wind`も含む、
軸id・軸の数を一切コードへ書かずに）を登録する。`inputs`・`display`は
`domain/axis_display.py: primary_attribute_ids_for()`・`axis_display_for()`
（`GET /api/axis-catalog`が実行時に同じ軸へ対して呼ぶのと同一の純粋関数、片側import）
から導出するため、ビルド時静的生成物と実行時APIの計算ロジックが完全に一致する。
`export_openapi.py`側の`_auto_ramp_axes`は構造的に不要になったため削除した。
`AxisSpec.transform_fn`/`output_range`/`description`フィールド（いずれも実行時経路の
どこからも参照されておらず、`axis-catalog.json`へも書き出されていなかった死蔵フィールド）
も削除した。各軸の`AxisDisplaySpec.label`は`AXIS_DEFINITIONS[axis_id].label`
（Stage DでDB化・軸スタジオでGUI編集可能な方）に統合済み。ただし`register_defaults()`
自体はビルド時・テストのみ実行されアプリ起動時には呼ばれないため、軸スタジオでのDB上の
編集はこの参照を経由して`axis-catalog.json`側へ動的反映されるわけではない
（`GET /api/axis-catalog`という実行時APIには即座に反映される、下記Stage D節参照）。

**改善計画T321（デッドコード監査）: `PrimaryAttributeSpec`の`ingest_fn`/`source`/`geometry`/
`dtype`/`update_cadence`/`description`フィールドを削除した**。上記の`AxisSpec.transform_fn`
等と全く同型の死蔵フィールドで、`ingest_fn`はモジュールパス文字列を持つだけで実際に
`importlib`等で解決する経路が存在せず、他の5フィールドも唯一の消費者`export_openapi.py`が
`attr_id`/`label`/`shared`の3つしか書き出していなかった。連動して`Geometry`/`DType`/
`UpdateCadence`のLiteral型エイリアス（この5フィールド専用）も削除した。単体取得関数
`get_primary_attribute`/`get_axis`（実行時参照ゼロ、テストのみ使用）も同時に削除した。

**本レジストリ（`registry.py`）が駆動するのは表示メタデータのみ**。コスト計算側は
改善計画T221 Stage B/Cで`domain/axis_definitions.py: AXIS_DEFINITIONS`（軸定義データ＋
汎用評価関数）が参照元になった——T142当時に見送られた「レジストリ駆動のコスト計算」は、
transform_fn文字列の動的解決ではなく「材料辞書＋shapeテンプレート＋パラメータをデータで
宣言する」形（Stage Aの4テンプレートで全軸のシグネチャが標準化されたため可能になった）で
実現している。表示レジストリと評価定義の軸ID集合は`test_registry_defaults.py`が機械的に
突き合わせる。改善計画T320により、軸を追加するときに本レジストリへの個別登録は不要になった
——上記「8軸の一覧と重み」の1本道（コスト計算側、中心はAXIS_DEFINITIONSへの1エントリ）
だけで、表示レジストリ（`axis-catalog.json`）側も`_register_axes()`の走査により自動反映される。

`domain/recipe_definition.py`（T141、`Recipe`/`RecipeComponents`等でレシピをJSON/DB
レコード形式へ統合する宣言的インフラとして新設）は、T142が別方式
（`compute_edge_axis_scores`）を採用したため一度も配線されず孤立していたため、
改善計画T155で削除済み。

### 〇次: ハード制約（改善計画T140）

8軸の難易度計算に入る前段として、`domain/evaluation.py: is_edge_allowed`が対象Edgeを
探索グラフから丸ごと除外するかどうかを判定する（設計プロンプト「評価システムの層構造
再設計」の〇次フィルタ、仕様書29章のHard Constraintと同じ概念）。**スコア・重みには
一切登場しない**点が8軸との決定的な違い（該当Edgeは`EdgeCostResult.allowed=False`で
`cost`/`difficulty`ともNoneになり、Dijkstra探索の候補にすら入らない）。

フィルタは名前付きで管理する（`HARD_FILTER_HIGHWAY_TYPES: dict[str, frozenset[str]]`、
`DEFAULT_HARD_FILTERS: frozenset[str]`）。`is_edge_allowed`は`hard_filters`引数
（省略時`DEFAULT_HARD_FILTERS`）で有効なフィルタの集合を受け取り、将来T141で
レシピJSON化した際の`hard_filters: list[str]`フィールドをそのまま渡せる形にしてある
（現時点ではまだどの呼び出し元も上書きしておらず、常に全フィルタ有効＝従来と同じ動作）。

| フィルタ名 | 対象highway | 除外理由 |
|---|---|---|
| `motorway` | motorway, motorway_link | 高速道路。法的に自転車通行不可（設計プロンプトが明示する〇次フィルタそのもの） |
| `trunk` | trunk, trunk_link | 幹線国道等。日本の法規上は自転車通行可能な場合が多いが、本アプリの用途（ロードバイクの周回ルート生成）にとって実務上走りにくい・危険という判断から、T100より前からの既存動作として維持（T140は挙動変更ではなく命名・明文化のみ） |

別途`no_bicycle`フィルタ（`bicycle=no`タグ、改善計画T100で追加）もway_tags側の判定として
同じ`hard_filters`の枠組みに含まれる。

**`motor_vehicle=no`（自転車可・自動車のみ通行禁止）はここに含めない**（改善計画T140での
方針確認）。自転車は法的に通行できるため〇次のハード除外対象にはせず、二次軸
（車ストレス、`domain/axis_definitions.py: AXIS_DEFINITIONS["car_stress_motor_vehicle_no_
adjustment"]`——改善計画T292で専用Pythonレシピの`motor_vehicle_no_override`から移行済み）
側で「該当区間は最善値へ固定」という軸内の特例として扱い続ける。ハード制約（探索対象から
消える）とこの特例（探索はするが最も走りやすい扱いになる）は挙動が異なるため区別が必要、
という設計プロンプトの「ハード制約は
スコア外」原則との整合はこの区別を保つことで満たされる。

### 停止密度・車ストレス・自転車インフラ・交差点密度（P1、OSM由来）

- **停止密度**: `osm_raw_pois`（`domain/traffic.py: classify_stop_poi`が
  traffic_signals/crossing/stop/give_way/level_crossingへ分類、`STOP_POI_MATCH_MAX_DISTANCE_M
  =15m`でEdge/サンプル点へ空間マッチ）。集約は`distance_weighted_stop_density`
  （合計count÷合計distance_km）。
- **車ストレス**（改善計画T150で「交通ストレス」から改称）: 改善計画T292で専用Pythonレシピを
  廃止し、`axis_definitions`（T350でDB専有化済み）上の内部軸5つ+公開軸1つの宣言的な
  階層構造で再実装した。内部軸（いずれも`is_published=False`、他の軸から参照される専用の
  推定軸で一般ユーザーへは公開しない）は`car_stress_highway_base`（highway種別の基準値1-4、
  旧`ROAD_SUITABILITY_BASE_BY_HIGHWAY`と同一の12区分）・`car_stress_maxspeed_adjustment`
  （低速緩和-1/高速+1）・`car_stress_lanes_adjustment`（少車線緩和-1/多車線+1）・
  `car_stress_designation_adjustment`（T51指定路線該当+1）・
  `car_stress_motor_vehicle_no_adjustment`（motor_vehicle=noの区間を最良値へ強制する
  優先確定を、他の内部軸の取りうる最大合計を確実に下回る固定マイナス項-1000として表現し、
  breakpointsのクランプで必ず最良値0へ張り付かせる。詳細は同ファイルのコメント参照）の5つ
  （改善計画T353: 自転車インフラ補正`car_stress_bicycle_infra_adjustment`は1材料1軸原則
  ［T268: `check_material_exclusivity`］を優先し廃止、下記「自転車インフラ」参照）。
  公開軸`car_stress`（`BreakpointLinearShape`、breakpoints `[0,0]-[4,100]`、T353で
  `(1,0)-(5,100)`から再較正。自転車インフラ非該当の道路では旧来と評価が完全一致）は
  この5軸を加重合成し、highway基準値（`required=True`）が未登録ならNone（未評価）になる。
  未知highwayは評価対象外。表示用の0-4生値専用フィールド（`RouteSegmentDetail.car_stress`・
  `domain/axis_definitions.py: car_stress_display_level`）は末端消費者ゼロと確認の上
  改善計画T459（2026-08-31）で撤去済み。表示・集計は汎用の`axis_difficulties["car_stress"]`
  （difficulty 0-100、他の公開軸と同じ経路）に一本化されている。
  地図表示は最終値をタイルへ焼き込まず、内部軸の材料5つ（highway/maxspeed_kmh/
  lanes_count/designation/motor_vehicle_no、T290でMVTへ焼き込み済み）を
  フロント側（`components/Map/axisLayers.ts`のramp汎用機構、下記「レジストリ駆動の
  二次軸ランプレイヤー」節参照）で再合成する。改善計画T404以降、この`tile_inputs`は
  `derive_ramp_inputs()`が5つの内部軸参照を再帰的に解決して自動導出する（手書き登録は
  廃止済み、上記「`display_override`廃止」節参照）。色分けの段階（thresholds）は自動導出
  だと粗くなるため`display_thresholds_override=[2,3,4]`で細かく指定している。最終値を
  計算済みでタイルへ焼き込む従来方式（レシピを変えるたびに世界中のタイルキャッシュを
  作り直す必要があった、T92/T93）とは異なりタイル世代を上げずにcar_stress自体の判定
  ロジックを変更できる。評価軸の`shape_params`調整
  （今回のT353含む）はmigrationではなくaxis_admin APIの unpublish→PUT→republish経由で
  行う運用（CLAUDE.md参照、監査証跡・ロールバックを要さない継続的チューニング対象という
  判断）。ルート採点の重み上書きは他の公開軸と同じく`/api/routes/generate`の
  `route_preference`（§10-1）で行う。
- **自転車インフラ**: 独立の公開評価軸`bicycle_infra_quality`（`BreakpointLinearShape`、
  breakpoints `[-4,0]-[0,100]`）が、正規化済みboolean材料4件（`highway_is_cycleway`
  weight -4・`cycleway_has_track`weight -4・`cycleway_has_lane`weight -2・
  `cycleway_has_shared`weight -1、`domain/recipe.py: bicycle_infra_flags`が単一ソース）を
  直接参照する（改善計画T353、1材料1軸原則［T268］を優先し、それまで軸参照
  ［T292］経由でcar_stress側の内部軸`car_stress_bicycle_infra_adjustment`を仲介していた
  構成から、直接参照へ再設計した）。旧`bicycle_infra`（優先順位付き7値categorical、
  `domain/traffic.py: classify_bicycle_infrastructure`）・`RouteSegmentDetail.
  bicycle_infra`の生値は評価軸のdifficulty表示（`axis_difficulties`）で代替可能になり
  削除済み（改善計画T347）。ルート集約統計`RouteCandidate.bicycle_infra_score`
  （`is_dedicated_bicycle_infra(flags)`から算出していた）も、改善計画T431で
  `ComparisonPanel`が`axis_difficulties`駆動へ移行し末端消費者ゼロになったため削除済み
  （詳細な経緯・教訓は
  [material-normalization-for-axis-composition.md](decisions/material-normalization-for-axis-composition.md)参照）。
- **交差点密度**: 次数3以上（`INTERSECTION_DEGREE_THRESHOLD`）のroad_node。
  `INTERSECTION_MATCH_MAX_DISTANCE_M=30m`で空間マッチ。改善計画T149で難易度への寄与は
  独立軸を持たず停止密度側（タグなし交差点として`signal`等の0.3倍の重みで加算、
  `domain/difficulty.py: stop_difficulty`）へ一本化済み。ルート単位の集約統計
  `RouteCandidate.intersection_density`は改善計画T431で末端消費者ゼロを確認した上で
  削除済み。地図の点タイル表示（`poi-tiles`の`degree`プロパティ）は表示専用の別経路
  として引き続き独立に保持する。

**地図表示ロジックと評価軸材料の分離原則（改善計画T341、教訓はT347再検証込みで
[material-normalization-for-axis-composition.md](decisions/material-normalization-for-axis-composition.md)参照）**:
評価軸（`AXIS_DEFINITIONS`）が参照する材料は正規化された生データ（数値・boolean・単純
categorical）に統一する。地図表示・API応答向けの人間可読な分類ラベルは評価軸の材料とは
別レイヤーの関心事であり、評価軸から参照されなくなったという理由**だけ**では削除対象に
ならない——別の独立した消費者が実在する限りは（ただしこの判定は「今の消費者を前提とする
限り」という条件付きであり、消費者側の設計が変われば再検証が必要になりうる。T347では
`bicycle_infra`の7値分類がこの再検証により実際に削除できた例）。

いずれも`AttributeRepository`（`road_graph_repository.py`）のEdge集合を渡すメソッド
（`get_stop_poi_counts`・`get_way_tags`・`get_intersection_counts`）で提供する
（RoadGraphEngineが使う）。サンプル点列を渡すKNN空間マッチ版（`get_nearest_stop_poi_counts`
等、openrouteserviceエンジン専用）は改善計画T462のエンジン撤去に伴い削除した。
`get_way_tags_by_osm_way_id`（T90、
osm_way_id完全一致の1行取得）はこの対に属さない別系統で、区間インスペクタAPI
（`POST /api/region/axis-inspector`。改善計画T292で車ストレス専用の内訳API
`POST /api/region/car-stress-breakdown`を統合・廃止した、下記「レジストリ駆動の二次軸ランプ
レイヤー」節参照）専用。地図表示は同じ属性を`road-surface-tiles`
（highway・surface同様プロパティとして焼き込み。車ストレス）と、点データの
`poi-tiles`（停止要因・交差点密度、後述）で提供する。

### 安全度（改善計画: 安全度レシピ、T148で削除）

車ストレスとは別に、事故・怪我リスクの客観的な目安を表す軸として`domain/safety.py:
safety_breakdown`（車ストレスと同じ構造、街灯・トンネル補正付き、1-4の整数）を新設して
いたが、改善計画T139で難易度合成からは外れ、以後は表示専用の別軸として残置していた。
本番投入前で移行リスクが無いことを踏まえ、改善計画T148で`domain/safety.py`・
`safety_recipe.yaml`・関連API（`POST /api/region/safety-breakdown`）・地図の安全度レイヤー
（`frontend/src/components/Map/safetyExpression.ts`）・調整UI
（`frontend/src/components/SafetyRecipePanel/`）を一括削除した。街灯・トンネル補正は
T139時点で既に`domain/night.py: night_difficulty`として独立済みのため、削除による評価軸の
欠落は無い。当時`recipeControls.tsx`（`LevelPicker`/`AdjustmentStepper`/`FieldLabel`）・
`recipeExpression.ts`・`recipe.py`（判定プリミティブ）は車ストレス軸の実装として
そのまま残っていたが、改善計画T292で車ストレス自体が専用Pythonレシピを廃止したことに伴い、
`CarStressRecipePanel.tsx`ごと`recipeExpression.ts`は削除。`recipeControls.tsx`は
`RouteSettingsPanel`等が引き続き使う`RecipePanelSection`/`withAutoEnable`/`FieldLabel`のみ残し、
車ストレス専用だった`LevelPicker`/`AdjustmentStepper`等は削除。`recipe.py`は材料タグ正規化
の純関数群のみ残る（詳細は上記「停止密度・車ストレス...」節参照）。

### 事故密度（T50、警察庁交通事故統計オープンデータ）

`app/batch/import_accidents.py`が本票CSV（年度別、`backend/data/accidents/`、ユーザーが
年度ページから入手して配置）を取込む。関東7都県・2022〜2024年（2019〜2021年は本票のCSV列数が
異なる別スキーマのため未対応）。migration `0006_add_accident_points.sql`で
`accident_points`（`accident_id`主キー・`occurred_year`・`fatal`・`involves_bicycle`・
`geom`）・`accident_import_runs`（取込実行の記録）を追加。`domain/accident.py`が
純関数群（`ACCIDENT_MATCH_MAX_DISTANCE_M=30m`等）を持つ。合計count÷合計distance_km÷
収録年数で「件/(km・年)」へ正規化する`distance_weighted_accident_density`は、
`RouteCandidate.accident_density`集約用として存在していたが改善計画T431で末端消費者
ゼロを確認した上で削除済み（区間ごとのaccident軸評価は`domain/evaluation.py`が直接
材料合成する）。収録年数は
`AttributeRepository.get_accident_years_covered`（`accident_import_runs`のsucceeded run数、
年重複なし）でハードコードせず動的取得する。地図表示は`GET /api/region/accident-tiles`
（後述、`AccidentService`/`AccidentTileQuery`）。

改善計画（事故密度の精度改善、既定挙動として反映）: `get_accident_counts`
（`road_graph_repository.py`）の`bicycle_only`既定値を`False`→`True`へ変更した
（自転車ルート案内アプリで自動車同士のみの事故まで数えていたのは実質バグに近いという
判断）。あわせて単純COUNTから死亡事故を`ACCIDENT_FATAL_WEIGHT`（`domain/accident.py`、
暫定値3.0）件分として積算するSUMへ変更し、戻り値がint→floatになった。当時
`GraphService.get_accident_counts`（repository層への薄いラッパー）に欠けていた
`bicycle_only`引数も追加し、road_graph_engine経由のルート生成にも既定値変更が実際に
反映されるようにした（この`GraphService`側ラッパー自体は、T219以降
`get_search_materials_for_bbox`/`get_edge_attribute_counts`が探索フェーズの読み取り経路を
一本化したことでランタイム呼び出し元が無くなり、改善計画T226で削除済み。repository層の
`get_accident_counts`は現在も存在し、`bicycle_only`の既定値もそのまま有効。サンプル点列版
`get_nearest_accident_counts`はopenrouteserviceエンジン専用だったため改善計画T462で削除）。

### 指定路線コンフレーション機構（T51、国土数値情報 N10/N12）

`app/batch/import_designations.py`が国土数値情報のN10（緊急輸送道路）・N12（重要物流道路）を
都道府県別ZIP（公開URLから直接取得、`backend/data/designations/`）から取込み、
`route_designations`（線データ、`kind`=`emergency_transport`/`critical_logistics`）へ
`(kind, pref_code)`単位でDELETE→INSERTする（migration `0007_add_route_designations.sql`）。
`app/batch/match_designations.py`が`route_designations`を`DESIGNATION_BUFFER_WIDTH_M=20m`で
バッファし、`osm_raw_ways`との交差長比が`DESIGNATION_MATCH_MIN_RATIO=0.5`以上のWayを
`designation_attributes`（osm_way_id基準のWay派生の事前計算）へ書き込む事前計算バッチ
（取込後・OSM再取込後に再実行が必要）。定数はすべて`domain/designation.py`が正準
（`DESIGNATION_IMPORT_KINDS`＝取込対象kind、`CAR_STRESS_DESIGNATION_KINDS`＝
車ストレス+1補正の対象kind。現状は同一集合だが概念的に別軸として別定数）。

改善計画T74（2026-08-16）: マッチング対象は当初`road_edges`（ルート生成地点周辺のみ遅延構築）
だったが、`route_designations`が関東全域投入済みなのに表示がルート生成履歴のあるエリアに
限られる不具合の根本対応として`osm_raw_ways`（関東全域自己完結）基準へ変更した。副作用として
評価粒度もedge単位any-matchからway単位ratio-matchへ統一されている。

該当区間は新しい評価軸を増やさず、**車ストレスへの+1補正のみ**として組み込む
（内部軸`car_stress_designation_adjustment`、大型車交通の代理指標。改善計画T292で
旧`car_stress_breakdown`の`designation_adjustment`からAXIS_DEFINITIONSへ移行済み）。
`AttributeRepository.get_designated_edge_ids`（RoadGraphEngine、Edge集合の積集合。呼び出し時点で
`road_edges`は構築済みのため、`road_edges.osm_way_id`経由で`designation_attributes`へJOINする）で
提供する（サンプル点列版`get_nearest_way_tags`が返す3要素目`is_designated`はopenrouteservice
エンジン専用だったため改善計画T462で削除。旧`get_nearest_designated_flags`は改善計画T76で
`get_nearest_way_tags`へ統合済みだった）。
地図表示は`road-surface-tiles`のMVTに`designation`プロパティ（`emergency_transport`/
`critical_logistics`/両方該当時は`both`/未該当はプロパティ欠落、`designation_attributes`を
osm_way_id単位へ集約してから`osm_raw_ways`へJOIN）として焼き込む。改善計画T338
フォローアップ（2026-08-26）: この3値へCASE式で畳み込む前の生フラグ（`is_ert`/`is_cl`）を
`is_emergency_transport`/`is_critical_logistics`という2つの真偽値タイルプロパティとしても
併せて焼き込み、`material_catalog.py`の同名の正規化材料（軸スタジオで選択可能、ただし
`extractor`は種別ごとのper-edge kind配線が未整備なためトリガー付きDEFER）が参照する
（「表示専用材料の除外」節参照）。

### 派生データの系譜追跡（改善計画T351、migration 0024）

T350のDB設計書レビューで、`edge_attribute_counts`/`way_attribute_counts`/
`designation_attributes`（いずれも上記の事前計算バッチが書く派生データ）が
`computed_at`/`calculated_at`しか持たず、(a) どの`accident_import_runs`/
`osm_import_runs`の内容から計算したか、(b) 「入力データが古い」のか「計算ロジックが
変わった」のかを区別する手段が無いと判明した（[docs/tasks/T351.md](tasks/T351.md)参照）。
以下の列を追加した:

- **`source_accident_import_run_id`/`source_osm_import_run_id`**（`edge_attribute_counts`・
  `way_attribute_counts`・`designation_attributes`のうちaccident/osm各データに依存する列のみ）:
  バッチ実行時点での`accident_import_runs`/`osm_import_runs`の`status='succeeded'`な行の
  中でのMAX(id)（**高水位マーク**）。行単位の厳密な系譜ではなく「この計算はどのデータ世代
  までを見ていたか」を表す——`accident_import_runs`は年ごとに複数行が積み上がる設計のため
  全年度を列挙する代わりに、単調増加するidの最大値を記録・比較するだけで新規取込の有無を
  検出できるという設計判断。ORM側は`ForeignKey()`を持たない素の`Integer`列（実FK制約は
  migrationのみが持つ）——`road_graph_models.py`が`accident_models.py`/
  `designation_models.py`の存在を知らずに定義できることを優先した（クロスモジュールFKを
  ORM側にも書くと、参照先モデルをimportしないプロセス——`precompute_edge_attribute_counts.py`
  単体実行時のテストフィクスチャ等——で`Base.metadata.sorted_tables`/`create_all`が
  `NoReferencedTableError`を起こすことを実機確認したため）。
- **`algorithm_version`**（`edge_attribute_counts`・`way_attribute_counts`のみ）: 計算ロジック
  自体（半径・重み付け等のパラメータ）の版数。`region_service.py: ROAD_SURFACE_TILE_VERSION`と
  同じ「パラメータを変えたら手動で上げる」文字列定数で、各バッチモジュール自身が持つ
  （`precompute_edge_attribute_counts.py`/`precompute_way_attribute_counts.py`の
  `ALGORITHM_VERSION`）。`designation_attributes`は既存の`data_version`列
  （バッファ幅`buffer{N}m`）が実質同じ役割を既に果たしているため新設していない。
- **`matched_route_designation_ids`**（`designation_attributes`のみ）: この`(osm_way_id, kind)`の
  `matched_ratio`へ実際に寄与した全`route_designations.id`（`integer[]`）。
  `match_designations.py`の`_MATCH_SQL`は同一`(osm_way_id, kind)`に複数の`route_designations`行が
  交差する場合、`ST_Union`で交差長を1本に集約してから比率を求める（二重計上防止のため）。
  単一のFK列では「実際にどの行が寄与したか」を表現できないため、寄与した全行のidを
  `array_agg(DISTINCT b.id)`で配列として保持する設計にした。

**現時点でできること・できないこと**: これらの列は「記録」のみで、生データが更新された際に
自動で再計算をトリガーする仕組みは持たない（[docs/batch-pipeline-dependencies.md](batch-pipeline-dependencies.md)
「段階2・3」参照）。記録された値を人が`SELECT`で参照し、現在の`accident_import_runs`/
`osm_import_runs`のMAX(id)と比較することで「再計算が必要か」を判断できるようになっただけ——
T281段階3（鮮度台帳、自動比較の仕組み）に着手する際は、この列がそのまま材料になる。

### 静的レイヤー・タイル配信（フロント固定レイヤー＋レジストリ駆動の二次軸ランプレイヤー）

[frontend/src/components/Map/mapLayers.ts](../frontend/src/components/Map/mapLayers.ts)の
`MAP_LAYERS`カタログは標高図・道路の種類・路面の種類（T165で「道路情報」から論理分割）・
車ストレス・自転車インフラ・指定路線・停止要因POI・補給休憩ポイント（T101）・
事故（警察庁統計）・ルートの固定レイヤー（旧・安全度レイヤーは改善計画T148で削除）に加え、
降水ナウキャスト・風（矢印）の2レイヤーが`kind="static"`（選択候補と無関係に常設）・
`dataNature="dynamic"`（値は時刻で変わる）として同じカタログに乗る（「動的気象レイヤー」節
参照）。交差点密度（次数3以上のroad_node）はバックエンドの
`poi-tiles`が引き続き焼き込むが、道路網を見れば概ね自明という判断（改善計画T96）により
地図上の独立可視化レイヤーとしては提供しない（`intersection_weight`のルーティング材料
としては引き続き使う）。色分け・凡例・絞り込み軸の定義は
[frontend/src/components/Map/staticAttributeLayers.ts](../frontend/src/components/Map/staticAttributeLayers.ts)
に集約（`STATIC_FILTER_AXES`が絞り込みUIのカタログ、事故のみ当事者×重大度の2軸）。
地図上チップ（`MapOverlayControls.tsx`）最上位のグルーピング（道路/環境/スポット）は
改善計画T406/T418により`MapOverlayGroup`が担う。サイドバー（`MapLayersPanel.tsx`、「地図の
見え方」パネル）も改善計画T413で同じ`mapOverlayGroupFor`を単一ソースとして使うよう統一済み
（「地図チップの最上位グルーピング（道路/環境/スポット、改善計画T406/T418）」節参照）。

タイル配信は3系統:

1. **`road-surface-tiles`**（既存、`ROAD_SURFACE_TILE_VERSION`）: highway・surface_good・
   smoothness・tunnel・bridgeに加え、`designation`・車ストレスの
   材料タグ（`maxspeed_kmh`/`lanes_count`/`motor_vehicle_no`。`cycleway_class`は
   改善計画T337で、`bicycle_infra`は改善計画T347で削除済み）と、night軸が参照する`lit`、改善計画T145b（下記
   「レジストリ駆動の二次軸ランプレイヤー」参照）が
   追加した`way_attribute_counts`由来のkm正規化密度3種（`accident_per_km`/`stop_per_km`/
   `intersection_per_km`、0はNULLIFでプロパティ自体を省略）をLineString地物へ追加
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
   （評価軸・地図表示のどちらからも未参照になった`cycleway_class`プロパティを削除。
   非互換変更だが未使用のためデプロイ順序制約なし）、v15=T338フォローアップ
   （designationが畳み込む前の正規化フラグ`is_emergency_transport`/`is_critical_logistics`
   プロパティを追加。プロパティ追加のみでデプロイ順序制約なし）、**v16=T347。地図表示の
   専用レイヤー廃止・評価軸側の公開軸`bicycle_infra_quality`への置き換えに伴い、
   評価軸・地図表示のどちらからも未参照になった`bicycle_infra`プロパティを削除**
   （v14と同じく非互換変更だが未使用のためデプロイ順序制約なし、現行）。
2. **`GET /api/region/poi-tiles/{z}/{x}/{y}.pbf`**（`POI_TILE_VERSION`、T54新規）:
   `osm_raw_pois`の点データを`kind`プロパティ付きで焼き込む1レイヤー（`stop_poi`）構成。
   停止要因（信号・横断歩道・一時停止・踏切）に加え、T101で補給・休憩ポイント
   （コンビニ・自販機・トイレ・給水・駐輪場）のkind値も同じテーブル・同じMVTクエリへ
   相乗りさせた（SQL自体は無改修、`kind`を無条件で焼き込む設計のため）。フロント側は
   `kind`値の集合でstopPoi/supplyPoiの2つの独立レイヤーへ絞り込む
   （`MapView.tsx`のbaseFilter、`legendFilter.ts`参照）。交差点密度（`degree`）は
   T96でフロント可視化を撤去、T97で配信自体も削除済み（ルーティング材料としては
   `_INTERSECTION_COUNTS_SQL`が別途独立に計算）。road-surface-tilesと同じ
   `ROAD_TILE_MIN_ZOOM`〜`MAX_ZOOM`のXYZタイル。
3. **`GET /api/region/accident-tiles/{z}/{x}/{y}.pbf`**（`ACCIDENT_TILE_VERSION`、T50新規）:
   事故地点の点データ（`involves_bicycle`・`fatal`）。`AccidentService`
   （[backend/app/services/accident_service.py](../backend/app/services/accident_service.py)）・
   専用リポジトリ`infrastructure/accident_repository.py`が担当し、`region_service.py`とは
   別系統（データソースがOSM派生グラフではなく`accident_points`のため）。

いずれもタイル世代はプロパティ追加のたびに上げ、`regionApi.ts`側の対応する定数
（`ROAD_SURFACE_TILE_VERSION`/`POI_TILE_VERSION`/`ACCIDENT_TILE_VERSION`）とドリフト検知
テスト（`regionApi.test.ts`、`export_openapi.py`が書き出す
`generated/region-tile-config.json`との照合）で同期を保証する。

### レジストリ駆動の二次軸ランプレイヤー（改善計画T145b）

上記10レイヤーとは別に、`domain/registry_defaults.py`の二次軸レジストリ（T137）から
自動生成される「ランプ」レイヤー（accident/stop_density軸、現状2種）がある。設計方針は
「**事実はタイルに、解釈はクライアントに**」: レシピ非依存の事実（`way_attribute_counts`由来の
`accident_per_km`/`stop_per_km`/`intersection_per_km`、上記road-surface-tiles v12参照）は
全ユーザー共有キャッシュのタイルへサーバー側で焼き込み、二次軸スコアへの変換（重み・
しきい値・凡例）はクライアント側のMapLibre expressionで行う（レシピ依存の解釈をキャッシュ
共有タイルへ焼き込めないという制約と、accident/stop_density軸の入力データがタイル外に
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

### 動的材料の状態別表現契約とway_id→動的値配信層（改善計画T405→T414→T423で汎用化）

上記の二次軸ランプレイヤーは「事実はタイルに焼き込み、解釈（重み・しきい値）はクライアント側の
MapLibre expressionで行う」方式だが、風のように**道路自身に紐づかない外部条件（風向風速）が
関与する材料**は、レシピ非依存の事実そのものがタイル生成時点では定まらない（同じ道路でも
時刻によって値が変わる）ため、この方式に乗らない。

こうした「動的材料」は、材料非依存の共通**状態機械**（[docs/tasks/T400.md](tasks/T400.md)
「2.」節、[T414](tasks/T414.md)で確立）に従う: ルート未確定時は「ユーザーが指定したパラメータ
（風なら時刻＋走行方位）を視界内の全道路へ一律適用」・ルート確定後は「ルート自身の実値
（実進行方向・実到達時刻）でルート線のみへ着色」。風はこの契約の最初の実装例——**T405時点の
実装（道路自身のOSM格納方向・現在時刻固定で評価）はこの契約と矛盾する誤った前提に基づいて
おり、T414（2026-08-30）で作り直した**。

**ルート未確定時**（「環境」グループ・評価軸としての風が同じ[時刻,向き]入力を共有する。
改善計画T418で評価軸は独立した地図チップではなくなったが、この入力共有の関係性自体は
維持している——windAxisの色分けを起動する場所がルート設定パネル
[`RouteSettingsPanel.tsx`]へ移っても、向きの指定元は「環境」グループのコンパススライダー
[`WindBearingSlider`]のまま）:

- **環境（面、`gridFill`）**: 風の矢印（`windVector`、格子点マップ§動的気象レイヤー参照）と
  同じフェッチ済みの風グリッド（`useWeatherGrid`のeffectiveGrid）から、コンパススライダー
  （`WindBearingSlider`、`@fseehawer/react-circular-slider`採用）で指定した走行方位を使い、
  **クライアント側だけ**でwind_penaltyを計算する（`frontend/src/components/Map/
  windPenalty.ts: windPenalty`、backend `WindCalculator.wind_penalty`のJS移植）——追加の
  API呼び出しは発生しない。矢印（gridMark）の背後に薄く重ね描きする面塗りは、当初
  `DYNAMIC_WEATHER_RENDERERS`汎用機構が「1グループにつき単一payload.kind」前提だったため
  `ensureWindPenaltyFillLayer`/`applyWindPenaltyFillGeojson`という独立実装（bespoke）に
  していたが、**改善計画T432**でこの制約自体を「1グループ＝複数の名前付きソース」へ
  一般化したことで、`windVector`グループの`penaltyFill`ソースとして汎用機構へ統合した
  （§動的気象レイヤー参照。bespoke実装は撤去済み）。
- **評価軸（線）**: `WindWayService.get_way_wind_penalties(z, x, y, at, bearing_deg)`
  （[wind_way_service.py](../backend/app/services/wind_way_service.py)）が、指定タイル内の
  way_id一覧（`RoadGraphRepository.get_way_ids_in_tile`——T414で道路自身の向き計算
  [`ST_Azimuth`]が不要になったため、旧`get_way_bearings_in_tile`より大幅に単純化した
  クエリへ置き換え）を取得し、最寄りの風グリッド格子点（`domain/wind_grid.py:
  nearest_grid_point`）の風向風速と、**ユーザーが指定した単一の走行方位**（全道路共通、
  道路自身の向きは計算に使わない）から`WindCalculator.wind_penalty`で1回だけ計算し、
  タイル内の全way_idへ同じ値を割り当てる（同じタイル内の全wayは常に同じ値を持つ——
  風グリッドをタイル中心1点で代表させる既存の近似＋走行方位が全道路共通のため）。
  計算結果は`(z, x, y, 時刻バケット, 向きバケット[5度刻み]) → スカラー値1個`という
  タイル単位のキーでRedisへキャッシュする（[wind_way_penalty_cache.py]
  (../backend/app/infrastructure/wind_way_penalty_cache.py)、TTLは風グリッドの新鮮判定TTL
  `WIND_GRID_CACHE_TTL_SECONDS`と同じ3時間）——T405時点は`way_id`単位のキー（旧設計、
  道路自身の向きが固定値だったため時刻だけが変数だった）だったが、T414で走行方位も
  ユーザー指定の変数になったことを受け、はるかに小さいタイル単位のキー空間へ再設計した。
  `GET /api/region/dynamic-way-values/wind/{z}/{x}/{y}`（§4参照、`bearing_deg`クエリ
  パラメータ必須）が`{way_id: wind_penalty}`を返す——静的なroad-surface-tiles（MVT、
  変更なし）とは完全に別経路のJSONエンドポイント。
  フロントは`ROAD_TILE_SOURCE_ID`のvector sourceへ`promoteId: { [ROAD_TILE_SOURCE_LAYER]:
  "osm_way_id" }`を設定し、既存の`osm_way_id`プロパティをMapLibreの`feature.id`へ昇格させる。
  `hooks/useWindAxisPenalties.ts`が現在のビューポート（500msデバウンス）を覆う道路タイル分を
  まとめてfetchし（`windAxisLayer.ts: tilesCoveringViewport`）、`MapView.tsx`が
  `map.setFeatureState({source, sourceLayer, id: wayId}, {windPenalty: value})`で道路タイル
  の地物へ後から値を差し込む。色分けは`["feature-state","windPenalty"]`を読むMapLibre
  expression（`windAxisLayer.ts: windAxisColorExpression`）で、環境グループのgridFillと
  同じしきい値・配色（`WIND_AXIS_THRESHOLDS`）を共有する。

**ルート確定後**: パラメータ指定UI（コンパススライダー・上記windAxisの一律色分け）は終了する
（`page.tsx`が`hasDetail`で`showWindAxis`/`showWindPenaltyFill`をfalseへ倒し、
`RouteSettingsPanel.tsx: renderMapColorToggle`が風の色分けトグルを「地図表示なし」の
案内表示へ切り替える[改善計画T418]。`MapView.tsx: clearRoadTileFeatureState`
（改善計画T440で`clearWindAxisFeatureState`/`clearGradientAxisFeatureState`という
重複した2関数を統合したもの）が`map.removeFeatureState`でそれまでの全道路ぶんの
feature-stateを明示的にクリアする）。
代わりに、既に実装済みだった`RouteSegmentDetail.axis_difficulties.wind`（ルート生成時点で
区間ごとの実進行方向・実到達時刻を使って計算済み、`routeStyleModesFromCatalogAxes`が
axis-catalogの`wind`軸の`supports_route_coloring`フラグから自動生成する`routeStyleModes`の
"wind"モード、「ルート設定/結果パネル」の「生成したルートの色分け」）が、ルート線のみへの
正確な色分けを担う——これはT400.md「3.」節の実装（T352）で既に存在しており、T414で新規に
実装したものではない。

`mapLayers.ts`の`windAxis`レイヤー自体（`layerVisibility.windAxis`のON/OFF・実際の地図描画）は
変更していないが、それを起動するUIは改善計画T418で地図上チップから撤去し、ルート設定パネル
（`RouteSettingsPanel.tsx`）の「風」行から起動する形へ移設した（下記節参照）。

#### 勾配（gradient、第2の具体例）と配信機構の汎用化（改善計画T423、T411の実施）

勾配も標高データ自体は既に永続化済み（`elevation_attributes`テーブル、T218a）のため同じ状態
機械に乗る（[T423](tasks/T423.md)、2026-08-30完了）。風・勾配の2例が揃ったことをトリガーに、
[T411](tasks/T411.md)（バックエンド配信機構の汎用化検討）も同時に実施した。

**風との違い（設計上の要点）**: 風は「道路自身の向きが不要」という訂正を経た材料（T414）だが、
勾配は逆に**道路自身の向きが本質的に必要**——`gradient_percent`自体が道路の始点→終点方向を
基準にした符号付き値のため。この違いを吸収するため、汎用化した配信機構は「1タイルにつき
スカラー値1個をway_id一覧全件へbroadcastする」（風）と「1タイルにつきway_idごとに異なる値を
持つ」（勾配）の両方を同じキャッシュ表現（`dict[way_id, float]`のJSON）で扱えるようにした。

**符号補正（確定済みの設計判断）**: `effective_gradient = gradient_percent × cos(道路自身の
向き − ユーザー指定の向き)`という連続的なcos補正を採用した
（[domain/gradient.py](../backend/app/domain/gradient.py): `GradientCalculator.
effective_gradient`）。道路の向きと指定方向のなす角度に応じて滑らかに変化し、二値反転案
（±90°で符号切替）のような境界での不自然な急変が無い。同じ道路の逆方向のroad_edges行
（forward/backward）のどちらを使っても、道路の向き±180度・gradient_percentの符号反転が
同時に起きるため計算結果は変わらない（cosは偶関数）。

**T411の実施内容（汎用化）**:
- **エンドポイント**: `GET /api/region/dynamic-way-values/wind/{z}/{x}/{y}`という風専用の
  固定パスを`GET /api/region/dynamic-way-values/{material_id}/{z}/{x}/{y}`
  （[region.py](../backend/app/api/routers/region.py): `region_dynamic_way_values`）へ
  一本化した。`material_id`は[domain/dynamic_way_values.py](../backend/app/domain/dynamic_way_values.py):
  `dynamic_way_value_materials()`（`AXIS_DEFINITIONS`の`dedicated_way_value_layer=True`
  な軸から`needs_time`/`needs_bearing`を導出する関数、改善計画T458。勾配は
  `needs_time=False`）で検証し、未知のidは404・向き依存の材料でbearing_deg省略は422。
  DI（`api/dependencies.py: get_dynamic_way_value_service`）は`material_id`パスパラメータを
  直接受け取り、材料に応じたサービス（`WindWayService`/`GradientWayService`）をDBセッション
  1つだけで組み立てる（両方を毎回Dependsすると2重にセッションを開いてしまうため）。
- **キャッシュ層**: 旧`wind_way_penalty_cache.py`（風専用、キーは`(z,x,y,時刻,向き)`→
  スカラー値1個）を[dynamic_way_value_cache.py](../backend/app/infrastructure/dynamic_way_value_cache.py)
  （材料id駆動、キーは`(material_id,z,x,y,時刻,向き)`→`{way_id: 値}`のJSON）へ汎用化した。
  風は従来どおり全way_idへ同値をbroadcastしたdictを渡すだけで動作は変わらない。
- **サービス層**: `WindWayService`（風専用、風グリッド取得＋`WindCalculator.wind_penalty`）
  と[GradientWayService](../backend/app/services/gradient_way_service.py)（勾配専用、
  `RoadGraphRepository.get_way_gradient_inputs_in_tile`でway単位の`(gradient_percent,
  road_bearing_deg)`を取得しway単位で`GradientCalculator.effective_gradient`を計算）は、
  どちらも`get_way_values(z, x, y, at, bearing_deg) -> dict[int, float]`という統一
  インターフェースを持つ（`at`は勾配側では無視するが、router側の材料非依存な呼び出しを
  可能にするため受け取る）。材料ごとの計算式自体は各サービスの専用ロジックのまま——
  2具体例しかない現時点で共通のProvider抽象を無理に導入せず、キャッシュ層という実際に
  共有できる部分だけを汎用化した（複雑度平衡の原則）。
- **フロント**: タイル座標計算・複数タイル応答統合（`tilesCoveringViewport`/
  `mergeDynamicWayValues`）を[dynamicWayValues.ts](../frontend/src/components/Map/dynamicWayValues.ts)
  へ抽出し、`windAxisLayer.ts`（風固有の配色・しきい値）・新設`gradientAxisLayer.ts`
  （勾配固有の配色・しきい値、ルート確定後の`routeStyleModes.ts`と同じ配色・しきい値
  `GRADIENT_BOUNDARIES`を共有）が個別に持つ。フェッチ本体は`services/regionApi.ts:
  fetchDynamicWayValues(materialId, ...)`・状態管理は`hooks/useDynamicWayValues.ts:
  useDynamicWayValues(materialId, ...)`として統合した（旧`fetchWindWayPenalties`/
  `useWindAxisPenalties`を汎用化、風・勾配どちらもこの1本のフック・1本のfetch関数を使う）。

**環境グループの勾配gridFill（面表示）**: 風のgridFillは矢印と共有の独立した気象グリッド
（道路と無関係な空間フィールド）から作れたが、勾配にはそのような独立フィールドが無い
——勾配は本質的に道路（way）ごとの属性である。そのため、評価軸グループ向けに既にフェッチ
済みのway単位`effective_gradient`値（追加のAPI呼び出し無し）を、フェッチ元のタイル境界
そのものを1セルとして平均集計した面表示へ変換する
（[gradientGridFill.ts](../frontend/src/components/Map/gradientGridFill.ts):
`gradientGridCellsFromTileResponses`。タイル境界の算出は`dynamicWayValues.ts:
tileBoundsLonLat`、`domain/region.py: tile_bounds_lonlat`のJS移植）。

**向き指定UI**: `WindBearingSlider`をそのまま再利用した（新規コンポーネント無し）——
value/onChange/ariaLabelという既存propsが元々「向きだけ」を扱う汎用的な形（時刻は
コンポーネントの外[`DynamicLayerTimeSlider`]で完結）だったため、コード変更は不要だった。
`page.tsx`は風・勾配で単一の共有state`travelBearingDeg`を持ち、地図上の
`TravelBearingControl`1箇所からのみ`WindBearingSlider`をマウントする
（詳細は[docs/modules/frontend/page-composition.md](modules/frontend/page-composition.md)
「動的材料（風・勾配）の状態別表現契約」参照）。

**preprocess="abs"対応（改善計画T404の先送り分）**: T423での調査の結果、実装しないことを
最終決定した——absを使う軸は`gradient`のみで、`gradient`が参照する材料`gradient_percent`は
`tile_property_direction_dependent=True`（方向依存材料）でもあり、方向依存材料を含む軸は
`derive_ramp_inputs`がこの時点で`None`を返すよう既に設計されている。つまりabs対応を実装
しても`gradient`のkind="ramp"化には一切寄与しない（2つの独立した制約が両方ともこの軸を
弾く）——かつ`gradient`の地図表示は上記のとおりRedis経由のway_id→値配信という別経路に
決着しており、そもそもramp（MVTタイル焼き込み）を必要としない。詳細は
[domain/axis_display.py](../backend/app/domain/axis_display.py)のモジュールdocstring参照。

**ルート確定後**（勾配）: T423時点では`routeStyleModes.ts`の`STATIC_MODES`が持つ固定の
`"gradient"`モードだったが、**改善計画T440（2026-08-30）でこの`STATIC_MODES`という
仕組み自体を撤去した**。以下、T440時点の設計を記す。

**T440（軸スタジオのデータを唯一の正としてルート結果の色分けを完全に駆動する）**:
T352〜T434の間、"wind"は`supports_route_coloring`経由で動的に生成される一方、
"gradient"/"road"/"difficulty"は`STATIC_MODES`という固定配列としてフロントに直書き
されたままだった（表示する/しないの判定・しきい値・ラベル・色のいずれも軸スタジオの
データを見ていなかった）。T440はこれを解消し、以下の設計へ全面的に作り直した:

- `AxisDefinition.shape`（`kind`/`preprocess`/`terms`、軸スタジオで軸を定義する時点で
  既に選ぶ既存データ）から、`isSignedAbsShape(shape)`（`shape.kind===
  "breakpoint_linear" && shape.preprocess==="abs" && shape.terms.length===1`）が
  「符号付き値を直接読むべきか」を判定する。`axis.axis_id==="gradient"`という文字列
  比較は使わない——gradientの実データがたまたまこの条件を満たすだけで、条件を満たす軸が
  将来増えてもコード変更なしに同じ経路へ乗る。真の場合は`shape.terms[0].material`
  （gradientの場合`"gradient_percent"`、`RouteSegmentDetail`のフィールド名と一致する
  文字列）を直接読む。偽の場合（wind・surface_q等）は従来どおり
  `axis_difficulties[axis_id]`（abs差難易度0-100）を読む。
- `buildRangeSteppedMode`: 境界値配列（軸スタジオの`display_thresholds_override`、
  未設定時は経路ごとの既定値）の**長さがそのまま段階数を決める**汎用関数。ラベルは
  境界値の実際の数字から機械的に生成する（「易しい/普通/難しい」「下り/上り」のような
  固定語彙は使わない）。色は`interpolateColors(colorLow, colorHigh, count)`
  （2色の間をHSL色空間で均等補間、新設）で生成するため、固定の色配列を持たない。
- `AxisCatalogEntry`（`GET /api/axis-catalog`）へ`shape`・`display_thresholds_override`を
  追加した——「個別フィールドを都度追加するのではなく、軸スタジオで決められること全部を
  まとめて返す」方針（ユーザー指摘を受けた設計判断）。
- `road`という名前の専用モードは無くなり、`surface_q`が他の動的モードと同じ
  `${axis.label}の影響`という汎用ラベルで現れる。`road_surface_good`
  （route_generator側が表示する真偽値）と`surface_q`軸が読む材料`surface_good`
  （`material_catalog.py: _extract_surface_good`）は、どちらも`classify_osm_surface()`
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
- プレルート側（ルート設定パネルの「地図で色分け」トグル・地図上チップグルーピング）の
  同種のaxis_idハードコード分岐（`RouteSettingsPanel.tsx: mapColorLayerIdFor`・
  `mapLayers.ts: isAxisStudioLayer`）も、新設した`AxisDefinition.
  dedicated_way_value_layer`（この軸が専用のway_id→値配信レイヤーを持つかの宣言）で
  判定するよう置き換えた。`isAxisStudioLayer`は`mapOverlayGroupFor`という広く呼ばれる
  純粋関数の内部で使われるため、ライブなaxis-catalogを動的注入する設計は見送り、
  `RAMP_AXES`/`AXIS_LABELS`と同じ「ビルド時静的axis-catalog.jsonからの片側import」
  パターン（`DEDICATED_WAY_VALUE_LAYER_IDS`）に揃えた。

### 地図チップの最上位グルーピング（道路/環境/スポット、改善計画T406/T418）と一次/二次命名（改善計画T163〜T169）

> 経緯・教訓（T167の自動ON連動導入→T181/T214での撤去、T215のタッチスクロール不具合対応等）は
> [decisions/map-chip-primary-secondary-registry.md](decisions/map-chip-primary-secondary-registry.md)参照。

一次属性・二次軸の命名・材料の単一ソースは`domain/registry.py`/`registry_defaults.py`（T163）で、
`export_openapi.py`が`axis-catalog.json`へ書き出す。フロント側は
[frontend/src/components/Map/primaryAttributes.ts](../frontend/src/components/Map/primaryAttributes.ts)が
1次→2次・2次→1次の導出を片側importで行う（T164、T308で情報源を実行時APIへ更新。詳細は
上記T308節）。

**地図上チップ（`MapOverlayControls.tsx`）の最上位グルーピング**は改善計画T406（2026-08-30）で
「観測データ/推定指標（合成）/動的データ」（データの出自による3分類）から「道路/評価軸/環境/
スポット」（対象＝何についての情報かによる4分類）へ再編し
（[docs/tasks/T400.md](tasks/T400.md)「1. パネルの最上位グルーピング」節・
[docs/tasks/T406.md](tasks/T406.md)参照）、続く改善計画T418（2026-08-30）で「評価軸」チップ
自体を地図UIから撤去し「道路/環境/スポット」の3分類になった
（[docs/tasks/T418.md](tasks/T418.md)参照）。評価軸（`car_stress`等の軸スタジオが作る全軸、
`windAxis`・`gradientAxis`）は、道路・環境・スポットと違い**ルートの状態と常に結び付いた道具**（ルート生成前は
重み配分を検討する材料、生成後は結果を分析する材料）であり、ルートの有無に関係なく意味が
一定な「地図そのものの見え方」設定として常設チップに置くこと自体が目的と合っていなかった、
という判断による。評価軸の色分けは、ルート未確定時はルート設定パネル
（`RouteSettingsPanel.tsx`、下記）の軸ごとの行から、ルート確定後は「生成したルートの色分け」
（`routeStyleModes.ts`）から、それぞれ起動する。

`mapLayers.ts: mapOverlayGroupFor()`が既存の`category`/`dataNature`フィールドから機械的に
導出する（道路=`category==="roadCondition"`、環境=`category==="terrain"||"weather"`、
スポット=`category==="trafficSafety"||"amenity"`）。軸スタジオ由来のレイヤー
（`isAxisStudioLayer()`、`dataNature==="composite"`のramp軸・way_id→動的値配信層
`windAxis`/`gradientAxis`）はcategory判定より先に除外され、地図上チップ・サイドバーのどちらにも一切現れない
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

**サイドバー（`MapLayersPanel.tsx`、「地図の見え方」パネル）の最上位グルーピング**は改善計画
T413（2026-08-30）で地図上チップと同じ`mapOverlayGroupFor`を単一ソースとして使うよう統一
済み（以前は独立した設計判断として`MapLayerDataNature`[観測/推定/動的]の2見出しを使って
いたが、この不整合を解消した）。T418の評価軸グループ撤去にもそのまま追従し、道路/環境/
スポットの3分類になっている。

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

### 区間インスペクタ（改善計画T146）

道路をクリックした際に「一次属性→取得可能な軸のみのスコア→参考合成コスト」を表示する
機能。`POST /api/region/axis-inspector`（§4参照）→`RegionService.get_axis_inspector`
→`domain/evaluation.py: axis_inspector_breakdown`（純関数）という「クリック時にサーバーへ
1回問い合わせ」パターンを採る（クライアント側での難易度式再実装はドリフトリスクがある
ため見送り。改善計画T292で本エンドポイントへ統合・廃止された旧車ストレス内訳ボタン
`POST /api/region/car-stress-breakdown`も同じパターンだった）。

`way_attribute_counts`（T145b、レジストリ駆動の二次軸ランプレイヤーと同じテーブル）から
その道路（Way）1本分の長さ・事故/停止/交差点カウントを取得し、car_stress・surface_q・
stop_density・accident・night・bicycle_infra_qualityの6軸（`AXIS_DEFINITIONS`の公開軸のうち
gradient/windを除く。bicycle_infra_qualityは正規化フラグ材料4件（改善計画T353）を直接参照するが、
これも単独wayのtags/highwayだけで算出可能なため引き続き対象に含まれる）を算出する。gradient・windは単独wayでは算出できない
（ルート文脈が必要）ため`AxisInspectorAxis.available=false`で常に返し、`composite_difficulty`は
取得できた軸だけの加重平均（`covered_weight_fraction`が全8軸重みに対する充足率を示す参考値）。

### 地図タイル閲覧起点の道路グラフ構築（T59）

上記のタイルは実際にはroad_nodes/road_edges（派生グラフ）を読むが、以前は`RouteGenerator`
（ルート生成）経由でしか構築されず、地図を眺めるだけの利用では永遠に空のままだった。
`RegionService`（[backend/app/services/region_service.py](../backend/app/services/region_service.py)）
がタイル配信のたびに、対象z12祖先タイルの道路グラフが未構築・古ければ
`GraphService.get_or_build_graph_with_attributes`をバックグラウンドタスク
（`asyncio.create_task`、応答は待たせず即座に返す）として起動する。実際の構築（closure再計算・
Edge全量再UPSERT）だけを`config.py: graph_build_max_concurrent`（既定1）で絞り、鮮度確認
（`is_split_up_to_date`）は絞らない（T59緊急修正: 無制限の同時構築がDBコネクションプールを
枯渇させ無関係な他タイル・API呼び出しまで502化した実障害への対応）。

---

## 9. Road Graph移行

経緯・フェーズ別の詳細は [decisions/road-graph-migration.md](decisions/road-graph-migration.md) へ移動した。
現状の要点:

- `/api/routes/generate`はRoad Graph＋scipy.sparse.csgraph Dijkstraの単一構成（改善計画T247で既定化、改善計画T462でopenrouteservice委譲・切替設定自体を完全撤去、1章「ルーティングエンジンの切り替え対応」参照）
- OSMデータはPBF取込バッチ（`app/batch/import_pbf.py`）でPostGISへ事前取込済みの範囲を第一系統とし、Overpassフォールバックは改善計画T22で撤去済み（取込範囲外は空タイル/データ未整備扱い。docs/osm-pbf-import.md、[decisions/pre-static-attributes-gate.md](decisions/pre-static-attributes-gate.md)参照）
- 永続化層の構造（生OSM層／派生グラフ／属性／表示用MVTの4リポジトリ＋ファサード、トランザクション境界の規約）は`infrastructure/road_graph_repository.py`のdocstring参照
