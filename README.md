# RideCompass

ロードバイク愛好者向けに、現在地から指定距離の周回ルートを自動生成するWebアプリのプロトタイプ。

距離・獲得標高・風向風速・道路特性などを考慮し、ロードバイクで走りやすい周回ルートを複数候補から選択できることを目指す。詳細な設計思想・技術選定・ロードマップは [docs/architecture.md](docs/architecture.md) を参照。

## 現在の進捗

- ✅ **Step 1**: Next.js + MapLibre GL JS で地図を表示（現在地取得 / 取得失敗時は東京・王子付近にフォールバック / 緯度経度の手動入力）
- ✅ **Step 2**: FastAPI バックエンドを作成し、フロントエンドから疎通確認（`GET /health`）
- ✅ **Step 3**: openrouteservice に接続し、現在地→クリックした地点までのルート取得を確認（`POST /api/routes/preview`、疎通確認用の暫定機能）
- ✅ **Step 4**: 周回ルート生成（`POST /api/routes/generate`）。距離を入力して「ルート生成」を押すと、現在地を起点・終点とする周回ルート候補が最大8件（8方位）生成され、地図に描画。候補リストから選ぶと地図上のハイライトが切り替わる
- ✅ **Step 5**: 獲得標高の計算（国土地理院標高API）。各候補ルートの獲得標高・最高/最低標高・最大勾配を算出し、候補リストに獲得標高を表示
- ✅ **Step 6**: 天候表示（Open-Meteo API）。現在地の気温・風向風速・降水確率を画面上部に表示。バックエンドは「地点＋時刻」を指定できる設計にしてあり、将来「ルート上の各点を通過する推定時刻の天気」を出す拡張がしやすいようにしてある
- ✅ **Step 7**: 風評価（`wind_score`）。各周回ルート候補について、ルート上のサンプル点ごとに「仮定巡航速度（20km/h）から逆算した推定到達時刻」の風向風速をStep6の`WeatherService`から取得し、進行方位との関係（向かい風/追い風/横風）から区間距離加重平均の`wind_score`を算出、候補リストに表示。値は符号付きm/s（正=正味向かい風、負=正味追い風）で、正規化・重み付けはStep8で行う
- ✅ **Step 8**: 総合スコアリング（`total_score`）。距離の近さ・獲得標高・`wind_score`・路面の舗装率（`road_score`、openrouteserviceの`extra_info=surface`から取得）の4指標を、候補集合内でmin-max正規化した上で`scoring.yaml`の重みで合成し0-100点の`total_score`を算出。候補リストは`total_score`が高い順（最も良い候補が先頭）に並ぶ
- ✅ **Step 9**: 候補ルートの難易度可視化。地図上にルートを区間（約12点サンプリング＝11区間）ごとの色分けで重ね描きする。標高・勾配・風・路面のいずれも、ロードバイク走行の一般的な目安に基づく絶対基準（Step8の相対評価とは異なる）で緑（易しい）〜赤（難しい）に着色。区間クリックで「距離・到達予想時刻・勾配・風・路面」のポップアップを表示し、時系列（推定到達時刻）を考慮した見方ができる
- ✅ **UI再構成**: 左サイドバー（操作パネル・候補一覧、折りたたみ可）＋右地図の2ペインレイアウトに変更。地図レイヤーは「変わらないデータ（標高・路面）」と「時間で変わるデータ（風）」で扱いを分離: 標高/路面は選択に関係なく**全候補**へチェックON/OFFで常時重ね描きし、風は選択中の候補にのみ自動で色分け表示する。選択中候補は色分けの種類に関わらず常時ハロー（薄い縁取り）で識別できる
- ✅ **Step 10**: 地域レイヤー（標高＝国土地理院 色別標高図のラスタタイル、路面＝自前生成のベクタタイル`GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf`）。候補ルートの有無に関わらず、**表示中の地図の範囲全体**に標高・OSM/Overpassの路面データを重ね描きできるようにした（Step5-9はいずれも「候補ルート沿い」限定だったのに対し、地域全体を対象にする点が新しい）。標高・路面とも「変わらないデータはタイル表示で統一する」方針のもと、標高は国土地理院の色別標高図タイルをそのまま重ね、路面はOverpassから取得したOSMデータをバックエンドでMVT（Mapbox Vector Tile）形式に変換し、地図タイルと同じファイルキャッシュで永続化して配信する。MapLibreのvector sourceとして扱えるため、区間クリックで路面情報を見るポップアップも維持している。**標高と路面は排他ではなく同時に重ね表示できる**。あわせて、地図タイル（OpenFreeMap）をバックエンド経由でプロキシ＋ファイルキャッシュする仕組み（`GET /api/basemap/{path}`, `POST /api/basemap/refresh`）も追加し、初回以降はオフラインに近い形で地図を表示できるようにした
- ✅ **フロントエンドUX改善**: スマホ幅（640px以下）では左サイドバーを画面上に重なる開閉式ドロワーに変更し、背景タップ・スワイプ・Escapeキーで閉じられるようにした。地図右下に「現在地に移動」ボタンを追加し、位置情報を再取得できるようにした（失敗時はエラー表示）。サイドバーのチェックボックスで有効化できる「デバッグモード」では、地図のタイル取得・API呼び出しの詳細ログを画面下部に表示する
- ✅ **バックエンド: 自前Road Graphルーティングの試験実装＋エンジン切り替え**: `/api/routes/generate`のルート生成を、自前のRoad Graph（OSM/Overpass由来）+NetworkX（Dijkstra）で行う実装を試験的に追加した。ただし自前ルーティング自体はまだ発展途上のため、現状はマップの見える化・評価に必要な情報（標高・風・路面）の精査を優先し、`.env`の`ROUTING_ENGINE`設定で従来のopenrouteservice委譲（既定）とRoad Graphのどちらを使うか切り替えられるようにしてある（詳細は[docs/architecture.md](docs/architecture.md)参照）
- ⬜ Step 11以降: 未定（現時点でMVPの主要機能は一通り実装済み）

