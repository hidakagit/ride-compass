"""CIのジョブごとの所要を、masterの直近の成功した実行の同じジョブと比べる（規約
docs/conventions/orchestration.md「監査の項目と合格の基準」の項目10）。監査（`audit`）と定期確認（`check`）が使う。

- 基準は、対象のコミットの祖先にあたるmasterのコミットに対するCIの成功した実行の新しい`BASELINE_RUNS`件。
  変更を入れる前のmasterと比べるため、対象より後にmasterへ入った実行は含めない。
- masterと作業ブランチで走る段が違うジョブ（ci.ymlの`if: github.ref`で分けた段・ジョブ）は、同じ名前でも
  中身が違うので比べず「比べられない」と出す。どの段が違うかはci.ymlを読まず、実行の結果（一方で飛ばされ、
  もう一方で走った段）から導く。
- GitHubへの問い合わせは`orchestration.github`を通す。ジョブは実行ごとにキャッシュし（`github.run_jobs`）、
  1回の比較で増える問い合わせは実行の一覧と、まだ読んでいない実行のジョブだけにする。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from orchestration import github

CI_WORKFLOW = "ci.yml"
#: 規約の項目10の値。監査と定期確認はどちらもここを読む。
BASELINE_RUNS = 5
MARGIN_SECONDS = 60
#: masterの成功した実行を一度に読む件数。対象の土台がこれより古ければ、基準の件数が減る（出力に件数が出る）。
MASTER_LISTING = 30
#: 定期確認で見る、全ブランチの完了した実行の件数。
BRANCH_LISTING = 30
JOBS_CACHE_NAME = "ci_jobs.json"


@dataclass
class Row:
    job: str
    seconds: int | None
    baseline: list[int] = field(default_factory=list)
    differs: list[str] = field(default_factory=list)
    master_only_job: bool = False

    @property
    def over(self) -> int | None:
        """基準の最大値からの伸び（秒）。比べられなければNone。"""
        if self.master_only_job or self.differs or not self.baseline or self.seconds is None:
            return None
        return self.seconds - max(self.baseline)

    @property
    def needs_user(self) -> bool:
        return self.over is not None and self.over >= MARGIN_SECONDS


def _time(value: object) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def job_seconds(job: dict) -> int | None:
    start, end = _time(job.get("started_at")), _time(job.get("completed_at"))
    return int((end - start).total_seconds()) if start and end and job.get("status") == "completed" else None


def _steps(job: dict, skipped: bool) -> set[str]:
    return {str(s.get("name")) for s in job.get("steps") or []
            if (s.get("conclusion") == "skipped") == skipped and s.get("conclusion") is not None}


def compare(target: list[dict], baseline: list[list[dict]]) -> list[Row]:
    """対象の実行のジョブごとに、基準の実行の同じジョブ（成功したもの）の所要を並べる。"""
    rows = []
    for tj in sorted(target, key=lambda j: str(j.get("name"))):
        name = str(tj.get("name"))
        same = [j for run in baseline for j in run if j.get("name") == name and j.get("conclusion") == "success"]
        if tj.get("conclusion") == "skipped":
            if same:
                rows.append(Row(name, None, [s for j in same if (s := job_seconds(j)) is not None], master_only_job=True))
            continue
        ran, skipped = _steps(tj, False), _steps(tj, True)
        differs = {s for j in same for s in _steps(j, False) & skipped}
        differs |= {s for s in ran if same and all(s in _steps(j, True) for j in same)}
        rows.append(Row(name, job_seconds(tj), [s for j in same if (s := job_seconds(j)) is not None],
                        sorted(differs)))
    return rows


def baseline_runs(master_runs: list[dict], target: dict, ancestors: set[str] | None) -> list[dict]:
    """対象の実行の基準にするmasterの実行（新しい順、同じコミットの再実行は1件）。`ancestors`は対象の
    コミットの祖先のsha。Noneなら（コミットが手元に無い）対象より前に作られた実行で代える。"""
    picked: list[dict] = []
    seen = {target.get("head_sha")}
    created = str(target.get("created_at") or "")
    for run in master_runs:
        sha = run.get("head_sha")
        if sha in seen or run.get("conclusion") != "success":
            continue
        if (sha not in ancestors) if ancestors is not None else not str(run.get("created_at") or "") < created:
            continue
        seen.add(sha)
        picked.append(run)
        if len(picked) == BASELINE_RUNS:
            break
    return picked


def master_runs() -> tuple[list[dict] | None, str]:
    return github.actions_runs(f"branch=master&event=push&status=success&per_page={MASTER_LISTING}", CI_WORKFLOW)


def compare_run(target: dict, ancestors: set[str] | None, cache_dir: Path | None,
                masters: list[dict]) -> tuple[list[Row] | None, list[dict], str]:
    """(ジョブごとの行、基準にした実行、取得できなかった理由)。"""
    cache = cache_dir / JOBS_CACHE_NAME if cache_dir else None
    base = baseline_runs(masters, target, ancestors)
    target_jobs = github.run_jobs(int(target["id"]), cache)
    if target_jobs is None:
        return None, base, "対象の実行のジョブを取得できない"
    base_jobs = [jobs for run in base if (jobs := github.run_jobs(int(run["id"]), cache)) is not None]
    if len(base_jobs) < len(base):
        return None, base, "基準の実行のジョブを取得できない"
    return compare(target_jobs, base_jobs), base, ""


def row_line(row: Row) -> str:
    base = row.baseline
    span = f"最大{max(base)}秒（{min(base)}〜{max(base)}、{len(base)}回）" if base else "無し"
    if row.master_only_job:
        return f"{row.job}: 比べられない（masterでだけ走るジョブ。基準 {span}）"
    now_text = "未完了" if row.seconds is None else f"{row.seconds}秒"
    if not base:
        return f"{row.job}: {now_text}  比べられない（masterの基準の実行に無いジョブ）"
    if row.differs:
        return (f"{row.job}: {now_text}  比べられない（masterと作業ブランチで走る段が違う: {'、'.join(row.differs)}。"
                f"基準 {span}は参考）")
    over = row.over
    diff = "" if over is None else f"  差 {over:+d}秒"
    mark = f"  → ユーザー確認（項目10: 基準の最大より{MARGIN_SECONDS}秒以上長い）" if row.needs_user else ""
    return f"{row.job}: {now_text}  基準 {span}{diff}{mark}"
