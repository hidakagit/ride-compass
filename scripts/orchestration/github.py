"""GitHubのREST APIを読む（Actionsの結論等）。並行実行の道具とpre-pushの警告が共有する1か所。

認証なしの問い合わせは接続元のIPごとに1時間60回までで、開発機の全エージェントと司令塔が同じ枠を
使う。`git credential fill`でGitHubのトークンが取れればそれを`Authorization: Bearer`で付け、取れなければ
認証なしで読む（公開リポジトリなので読める）。

- トークンは出力・ログ・例外文に出さない。取得や問い合わせの失敗は、トークンを含まない文言だけを返す。
- 認証の見出しはリダイレクト先へ渡さない。GitHubは問い合わせがリダイレクトされうるとし（ログの
  ダウンロードは署名付きの別のURLへの302）、標準ライブラリのリダイレクトは見出しを引き継ぐため、
  `add_unredirected_header`で付ける（リダイレクトで作り直す要求へ写されない）。

    python scripts/orchestration/github.py      # 今の問い合わせの枠（認証の有無・上限・残り）
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
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


def request_json(url: str, timeout: float = TIMEOUT_SECONDS) -> tuple[dict | None, dict[str, str], str]:
    """(応答のJSON、問い合わせの枠の見出し、失敗の理由)。失敗ならJSONはNoneで、理由はトークンを含まない。"""
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                       "X-GitHub-Api-Version": "2022-11-28"})
        secret = token()
        if secret:
            request.add_unredirected_header("Authorization", f"Bearer {secret}")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            limits = {k: v for k, v in response.headers.items() if k.lower().startswith("x-ratelimit-")}
            return json.load(response), limits, ""
    except urllib.error.HTTPError as e:
        limits = {k: v for k, v in (e.headers or {}).items() if k.lower().startswith("x-ratelimit-")}
        return None, limits, f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        return None, {}, type(e).__name__


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
    jobs = [{"name": j.get("name"), "status": j.get("status"), "conclusion": j.get("conclusion"),
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


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    payload, limits, error = request_json(f"{API_ROOT}/rate_limit")
    auth = "あり（git credential fill）" if token() else "なし"
    if payload is None:
        print(f"問い合わせに失敗: {error}（認証: {auth}）")
        return 1
    print(f"認証: {auth}  上限 {limits.get('X-RateLimit-Limit', '?')}/時  残り {limits.get('X-RateLimit-Remaining', '?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
