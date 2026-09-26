"""`scripts/flow.py` の入口・取り込み・遷移・出口・スロットを、一時的な git のリポジトリと偽の gh で確かめる。

GitHub はプロセス境界なので `flow.gh` を偽物に差し替える。偽物は gh が返す形（issue の一覧・GraphQL の欄の値・
Actions の実行）を持ち、単一選択の欄に無い選択肢を書こうとすると gh と同じく失敗する。git は本物を使う。
"""

import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import flow  # noqa: E402

REPO = "owner/tasks"
HOLD = ("--review", "2999-01-01")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


class FakeGh:
    def __init__(self) -> None:
        self.issues: list[dict] = []
        self.fields: dict[str, dict] = {}
        self.runs: dict[str, list[dict]] = {}

    def issue(self, number: int | str) -> dict:
        return next(i for i in self.issues if i["number"] == int(number))

    def __call__(self, *args: str) -> str:
        opt = {args[i]: args[i + 1] for i in range(len(args) - 1) if args[i].startswith("-")}
        cmd = args[:2]
        if cmd == ("issue", "list"):
            return json.dumps([{k: v for k, v in i.items() if k != "comments"} for i in self.issues])
        if cmd == ("issue", "view"):
            issue = self.issue(args[2])
            return json.dumps({"body": issue["body"], "comments": [{"body": c} for c in issue["comments"]]})
        if cmd == ("issue", "create"):
            url = f"https://github.com/{REPO}/issues/{len(self.issues) + 1}"
            self.issues.append({"number": len(self.issues) + 1, "title": opt["--title"], "body": opt["--body"],
                                "state": "OPEN", "labels": [], "url": url, "comments": []})
            return url + "\n"
        if cmd == ("issue", "edit"):
            self.issue(args[2])["title"] = opt["--title"]
        elif cmd == ("issue", "comment"):
            self.issue(args[2])["comments"].append(opt["--body"])
        elif cmd == ("issue", "close"):
            self.issue(args[2]).update(state="CLOSED")
        elif cmd == ("project", "item-add"):
            self.fields[opt["--url"]] = {}
        elif cmd == ("project", "item-edit"):
            values, name = self.fields[opt["--url"]], opt["--field"]
            if "--clear" in args:
                values.pop(name, None)
            elif name in flow.SELECT_OPTIONS and opt["--value"] not in flow.SELECT_OPTIONS[name]:
                raise flow.FlowError(f"{name} に選択肢 {opt['--value']} が無い")
            else:
                values[name] = opt["--value"]
        elif cmd == ("api", "graphql"):
            kind = {"SINGLE_SELECT": "name", "TEXT": "text", "DATE": "date", "NUMBER": "number"}
            nodes = [{"content": {"url": url}, "fieldValues": {"nodes": [
                {kind[flow.FIELDS[n]]: float(v) if flow.FIELDS[n] == "NUMBER" else v, "field": {"name": n}}
                for n, v in values.items()]}} for url, values in self.fields.items()]
            return json.dumps([{"data": {"user": {"projectV2": {"items": {"nodes": nodes}}}}}])
        elif cmd == ("run", "list"):
            return json.dumps(self.runs.get(opt["--commit"], []))
        return ""

    def state(self, number: int) -> str | None:
        issue = self.issue(number)
        return flow.state_of({**issue, "fields": self.fields.get(issue["url"], {})})

    def field(self, number: int, name: str) -> str | None:
        return self.fields[self.issue(number)["url"]].get(name)

    def label(self, number: int, name: str) -> None:
        self.issue(number)["labels"].append({"name": name})


@pytest.fixture
def world(tmp_path, monkeypatch):
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "test")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "test@example.com")
    origin, main = tmp_path / "origin.git", tmp_path / "main"
    git(tmp_path, "init", "--quiet", "--bare", "-b", "master", str(origin))
    git(tmp_path, "clone", "--quiet", str(origin), str(main))
    git(main, "switch", "--quiet", "-c", "master")
    (main / "docs" / "records" / "tasks").mkdir(parents=True)
    (main / "docs" / "records" / "tasks" / "T5.md").write_text("# T5\n", encoding="utf-8")
    git(main, "add", "docs")
    git(main, "commit", "--quiet", "-m", "T5 段階B: 土台")
    git(main, "push", "--quiet", "origin", "master")
    git(main, "config", "flow.repo", REPO)
    git(main, "config", "flow.project", "1")
    monkeypatch.chdir(main)
    fake = FakeGh()
    monkeypatch.setattr(flow, "gh", fake)
    return main, fake


def run(*args: str) -> int:
    return flow.main(list(args))


def admitted(fake: FakeGh, title: str, *extra: str) -> int:
    """承認して入口を通した ① の issue の番号。"""
    assert run("propose", title, *extra) == 0
    fake.label(len(fake.issues), flow.APPROVAL_LABEL)
    assert run("take") == 0
    return len(fake.issues)


def test_doc_transition_table_is_the_code_table():
    doc = (ROOT / "docs" / "conventions" / "flow.md").read_text(encoding="utf-8")
    rows = {(m[1], m[2]): (m[3], m[4]) for m in re.finditer(r"^\| (\S+) → (\S+) \| (.+?) \| (.+?) \|$", doc, re.M)}

    assert rows == flow.TRANSITIONS


