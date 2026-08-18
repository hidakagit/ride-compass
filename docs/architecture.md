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
| Backend | Python + FastAPI | pytest でロジックを単体テスト |
| DB | PostgreSQL + PostGIS | `road_graph_use_repository=true`のとき、PBF取込済みの生OSM層・Road Graph・路面タイル生成（ST_AsMVT）の第一系統として使用。Overpassフォールバックは改善計画T22で撤去済みのため、取込範囲外はOverpassへ問い合わせず「データ未整備」として扱う（`road_graph_use_repository=false`のときのみ、DBなし構成としてOverpassのみで動作する）。SQLAlchemy+GeoAlchemy2経由（`infrastructure/database.py`, `road_graph_models.py`, `road_graph_repository.py`）。dev環境はネイティブのPostgreSQL 18.6＋PostGIS 3.6.2（Windowsサービス）で実接続検証済み（[decisions/road-graph-migration.md](decisions/road-graph-migration.md)「実PostGISでの動作検証（Phase 0）」参照） |
| ルーティングエンジン（周回ルート生成、`/api/routes/generate`） | **切り替え可能**（既定: openrouteservice API、`config.py`の`routing_engine`設定で`road_graph`にも切替可） | 周回生成戦略は単一の`RouteGenerator`（[backend/app/services/route_generator.py](../backend/app/services/route_generator.py)）が持ち、経路計算・評価だけを`LoopRoutingEngine`ポート経由で`OpenRouteServiceEngine`（[backend/app/services/openrouteservice_engine.py](../backend/app/services/openrouteservice_engine.py)、外部APIキー方式、Road Graph移行前の実装）または`RoadGraphEngine`（[backend/app/services/road_graph_engine.py](../backend/app/services/road_graph_engine.py)、自前ホスト・外部APIキー不要、`GraphService`・`EvaluationService`・`domain/routing.py`のNetworkX Dijkstraを使う）へ委譲する。ルーティング自体（自前の経路探索）は将来拡張として開発を続ける一方、現状はマップの見える化・評価に必要な情報の精査を優先するため既定値はopenrouteservice。レスポンスの`engine`フィールドでどちらが生成したかを識別できる。詳細は「ルーティングエンジンの切り替え対応」および[decisions/road-graph-migration.md](decisions/road-graph-migration.md)参照 |
| ルーティングエンジン（単一区間確認、`/api/routes/preview`） | openrouteservice API（`cycling-road`プロファイル、外部APIキー方式） | Step3の疎通確認用エンドポイントは移行対象外のまま残置。`RoutingService`（[backend/app/services/routing_service.py](../backend/app/services/routing_service.py)）が`get_directions(waypoints: list[Coordinates])`を実装したクライアント（`ORSClient`）を受け取る形 |
| 地図タイル | OpenFreeMap（`https://tiles.openfreemap.org/styles/liberty`、APIキー不要） | `tile.openstreetmap.org` は bulk/非ブラウザアクセスをブロックするポリシーがあり不採用（後述）。Step10でバックエンド経由のプロキシ＋ファイルキャッシュ（`BasemapClient`）を追加 |
| 天候 | **Open-Meteo Forecast API**（APIキー不要） | `WeatherService`（[backend/app/services/weather_service.py](../backend/app/services/weather_service.py)）が`current`＋`hourly`をまとめて取得し、「地点＋時刻」で天候を引ける設計（後述）。周回ルート生成は8候補（方位）ぶんの風評価を並列実行するため、素朴には候補数ぶんのOpen-Meteo呼び出しがほぼ同時発火し本番の共有送信元IPで429が常態化する一因になっていた。`WeatherService.prefetch`/`WindService.prefetch`（[backend/app/services/wind_service.py](../backend/app/services/wind_service.py)）が候補間でサンプル点を合流させ、`get_forecast_many`のTTLキャッシュを先読みで温めることで、実質1リクエストへ集約する（`/api/debug/stats`の`error_types`/`last_error_type`等の診断情報拡張と併せて対応） |
| 標高 | **国土地理院（GSI）標高API**（APIキー不要、日本国内限定） | `ElevationService`（[backend/app/services/elevation_service.py](../backend/app/services/elevation_service.py)）がルートを距離連動の点数（約1km間隔・12〜32点、`sample_count_for_distance`）でサンプリングして問い合わせ、獲得標高・最高/最低標高・最大勾配を算出 |
| 標高（地域レイヤー） | **国土地理院 色別標高図**（ラスタタイル、`https://cyberjapandata.gsi.go.jp/xyz/relief/{z}/{x}/{y}.png`、APIキー不要） | `MapView.tsx`がMapLibreのraster sourceとして直接重ね描き。バックエンドAPIを介さない。候補ルートに紐づかない「地域全体」の標高表示用で、Step5の標高API（点ごとの数値取得）とは別用途 |
| 路面（地域レイヤー） | **PostGIS**（`ST_AsMVT`、`road_graph_use_repository=true`時）／DBなし構成では常に空タイル | `RegionService`（[backend/app/services/region_service.py](../backend/app/services/region_service.py)）が候補ルートに紐づかない「地域全体」の路面レイヤーを提供する。PBF取込済み範囲はPostGIS側（`road_graph_repository.py`の`_ROAD_SURFACE_TILE_MVT_SQL`）でMVT生成まで完結し、取込範囲外・DB障害・DBなし構成は空タイル（`infrastructure/vector_tile.py: encode_empty_road_surface_tile`）を返す。Overpass APIによる取得は改善計画T22で撤去済み（当初はOverpass API＋自前Python MVTエンコードだったが、PostGIS移行に伴い不要になった。経緯は[decisions/pre-static-attributes-gate.md](decisions/pre-static-attributes-gate.md)参照） |

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
- **タイルプロパティを削除する変更のデプロイ順序に注意**: backend・frontendはRender上で別サービスとして独立にデプロイされ、反映タイミングは同期しない。road-surface-tilesのプロパティ追加（v2〜v8）は常に後方互換だった（旧フロントは新プロパティを単に無視するだけ）が、v9（交通ストレスレシピ外出し基盤）は計算済みの`traffic_stress`プロパティを削除する初めての非互換変更。backendがv9を先に配信すると、まだ`["!", ["has","traffic_stress"]]`を使う旧フロントの凡例フィルタが全地物に一致し、交通ストレスレイヤーが全線「不明・他」（グレー）表示になる（数分〜デプロイ完了まで自己解消するが、その間は誤った見た目になる）。**frontendを先に（または同時に）デプロイし、backendのv9切替がfrontendの新実装より先に本番へ出ないようにする**こと。

### 周回ルート生成のアルゴリズムと既知の制約（Step4）
`RouteGenerator`＋`OpenRouteServiceEngine`（[backend/app/services/route_generator.py](../backend/app/services/route_generator.py)・[backend/app/services/openrouteservice_engine.py](../backend/app/services/openrouteservice_engine.py)、Step4当時は`route_generator.py`という単一ファイルだったが「ルーティングエンジンの切り替え対応」で戦略とエンジンに分離した）は、8方位それぞれについて「方位θの方向に半径R」「方位θ+45°の方向に半径R」の2経由地点を`domain/geo.py`の`destination_point`（球面三角法）で計算し、`[現在地, 経由地A, 経由地B, 現在地]`をopenrouteservice Directions APIに1回のリクエストで渡す。半径Rは`distance_km / 3`という固定ヒューリスティック。8方位分は`asyncio.gather`で並列実行し、失敗した方位はスキップする。

実機検証（王子駅付近、15km/30km指定）では8方位すべてが成功し、目標距離に対して+10〜+16%程度（許容差±5km以内）に収まった。ただし適応的な半径調整は行っていないため、道路網の形状次第では大きくずれる方位が出る可能性がある。将来の改善点:
- 半径を反復調整して目標距離に近づける適応的探索
- `distance_tolerance_km`のデフォルト値を、実データが蓄積された段階で仕様書どおりの±2km程度まで狭める
- 8方位に加え、方位内で複数の経由地点パターンを試す（候補数を増やす）

### 標高計算のアルゴリズムと既知の制約（Step5）
`ElevationService`（[backend/app/services/elevation_service.py](../backend/app/services/elevation_service.py)）は、各ルートのGeoJSON LineStringから始点・終点を含む点列（当初は12点固定。現在はエンジンが`sample_count_for_distance`で距離連動の約1km間隔・12〜32点を決めて渡す。Step9で点列を直接受け取るシグネチャへ変更）をサンプリングし、国土地理院の標高API（1リクエスト=1地点）に問い合わせる。獲得標高は連続区間の正の標高差の合計、最大勾配は`|標高差| / 水平距離`の最大値（%、水平距離は`haversine_distance_km`で算出）。標高が取得できない区間（海上・データ範囲外・通信エラー）は`None`として扱い、有効な点が2点未満なら標高関連フィールドはすべて`None`を返す（ルート自体は除外しない）。

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
Step6で`WeatherService.get_conditions(point, at: datetime | None = None)`を「地点＋時刻」対応にしておいたのは、まさにこのStep7のため。`WindService`（[backend/app/services/wind_service.py](../backend/app/services/wind_service.py)）は候補ルートのサンプル点列（`ElevationService`と同じ点集合。当初12点固定、現在は距離連動の約1km間隔・12〜32点）について、区間ごとに以下を行う。

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

**（後日追加: 改善計画T21・2026-08-15で撤去）** ここまでに書いたopenrouteservice `extra_info=surface`・`RouteSegment.surface_summary`・`paved_percent`は、評価のエンジン非依存化（後述「ルーティングエンジンの切り替え対応」）に伴い撤去済み。`road_score`は現在、両エンジンとも`domain/road.py`の`classify_osm_surface`（OSMタグ語彙）と`distance_weighted_road_score`（距離加重集計、共通関数）で算出する。ORSエンジンはサンプル点を`RoadGraphRepository.get_nearest_surface_tags`で自前DBのEdgeへ空間マッチしてタグを読む（詳細は後述）。

### 候補ルートの難易度可視化の設計（Step9）
`total_score`は候補集合内の相対評価のため、数値だけでは「具体的にどこが走りにくいのか」が分からない。ユーザーからの要望で、候補選択時に地図上へ標高・風・路面を時系列（区間ごとの推定到達時刻）も考慮したレイヤーとして重ね描きし、走破の易しい/難しい区間を色分けする機能を追加した。

