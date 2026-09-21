"""デプロイ確認用のプロセス起動時刻。

デプロイのたびにプロセスが再起動される運用のため、この値は「直近のデプロイがいつ
反映されたか」の目安になる。
"""

from datetime import datetime, timezone

STARTED_AT = datetime.now(timezone.utc)
