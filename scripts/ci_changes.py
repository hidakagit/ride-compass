"""変更されたファイルから、CI（`.github/workflows/ci.yml`）のどのジョブを走らせるかを決める（同じファイルの`changes`ジョブが呼ぶ）。

    python scripts/ci_changes.py

変わったファイルを1つずつ`RULES`へ当て、当たったジョブを合わせる。backendのイメージとデプロイは、本番へ出すかの振り分け
（`scripts/deploy_backend_gate.py: DEPLOY_PATHS`・`NOT_DEPLOYED`）に当たるかで決める（振り分けを2か所に持たない）。
結果は`{ジョブ: 走らせるか}`のJSONを1行で出し、GitHub Actionsの中では`$GITHUB_OUTPUT`へ`run=<JSON>`を書く。

**ジョブは、そのジョブが読むものから決める。** 読まないファイルの変更で走らせず、読むファイルの変更では必ず走らせる。
どの行にも当たらないファイルは、読むジョブが分からないので全部を走らせる（読まないと分かったら行を足す）。

**何と比べるか**は出来事で決まる（GitHub Actionsが渡す環境変数`GITHUB_EVENT_NAME`）:
- Pull Request: 向け先のコミット（`ci.yml`が渡す`BASE`）。
- masterのpush: ジョブごとに、masterの祖先のうち、pushの実行でそのジョブが成功した一番近いコミット（実行全体が成功した
  コミットでもよい）。直前のコミットの実行が落ちたか待ちのまま取り消されたとき、その変更はそのジョブで確かめられて
  いないので、この実行の判定に入れる。ジョブごとに見るのは、ほかのジョブ（デプロイ等）だけが落ちた実行のあとで、
  確かめ済みの変更のために通ったジョブを走らせ直さないため。
- 手での実行・比べる相手が見つからないジョブ: 走らせる。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

#: このスクリプトが決めるジョブ（`ci.yml`のジョブのid）。
JOBS = (
    "backend",
    "api-contract",
    "frontend",
    "e2e",
    "e2e-scan",
    "frontend-image",
    "backend-image",
    "deploy-frontend",
    "deploy-backend",
)

_BACKEND_TESTS = frozenset({"backend", "api-contract"})
_FRONTEND_TESTS = frozenset({"frontend", "e2e", "e2e-scan", "api-contract"})
_FRONTEND_APP = _FRONTEND_TESTS | {"frontend-image", "deploy-frontend"}

#: 変えたファイルが要るジョブ（backendのイメージとデプロイを除く）。上から当て、最初に当たった行で決める。書き方はgitの
#: pathspecのglobと同じで、リポジトリの根から当てる（`*`は`/`を跨がず、`**/`は0個以上のディレクトリに当たる）。
RULES: tuple[tuple[str, frozenset[str]], ...] = (
    # 検査の定義そのもの。どのジョブの書き方も変えうる。
    (".github/workflows/ci.yml", frozenset(JOBS)),
    # srcの下の.mdも読む検査がある（frontend/src/structure/caseOnlyPaths.test.ts）ので、下の.mdの行より先に当てる。
    ("frontend/src/**", _FRONTEND_APP),
    # 文書。読む検査は文書だけの変更でも走るdocs-consistency.ymlにある。
    ("**/*.md", frozenset()),
    (".github/actions/postgis/**", frozenset({"backend"})),
    (".github/workflows/deploy-frontend.yml", frozenset({"deploy-frontend"})),
    # backendのテストが読み込む（scripts/review_checks.py: TASKFLOW_PREFIXES）。
    (".github/taskflow-paths", frozenset({"backend"})),
    # ほかのワークフロー・GitHubの設定は、このワークフローのどのジョブも読まない。
    (".github/**", frozenset()),
    ("backend/**", _BACKEND_TESTS),
    # 根のscripts/の道具は、backendのテストが読み込む（backend/tests/script_module.py: load_script）。ただし次の2つは読まない。
    ("scripts/size_thresholds.json", frozenset()),
    ("scripts/remote_dev/**", frozenset()),
    ("scripts/**", frozenset({"backend"})),
    # frontendのイメージはこのファイルで作り、テストとe2eは読まない（e2eはビルドしたstandaloneのサーバーを直接起こす）。
    ("frontend/Dockerfile", frozenset({"frontend-image", "deploy-frontend"})),
    # テストと撮影の足場と、テストだけが読む設定。ビルドに入らず、本番の画面を変えない。
    ("frontend/e2e/**", _FRONTEND_TESTS),
    ("frontend/e2e-live/**", _FRONTEND_TESTS),
    ("frontend/capture/**", _FRONTEND_TESTS),
    ("frontend/playwright*.config.ts", _FRONTEND_TESTS),
    ("frontend/vitest.*", _FRONTEND_TESTS),
    ("frontend/eslint.config.mjs", _FRONTEND_TESTS),
    ("frontend/knip.json", _FRONTEND_TESTS),
    ("frontend/**", _FRONTEND_APP),
    ("docs/**", frozenset()),
    (".claude/**", frozenset()),
    ("tools/**", frozenset()),
    # 手元の開発の道具と設定。CIもイメージも読まない。
    ("docker-compose.yml", frozenset()),
    ("*.bat", frozenset()),
    (".env.example", frozenset()),
)

#: masterのpushで祖先を辿る上限。超えても比べる相手の見つからないジョブは走らせる。
ANCESTOR_LIMIT = 100


def _load_gate():
    spec = importlib.util.spec_from_file_location("deploy_backend_gate", Path(__file__).with_name("deploy_backend_gate.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_GATE = _load_gate()


def _glob_regex(pattern: str) -> re.Pattern[str]:
    parts = re.split(r"(\*\*/|\*\*|\*)", pattern)
    table = {"**/": "(?:.*/)?", "**": ".*", "*": "[^/]*"}
    return re.compile("".join(table.get(p, re.escape(p)) for p in parts) + r"\Z")


_RULES = tuple((_glob_regex(pattern), jobs) for pattern, jobs in RULES)


def jobs_for(path: str) -> frozenset[str] | None:
    """`path`の変更が要るジョブ（backendのイメージとデプロイを除く。`RULES`のどの行にも当たらなければNone）。"""
    for regex, jobs in _RULES:
        if regex.match(path):
            return jobs
    return None


def wanted(changed: list[str], deployed: list[str]) -> frozenset[str]:
    """変わったファイルが要るジョブ。`deployed`は`changed`のうち、backendの本番へ出す振り分けに当たるもの。"""
    jobs: set[str] = set()
    for path in changed:
        hit = jobs_for(path)
        jobs |= set(JOBS) if hit is None else hit
    if deployed:
        jobs.add("deploy-backend")
    if any(path.startswith("backend/") for path in deployed):
        jobs.add("backend-image")
    return frozenset(jobs)


def job_key(name: str) -> str:
    """実行のジョブの一覧に出る名前（`e2e-scan (mobile 1/3)`・`deploy-frontend / deploy`）から、`ci.yml`のジョブのid。"""
    return name.split(" ", 1)[0]


def bases(verified: Iterable[tuple[str, frozenset[str] | None]]) -> dict[str, str | None]:
    """masterのpushで、ジョブごとの比べる相手（見つからなければNone）。

    `verified`は、pushの実行があった祖先のコミットを近い順に、そのコミットで成功したジョブ（実行全体が成功したならNone）
    と組にしたもの。全部のジョブの相手が決まったら、それより先は読まない。
    """
    found: dict[str, str | None] = dict.fromkeys(JOBS)
    for sha, ok in verified:
        for job in JOBS:
            if found[job] is None and (ok is None or job in ok):
                found[job] = sha
        if all(found.values()):
            break
    return found


def _git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def _gh(path: str) -> dict:
    return json.loads(subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True).stdout)


def _push_verified(head: str) -> Iterable[tuple[str, frozenset[str] | None]]:
    repo = os.environ["GITHUB_REPOSITORY"]
    runs = _gh(f"repos/{repo}/actions/workflows/ci.yml/runs?branch=master&event=push&status=completed&per_page=100")
    # 同じコミットに実行が複数あれば、新しいものを使う（一覧の並びに頼らず、作られた時刻で選ぶ）。
    latest: dict[str, dict] = {}
    for run in runs["workflow_runs"]:
        if run["head_sha"] not in latest or run["created_at"] > latest[run["head_sha"]]["created_at"]:
            latest[run["head_sha"]] = run
    for sha in _git("rev-list", "--first-parent", "--skip=1", f"--max-count={ANCESTOR_LIMIT}", head):
        run = latest.get(sha)
        if run is None:
            continue
        if run["conclusion"] == "success":
            yield sha, None
            continue
        results: dict[str, set[str]] = {}
        for job in _gh(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100")["jobs"]:
            results.setdefault(job_key(job["name"]), set()).add(job["conclusion"])
        yield sha, frozenset(key for key, seen in results.items() if seen == {"success"})


def decide(head: str, base_of: dict[str, str | None]) -> dict[str, bool]:
    """ジョブごとに、比べる相手から`head`までの変更がそのジョブを要るか。比べる相手が無い・履歴に無いジョブは走らせる。"""
    result: dict[str, bool] = {}
    cache: dict[str, frozenset[str]] = {}
    for job in JOBS:
        base = base_of[job]
        if not base or subprocess.run(["git", "cat-file", "-e", f"{base}^{{commit}}"], capture_output=True, check=False).returncode != 0:
            print(f"{job}: 比べる相手が無いので走らせる")
            result[job] = True
            continue
        if base not in cache:
            changed = _git("diff", "--name-only", base, head)
            deployed = _git("diff", "--name-only", base, head, "--", *_GATE.pathspec(_GATE.DEPLOY_PATHS, _GATE.NOT_DEPLOYED))
            for path in changed:
                if jobs_for(path) is None:
                    print(f"読むジョブが分からないので全部を走らせる: {path}")
            cache[base] = wanted(changed, deployed)
        result[job] = job in cache[base]
        print(f"{job}: {base[:8]} と比べて{'走らせる' if result[job] else '飛ばす'}")
    return result


def main() -> int:
    head = os.environ["GITHUB_SHA"]
    event = os.environ.get("GITHUB_EVENT_NAME")
    base_of: dict[str, str | None] = dict.fromkeys(JOBS)
    if event == "pull_request":
        base_of = dict.fromkeys(JOBS, os.environ.get("BASE") or None)
    elif event == "push":
        try:
            base_of = bases(_push_verified(head))
        except subprocess.CalledProcessError as e:
            print(f"masterの実行を読めないので、全部を走らせる: {e.stderr}")
    line = json.dumps(decide(head, base_of))
    print(line)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"run={line}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