- **データ取得方針**: Step5-7-8で候補ごとに12点サンプリングして取得していた標高・風・路面の生データは、集約値（`elevation_gain_m`等）だけを残して区間ごとの詳細を捨てていた。Step9はこれを**捨てずに`RouteCandidate.segments`として返す**だけで実現しており、追加のAPIコール（GSI/Open-Meteo/openrouteservice）は一切発生しない。
- **サンプル点の共有化**: `ElevationService.get_profile`と`WindService.get_wind_score`はそれぞれ独立に`sample_line_coordinates`を呼んでいたが、区間ごとの標高・風・路面を1つの配列としてインデックス整合させるため、`route_generator.py`が`sample_line_points(geometry, SAMPLE_COUNT)`（新規、`domain/geo.py`。座標だけでなく元geometry内でのインデックスも返す）で一度だけ点を取得し、両サービスに共有するようリファクタした。シグネチャも`get_profile(points)` / `get_wind_profile(points, start_time)`に変更（`geometry`ではなく点列を直接受け取る）。
- **路面の位置対応（2026-08-15、改善計画T21で撤去・置換）**: 当初はopenrouteserviceの`extras.surface.values`（`[[start_idx, end_idx, surface_id], ...]`）を`RouteSegment.surface_values`として保持し`surface_id_at_index`で求めていたが、現在はサンプル点を`RoadGraphRepository.get_nearest_surface_tags`で自前DBのEdgeへ空間マッチして`classify_osm_surface`で判定する方式に統一済み（後述「ルーティングエンジンの切り替え対応」）。
- **難易度の算出（絶対基準）**: `domain/difficulty.py`が、Step8の相対正規化とは異なり**絶対基準**（一般的なロードバイク走行の目安）で0-100点化する。`gradient_difficulty`（0-3%易しい〜9%以上激坂の区分的線形）、`wind_difficulty`（向かい風0-8m/sで0→100、追い風・無風は0）、`road_difficulty`（舗装路0・非舗装80、`domain/road.py`の`GOOD_SURFACE_IDS`と基準を統一）、`composite_difficulty`（重み付き平均、`None`の指標は除外して残りの重みで再正規化、`RouteScorer`と同じ考え方）。重みはStep8の`scoring.yaml`から`distance_weight`を除いた`elevation_weight`/`wind_weight`/`road_weight`をそのまま流用し、スコアリングの優先度と可視化の強調点を一致させている。地図の色分けは「候補間の相対比較」ではなく「客観的にどこが大変か」を示す目的のため、Step8のような候補集合内正規化ではなく絶対基準を採用した。
- **`RouteSegmentDetail`**（`domain/route.py`、`RouteCandidate.segments`）: 区間の始点/終点座標・累積距離・推定到達時刻に加え、表示用の生値（`gradient_percent`, `wind_penalty`, `road_surface_good`）と正規化済みの`*_difficulty`（`elevation_difficulty`, `wind_difficulty`, `road_difficulty`, 総合の`difficulty`）を両方保持する。正規化済みの値をフロントに渡すことで、閾値ロジックをフロント側に複製せず、UIは常に「0-100→緑〜赤」の単一の色変換関数だけで済む。
- **フロントエンド**（当初実装）: 選択中候補に`segments`があれば区間ごとの色分けレイヤーを追加し、モード切替ボタン（総合難易度/標高/風/路面）で`line-color`を切り替える形にした。この設計は後述のUI再構成でレイヤー構成ごと見直している。

既知の制約と改善（区間表示の粒度・形状）: 当初はサンプリング密度が12点固定（＝11区間、Step5-7と同じ）で、30kmルートでは1区間約2.7kmと粗く、さらに区間の線は始点・終点を直線で結んでいたためカーブ区間で色分け線が道路から外れていた。「区間が荒すぎて実態が分からない」というフィードバックを受け、次の2点を改善した（2026-08-15）: ①**区間の道なり形状**: `RouteSegmentDetail.geometry`にルートgeometryの部分列（サンプル点インデックスで切り出し。road_graphエンジンはEdge形状点列）を持たせ、フロントはそれをそのまま描画する（追加APIコール無し。geometryがnullの場合のみ従来の直線代替）。②**距離連動サンプリング**: `sample_count_for_distance`（openrouteservice_engine.py）が約1km間隔になるよう点数を決める（下限12点=従来密度、上限32点=外部API問い合わせの安全弁。最悪でも8候補×32点=256 GSIリクエスト/生成。風はTTL＋座標丸めキャッシュにより点数増の影響がほぼ無い）。密度をさらに上げる場合はGSI問い合わせ数とのトレードオフになる（DEMタイル化T10が根本対策）。

### UI再構成: サイドバー＋地図レイヤーの静的/動的分離
Step9の可視化はモード切替（総合難易度/標高/風/路面のいずれか1つ）＋選択中候補のみという設計だったが、ユーザーから「データの性質（時間で変わる/変わらない）によって持ち方・見せ方を分けたい」「左に操作パネル、右に地図」という要望を受け、UIを再構成した。

- **レイアウト**（[frontend/src/app/page.tsx](../frontend/src/app/page.tsx)）: `display:flex; height:100vh`のルート要素の下に、折りたたみ可能な`<aside>`（左サイドバー: タイトル・`WeatherPanel`・`LocationControl`・`MapLayersPanel`・`RouteForm`・`RouteList`・`BackendStatus`等）と`flex:1`の地図ペイン（`MapView`＋地図上の`MapOverlayControls`）を並べる。位置情報（現在地取得・手動入力）の状態は`MapView`から`page.tsx`（`Home`）に引き上げ、`MapView`は`location`等をpropsで受け取る「地図描画に専念する」薄いコンポーネントにした。
- **レイヤー構成の分離**（[frontend/src/components/Map/MapView.tsx](../frontend/src/components/Map/MapView.tsx)）: 4種類のMapLibreレイヤーを常設する構成に変更。
  1. `route-candidates-line`（既存）: 全候補のベース表示（amber未選択/blue選択）。`staticLayer==="none"`のときのみ表示。
  2. `route-static-segments-line`（新規）: **全候補**のセグメントを`elevation_difficulty`/`road_difficulty`で色分け。選択に関わらず常時利用可能（`MapOverlayControls`のチェックボックスでON/OFF）。
  3. `route-selected-outline-line`（新規）: 選択中候補の全体ジオメトリを太め・低不透明度のハローで最背面に描画し、①②のどちらの表示中でも選択中候補を常時識別できるようにする。
  4. `route-detail-segments-line`（既存を単純化）: 選択中候補のみ、色分けモード（`routeStyleModes.ts`: 風の影響=`wind_difficulty`／勾配=`gradient_percent`／路面=`road_surface_good`／総合難易度=`difficulty`。いずれも`segments`に返却済みの値のみ使い追加取得なし）で色分け。ルートレイヤーがONかつ選択中候補にセグメントがある場合のみ表示（一時期は風のみに絞っていたが、その後勾配を追加し、研究インターフェース改善 §10-5で路面・総合難易度も追加した）。
  - ①②は`visibility`レイアウトプロパティで排他的に切り替え、③は常時、④は最前面。クリック/ホバーの`queryRenderedFeatures`は②④の両方を対象にし、②のポップアップには所属候補が分かるよう`direction_label`を付与している。
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

### ルーティングエンジンの切り替え対応（openrouteservice ⇄ Road Graph）
「Road Graphを実際のルーティングへ接続する移行（完全移行）」で`/api/routes/generate`をopenrouteservice委譲からRoad Graph + NetworkX（Dijkstra）ベースへ全面置き換えたが、Road Graphの経路探索自体（ルーティングエンジンとしての精度・速度）はまだ発展途上で、今後も継続して手を入れる将来拡張と位置付けている。一方で、標高・風・路面といった「評価に必要な情報」の取得方法や地図上の見える化は、経路探索エンジンがどちらであっても検証を進めたい。そのため、経路探索エンジンを設定で切り替えられるようにし、openrouteservice委譲（外部APIキーのみで動く、枯れた実装）を使いながら評価まわりの精査を進められるようにした。

- **戦略（共通）とエンジン（差し替え可能）の分離**: 当初は「2つの`generate_loops`実装を丸ごと並行して残す」形で切り替えを導入したが、8方位・半径ヒューリスティック・距離許容フィルタ・`RouteScorer`適用・ソートという周回生成戦略が二重化し、仕様書5章の将来拡張（適応的半径調整・候補地点選定の改善等）を2回ずつ実装することになるため、直後の設計レビュー（後述）でポート分割へリファクタリングした。現在の構造:
  - **`RouteGenerator`**（[backend/app/services/route_generator.py](../backend/app/services/route_generator.py)、戦略層・単一実装）: 経由地点の計算（`destination_point`）、8方位分の`trace_loop`並列実行、距離許容範囲フィルタ、`RouteScorer`によるtotal_score付与・ソートを持つ。エンジンには`LoopRoutingEngine`（Protocol）として`prepare`（リクエスト単位の共有準備）／`trace_loop`（1方位分の経路と距離）／`evaluate_loops`（**距離フィルタ通過後の候補だけ**への標高・風・路面評価）の3段階で委譲する。評価を後段に分離しているのは、棄却済み候補への外部API問い合わせ（GSI標高等）を避けるため（旧openrouteservice版が持っていたクォータ節約の挙動を両エンジン共通の戦略として保証する形。Road Graph版は従来フィルタ前に標高を取得していたが、この分割でフィルタ後のみになった）
  - **`OpenRouteServiceEngine`**（[backend/app/services/openrouteservice_engine.py](../backend/app/services/openrouteservice_engine.py)）: 経路はopenrouteservice Directions API（`RoutingService`/`ORSClient`）へ1方位1リクエストで委譲し、評価は復元した`ElevationService`（距離連動サンプリング、約1km間隔・12〜32点）・`WindService`（区間ごとの推定到達時刻の風）で行う
  - **`RoadGraphEngine`**（[backend/app/services/road_graph_engine.py](../backend/app/services/road_graph_engine.py)）: `prepare`でRoad Graphを1回だけ取得しEdge Cost・NetworkXグラフ・起点スナップ・出発時点の風を構築、`trace_loop`でDijkstra探索、`evaluate_loops`で経路上のEdgeだけに標高を取得する（完全移行時の実機検証で判明した性能問題への対応をポート3段階へ対応付けた形）
- **`domain/geo.py`のサンプリング関数も復元**: `sample_indices`/`sample_line_coordinates`/`sample_line_points`（`geo.py`）は、完全移行で「Road Graphエンジンからは参照されなくなった」という理由で削除されていたが、`OpenRouteServiceEngine`が引き続き必要とするため復元した。
- **路面判定は1系統へ統一済み（2026-08-15、改善計画T21）**: 導入当初は`GOOD_SURFACE_IDS`/`paved_percent`/`surface_id_at_index`/`is_good_surface`（openrouteserviceの数値ID基準）と`classify_osm_surface`（OSMタグ基準、RoadGraphEngine用）の2系統が併存していたが、`decisions/pre-static-attributes-gate.md`（決定1）に基づき、ORSエンジンのサンプル点を`RoadGraphRepository.get_nearest_surface_tags`（PostGIS KNN、スナップ半径`SURFACE_MATCH_MAX_DISTANCE_M=30m`）で自前DBのEdgeへ空間マッチしてOSMタグを読む方式へ統一した。前者4関数は削除済み。両エンジンとも`classify_osm_surface`＋距離加重集計`distance_weighted_road_score`（`domain/road.py`、Edge/サンプル区間どちらの距離単位でも使える共通関数）を使う。`settings.road_graph_use_repository=false`（DBなしプロファイル）では空間マッチ自体を行わず、ORSエンジンの路面評価は全区間`None`になる。
- **設定と既定値**: `config.py`に`routing_engine: Literal["openrouteservice", "road_graph"]`を追加した（`.env`の`ROUTING_ENGINE`で上書き可）。現状はマップの見える化・評価情報の精査を優先するという方針に合わせ、既定値は`openrouteservice`にした（Road Graphエンジンを使うには`.env`で明示的に`road_graph`を指定する）。
- **DI（`api/dependencies.py`の`get_route_generation_builder`）**: `settings.routing_engine`の値に応じてどちらのエンジンを構築し`RouteGenerator`へ渡すかを切り替える。両エンジン分の依存を`Depends`パラメータとして宣言しているため、FastAPIの制約上、実際には使わない側の依存（`httpx.AsyncClient`等、いずれもこの時点では実I/Oを伴わない軽量なオブジェクト）も毎リクエスト構築されるが、条件分岐に応じて一部の`Depends`だけを解決する簡便な方法が無いため単純さを優先した（コード上のコメント参照）。研究インターフェース改善Phase 1（T23）で、`RouteGenerator`本体ではなくビルダーを返す形へ再構成し、エンドポイントが検証済みの重み上書き（無ければYAML既定値）を渡して組み立てを完了する（5章「評価重みのリクエスト上書きと評価モデル研究時の構成」参照）。
- **`/api/routes/preview`は無変更**: Step3の疎通確認用エンドポイントは元々`RoutingService`/`ORSClient`を直接使っており、今回のエンジン切り替えの対象外（従来通りopenrouteserviceのみ）。

