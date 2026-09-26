"""GitHubのREST APIを読む（Actionsの結論等）。並行実行の道具とpre-pushの警告が共有する1か所。

認証なしの問い合わせは接続元のIPごとに1時間60回までで、開発機の全エージェントと司令塔が同じ枠を
使う。`git credential fill`でGitHubのトークンが取れればそれを`Authorization: Bearer`で付け、取れなければ
認証なしで読む（公開リポジトリなので読める）。

- トークンは出力・ログ・例外文に出さない。取得や問い合わせの失敗は、トークンを含まない文言だけを返す。
- 認証の見出しはリダイレクト先へ渡さない。GitHubは問い合わせがリダイレクトされうるとし（ログの
  ダウンロードは署名付きの別のURLへの302）、標準ライブラリのリダイレクトは見出しを引き継ぐため、
  `add_unredirected_header`で付ける（リダイレクトで作り直す要求へ写されない）。

    python scripts/orchestration/github.py                  # 今の問い合わせの枠（認証の有無・上限・残り）
    python scripts/orchestration/github.py wait <40桁のsha>  # そのコミットのCIが全部終わるまで待ち、結論を出す
    python scripts/orchestration/github.py log <40桁のsha>   # そのコミットのCIで落ちたジョブのログの末尾

CIの実行はコミットの完全なsha（40桁）でしか引けない（ActionsのAPIの`head_sha`は短いshaでは実行を返さない）ので、
短いshaは問い合わせる前に断る。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

API_ROOT = "https://api.github.com"
REPO = "hidakagit/ride-compass"
TIMEOUT_SECONDS = 6.0
CREDENTIAL_TIMEOUT_SECONDS = 10
REPO_ROOT = Path(__file__).resolve().parents[2]

_token_cache: list[str | None] = []


def token() -> str | None:
    """git credential fill で取れるGitHubのトークン。取れなければNone。対話で聞き返させない。"""
    if _token_cache:
        return _token_cache[0]
    value = None
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", GIT_ASKPASS="")
    try:
        out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                             capture_output=True, text=True, env=env, cwd=str(REPO_ROOT),
                             timeout=CREDENTIAL_TIMEOUT_SECONDS, check=False)
        if out.returncode == 0:
            value = next((line.split("=", 1)[1] for line in out.stdout.splitlines()
                          if line.startswith("password=")), None) or None
    except (OSError, subprocess.TimeoutExpired):
        value = None
    _token_cache.append(value)
    return value


def request_bytes(url: str, timeout: float = TIMEOUT_SECONDS) -> tuple[bytes | None, dict[str, str], str]:
    """(応答の本文、問い合わせの枠の見出し、失敗の理由)。失敗なら本文はNoneで、理由はトークンを含まない。
    リダイレクトは標準ライブラリが辿り、認証の見出しは転送先へ渡さない（モジュールの冒頭）。"""
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                       "X-GitHub-Api-Version": "2022-11-28"})
        secret = token()
        if secret:
            request.add_unredirected_header("Authorization", f"Bearer {secret}")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            limits = {k: v for k, v in response.headers.items() if k.lower().startswith("x-ratelimit-")}
            return response.read(), limits, ""
    except urllib.error.HTTPError as e:
        limits = {k: v for k, v in (e.headers or {}).items() if k.lower().startswith("x-ratelimit-")}
        e.close()
        return None, limits, f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        return None, {}, type(e).__name__


def request_json(url: str, timeout: float = TIMEOUT_SECONDS) -> tuple[dict | None, dict[str, str], str]:
    """(応答のJSON、問い合わせの枠の見出し、失敗の理由)。失敗ならJSONはNoneで、理由はトークンを含まない。"""
    body, limits, error = request_bytes(url, timeout)
    if body is None:
        return None, limits, error
    try:
        return json.loads(body), limits, ""
    except ValueError as e:
        return None, limits, type(e).__name__


def get_json(url: str, timeout: float = TIMEOUT_SECONDS) -> dict | None:
    return request_json(url, timeout)[0]


def failure_note(error: str, limits: dict[str, str]) -> str:
    """問い合わせに失敗した理由（認証の有無と枠の残りを添える。トークンは含まない）。"""
    auth = "認証付き" if token() else "認証なし"
    remaining = f"{limits.get('X-RateLimit-Remaining', '?')}/{limits.get('X-RateLimit-Limit', '?')}"
    return f"{error or '応答の形が違う'}、{auth}、残り{remaining}"


def actions_runs(query: str, workflow: str | None = None) -> tuple[list[dict] | None, str]:
    """Actionsの実行の一覧（新しい順）と失敗の理由。`query`は`?`の後ろ、`workflow`はワークフローの
    ファイル名（`ci.yml`等）で、指定すればそのワークフローの実行だけを返す。"""
    scope = f"workflows/{workflow}/runs" if workflow else "runs"
    payload, limits, error = request_json(f"{API_ROOT}/repos/{REPO}/actions/{scope}?{query}")
    runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
    return (runs, "") if isinstance(runs, list) else (None, failure_note(error, limits))


#: ジョブのキャッシュに残す実行の件数。監査と定期確認が読むのは直近の実行だけなので、古いものから捨てる。
JOBS_CACHE_ENTRIES = 200


def run_jobs(run_id: int, cache: Path | None = None) -> list[dict] | None:
    """実行のジョブ（名前・状態・結論・開始と終了の時刻・段の名前と結論）。取得できなければNone。

    完了した実行のジョブは以後変わらないので、`cache`（JSONファイル）に持ち、同じ実行を2度問い合わせない
    （定期確認は20分おきに同じ実行を見直すため、キャッシュが無いと枠を毎回使う）。
    """
    key = str(run_id)
    stored: dict = {}
    if cache is not None:
        try:
            stored = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        if isinstance(stored.get(key), list):
            return stored[key]
    payload = get_json(f"{API_ROOT}/repos/{REPO}/actions/runs/{run_id}/jobs?per_page=100")
    raw = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return None
    jobs = [{"id": j.get("id"), "name": j.get("name"), "status": j.get("status"), "conclusion": j.get("conclusion"),
             "started_at": j.get("started_at"), "completed_at": j.get("completed_at"),
             "steps": [{"name": s.get("name"), "conclusion": s.get("conclusion")} for s in j.get("steps") or []]}
            for j in raw if isinstance(j, dict)]
    if cache is not None and jobs and all(j["status"] == "completed" for j in jobs):
        stored = {k: v for k, v in stored.items() if isinstance(v, list)}
        stored[key] = jobs
        kept = dict(list(stored.items())[-JOBS_CACHE_ENTRIES:])
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".tmp")
            tmp.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, cache)
        except OSError:
            pass
    return jobs


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHORT_SHA_NOTE = "完全な40桁のshaを渡す（短いshaではActionsの実行を引けない）"
#: 成功とみなす結論（check_master_ci.is_failure と同じ）。
PASSING = ("success", "skipped", "neutral")
#: CIを待つときの読み直しの間隔と上限（秒）。実行全体は2〜3分かかり、認証なしの枠（1時間60回）は開発機の全員で
#: 分けるので、数秒おきには読まない。
WAIT_INTERVAL_SECONDS = 90
WAIT_TIMEOUT_SECONDS = 20 * 60
LOG_TAIL_LINES = 80


def job_log(job_id: int, timeout: float = 30.0) -> tuple[str | None, str]:
    """ジョブのログの全文と失敗の理由。GitHubは署名付きの別のURLへの302で返し、転送先は転送された認証の見出しを
    拒むので、見出しを転送しない`request_bytes`で読む。"""
    body, limits, error = request_bytes(f"{API_ROOT}/repos/{REPO}/actions/jobs/{job_id}/logs", timeout)
    if body is None:
        return None, failure_note(error, limits)
    return body.decode("utf-8", errors="replace"), ""


def latest_runs(sha: str) -> tuple[list[dict] | None, str]:
    """`sha`に対するワークフローごとの最新の実行（名前の順）と失敗の理由。"""
    from check_master_ci import latest_per_workflow

    runs, error = actions_runs(f"head_sha={sha}&per_page=30")
    if runs is None:
        return None, error
    return sorted(latest_per_workflow(runs, sha), key=lambda r: str(r.get("name"))), ""


def failed_job_logs(sha: str, lines: int = LOG_TAIL_LINES) -> tuple[list[dict], str]:
    """`sha`のCIで失敗したジョブごとの{ワークフロー名・ジョブ名・ジョブのid・ログの末尾`lines`行}と失敗の理由。"""
    if not FULL_SHA_RE.match(sha):
        return [], f"{SHORT_SHA_NOTE}: {sha}"
    runs, error = latest_runs(sha)
    if runs is None:
        return [], error
    out = []
    for run in runs:
        if run.get("status") == "completed" and run.get("conclusion") in PASSING:
            continue
        jobs = run_jobs(int(run["id"]))
        if jobs is None:
            return out, f"{run.get('name')}のジョブを取得できない"
        for job in jobs:
            if job.get("status") != "completed" or job.get("conclusion") in PASSING:
                continue
            text, err = job_log(int(job["id"]))
            tail = "\n".join(text.splitlines()[-lines:]) if text is not None else f"（ログを取得できない: {err}）"
            out.append({"workflow": run.get("name"), "job": job.get("name"), "id": job.get("id"), "log": tail})
    return out, ""


def wait_for_ci(sha: str, *, timeout_s: int = WAIT_TIMEOUT_SECONDS, interval_s: int = WAIT_INTERVAL_SECONDS,
                sleep: Callable[[float], None] = time.sleep) -> tuple[list[dict], str]:
    """`sha`に対する全ワークフローの最新の実行が終わるまで読み直し、(実行の並び、失敗の理由)を返す。
    実行がまだ1件も無いうちは、pushの直後とみなして待つ。時間切れ・短いshaでは理由が空でない。"""
    if not FULL_SHA_RE.match(sha):
        return [], f"{SHORT_SHA_NOTE}: {sha}"
    waited = 0
    runs: list[dict] = []
    while True:
        latest, error = latest_runs(sha)
        if latest is not None:
            runs = latest
            if runs and all(r.get("status") == "completed" for r in runs):
                return runs, ""
        if waited + interval_s > timeout_s:
            why = f"取得できない: {error}" if latest is None else ("実行が無い" if not runs else "結論待ち")
            return runs, f"時間切れ（{waited // 60}分待って{why}）"
        sleep(interval_s)
        waited += interval_s


def verdict_line(run: dict) -> str:
    state = run.get("conclusion") if run.get("status") == "completed" else f"結論待ち（{run.get('status')}）"
    return f"{run.get('name')}: {state}  {run.get('html_url', '')}"


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    parser = argparse.ArgumentParser(description="GitHubのActionsを読む（問い合わせの枠・CI待ち・落ちたジョブのログ）")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("wait", help="コミットのCIが全部終わるまで待ち、結論を出す（全部成功なら0）")
    p.add_argument("sha", help="完全な40桁のsha")
    p.add_argument("--timeout-min", type=int, default=WAIT_TIMEOUT_SECONDS // 60)
    p = sub.add_parser("log", help="コミットのCIで落ちたジョブのログの末尾を出す")
    p.add_argument("sha", help="完全な40桁のsha")
    p.add_argument("--lines", type=int, default=LOG_TAIL_LINES)
    args = parser.parse_args(argv)
    if args.cmd == "wait":
        runs, error = wait_for_ci(args.sha, timeout_s=args.timeout_min * 60)
        for run in runs:
            print(verdict_line(run))
        if error:
            print(error)
        return 0 if runs and not error and all(r.get("conclusion") in PASSING for r in runs) else 1
    if args.cmd == "log":
        logs, error = failed_job_logs(args.sha, args.lines)
        for entry in logs:
            print(f"=== {entry['workflow']} / {entry['job']}（ジョブ {entry['id']}）")
            print(entry["log"])
        if error:
            print(error)
        elif not logs:
            print("落ちたジョブは無い（実行中のものは含めない）")
        return 1 if error else 0
    payload, limits, error = request_json(f"{API_ROOT}/rate_limit")
    auth = "あり（git credential fill）" if token() else "なし"
    if payload is None:
        print(f"問い合わせに失敗: {error}（認証: {auth}）")
        return 1
    print(f"認証: {auth}  上限 {limits.get('X-RateLimit-Limit', '?')}/時  残り {limits.get('X-RateLimit-Remaining', '?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
