"""masterの直近CIが赤いことを、手元の作業中に知らせる。

`@postgis`マークのテストは手元の既定実行から外れCIだけが走らせるため、実装へ追随していない
テストがあっても手元は緑のまま気づけない。実際に2026-09-12〜14で3件が同じ型で赤を作り、
ユーザーがCIのログを開くまで2日間気づかれなかった（[T834](docs/records/tasks/T834.md)・
[T835](docs/records/tasks/T835.md)）。**既に赤いCIには新しい赤が埋もれ、「CIが通ったこと」を完了の
根拠にできなくなる。**

`gh`は入っていない環境があるため、GitHubの公開REST APIを直接読む（このリポジトリは公開で、
認証なしに参照できる）。**ネットワークに触れるので、取得できない・遅い・形が違うときは黙って
素通しする**——CIの状態を知るための補助が、コミットやpushを止める理由になってはいけない。

判定の単位はワークフローではなく**「masterの最新コミットに対する結論」**。古いコミットで
失敗したまま新しいコミットで直っている場合に鳴り続けると、警告そのものが無視されるようになる。
"""

import json
import sys
import urllib.error
import urllib.request

REPO = "hidakagit/ride-compass"
RUNS_API = f"https://api.github.com/repos/{REPO}/actions/runs"
API = f"{RUNS_API}?branch=master&per_page=30"
TIMEOUT_SECONDS = 6.0


def fetch_runs(url: str = API, timeout: float = TIMEOUT_SECONDS) -> list[dict] | None:
    """masterの実行履歴。取得できなければNone（呼び出し側は黙って素通しする）。"""
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 固定のhttps URL
            payload = json.load(response)
        runs = payload.get("workflow_runs")
        return runs if isinstance(runs, list) else None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def failing_workflows(runs: list[dict]) -> list[dict]:
    """**masterの最新コミット**について、完了していて失敗しているワークフロー。

    まだ実行中のものは結論が出ていないので対象外——「まだ分からない」を赤として扱うと、
    押すたびに鳴る。
    """
    if not runs:
        return []
    return [run for run in latest_per_workflow(runs, runs[0].get("head_sha")) if is_failure(run)]


def latest_per_workflow(runs: list[dict], head_sha: str | None) -> list[dict]:
    """`head_sha`に対する実行を、ワークフローごとに最も新しい1件へ絞る。

    同じコミットに複数の実行が混ざりうる（手動の再実行・concurrency設定に打ち切られた実行）。
    並びは`created_at`の降順で先頭が新しいが、**同じ秒に作られた実行どうしの順序は保証
    されない**ため、`run_number`（ワークフロー内で単調に増える）が大きい方を採る。値が無い
    応答では並び順のまま先頭を残す。
    """
    latest: dict[str, dict] = {}
    for run in runs:
        if run.get("head_sha") != head_sha:
            continue
        name = run.get("name")
        if not isinstance(name, str):
            continue
        previous = latest.get(name)
        if previous is None or run_number(run) > run_number(previous):
            latest[name] = run
    return list(latest.values())


def is_failure(run: dict) -> bool:
    """完了していて成功ではない実行。実行中のものは結論が出ていないので含めない。"""
    return run.get("status") == "completed" and run.get("conclusion") not in ("success", "skipped", "neutral", None)


def run_number(run: dict) -> int:
    """ワークフロー内で単調に増える実行番号。持たない応答は最古として扱う。"""
    value = run.get("run_number")
    return value if isinstance(value, int) else -1


def format_warning(failures: list[dict]) -> str:
    head = failures[0]
    lines = [
        "",
        f"警告: masterのCIが赤いままです（{head.get('head_sha', '')[:8]} "
        f"{str(head.get('display_title', ''))[:40]}）",
    ]
    for run in failures:
        lines.append(f"      - {run.get('name')}: {run.get('conclusion')}  {run.get('html_url', '')}")
    lines.append("      赤が常態になると、CIが通ったことを完了の根拠にできなくなります。")
    return "\n".join(lines)


def main() -> int:
    runs = fetch_runs()
    if runs is None:
        return 0
    failures = failing_workflows(runs)
    if failures:
        print(format_warning(failures), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
