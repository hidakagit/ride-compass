"""デプロイ確認用のプロセス起動時刻。

RenderはWebサービスへのデプロイ（＝git pushからのビルド完了）のたびにプロセスを
再起動するため、このタイムスタンプは「直近のデプロイがいつ反映されたか」の目安になる
（`app.config.settings.render_git_commit`と組み合わせて`/health`が返す。詳細はdocs/architecture.md参照）。
インポート時（プロセス起動時）に一度だけ評価される。
"""

from datetime import datetime, timezone

STARTED_AT = datetime.now(timezone.utc)
