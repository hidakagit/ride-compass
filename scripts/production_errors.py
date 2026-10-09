"""本番のbackendが記録したエラーを読み、1件でもあれば失敗する（`.github/workflows/production-watch.yml`が呼ぶ）。

    python scripts/production_errors.py <backendのオリジン> [<この時刻からを読む（ISO 8601）>]

時刻を渡さなければ、今から`DEFAULT_WINDOW`前から読む。読む口は`GET /api/debug/errors`（記録の中身は
`backend/app/infrastructure/error_reports.py`）。backendに届かない・応答が読めないときも失敗する——集める側が
止まっていることも知らせる。失敗はGitHub Actionsの失敗の知らせに乗る。
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

#: 前の回が見つからないときに読む幅。定期の間隔（1時間）に合わせる。
DEFAULT_WINDOW = timedelta(hours=1)
#: backendの応答を待つ上限。
TIMEOUT_SECONDS = 30


def describe(body: dict) -> list[str]:
    """読む口の応答から、出す行を作る。1件も無ければ空。"""
    if body["count"] == 0:
        return []
    lines = [f"本番でエラーが {body['count']} 件記録された（直近 {len(body['recent'])} 件を古い順に出す）"]
    for report in body["recent"]:
        where = f" page={report['page']}" if report["page"] else ""
        request = f" req={report['request_id']}" if report["request_id"] else ""
        lines.append(f"- {report['at']} {report['source']} {report['kind']} {report['name']}{where}{request}")
    return lines


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    origin = argv[1].rstrip("/")
    since = datetime.fromisoformat(argv[2]) if len(argv) == 3 else datetime.now(UTC) - DEFAULT_WINDOW
    url = f"{origin}/api/debug/errors?{urllib.parse.urlencode({'since': since.isoformat()})}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            body = json.load(response)
    except (OSError, ValueError) as exc:
        print(f"本番のbackendからエラーの記録を読めない url={url} error={exc!r}")
        return 1
    lines = describe(body)
    if not lines:
        print(f"{since.isoformat()} からのエラーは無い")
        return 0
    print("\n".join(lines))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
