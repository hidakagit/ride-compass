"""`scripts/orchestrate.py`の状態の表・門・定期確認・監査の機械項目を、一時的なgitリポジトリで入口のコマンドから
確かめる（監査だけは同じプロセスで回し、GitHubへの問い合わせを差し替える）。

台帳・記録はorigin/masterから読まれるので、一時的なリポジトリのmasterに台帳の行と記録を置いてpushする。状態の表は
`--dir`で一時的なディレクトリへ向け、実物の表に触れない。
"""

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

ENTRY = Path(__file__).resolve().parents[2] / "scripts" / "orchestrate.py"
PLAN = "# 台帳\n\n## 節A\n\n- [ ] [T1](records/tasks/T1.md). 走っているタスク 規模S\n"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def ago(minutes: int) -> str:
    """`minutes`分前の時刻。秒まで書く——分へ切り捨てると最大59秒古くなり、道具が経過を分へ切り捨てて出す値が
    分の終わり近くで1分ずれる。"""
    return (dt.datetime.now().astimezone() - dt.timedelta(minutes=minutes)).isoformat(timespec="seconds")


@pytest.fixture
def world(tmp_path, monkeypatch):
    """masterに台帳（T1は規模S・未完了）と記録（T2は完了）を置き、回の母集団をT1・T2にした表。
    所要の実績が無いので、規模Sの予算は規模札の定義の60分になる。"""
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "test")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "test@example.com")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    origin, main, orch = tmp_path / "origin.git", tmp_path / "main", tmp_path / "orch"
    git(tmp_path, "init", "--quiet", "--bare", "-b", "master", str(origin))
    git(tmp_path, "clone", "--quiet", str(origin), str(main))
    git(main, "switch", "--quiet", "-c", "master")
    write(main, "docs/improvement-plan.md", PLAN)
    write(main, "docs/records/tasks/T1.md", "# T1. 走っているタスク\n\n状態: 未完了\n")
    write(main, "docs/records/tasks/T2.md", "# T2. 閉じたタスク\n\n状態: 完了\n")
    git(main, "add", "docs")
    git(main, "commit", "--quiet", "-m", "T0: 土台")
    git(main, "push", "--quiet", "origin", "master")
    orch.mkdir()
    save(orch, {"limits": {"concurrent": 3}, "agents": [],
                "run": {"name": "試験", "population": [{"task": "T1"}, {"task": "T2"}]}})
    return main, orch


def save(orch: Path, board: dict) -> None:
    (orch / "board.json").write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")


def load(orch: Path) -> dict:
    return json.loads((orch / "board.json").read_text(encoding="utf-8"))


def orchestrate(main: Path, orch: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(ENTRY), "--repo", str(main), "--dir", str(orch), *args],
                          cwd=main, capture_output=True, text=True, encoding="utf-8", check=False)


def overran(main: Path, orch: Path, **agent) -> None:
    """担当AがT1（規模S、予算60分）を90分前に始めていて、見込みを超えている表。"""
    board = load(orch)
    board["agents"] = [{"name": "A", "state": "稼働", "current_task": "T1", "task_first_started": ago(90), **agent}]
    save(orch, board)


def gate_output(main: Path, orch: Path) -> str:
    gated = orchestrate(main, orch, "gate")
    return gated.stdout + gated.stderr


def test_gate_stays_closed_by_an_overrun_until_it_is_marked_corrected(world):
    main, orch = world
    overran(main, orch)
    assert "見込み超過がある: A: T1の着手から通算90分 / 規模の予算60分" in gate_output(main, orch)

    marked = orchestrate(main, orch, "board", "set", "A", "overrun_ack=now")

    assert marked.returncode == 0, marked.stderr
    assert "見込み超過" not in gate_output(main, orch)


def test_corrected_mark_stops_counting_after_one_more_budget(world):
    main, orch = world
    overran(main, orch, overrun_ack=ago(61))

    assert "見込み超過がある: A: T1" in gate_output(main, orch)


def test_corrected_mark_from_before_the_task_started_does_not_count(world):
    main, orch = world
    overran(main, orch, overrun_ack=ago(95))

    assert "見込み超過がある: A: T1" in gate_output(main, orch)


def test_corrected_mark_is_dropped_when_the_agent_takes_the_next_task(world):
    main, orch = world
    overran(main, orch, overrun_ack=ago(1))

    assert orchestrate(main, orch, "board", "set", "A", "current_task=T3").returncode == 0

    assert "overrun_ack" not in load(orch)["agents"][0]


