"""backendを本番へ出すかを決める（`.github/workflows/deploy-backend.yml`が呼ぶ）。

    python scripts/deploy_backend_gate.py <本番で動いているコミット> <出したいコミット>

本番で動いているコミットから出したいコミットまでの変更に、`DEPLOY_PATHS`に当たるファイルが
1つでもあれば出す。判定と理由を1行で出し、GitHub Actionsの中では`$GITHUB_OUTPUT`へ
`deploy=true|false`を書く。

**差分の起点を「直前のpush」ではなく「本番で動いているコミット」に取る。** CIが赤で出せなかった
変更は、次にCIを通ったコミットの差分へそのまま含まれる（直前のpushとの差分では、テストだけを
直したコミットが本番へのコードの変更を運ばず、その変更が次の変更まで出なくなる）。
本番で動いているコミットが分からない・履歴に無いときは出す（出し漏れより出し直しの方が安い）。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

#: 本番のイメージに入り、本番プロセスが読むファイル。GitHubの`paths`と同じ規則で読む:
#: 上から順に当て、最後に当たったものが勝つ（`!`で始まるものは外す）。`*`は`/`を跨がず、
#: `**`は跨ぐ。
DEPLOY_PATHS = (
    "backend/**",
    # ベンチマークはイメージに入らない（backend/Dockerfileのcopy対象外。VM上の作業コピー
    # から実行する）。押しただけでビルドとコンテナ入れ替えを起こさないよう除外し、VMの
    # 作業コピーを新しくしたいときはworkflow_dispatchで明示的に起動する。どのコードを
    # 測ったかは、どの実行口もbenchmarks/_revision.pyが実行時に出力へ残す（まとめて
    # 走らせるrun_allは配信元と違えば止め、個別のベンチは警告に留める）。
    "!backend/benchmarks/**",
    # イメージに入らないもの（backend/DockerfileのCOPY対象外）。
    "!backend/tests/**",
    "!backend/pytest.ini",
    "!backend/ruff.toml",
    "!backend/requirements-dev.txt",
    "!backend/.env.example",
    # イメージに入るが、本番プロセスが読まないもの。生成スクリプトとそれだけが読む表示値で、
    # 変更は生成物（frontend/src/types/generated/）を経由してだけ画面へ届く。
    # **backend/app配下はbackend/tests/structure/test_deploy_exclusions.pyが、本番側から
    # importされていないことを検査する**——importされた時点で、ここに挙げたままでは
    # 変更が本番へ届かなくなる。
    "!backend/scripts/export_openapi.py",
    "!backend/app/domain/map_display.py",
    "!backend/app/domain/display_palette.py",
    "!backend/app/domain/weather_display.py",
    # デプロイの手順そのもの。
    ".github/workflows/deploy-backend.yml",
    "scripts/deploy_backend_gate.py",
)


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    if re.search(r"[?+\[\]]", pattern):
        # GitHubの`?`・`+`は「直前の文字の0〜1回・1回以上」で、一般のglobと意味が違う。
        # 同じ意味で読めない記号は受け付けない。
        raise ValueError(f"対応していない記号を含むパターン: {pattern}")
    parts = re.split(r"(\*\*|\*)", pattern)
    body = "".join(".*" if p == "**" else "[^/]*" if p == "*" else re.escape(p) for p in parts)
    return re.compile(f"^{body}$")


def matches(path: str, patterns: tuple[str, ...] = DEPLOY_PATHS) -> bool:
    included = False
    for pattern in patterns:
        negative = pattern.startswith("!")
        if _pattern_regex(pattern[1:] if negative else pattern).match(path):
            included = not negative
    return included


def decide(relation: str, changed: list[str], patterns: tuple[str, ...] = DEPLOY_PATHS) -> tuple[bool, str]:
    """`relation`は本番で動いているコミット（deployed）と出したいコミット（target）の関係。

    unknown: deployedが分からない／履歴に無い、same: 同じ、older: targetがdeployedの祖先、
    newer: deployedがtargetの祖先、diverged: どちらも祖先でない。
    """
    if relation == "unknown":
        return True, "本番で動いているコミットが分からないため出す"
    if relation == "same":
        return False, "本番は既にこのコミットで動いている"
    if relation == "older":
        return False, "本番はこれより新しいコミットで動いている（後から終わった古いCIの実行）"
    if relation == "diverged":
        return True, "本番のコミットと履歴が分かれているため出す"
    hits = [path for path in changed if matches(path, patterns)]
    if not hits:
        return False, f"本番のイメージに届く変更が無い（変更{len(changed)}件）"
    return True, f"本番のイメージに届く変更が{len(hits)}件ある（例: {hits[0]}）"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def _relation(deployed: str, target: str) -> str:
    if not deployed or _git("cat-file", "-e", f"{deployed}^{{commit}}").returncode != 0:
        return "unknown"
    if _git("rev-parse", deployed).stdout.strip() == _git("rev-parse", target).stdout.strip():
        return "same"
    if _git("merge-base", "--is-ancestor", target, deployed).returncode == 0:
        return "older"
    if _git("merge-base", "--is-ancestor", deployed, target).returncode == 0:
        return "newer"
    return "diverged"


def main(argv: list[str]) -> int:
    deployed, target = argv[1].strip(), argv[2].strip()
    relation = _relation(deployed, target)
    changed: list[str] = []
    if relation == "newer":
        diff = _git("diff", "--name-only", deployed, target)
        if diff.returncode != 0:
            print(diff.stderr, file=sys.stderr)
            return 1
        changed = [line for line in diff.stdout.splitlines() if line]
    deploy, reason = decide(relation, changed)
    print(f"{'出す' if deploy else '出さない'}: {reason}（本番 {deployed[:8] or '不明'} → {target[:8]}）")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"deploy={'true' if deploy else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
