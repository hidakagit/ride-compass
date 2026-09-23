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

対象エリアが取込範囲の外なら候補0件になる。範囲内でも、タイル材料のキャッシュが冷えている
（初回・派生データの作り直し直後）とDBからの読み出しが乗り、数十秒以上かかることがある。
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

PostGIS統合テスト（`road_graph_session`フィクスチャを使うもの）は、テスト専用DB
（既定`postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass_test`、
`TEST_DATABASE_URL`で上書き可）へ接続できない環境では自動的にスキップされる
（`backend/tests/conftest.py`）。

## リポジトリの構成

```
RideCompass/
  frontend/           Next.js (App Router) + TypeScript + MapLibre GL JS
  backend/            FastAPI (Python) + PostGIS
  docs/               architecture/（構成と設計原則）・modules/（実装の詳細）・
                      conventions/（規約）・improvement-plan.md（台帳）・records/（記録）
  .claude/            レビュー基盤・スキル定義
  scripts/            リポジトリ横断の検査スクリプト
  .githooks/          push直前の門（git config core.hooksPath .githooks で有効化）
  docker-compose.yml  frontend/backend/postgres(PostGIS)/redisを一括起動
  restart-dev.bat / stop-dev.bat   Windows向けの再起動・停止（残留プロセスをkillして
                                    バックグラウンド起動、ログはlogs/へ）
```
