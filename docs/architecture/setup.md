# 開発環境の立ち上げ

## 前提

- Node.js 20+
- Python 3.11+
- PostgreSQL + PostGIS（Road Graph・路面タイル生成の一次系統。**DBなしでは起動しない**）
- Redis（JMA気象データの短命キャッシュ。未接続でもフォールバックする箇所が
  一部あるが、ローカル開発でも用意することを推奨）
- Docker / Docker Compose（任意。frontend/backend/postgres/redisをまとめて起動する場合）

## Docker Composeで起動する

```bash
cp .env.example .env
docker compose up --build
```

- フロントエンド: http://localhost:3000
- バックエンド: http://localhost:8000/health
- Postgres(PostGIS): localhost:5432
- Redis: localhost:6379

PostgreSQLの版は本番に合わせてある（[tech-stack.md](tech-stack.md)「DBの版」）。データ形式はメジャー版の
間で互換が無いため、ボリュームは版ごとに名前を分けており、版を上げた直後のDBは空から始まる。
古い版のボリュームは`docker volume ls`で探して消す。

**DBは空から始まる。** スキーマは起動したあとに作る（composeのDBユーザーはスーパーユーザーなので、
`--create-extensions`で必要な拡張もここで入る）:

```bash
docker compose run --rm backend python scripts/bootstrap_database.py --create-extensions --to schema
```

**スキーマを作っても、軸定義が0行のままではbackendは起動しない**（`refresh_axis_definitions`が
0行を起動失敗にする。[axis-studio.md](../modules/backend/axis-studio.md)「まっさらなDBに軸の行は
入らない」）。軸を入れる管理APIも起動したbackendにしか無いため、新しい環境へ軸が入るのは管理データの
バックアップから戻したときだけで、それは本番を作り直すための経路である（[deployment-sync.md](../conventions/deployment-sync.md)
「本番DBを失ったとき」）——composeのDB・クラウドのセッションは**テストを回す場**であり、アプリを実データで
確かめるのは本番か手元の開発機で行う（地図に色を出すには軸のほかに取込済みのデータも要る）。
テスト（`-m postgis`を含む）は軸を要らないので、この状態で回せる。

## クラウドのセッション（Claude Code on the web）

依存の導入とDB・Redisの起動を自動で行う。本体は`scripts/remote_dev/`。

- **環境のセットアップスクリプト**（claude.aiの環境設定の欄。環境の初回・スクリプトの変更時・
  約7日ごとにだけ走り、終わった時点のファイルシステムが以後のセッションの出発点になる）へ
  次の1行を書く:

  ```bash
  d=$(mktemp -d) && git clone -q --depth 1 https://github.com/hidakagit/ride-compass "$d" && bash "$d/scripts/remote_dev/setup.sh"; rm -rf "$d"; true
  ```

  masterの浅いcloneから`setup.sh`を流す（セットアップの時点でリポジトリがどこにあるかに
  依存しないため）。backendのvenvとfrontendの`node_modules`をlockfileのダイジェストごとに
  リポジトリの外（`/opt/ridecompass-dev`）へ作り、postgres・redisのイメージを取る。さらにcomposeの
  postgresを一度起動してボリュームを初期化し（テストの複製元DB`ridecompass_test`も作る）、止めてから終える。
  ボリュームがキャッシュに無いと、毎回の開始で空のボリュームへのinitdbとPostGIS拡張の読み込み（実測で約10秒）が走る。
  composeのプロジェクト名は`ride-compass`に固定している（一時ディレクトリのcloneから流しても、セッションの
  cloneと同じボリュームになるように）。
- **SessionStartフック**（`.claude/settings.json`→`scripts/remote_dev/session_start.sh`）が
  毎セッションの開始時に、`backend/.venv`と`frontend/node_modules`をそこへ繋ぎ（lockfileが
  変わっていれば入れ直す）、dockerdを起こしてcomposeのpostgres・redisを起動し、テストの
  複製元DB`ridecompass_test`を作る。`CLAUDE_CODE_REMOTE`が`true`でない（手元の）セッション
  では何もせずに抜ける。セットアップの欄が空でもフックが依存を入れる（開始が遅くなるだけ）。
  DB・Redisの起動は裏で行い、フックは待たない——保存から戻したディスクでは起動に20秒ほど
  かかる（キャッシュからの開始の実測22秒。温まったディスクなら7〜8秒）。DBを使う前に
  `bash scripts/remote_dev/wait_db.sh`で待つ（起動が済んでいれば即座に返り、失敗ならログの場所を出して
  終了コード1）。
