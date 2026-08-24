"""デプロイ確認用のプロセス起動時刻。

デプロイ（＝git pushからのビルド完了）のたびにプロセスが再起動される運用
（Render／改善計画T263のOracle VM向けdeploy-backend.ymlのいずれも）のため、
このタイムスタンプは「直近のデプロイがいつ反映されたか」の目安になる
（`app.config.settings.git_commit`と組み合わせて`/health`が返す。詳細はdocs/architecture.md参照）。
インポート時（プロセス起動時）に一度だけ評価される。
"""

from datetime import datetime, timezone

STARTED_AT = datetime.now(timezone.utc)