def test_take_numbers_approved_proposals_after_records_and_issues(world):
    _, fake = world
    run("propose", "承認されていない")
    fake.issues.append({"number": 2, "title": "T7-A: 見送った", "body": "", "state": "CLOSED", "labels": [],
                        "url": f"https://github.com/{REPO}/issues/2", "comments": []})
    new = admitted(fake, "新しいタスク")
    stage = admitted(fake, "段を足す", "--task", "T5")

    assert (fake.state(1), fake.issue(1)["title"]) == ("①", "承認されていない")
    assert fake.issue(new)["title"] == "T8-A: 新しいタスク"
    assert fake.issue(stage)["title"] == "T5-C: 段を足す"
    assert (fake.state(new), fake.field(new, "段"), fake.field(new, "次に動かす人")) == ("③", "T8-A", "司令塔")

    fake.label(1, flow.DROP_LABEL)
    run("take")
    assert fake.state(1) == flow.DONE


def test_move_refuses_what_the_table_does_not_have(world):
    _, fake = world
    number = admitted(fake, "作業")

    assert run("move", "T6-A", "⑤") == 1
    assert run("move", "T6-A", "②", "--by", "司令塔", "--missing", "x", *HOLD) == 1
    assert run("move", "T6-A", "④") == 0
    assert run("move", "T6-A", "③") == 1
    assert fake.state(number) == "④"


def test_user_hold_is_answered_by_checking_one_choice_and_extends_once(world):
    _, fake = world
    number = admitted(fake, "作業")
    run("move", "T6-A", "④")
    ask = ("--by", "ユーザー", "--missing", "どちらで測るか", *HOLD)

    assert run("move", "T6-A", "②", *ask) == 1  # 選択肢が無い
    assert run("move", "T6-A", "②", *ask, "--choice", "本番", "--choice", "開発DB") == 0
    assert run("move", "T6-A", "②", "--review", "2999-02-01") == 0
    assert run("move", "T6-A", "②", "--review", "2999-03-01") == 1
    assert (fake.field(number, "見直す日"), fake.field(number, "延ばした回数")) == ("2999-02-01", "1")

    run("take")
    assert fake.state(number) == "②"
    question = next(i for i, c in enumerate(fake.issue(number)["comments"]) if "- [ ] 本番" in c)
    fake.issue(number)["comments"][question] = fake.issue(number)["comments"][question].replace("- [ ] 本番",
                                                                                                "- [x] 本番")
    run("take")
    assert (fake.state(number), fake.field(number, "見直す日")) == ("③", None)
    assert "答え: 本番" in fake.issue(number)["comments"][-1]


def work_branch(main: Path, stage: str, subject: str, body: str) -> str:
    git(main, "switch", "--quiet", "-c", f"orch/{stage}", "origin/master")
    (main / f"{stage}.txt").write_text("作業\n", encoding="utf-8")
    git(main, "add", ".")
    git(main, "commit", "--quiet", "-m", subject, "-m", body)
    git(main, "push", "--quiet", "origin", f"orch/{stage}")
    git(main, "switch", "--quiet", "master")
    return git(main, "rev-parse", f"orch/{stage}")


def test_land_needs_green_ci_and_releases_the_stage_waiting_for_it(world):
    main, fake = world
    number = admitted(fake, "作業")
    waiting = admitted(fake, "前提を待つ", "--body", "前提: T6-A")
    assert (fake.state(waiting), fake.field(waiting, "欠けているもの")) == ("②", "T6-A")
    run("move", "T6-A", "④")
    work_branch(main, "T6-A", "T6-B: 別の段の件名", "検証: x")
    assert run("move", "T6-A", "⑤") == 1

    git(main, "push", "--quiet", "origin", "--delete", "orch/T6-A")
    git(main, "branch", "--quiet", "-D", "orch/T6-A")
    sha = work_branch(main, "T6-A", "T6-A: 作業が済む", "検証: pytest → 1 passed")
    assert run("move", "T6-A", "⑤") == 0
    fake.runs[sha] = [{"name": "CI", "status": "completed", "conclusion": "failure", "url": "u"}]
    assert run("land", "T6-A") == 1
    assert git(main, "ls-remote", "origin", "master").split()[0] != sha

    fake.runs[sha][0]["conclusion"] = "success"
    assert run("land", "T6-A") == 0
    assert git(main, "ls-remote", "origin", "master").split()[0] == sha
    assert (fake.state(number), fake.state(waiting)) == (flow.DONE, "③")


def hook(monkeypatch, command: str, payload: dict) -> int:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode("utf-8"))))
    return run(command)


def test_slots_are_lent_once_and_kept_while_work_would_be_lost(world, monkeypatch, capsys):
    lent = []
    for _ in range(flow.SLOTS):
        assert hook(monkeypatch, "hook-create", {"name": "担当"}) == 0
        lent.append(Path(capsys.readouterr().out.strip()))
    assert len(set(lent)) == flow.SLOTS
    assert hook(monkeypatch, "hook-create", {"name": "担当"}) == 1

    (lent[0] / "作業中.txt").write_text("x", encoding="utf-8")
    hook(monkeypatch, "hook-remove", {"worktree_path": str(lent[0])})
    assert hook(monkeypatch, "hook-create", {"name": "担当"}) == 1

    (lent[0] / "作業中.txt").unlink()
    hook(monkeypatch, "hook-remove", {"worktree_path": str(lent[0])})
    capsys.readouterr()
    assert hook(monkeypatch, "hook-create", {"name": "次の担当"}) == 0
    assert Path(capsys.readouterr().out.strip()) == lent[0]