- **環境のキャッシュを作る実行**では、セットアップスクリプトのあとに基盤が`claude --init-only`を
  走らせ、リポジトリの`Setup`フック（trigger `init`）とSessionStartフックがこの順に走る（公式の文書に
  あるのは`--init-only`で`Setup`が走ることだけで、キャッシュ作りの中で走ることは環境マネージャの
  ログでの観測）。新規のセッションも`claude --init`で起動され、同じ順で同じ入力のフックが走るため、
  フックは入力ではなくClaude Code本体（`$CLAUDE_PID`）の起動引数に`--init-only`があるかで見分ける
  （これも観測。文書に無い）。`--init-only`のときだけ`Setup`フックが`setup.sh`を流し、SessionStartは何もしない。
  DBが動いたままファイルシステムが保存されると、以後の開始でpostgresがクラッシュリカバリから
  立ち上がる。セットアップの欄が空でも、この`Setup`フックが依存・イメージ・DBのボリュームをキャッシュへ入れる。
- backend・frontendは手元と同じくネイティブで動かす。クラウドのコンテナの中からは外へ
  直接出られないため、composeのbackend・frontendのイメージはそこではビルドできない
  （`apt-get`・`npm ci`が止まる）。

## 個別に起動する

### backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

`DATABASE_URL`は実接続できるPostGISが必須（`backend/.env.example`のコメント参照）。

確認:

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/api/routes/generate -H "Content-Type: application/json" \
  -d '{"latitude":35.7597,"longitude":139.7387,"distance_km":15,"distance_tolerance_km":5,"route_type":"loop"}'
```

対象エリアが取込範囲の外なら候補0件になる。範囲内でも、道路網全体の配列の置き場
（`backend/data/road_network/`）が今のコードの形で無いと生成は失敗する。置き場はDBを書くバッチ
（取込・派生・`scripts/bootstrap_database.py`）の最後に作られ、材料の式を変えたコードへ
切り替えたときは`python scripts/build_road_network.py`で作り直す（DBから数分）。
レート制限・同時実行数の上限に達すると429が返る。

**`.env`を変えたらプロセスを止めて起動し直す。** `uvicorn --reload`はPythonファイルの変更は
検知するが`.env`は検知しない。Windowsでは`--reload`の再起動サイクルでワーカープロセスが
残留し、同じポートを奪い合うことがある（`restart-dev.bat`はこのkillを含めて再起動する）。
手で確認するなら`netstat -ano | findstr :8000`でPIDを見て`taskkill /F /PID <PID>`。

### frontend

```bash
cd frontend
npm install
npm run dev
```

バックエンドのURLは既定で`http://localhost:8000`（`NEXT_PUBLIC_API_URL`で上書き可、
`.env.local`は無くても動く）。

## テスト

手元で回すのは変更が届く範囲だけで、フルスイートはCIが持つ
（[../conventions/testing.md](../conventions/testing.md)）。

```bash
cd backend && pytest tests/test_road_graph_engine.py -q
cd frontend && npx vitest run <対象ファイル> --pool=threads
cd frontend && npx tsc --noEmit
```

PostGIS統合テスト（`road_graph_session`フィクスチャを使うもの。`postgis`マーカー付き）は、
テスト専用DB（既定は作業ツリーごとのDB、`TEST_DATABASE_URL`で上書き可。
[testing.md](../conventions/testing.md)「テストDBは作業ツリーごとに分かれる」）へ接続できないと
落ちる（スキップにはしない。`backend/tests/conftest.py`）。DBの無い環境では
`-m "not postgis"`で除外して回す。

## リポジトリの構成

```
RideCompass/
  frontend/           Next.js (App Router) + TypeScript + MapLibre GL JS
  backend/            FastAPI (Python) + PostGIS
  docs/               architecture/（構成と設計原則）・modules/（実装の詳細）・
                      conventions/（規約）・improvement-plan.md（台帳）・records/（記録）
  .claude/            レビュー基盤・スキル定義
  scripts/            リポジトリ横断の検査スクリプト・クラウドのセッションの用意（remote_dev/）
  .githooks/          push直前の門（git config core.hooksPath .githooks で有効化）
  docker-compose.yml  frontend/backend/postgres(PostGIS)/redisを一括起動
  restart-dev.bat / stop-dev.bat   Windows向けの再起動・停止（残留プロセスをkillして
                                    バックグラウンド起動、ログはlogs/へ）
```