#### 設計レビュー（エンジン切り替え後）と対応した推奨アクション

エンジン切り替え導入直後に仕様書・実装・将来拡張の観点で設計レビューを実施し、優先度上位4件を実装した。

1. **評価値の定義統一＋`engine`フィールド（レビュー指摘H2）**: エンジン間で同じフィールド名の数値の意味が食い違っていた3点のうち2点を統一した。
   - **road_scoreの不明路面の扱い**: openrouteservice数値ID版`paved_percent`は不明を分母に含めて実質減点していたが、OSMタグ版（`classify_osm_surface`ベースの距離加重集計）と同じ「**不明は分母から除外**（不明≠悪い路面）、全区間不明ならNone」へ統一した。あわせて`is_good_surface`もID 0（Unknown）を`False`ではなく`None`（判定不能）へ変更し、両語彙の3値判定（良い/悪い/不明）の意味を揃えた（`domain/road.py`冒頭の「正準定義」コメント参照）
   - **区間難易度（`segments[].difficulty`）の合成重み**: openrouteservice版は`scoring.yaml`（候補集合内の相対評価用）を流用しており、`route_preference.yaml`を使うRoad Graph版と地図の色分けが食い違っていた。**両エンジンとも`route_preference.yaml`（Edge単位の絶対評価用の重み）へ統一**した。`scoring.yaml`はルート単位のtotal_score専用となり、役割の境界が明確になった（副次効果として、旧openrouteservice版がリクエストごとに行っていた`load_scoring_weights()`のファイルI/Oも除去された）
   - **区間勾配（`segments[].gradient_percent`）の符号**（後日追加: 2026-08-15の全体設計レビューB1で発覚）: openrouteservice版は絶対値で返しており（下り坂が登り扱いになり、フロントの勾配色分けの「下り」カテゴリが既定エンジンで一度も表示されない）、Road Graph版の符号付き`average_grade`と食い違っていた。**両エンジンとも符号付き（進行方向基準、登り=正/下り=負）へ統一**した（`domain/route.py`: `RouteSegmentDetail`の正準定義参照。難易度への変換は`gradient_difficulty`が絶対値を取るため影響なし）
   - **wind_scoreの意味の違いは意図的に残す**: openrouteservice版は区間ごとの推定到達時刻の風（時間変化あり）、Road Graph版は出発時点の風の一様適用（探索中は到達時刻が未確定という制約）。将来の時間展開対応まで統一できないため、レスポンスに**`engine`フィールド**（`RouteGenerateResponse.engine`、フロントの`types/route.ts`にも追加しデバッグログに出力）を追加し、どちらの定義の数値かを識別可能にした
2. **`/api/routes/generate`のレート制限・同時実行ガード（レビュー指摘H3)**: 最も高コストなエンドポイント（openrouteservice: 外部APIクォータ消費 / road_graph: コールド時40〜70秒＋Overpass/GSI大量問い合わせ）が無防備だったため、既存の`check_rate_limit`によるper-IP上限（`GENERATE_RATE_LIMIT_PER_MINUTE = 10`/分）と、プロセス全体の同時実行数上限（`GENERATE_MAX_CONCURRENT = 2`、`asyncio.Semaphore`）を追加した。上限超過は待たせず429で即座に返す（ブラウザのリトライ・連打による外部サービスへの負荷の積み上げ防止）
3. **`ORSClient`のコネクション共有（レビュー指摘M1）**: 呼び出しごとに新規`httpx.AsyncClient`を生成していた（8方位の周回生成でTLSハンドシェイク8回。`ElevationClient`で実測57秒→7秒の差を生んだのと同じパターン）ため、他のクライアントと同様にDI（`get_routing_service`）が生成する共有コネクションのコンストラクタ注入へ統一した
4. **ポート分割（レビュー指摘H1）**: 前述の「戦略（共通）とエンジン（差し替え可能）の分離」

