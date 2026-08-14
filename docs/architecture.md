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
- ⬜ Step 11以降: 未定（MVPの主要機能は一通り実装済み）

---

## 1. 技術選定

| 領域 | 採用technology | 備考 |
|---|---|---|
| Frontend | Next.js (App Router) + TypeScript + MapLibre GL JS | React 19 / Next.js 16 |
| Backend | Python + FastAPI | pytest でロジックを単体テスト |
| DB | PostgreSQL + PostGIS | Step1-2では未接続。Docker Composeにコンテナのみ用意 |
| ルーティングエンジン | **暫定: openrouteservice API**（`cycling-road`プロファイル、外部APIキー方式）<br>**将来: Valhalla自前構築（Docker）** | `RoutingService`（[backend/app/services/routing_service.py](../backend/app/services/routing_service.py)）が `get_directions(waypoints: list[Coordinates])` を実装したクライアント（現在は`ORSClient`）を受け取る形にし、将来Valhalla用クライアントに差し替え可能にしてある。2点間（Step3）・多点経由（Step4の周回）の両方に対応 |
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

### 周回ルート生成のアルゴリズムと既知の制約（Step4）
`RouteGenerator`（[backend/app/services/route_generator.py](../backend/app/services/route_generator.py)）は、8方位それぞれについて「方位θの方向に半径R」「方位θ+45°の方向に半径R」の2経由地点を`domain/geo.py`の`destination_point`（球面三角法）で計算し、`[現在地, 経由地A, 経由地B, 現在地]`をopenrouteservice Directions APIに1回のリクエストで渡す。半径Rは`distance_km / 3`という固定ヒューリスティック。8方位分は`asyncio.gather`で並列実行し、失敗した方位はスキップする。

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

---

## 2. ディレクトリ構成

