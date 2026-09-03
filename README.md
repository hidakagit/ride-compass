# RideCompass

**ロードバイクで気持ちよく走れる周回ルートを、自動で提案してくれるWebアプリです。**
出発地点と走りたい距離を入れるだけで、坂道の少なさ・風向き・路面の状態・車通りの多さ・
信号の多さ・事故の多さ・夜道の暗さといった「走りやすさ」に関わる要素を考慮したルート
候補がいくつも作られ、その中から好みのものを選べます。

## RideCompassでできること

- **距離と出発地点を指定するだけでルートを自動生成**: 現在地・地図タップ・ドラッグの
  いずれかで出発地点を決め、走りたい距離を入れると、その距離に近い周回ルート（元の場所へ
  戻ってくるルート）や、目的地・経由地を指定したルートを何パターンか自動で作る。
- **「走りやすさ」を自分好みに調整できる**: 「坂道は避けたい」「車の通りが少ない道を
  優先したい」「向かい風になりにくいルートがいい」など、重視したいポイントの比重を
  スライダーで調整でき、その好みに合わせてルート候補の順番が変わる。重視するポイント
  （評価軸と呼んでいる）自体も画面から追加・調整できるようになっている。
- **地図上でルートの大変さが一目でわかる**: 生成したルートを区間ごとに色分け表示し、
  どこが坂道できついか・どこが向かい風になりやすいかなどをひと目で確認できる。区間を
  クリックすると、その場所の詳しい情報（勾配・風の影響・通過予想時刻など）も見られる。
- **地図の見え方を自由に切り替えられる**: 路面の種類・道路の種類・トンネル・一方通行
  ・過去の事故が多い場所など、道路に関する情報を地図に重ねて表示できる。
- **天気・雨雲レーダーを地図で確認できる**: 気温・風向風速・降水確率に加えて、雨雲
  レーダー・雷・大雨や洪水の危険度分布といった気象庁の情報も地図上で時間を追って
  確認できる。
- **獲得標高やアップダウンを事前に把握できる**: 国土地理院の標高データをもとに、
  各ルート候補の獲得標高や最大勾配を計算して表示する。

技術的な設計・実装の詳細（採用技術・API・データモデル等）は
[docs/architecture.md](docs/architecture.md)、機能単位の詳細設計は
[docs/modules/README.md](docs/modules/README.md)を参照。ここから先は開発者向けの情報。

## 主な機能（開発者向け）

- **周回・目的地ルート生成**（`POST /api/routes/generate`）: 自前ホストのRoad Graph
  （OSM由来、PostGIS永続化）+ `scipy.sparse.csgraph`のDijkstra探索で、外部ルーティングAPIに
  依存せずルートを計算する。周回・経由地指定・目的地指定のいずれにも対応し、出発地点は
  現在地取得のほか地図タップ・ドラッグでも指定できる。
- **評価軸ベースのスコアリング**: 勾配・路面・風・車の圧迫感・停止密度・事故密度・夜間などの
  評価軸ごとに0-100の難易度を算出し、重み付き合成した`overall_difficulty`で候補を並べる。
  評価軸自体は「軸スタジオ」（`/admin`、HTTP Basic認証）というGUIから追加・調整でき、
  コード変更や再デプロイなしに評価の観点を増やせる。軸の一覧・現在の重みは
  [docs/architecture.md](docs/architecture.md)の評価軸の節が正本。
- **難易度・評価軸の地図可視化**: ルート区間ごとに勾配・風などで色分け表示し、区間クリックで
  内訳（軸別寄与度・到達予想時刻）を確認できる。評価軸に対応する道路属性は地図レイヤーとしても
  重ね描きできる（路面・道路種別・指定路線・トンネル・一方通行・停止要因POI・事故統計など）。
- **動的な気象・防災レイヤー**: Open-Meteo（気温・風向風速・降水確率）に加え、気象庁の
  降水ナウキャスト・rasrf・雷/竜巻ナウキャスト・キキクル・線状降水帯予測マップ等の動的タイルを
  バックエンド経由でプロキシ・キャッシュして地図へ重ね描きする（時系列スライダー付き）。