def test_finished_task_is_popped_from_the_dispatch_queue_only_with_the_cleanup_mark(world):
    main, orch = world
    assert orchestrate(main, orch, "board", "dispatch", "push", "T2").returncode == 0

    plain = orchestrate(main, orch, "board", "dispatch", "pop")

    assert plain.returncode != 0
    assert "取り出した" not in plain.stdout

    assert orchestrate(main, orch, "board", "dispatch", "push", "T2", "cleanup=true").returncode == 0
    listed = orchestrate(main, orch, "board", "dispatch", "list").stdout
    assert "後始末" in listed, listed

    popped = orchestrate(main, orch, "board", "dispatch", "pop")

    assert popped.returncode == 0, popped.stdout + popped.stderr
    assert '"cleanup": true' in popped.stdout
    assert [i.get("cleanup") for i in load(orch)["queue"]] == [None]


def slot(main: Path, n: int, owner: str) -> Path:
    """スロットnを作り、渡した印（`slot <渡し先> <時刻>`）を付ける。"""
    path = main / ".claude" / "worktrees" / f"slot-{n}"
    git(main, "worktree", "add", "--quiet", "-B", f"slot-{n}", str(path), "origin/master")
    git(main, "worktree", "lock", "--reason", f"slot {owner} {ago(1)}", str(path))
    return path


def lock_reason(main: Path, path: Path) -> str | None:
    for block in git(main, "worktree", "list", "--porcelain").split("\n\n"):
        fields = dict(line.partition(" ")[::2] for line in block.splitlines())
        if Path(fields.get("worktree", "")).resolve() == path.resolve():
            return fields.get("locked")
    raise AssertionError(f"作業ツリーに無い: {path}")


def test_sha_made_only_of_digits_is_kept_as_written(world):
    main, orch = world
    assert orchestrate(main, orch, "board", "add", "A", "current_task=T1").returncode == 0

    reported = orchestrate(main, orch, "board", "set", "A", "state=停止済み", "reported_sha=447131473413")
    audited = orchestrate(main, orch, "board", "set", "A", "audit_base=12e45678", "audit_done=now", "audit_result=差し戻す")

    assert reported.returncode == 0 and audited.returncode == 0, reported.stderr + audited.stderr
    entry = load(orch)["agents"][0]["audit_log"][0]
    assert (entry["reported_sha"], entry["audit_base"]) == ("447131473413", "12e45678")


def test_audit_values_go_only_into_the_audit_log_and_are_not_carried_into_the_next_audit(world):
    main, orch = world
    assert orchestrate(main, orch, "board", "add", "A", "current_task=T1").returncode == 0
    assert orchestrate(main, orch, "board", "set", "A", "state=停止済み", "reported_sha=1234567").returncode == 0
    assert orchestrate(main, orch, "board", "set", "A", "audit_base=7654321", "audit_done=now",
                       "audit_result=差し戻す").returncode == 0
    agent = load(orch)["agents"][0]
    assert not {"reported_sha", "audit_base", "audit_done", "audit_result", "urgent"} & set(agent), agent

    forgot_result = orchestrate(main, orch, "board", "set", "A", "audit_done=now")
    again = orchestrate(main, orch, "board", "set", "A", "audit_done=now", "audit_result=通す")

    assert forgot_result.returncode != 0 and "audit_result=<結果>" in forgot_result.stderr, forgot_result.stderr
    assert again.returncode == 0, again.stderr
    second = load(orch)["agents"][0]["audit_log"][1]
    assert (second["reported_sha"], second["audit_base"], second["audit_result"]) == (None, None, "通す")


def test_audit_log_mistake_is_fixed_only_with_a_commit_that_exists(world):
    main, orch = world
    board = load(orch)
    board["agents"] = [{"name": "A", "state": "停止済み", "audit_log": [
        {"task": "T1", "reported_sha": "1234567", "audit_base": "78964a5bxxxx", "audit_result": "通す"}]}]
    save(orch, board)
    real = git(main, "rev-parse", "--short=12", "HEAD")

    bogus = orchestrate(main, orch, "board", "audit-fix", "A", "1", "audit_base=78964a5bffff")
    fixed = orchestrate(main, orch, "board", "audit-fix", "A", "1", f"audit_base={real}")

    assert bogus.returncode != 0 and "引けない" in bogus.stderr, bogus.stdout + bogus.stderr
    assert fixed.returncode == 0, fixed.stderr
    assert load(orch)["agents"][0]["audit_log"][0]["audit_base"] == real
    assert "1. " in orchestrate(main, orch, "board", "audit-fix", "A").stdout