```
RideCompass/
  docs/
    architecture.md          ✅
  backend/
    app/
      main.py                ✅ FastAPI app, CORS
      config.py               ✅ pydantic-settings（.env読込、basemap_public_base_url含む）
      api/
        routes.py             ✅ GET /health, POST /api/routes/preview, POST /api/routes/generate, GET /api/weather, GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf, GET /api/basemap/{path}, POST /api/basemap/refresh
      domain/
        route.py               ✅ Coordinates, RouteSegment（surface_summary/surface_values含む）, RouteSegmentDetail（Step9）, RouteCandidate（標高・wind_score・road_score・total_score・segments含む）
        weather.py               ✅ WeatherConditions
        errors.py               ✅ RoutingError
        geo.py                   ✅ destination_point, haversine_distance_km, sample_indices, sample_line_coordinates, sample_line_points, compass_label, bearing_between
        road.py                   ✅ paved_percent（Step8）, surface_id_at_index, is_good_surface（Step9）, classify_osm_surface（Step10）
        scoring.py               ✅ normalize_min_max（Step8）
        difficulty.py             ✅ gradient_difficulty, wind_difficulty, road_difficulty, composite_difficulty（Step9）
        wind.py                   ✅ WindCalculator.wind_penalty（Step7）
        region.py                 ✅ BoundingBox, tile_bounds_lonlat, ROAD_TILE_MIN_ZOOM/MAX_ZOOM（Step10改訂。標高グリッド・snap_cells・bbox対角距離関連は撤去済み）
      services/
        routing_service.py     ✅ ORSClient等をラップ（waypointsリスト対応、surface extras/valuesのパース含む）。将来Valhallaに差し替え可能
        route_generator.py     ✅ 8方位の周回候補を並列生成＋標高・風・路面・総合スコア・区間詳細を統合（Step4-5-7-8-9）
        elevation_service.py   ✅ 点列から標高プロファイル・生の標高配列を算出（Step5、Step9でgeometryではなくpoints受け取りに変更）
        weather_service.py     ✅ 「地点＋時刻」で天候を取得（Step6）
        wind_service.py            ✅ 点列から区間ごとのwind_penaltyとwind_scoreを算出（Step7、Step9でget_wind_profileに変更）
        route_scorer.py            ✅ 4指標を正規化・重み付け合成しtotal_scoreを算出（Step8）
        region_service.py          ✅ get_road_surface_tile(z,x,y)で路面ベクタタイル(PBF)を生成・tile_cacheに永続化（Step10改訂。標高はGSIラスタタイルとしてフロントエンドが直接取得するためバックエンドを介さない）
      infrastructure/
        ors_client.py           ✅ openrouteservice Directions API（cycling-road、複数経由地対応、extra_info=surface）
        elevation_client.py     ✅ 国土地理院標高API（共有コネクション＋緯度経度メモ化キャッシュ）
        weather_client.py       ✅ Open-Meteo Forecast API（current+hourlyをまとめて取得、TTLキャッシュ）
        overpass_client.py         ✅ Overpass API（地域全体のOSM道路データ取得、Step10）
        vector_tile.py               ✅ 路面データをMVT（Mapbox Vector Tile）にエンコード（Web Mercator投影、Step10改訂）
        cache_db.py                 ✅ SQLite永続キャッシュ（標高のみ、Step5用。路面セルのキャッシュはStep10改訂でtile_cache.pyに統合し削除）
        tile_cache.py               ✅ 地図タイル・路面ベクタタイル共通のファイルキャッシュ（パスをSHA-256でフラット化、Step10）
        basemap_client.py           ✅ OpenFreeMapタイル/スタイルJSONのプロキシ＋URL書き換え（Step10）
        valhalla_client.py        ⬜ 将来
        osm_repository.py            ⬜
        database.py                   ⬜
    tests/
      test_health.py          ✅
      test_geo.py             ✅ destination_point / haversine_distance_km / sample_indices / sample_line_coordinates / sample_line_points / compass_label / bearing_betweenの検証
      test_routing_service.py ✅ ORSClientをモックした単体テスト（surface_summary/surface_valuesのパース含む）
      test_routes_preview.py  ✅ RoutingServiceをDIでモックしたAPIテスト
      test_route_generator.py ✅ 8方位生成・許容範囲フィルタ・失敗時スキップ・標高/wind_score/total_scoreマージ・segments構築
      test_routes_generate.py ✅ RouteGeneratorをDIでモックしたAPIテスト
      test_elevation_service.py ✅ 獲得標高/最大勾配の計算、欠損データ・データ不足時の扱い、生の標高配列の検証
      test_elevation_client_cache.py ✅ 同一/近傍座標でのキャッシュ再利用・遠方座標での再取得
      test_weather_service.py ✅ 現在/指定時刻の天候取得、取得失敗時の扱い
      test_weather_client_cache.py ✅ TTL内キャッシュ再利用・失効後再取得・取得失敗時の扱い
      test_weather_route.py   ✅ /api/weatherのDIモックテスト
      test_wind.py             ✅ WindCalculator.wind_penaltyの向かい風/追い風/横風の検証
      test_wind_service.py    ✅ FakeWeatherServiceを使った区間加重平均・区間ごとのwind_penalty・欠損時の扱いの検証
      test_road.py             ✅ paved_percent / surface_id_at_index / is_good_surface / classify_osm_surfaceの検証
      test_scoring.py         ✅ normalize_min_maxの方向反転・全同値時の中立100点・None扱いの検証
      test_route_scorer.py    ✅ RouteScorer.scoreの正常系・指標欠損時の重み再正規化の検証
      test_difficulty.py      ✅ gradient/wind/road_difficultyの閾値・composite_difficultyの再正規化の検証
      test_region.py           ✅ tile_bounds_lonlatの検証（zoom0で全世界を覆う・隣接タイルの境界一致など、Step10改訂）
      test_region_service.py  ✅ RegionService.get_road_surface_tileのタイルキャッシュ利用/未キャッシュ時の挙動の検証（Step10改訂）
      test_region_routes.py   ✅ /api/region/road-surface-tiles/{z}/{x}/{y}.pbfのDIモックテスト・ズーム範囲外リクエストの400（Step10改訂）
      test_overpass_client.py ✅ OverpassClient.get_roadsの正常系・エラー時のNone返却（Step10）
      test_vector_tile.py      ✅ encode_road_surface_tileのデコード可能性・座標範囲・surface_goodプロパティ・2点未満のway除外の検証（Step10改訂）
      test_cache_db.py        ✅ 標高のSQLite永続キャッシュ読み書きの検証（Step5用。路面セルのテストはStep10改訂で撤去）
      test_basemap_client.py  ✅ BasemapClientのプロキシ・URL書き換え・キャッシュ利用の検証（Step10）
      test_basemap_routes.py  ✅ /api/basemap/{path}, /api/basemap/refreshのDIモックテスト（Step10）
      test_tile_cache.py      ✅ ファイルキャッシュのパスフラット化・パストラバーサル耐性の検証（Step10）
    scoring.yaml               ✅ total_score算出とStep9難易度可視化で共有する重み設定（Step8）
    data/                       ✅ SQLite永続キャッシュ（ridecompass_cache.db、標高用）・地図タイル/路面ベクタタイル共通キャッシュ（tile_cache/）の保存先。gitignore対象（Step10）
    requirements.txt          ✅ mapbox-vector-tile追加（路面のMVTエンコード用、Step10改訂）
    Dockerfile                ✅
    .env.example              ✅
    pytest.ini                ✅ asyncio_mode = auto
  frontend/
    next.config.ts               ✅ `/api/basemap/*`と`/api/region/road-surface-tiles/*`をバックエンドへプロキシするrewrites（同一オリジン維持、Step10・Step10改訂）
    src/
      app/
        page.tsx               ✅ 左サイドバー（折りたたみ可）＋右地図の2ペインレイアウト統括。位置情報state・天候取得もここで保持（UI再構成）
        layout.tsx              ✅
      components/
        Map/MapView.tsx         ✅ 地図描画に専念（controlled props）。全候補ベース表示・選択中ハロー・動的レイヤー（風、選択中候補のみ）・地域レイヤー（標高＝GSIラスタタイル/路面＝自前ベクタタイル、いずれもMapLibreのtile sourceとして常設、同時表示可）の構成（Step4, Step9, UI再構成, Step10, Step10改訂）
        LocationControl/LocationControl.tsx ✅ 現在地表示・手動緯度経度入力フォーム（UI再構成、MapViewから分離）
        MapLayerControls/MapLayerControls.tsx ✅ 標高/路面（独立チェックボックス、同時表示可）・風（チェックボックス）・凡例・地域が広すぎる場合の案内・タイルキャッシュ更新ボタン（UI再構成, Step10）
        BackendStatus.tsx        ✅
        RouteForm/RouteForm.tsx  ✅ 距離入力＋生成ボタン（Step4）
        RouteList/RouteList.tsx  ✅ 候補一覧・選択・獲得標高・風評価・路面・総合スコア表示（Step4-5-7-8）
        WeatherPanel/WeatherPanel.tsx ✅ 気温・風向風速・降水確率表示（Step6）
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
GET /health
→ 200 { "status": "ok" }

POST /api/routes/preview   # Step3: 単一区間のルート取得確認用（暫定エンドポイント。デバッグ・疎通確認用に残置）
Request:
{ "origin": {"latitude":35.7597,"longitude":139.7387}, "destination": {"latitude":35.71,"longitude":139.75} }
Response 200:
{ "distance_km": 6.85, "duration_minutes": 17.9, "geometry": { "type":"LineString","coordinates":[...] } }
Response 502（openrouteservice呼び出し失敗時）:
{ "detail": "ルート取得に失敗しました: ..." }

POST /api/routes/generate   # Step4: 周回ルート候補生成、Step5: 標高フィールド追加、Step7: wind_score追加、Step8: road_score/total_score追加
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
        /* ...区間の数だけ続く（12点サンプリング＝11区間前後） */
      ],
      "geometry": { "type":"LineString","coordinates":[...] }
    },
    ...（total_scoreが高い順、最大8件）
  ]
}