## 構成

```
RideCompass/
  frontend/   Next.js + TypeScript + MapLibre GL JS
  backend/    FastAPI (Python)
  docs/       設計ドキュメント
  docker-compose.yml
```

## セットアップ

### 前提

- Node.js 20+
- Python 3.11+
- Docker / Docker Compose（任意。frontend/backend/postgresをまとめて起動する場合）

### Docker Composeで起動する場合

```bash
cp .env.example .env
docker compose up --build
```

- フロントエンド: http://localhost:3000
- バックエンド: http://localhost:8000/health
- Postgres(PostGIS): localhost:5432（Road Graph/Road Attributeの永続化用にSQLAlchemy+GeoAlchemy2の読み書きコードは実装済みだが、このdev環境では実接続の検証ができておらず、`GraphService`/`ElevationAttributeService`へ`repository`を明示的に注入しない限り既存のAPIエンドポイントはどれもこのDBを使わない。詳細は[docs/architecture.md](docs/architecture.md)9章参照）

### ローカルで個別起動する場合

#### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
# .env の OPENROUTESERVICE_API_KEY に openrouteservice.org で取得したキーを設定
# ROUTING_ENGINE は既定値openrouteservice。road_graphに変えると自前Road Graphルーティング（試験実装、APIキー不要）を使う
uvicorn app.main:app --reload
```

- ヘルスチェック: `curl http://localhost:8000/health`
- 単一区間ルート確認: `curl -X POST http://localhost:8000/api/routes/preview -H "Content-Type: application/json" -d '{"origin":{"latitude":35.7597,"longitude":139.7387},"destination":{"latitude":35.71,"longitude":139.75}}'`
- 周回ルート生成確認: `curl -X POST http://localhost:8000/api/routes/generate -H "Content-Type: application/json" -d '{"latitude":35.7597,"longitude":139.7387,"distance_km":15,"distance_tolerance_km":5,"route_type":"loop"}'`（8方位分のopenrouteservice呼び出し＋各候補の標高・風評価取得のため10秒前後かかる。openrouteservice無料枠は日次2000リクエストが上限で、連続実行すると消費するので注意。1クライアントIPあたり1分間10回・プロセス全体で同時2件のレート制限があり、超過分は429が返る）
- 天候確認: `curl "http://localhost:8000/api/weather?latitude=35.7597&longitude=139.7387"`
- テスト: `pytest`

> **注意（`.env`変更時）**: `uvicorn --reload` はPythonファイルの変更は自動検知するが、`.env` の変更は検知しない。APIキーなど `.env` を編集した場合は一度プロセスを完全に停止し、再起動すること。Windowsでは `--reload` の再起動サイクルでワーカープロセスが残留し、複数プロセスが同じポートを奪い合うことがある。挙動がおかしい場合は `netstat -ano | findstr :8000` でポートを握っているPIDを確認し、`taskkill /F /PID <PID>` で全て終了してから起動し直すこと。

#### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

ブラウザで http://localhost:3000 を開くと、地図（現在地 or 東京・王子付近）と、バックエンドの疎通状況（`Backend: OK`）が表示される。

## 補足・既知の注意点

- **地図タイル**: MapLibre GL JS の地図タイルには、APIキー不要の [OpenFreeMap](https://openfreemap.org/) を使用している。`tile.openstreetmap.org` は bulk/非ブラウザアクセスをブロックするポリシーがあるため採用していない。本番運用時は利用規約を確認の上、専用プロバイダへの切り替えを検討すること。
- **maplibre-gl のバージョン固定**: `maplibre-gl` は `^5.24.0` に固定している。最新メジャー（v6系）は Web Worker のURL解決方法が Next.js のバンドラ（Turbopack / Webpack）と相性が悪く、地図タイルが永久に読み込まれない不具合を確認したため。詳細は [docs/architecture.md](docs/architecture.md) を参照。
- **ルーティングエンジン**: openrouteservice API（`cycling-road`プロファイル）を暫定利用。`RoutingService`（[backend/app/services/routing_service.py](backend/app/services/routing_service.py)）を挟んでいるため、将来Valhalla等へ差し替え可能。APIキーは無料枠でも1分あたりのレート制限があるため、ルート生成を連打すると一時的に502が返ることがある。
- **周回ルート生成のヒューリスティック**: 8方位×固定半径（距離の1/3）で候補地点を決める簡易方式。周回生成戦略は[backend/app/services/route_generator.py](backend/app/services/route_generator.py)（エンジン非依存の単一実装）が持ち、経由地点間の経路計算・評価は`ROUTING_ENGINE`設定に応じて[backend/app/services/openrouteservice_engine.py](backend/app/services/openrouteservice_engine.py)（既定）または[backend/app/services/road_graph_engine.py](backend/app/services/road_graph_engine.py)（自前Road Graph、試験実装）へ委譲する。レスポンスの`engine`フィールドでどちらが生成したか識別できる。適応的な半径調整は行っていないため、方位によって実際の距離にばらつきが出る（デフォルトの許容差は±5km）。詳細・既知の制約は [docs/architecture.md](docs/architecture.md) を参照。
- **標高API**: 国土地理院（GSI）標高APIを使用（APIキー不要、日本国内限定）。1リクエスト=1地点のAPIのため、各ルートを12点にサンプリングして問い合わせる（[backend/app/services/elevation_service.py](backend/app/services/elevation_service.py)）。当初リクエストごとに新規コネクションを張っていたため15km生成に約57秒かかっていたが、コネクション再利用に直してから約7秒に短縮した（実機検証で確認済み）。さらに緯度経度を丸めたキーでSQLiteに永続化するキャッシュ（[backend/app/infrastructure/elevation_client.py](backend/app/infrastructure/elevation_client.py)・[backend/app/infrastructure/cache_db.py](backend/app/infrastructure/cache_db.py)）を追加し、起点が同じ再生成では標高取得分（全体の1〜2割程度）を短縮している。プロセス再起動やコンテナ再作成をまたいで使い回される永続キャッシュで、サイズ上限・退避（LRU等）は無い点、タイル一括取得への発展は将来課題（[docs/architecture.md](docs/architecture.md) 参照）。
- **天候API**: Open-Meteo Forecast APIを使用（APIキー不要）。`current`（現在の気象）と`hourly`（当日+翌日の時間別予報）を1回のリクエストでまとめて取得し、緯度経度を丸めたキーで30分TTLのキャッシュを行う（[backend/app/infrastructure/weather_client.py](backend/app/infrastructure/weather_client.py)）。`WeatherService.get_conditions(point, at=...)`は時刻を指定できる設計にしてあり、Step6のUIでは「現在の天候」のみ表示するが、将来ルート上の各点＋推定到達時刻を渡す形にそのまま拡張できる。
- **風評価（`wind_score`）**: `WindService`（[backend/app/services/wind_service.py](backend/app/services/wind_service.py)）が各候補ルートを12点サンプリングし、区間ごとに「起点からの累積距離 ÷ 仮定巡航速度20km/h」で推定到達時刻を計算、その地点・時刻の風を`WeatherService.get_conditions(point, at=...)`（Step6）から取得する。走行方位は`geo.py`の`bearing_between`で区間ごとに算出し、`WindCalculator.wind_penalty`（[backend/app/domain/wind.py](backend/app/domain/wind.py)）で`風速 × cos(風向 − 走行方位)`から向かい風/追い風の度合いを計算、区間距離で加重平均した値を`wind_score`（符号付きm/s、正=向かい風・負=追い風）として返す。仮定巡航速度は現状固定値で、将来ユーザー設定可能にする拡張ポイント。天候はTTLキャッシュ済みのため、近接するサンプル点は追加リクエストなしで評価できる。
- **路面評価（`road_score`）と総合スコア（`total_score`）**: openrouteserviceへの既存のルート取得リクエストに`extra_info: ["surface"]`を追加するだけで、追加APIコールなしに区間ごとの路面種別内訳が取得できる（[backend/app/infrastructure/ors_client.py](backend/app/infrastructure/ors_client.py)）。`domain/road.py`の`paved_percent`が舗装系路面（Paved/Asphalt/Concrete/Paving Stones）の占める割合を`road_score`（0-100%）として算出する。`RouteScorer`（[backend/app/services/route_scorer.py](backend/app/services/route_scorer.py)）が、距離目標との近さ・獲得標高・`wind_score`・`road_score`の4指標を**その回に生成された候補集合内でmin-max正規化**（`domain/scoring.py`）した上で、`backend/app/scoring.yaml`の重み（`distance_weight`/`elevation_weight`/`wind_weight`/`road_weight`、デフォルトはそれぞれ0.30/0.15/0.30/0.25）で合成し`total_score`（0-100点）を算出する。相対評価のため異なるリクエスト間の`total_score`は比較できない点に注意。獲得標高は「小さいほど高得点」というMVPの解釈（走りやすさ優先、ヒルクライム志向への対応は将来課題）。一部の指標が取得できなかった候補は、残りの指標の重みだけで再正規化して合成する。
- **openrouteserviceのレート制限確認**: 無料枠は日次2000リクエスト。上限に達すると`403 Access to this API has been disallowed`が返る（通常のレスポンスヘッダーに`x-ratelimit-limit`/`x-ratelimit-remaining`/`x-ratelimit-reset`が含まれるので、プログラムから残数を確認できる）。挙動が不審な場合は残数を確認すること。
- **難易度可視化（`RouteCandidate.segments`）**: Step5-7-8で候補ごとに12点サンプリングして取得していた標高・風・路面の生データは、集約値（`elevation_gain_m`等）だけ残して区間ごとの詳細は捨てていた。Step9はこれを捨てずに`segments`（区間＝11件前後）として返すだけで実現しており、**追加のAPIコールは一切発生しない**。標高（`ElevationService.get_profile`）と風（`WindService.get_wind_profile`）は同じ点集合（`domain/geo.py`の`sample_line_points`）を共有するようリファクタし、路面はopenrouteserviceの`extras.surface.values`（区間ごとのインデックス範囲）を`domain/road.py`の`surface_id_at_index`で同じインデックスに対応させている。区間ごとの難易度（`domain/difficulty.py`）は、Step8の`total_score`（候補集合内の相対評価）とは異なり、勾配（0-3%易しい〜9%以上激坂）・向かい風風速（0-8m/sで0→100）・路面種別という**絶対基準**で0-100点化しており、地図上で「客観的にどこが大変か」を示す。密度（12点=11区間）を上げると地図はより滑らかになるが、GSI/Open-Meteoへの問い合わせ数が比例して増え生成時間が伸びるため、既存のサンプリング密度をそのまま踏襲している（既知の制約）。
- **UI再構成（サイドバー＋地図レイヤーの静的/動的分離）**: `MapView`（[frontend/src/components/Map/MapView.tsx](frontend/src/components/Map/MapView.tsx)）は4種類のMapLibreレイヤーを常設する構成に変更した: ①`route-candidates-line`（全候補のベース表示、amber/blue）、②`route-static-segments-line`（**全候補**のセグメントを標高/路面で色分け、選択に関わらず表示）、③`route-selected-outline-line`（選択中候補の常時ハロー、最背面）、④`route-detail-segments-line`（選択中候補のみの風の色分け、最前面）。①と②は`visibility`レイアウトプロパティで排他的に切り替え、③は常時、④は「風の影響を表示」チェックがONかつ選択中候補にセグメントがある場合のみ表示する。区間クリックのポップアップは②③両レイヤーを対象にクエリし、静的レイヤーのポップアップには`direction_label`（例:「南西方向」）を添えてどの候補の区間かを明示する。標高・路面のチェックボックスは当初「同じ線の色を奪い合う」という理由で単一値による排他制御にしていたが、Step10で標高がラスタタイル表示になり色の競合が解消されたため、`showElevation`/`showRoad`の独立した2状態に変更した（同時表示可、後述のStep10改訂参照）。
- **MapLibreの`isStyleLoaded()`起因の描画スキップ**: 当初、地図初期化直後にレイヤーを追加する際「`map.isStyleLoaded()`がfalseならスタイルの`load`イベントを待ってから描画する」というガードを各描画関数に入れていたが、`isStyleLoaded()`はタイル読み込み中（候補選択時の`fitBounds`によるカメラ移動など）にも一時的にfalseを返すため、`load`イベントが二度と発火しない（初回読み込み時に一度だけ発火する仕様）タイミングでガードに引っかかると、その描画が永久にスキップされる不具合があった（風レイヤーが選択直後に表示されないという形で顕在化、Playwright実機確認で発見）。スタイルが一度でも読み込まれたかどうかをmapインスタンス自身にフラグとして記録する`runWhenStyleReady`ヘルパーに置き換えて解消した。
- **地域レイヤー（標高・路面の常時オーバーレイ、Step10）**: 標高は国土地理院の色別標高図（ラスタタイル、`https://cyberjapandata.gsi.go.jp/xyz/relief/{z}/{x}/{y}.png`、APIキー不要）を`MapView`（[frontend/src/components/Map/MapView.tsx](frontend/src/components/Map/MapView.tsx)）が直接MapLibreのraster sourceとして半透明（不透明度0.55）で重ね描きする。当初は国土地理院の標高API（1点=1リクエスト）をグリッド状に問い合わせて点で描画していたが、「点だとわかりにくい」というフィードバックを受けて、標準的な地図として塗られた色別標高図タイルをそのまま重ねる方式に変更した（バックエンドAPIを介さずフロントエンドから直接取得。地理院タイルは別オリジンのため、地図タイル用に分離したフロントエンドオリジンとも接続数が競合しない）。
- **路面のベクタタイル化（Step10改訂）**: 当初、路面はビューポートのbboxで`GET /api/region/road-surface`にリクエストしGeoJSONの線データを返す設計だったが、「変わらないデータはタイル表示で統一したい」という要望を受け、標高と同じくXYZタイルとして配信する方式に作り直した。`RegionService.get_road_surface_tile(z, x, y)`（[backend/app/services/region_service.py](backend/app/services/region_service.py)）が、タイルのz/x/yから求めた範囲（`domain/region.py`の`tile_bounds_lonlat`、標準的なスライピータイル座標式）でOverpassに問い合わせ、`infrastructure/vector_tile.py`の`encode_road_surface_tile`でMVT（Mapbox Vector Tile、`mapbox-vector-tile`ライブラリ使用）にエンコードする。**生成したタイルは基礎地図タイルと同じファイルキャッシュ（`infrastructure/tile_cache.py`）にz/x/y単位で永続化**し、「変わらないデータを更新」ボタン一つで両方まとめてクリアできる（Step9まで使っていた路面専用のSQLiteテーブル`road_surface_cache`は不要になり削除した）。フロントエンドは`GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf`をMapLibreの`type: "vector"`ソースとして直接読み込む（`MapView.tsx`の`ensureRoadSurfaceTileLayer`）ため、Step9まであった「パン/ズーム終了を検知してbboxをfetchする」独自ロジック（デバウンス処理含む）は不要になり、MapLibre自身がタイル単位で自動的にパン/ズームに追随して取得するようになった。ビューポートが広すぎる場合の「ズームインしてください」表示も、bbox対角距離の計算ではなく、路面ベクタタイルの`minzoom`（12、`ROAD_TILE_MIN_ZOOM`）と現在のズームレベルを比較するだけの単純な判定に置き換わった（標高はラスタタイルのためこの判定の対象外）。路面は`ROAD_SURFACE_COLOR_EXPRESSION`で舗装=緑/未舗装=赤/不明=グレーに塗り分け、MVTは地物データを保持したベクタ形式のため区間クリックでの路面情報ポップアップも従来通り機能する。座標変換は緯度経度→Web Mercator→タイルローカル座標（0-4096）の標準的な手順（[backend/app/infrastructure/vector_tile.py](backend/app/infrastructure/vector_tile.py)）で行っており、Overpassの取得範囲をタイル境界でクリップしていないため、タイル境界をまたぐ道路はタイル範囲をわずかに超える座標を含むことがある（MVT仕様上は許容される値で、MapLibre側の描画時クリップに委ねている）。**標高・路面は独立したチェックボックスで、排他ではなく同時に重ね表示できる**（標高ラスタは他のレイヤーより先に追加し常に背景寄りに描画されるため、路面の色分け線やルート線が隠れることはない）。候補ルートの選択状態とは独立に常時表示できる。
- **地図タイルのバックエンド経由プロキシ＋キャッシュ（Step10）**: `BasemapClient`（[backend/app/infrastructure/basemap_client.py](backend/app/infrastructure/basemap_client.py)）がOpenFreeMap（`tiles.openfreemap.org`）のスタイルJSON・スプライト・グリフ・タイルを透過的にプロキシしつつ、ファイルシステム（`backend/data/tile_cache/`、[backend/app/infrastructure/tile_cache.py](backend/app/infrastructure/tile_cache.py)）にキャッシュする。フロントエンドは`next.config.ts`のrewritesで`/api/basemap/*`と`/api/region/road-surface-tiles/*`（路面ベクタタイル、Step10改訂）の両方をバックエンドへプロキシし、ブラウザからは常にフロントエンドと同一オリジン（`:3000`）に見えるようにしている。地図タイルとAPI呼び出しを別オリジンから同一オリジンにまとめた結果、大量のタイルリクエストがブラウザのオリジン単位の同時接続数上限（HTTP/1.1で6本程度）を埋めてしまいAPI呼び出しが詰まる問題が実機確認で発覚したため、あえて地図タイル（路面ベクタタイルも含む）はAPI呼び出し（`:8000`直接）とは別オリジン（フロントエンド`:3000`経由）に分離してある。スタイルJSON内のOpenFreeMap本体への絶対URLは、自分自身（`BASEMAP_PUBLIC_BASE_URL`、既定値`http://localhost:3000/api/basemap`）への絶対URLに書き換えてから返す（MapLibreは相対URLをスタイル自身の取得元ではなくページのオリジンに対して解決してしまうため、絶対URLへの書き換えが必須）。**既知の制約**: このURL書き換え後の内容をそのままファイルキャッシュするため、`BASEMAP_PUBLIC_BASE_URL`の値を変更した場合は古いURLが埋め込まれたキャッシュが残り続ける（キャッシュには書き換え元の設定値を記録していないため自動検知できない）。「変わらないデータを更新」ボタン（`POST /api/basemap/refresh`）でキャッシュを全消去すれば解消する。Windowsでは、URLのパス構造をそのままディレクトリ階層にミラーリングすると「同名のファイルがあるためディレクトリを作成できない」というエラーで実際にクラッシュすることを実機確認したため、パスをSHA-256でハッシュ化しフラットなファイル名で保存する方式にしている。
- **ベクタタイルの取得はWeb Worker内で行われる点に注意**: MapLibreはラスタタイル（`Image`要素、メインスレッド）とベクタタイル（`fetch`、Web Worker内）でタイルの取得方法が異なる。ラスタタイルのURLは相対パスのままページのオリジンに対して解決されるが、ベクタタイルのURLをWorker内から相対パスのまま`fetch`しようとすると`Failed to construct 'Request'`のエラーで失敗することを実機確認した（Workerの実行コンテキストではベースURLが異なるため）。そのため路面ベクタタイルのURLは`window.location.origin`を使って明示的に絶対URL化している（[frontend/src/services/regionApi.ts](frontend/src/services/regionApi.ts)の`roadSurfaceTileUrl()`。`window`はクライアントサイドでしか使えないため、モジュール読み込み時の定数ではなく呼び出し時に評価する関数にしてある点にも注意）。

## テスト

```bash
cd backend
pytest
```

**注意**: PostGIS統合テスト（`test_road_graph_repository.py`等、`road_graph_session`フィクスチャ使用）は、テスト専用DB（既定`postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass_test`、`TEST_DATABASE_URL`で上書き可）に接続できない環境では自動的に`pytest.skip`される（[backend/tests/conftest.py](backend/tests/conftest.py)）。全件成功と表示されても、これらのテストが実際に実行されたとは限らない点に注意。