- **標高**: 国土地理院DEMタイルをRoad GraphのEdgeへ事前計算で紐付け、探索中の追加API呼び出し
  なしで獲得標高・最大勾配を算出する。地域全体の標高は色別標高図タイルとして常時表示できる。
- **ルート比較・研究モード**: 複数回生成した候補を並べて比較する実験スロット機能、評価軸の
  重み調整UIなど、一般利用者向け画面とは別に研究・軸調整向けの機能を持つ。

## 構成

```
RideCompass/
  frontend/           Next.js (App Router) + TypeScript + MapLibre GL JS
  backend/            FastAPI (Python) + PostGIS
  docs/               設計ドキュメント（architecture.md・modules/・improvement-plan.md等）
  .claude/            レビュー基盤・スキル定義（.claude/commands/review/README.md参照）
  scripts/            リポジトリ横断のCI/pre-commitスクリプト・review_checks.py
  docker-compose.yml  frontend/backend/postgres(PostGIS)/redisを一括起動
  restart-dev.bat / stop-dev.bat   Windows向けのローカル再起動・停止スクリプト（backend/frontendの
                                    残留プロセスをkillしてバックグラウンドで再起動、ログはlogs/へ）
```

## セットアップ

### 前提

- Node.js 20+
- Python 3.11+
- PostgreSQL + PostGIS（Road Graph・路面タイル生成の一次系統。**DBなしでは起動しない**——
  `GraphService`は改善計画T222でDBなし構成を撤去済み）
- Redis（JMA気象データ・road_graph_tilesのcache-aside層。未接続でもフォールバックする箇所が
  一部あるが、ローカル開発でも用意することを推奨）
- Docker / Docker Compose（任意。frontend/backend/postgres/redisをまとめて起動する場合）

### Docker Composeで起動する場合

```bash
cp .env.example .env
docker compose up --build
```

- フロントエンド: http://localhost:3000
- バックエンド: http://localhost:8000/health
- Postgres(PostGIS): localhost:5432
- Redis: localhost:6379

### ローカルで個別起動する場合

#### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
# DATABASE_URLは実接続できるPostGISが必須（.env.exampleのコメント・
# docs/architecture.md「本番/開発プロファイル一覧」参照）
uvicorn app.main:app --reload
```

- ヘルスチェック: `curl http://localhost:8000/health`
- 単一区間ルート確認: `curl -X POST http://localhost:8000/api/routes/preview -H "Content-Type: application/json" -d '{"origin":{"latitude":35.7597,"longitude":139.7387},"destination":{"latitude":35.71,"longitude":139.75}}'`
- 周回ルート生成確認: `curl -X POST http://localhost:8000/api/routes/generate -H "Content-Type: application/json" -d '{"latitude":35.7597,"longitude":139.7387,"distance_km":15,"distance_tolerance_km":5,"route_type":"loop"}'`（対象エリアが未取込・split未済みだと自前Road Graphの構築コストが乗り数十秒かかることがある。レート制限・同時実行数の上限に達すると429が返る）
- テスト: `pytest -q -m "not postgis"`（PostGIS統合テストを含むフルスイートは下記「テスト」参照）

> **注意（`.env`変更時）**: `uvicorn --reload` はPythonファイルの変更は自動検知するが、`.env` の変更は検知しない。編集した場合は一度プロセスを完全に停止し、再起動すること。Windowsでは `--reload` の再起動サイクルでワーカープロセスが残留し、複数プロセスが同じポートを奪い合うことがある（`restart-dev.bat`はこのkillを含めて再起動する）。手動で確認する場合は `netstat -ano | findstr :8000` でPIDを確認し、`taskkill /F /PID <PID>` で終了してから起動し直すこと。

#### Frontend

```bash
cd frontend
npm install
npm run dev
```

ブラウザで http://localhost:3000 を開く。バックエンドのURLは既定で`http://localhost:8000`
（`NEXT_PUBLIC_API_URL`で上書き可、`.env.local`は無くても動く）。

## テスト

