"""`scripts/check_master_ci.py`の判定テスト（ネットワークには触れない）。

取得そのものは外部に依存するため、ここでは「取れたデータから何を赤と呼ぶか」だけを固定する。
"""

import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_master_ci", Path(__file__).resolve().parents[2] / "scripts" / "check_master_ci.py"
)
check_master_ci = importlib.util.module_from_spec(_SPEC)
sys.modules["check_master_ci"] = check_master_ci
_SPEC.loader.exec_module(check_master_ci)

failing_workflows = check_master_ci.failing_workflows
format_warning = check_master_ci.format_warning

HEAD = "0dcaf69a847ace8e9277eafea7a04ba8e3067dd3"
OLD = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _run(name, conclusion, sha=HEAD, status="completed"):
    return {
        "name": name,
        "conclusion": conclusion,
        "status": status,
        "head_sha": sha,
        "display_title": "テスト用",
        "html_url": f"https://example.invalid/{name}",
    }


def test_all_green_reports_nothing():
    runs = [_run("CI", "success"), _run("Docs Consistency", "success")]

    assert failing_workflows(runs) == []


def test_failure_on_the_latest_commit_is_reported():
    runs = [_run("CI", "success"), _run("Docs Consistency", "failure")]

    failures = failing_workflows(runs)

    assert [run["name"] for run in failures] == ["Docs Consistency"]


def test_failure_on_an_older_commit_is_not_reported():
    # 古いコミットで落ちたまま最新では直っている場合に鳴り続けると、警告そのものが無視される
    # ようになる。判定の単位はワークフローではなく「masterの最新コミットに対する結論」。
    runs = [_run("CI", "success"), _run("Docs Consistency", "failure", sha=OLD)]

    assert failing_workflows(runs) == []


def test_in_progress_run_is_not_treated_as_red():
    # 「まだ分からない」を赤として扱うと、pushのたびに鳴る。
    runs = [_run("CI", None, status="in_progress")]

    assert failing_workflows(runs) == []


def test_only_the_newest_run_of_each_workflow_counts():
    # 再実行で直った場合、古い失敗が先頭より後ろに残る。APIは新しい順に返す。
    runs = [_run("CI", "success"), _run("CI", "failure")]

    assert failing_workflows(runs) == []


def test_cancelled_and_timed_out_count_as_red():
    # 成功していない以上、「CIが通った」を完了の根拠にはできない。
    runs = [_run("CI", "cancelled"), _run("Docs Consistency", "timed_out")]

    assert {run["name"] for run in failing_workflows(runs)} == {"CI", "Docs Consistency"}


def test_skipped_is_not_red():
    runs = [_run("Deploy Backend to Oracle VM", "skipped")]

    assert failing_workflows(runs) == []


def test_empty_history_reports_nothing():
    assert failing_workflows([]) == []


def test_warning_names_the_workflow_and_links_to_the_run():
    # 「赤い」とだけ言われても、どれを見ればよいか分からなければ動けない。
    failures = failing_workflows([_run("Docs Consistency", "failure")])

    message = format_warning(failures)

    assert "Docs Consistency" in message
    assert "https://example.invalid/Docs Consistency" in message
    assert HEAD[:8] in message