def test_passing_the_audit_before_the_report_still_stops_the_agent_and_frees_its_slot(world):
    main, orch = world
    path = slot(main, 1, "agent-a1")
    assert orchestrate(main, orch, "board", "add", "A", "current_task=T1", "id=a1").returncode == 0

    passed = orchestrate(main, orch, "board", "set", "A", "audit_done=now", "audit_result=通す")

    assert passed.returncode == 0, passed.stderr
    assert load(orch)["agents"][0]["state"] == "停止済み"
    assert lock_reason(main, path) is None, passed.stdout


def test_gate_stays_open_for_an_audit_wait_until_no_slot_is_left(world):
    main, orch = world
    board = load(orch)
    board["limits"] = {"concurrent": 2}
    board["agents"] = [{"name": "B", "id": "b1", "state": "停止済み", "current_task": "T1", "reported_sha": "1234567"}]
    save(orch, board)
    slot(main, 1, "agent-b1")

    one_free = gate_output(main, orch)

    assert "監査待ち" not in one_free and "空いているスロットが無い" not in one_free, one_free

    board["agents"].append({"name": "C", "id": "c1", "state": "停止済み", "current_task": "T1", "reported_sha": "1234567"})
    save(orch, board)
    slot(main, 2, "agent-c1")

    assert "空いているスロットが無い: slot-1（監査待ち B）、slot-2（監査待ち C）" in gate_output(main, orch)


def test_idle_slot_with_waiting_dispatch_is_raised_after_five_minutes_even_with_the_gate_closed(world):
    main, orch = world
    assert orchestrate(main, orch, "board", "dispatch", "push", "T1").returncode == 0

    first = orchestrate(main, orch, "check", "--record")

    assert "続いている" not in first.stdout, first.stdout
    assert int((orch / "next_check").read_text()) <= dt.datetime.now().timestamp() + 5 * 60 + 5
    board = load(orch)
    assert board["idle_since"]
    board["idle_since"] = ago(6)
    save(orch, board)
    (orch / "STOP").write_text("", encoding="utf-8")

    later = orchestrate(main, orch, "check").stdout

    assert "稼働が上限未満（0本 / 上限3本）で振り出し待ち1件がある状態が" in later, later
    assert "6分続いている（門: " in later and "停止ファイル" in later


ITEM = {"task": "T1", "kind": "保留", "text": "コメントで答えた問い", "comments": [{"text": "半分だけ残す", "at": ago(200)}]}


def check_with_dump(orch: Path, main: Path, minutes: int) -> str:
    backup = orch / "pending-backup"
    backup.mkdir(exist_ok=True)
    (backup / f"{dt.date.today().isoformat()}.json").write_text(
        json.dumps({"saved_at": ago(minutes), "items": {"T1-q": ITEM}}, ensure_ascii=False), encoding="utf-8")
    return orchestrate(main, orch, "check").stdout


def test_check_counts_the_items_of_a_recent_dump_without_listing_them(world):
    main, orch = world

    fresh = check_with_dump(orch, main, 1)

    assert "（1分前）の書き出しに確認中1件" in fresh, fresh
    assert "T1-q" not in fresh and "コメントで答えた問い" not in fresh


def test_check_only_asks_to_dump_again_when_the_dump_is_stale(world):
    main, orch = world

    stale = check_with_dump(orch, main, 120)

    assert "（120分前）で古い" in stale, stale
    assert "確認中1件" not in stale and "T1-q" not in stale


def test_backup_lists_the_current_items_by_owner(world, tmp_path):
    main, orch = world
    dump = tmp_path / "dump" / "pending"
    dump.mkdir(parents=True)
    (dump / "T1-q.json").write_text(json.dumps(ITEM, ensure_ascii=False), encoding="utf-8")

    backup = orchestrate(main, orch, "pending-backup", "--pending", str(dump.parent))

    assert "確認中1件 → 司令塔（持ち主の担当・セッションがいない）: T1-q（T1）コメントで答えた問い" in backup.stdout, backup.stdout


def test_add_renews_the_stopped_row_of_an_earlier_dispatch_and_keeps_its_audit_log(world):
    main, orch = world
    assert orchestrate(main, orch, "board", "add", "A", "current_task=T1", "id=a1").returncode == 0
    assert orchestrate(main, orch, "board", "set", "A", "reported_sha=1234567", "audit_done=now",
                       "audit_result=通す").returncode == 0

    again = orchestrate(main, orch, "board", "add", "A", "current_task=T1", "id=a2")

    assert again.returncode == 0, again.stderr
    agent = load(orch)["agents"][0]
    assert (agent["state"], agent["id"], agent["current_task"]) == ("稼働", "a2", "T1")
    assert "reported_sha" not in agent and "audit_result" not in agent
    assert [e["reported_sha"] for e in agent["audit_log"]] == ["1234567"]


