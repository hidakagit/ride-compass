FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

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
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