```bash
# backend（変更に直接関係するテストだけ絞り込む場合はファイルを指定する）
cd backend
pytest -q -m "not postgis"          # PostGIS統合テストを除いた全件
pytest tests/test_road_graph_engine.py -q

# frontend
cd frontend
npx vitest run                      # 全件
npx vitest run <対象ファイル> --pool=threads
npx tsc --noEmit
npx eslint
```

**注意**: PostGIS統合テスト（`road_graph_session`フィクスチャ使用のテスト群）は、テスト専用DB
（既定`postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass_test`、
`TEST_DATABASE_URL`で上書き可）に接続できない環境では自動的にスキップされる
（[backend/tests/conftest.py](backend/tests/conftest.py)）。CIはpytest-xdistで並列化しているため、
新規のPostGIS統合テストファイルには`loop_scope="module"`・`xdist_group(name="postgis")`の指定が
必要（詳細は[docs/testing.md](docs/testing.md)参照）。

## 補足・既知の注意点

- **ルーティングエンジン**: 自前のRoad Graph（OSM由来、PostGIS永続化）+
  `scipy.sparse.csgraph`のDijkstraで経路計算する
  ([backend/app/services/road_graph_engine.py](backend/app/services/road_graph_engine.py))。
  外部ルーティングAPIへの依存は無い（openrouteservice委譲は改善計画T462で完全撤去済み）。
- **地図タイル**: MapLibre GL JSの地図タイルにはAPIキー不要の[OpenFreeMap](https://openfreemap.org/)を使用し、`BasemapClient`がバックエンド経由でプロキシ・ファイルキャッシュする。`tile.openstreetmap.org`はbulk/非ブラウザアクセスをブロックするポリシーがあるため採用していない。
- **maplibre-glのバージョン固定**: `maplibre-gl`は`^5.24.0`に固定している。最新メジャー（v6系）はWeb WorkerのURL解決方法がNext.jsのバンドラと相性が悪く、地図タイルが永久に読み込まれない不具合を確認したため（詳細は[docs/architecture.md](docs/architecture.md)参照）。
- **JMA動的タイル**: 降水ナウキャスト・rasrf・雷/竜巻ナウキャスト・キキクル等の気象庁タイルは
  `GET /api/jma-tile/{path}`経由でプロキシ・キャッシュする（[docs/modules/backend/weather-dynamic-layers.md](docs/modules/backend/weather-dynamic-layers.md)参照）。
- **標高API**: 国土地理院（GSI）のDEMタイルを使用（APIキー不要、日本国内限定）。Road Graphの
  Edgeへ標高属性を事前計算バッチ（`app/batch/precompute_elevation_attributes.py`）で紐付ける
  （[docs/modules/backend/elevation.md](docs/modules/backend/elevation.md)参照）。
- **天候API**: Open-Meteo Forecast API（APIキー不要）。本番はRenderの共有outbound IPが
  Open-Meteoにレート制限されるため、Oracle Cloud VM上のリレープロキシ経由にしている
  （`OPEN_METEO_BASE_URL`、`backend/.env.example`参照）。
- **評価軸・軸スタジオ**: 評価軸の定義は`axis_definitions`テーブルが唯一の正本で、Python側の
  ハードコード定義は撤去済み。軸の追加・削除・調整は`/admin`の軸スタジオGUI（またはそのAPI）
  経由でのみ行う（`backend/migrations/`は行データを持たない。詳細は
  [docs/modules/backend/axis-studio.md](docs/modules/backend/axis-studio.md)参照）。

## 開発を続ける・タスクの状況を追う

- 直近の設計レビュー結果・進行中の改善タスク一覧: [docs/improvement-plan.md](docs/improvement-plan.md)（各タスクの詳細は`docs/tasks/Txxx.md`）
- ログ・テストの方針: [docs/logging.md](docs/logging.md) / [docs/testing.md](docs/testing.md)
- RideCompass固有の設計原則: [docs/design-principles.md](docs/design-principles.md)
- このリポジトリで作業する際のルール（コミット時の同期ルール等）: [CLAUDE.md](CLAUDE.md)
