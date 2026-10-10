"""変異ごとに落ちたテストを記録する pytest のプラグイン（runner.py が `-p mutkill` で読ませる）。

書き先は環境変数 MUTKILL_DIR の下の <プロセスの id>.tsv（変異・テスト・落ちた段）。変異の欄は MUTKILL_NAME があればそれ
（基準の実行は変異を入れないので、runner.py が基準の名前を渡す）。
"""
import os


def _write(nodeid, when):
    mutant = os.environ.get("MUTKILL_NAME") or os.environ.get("MUTANT_UNDER_TEST", "")
    with open(os.path.join(os.environ["MUTKILL_DIR"], f"{os.getpid()}.tsv"), "a", encoding="utf-8") as out:
        out.write(f"{mutant}\t{nodeid}\t{when}\n")


def pytest_runtest_logreport(report):
    if report.failed:
        _write(report.nodeid, report.when)


def pytest_collectreport(report):
    if report.failed:
        _write(report.nodeid, "collect")
