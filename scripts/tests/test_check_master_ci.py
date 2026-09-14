"""masterのCIが赤かどうかの判定（改善計画T853）。

この経路は実行するたびにネットワークへ出るため、判定そのものは応答の形だけで確かめる。
"""

import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_master_ci", Path(__file__).resolve().parents[1] / "check_master_ci.py"
)
check_master_ci = importlib.util.module_from_spec(_SPEC)
sys.modules["check_master_ci"] = check_master_ci
_SPEC.loader.exec_module(check_master_ci)


def run(name, conclusion, *, number, sha="aaaa1111", status="completed"):
    return {
        "name": name,
        "head_sha": sha,
        "status": status,
        "conclusion": conclusion,
        "run_number": number,
        "html_url": f"https://example.test/{number}",
        "display_title": "ある変更",
    }


def names(runs):
    return sorted(r["name"] for r in check_master_ci.failing_workflows(runs))


def test_reports_a_failing_workflow_on_the_head_commit():
    assert names([run("CI", "failure", number=2), run("Docs", "success", number=1)]) == ["CI"]


def test_a_run_cancelled_by_concurrency_does_not_make_a_green_commit_red():
    # 同じコミットへ続けてpushすると、先行の実行が打ち切られて同じ秒に2組並ぶ。APIの
    # 並びは打ち切られた側が先に来ることがあるため、run_numberの大きい方を最新とする。
    runs = [
        run("Docs Consistency", "cancelled", number=644),
        run("CI", "success", number=1052),
        run("Docs Consistency", "success", number=645),
        run("CI", "cancelled", number=1051),
    ]

    assert names(runs) == []


def test_a_cancelled_run_alone_is_not_red():
    # 打ち切りは「失敗した」ではなく「判定が無い」。押すたびに鳴る理由にしない。
    assert names([run("CI", "cancelled", number=1)]) == []


def test_an_unfinished_run_is_not_red():
    assert names([run("CI", None, number=1, status="in_progress")]) == []


def test_an_older_commit_that_failed_is_ignored():
    # 古いコミットで失敗したまま新しいコミットで直っている場合に鳴り続けると、警告そのものが
    # 無視されるようになる。
    runs = [
        run("CI", "success", number=2, sha="bbbb2222"),
        run("CI", "failure", number=1, sha="aaaa1111"),
    ]

    assert names(runs) == []


def test_a_rerun_that_now_passes_clears_the_earlier_failure():
    runs = [
        run("CI", "success", number=3),
        run("CI", "failure", number=2),
    ]

    assert names(runs) == []
