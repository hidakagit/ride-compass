"""`scripts/orchestrate.py pending-inbox`・`pending-waiting`が、ダッシュボードのページと同じ定義で件を振り分けるか。

ダッシュボードは`ArtifactData`でしか読めないので、道具は書き出したファイル（`--pending`）を読む。ここでは書き出しの
形のファイルを一時的なディレクトリに置き、入口のコマンドから確かめる。ページの定義（確認中＝コメントが残っていて、答えと
コメントが取り込み済みでない件。取り込み待ち＝答えかコメントが付いていて、取り込みがそれより前か無い件で確認中でない件。
決定はコメントだけで入る。回答待ち＝答えを待つ種類で答えの無い件）の正本は`docs/conventions/asking-user.md`
「仕掛中のダッシュボード」節。
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ENTRY = Path(__file__).resolve().parents[2] / "scripts" / "orchestrate.py"

ITEMS = {
    # 問いを置く側が誤って sent_at を書いた、答えの無い問い。回答待ちであって、取り込み待ちではない。
    "T1-sent-without-answer": {"task": "T1", "kind": "保留", "text": "答えの無い問い",
                               "sent_at": "2026-09-26T10:30:00Z"},
    # ページで答えたが、まだ送っていない問い（反映待ち）。
    "T1-answered": {"task": "T1", "kind": "保留", "text": "答えた問い", "answer": "(1) 残す（2026-09-26）",
                    "answered_at": "2026-09-26T10:40:00Z"},
    # 答えて送り、取り込まれた改善案（記録待ち）。
    "T1-taken": {"task": "T1", "kind": "改善案", "text": "取り込んだ改善案", "answer": "承認（2026-09-26）",
                 "answered_at": "2026-09-26T10:00:00Z", "sent_at": "2026-09-26T10:01:00Z",
                 "taken_at": "2026-09-26T10:05:00Z"},
    # 取り込んだ後にコメントが付いた改善案（確認中へ入る）。
    "T1-commented": {"task": "T1", "kind": "改善案", "text": "コメントの付いた改善案", "answer": "承認（2026-09-26）",
                     "answered_at": "2026-09-26T10:00:00Z", "taken_at": "2026-09-26T10:05:00Z",
                     "comments": [{"text": "ここを直して", "at": "2026-09-26T10:20:00Z"}]},
    # 答えもコメントも取り込んだ改善案（記録待ち。コメントが残っていても確認中ではない）。
    "T1-commented-taken": {"task": "T1", "kind": "改善案", "text": "コメントごと取り込んだ改善案", "answer": "承認（2026-09-26）",
                           "answered_at": "2026-09-26T10:00:00Z", "taken_at": "2026-09-26T10:30:00Z",
                           "comments": [{"text": "ここも", "at": "2026-09-26T10:20:00Z"}]},
    # 選択肢のある問いに、番号を選ばずコメントで答えた件（確認中。回答待ちでも取り込み待ちでもない）。
    "T1-own-answer": {"task": "T1", "kind": "保留", "text": "コメントで答えた問い", "options": ["残す", "消す"],
                      "comments": [{"text": "どちらでもなく、半分だけ残す", "at": "2026-09-26T10:50:00Z"}]},
    # Claudeが書いた決定（answer を持つが、コメントが無ければ取り込み待ちにならない）。
    "T1-decided": {"task": "T1", "kind": "決定", "text": "決めたこと", "answer": "決定（2026-09-26）",
                   "answered_at": "2026-09-26T10:00:00Z"},
    # answer の項目自体が無い起票案（回答待ち、優先度 高）。
    "proposal-new": {"task": "", "kind": "起票案", "text": "新しいタスクの案", "priority": "高"},
    "T1-subject": {"task": "T1", "kind": "件名", "text": "T1: 件名"},
}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    repo, orch, dump = tmp_path / "repo", tmp_path / "orch", tmp_path / "dump" / "pending"
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    orch.mkdir()
    (orch / "board.json").write_text(json.dumps({"agents": []}), encoding="utf-8")
    dump.mkdir(parents=True)
    for doc_id, item in ITEMS.items():
        (dump / f"{doc_id}.json").write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
    return repo, orch, dump.parent


def orchestrate(repo: Path, orch: Path, *args: str) -> str:
    done = subprocess.run([sys.executable, str(ENTRY), "--repo", str(repo), "--dir", str(orch), *args],
                          capture_output=True, text=True, encoding="utf-8", check=False)
    return done.stdout + done.stderr


def test_inbox_lists_commented_items_as_checking_and_answered_items_as_intake(world):
    repo, orch, dump = world

    inbox = orchestrate(repo, orch, "pending-inbox", "--pending", str(dump))

    checking = inbox[inbox.index("確認中"):inbox.index("取り込み待ち")]
    assert "T1-commented（" in checking and "T1-own-answer" in checking, inbox
    assert "選択肢の答えとして取り込まず" in checking
    assert "T1-answered" in inbox[inbox.index("取り込み待ち"):]
    for doc_id in ("T1-sent-without-answer", "T1-taken", "T1-commented-taken", "T1-decided", "proposal-new", "T1-subject"):
        assert f"{doc_id}（" not in inbox, inbox


def test_waiting_counts_each_tab_like_the_page(world):
    repo, orch, dump = world

    waiting = orchestrate(repo, orch, "pending-waiting", "--pending", str(dump))

    assert "回答待ち2件（高1・中1・低0）" in waiting, waiting
    assert "確認中2件" in waiting, waiting
    assert "取り込み待ち1件（反映待ち1・送った0）" in waiting, waiting
    assert "記録待ち3件" in waiting, waiting
    lines = waiting.splitlines()
    high = next(i for i, line in enumerate(lines) if "proposal-new" in line)
    mid = next(i for i, line in enumerate(lines) if "T1-sent-without-answer" in line)
    assert high < mid
    own = next(line for line in lines if "T1-own-answer" in line)
    assert own.lstrip().startswith("[確認中]"), own
    assert not any("T1-answered" in line for line in lines[1:])