def test_add_refuses_a_running_row_and_a_row_whose_slot_is_still_marked(world):
    main, orch = world
    assert orchestrate(main, orch, "board", "add", "A", "current_task=T1", "id=a1").returncode == 0
    board = load(orch)
    board["agents"].append({"name": "B", "id": "b1", "state": "強制停止"})
    save(orch, board)
    slot(main, 1, "agent-b1")

    running = orchestrate(main, orch, "board", "add", "A", "current_task=T1", "id=a2")
    marked = orchestrate(main, orch, "board", "add", "B", "current_task=T1", "id=b2")

    assert running.returncode != 0 and "既にある: A（稼働）" in running.stderr, running.stderr
    assert marked.returncode != 0 and "slot release" in marked.stderr, marked.stderr
    assert [a.get("id") for a in load(orch)["agents"]] == ["a1", "b1"]


def audit(main: Path, orch: Path, name: str, sha: str, monkeypatch, capsys) -> str:
    """`audit`を同じプロセスで回す。GitHubへの問い合わせ（網の境界）だけを「実行が無い」に差し替える。"""
    monkeypatch.syspath_prepend(str(ENTRY.parent))
    from orchestration import core, github

    monkeypatch.setattr(github, "actions_runs", lambda *_args, **_kwargs: ([], ""))
    capsys.readouterr()
    core.main(["--repo", str(main), "--dir", str(orch), "audit", name, sha])
    return capsys.readouterr().out


def touch_other_record(main: Path, t3_after: str) -> str:
    """masterに未完了のT3を置き、担当の枝で自分のT1と、T3を`t3_after`へ変えたコミットのsha。"""
    write(main, "docs/improvement-plan.md", PLAN + "- [ ] [T3](records/tasks/T3.md). 別のタスク 規模S\n")
    write(main, "docs/records/tasks/T3.md", T3_BEFORE)
    git(main, "add", "docs")
    git(main, "commit", "--quiet", "-m", "T0: T3")
    git(main, "push", "--quiet", "origin", "master")
    git(main, "switch", "--quiet", "-c", "work")
    write(main, "docs/records/tasks/T1.md", "# T1. 走っているタスク\n\n状態: 未完了\n\n実施した\n")
    write(main, "docs/records/tasks/T3.md", t3_after)
    git(main, "add", "docs")
    git(main, "commit", "--quiet", "-m", "T1: 実施")
    return git(main, "rev-parse", "HEAD")


T3_BEFORE = "# T3. 別のタスク\n\n状態: 未完了\n\n本文の行\n"
T3_NOTE = "前提の変化: X を撤去した（T1）"


@pytest.mark.parametrize(("t3_after", "holder", "expected", "unexpected"), [
    (T3_BEFORE + T3_NOTE + "\n", None, "? 他のタスクの記録への追記: T3（+1行。", "! "),
    (T3_BEFORE + T3_NOTE + "\n", "B", "! 仕掛中のタスクの記録へ追記している: T3（担当 B（稼働））", "? 他のタスク"),
    (T3_BEFORE.replace("本文の行", "書き直した行"), None, "! 担当のタスク外の記録を書き換えている: T3", "? 他のタスク"),
])
def test_audit_lets_an_append_to_an_idle_task_record_through_and_flags_the_rest(
        world, monkeypatch, capsys, t3_after, holder, expected, unexpected):
    main, orch = world
    sha = touch_other_record(main, t3_after)
    board = load(orch)
    board["agents"] = [{"name": "A", "state": "稼働", "current_task": "T1"}]
    if holder:
        board["agents"].append({"name": holder, "state": "稼働", "current_task": "T3"})
    save(orch, board)

    out = audit(main, orch, "A", sha, monkeypatch, capsys)

    records = out[out.index("2. 記録の整合"):out.index("4. 検証の証拠")]
    assert expected in records, out
    assert unexpected not in records, out


MAP_FILE = "frontend/src/features/map/x.ts"
EVIDENCE = ("\n\n検証: `python scripts/lockrun.py -- 'cd frontend && ./node_modules/.bin/playwright test"
            " -c playwright.live.config.ts s1-map'` → 3 passed\n増減: 実装 +1/−0\n")


