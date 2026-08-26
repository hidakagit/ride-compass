FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# migrations/scripts: 改善計画T349でfail-fast化した都合上、デプロイパイプライン側で
# `python scripts/apply_migrations.py`（backend/app/infrastructure/migrate.py参照）を
# 起動前に実行してmigrationを適用する必要があり、そのためにイメージへ同梱する
# （以前はappディレクトリのみで、DB未接続時は起動を止めない安全側フォールバックが
# あったためmigration適用漏れがあっても気づかれなかった）。
COPY migrations ./migrations
COPY scripts ./scripts

EXPOSE 8000


# RenderはWebサービスの手前に自前のリバースプロキシ/ロードバランサーを置くため、
# コンテナから見ると全リクエストがRenderの内部プロキシから接続してきたように見える。
# uvicornの--proxy-headers（既定で有効）はX-Forwarded-Forを見てrequest.client.hostを
# 実際の訪問者IPに書き換えられるが、信頼するピアIPの既定値は127.0.0.1のみのため、
# Renderの内部プロキシは信頼されずヘッダーが無視されてしまう。結果として
# infrastructure/rate_limiter.pyの_client_idが「実際の訪問者ごと」ではなく
# 「Renderの内部プロキシ」という単一の値になり、路面タイル/basemapタイルのレート制限を
# デプロイ先の全アクセスがひとつのカウンタで共有してしまい、通常のパン/ズーム操作だけで
# 上限に達して429になる不具合が実機で確認された（ローカルはリバースプロキシを挟まないため
# 再現しない）。コンテナへの着信経路はRenderのプロキシ経由のみのため、
# --forwarded-allow-ips='*'で信頼してよい。
# --no-access-log: アクセスログはapp側のミドルウェア(infrastructure/request_log.py)が
# リクエストID・所要時間付きの1行サマリとして出すため、uvicorn標準のアクセスログは
# 二重になるだけの上に情報が少ない(IDも所要時間も無い)ので止める。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log"]
