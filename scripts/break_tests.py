r"""壊れ方の一覧を1件ずつ実装へ当て、残す側のテストが落ちるかを見て、実装を戻す。

testing.md「そのテストは要るか（3問を順に）」の、消す・まとめる前の確かめ（壊れ方ごとに実装の行を一時に変え、
残す側のテストのファイルだけを回し、編集で戻す）を流す。作る担当も確かめる担当も同じ確かめを打つ。

実行方法（リポジトリの根から。backend のテストを含むなら、backend の依存を持つ python で打つ。pytest はこの python で回す）:
    python scripts/break_tests.py <壊れ方の一覧.json> [--ref <git の版>]

一覧は JSON の配列で、1件は次の組。パスはリポジトリの根からの相対（frontend と backend を1つの一覧に混ぜてよい）。
    {"name": "<消す・まとめるテスト>", "file": "<実装のファイル>", "before": "<壊す前の文字列>",
     "after": "<壊した後の文字列>", "tests": ["<残す側のテストのファイル>", ...]}

- 回す前に全部の件を照らし、どれかが合わなければ1件も回さずに断る: before が実装にちょうど1回現れない（どこを壊したかが
  定まらない）・実装が HEAD から変わっている（戻ったことを `git diff` で見られない）・1件のテストが frontend/ と backend/ に
  またがる・ファイルが無い。
- 壊す前に、全部の件のテストを壊さずに1回回し、落ちるものがあれば回さない（落ちていると、どの壊れ方でも落ちたと出る）。
- 1件ずつ、実装の before を after へ置き換え → その件のテストだけを回す（frontend/ は vitest、backend/ は pytest）→ 元の中身を
  書き戻す → `git diff --exit-code HEAD -- <実装>` で戻ったことを見る。テストが止まっても止められても、書き戻してから終わる。
- `--ref` を渡すと、その版の同じパスのテストを元の隣へ一時の名前で書き出して一緒に回し、前の版で落ちたテストを別に出す
  （前の版が落ちて今のテストが通れば、まとめた先が見ていない）。書き出したものは終わるときに消す。
- 件ごとに落ちたテストの名前を出し、最後に今のテストが1本も落ちなかった件を並べる。そうした件があれば終了コード 1、断ったら 2。
- テストの結果は標準出力から拾わず、作業ツリーの外の一時のファイルへ書かせて読む（vitest の JSON・pytest の JUnit XML）。
  frontend の vitest の設定は JSON の報告を作業ツリーの中へ書くので、標準出力には出ない。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_KEYS = ("name", "file", "before", "after", "tests")


class Refused(Exception):
    """回さずに断る（一覧が合わない・壊す前に落ちる・戻らない・テストの道具が結果を書かない）。"""


@dataclass(frozen=True)
class Breakage:
    name: str
    file: str
    before: str
    after: str
    tests: tuple[str, ...]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=False)


def _side(test: str) -> str:
    return test.split("/", 1)[0]


def load(repo: Path, entries: list[dict]) -> list[Breakage]:
    """一覧を照らして返す。合わない件があれば、全部の理由を並べて断る。"""
    breakages, problems = [], []
    for number, entry in enumerate(entries, 1):
        missing = [key for key in _KEYS if key not in entry]
        if missing:
            problems.append(f"[{number}] 欄が無い: {', '.join(missing)}")
            continue
        b = Breakage(entry["name"], entry["file"], entry["before"], entry["after"], tuple(entry["tests"]))
        path = repo / b.file
        if not path.is_file():
            problems.append(f"[{number}] 実装のファイルが無い: {b.file}")
            continue
        count = path.read_bytes().count(b.before.encode("utf-8"))
        if count != 1:
            problems.append(f"[{number}] 壊す前の文字列が実装に{count}回現れる（ちょうど1回でなければ回さない）: {b.file}")
        if _git(repo, "diff", "--quiet", "HEAD", "--", b.file).returncode != 0:
            problems.append(f"[{number}] 実装が HEAD から変わっている（コミットしてから回す）: {b.file}")
        sides = {_side(test) for test in b.tests}
        if not b.tests or not sides <= {"frontend", "backend"} or len(sides) != 1:
            problems.append(f"[{number}] テストは frontend/ か backend/ の片方だけで1つ以上並べる: {', '.join(b.tests)}")
        problems += [f"[{number}] テストのファイルが無い: {test}" for test in b.tests if not (repo / test).is_file()]
        breakages.append(b)
    if problems:
        raise Refused("一覧が合わないので1件も回さない:\n" + "\n".join(problems))
    return breakages


def ref_copy(test: str) -> str:
    """--ref の版のテストを書き出す一時の名前（元の隣。テストの道具が拾う名前の形を保つ）。"""
    if _side(test) == "frontend":
        return re.sub(r"(\.test\.[^./]+)$", r".break-before\1", test)
    return re.sub(r"\.py$", "_break_before.py", test)


@contextmanager
def ref_copies(repo: Path, ref: str | None, tests: list[str]) -> Iterator[dict[str, str]]:
    """--ref の版のテストを書き出し、一時の名前から元のパスへの対応を渡す。抜けるときに消す。"""
    written: dict[str, str] = {}
    try:
        for test in tests if ref else []:
            shown = _git(repo, "show", f"{ref}:{test}")
            if shown.returncode != 0:
                raise Refused(f"{ref} にテストが無い: {test}")
            copy = ref_copy(test)
            if (repo / copy).exists():
                raise Refused(f"一時の名前が既にある: {copy}")
            (repo / copy).write_text(shown.stdout, encoding="utf-8", newline="")
            written[copy] = test
        yield written
    finally:
        for copy in written:
            (repo / copy).unlink(missing_ok=True)


def vitest_failures(report: dict, frontend: Path) -> list[tuple[str, str]]:
    """vitest の JSON の報告から、落ちた（テストのファイル, テストの名前）。ファイルごと落ちたもの（読み込めない等）も含める。"""
    failures = []
    for result in report["testResults"]:
        file = "frontend/" + Path(os.path.relpath(result["name"], frontend)).as_posix()
        names = [
            " > ".join([*test["ancestorTitles"], test["title"]])
            for test in result["assertionResults"]
            if test["status"] == "failed"
        ]
        if result["status"] == "failed" and not names:
            first_line = (result.get("message") or "").strip().split("\n")[0]
            names = [f"（ファイルが落ちた）{first_line}"]
        failures += [(file, name) for name in names]
    return failures


def pytest_failures(report: ET.Element) -> list[tuple[str, str]]:
    """pytest の JUnit XML（xunit1）から、落ちた（テストのファイル, テストの名前）。集められなかったファイルも含める。"""
    failures = []
    for case in report.iter("testcase"):
        if case.find("failure") is None and case.find("error") is None:
            continue
        file = case.get("file")
        if file is None:  # 集められなかったファイルは、名前にモジュール名だけを持つ
            failures.append((f"backend/{case.get('name', '').replace('.', '/')}.py", "（集められない）"))
            continue
        file = file.replace("\\", "/")
        module = file.removesuffix(".py").replace("/", ".")
        classname = case.get("classname", "")
        prefix = classname[len(module) + 1:] + "::" if classname.startswith(module + ".") else ""
        failures.append((f"backend/{file}", f"{prefix}{case.get('name')}"))
    return failures


def run_tests(repo: Path, tests: list[str], out: Path) -> list[tuple[str, str]]:
    """テストのファイル（同じ側）を回し、落ちた（テストのファイル, テストの名前）を返す。"""
    side = _side(tests[0])
    cwd = repo / side
    relative = [test.removeprefix(f"{side}/") for test in tests]
    if side == "frontend":
        report = out / "vitest.json"
        command = ["node", str(cwd / "node_modules" / "vitest" / "vitest.mjs"), "run", *relative,
                   "--reporter=json", f"--outputFile={report}"]
    else:
        report = out / "pytest.xml"
        command = [sys.executable, "-m", "pytest", *relative, "-q", "-p", "no:cacheprovider",
                   f"--junitxml={report}", "-o", "junit_family=xunit1"]
    report.unlink(missing_ok=True)
    # 毎回空のバイトコードの置き場を渡す。置き換えが同じ長さで同じ秒のうちなら、`.pyc` は更新時刻と大きさで
    # 古いと見分けられず、壊す前のバイトコードが使われて壊れ方が効かない。
    env = {**os.environ, "PYTHONPYCACHEPREFIX": tempfile.mkdtemp(dir=out)}
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", check=False)
    if not report.exists():
        raise Refused(f"{side} のテストが結果を書かなかった:\n{result.stdout}\n{result.stderr}")
    if side == "frontend":
        return vitest_failures(json.loads(report.read_text(encoding="utf-8")), cwd)
    return pytest_failures(ET.parse(report).getroot())


def _by_side(tests: list[str]) -> list[list[str]]:
    return [group for side in ("frontend", "backend") if (group := [t for t in tests if _side(t) == side])]


def run(repo: Path, breakages: list[Breakage], ref: str | None) -> int:
    """全部の件を流して結果を出し、今のテストが1本も落ちなかった件があれば 1 を返す。"""
    tests = sorted({test for b in breakages for test in b.tests})
    with tempfile.TemporaryDirectory() as directory, ref_copies(repo, ref, tests) as copies:
        out = Path(directory)
        copy_of = {test: copy for copy, test in copies.items()}
        broken_before = [f for group in _by_side(tests + list(copies)) for f in run_tests(repo, group, out)]
        if broken_before:
            raise Refused("壊す前に落ちるテストがあるので回さない:\n"
                          + "\n".join(f"  {file} > {name}" for file, name in broken_before))
        silent = []
        for number, b in enumerate(breakages, 1):
            path = repo / b.file
            original = path.read_bytes()
            try:
                path.write_bytes(original.replace(b.before.encode("utf-8"), b.after.encode("utf-8"), 1))
                failures = run_tests(repo, [*b.tests, *(copy_of[t] for t in b.tests if t in copy_of)], out)
            finally:
                path.write_bytes(original)
            if _git(repo, "diff", "--quiet", "HEAD", "--", b.file).returncode != 0:
                raise Refused(f"[{number}] 実装が戻っていない: {b.file}")
            now = sorted((file, name) for file, name in failures if file not in copies)
            before = sorted((copies[file], name) for file, name in failures if file in copies)
            print(f"[{number}] {b.name}")
            print(f"  壊した所: {b.file}")
            print(f"  落ちた（作業ツリーのテスト）: {len(now)}本")
            print("".join(f"    {file} > {name}\n" for file, name in now), end="")
            if ref:
                print(f"  落ちた（{ref} のテスト）: {len(before)}本")
                print("".join(f"    {file} > {name}\n" for file, name in before), end="")
            print("  実装は戻った")
            if not now:
                silent.append(f"[{number}] {b.name}")
    print(f"落ちなかった件: {'、'.join(silent) or 'なし'}")
    return 1 if silent else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="壊れ方の一覧を当て、残す側のテストが落ちるかを見て戻す")
    parser.add_argument("breakages", type=Path, help="壊れ方の一覧（JSON の配列）")
    parser.add_argument("--ref", help="この版の同じパスのテストも一緒に回す（例: origin/master）")
    args = parser.parse_args(argv)
    try:
        return run(REPO, load(REPO, json.loads(args.breakages.read_text(encoding="utf-8"))), args.ref)
    except Refused as refused:
        print(f"[break_tests] {refused}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