レビューで指摘されたが今回は見送った項目（既知の課題として記録）:
- **Road Graph版の`segments`肥大化（M3）**: Edge=区間のため4kmで150〜230区間、30km×8候補では数千区間になりペイロード・描画コストが嵩む。表示用の集約（約500m単位のビン化等）をAPI境界で行う案
- **周回品質（M4）**: 両エンジンとも「行きと帰りが同じ道」の往復型周回を防ぐ仕組みが無い。Road Graph版は「前の脚で使ったEdgeのコストを一時的に引き上げる」ことで自前修正でき、自前エンジンの差別化ポイントになりうる
- **`find_nearest_node`の距離上限が無い（M5）**: 起点が道路網から極端に遠い場合も最近傍Nodeへ黙ってスナップする
- ~~`RoutingService`へのORS固有パース漏れ（M2）~~: **解消済み（2026-08-15、改善計画T21）**。`properties.extras.surface`のパース自体を撤去した（路面評価が自前DB空間マッチへ統一されたため、ORS側のextra_infoが不要になった）
- **`WeatherService.get_conditions(at=...)`のhourly範囲外ガード未実装（L3）**: openrouteservice版が既定へ戻ったことで実使用中の既知制約となった（20km/h想定の周回では実害はほぼ無い）

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
      config.py               ✅ pydantic-settings（.env読込、basemap_public_base_url含む）。routing_engine（"openrouteservice" | "road_graph"、既定openrouteservice）を「ルーティングエンジンの切り替え対応」で追加。render_git_commit（Render自動注入のRENDER_GIT_COMMIT、ローカルはnull）を「Renderデプロイの反映確認」で追加
      version.py               ✅ STARTED_AT（プロセス起動時刻、インポート時に一度だけ評価）。/healthのデプロイ確認用（「Renderデプロイの反映確認」で新規）
      api/
        dependencies.py        ✅ DI工場（get_route_generator等のDependsファクトリ）とclient_id（per-IPレート制限キー）。旧routes.pyの分割（改善計画T5）
        routers/               ✅ エンドポイント群（main.pyはrouters/__init__.pyのapi_routerをinclude）。health.py（GET /health, GET /api/debug/stats）/ routes.py（POST /api/routes/preview, POST /api/routes/generate。per-IPレート制限＋同時実行数ガード付き）/ weather.py（GET /api/weather）/ region.py（GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf）/ basemap.py（GET /api/basemap/{path}, POST /api/basemap/refresh）。レート制限・同時実行の上限値はconfig.pyのSettingsへ外部化済み（.envで上書き可）
      domain/
        route.py               ✅ Coordinates, RouteSegment, RouteSegmentDetail（Step9）, RouteCandidate（標高・wind_score・road_score・total_score・segments含む）
        weather.py               ✅ WeatherConditions
        errors.py               ✅ RoutingError
        geo.py                   ✅ destination_point, haversine_distance_km, sample_indices, sample_line_coordinates, sample_line_points, compass_label, bearing_between
        road.py                   ✅ classify_osm_surface, GOOD_OSM_SURFACE_TAGS, BAD_OSM_SURFACE_TAGS（両エンジン共通の唯一の路面判定語彙）, distance_weighted_road_score（距離加重集計、改善計画T21で両エンジン共通化）
        scoring.py               ✅ normalize_min_max（Step8）
        difficulty.py             ✅ gradient_difficulty, wind_difficulty, road_difficulty, composite_difficulty（Step9）
        wind.py                   ✅ WindCalculator.wind_penalty（Step7）
        region.py                 ✅ BoundingBox, tile_bounds_lonlat, ROAD_TILE_MIN_ZOOM/MAX_ZOOM（Step10改訂。標高グリッド・snap_cells・bbox対角距離関連は撤去済み）。ROAD_GRAPH_TILE_ZOOM, tiles_covering_bbox（Road Graphのタイル単位キャッシュ用、新規）
        graph.py                    ✅ Node, DirectedEdge, RoadGraph, WaySpec, build_road_graph（Road Graph移行Phase 1、新規。Phase 2でOSMタグ解釈を分離しWaySpec契約に一本化。Phase 3でWaySpec.surfaceを追加）
        osm_adapter.py               ✅ OSM Way（tags辞書）→WaySpecへの変換（Road Graph移行Phase 2、新規。OSM Adapter/Importer）
        attributes.py                 ✅ ElevationAttribute, SurfaceAttribute, compute_elevation_attribute, build_surface_attributes（Road Graph移行Phase 3、新規）
        recipe.py                      ✅ 改善計画T122: レシピ付き軸（traffic.py/safety.py）が共有する判定プリミティブ。clamp_level/threshold_adjustment/cycleway_adjustment/flag_adjustment/tag_value_is/validate_threshold_order、材料タグ正規化（parse_lanes/parse_maxspeed/cycleway_values/cycleway_class、traffic.pyから移設）
        traffic.py                     ✅ 静的道路属性P1: classify_stop_poi/classify_bicycle_infrastructure/car_stress_level（highway,tags,is_designated、改善計画T150で「交通ストレス」から改称）/distance_weighted_stop_density/distance_weighted_intersection_density/distance_weighted_bicycle_infra_score、STOP_POI_MATCH_MAX_DISTANCE_M/INTERSECTION_MATCH_MAX_DISTANCE_M/INTERSECTION_DEGREE_THRESHOLD（7章参照）。判定プリミティブはrecipe.pyへ切り出し済み（改善計画T122）。classify_supply_poi（コンビニ・自販機・トイレ・給水・駐輪場、改善計画T101、表示専用でEdge Costには組み込まない）も同ファイル
        accident.py                     ✅ 外部静的データソースT50: ACCIDENT_MATCH_MAX_DISTANCE_M, KANTO_PREFECTURE_CODES（NPA採番）, ACCIDENT_FATAL_WEIGHT, distance_weighted_accident_density（7章参照）
        designation.py                   ✅ 外部静的データソースT51: DESIGNATION_BUFFER_WIDTH_M/DESIGNATION_MATCH_MIN_RATIO/DESIGNATION_IMPORT_KINDS/CAR_STRESS_DESIGNATION_KINDS（7章参照）
        safety.py                        ✅ 改善計画: 安全度レシピ: SafetyRecipe/DEFAULT_SAFETY_RECIPE, safety_breakdown/safety_level/safety_tile_ingredients（7章参照）
        evaluation.py                  ✅ RoutePreference（7軸の重み、7章参照）, EdgeCostResult, is_edge_allowed, compute_edge_cost（Road Graph移行Phase 4、新規。Evaluation Engine）。compute_wind_penaltyを「完全移行」（Phase 6・Dynamic Data対応）で追加
        difficulty.py                    ✅ AxisDifficulties（7軸）, evaluate_axis_difficulties, accident_difficulty/gradient_difficulty等の軸別difficulty関数（Step9で標高/風/路面のみ導入、P1/T50/T138/T139/T149で7軸へ再編。7章参照）
        night.py                         ✅ 改善計画T139: night_difficulty（街灯なし・トンネルの難易度変換、7章参照）
        routing.py                     ✅ build_networkx_graph, find_nearest_node, shortest_path_node_ids, path_to_edge_ids, concat_node_paths（「完全移行」で新規。Route Engine、NetworkXのDijkstraをラップ）
      services/
        routing_service.py     ✅ ORSClient等をラップ（waypointsリスト対応）。`/api/routes/preview`専用に加え、`routing_engine=="openrouteservice"`のときは`OpenRouteServiceEngine`からも使われる
        route_generator.py     ✅ `RouteGenerator`（周回生成戦略、エンジン非依存）＋`LoopRoutingEngine`（Protocol）＋`TracedLoop`。8方位・距離許容フィルタ・RouteScorer適用を単一実装で持ち、経路計算・評価はエンジンへ委譲（設計レビュー対応でポート分割）
        openrouteservice_engine.py ✅ `OpenRouteServiceEngine`。経路はRoutingService（openrouteservice委譲）、標高・風はElevationService+WindService（ルート単位の距離連動サンプリング、約1km間隔・12〜32点＝`sample_count_for_distance`）、路面は同じサンプル点を`RoadGraphRepository.get_nearest_surface_tags`（`repository`未注入時はNone、改善計画T21）で自前DBのEdgeへ空間マッチして評価するエンジン（Road Graph移行前の実装をポート化）。segmentsにはルートgeometryから切り出した区間の道なり形状を付与
        road_graph_engine.py   ✅ `RoadGraphEngine`。Road Graph + Evaluation Engine + Route Engine（domain/routing.py）で経路・評価を行うエンジン（「完全移行」の実装をポート化。prepareでRoad Graph1回取得、evaluate_loopsで経路上Edgeのみ標高取得）
        elevation_service.py    ✅ エンジンから渡されたサンプル点列（距離連動、約1km間隔・12〜32点）についてGSI標高APIで獲得標高・最高/最低標高・最大勾配を算出（Step5。「完全移行」でRoad Graphエンジンからは不要になり一度削除、「ルーティングエンジンの切り替え対応」で`OpenRouteServiceEngine`用に復元）
        wind_service.py         ✅ ルートのサンプル点ごとに推定到達時刻の風からwind_penalty/wind_scoreを算出（Step7。elevation_service.pyと同じ経緯で削除→復元）
        weather_service.py     ✅ 「地点＋時刻」で天候を取得（Step6）。RoadGraphEngineからは出発時点・起点付近の風を取得する用途で（「完全移行」）、OpenRouteServiceEngineからはWindService経由で区間ごとの推定到達時刻の風を取得する用途で、それぞれ呼ばれる
        route_scorer.py            ✅ 4指標を正規化・重み付け合成しtotal_scoreを算出（Step8）。「完全移行」後もRoad Graphベースの候補に対しそのまま再利用
        region_service.py          ✅ get_road_surface_tile(z,x,y)で路面ベクタタイル(PBF)を生成・tile_cacheに永続化（Step10改訂。標高はGSIラスタタイルとしてフロントエンドが直接取得するためバックエンドを介さない）。get_poi_tile(z,x,y)で停止要因POI・交差点密度の点タイルを生成（T54）。カバレッジ内タイル配信のたびにz12祖先タイルの道路グラフ未構築・古さを確認しバックグラウンド構築を起動（T59、7章参照）
        accident_service.py          ✅ 事故点のタイル生成（accident_repository.py経由）。region_service.pyとは別系統（外部静的データソースT50、7章参照）
        graph_service.py            ✅ GraphService.build_graph_with_surface_tags_for_bbox(bbox)でOverpass取得+Road Graph構築を統合（Road Graph移行Phase 1〜3、新規）。「完全移行」でRouteGeneratorから実際に参照されるようになった
        elevation_attribute_service.py ✅ ElevationAttributeService.get_attributes_for_graph(graph)でEdge単位の標高属性（形状点をGSI APIへ問い合わせ）を算出（Road Graph移行Phase 3、新規）。「完全移行」でRouteGeneratorから、確定した経路上のEdgeだけに絞って呼ばれるようになった（性能上の理由、decisions/road-graph-migration.md参照）
        evaluation_service.py           ✅ EvaluationService.evaluate_graph(graph, elevation_attributes, surface_attributes, wind=None)でEdge Costを算出（Road Graph移行Phase 4、新規。Phase 5でload_route_preference()を追加。「完全移行」でwind引数を追加しRouteGeneratorから参照されるようになった）
      infrastructure/
        ors_client.py           ✅ openrouteservice Directions API（cycling-road、複数経由地対応。`extra_info=surface`は改善計画T21で撤去済み、路面評価は自前DB空間マッチへ統一）
        elevation_client.py     ✅ 国土地理院標高API（共有コネクション＋緯度経度メモ化キャッシュ）
        weather_client.py       ✅ Open-Meteo Forecast API（current+hourlyをまとめて取得、TTLキャッシュ）
        overpass_client.py         ✅ Overpass API。`get_ways_and_nodes`（Way/Node IDを保持したトポロジー取得、Road Graph構築専用）のみ保持。地域路面レイヤー用の`get_roads`は改善計画T22でOverpassフォールバックとともに削除済み（`GraphService`の`repository`未接続時＝DBなし構成でのみ使う）
        vector_tile.py               ✅ 路面データをMVT（Mapbox Vector Tile）にエンコード（Web Mercator投影、Step10改訂）
        cache_db.py                 ✅ SQLite永続キャッシュ（標高のみ、Step5用。路面セルのキャッシュはStep10改訂でtile_cache.pyに統合し削除）
        tile_cache.py               ✅ 地図タイル・路面ベクタタイル共通のファイルキャッシュ（パスをSHA-256でフラット化、Step10）
        basemap_client.py           ✅ OpenFreeMapタイル/スタイルJSONのプロキシ＋URL書き換え（Step10）
        rate_limiter.py              ✅ プロセス内メモリのみの固定窓レート制限（`check_rate_limit`）。認証なしで叩ける`/api/region/road-surface-tiles/*`（120req/min）・`/api/basemap/*`（300req/min）に`api/routes.py`から適用し、超過時は429を返す
        debug_log.py                  ✅ `log_external_call`（contextmanager）。外部API呼び出し・タイルキャッシュアクセスの開始/完了/失敗をカテゴリ単位でDEBUGログに出力する。`settings.debug_mode`（`main.py`のlogging設定）がFalseの間は実質無出力
        database.py                  ✅ SQLAlchemy非同期エンジン・セッションファクトリ（Road Graph移行「永続化」、新規。DB未接続でも既存機能に影響なし）
        migrate.py                   ✅ 最小マイグレーション機構（`apply_pending_migrations`。改善計画T17、decisions/pre-static-attributes-gate.md 決定3）。`../migrations/`配下の番号付きSQLを`schema_migrations`テーブルで適用管理する。`create_tables`（新規DB向けの基本スキーマのみ）とは役割分離
        road_graph_models.py         ✅ road_nodes/road_edges/elevation_attributes/surface_attributesのSQLAlchemy ORMモデル（PostGIS Geometry型、Road Graph移行「永続化」、新規）。OsmRawNodeRow/OsmRawWayRow（生OSMデータ、配列型+GINインデックス）を「根本修正」で追加
        road_graph_repository.py     ✅ 責務別4リポジトリ＋ファサード（改善計画T6で分割）: RawOsmRepository（生OSM層・タイルマーカー）/ DerivedGraphRepository（road_nodes/edges・split_at鮮度判定）/ AttributeRepository（標高・路面属性）/ RoadSurfaceTileQuery（表示用MVT）/ RoadGraphRepository（既存公開APIを保つファサード、DI注入点）。**書き込みメソッドはcommitせず、サービス層が操作のまとまりごとにcommit()を呼ぶ規約**（トランザクション境界の詳細はモジュールdocstring参照）。save_raw_ways/get_way_specs_with_closureは「根本修正」で追加、save_graphはway_ids_to_replaceによるdelete-then-reinsert対応
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
    scripts/                    ✅ 単発実行の検証・計測スクリプト群（`.venv\Scripts\python.exe scripts\<module>.py`で実行、batch/と違いDB書き込みを伴わない読み取り専用が主）。verify_postgis_phase0.py（Phase 0検証）/ apply_migrations.py（migrate.pyの手動起動）/ check_db_connection.py（接続確認）/ export_openapi.py（OpenAPIスキーマ・フロント契約フィクスチャの書き出し）/ measure_tag_coverage.py（改善計画T102、PBF直読みのタグ付与率実測）/ measure_axis_stats.py（改善計画T124、dev DBに対する軸ペア相関・クランプ前生値分布・材料タグの補正発火率・highway階級別事故密度の計測。相関・丸め損失の実測方法はT121の使い捨て版を常設化したもの）/ collect_jartic.py（改善計画T53、JARTIC WFSから交通量オープンデータを収集しdev専用のtraffic_stations/traffic_hourlyへ保存。唯一DB書き込みを伴うscripts/。本番Oracle migrationには含めない）/ analyze_jartic_calibration.py（改善計画T53、collect_jartic.pyの収集結果を最寄りosm_raw_waysへ空間マッチしcar_stress_level（改善計画T150で「交通ストレス」から改称）との突き合わせを集計。相関計算はmeasure_axis_stats.pyの純関数を再利用）
    tests/
      test_health.py          ✅ status/started_at（ISO8601）の検証、commitがRENDER_GIT_COMMIT未設定時null・設定時はその値を反映すること（「Renderデプロイの反映確認」で追加）
      test_geo.py             ✅ destination_point / haversine_distance_km / compass_label / bearing_between / sample_indices / sample_line_coordinates / sample_line_pointsの検証（後者3つは「完全移行」で一度撤去、「ルーティングエンジンの切り替え対応」でOpenRouteServiceEngine用に復元）
      test_routing_service.py ✅ ORSClientをモックした単体テスト
      test_routes_preview.py  ✅ RoutingServiceをDIでモックしたAPIテスト。per-IPレート制限（20回/分）の429検証を追加
      test_route_generator.py ✅ RouteGenerator（周回生成戦略、エンジン非依存）の検証: 経由地点が起点始点/終点の周回を成すこと・距離許容フィルタ・失敗方位のスキップ・prepare失敗時の空返却・**評価が距離フィルタ通過候補だけに行われること**・total_scoreソート・engine_name公開（設計レビュー対応のポート分割で新規）
      test_openrouteservice_engine.py ✅ OpenRouteServiceEngineのエンドツーエンド検証（RouteGenerator経由）: 8方位生成・経路取得失敗時スキップ・標高/風プロファイルのマージ・total_score算出・segments構築・engine_name（旧test_route_generator.pyのopenrouteservice版から改組）
      test_road_graph_engine.py ✅ RoadGraphEngineのエンドツーエンド検証（RouteGenerator経由）: 起点を中心とした「車輪」状のRoad Graphフィクスチャによる8方位生成・許容範囲フィルタ・経路探索失敗時スキップ・標高/路面/風の集計・segments構築・Overpass問い合わせが1回のみ・標高取得がパス上のEdgeだけ＆距離フィルタ通過候補だけに絞られること（性能回帰テスト）・engine_name（旧test_route_generator.pyのRoad Graph版から改組）
      test_routing.py          ✅ build_networkx_graph（Hard Constraint除外）・find_nearest_node・shortest_path_node_ids（コスト最小経路・到達不能・始点=終点）・path_to_edge_ids・concat_node_pathsの検証（「完全移行」で新規）
      test_routes_generate.py ✅ get_route_generation_builderをDIでモックしたAPIテスト（engineフィールドの返却・per-IPレート制限の429・同時実行上限の429・settings.routing_engineによるエンジン選択に加え、研究IF改善Phase 1で重み上書きの伝搬・conditionsエコー・上書きバリデーション422・YAML既定値へのフォールバックの検証を追加）
      test_elevation_service.py ✅ 標高プロファイル（獲得標高・最高/最低標高・最大勾配）の算出・欠損値・有効点2点未満時の扱いの検証（Step5。elevation_service.pyと同じ経緯で削除→復元）
      test_wind_service.py    ✅ 区間ごとの推定到達時刻の計算・wind_penalty算出・天候取得失敗時の扱いの検証（Step7。wind_service.pyと同じ経緯で削除→復元）
      test_elevation_client_cache.py ✅ 同一/近傍座標でのキャッシュ再利用・遠方座標での再取得
      test_weather_service.py ✅ 現在/指定時刻の天候取得、取得失敗時の扱い
      test_weather_client_cache.py ✅ TTL内キャッシュ再利用・失効後再取得・取得失敗時の扱い
      test_weather_route.py   ✅ /api/weatherのDIモックテスト。per-IPレート制限（60回/分）の429検証を追加
      test_wind.py             ✅ WindCalculator.wind_penaltyの向かい風/追い風/横風の検証（domain/wind.py自体は「完全移行」後もdomain/evaluation.py: compute_wind_penaltyから再利用）
      test_road.py             ✅ classify_osm_surface（OSMタグ基準、両エンジン共通）とdistance_weighted_road_score（距離加重集計、改善計画T21で両エンジン共通化）の検証。不明路面の「分母から除外・None判定」（設計レビュー対応）の検証を含む
      test_scoring.py         ✅ normalize_min_maxの方向反転・全同値時の中立100点・None扱いの検証
      test_route_scorer.py    ✅ RouteScorer.scoreの正常系・指標欠損時の重み再正規化・score_breakdown（寄与点の合計=total_score）・全重み0時のtotal_score=Noneの検証
      test_difficulty.py      ✅ gradient/wind/road_difficultyの閾値・composite_difficultyの再正規化の検証
      test_region.py           ✅ tile_bounds_lonlatの検証（zoom0で全世界を覆う・隣接タイルの境界一致など、Step10改訂）。tiles_covering_bboxの検証（単一/複数タイル・世界端でのクランプ）を追加（Road Graphのタイル単位キャッシュ導入時、新規）
      test_region_service.py  ✅ RegionService.get_road_surface_tileのタイルキャッシュ利用/未キャッシュ時の挙動の検証（Step10改訂）
      test_region_routes.py   ✅ /api/region/road-surface-tiles/{z}/{x}/{y}.pbfのDIモックテスト・ズーム範囲外リクエストの400（Step10改訂）
      test_overpass_client.py ✅ OverpassClient.get_ways_and_nodesの正常系・エラー時のNone返却・複数ミラーへの同時問い合わせ（`get_roads`は改善計画T22で削除済み）
      test_graph.py            ✅ build_road_graphのWay分割（交差点/端点/形状点）・direction処理・内部ID/OSM IDの分離・距離計算の検証（Road Graph移行Phase 1、新規。Phase 2でWaySpec契約に合わせて更新）
      test_osm_adapter.py      ✅ osm_way_to_way_specのonewayタグ解釈（yes/-1/大文字小文字・空白/未知の値）・highway受け渡し・ノード数不足時の除外の検証（Road Graph移行Phase 2、新規。Phase 3でsurfaceタグ受け渡しの検証を追加）
      test_attributes.py       ✅ compute_elevation_attribute（登り/下り/混在/欠損値/有効点不足）・build_surface_attributes（osm_way_id対応/未知way/way_id無し）の検証（Road Graph移行Phase 3、新規）
      test_elevation_attribute_service.py ✅ ElevationAttributeService.get_attributes_for_graphのDIモックテスト（複数Edge独立性・欠損値・空グラフ）（Road Graph移行Phase 3、新規）
      test_evaluation.py       ✅ is_edge_allowed（Hard Constraint）・compute_edge_cost（平坦舗装/激坂未舗装の比較・属性欠損時のフォールバック・重み変更）の検証（Road Graph移行Phase 4、新規）。compute_wind_penalty（向かい風/追い風）・風統合の検証を「完全移行」（Phase 6）で追加
      test_evaluation_service.py ✅ EvaluationService.evaluate_graphのDIモックテスト（Hard Constraint除外・属性欠損・空グラフ・カスタムRoutePreference）（Road Graph移行Phase 4、新規。Phase 5でload_route_preference（既定パス/カスタムパス）・設定ファイル経由デフォルトの検証を追加）
      test_graph_service.py   ✅ GraphService.build_graph_with_surface_tags_for_bboxのDIモックテスト（Road Graph移行Phase 1、新規）。get_or_build_graph_with_attributesのタイル単位キャッシュ動作（単一/複数タイル・部分キャッシュ・一部タイル取得失敗）の検証を追加
      test_vector_tile.py      ✅ encode_road_surface_tileのデコード可能性・座標範囲・surface_goodプロパティ・2点未満のway除外の検証（Step10改訂）
      test_cache_db.py        ✅ 標高のSQLite永続キャッシュ読み書きの検証（Step5用。路面セルのテストはStep10改訂で撤去）
      test_basemap_client.py  ✅ BasemapClientのプロキシ・URL書き換え・キャッシュ利用の検証（Step10）
      test_basemap_routes.py  ✅ /api/basemap/{path}, /api/basemap/refreshのDIモックテスト（Step10）。basemap/refreshのper-IPレート制限（6回/分）の429検証を追加
      test_tile_cache.py      ✅ ファイルキャッシュのパスフラット化・パストラバーサル耐性の検証（Step10）
      test_rate_limiter.py     ✅ check_rate_limitの固定窓レート制限（上限内許可・超過拒否・クライアント単位の独立性・ウィンドウ経過後のリセット）の検証。_sweep（アクセス途絶クライアントの定期削除、メモリリーク対策）の検証を追加
      test_migrate.py          ✅ apply_pending_migrationsの検証: 新規ファイルの適用・記録、2回目呼び出しでの冪等（再実行なし）、一部ファイルが適用済みの場合に残りだけ適用されること（改善計画T17）
    migrations/                 ✅ 番号付きSQLファイル（`infrastructure/migrate.py`が適用。改善計画T17）。列追加・インデックス・データバックフィルはここへファイルを1つ足して行う。`create_tables`への追記は禁止（decisions/pre-static-attributes-gate.md 決定3）。0001_legacy_backfill_and_indexes.sql: 旧create_tables内にあったALTER/インデックス/バックフィルの移設（内容無変更）。0006_add_accident_points.sql: accident_points/accident_import_runs（T50）。0007_add_route_designations.sql: route_designations/designation_attributes/designation_import_runs（T51）。0008_stale_way_partial_index.sql: is_split_up_to_date用の部分GiST索引（T68、性能対策）。0009_designation_attributes_osm_way_id.sql: designation_attributesのキーをedge_id（road_edges FK）からosm_way_id（osm_raw_ways FK）へ変更（T74、DROP→再作成）
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
        Map/mapLayers.ts        ✅ 地図レイヤーのカタログ（id/label/kind/description、単一ソース）。チップ行とサイドバーのセクション枠はこの列挙で描画（UI再構成 第2段で新規）
        MapOverlayControls/MapOverlayControls.tsx ✅ 地図上のON/OFFチップ行＋▶で開く凡例内訳パネル（レイヤー固有の知識を持たない汎用描画係。UI再構成 第2段で全面書き換え、旧⚙ボタン・RoadFilterDialogは廃止。凡例パネルは実機フィードバックを受け位置ズレ・展開挙動を反復修正済み）
        Map/staticAttributeLayers.ts ✅ P1/T50/T51の静的レイヤー色分け・凡例・絞り込み軸カタログ（CAR_STRESS/BICYCLE_INFRA/DESIGNATION/ACCIDENT/STOP_POI/INTERSECTION、STATIC_FILTER_AXES。7章参照）。buildCategoricalLayerDefsで同型3組を共通化（T82）
        Map/icons.tsx              ✅ 地図上チップ用の自作SVGアイコン群（レイヤー数増加に伴う新規）
        Map/recipeExpression.ts    ✅ 改善計画T123: carStressExpression.ts/safetyExpression.tsが共有するMapLibre expression断片の組み立てヘルパー（backend/app/domain/recipe.py・改善計画T122のTS側ミラー）
        Map/recipeBreakdownPopup.ts ✅ 改善計画T123: 車ストレス・安全度の区間別判定内訳ポップアップ（改善計画T90・安全度レシピ）のHTML組み立て＋ボタン配線。MapView.tsxの双子関数（約158行）を軸設定オブジェクト渡しの1実装へ集約
        Map/useLayerDataStatus.ts   ✅ 改善計画T123: レイヤーデータ状態（loading/empty/error、改善計画T87）の算出・追跡（computeLayerDataStatus/clearStaleTrackedSourceErrors＋状態管理フック）。MapView.tsxから抽出（2026-08-17レビューDEFER(a)の履行）
        MapLayersPanel/          ✅ サイドバーのレイヤー設定パネル（MapLayersPanel.tsx: kind別グループ＋レイヤーごとの表示スイッチ・凡例・panelHint説明文（T84カタログ集約） / RoadFilterEditor.tsx: 路面絞り込みの下書き→適用編集 / WidthSwatch.tsx: 太さプレビュー）。旧MapLegendPanel＋旧RoadFilterDialogの統合置き換え（UI再構成 第2段）
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
        useStoredState.ts              ✅ localStorage永続化付きuseState（page.tsxの保存付き状態を抽出。改善計画T47 R-6の閾値到達時対応）
      lib/
        debugLog.ts                ✅ デバッグモードのON/OFF状態（`localStorage`永続化）とログ出力本体。`services/`配下の各fetchラッパー・`MapView.tsx`から呼ばれる（フロントエンドUX改善）
      services/
        healthApi.ts             ✅
        routeApi.ts               ✅ previewRoute() / generateRoutes()。previewRouteは`/api/routes/preview`
                                    （Step3の疎通確認用エンドポイント）向けのクライアント関数で、
                                    現状どのUIコンポーネントからも呼ばれていない（テストのみが参照）
        weatherApi.ts             ✅ getCurrentWeather()
        regionApi.ts               ✅ roadSurfaceTileUrl() / ROAD_TILE_MIN_ZOOM/MAX_ZOOM / refreshBasemapCache()（Step10改訂。路面がタイル化されJSON型を持たなくなったため`types/region.ts`は削除済み）
      types/
        generated/                 ✅ backendのOpenAPIスキーマからの生成物（openapi.json＝backend/scripts/export_openapi.pyが出力、api.d.ts＝npm run generate:apiが生成）。コミット対象で、CIのapi-contractジョブがドリフトを検知する
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