@pytest.mark.parametrize(("message", "expected", "unexpected"), [
    ("T1: 地図を変えた", ["? 候補: ", "無: 「検証:」の欄・「増減:」の欄", "e2e-liveの実行の記録も回さない理由も無い: " + MAP_FILE,
                      "指摘 1件・候補 2件"], []),
    ("T1: 地図を変えた" + EVIDENCE, ["指摘 1件・候補 0件"], ["? 候補: "]),
], ids=["欄もe2e-liveの記録も無い", "欄とe2e-liveの記録がある"])
def test_audit_lists_evidence_and_e2e_live_as_candidates_without_counting_them(
        world, monkeypatch, capsys, message, expected, unexpected):
    main, orch = world
    git(main, "switch", "--quiet", "-c", "work")
    write(main, "docs/records/tasks/T1.md", "# T1. 走っているタスク\n\n状態: 未完了\n\n実施した\n")
    write(main, MAP_FILE, "export {};\n")
    git(main, "add", "docs", "frontend")
    git(main, "commit", "--quiet", "-m", message)
    board = load(orch)
    board["agents"] = [{"name": "A", "state": "停止済み", "current_task": "T1"}]
    save(orch, board)

    out = audit(main, orch, "A", git(main, "rev-parse", "HEAD"), monkeypatch, capsys)

    assert all(text in out for text in expected), out
    assert not any(text in out for text in unexpected), out
    assert "! このコミットに対するCIの実行が無い" in out


def test_record_only_commit_audited_under_a_non_task_name_is_unpushed_until_it_lands(world):
    main, orch = world
    base = git(main, "rev-parse", "HEAD")
    git(main, "switch", "--quiet", "-c", "work")
    write(main, "docs/records/tasks/T2.md", "# T2. 閉じたタスク\n\n状態: 完了\n\n答え: 見送り\n")
    git(main, "add", "docs")
    git(main, "commit", "--quiet", "-m", "記録: 答え T2")
    sha = git(main, "rev-parse", "HEAD")
    board = load(orch)
    board["agents"] = [{"name": "C", "state": "停止済み", "audit_log": [
        {"task": "記録待ち", "reported_sha": sha[:12], "audit_base": base[:12], "audit_done": ago(1), "audit_result": "通す"}]}]
    save(orch, board)

    before = orchestrate(main, orch, "board", "unpushed").stdout
    git(main, "switch", "--quiet", "master")
    git(main, "cherry-pick", sha)
    git(main, "commit", "--quiet", "--amend", "--no-edit")
    git(main, "push", "--quiet", "origin", "master")
    after = orchestrate(main, orch, "board", "unpushed").stdout

    assert "監査済み・未push 1件" in before, before
    assert "監査済み・未push 0件" in after, after


def test_ledger_sync_drops_the_rows_of_closed_records_and_restores_the_rows_of_reopened_ones(world):
    main, orch = world
    t2_row = "- [ ] [T2](records/tasks/T2.md). 閉じたタスク 規模S"
    write(main, "docs/improvement-plan.md", PLAN + "\n## 節B\n\n" + t2_row + "\n")
    git(main, "commit", "--quiet", "-am", "T2: 起票")
    write(main, "docs/improvement-plan.md", PLAN + "\n## 節B\n")
    git(main, "commit", "--quiet", "-am", "T2: 閉じた")
    write(main, "docs/records/tasks/T1.md", "# T1. 走っているタスク\n\n状態: 完了\n")
    write(main, "docs/records/tasks/T2.md", "# T2. 閉じたタスク\n\n状態: 未完了（開け直した）\n")

    synced = orchestrate(main, orch, "ledger", "sync")

    assert synced.returncode == 0, synced.stdout + synced.stderr
    assert "消した行: T1" in synced.stdout and "戻した行: T2" in synced.stdout, synced.stdout
    plan = (main / "docs" / "improvement-plan.md").read_text(encoding="utf-8")
    assert "[T1]" not in plan and plan.endswith("## 節B\n\n" + t2_row + "\n"), plan


def test_rules_prints_the_block_of_the_convention_with_the_agent_name(world):
    main, orch = world
    convention = Path(__file__).resolve().parents[2] / "docs" / "conventions" / "orchestration.md"
    write(main, "docs/conventions/orchestration.md", convention.read_text(encoding="utf-8"))
    git(main, "add", "docs")
    git(main, "commit", "--quiet", "-m", "T0: 規約")
    git(main, "push", "--quiet", "origin", "master")

    rules = orchestrate(main, orch, "rules", "K-x")

    assert rules.returncode == 0, rules.stderr
    lines = rules.stdout.splitlines()
    assert 1 <= len(lines) <= 10 and all(line.startswith("- ") for line in lines), rules.stdout
    assert "orch/K-x" in rules.stdout and "<名前>" not in rules.stdout
