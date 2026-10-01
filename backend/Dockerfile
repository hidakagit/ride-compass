FROM python:3.12-slim

WORKDIR /app

# rasterioのwheelが同梱するGDALはlibexpatへ動的リンクしており、python公式slimイメージには
# 入っていない（`import rasterio`が`ImportError: libexpat.so.1`で落ちる）。manylinuxの
# ポリシーが「配布先にある前提」として同梱を許さないライブラリのため、wheelを新しくしても
# 解決しない。
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# バッチ用の依存も入れる。取込・派生は本番のコンテナの中で動くため、webの応答経路が
# 読まないからといって外すと、DBを立ち上げ直すときにimportで落ちる。
COPY requirements.txt requirements-batch.txt ./
RUN pip install --no-cache-dir -r requirements-batch.txt

COPY app ./app
# 探索のJITをここでコンパイルし、結果（`app/domain/__pycache__`）をイメージに焼く。コンテナを入れ替えた
# 直後の最初のルート生成がコンパイルを待たない。numbaのキャッシュはCPUの型と元のファイルの更新時刻に
# 結び付くが、組み立てと実行は同じVM・同じイメージのファイルで行う。
RUN python -c "from app.domain.routing import compile_search_kernels; compile_search_kernels()"
# scripts: デプロイが起動前に実行する運用スクリプト（土地被覆ラスタの取得等）を同梱する。
COPY scripts ./scripts

EXPOSE 8000


# --proxy-headers・--forwarded-allow-ips: per-IPのレート制限のキー（app/api/rate_limit.py:
# client_id）はrequest.client.hostで、前段のプロキシを通った要求はX-Forwarded-Forを信頼させないと
# 全員がプロキシのIP1つへ潰れ、共有した上限に地図の操作だけで当たって429になる。uvicornが既定で
# 信頼する接続元は127.0.0.1だけ。'*'は接続元を問わずヘッダーを信頼するため、前段を通らずに
# このポートへ届く経路があると、X-Forwarded-Forを偽ってレート制限のキーを選べる（前段の
# プロキシと着信の制限はVM側の設定で、リポジトリには無い）。
# --no-access-log: アクセスログはapp側のミドルウェア(infrastructure/request_log.py)が
# リクエストID・所要時間付きの1行サマリとして出すため、uvicorn標準のアクセスログは
# 二重になるだけの上に情報が少ない(IDも所要時間も無い)ので止める。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log"]