GET /api/debug/stats   # 外部API呼び出し・キャッシュのカテゴリ別集計（呼び出し数/エラー数/ヒット率/所要時間、
                       # error_types内訳・last_error_type/at・last_success_at・retried_calls/
                       # retry_attempts_total・stale_fallback_used。夜間502調査（改善計画T92）で
                       # 「失敗の主な理由を推測できる程度の情報」として追加）と429拒否数のプロセス内
                       # スナップショット（infrastructure/debug_log.py）。error_typesはHTTPステータス
                       # （例: "http_429"）か例外クラス名のみの粗いラベルで、メッセージ本文・URL・
                       # 座標は含まないため、debug_modeに関わらず/healthと同様に常時公開。
                       # プロセス再起動でリセット
Response 200:
{ "commit": null, "started_at": "2026-08-14T10:00:00+00:00", "engine": "openrouteservice", "debug_mode": false,
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
Response 502（openrouteservice呼び出し失敗時）:
{ "detail": "ルート取得に失敗しました: ..." }
Response 429（同一クライアントIPから1分あたり20リクエスト（`PREVIEW_RATE_LIMIT_PER_MINUTE`）を超えた場合）:
{ "detail": "リクエストが多すぎます。しばらく待ってから再試行してください。" }

POST /api/routes/generate   # Step4: 周回ルート候補生成、Step5: 標高フィールド追加、Step7: wind_score追加、Step8: road_score/total_score追加
                            # ルーティングエンジンはsettings.routing_engineで切り替え（既定openrouteservice）。
                            # レスポンスのengineフィールドでどちらのエンジンが生成したかを識別できる
                            # （wind_score等はエンジンによって算出の意味が異なるため。設計レビュー対応で追加）。
Request:
{ "latitude":35.7597, "longitude":139.7387, "distance_km":30, "distance_tolerance_km":5, "route_type":"loop" }
Request（評価重みの上書き。研究用・省略可。docs/research-interface-review-2026-08-15.md §10-1）:
{ ...上記に加えて,
  "scoring_weights": { "distance_weight":0.1, "elevation_weight":0.2, "wind_weight":0.3, "road_weight":0.4 },
  "route_preference": { "elevation_weight":0.5, "road_weight":0.25, "wind_weight":0.25 },
  "car_stress_recipe": { "lanes_low_threshold":1, "lanes_low_adjustment":-1 },
  "safety_recipe": { "lit_adjustment":-1, "tunnel_adjustment":1 } }
  # 省略時はscoring.yaml / route_preference.yaml / car_stress_recipe.yaml / safety_recipe.yamlの
  # 既定値。指定する場合は全フィールド必須・非負（部分指定でクラス既定値が黙って入る事故を防ぐ、
  # car_stress_recipe/safety_recipeも同様）。
  # 重みは有効指標の重み和で正規化されるため合計1.0でなくてよい。scoring_weightsを全て0にすると
  # total_score=nullになる（RouteScorer参照）。car_stress_recipe/safety_recipeはそれぞれの軸の
  # 中身（一次情報→二次情報の変換式）の上書きで、route_preferenceのcar_stress_weight/night_weight
  # （軸間の重み）とは別階層（7章参照）。safety_recipeは改善計画T139で難易度合成からは
  # 外れたが、表示用途（安全度の内訳確認）としてリクエスト単位の上書きを引き続き受け付ける
Response 200:
{
  "routes": [
    {
      "id":"route-090", "direction_label":"東", "distance_km":32.7,
      "elevation_gain_m":12.8, "min_elevation_m":1.1, "max_elevation_m":9.6, "max_gradient_percent":0.8,
      "wind_score":0.15, "road_score":76.2, "total_score":73.8,
      "score_breakdown": [   /* total_scoreの軸別内訳（RouteScorerが算出。研究IF改善 §10-2）。
                                scoreは候補集合内相対の正規化値(0-100)、contributionは寄与点で
                                有効指標分の合計がtotal_scoreに一致（丸め誤差除く） */
        { "axis":"distance", "score":95.0, "weight":0.30, "contribution":28.5 },
        { "axis":"elevation", "score":80.0, "weight":0.15, "contribution":12.0 },
        { "axis":"wind", "score":66.0, "weight":0.30, "contribution":19.8 },
        { "axis":"road", "score":54.0, "weight":0.25, "contribution":13.5 }
      ],
      "segments": [
        {
          "geometry": { "type":"LineString","coordinates":[...] },  /* 区間の道なり形状（ルートgeometryの部分列。地図の色分けはこれに沿って描く） */
          "start_latitude":35.7597, "start_longitude":139.7387,
          "end_latitude":35.7602, "end_longitude":139.7390,
          "cumulative_distance_km":0.0, "distance_km":1.16,
          "estimated_arrival_time":"2026-08-13T23:20:43",
          "gradient_percent":0.2, "wind_penalty":-0.83, "road_surface_good":true,
          "elevation_difficulty":2.0, "wind_difficulty":0.0, "road_difficulty":0.0, "difficulty":0.4
        }
        /* ...区間の数だけ続く（openrouteserviceエンジン: 距離連動サンプリング＝約1km間隔・12〜32点 / road_graphエンジン: Edge数分） */
      ],
      "geometry": { "type":"LineString","coordinates":[...] },
      "stop_density": 3.1, "car_stress_score": 2.4, "bicycle_infra_score": 18.0,
      "intersection_density": 5.2, "accident_density": 0.03,
      /* ↑ P1（停止密度〜交差点密度）・T50（事故密度）。route_preference.yaml側の重みのみに効き、
         上のtotal_scoreには含まれない。segments[]側にも軸別difficulty・生値が入る（7章参照） */
      "overall_difficulty": 22.5  /* segments.difficultyの距離加重平均（絶対基準、実験間比較用） */
    },
    ...（total_scoreが高い順、最大8件）
  ],
  "engine": "openrouteservice",
  "conditions": {   /* この生成に実際に適用された条件のエコー（実験の記録・再現用。研究IF改善 §10-6）。
                       重みは上書き値またはYAML既定値のうち実際に使われた方 */
    "latitude":35.7597, "longitude":139.7387, "distance_km":30, "distance_tolerance_km":5,
    "scoring_weights": { "distance_weight":0.30, "elevation_weight":0.15, "wind_weight":0.30, "road_weight":0.25 },
    "route_preference": { "elevation_weight":0.25, "road_weight":0.30, "wind_weight":0.45 },
    "car_stress_recipe": { "lanes_low_threshold":1, "lanes_low_adjustment":-1 },
    "generated_at": "2026-08-15T14:30:00+09:00"
  }
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
Response 429（同一クライアントIPから1分あたり60リクエスト（`WEATHER_RATE_LIMIT_PER_MINUTE`）を超えた場合）:
{ "detail": "リクエストが多すぎます。しばらく待ってから再試行してください。" }

GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf   # 表示中ビューポート全体の路面データ（PostGIS/ST_AsMVTで生成したベクタタイル。取込範囲外は空タイル）
Response 200（Content-Type: application/vnd.mapbox-vector-tile）: バイナリのMVT。レイヤー名`road_surface`、各地物（LineString）は`surface_good`（true=舗装/false=未舗装/null=不明）に加え、
  highway/surface/smoothness/tunnel/bridge/`bicycle_infra`/`designation`/`osm_way_id`、および車ストレス・
  安全度が共有する材料タグ`cycleway_class`/`maxspeed_kmh`/`lanes_count`/`motor_vehicle_no`と、
  安全度のみが使う`lit`（`shoulder`は改善計画T122でP1実測0.0%の死に補正と判明し撤去済み）
  （P0/P1/T51/T74/T90/車ストレスレシピ外出し基盤/安全度レシピ、現行タイル世代v10。7章参照）プロパティを持つ。
  車ストレスの最終値（1-5）・安全度の最終値（1-4、段階数は独立）はタイルへ焼き込まず、
  フロントエンド（`carStressExpression.ts`/`safetyExpression.ts`、MapLibre expression）と
  ルート採点（`domain/traffic.py: car_stress_breakdown`/`domain/safety.py:
  safety_breakdown`）がそれぞれ材料タグから計算する（7章参照）。`osm_way_id`は表示用ではなく、
  区間クリック時の車ストレス内訳取得（`POST /api/region/car-stress-breakdown`）・
  安全度内訳取得（`POST /api/region/safety-breakdown`）がクリックされたフィーチャーを
  曖昧さ無く引き直すための識別子（T90、安全度レシピ）
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

POST /api/region/car-stress-breakdown   # 車ストレスの区間別判定内訳（T90）。クリックされた道路（road-surface-tilesが焼き込む`osm_way_id`）について、`car_stress_breakdown`が計算に使ったベース値・各補正・最終値を返す
Request: `{ "osm_way_id": number, "car_stress_recipe"?: CarStressRecipeOverride }`。
  `car_stress_recipe`省略時は既定レシピ（`domain/traffic.py: DEFAULT_CAR_STRESS_RECIPE`）。
  GETでなくPOST+JSONボディなのは、レシピ上書きという複雑なオブジェクトをクエリパラメータで
  渡すのが不自然なため（車ストレスレシピ外出し基盤、`/api/routes/generate`と同じ形に統一）
Response 200: `CarStressBreakdown`（`base`/`cycleway_adjustment`/`maxspeed_adjustment`/`lanes_adjustment`/`designation_adjustment`/`motor_vehicle_no_override`/`level`）。該当wayが存在しない・highwayが判定基準に未登録・DBなし構成の場合はnullまたはlevel=null
Response 422（osm_way_idが整数でない場合）
Response 429: road-surface-tilesと同じレート制限（`ROAD_TILE_RATE_LIMIT_PER_MINUTE`）を流用

POST /api/region/safety-breakdown   # 安全度の区間別判定内訳（改善計画: 安全度レシピ）。region_car_stress_breakdownと完全に同じ構造
Request: `{ "osm_way_id": number, "safety_recipe"?: SafetyRecipeOverride }`。
  `safety_recipe`省略時は既定レシピ（`domain/safety.py: DEFAULT_SAFETY_RECIPE`）
Response 200: `SafetyBreakdown`（`base`/`cycleway_adjustment`/`maxspeed_adjustment`/`lanes_adjustment`/`lit_adjustment`/`tunnel_adjustment`/`designation_adjustment`/`motor_vehicle_no_override`/`level`）。該当wayが存在しない・highwayが判定基準に未登録・DBなし構成の場合はnullまたはlevel=null
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

### 評価重みのリクエスト上書きと評価モデル研究時の構成（研究インターフェース改善 Phase 1）

評価モデルの探索・研究（[research-interface-review-2026-08-15.md](research-interface-review-2026-08-15.md)）のため、
`scoring.yaml`（total_score・候補集合内相対）と`route_preference.yaml`（Edge評価・区間難易度・絶対）の重みは
`/api/routes/generate`のリクエストボディでリクエスト単位に上書きできる（§10-1）。実際に適用された値は
レスポンスの`conditions`にエコーされ（§10-6）、レスポンスJSONを保存すればそのまま再現条件になる。

- 配線: `dependencies.py: get_route_generation_builder`がビルダー（`RouteGenerationSetup`を返す呼び出し可能）を
  DIで供給し、エンドポイントが検証済みの上書き値（無ければNone→YAML既定値）を渡して組み立てを完了する。
  YAMLはリクエスト毎に再読込されるため、ファイル編集もサーバー再起動なしで反映される
- 上書きは全フィールド必須・非負（部分指定でクラス既定値が黙って入る事故を防ぐ）。重みは有効指標の
  重み和で正規化するため合計1.0でなくてよく、`scoring_weights`を全て0にした場合は合成不能として
  `total_score=null`（`RouteScorer`のweight_sum==0ガード、`composite_difficulty`と同じ扱い）
- **研究時のエンジン選択**: 既定エンジン（openrouteservice）では重みは同じ8候補の並べ替え・色分けにしか
  効かない（経路形状はORSが決める）。**重みの変更をルート形状まで反映させる実験は`.env`で
  `ROUTING_ENGINE=road_graph`を指定して行うこと**（`route_preference`がEdge Cost→Dijkstra探索に効く。
  ただし勾配は探索コストに含まれない既知の制約がある。road_graph_engine.pyのdocstring参照）

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
  car_stress: number | null;          // 1-5、P1残り（生値。T138で自転車インフラの寄与を含む）
  safety: number | null;              // 1-4（表示用一次属性の生値。T139でdifficulty軸からは独立に廃止済み、削除はT148）
  bicycle_infra: string | null;       // 分類の生値（表示用一次属性。T138でdifficulty軸からは独立に廃止済み）
  elevation_difficulty: number | null;
  wind_difficulty: number | null;
  road_difficulty: number | null;
  stop_difficulty: number | null;         // P1（改善計画T149でタグなし交差点の寄与を含む）
  car_stress_difficulty: number | null;   // P1残り（T138で自転車インフラの寄与を含む）
  accident_difficulty: number | null;     // T50
  night_difficulty: number | null;        // 改善計画T139（街灯なし・トンネル、既定重み0）
  difficulty: number | null;              // 7軸の合成値（絶対基準0-100）
}

interface RouteScoreComponent {   // total_scoreの軸別内訳（研究IF改善 §10-2）
  axis: string;                    // "distance" | "elevation" | "wind" | "road"
  score: number | null;            // 候補集合内相対の正規化値0-100（指標が取れなかった候補はnull）
  weight: number;                  // 合成に使った設定重み
  contribution: number | null;     // total_scoreへの寄与点（有効指標分の合計=total_score）
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
  stop_density: number | null;          // 回/km、P1
  car_stress_score: number | null;      // 距離加重平均(1-5)、P1残り
  bicycle_infra_score: number | null;   // 専用インフラ区間率(%)、表示用一次属性の集約統計
  intersection_density: number | null;  // 回/km、P1残り
  accident_density: number | null;      // 件/(km・年)、T50
  safety_score: number | null;          // 距離加重平均(1-4)、改善計画: 安全度レシピ
  total_score: number | null;
  score_breakdown: RouteScoreComponent[] | null;
  segments: RouteSegmentDetail[] | null;
  overall_difficulty: number | null;  // segments.difficultyの距離加重平均（絶対基準、実験間比較用。研究IF改善§10-7）
}

interface RouteGenerateRequest {
  latitude: number;
  longitude: number;
  distance_km: number;
  distance_tolerance_km: number;
  route_type: "loop";
  scoring_weights?: ScoringWeights;          // 評価重みの上書き（研究用・省略可、§10-1）
  route_preference?: RoutePreferenceWeights; // 同上（Edge評価・区間難易度の重み）
  car_stress_recipe?: CarStressRecipeOverride; // 同上（車ストレス軸の中身、7章参照）
  safety_recipe?: SafetyRecipeOverride;      // 同上（安全度軸の中身、7章参照）
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

候補ルートに紐づかない地域全体の標高・路面レイヤー（Step10）は、いずれもタイル形式（標高はGSIのラスタタイル、路面はPostGIS/ST_AsMVTで生成したMVT）で配信するため、Step5-9のようなJSONのレスポンスモデルを持たない。バックエンド側の`domain/region.py`にはタイル範囲計算に使う`BoundingBox`（Pydanticモデル）が残っているが、これはPostGISクエリ・（DBなし構成での）Overpass問い合わせに使う内部的な値であり、フロントエンドとの間でJSONとしてやり取りするものではない（フロント側に対応する型定義は無い）。

これで仕様書18章記載の`RouteCandidate`の項目、地図可視化用の`segments`（Step9）、および候補ルートに紐づかない地域全体の標高・路面レイヤー（Step10）が出揃った。

---

## 7. 静的道路属性と7軸評価モデル（P0/P1、外部静的データソースT50/T51、安全度レシピ）

Step8時点の評価（距離・標高・風・路面の4指標）に加え、OSMタグ・警察庁事故統計・国土数値情報
（KSJ）を材料とした指標を追加し、区間難易度（`route_preference.yaml`）・地図の静的レイヤーの
両方に反映した（`static-road-attributes-plan.md` P0/P1、
[external-data-sources-review-2026-08-16.md](external-data-sources-review-2026-08-16.md)、
改善計画: 安全度レシピ）。scoring.yaml（total_score）には含めない（stop_weightと同じ
スコープ判断、後述）。

自転車インフラは改善計画T138（評価システムの層構造再設計）で独立軸（`infra_weight`）を
廃止し車ストレス側へ統合済み（9軸→8軸。`car_closeness()`のcycleway補正が既に
自転車インフラの情報を反映しているため、独立に同じ情報を二重に持たない設計）。
生値（`bicycle_infra`分類）・ルート集約統計（`bicycle_infra_score`、専用インフラ区間の
距離加重率%）自体は一次属性の表示用データとして引き続き保持する。

続く改善計画T139で、安全度軸（旧`safety_weight`）自体を廃止した。highway・cycleway・
maxspeed・lanes・指定路線由来の部分は既にT138で車ストレス側へ吸収済みのため重複実装せず、
街灯・トンネル由来の部分のみ`domain/night.py: night_difficulty`として独立させた
（既定重み`night_weight=0.0`で運用。街灯・トンネルを気にするユーザーが研究モードで
個別に重みを上げる想定）。事故実績は元から独立軸（`accident_weight`）のため変更なし。
`domain/safety.py`・`safety_recipe.yaml`・関連API・地図の安全度レイヤーは表示用途
（研究モードの内訳確認等）として残置し、削除は改善計画T148（移行完了後）で行う。

続く改善計画T149（設計プロンプト改訂2026-08-18「現行9軸からの帰属先」）で、交差点密度
（旧`intersection_weight`）の独立軸を廃止し停止密度側へ統合した。`domain/difficulty.py:
stop_difficulty`が、信号・横断歩道・一時停止・踏切の密度に加え、次数3以上のタグなし
交差点の密度を低い重み（0.3、signal等を1.0とした相対値）で加算する（8軸→7軸）。
ルート単位の交差点密度（`RouteCandidate.intersection_density`）は表示用の一次属性
集約統計として引き続き独立に保持する。

### 7軸の一覧と重み

`domain/difficulty.py: evaluate_axis_difficulties`が7軸の生値と重みから軸別difficulty・
合成difficulty（区間の`difficulty`、絶対基準0-100）を算出する。重みは
[backend/app/route_preference.yaml](../backend/app/route_preference.yaml)：

| 軸 | weight フィールド | 既定値 | 生値の単位 | 算出元 |
|---|---|---|---|---|
| 標高（勾配） | `elevation_weight` | 0.15 | %（区間勾配） | Step5（`ElevationService`/`ElevationAttribute`） |
| 路面 | `road_weight` | 0.19 | good/bad/unknown | Step8（`domain/road.py: classify_osm_surface`） |
| 風 | `wind_weight` | 0.26 | m/s（正=向かい風） | Step7（`WindCalculator`） |
| 停止密度（交差点密度込み） | `stop_weight` | 0.20 | 回/km | P1（信号・横断歩道・一時停止・踏切、`osm_raw_pois`。T149で旧`intersection_weight`0.05を合算） |
| 車ストレス（自転車インフラ込み） | `car_stress_weight` | 0.20 | 1-5 | P1（`domain/traffic.py: car_stress_level`、T138で旧`infra_weight`0.10を合算。改善計画T150で`traffic_weight`から改称） |
| 事故密度 | `accident_weight` | 0.08 | 件/(km・年) | T50（警察庁交通事故統計） |
| 夜間 | `night_weight` | 0.0 | 0-100 | 改善計画T139（`domain/night.py: night_difficulty`、街灯なし・トンネル） |

`scoring.yaml`（total_score・候補集合内相対評価）にはこの7軸のうち距離・標高・風・路面の
4指標のみ残す（区間難易度と違い、停止密度以降の指標は候補間の「おすすめ度」の並び順には
効かせない、というユーザー承認済みのスコープ判断。P1着手時に決定）。**軸を追加するときは
必ずこの1本道を通す**（`CLAUDE.md`参照）: 取込（`import_profile.yaml`/`ALLOWED_WAY_TAGS`等）
→ domain純関数 → `evaluate_axis_difficulties`への追加 → `route_preference.yaml` →
`AttributeRepository`＋ファサード対称委譲 → 両エンジン（`OpenRouteServiceEngine`/
`RoadGraphEngine`）→ フロント`evaluationAxes.ts`のカタログ1行。エンジンファイルに軸固有の
知識（SQL・タグ解釈）を書き足さない。

### 〇次: ハード制約（改善計画T140）

7軸の難易度計算に入る前段として、`domain/evaluation.py: is_edge_allowed`が対象Edgeを
探索グラフから丸ごと除外するかどうかを判定する（設計プロンプト「評価システムの層構造
再設計」の〇次フィルタ、仕様書29章のHard Constraintと同じ概念）。**スコア・重みには
一切登場しない**点が7軸との決定的な違い（該当Edgeは`EdgeCostResult.allowed=False`で
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
（車ストレス・旧安全度、いずれも`domain/traffic.py`/`domain/safety.py`の
`motor_vehicle_no_override`）側で「該当区間は最善値へ固定」という軸内の特例として
扱い続ける。ハード制約（探索対象から消える）とこの特例（探索はするが最も走りやすい
扱いになる）は挙動が異なるため区別が必要、という設計プロンプトの「ハード制約は
スコア外」原則との整合はこの区別を保つことで満たされる。

### 停止密度・車ストレス・自転車インフラ・交差点密度（P1、OSM由来）

- **停止密度**: `osm_raw_pois`（`domain/traffic.py: classify_stop_poi`が
  traffic_signals/crossing/stop/give_way/level_crossingへ分類、`STOP_POI_MATCH_MAX_DISTANCE_M
  =15m`でEdge/サンプル点へ空間マッチ）。集約は`distance_weighted_stop_density`
  （合計count÷合計distance_km）。
- **車ストレス**（改善計画T150で「交通ストレス」から改称）: `car_stress_breakdown(highway, tags, is_designated, recipe)`がhighway
  基本値（既定は`domain/recipe.py: ROAD_SUITABILITY_BASE_BY_HIGHWAY`、T130で車ストレス・
  安全度の共有材料として切り出し済み）に自転車専用帯・制限速度・車線数・T51指定
  路線該当（後述、+1補正）を加味した1-5の整数。未知highwayは評価対象外（None）。
  `car_stress_level`は`.level`だけを返す薄いラッパー。判定基準のうち軸固有の部分
  （対面通行の少車線道路への緩和）は`domain/traffic.py: CarStressRecipe`という「レシピ」に
  切り出してあり（車ストレスレシピ外出し基盤）、`recipe`省略時は既定レシピ
  （`DEFAULT_CAR_STRESS_RECIPE`、`car_stress_recipe.yaml`と同値）を使う。ルート採点は
  `/api/routes/generate`のリクエストで`route_preference`と同じ形で上書き可能（研究モード用、
  §10-1と同じ設計）。地図表示は最終値をタイルへ焼き込まず、材料タグ（後述）だけを焼き込んで
  フロントエンド側（`frontend/src/components/Map/carStressExpression.ts`、MapLibre
  expressionとして同じレシピを再現）で計算する。最終値を計算済みでタイル（全ユーザー共有
  キャッシュ）へ焼き込む従来方式では、レシピを変えるたびに世界中のタイルキャッシュを
  作り直す必要があった（T92/T93）ため、材料タグとレシピを分離した。
  **調整UI**（改善計画: 車ストレスレシピ調整UIパネル、T107の次ラウンド）:
  `frontend/src/components/CarStressRecipePanel/CarStressRecipePanel.tsx`が
  研究モード限定・`WeightPanel`（評価重みの上書き）とは独立したトグルでレシピの項目
  （T130で道路適正・自動車密度へ大部分が分離済みのため、現在は少車線道路への緩和2項目
  のみ）を編集できる
  （独立トグルにした理由: レシピは上書きすると地図の色分けへ即座に反映されるが、
  重みは次回のルート生成まで反映されないという挙動差があるため）。上書き中は
  `MapView.tsx`が車ストレスレイヤーの`line-color`（`setPaintProperty`）と凡例による
  絞り込み（`setStaticOverlayFilters`、`buildCarStressLegend`で該当軸だけ動的に
  組み立て直す）の両方をライブ更新し、区間クリックの内訳ポップアップ・次回のルート生成
  リクエストにも同じレシピを渡す（`page.tsx`が単一のstateを両方へ配線）。
- **自転車インフラ**: `classify_bicycle_infrastructure`がseparated/lane/shared_busway/
  shared_pedestrian/roadway/prohibited/unknownの7値に分類（優先順位あり）。改善計画T138で
  難易度への寄与は独立軸を持たず車ストレス側（`car_closeness()`のcycleway補正）へ
  一本化済み。この分類自体（`RouteSegmentDetail.bicycle_infra`の生値、
  `RouteCandidate.bicycle_infra_score`のルート集約統計）は一次属性の表示用データとして
  引き続き独立に保持する（地図の「自転車インフラ」レイヤー・研究インターフェースの
  統計表示はこちらを参照する）。
- **交差点密度**: 次数3以上（`INTERSECTION_DEGREE_THRESHOLD`）のroad_node。
  `INTERSECTION_MATCH_MAX_DISTANCE_M=30m`で空間マッチ。改善計画T149で難易度への寄与は
  独立軸を持たず停止密度側（タグなし交差点として`signal`等の0.3倍の重みで加算、
  `domain/difficulty.py: stop_difficulty`）へ一本化済み。ルート単位の集約統計
  （`RouteCandidate.intersection_density`）・地図の点タイル表示（`poi-tiles`の`degree`
  プロパティ）は一次属性の表示用データとして引き続き独立に保持する。

いずれも`AttributeRepository`（`road_graph_repository.py`）の対称メソッド
（`get_stop_poi_counts`/`get_nearest_stop_poi_counts`、`get_way_tags`/`get_nearest_way_tags`、
`get_intersection_counts`/`get_nearest_intersection_counts`）で提供し、`get_*`＝Edge集合を
渡してEdge単位（RoadGraphEngine）、`get_nearest_*`＝サンプル点列を渡してKNN空間マッチ
（OpenRouteServiceEngine）という対で揃えている。`get_way_tags_by_osm_way_id`（T90、
osm_way_id完全一致の1行取得）はこの対に属さない別系統で、区間別車ストレス内訳API
（`POST /api/region/car-stress-breakdown`）専用。地図表示は同じ属性を`road-surface-tiles`
（highway・surface同様プロパティとして焼き込み。車ストレス・自転車インフラ）と、点データの
`poi-tiles`（停止要因・交差点密度、後述）で提供する。

### 安全度（改善計画: 安全度レシピ）

車ストレス（走りにくさ・主観的な快適性）とは別概念として、事故・怪我リスクの客観的な
目安を表す軸を新設した。`safety_breakdown(highway, tags, is_designated, recipe)`
（`domain/safety.py`）が車ストレスと完全に同じ構造（highway基本値＋タグ由来の閾値・
補正、`recipe`省略時は既定レシピ`DEFAULT_SAFETY_RECIPE`/`safety_recipe.yaml`と同値、
研究モードで`/api/routes/generate`から上書き可能、地図表示は最終値をタイルへ焼き込まず
材料タグだけ焼き込んで`frontend/src/components/Map/safetyExpression.ts`が同じレシピを
MapLibre expressionとして再現）で1-4の整数を返す。cycleway分類・maxspeed・lanes・
designation該当は車ストレスと同じ材料タグを共有するが、`base_by_highway`の数値セット自体は
独立（同じhighway集合でも快適性と安全性は異なる概念のため、値を共有すると「安全度を調整した
つもりが車ストレスも変わる」事故を招く）。安全度のみが持つ追加補正: 街灯あり
（`lit_adjustment`）・トンネル（`tunnel_adjustment`）。
安全度はlanes_high（多車線＝リスク増）のみ採用し、車ストレスにあるlanes_low（少車線）は
採用しない（少車線が安全側かは研究上見解が分かれるため）。

事故密度（後述、警察庁統計）は意図的にこのレシピへ組み込まない。事故密度は特定のOSMタグから
決まる「材料」ではなく空間統計であり、既存の`accident_weight`軸が既にその役割を持つため、
二重計上を避けて別軸のまま独立させている（ユーザー承認済み）。

**調整UI**: `frontend/src/components/SafetyRecipePanel/SafetyRecipePanel.tsx`が
`CarStressRecipePanel.tsx`と同じ構造・同じ独立トグルの理由で全項目を編集できる。
基準値ピッカー・補正値ステッパー・情報アイコン開閉ボタンは、2つ目のレシピ登場を機に
`frontend/src/components/Map/recipeControls.tsx`（`LevelPicker`/`AdjustmentStepper`/
`FieldLabel`、色パレット・段階配列を引数化）へ共通化し、`CarStressRecipePanel.tsx`も
そちらを使うよう移行した。研究タブでは「レシピ」カテゴリの見出し下に車ストレスレシピの
直後に並ぶ（改善計画: 研究パラメータの導線改善で設計した、複数レシピを想定した`<div>`）。

### 事故密度（T50、警察庁交通事故統計オープンデータ）

`app/batch/import_accidents.py`が本票CSV（年度別、`backend/data/accidents/`、ユーザーが
年度ページから入手して配置）を取込む。関東7都県・2022〜2024年（2019〜2021年は本票のCSV列数が
異なる別スキーマのため未対応）。migration `0006_add_accident_points.sql`で
`accident_points`（`accident_id`主キー・`occurred_year`・`fatal`・`involves_bicycle`・
`geom`）・`accident_import_runs`（取込実行の記録）を追加。`domain/accident.py`が
純関数群（`ACCIDENT_MATCH_MAX_DISTANCE_M=30m`、`distance_weighted_accident_density`＝
合計count÷合計distance_km÷収録年数で「件/(km・年)」へ正規化）を持つ。収録年数は
`AttributeRepository.get_accident_years_covered`（`accident_import_runs`のsucceeded run数、
年重複なし）でハードコードせず動的取得する。地図表示は`GET /api/region/accident-tiles`
（後述、`AccidentService`/`AccidentTileQuery`）。

改善計画（事故密度の精度改善、既定挙動として反映）: `get_accident_counts`/
`get_nearest_accident_counts`（`road_graph_repository.py`）の`bicycle_only`既定値を
`False`→`True`へ変更した（自転車ルート案内アプリで自動車同士のみの事故まで数えていたのは
実質バグに近いという判断）。あわせて単純COUNTから死亡事故を`ACCIDENT_FATAL_WEIGHT`
（`domain/accident.py`、暫定値3.0）件分として積算するSUMへ変更し、戻り値がint→floatに
なった。`GraphService.get_accident_counts`に欠けていた`bicycle_only`引数も追加し、
road_graph_engine経由のルート生成にも既定値変更が実際に反映されるようにした。

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
（`car_stress_breakdown`の`designation_adjustment`、大型車交通の代理指標）。
`AttributeRepository.get_designated_edge_ids`（RoadGraphEngine、Edge集合の積集合。呼び出し時点で
`road_edges`は構築済みのため、`road_edges.osm_way_id`経由で`designation_attributes`へJOINする）と
`get_nearest_way_tags`が返す3要素目`is_designated`（OpenRouteServiceEngine、highway・tagsと
同一KNNに同居。旧`get_nearest_designated_flags`は改善計画T76で統合・削除済み）の対で提供する。
地図表示は`road-surface-tiles`のMVTに`designation`プロパティ（`emergency_transport`/
`critical_logistics`/両方該当時は`both`/未該当はプロパティ欠落、`designation_attributes`を
osm_way_id単位へ集約してから`osm_raw_ways`へJOIN）として焼き込む。

### 静的レイヤー・タイル配信（フロント9レイヤー）

[frontend/src/components/Map/mapLayers.ts](../frontend/src/components/Map/mapLayers.ts)の
`MAP_LAYERS`カタログは標高図・道路情報・車ストレス・安全度・自転車インフラ・指定路線・
停止要因・事故（警察庁統計）・ルートの9レイヤー。交差点密度（次数3以上のroad_node）は
バックエンドの
`poi-tiles`が引き続き焼き込むが、道路網を見れば概ね自明という判断（改善計画T96）により
地図上の独立可視化レイヤーとしては提供しない（`intersection_weight`のルーティング材料
としては引き続き使う）。色分け・凡例・絞り込み軸の定義は
[frontend/src/components/Map/staticAttributeLayers.ts](../frontend/src/components/Map/staticAttributeLayers.ts)
に集約（`STATIC_FILTER_AXES`が絞り込みUIのカタログ、事故のみ当事者×重大度の2軸）。

タイル配信は3系統:

1. **`road-surface-tiles`**（既存、`ROAD_SURFACE_TILE_VERSION`）: highway・surface_good・
   smoothness・tunnel・bridgeに加え、`bicycle_infra`・`designation`・車ストレス/安全度の
   材料タグ（`cycleway_class`/`maxspeed_kmh`/`lanes_count`/`motor_vehicle_no`/`shoulder`/`lit`）を
   LineString地物へ追加（P1・T51・安全度レシピで拡張）。世代v2=surface/highway追加、
   v3=surface正準拡充、v4=P0静的属性追加、v5=T51 designationプロパティ追加、
   v6=T74 designationのosm_way_id基準化・3値化（`both`追加）、
   v7=T90 osm_way_idプロパティ追加（区間クリック時の車ストレス内訳取得の識別子）、
   v8=T93（統合レビュー2026-08-17 F-1、T92の車ストレス判定ロジック変更の世代対上げ漏れ修正）、
   v9=車ストレスレシピ外出し基盤（当時の呼称は「交通ストレス」、改善計画T150で改称）。
   計算済みの`traffic_stress`最終値プロパティを廃止し、
   材料タグへ差し替え（最終値の計算はフロントエンドのMapLibre expressionへ移した）、
   **v10=安全度レシピ。安全度の材料タグ`shoulder`/`lit`を追加（tunnelは既存プロパティを
   再利用）**（現行）。
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

- `/api/routes/generate`は`config.py`の`routing_engine`設定でopenrouteservice委譲（既定）とRoad Graph＋NetworkX Dijkstraを切り替えられる（1章「ルーティングエンジンの切り替え対応」参照）
- OSMデータはPBF取込バッチ（`app/batch/import_pbf.py`）でPostGISへ事前取込済みの範囲を第一系統とし、Overpassフォールバックは改善計画T22で撤去済み（取込範囲外は空タイル/データ未整備扱い。docs/osm-pbf-import.md、[decisions/pre-static-attributes-gate.md](decisions/pre-static-attributes-gate.md)参照）
- 永続化層の構造（生OSM層／派生グラフ／属性／表示用MVTの4リポジトリ＋ファサード、トランザクション境界の規約）は`infrastructure/road_graph_repository.py`のdocstring参照