GET /api/weather?latitude=35.7597&longitude=139.7387   # Step6: 現在地の天候
Response 200:
{ "temperature_c":24.6, "wind_speed_ms":1.93, "wind_direction_deg":69.0, "wind_direction_label":"東", "precipitation_probability_percent":100.0, "observed_at":"2026-08-13T21:15" }
Response 502（Open-Meteo呼び出し失敗時）:
{ "detail": "天候情報の取得に失敗しました" }

GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf   # Step10改訂: 表示中ビューポート全体の路面データ（OSM/Overpassを自前でMVTに変換したベクタタイル）
Response 200（Content-Type: application/vnd.mapbox-vector-tile）: バイナリのMVT。レイヤー名`road_surface`、各地物（LineString）は`surface_good`プロパティ（true=舗装/false=未舗装/null=不明）を持つ
Response 400（zがROAD_TILE_MIN_ZOOM=12未満、またはROAD_TILE_MAX_ZOOM=15を超える場合）:
{ "detail": "対応していないズームレベルです。" }

GET /api/basemap/{path}   # Step10: OpenFreeMapの地図タイル/スタイルJSON/スプライト/グリフのプロキシ＋キャッシュ
Response 200: 上流（OpenFreeMap）のContent-Typeをそのまま転送
Response 502（上流取得失敗時）:
{ "detail": "地図タイルの取得に失敗しました" }

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
