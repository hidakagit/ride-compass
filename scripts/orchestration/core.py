"""並行実行（司令塔）の管理の核: 状態の表の読み書き・門・定期確認（と確認のフック）・監査の
機械的な項目・停止ファイル。

規約（docs/conventions/orchestration.md）のうち、司令塔の注意に頼ると崩れる手続きを
コマンドにしたもの。判断の基準と運用の正本は規約の側にあり、ここは事実を集めて突き合わせる。
依頼で足す機能は別のモジュールに置き、`load_board`・`save_board`・`Context`等を使って状態の表を
読み書きする（このモジュールからそれらをimportしない）。

## 使い方

    python scripts/orchestrate.py gate [--concurrent N]      # 振り出してよいか（0=OK / 1=NG）
    python scripts/orchestrate.py status [名前またはTxxx]     # checkが使う事実の一覧
    python scripts/orchestrate.py check [--record]            # 定期確認。異常だけを出す（0=異常なし / 1=あり）
    python scripts/orchestrate.py check --if-due              # フック用（scripts/orchestration/hook.sh から）
    python scripts/orchestrate.py board claim                 # このセッションを司令塔として記録する
    python scripts/orchestrate.py audit <名前> <sha>         # 監査のうち機械で見られる項目＋CIの結論
    python scripts/orchestrate.py board set <名前> k=v ...    # エージェントの行を更新
    python scripts/orchestrate.py board add <名前> k=v ...    # エージェントの行を追加
    python scripts/orchestrate.py board run k=v ...           # 回の値（limits.concurrent等）を更新
    python scripts/orchestrate.py board run start <名前>      # 新しい回を始める（目的・母集団を空にする）
    python scripts/orchestrate.py board run goal <文>         # 回の目的
    python scripts/orchestrate.py board run add <Txxx>... [from=<Tyyy>]  # 母集団へ足す（派生元つき）
    python scripts/orchestrate.py board run remove <Txxx>...  # 母集団から外す
    python scripts/orchestrate.py board run [list]            # 回の目的と母集団の各タスクの状態（導出）
    python scripts/orchestrate.py board todo push|pop|list    # 司令塔のキュー（中断・待ちの作業）
    python scripts/orchestrate.py board dispatch push <Txxx>|pop|list  # 振り出し待ちのキュー
    python scripts/orchestrate.py board unpushed              # 監査済み・未pushのコミット（gitから導く）

## 表に持つもの、正本から導くもの

表に持つのは表にしか無い事実だけ（規約「状態の表」節）。他に正本があるものは写さず、読むときに
導く（`ledger_rows`・`effort_budgets`・`budget_of`・`task_title`・`audited_unpushed`・`master_tip_time`）:

- タスクの題名と規模札は台帳（origin/masterの`docs/improvement-plan.md`の行）。見込み超過の予算は、
  担当の現在のタスクの規模札（「S〜M」のような幅は大きい側）について、タスク記録の所要の行
  （`所要（並行実行）:`）を集めた80パーセンタイルから、読むたびに計算する（`effort_budgets`）。
- 監査済みのコミットがmasterへ入ったかは、監査の記録（`audit_log`の`通す`）と`git cherry`
  （cherry-pickでshaが変わっても、変更の中身が同じなら入ったとみなす）。前回のpushの時刻は
  origin/masterの先端のコミットの時刻。
- 監査待ちかは、監査の記録（報告の受領`reported`が最後の`audit_done`より新しい）。
- 回（`run`）が持つのは名前・目的・母集団（タスク番号と派生元）だけ。母集団の各タスクが完了・
  トリガー待ち・残りのどれかと、終わりの条件1に当たっているかは、origin/masterの記録の`状態:`と
  台帳の行から読むたびに導く（`population_view`）。
- 担当の作業ツリーは、スロットなら渡した印（`git worktree lock`の理由`slot agent-<id> <時刻>`）、
  それ以外は作業ツリーの名前`agent-<id>`から、表の`id`で引く（`worktree_of`）。印は監査を
  通したとき（`audit_result=通す`）に、作業ツリーにしか無い成果が無ければ外す（`release_slot`）。

担当の現在のタスク（`current_task`）とその着手時刻（`task_first_started`）は、振り出し
（`board add ... current_task=Txxx`、`board set ... current_task=Txxx`）で入り、監査を通したとき
（`audit_result=通す`）に外れる。差し戻しの間は同じタスクのまま着手時刻を保つ。所要の実績は
担当が完了のコミットで`Txxx.md`へ残す（表には写さない）。

写しのキー（`FORBIDDEN_KEYS`、回と母集団の1件は`RUN_KEYS`・`POPULATION_ITEM_KEYS`の外）を書こうと
すると、正本の場所を添えて拒否する。手で書かれた写しのキーは check が出す（`board_copy_keys`）。

`board set <名前> audit_done=now audit_result=通す`は、監査の記録（audit_log）を1件残す。

`k=v`の値は、`now`なら現在時刻、JSONとして読めればその値（数値・配列）、それ以外は文字列。
`k+=v`は配列へ足す。キーは`limits.concurrent`のように`.`で入れ子を指せる。

## 置き場所

状態の表は`<gitの共通ディレクトリ>/orchestration/board.json`、停止ファイルは同じディレクトリの
`STOP`、ロックの記録は`<gitの共通ディレクトリ>/lockrun/log.jsonl`（scripts/lockrun.py）。
`--dir`（または環境変数`ORCH_DIR`）でorchestrationディレクトリを差し替えると、ロックの記録も
その隣の`lockrun/`を読む——試験で実物の表を壊さないため。`--repo`は調べるgitリポジトリ。

## 軽さ

飽和した機械で回す前提なので、gitは`GIT_OPTIONAL_LOCKS=0`で呼び（索引を書き戻さない）、
コミット時刻・参照・ファイルの中身はそれぞれ1回の呼び出しでまとめて取る。作業ツリーごとに
要るのは`git status`の1回だけで、時間切れは「未取得」として扱う。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
#: コマンドの入口（scripts/orchestrate.py）。フックから確認を起こすときに使う。
ENTRY = REPO_ROOT / "scripts" / "orchestrate.py"
PLAN_DOC = "docs/improvement-plan.md"
#: 重い段の定義（「重い処理は機械全体で1本ずつ」節の「対象」の項目）を持つ規約。
CONVENTION_DOC = "docs/conventions/orchestration.md"
HEAVY_TARGET_PREFIX = "- **対象**:"
HEAVY_LOCK = "heavy"
TASKS_DIR = "docs/records/tasks"
PLAN_ENTRY_RE = re.compile(r"^- \[[ x]\] \[(T\d+[a-z0-9-]*)\]\(")
TASK_ID_RE = re.compile(r"T\d+[a-z0-9-]*")
TASK_DOC_RE = re.compile(r"^docs/records/tasks/(T\d+[a-z0-9-]*)\.md$")

#: 状態の表の`state`の語彙。司令塔の指示（振り出した・止めた）だけで、監査の段階は監査の記録から導く。
ACTIVE_STATES = ("稼働", "停止指示")
STOPPED_STATES = ("停止済み", "強制停止")
STATES = ACTIVE_STATES + STOPPED_STATES

#: 表に書いてはならないキー（他に正本がある写し・規則や記録の文）と、その正本。
FORBIDDEN_KEYS = {
    "agent": {
        "queue": "1件ずつの依頼にしたので current_task だけを持つ",
        "scale": "規模札は台帳の行",
        "scale_budget_min": "予算は台帳の規模札から計算する",
        "task_log": "所要の実績は完了のコミットで Txxx.md へ",
        "note": "経緯は回の記録 Txxx.md へ",
        "audit": "監査の記録は reported・audit_* のキー",
    },
    "top": {
        "decisions": "判断の問いと回答は各タスクの記録の保留節と「ユーザー決定」",
        "audited_unpushed": "masterに入ったかは git（board unpushed が導く）",
        "last_master_push": "origin/master の履歴",
        "last_master_push_at": "origin/master の履歴",
        "push_blocked": "出来事は回の記録 Txxx.md へ",
        "resume_policy": "規約",
        "decision_policy": "規約",
        "check_rule": "規約",
        "incidents": "回の記録 Txxx.md",
        "hookspath_reverts": "回の記録 Txxx.md",
        "audit_findings": "回の記録 Txxx.md",
        "notes": "回の記録 Txxx.md",
        "pending_cleanup": "台帳",
        "run": "回は board run start・goal・add・remove で書く（丸ごと置き換えると母集団へ写しを紛れ込ませられる）",
    },
    "limits": {"note": "規約"},
    "queue": {
        "what": "題名・規模は台帳の行（dispatch list が導く）",
        "note": "経緯は回の記録 Txxx.md へ",
    },
}

#: 回（`run`）が持つキー。回の各タスクの状態・残り・終わりの条件は記録と台帳から導くので、
#: これ以外（出来事・進め方の指示の文を含む）は持たない。
RUN_KEYS = ("name", "started", "goal", "population")
#: 母集団の1件が持つキー。`task`と派生元`from`は表にしか無い事実、`added`は足した時刻。
POPULATION_ITEM_KEYS = ("task", "from", "added")
#: `board run`の語（k=v でないもの）。
RUN_OPS = ("start", "goal", "add", "remove", "list")
#: 台帳の行で、着手の条件を待っている（ユーザーの判断で先送りした）ことを表す印。
TRIGGER_MARK = "— トリガー:"

DEFAULT_CONCURRENT = 3
#: 規模札の定義（CLAUDE.md「規模の目安」）の分。予算は所要の実績から計算し、これは実績の無い
#: 規模札の補い（隣の規模札との比と、最後の既定値）にだけ使う。
SCALE_BUDGET_MINUTES = {"S": 60, "M": 240, "L": 480}
#: 所要の行（規約「完了とpush」の書式）。
EFFORT_PREFIX = "所要（並行実行）"
EFFORT_REAL_RE = re.compile(r"完了[^（(]*[（(]約?(\d+)分")
EFFORT_FRAME_RE = re.compile(r"枠待ち約?(\d+)分")
EFFORT_CI_RE = re.compile(r"CI待ち約?(\d+)分")
#: 監査が書き足す、完了のコミットのCI（scripts/orchestration/effort_ci.py）。完了の時刻より後の時間。
EFFORT_AFTER_CI_RE = re.compile(r"完了のコミットのCI\s*約?(\d+)分")
EFFORT_SCALE_RE = re.compile(r"規模札([SML])(?:〜([SML]))?")
EFFORT_REASON_RE = re.compile(r"超過[:：]\s*([^、。）\n]+)")
BUDGET_PERCENTILE = 0.8
#: これより少ない件数の規模札は、その件数だけで予算を決めない。
BUDGET_MIN_SAMPLES = 5
#: 作業ツリーの未コミット変更がこの時間内に更新されていれば「手元で動いている」と数える。
ACTIVE_MINUTES = 15
STALE_COMMIT_MINUTES = 30
AUDIT_WAIT_MINUTES = 30
LOCK_WINDOW_MINUTES = 30
LOCK_WAIT_LIMIT_MINUTES = 10
CPU_SATURATED_PERCENT = 90
CPU_SAMPLE_SECONDS = 2.0
GIT_TIMEOUT_SECONDS = 60
#: 監査を通したコミットは溜めてmasterへ1回でpushする（masterへのpushのたびにCIとbackendの
#: デプロイ＝本番の再起動が走るため、回数を減らす）。
PUSH_BATCH_SIZE = 2
PUSH_INTERVAL_MINUTES = 60
#: これより古い監査の記録は、masterへ入ったかを調べない（1件ごとにgitを1回呼ぶため）。
UNPUSHED_LOOKBACK_HOURS = 48
#: CIの所要の基準にするmasterの実行を、対象のコミットの祖先から選ぶときに辿るコミット数。
CI_ANCESTRY_DEPTH = 500
#: 台帳の未完了の行と、その規模札。
LEDGER_ROW_RE = re.compile(r"^- \[ \] \[(T\d+[a-z0-9-]*)\]\([^)]*\)\.?\s*(.*)$")
SCALE_LABEL_RE = re.compile(r"規模([SML])(?:〜([SML]))?")
TASK_HEADING_RE = re.compile(r"^# T\d+[a-z0-9-]*\.\s*(.*)$")
EXPECTED_HOOKS_PATH = ".githooks"
#: どの作業ツリーにも自動で作られる設定。作業の進みを表さない。
IGNORED_CHANGES = (".claude/settings.local.json",)
#: スロット（scripts/orchestration/slots.py）を渡した印は`git worktree lock`の理由
#: `slot <渡し先> <時刻>`。渡し先はClaude CodeがWorktreeCreateフックへ渡す名前（`agent-<id>`）。
SLOT_LOCK_PREFIX = "slot "

#: 監査の同期ルール（CLAUDE.md「コミット時の同期ルール」）で、生成物の再生成を要する宣言の場所。
API_DECL_RE = re.compile(r"^backend/(app/(api|domain)/|app/config\.py|scripts/export_openapi\.py)")
GENERATED_PREFIX = "frontend/src/types/generated/"
STATIC_CHECK_TIMEOUT = 600
#: 使い捨ての成果物が紛れ込みやすい形。混入の候補であって判定ではない。
SCRATCH_RE = re.compile(r"(^|/)(scratch|tmp|temp)(/|$)|\.(log|png|jpe?g|webm|zip)$", re.IGNORECASE)
E2E_SPEC_RE = re.compile(r"^frontend/e2e/.*\.spec\.[jt]s$")
#: コミットメッセージに検証の証拠らしき記述があるかの目安。
COMMAND_HINT_RE = re.compile(
    r"pytest|ruff|vitest|tsc|eslint|playwright|review_checks|lockrun|run_probe|npm |python |git (grep|diff)|`[^`]+`")
OBSERVED_HINT_RE = re.compile(r"\d+ ?(件|passed|failed|秒|分|ms|本|行|%)|→|緑|赤")
DELTA_HINT_RE = re.compile(r"増減|[+＋−-]\d+ ?行|\+\d+/[−-]\d+")


# ---------------------------------------------------------------- 共通


def now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def iso(t: dt.datetime) -> str:
    return t.isoformat(timespec="minutes")


def parse_time(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        t = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return t if t.tzinfo else t.astimezone()


def hm(t: dt.datetime | None) -> str:
    if t is None:
        return "-"
    return t.strftime("%H:%M") if t.date() == now().date() else t.strftime("%m-%d %H:%M")


def minutes(delta: dt.timedelta) -> int:
    return int(delta.total_seconds() // 60)


def git(repo: Path, *args: str, stdin: bytes | None = None,
        timeout: float = GIT_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[bytes] | None:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    try:
        return subprocess.run(["git", *args], cwd=str(repo), input=stdin, capture_output=True,
                              env=env, timeout=timeout, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return None


def git_out(repo: Path, *args: str) -> str | None:
    r = git(repo, *args)
    if r is None or r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", errors="replace").strip()


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    r = git(repo, "merge-base", "--is-ancestor", older, newer)
    return r is not None and r.returncode == 0


def cat_files(repo: Path, specs: list[str]) -> dict[str, str | None]:
    """`<rev>:<path>`の中身を1回の`git cat-file --batch`でまとめて読む。無ければNone。"""
    if not specs:
        return {}
    r = git(repo, "cat-file", "--batch", stdin=("\n".join(specs) + "\n").encode("utf-8"))
    out: dict[str, str | None] = dict.fromkeys(specs)
    if r is None or r.returncode != 0:
        return out
    data, pos = r.stdout, 0
    for spec in specs:
        end = data.index(b"\n", pos)
        header = data[pos:end].decode("utf-8", errors="replace").split()
        pos = end + 1
        if len(header) == 3 and header[1] == "blob":
            size = int(header[2])
            out[spec] = data[pos:pos + size].decode("utf-8", errors="replace")
            pos += size + 1
        elif len(header) == 3:
            pos += int(header[2]) + 1
    return out


def task_state(text: str | None) -> str | None:
    if text is None:
        return None
    line = next((l for l in text.splitlines() if l.startswith("状態:")), None)
    if line is None:
        return "状態行なし"
    value = line[len("状態:"):].strip()
    for word in ("未完了", "完了"):
        if value.startswith(word):
            return word
    return value[:10]


def prereqs_of_item(item: dict) -> list[str]:
    """振り出し待ちの1行の前提（`after`）。1件の文字列でも、配列でもよい。"""
    after = item.get("after")
    if not after:
        return []
    return [str(t) for t in (after if isinstance(after, list) else [after])]


def done_tasks(ctx: Context, tasks: list[str]) -> set[str]:
    """origin/masterのタスク記録で`状態: 完了`のもの。"""
    texts = cat_files(ctx.repo, [f"origin/master:{TASKS_DIR}/{t}.md" for t in tasks])
    return {t for t in tasks if task_state(texts[f"origin/master:{TASKS_DIR}/{t}.md"]) == "完了"}


def ready_to_dispatch(ctx: Context, items: list[dict]) -> list[dict]:
    """振り出し待ちのうち、前提がすべてorigin/masterで完了しているもの。"""
    done = done_tasks(ctx, sorted({t for i in items for t in prereqs_of_item(i)}))
    return [i for i in items if all(t in done for t in prereqs_of_item(i))]


def ledger_rows(ctx: Context) -> dict[str, dict]:
    """台帳（origin/master）の未完了の行: タスク → 題名・規模札（幅があれば大きい側）。"""
    plan = cat_files(ctx.repo, [f"origin/master:{PLAN_DOC}"])[f"origin/master:{PLAN_DOC}"] or ""
    rows = {}
    for line in plan.splitlines():
        m = LEDGER_ROW_RE.match(line)
        if m:
            s = SCALE_LABEL_RE.search(m.group(2))
            rows[m.group(1)] = {"title": m.group(2).strip(), "scale": (s.group(2) or s.group(1)) if s else None}
    return rows


def parse_effort(task: str, text: str) -> dict:
    """所要の1行（規約「完了とpush」の書式）を読む。読めない値はNone（「不明」も同じ）。"""
    def minutes_of(rx: re.Pattern) -> int | None:
        m = rx.search(text)
        return int(m.group(1)) if m else None

    s = EFFORT_SCALE_RE.search(text)
    real, frame, ci = minutes_of(EFFORT_REAL_RE), minutes_of(EFFORT_FRAME_RE), minutes_of(EFFORT_CI_RE)
    after = minutes_of(EFFORT_AFTER_CI_RE)
    if after is not None:
        # 完了の時刻の後の時間なので、実時間とCI待ちの両方へ足す（作業そのものの時間は変えない）。
        real = real + after if real is not None else None
        ci = ci + after if ci is not None else None
    reason = EFFORT_REASON_RE.search(text)
    return {"task": task, "scale": (s.group(2) or s.group(1)) if s else None, "real": real,
            "work": real - frame - ci if None not in (real, frame, ci) else None,
            "reason": reason.group(1).strip() if reason else None}


def effort_records(ctx: Context) -> list[dict]:
    """origin/masterのタスク記録にある所要の行（1回のgit grepで取る）。"""
    out = git_out(ctx.repo, "grep", "--no-color", "-e", f"^{EFFORT_PREFIX}", "origin/master", "--",
                  f"{TASKS_DIR}/*.md") or ""
    records = []
    for line in out.splitlines():
        _, path, text = line.split(":", 2)
        m = TASK_DOC_RE.match(path)
        if m:
            records.append(parse_effort(m.group(1), text))
    return records


def percentile(values: list[int], q: float) -> int:
    """最近順位法の百分位（件数に1件足しても、外れ値の側へは順位1つ分しか動かない）。"""
    ordered = sorted(values)
    return ordered[max(math.ceil(q * len(ordered)) - 1, 0)]


def effort_budgets(records: list[dict]) -> dict[str, dict]:
    """規模札ごとの予算（分）を、所要の実績の80パーセンタイルから計算する。保存しない。

    作業そのものの時間（実時間 − 枠待ち − CI待ち）の件数が足りればそれを、足りなければ実時間を
    使う。どちらも足りない規模札は、実績のある隣の規模札に、規模札の定義の比（S:M:L=1:4:8）を
    掛けて補い、隣も無ければ定義の値を使う。"""
    stats: dict[str, dict] = {}
    for scale in SCALE_BUDGET_MINUTES:
        real = [r["real"] for r in records if r["scale"] == scale and r["real"] is not None]
        work = [r["work"] for r in records if r["scale"] == scale and r["work"] is not None]
        stat = {"n_real": len(real), "n_work": len(work),
                "real": percentile(real, BUDGET_PERCENTILE) if real else None,
                "work": percentile(work, BUDGET_PERCENTILE) if work else None, "value": None, "basis": ""}
        if len(work) >= BUDGET_MIN_SAMPLES:
            stat["value"], stat["basis"] = stat["work"], "作業そのものの時間"
        elif len(real) >= BUDGET_MIN_SAMPLES:
            stat["value"], stat["basis"] = stat["real"], "実時間"
        stats[scale] = stat
    order = list(SCALE_BUDGET_MINUTES)
    for i, scale in enumerate(order):
        if stats[scale]["value"] is not None:
            continue
        neighbors = sorted((abs(i - j), other) for j, other in enumerate(order)
                           if other != scale and stats[other]["basis"] in ("作業そのものの時間", "実時間"))
        if neighbors:
            other = neighbors[0][1]
            ratio = SCALE_BUDGET_MINUTES[scale] / SCALE_BUDGET_MINUTES[other]
            stats[scale]["value"] = round(stats[other]["value"] * ratio)
            stats[scale]["basis"] = f"{other}の実績×{ratio:g}"
        else:
            stats[scale]["value"], stats[scale]["basis"] = SCALE_BUDGET_MINUTES[scale], "規模札の定義"
    return stats


def budget_line(stats: dict[str, dict]) -> str:
    parts = []
    for scale, s in stats.items():
        measured = (f"実時間p80 {s['real'] if s['real'] is not None else '-'}分/{s['n_real']}件・作業p80 "
                    f"{s['work'] if s['work'] is not None else '-'}分/{s['n_work']}件")
        parts.append(f"{scale} {s['value']}分（{s['basis']}。{measured}）")
    return "予算（所要の実績の80パーセンタイル）: " + " ／ ".join(parts)


def task_title(ctx: Context, task: str, rows: dict[str, dict]) -> str:
    """タスクの題名。台帳に行があればその行、無ければ（閉じたタスク等）記録の見出し。"""
    if task in rows:
        return rows[task]["title"]
    text = cat_files(ctx.repo, [f"origin/master:{TASKS_DIR}/{task}.md"])[f"origin/master:{TASKS_DIR}/{task}.md"]
    m = TASK_HEADING_RE.match((text or "").splitlines()[0]) if text else None
    return m.group(1) if m else "（台帳にも記録にも無い）"


def master_tip_time(ctx: Context) -> dt.datetime | None:
    out = git_out(ctx.repo, "log", "-1", "--format=%ct", "origin/master")
    return dt.datetime.fromtimestamp(int(out)).astimezone() if out else None


def audited_unpushed(ctx: Context, board: dict, at: dt.datetime) -> list[dict]:
    """監査を通したコミットのうち、まだorigin/masterに入っていないもの。

    入ったかは、変更の中身が同じ（`git cherry`のpatch-id）か、同じ件名のコミットがmasterにあるかで
    見る——司令塔が取り込みで衝突を解くと中身が変わり、patch-idだけでは入っていないように見える。"""
    since = at - dt.timedelta(hours=UNPUSHED_LOOKBACK_HOURS)
    subjects = set((git_out(ctx.repo, "log", "--format=%s", f"--since={iso(since - dt.timedelta(days=1))}",
                            "origin/master") or "").splitlines())
    out = []
    for agent in board.get("agents") or []:
        for entry in agent.get("audit_log") or []:
            sha, done = entry.get("reported_sha"), parse_time(entry.get("audit_done"))
            if entry.get("audit_result") != "通す" or not sha or (done and done < since):
                continue
            base = entry.get("audit_base") or git_out(ctx.repo, "merge-base", "origin/master", str(sha))
            cherry = git_out(ctx.repo, "cherry", "-v", "origin/master", str(sha), *([str(base)] if base else []))
            missing = [line.split(" ", 2)[2] for line in (cherry or "").splitlines()
                       if line.startswith("+ ") and line.count(" ") >= 2]
            if cherry is None or any(subject not in subjects for subject in missing):
                out.append({"agent": agent.get("name"), "sha": sha, "base": entry.get("audit_base"),
                            "audited": entry.get("audit_done"), "urgent": bool(entry.get("urgent"))})
    return out


def ledger_ids(plan_text: str | None) -> set[str]:
    if plan_text is None:
        return set()
    return {m.group(1) for line in plan_text.splitlines() if (m := PLAN_ENTRY_RE.match(line))}


def cpu_percent(sample: float = CPU_SAMPLE_SECONDS) -> float | None:
    """全体のCPU使用率。取れなければNone。プロセスを起こさずに取る（飽和時に足さない）。"""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class FileTime(ctypes.Structure):
                _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

            def snap() -> tuple[int, int] | None:
                idle, kernel, user = FileTime(), FileTime(), FileTime()
                if not ctypes.windll.kernel32.GetSystemTimes(
                        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                    return None
                value = lambda t: (t.hi << 32) | t.lo
                # カーネル時間はアイドル時間を含む。
                return value(idle), value(kernel) + value(user)
        else:
            def snap() -> tuple[int, int] | None:
                with open("/proc/stat", encoding="ascii") as f:
                    fields = [int(x) for x in f.readline().split()[1:]]
                return fields[3] + fields[4], sum(fields)
        a = snap()
        time.sleep(sample)
        b = snap()
        if a is None or b is None or b[1] == a[1]:
            return None
        return 100.0 * (1 - (b[0] - a[0]) / (b[1] - a[1]))
    except (OSError, AttributeError, ValueError, IndexError):
        return None


# ---------------------------------------------------------------- 置き場所と状態の表


class Context:
    def __init__(self, repo: Path, orch_dir: str | None):
        self.repo = repo
        common = git_out(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if common is None:
            raise SystemExit(f"gitリポジトリではありません: {repo}")
        self.common = Path(common)
        self.dir = Path(orch_dir) if orch_dir else self.common / "orchestration"
        self.board_path = self.dir / "board.json"
        self.stop_path = self.dir / "STOP"
        self.lock_root = self.dir.parent / "lockrun"


def load_board(ctx: Context) -> dict:
    if not ctx.board_path.exists():
        return {"agents": []}
    with open(ctx.board_path, encoding="utf-8") as f:
        board = json.load(f)
    board.setdefault("agents", [])
    return board


def save_board(ctx: Context, board: dict) -> None:
    ctx.dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="board.", suffix=".tmp", dir=str(ctx.dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(board, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, ctx.board_path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def find_agent(board: dict, name: str) -> dict | None:
    lowered = name.lower()
    return next((a for a in board["agents"] if str(a.get("name", "")).lower() == lowered), None)


def limit_of(board: dict, override: int | None) -> int:
    if override is not None:
        return override
    value = (board.get("limits") or {}).get("concurrent")
    return value if isinstance(value, int) else DEFAULT_CONCURRENT


def is_cloud(agent: dict) -> bool:
    """クラウドセッションは手元の資源を使わず、手元の作業ツリーも持たない。"""
    return str(agent.get("where", "")).startswith("cloud")


def budget_of(agent: dict, rows: dict[str, dict], budgets: dict[str, dict]) -> int | None:
    """担当の現在のタスクの予算（分）: 台帳の規模札の、所要の実績から計算した予算（台帳に行が無ければ不明）。"""
    task = agent.get("current_task")
    scale = (rows.get(str(task)) or {}).get("scale") if task else None
    return budgets[scale]["value"] if scale in budgets else None


def start_task(agent: dict, task: str, at: dt.datetime) -> None:
    """担当の現在のタスクを切り替え、着手時刻を入れる。"""
    agent["current_task"] = task
    agent["task_first_started"] = iso(at)


def audit_pending(agent: dict) -> bool:
    """監査待ちか。報告の受領が、最後の監査の終わりより新しい。"""
    reported, done = parse_time(agent.get("reported")), parse_time(agent.get("audit_done"))
    return reported is not None and (done is None or done < reported)


def run_of(board: dict) -> dict:
    """回の値。名前だけを文字列で持っていた表も、名前だけの回として読む。"""
    run = board.get("run")
    if isinstance(run, dict):
        return run
    return {"name": run} if run else {}


def population_view(ctx: Context, board: dict, rows: dict[str, dict]) -> dict:
    """回の母集団の各タスクの状態を、origin/masterの記録の`状態:`と台帳の行から導く。

    `完了`は記録が完了のもの、`トリガー待ち`は未完了で台帳の行に着手の条件（`— トリガー:`）が
    あり、その条件が母集団のタスクを名指ししていないもの（ユーザーの判断で先送りした）、`残り`は
    それ以外の未完了、`記録なし`は記録がorigin/masterに無いもの。終わりの条件1（規約「回の始まりと終わり」）は、母集団が空でなく、
    すべて完了かトリガー待ちであること。"""
    run = run_of(board)
    items = [i for i in run.get("population") or [] if isinstance(i, dict) and i.get("task")]
    tasks = [str(i["task"]) for i in items]
    texts = cat_files(ctx.repo, [f"origin/master:{TASKS_DIR}/{t}.md" for t in tasks])
    assigned = {str(a.get("current_task")): a for a in board.get("agents") or [] if a.get("current_task")}
    queued = {str(q.get("task")) for q in board.get("queue") or []}
    entries = []
    for item in items:
        task = str(item["task"])
        text = texts[f"origin/master:{TASKS_DIR}/{task}.md"]
        st = task_state(text)
        heading = TASK_HEADING_RE.match(text.splitlines()[0]) if text else None
        title = (rows.get(task) or {}).get("title") or (heading.group(1) if heading else "")
        if st is None:
            kind = "記録なし"
        elif st == "完了":
            kind = "完了"
        elif st == "未完了" and TRIGGER_MARK in (rows.get(task) or {}).get("title", ""):
            kind = "トリガー待ち"
        else:
            kind = "残り"
        where = ""
        if kind != "完了" and task in assigned:
            where = f"担当 {assigned[task].get('name')}（{assigned[task].get('state')}）"
        elif kind != "完了" and task in queued:
            where = "振り出し待ち"
        entries.append({"task": task, "from": item.get("from"), "kind": kind, "where": where, "title": title})
    # 着手の条件が母集団のタスクを名指しするものは、先送りではなく回の中の順番なので残りに数える。
    # 母集団の外のタスクを名指す条件は、完了を待つのか利用実績を待つのかを文から決められないので先送りのまま。
    in_run = {e["task"] for e in entries}
    done = {e["task"] for e in entries if e["kind"] == "完了"}
    for e in entries:
        if e["kind"] != "トリガー待ち":
            continue
        named = [t for t in dict.fromkeys(TASK_ID_RE.findall(e["title"].split(TRIGGER_MARK, 1)[1])) if t in in_run]
        if named:
            waiting = [t for t in named if t not in done]
            note = "・".join(waiting) + "待ち" if waiting else "・".join(named) + "は完了"
            e["kind"], e["where"] = "残り", note + (f"・{e['where']}" if e["where"] else "")
    remaining = [e for e in entries if e["kind"] in ("残り", "記録なし")]
    return {"name": run.get("name"), "goal": run.get("goal"), "entries": entries, "remaining": remaining,
            "ended": bool(entries) and not remaining}


def run_summary_lines(view: dict, *, detail: bool) -> list[str]:
    """回の目的・母集団の残り・終わりの条件1の行。detailなら母集団の全件を1行ずつ出す。"""
    lines = [f"回: {view['name'] or '-'}  目的: {view['goal'] or '未設定（board run goal <文>）'}"]
    entries = view["entries"]
    if not entries:
        lines.append("母集団: 未設定（board run add <Txxx> from=<派生元>）")
        return lines
    counts = {k: sum(1 for e in entries if e["kind"] == k) for k in ("完了", "トリガー待ち", "残り", "記録なし")}
    lines.append(f"母集団{len(entries)}件: " + "・".join(f"{k}{n}件" for k, n in counts.items() if n))
    if view["ended"]:
        lines.append("終わりの条件1に当たっている（母集団がすべて完了かトリガー待ち）。新しいタスクは振り出さない")
    else:
        rest = "、".join(e["task"] + (f"（{e['where']}）" if e["where"] else "") for e in view["remaining"])
        lines.append(f"終わりの条件1には当たっていない。残り: {rest}")
    if detail:
        for e in entries:
            origin = f"  派生元 {e['from']}" if e["from"] else ""
            lines.append(f"  {e['task']}  [{e['kind']}]{origin}{'  ' + e['where'] if e['where'] else ''}"
                         f"  {e['title'][:60]}")
    return lines


# ---------------------------------------------------------------- 事実の収集


class Worktree:
    def __init__(self, path: str, head: str | None, branch: str | None, main: bool,
                 locked: str | None = None):
        self.path, self.head, self.branch, self.main = path, head, branch, main
        #: `git worktree lock`の理由（ロックが無ければNone、理由の無いロックは空文字）。
        self.locked = locked
        self.exists = os.path.isdir(path)
        self.commit_time: dt.datetime | None = None
        self.dirty: int | None = None
        self.newest_change: dt.datetime | None = None

    @property
    def label(self) -> str:
        return f"{os.path.basename(self.path)}（{self.branch or 'detached'}）"

    def active(self, at: dt.datetime, active_min: int) -> bool:
        return (self.newest_change is not None
                and at - self.newest_change <= dt.timedelta(minutes=active_min))


def list_worktrees(ctx: Context) -> list[Worktree]:
    out = git_out(ctx.repo, "worktree", "list", "--porcelain") or ""
    trees: list[Worktree] = []
    for block in out.split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            fields[key] = value
        if "worktree" in fields:
            branch = fields.get("branch", "").removeprefix("refs/heads/") or None
            trees.append(Worktree(os.path.normpath(fields["worktree"]), fields.get("HEAD"),
                                  branch, main=not trees, locked=fields.get("locked")))
    heads = [t.head for t in trees if t.head]
    times = git_out(ctx.repo, "log", "--no-walk=unsorted", "--format=%H %ct", *heads) if heads else ""
    by_sha = {}
    for line in (times or "").splitlines():
        sha, _, ts = line.partition(" ")
        by_sha[sha] = dt.datetime.fromtimestamp(int(ts)).astimezone()
    for t in trees:
        t.commit_time = by_sha.get(t.head or "")
    return trees


def inspect_changes(tree: Worktree) -> None:
    """未コミットの変更の件数と、その中で最も新しい更新時刻。"""
    if not tree.exists:
        return
    r = git(Path(tree.path), "status", "--porcelain=v1", "-z", "--no-renames")
    if r is None or r.returncode != 0:
        return
    paths = [entry[3:] for entry in r.stdout.decode("utf-8", errors="replace").split("\0")
             if len(entry) > 3]
    paths = [p for p in paths if p.rstrip("/") not in IGNORED_CHANGES]
    tree.dirty = len(paths)
    newest = None
    for p in paths:
        try:
            m = os.stat(os.path.join(tree.path, p)).st_mtime
        except OSError:
            continue  # 削除した変更は時刻を持たない
        newest = m if newest is None or m > newest else newest
    tree.newest_change = dt.datetime.fromtimestamp(newest).astimezone() if newest else None


def slot_owner(tree: Worktree) -> str | None:
    """スロットを渡した印の渡し先。スロットの印でなければNone。"""
    reason = tree.locked or ""
    if not reason.startswith(SLOT_LOCK_PREFIX):
        return None
    return reason[len(SLOT_LOCK_PREFIX):].split(" ", 1)[0] or None


def worktree_of(agent: dict, trees: list[Worktree]) -> Worktree | None:
    """担当の作業ツリー。スロットで動く担当は、渡した印の渡し先（`agent-<id>`）から導く——
    スロットの名前は担当を表さず、印が外れれば担当とスロットの対応も消える。"""
    explicit = agent.get("worktree")
    if explicit:
        target = os.path.normcase(os.path.normpath(str(explicit)))
        return next((t for t in trees if os.path.normcase(t.path) == target
                     or os.path.basename(t.path) == explicit), None)
    agent_id, name = agent.get("id"), str(agent.get("name", "")).lower()
    if agent_id:
        key = f"agent-{agent_id}"
        found = next((t for t in trees if os.path.basename(t.path) == key or slot_owner(t) == key), None)
        if found:
            return found
    return next((t for t in trees if not t.main and t.branch in (name, f"orch/{name}")), None)


def unsaved_work(path: Path) -> list[str]:
    """作業ツリーにしか無い成果。空なら、作業ツリーを次の担当へ渡しても何も失われない。
    確かめられなかったときも、失われうるものとして返す。"""
    r = git(path, "status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all")
    if r is None or r.returncode != 0:
        return ["git statusが失敗した（未コミットの変更を確かめられない）"]
    entries = r.stdout.decode("utf-8", errors="replace").split("\0")
    dirty = [e[3:] for e in entries if len(e) > 3 and e[3:] not in IGNORED_CHANGES]
    out = []
    if dirty:
        shown = "、".join(dirty[:5]) + (f" ほか{len(dirty) - 5}件" if len(dirty) > 5 else "")
        out.append(f"未コミットの変更がある: {shown}")
    unpushed = git_out(path, "rev-list", "--count", "HEAD", "--not", "--remotes=origin")
    if unpushed is None:
        out.append("pushしていないコミットを確かめられない（git rev-listが失敗した）")
    elif unpushed != "0":
        out.append(f"どのリモートの枝からも届かないコミットが{unpushed}件ある（pushしていない成果）")
    return out


def release_slot(ctx: Context, agent: dict) -> None:
    """担当に渡したスロットの印を外す。作業ツリーにしか無い成果が残っていれば外さずに理由を出す。
    Claude Codeは担当の終了時にWorktreeRemoveフックを呼ばない（中身のある作業ツリーは残す）ため、
    印を外す契機は司令塔が担当を監査で通したときに置く。"""
    if not agent.get("id"):
        return
    owner = f"agent-{agent['id']}"
    tree = next((t for t in list_worktrees(ctx) if slot_owner(t) == owner), None)
    if tree is None:
        return
    slot = os.path.basename(tree.path)
    problems = unsaved_work(Path(tree.path))
    if problems:
        print(f"{slot}の印を残した（渡し先 {owner}）: " + " / ".join(problems))
        return
    r = git(ctx.repo, "worktree", "unlock", tree.path)
    if r is None or r.returncode != 0:
        err = "時間切れ" if r is None else r.stderr.decode("utf-8", errors="replace").strip()
        print(f"{slot}の印を外せなかった（渡し先 {owner}）: {err}")
        return
    print(f"{slot}の印を外した（渡し先だった {owner}）")


class Facts:
    def __init__(self, ctx: Context, args: argparse.Namespace, *, cpu: bool = True):
        self.ctx = ctx
        self.at = now()
        self.board = load_board(ctx)
        self.limit = limit_of(self.board, getattr(args, "concurrent", None))
        self.active_min = args.active_min
        self.trees = list_worktrees(ctx)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(inspect_changes, [t for t in self.trees if not t.main]))
        self.agent_trees = {id(a): worktree_of(a, self.trees) for a in self.board["agents"]}
        self.stop = ctx.stop_path.exists()
        self.hooks_path = git_out(ctx.repo, "config", "--get", "core.hooksPath")
        self.cpu = cpu_percent() if cpu else None
        self.lock_records = self._recent_locks()
        self.lock_holders = self._lock_holders()
        self.ledger = ledger_rows(ctx)
        self.budgets = effort_budgets(effort_records(ctx))

    def _recent_locks(self) -> list[dict]:
        log = self.ctx.lock_root / "log.jsonl"
        if not log.exists():
            return []
        since = self.at - dt.timedelta(minutes=LOCK_WINDOW_MINUTES)
        rows = []
        with open(log, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                start = parse_time(row.get("start"))
                if start and start >= since:
                    rows.append(row)
        return rows

    def _lock_holders(self) -> list[str]:
        if not self.ctx.lock_root.is_dir():
            return []
        out = []
        for entry in sorted(self.ctx.lock_root.iterdir()):
            if entry.is_dir():
                age = minutes(self.at - dt.datetime.fromtimestamp(entry.stat().st_ctime).astimezone())
                out.append(f"{entry.name}（{age}分保持）")
        return out

    def tree(self, agent: dict) -> Worktree | None:
        return self.agent_trees.get(id(agent))

    def active(self) -> list[str]:
        """手元で動いているものの一覧。状態の表で稼働中のもの＋最近変更のある作業ツリー。"""
        names, seen = [], set()
        for a in self.board["agents"]:
            if a.get("state") in ACTIVE_STATES and not is_cloud(a):
                names.append(f"{a.get('name')}（表: {a.get('state')}）")
                t = self.tree(a)
                if t:
                    seen.add(t.path)
        for t in self.trees:
            if not t.main and t.path not in seen and t.active(self.at, self.active_min):
                owner = next((a.get("name") for a in self.board["agents"] if self.tree(a) is t), None)
                why = f"表では{owner}" if owner else "表に無い"
                names.append(f"{t.label}（{why}・{hm(t.newest_change)}に変更）")
        return names

    def overrun(self) -> list[str]:
        out = []
        for a in self.board["agents"]:
            if a.get("state") not in ACTIVE_STATES or audit_pending(a):
                continue
            first, budget = parse_time(a.get("task_first_started")), budget_of(a, self.ledger, self.budgets)
            if first and budget is not None:
                total = minutes(self.at - first)
                if total > budget:
                    task = a.get("current_task") or "現在のタスク"
                    out.append(f"{a.get('name')}: {task}の着手から通算{total}分 / 規模の予算{budget}分")
            start, expected = parse_time(a.get("started")), a.get("expected_min")
            if start and isinstance(expected, (int, float)):
                elapsed = minutes(self.at - start)
                if elapsed > expected:
                    out.append(f"{a.get('name')}: 今回の区切りで経過{elapsed}分 / 見込み{expected}分")
        return out

    def audit_waiting(self) -> list[dict]:
        return [a for a in self.board["agents"] if audit_pending(a)]

    def lock_wait_problems(self) -> list[str]:
        out = []
        for row in self.lock_records:
            if row.get("wait_s", 0) >= LOCK_WAIT_LIMIT_MINUTES * 60:
                out.append(f"{row.get('lock')}: {row['wait_s'] / 60:.0f}分待ち（{row.get('start', '')[11:16]}開始）")
        return out


# ---------------------------------------------------------------- gate


def restore_hooks_path(ctx: Context) -> None:
    """Claude Codeは作業ツリーを作るたびに共有のcore.hooksPathを本体の絶対パスへ書き換える
    （anthropics/claude-code#66993）。振り出し・再開を表へ記録するこの時点で相対へ戻す。"""
    current = git_out(ctx.repo, "config", "--get", "core.hooksPath")
    if current != EXPECTED_HOOKS_PATH:
        subprocess.run(["git", "config", "core.hooksPath", EXPECTED_HOOKS_PATH], cwd=ctx.repo, check=True)
        print(f"core.hooksPathを相対の{EXPECTED_HOOKS_PATH}へ戻した（{current}）")


def gate_reasons(f: Facts, args: argparse.Namespace) -> list[str]:
    """門を閉じている理由。空なら振り出してよい。"""
    ng: list[str] = []
    active = f.active()
    if len(active) >= f.limit:
        ng.append(f"稼働が上限に達している（{len(active)}本 / 上限{f.limit}本）")
    waiting = f.audit_waiting()
    if waiting:
        ng.append("監査待ちがある: " + "、".join(str(a.get("name")) for a in waiting))
    over = f.overrun()
    if over:
        ng.append("見込み超過がある: " + "、".join(over))
    if f.stop:
        ng.append(f"停止ファイルがある（{f.ctx.stop_path}）")
    locks = f.lock_wait_problems()
    if locks:
        ng.append(f"直近{LOCK_WINDOW_MINUTES}分にロック待ち{LOCK_WAIT_LIMIT_MINUTES}分以上: " + "、".join(locks))
    if f.cpu is not None and f.cpu >= args.cpu_max:
        ng.append(f"CPUが飽和している（{f.cpu:.0f}% ≥ {args.cpu_max}%）")
    return ng


def cmd_gate(ctx: Context, args: argparse.Namespace) -> int:
    f = Facts(ctx, args)
    ng = gate_reasons(f, args)
    active = f.active()

    print(f"{'NG' if ng else 'OK'}: 振り出し{'不可' if ng else '可'}")
    for reason in ng:
        print(f"  - {reason}")
    print(f"稼働 {len(active)}本 / 上限{f.limit}本")
    for name in active:
        print(f"  - {name}")
    print(f"CPU: {'未取得' if f.cpu is None else f'{f.cpu:.0f}%'}"
          f"  ロック保持: {'、'.join(f.lock_holders) or 'なし'}")
    return 1 if ng else 0


# ---------------------------------------------------------------- status


def stale_slot(f: Facts, a: dict) -> str | None:
    """止まって監査も待っていない担当が、スロットの印を持ったままか。持っていれば外し方の文。
    印が残ると、そのスロットは次の担当へ渡らず、同時に動かせる本数が1つ減る。"""
    t = f.tree(a)
    if a.get("state") not in STOPPED_STATES or t is None or not slot_owner(t) or audit_pending(a):
        return None
    name = os.path.basename(t.path)
    return (f"表は{a.get('state')}だが{name}の印が残っている（監査で通すと外れる。通さずに止めたなら"
            f" orchestrate.py slot release {name.removeprefix('slot-')}）")


def agent_marks(f: Facts, a: dict, states: dict[str, str | None], listed: set[str]) -> list[str]:
    """状態の表と事実の食い違い（!）と、確かめるべき点（?）。"""
    marks = []
    t, state = f.tree(a), a.get("state")
    if state not in STATES:
        marks.append(f"! 状態が語彙に無い（{state}）")
    if not is_cloud(a):
        if state in ACTIVE_STATES and (t is None or not t.exists):
            marks.append("! 表は稼働だが作業ツリーが無い")
        if state not in ACTIVE_STATES and t is not None and t.active(f.at, f.active_min):
            marks.append(f"! 表は{state}だが作業ツリーが{hm(t.newest_change)}に変更されている")
        held = stale_slot(f, a)
        if held:
            marks.append(f"! {held}")
    task = a.get("current_task")
    if task:
        st, in_ledger = states.get(task), task in listed
        if st is None:
            marks.append(f"! {task}: origin/masterにタスク記録が無い")
        elif st == "完了" and in_ledger:
            marks.append(f"! {task}: 完了なのに台帳に行がある")
        elif st == "未完了" and not in_ledger:
            marks.append(f"! {task}: 未完了なのに台帳に行が無い")
    return marks


def cmd_status(ctx: Context, args: argparse.Namespace) -> int:
    f = Facts(ctx, args, cpu=False)
    agents = f.board["agents"]
    if args.target:
        key = args.target.lower()
        agents = [a for a in agents if str(a.get("name", "")).lower() == key
                  or args.target == a.get("current_task")]
        if not agents:
            print(f"該当するエージェントがありません: {args.target}")
            return 1
    tasks = sorted({a["current_task"] for a in agents if a.get("current_task")})
    specs = [f"origin/master:{TASKS_DIR}/{t}.md" for t in tasks] + [f"origin/master:{PLAN_DOC}"]
    blobs = cat_files(ctx.repo, specs)
    states = {t: task_state(blobs[f"origin/master:{TASKS_DIR}/{t}.md"]) for t in tasks}
    listed = ledger_ids(blobs[f"origin/master:{PLAN_DOC}"])
    master = git_out(ctx.repo, "log", "-1", "--format=%h %ct", "origin/master") or ""
    master_sha, _, master_ts = master.partition(" ")

    b = f.board
    view = population_view(ctx, b, f.ledger)
    for line in run_summary_lines(view, detail=False):
        print(line)
    population = {e["task"] for e in view["entries"]}
    print(f"上限{f.limit}本  最終確認 {hm(parse_time(b.get('last_check')))}"
          f"  origin/master {master_sha}"
          f"（{hm(dt.datetime.fromtimestamp(int(master_ts)).astimezone()) if master_ts else '-'}。fetchはしない）")
    print(f"稼働（手元）{len(f.active())}本  監査待ち{len(f.audit_waiting())}本"
          f"  停止ファイル{'あり' if f.stop else 'なし'}  core.hooksPath={f.hooks_path}")
    print(budget_line(f.budgets))
    reasons: dict[str, dict[str, int]] = {}
    for r in effort_records(ctx):
        if r["reason"]:
            by_scale = reasons.setdefault(r["scale"] or "規模札なし", {})
            by_scale[r["reason"]] = by_scale.get(r["reason"], 0) + 1
    if reasons:
        print("超過の理由（所要の行の「超過:」）: " + " ／ ".join(
            f"{s} " + "・".join(f"{k}{n}件" for k, n in c.items()) for s, c in reasons.items()))
    for a in agents:
        state = a.get("state", "-")
        start, expected = parse_time(a.get("started")), a.get("expected_min")
        progress = ""
        if state in ACTIVE_STATES and start:
            progress = f"  経過{minutes(f.at - start)}分/見込み{expected if expected is not None else '-'}分"
            first = parse_time(a.get("task_first_started"))
            if first:
                progress += (f"  {a.get('current_task') or '現在のタスク'}: 着手から{minutes(f.at - first)}分"
                             f"/予算{budget_of(a, f.ledger, f.budgets) or '-'}分")
        print(f"\n{a.get('name')}  [{state}]  {a.get('where', '-')}  開始{hm(start)}{progress}")
        t = f.tree(a)
        if t is None:
            print("  作業ツリー: 無し")
        else:
            dirty = "未取得" if t.dirty is None else f"{t.dirty}件"
            change = f"（最新の変更 {hm(t.newest_change)}）" if t.newest_change else ""
            print(f"  作業ツリー: {t.label}  先頭 {(t.head or '-')[:8]}  最新コミット {hm(t.commit_time)}"
                  f"  未コミット{dirty}{change}")
        if audit_pending(a):
            reported = parse_time(a.get("reported"))
            wait = f"{minutes(f.at - reported)}分待ち" if reported else "受領時刻が未記録"
            sha = a.get("reported_sha")
            print(f"  監査待ち: {sha or 'sha未記録'}（{wait}）")
            if sha and t is not None and t.head and not is_ancestor(ctx.repo, str(sha), t.head):
                print("  ! 報告のshaが作業ツリーの履歴に無い（報告後にrebaseした?）")
        if a.get("current_task"):
            task = a["current_task"]
            print(f"  {task}: {task_title(ctx, task, f.ledger)}")
            print(f"    master上の状態={states.get(task) or '記録なし'}  台帳={'あり' if task in listed else 'なし'}")
        for mark in agent_marks(f, a, states, listed):
            print(f"  {mark}")
        if population and a.get("current_task") and a["current_task"] not in population:
            print(f"  ? {a['current_task']}は回の母集団の外（派生なら board run add {a['current_task']} from=<派生元>）")
    if not args.target:
        owned = {f.tree(a).path for a in f.board["agents"] if f.tree(a)}
        stray = [t for t in f.trees if not t.main and t.path not in owned and t.dirty]
        if stray:
            print("\n表に無い作業ツリー（未コミット変更あり）:")
            for t in stray:
                print(f"  {t.label}  未コミット{t.dirty}件  最新の変更 {hm(t.newest_change)}"
                      f"{'  ← 最近動いている' if t.active(f.at, f.active_min) else ''}")
    return 0


# ---------------------------------------------------------------- check


def heavy_stages(convention: str) -> list[str]:
    """規約の「対象」の項目にコード書式で挙げた重い段（例: `tsc --noEmit`）。別の一覧は持たない。"""
    lines = convention.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(HEAVY_TARGET_PREFIX):
            block = [line]
            for rest in lines[i + 1:]:
                if not rest.startswith("  "):
                    break
                block.append(rest)
            return re.findall(r"`([^`]+)`", " ".join(block))
    return []


def stage_pattern(stage: str) -> re.Pattern:
    """段の語が、1つのコマンドの中にこの順で現れるか。先頭の語はパスの末尾・拡張子付きでもよい
    （`node .../typescript/bin/tsc --noEmit`・`vitest.mjs run`）。"""
    words = stage.split()
    head = r"(?:^|[\s/\\'\"`(&;|])" + re.escape(words[0]) + r"(?:\.(?:cmd|exe|mjs|js))?"
    tail = "".join(r"(?:\s+[^\s;&|]+)*?\s+" + re.escape(w) for w in words[1:])
    return re.compile(head + tail + r"(?=$|[\s'\"`;&|)])")


def heavy_outside_lock(ctx: Context) -> list[str]:
    """枠（`heavy`の保持者）の子孫でないところで走っている重い段。候補であって判定ではない
    （コマンドラインに段の語を含むだけの`grep`等も拾う）。"""
    from orchestration import procs

    table = procs.processes()
    if table is None:
        return []
    convention = cat_files(ctx.repo, [f"origin/master:{CONVENTION_DOC}"])[f"origin/master:{CONVENTION_DOC}"]
    stages = [(s, stage_pattern(s)) for s in heavy_stages(convention or "")]
    if not stages:
        return [f"重い段を規約から読めない（origin/master:{CONVENTION_DOC}の「{HEAVY_TARGET_PREFIX}」の項目）"]
    try:
        holder = json.loads((ctx.lock_root / HEAVY_LOCK / "owner.json").read_text(encoding="utf-8")).get("pid")
    except (OSError, ValueError, AttributeError):
        holder = None
    matched = {}
    for p in table.values():
        # lockrunを呼んだ包み（待っている間も含む）は、コマンドラインに段の語を持つが枠の外で走ってはいない。
        if p.cmdline and "lockrun.py" not in p.cmdline:
            stage = next((s for s, rx in stages if rx.search(p.cmdline)), None)
            if stage:
                matched[p.pid] = stage
    out = []
    for pid, stage in sorted(matched.items()):
        chain = procs.ancestors(table, pid)
        if any(a.pid in matched for a in chain) or any(a.pid == holder for a in chain):
            continue
        cmd = " ".join(table[pid].cmdline.split())
        out.append(f"{stage}（pid {pid}、{table[pid].name}）: {cmd[:120]}")
    return out


def cmd_check(ctx: Context, args: argparse.Namespace) -> int:
    f = Facts(ctx, args)
    problems: list[str] = []
    active = f.active()
    if len(active) > f.limit:
        problems.append(f"稼働が上限を超えている（{len(active)}本 / 上限{f.limit}本）: " + "、".join(active))
    problems += [f"見込み超過: {x}" for x in f.overrun()]
    stale = dt.timedelta(minutes=args.stale_min)
    for a in f.board["agents"]:
        t = f.tree(a)
        if a.get("state") in ACTIVE_STATES and not is_cloud(a):
            if t is None or not t.exists:
                problems.append(f"{a.get('name')}: 表は稼働だが作業ツリーが無い")
            elif (t.commit_time and f.at - t.commit_time > stale and t.newest_change
                  and t.newest_change > t.commit_time):
                problems.append(f"{a.get('name')}: {minutes(f.at - t.commit_time)}分コミットが無いまま"
                                f"未コミット変更が{t.dirty}件積み上がっている（最新の変更 {hm(t.newest_change)}）")
        elif t is not None and not is_cloud(a) and t.active(f.at, f.active_min):
            problems.append(f"{a.get('name')}: 表は{a.get('state')}だが作業ツリーが{hm(t.newest_change)}に変更されている")
        held = None if is_cloud(a) else stale_slot(f, a)
        if held:
            problems.append(f"{a.get('name')}: {held}")
        if audit_pending(a):
            reported = parse_time(a.get("reported"))
            if reported is None:
                problems.append(f"{a.get('name')}: 監査待ちだが報告の受領時刻が未記録（board set {a.get('name')} reported=now）")
            elif (f.at - reported > dt.timedelta(minutes=args.audit_wait_min)
                  and parse_time(a.get("audit_started")) is None):
                problems.append(f"{a.get('name')}: 監査待ちの放置（受領から{minutes(f.at - reported)}分、未着手）")
    if f.hooks_path != EXPECTED_HOOKS_PATH:
        problems.append(f"core.hooksPathが相対の{EXPECTED_HOOKS_PATH}でない（{f.hooks_path}）")
    if f.stop:
        problems.append(f"停止ファイルが置かれている（{ctx.stop_path}）")
    problems += [f"ロック待ち: {x}" for x in f.lock_wait_problems()]
    if f.cpu is not None and f.cpu >= args.cpu_max:
        problems.append(f"CPUが飽和している（{f.cpu:.0f}% ≥ {args.cpu_max}%）")
    problems += [f"枠の外の重い処理: {x}" for x in heavy_outside_lock(ctx)]
    problems += ci_duration_problems(ctx, f.board)
    unpushed = audited_unpushed(ctx, f.board, f.at)
    if push_due(ctx, unpushed, f.at):
        problems.append(f"要対応: {push_due_line(ctx, unpushed, f.at)}（board unpushed）")
    problems += [f"表に写しのキーがある: {k}" for k in board_copy_keys(f.board)]
    view = population_view(ctx, f.board, f.ledger)
    population = {e["task"] for e in view["entries"]}
    if not population and any(a.get("state") in ACTIVE_STATES for a in f.board["agents"]):
        problems.append("担当が稼働しているのに、回の目的と母集団が表に無い（board run goal・board run add）")
    problems += [f"母集団の{e['task']}: origin/masterに記録が無い" for e in view["entries"] if e["kind"] == "記録なし"]
    if view["ended"]:
        problems.append("要対応: 回の終わりの条件1に当たっている（母集団がすべて完了かトリガー待ち）。新しいタスクは"
                        "振り出さず、終わった状態を揃える（規約「回の始まりと終わり」）")
    # 門がNGで見送った振り出しは、門が開いた最初の確認で拾う（「落ち着いたら」を人の注意に頼らない）。
    # 回に母集団があれば、その外のタスクは次の回の候補なので拾わない。終わりに入ったら何も拾わない。
    waiting_dispatch = [] if view["ended"] else [
        i for i in ready_to_dispatch(ctx, f.board.get("queue") or [])
        if not population or str(i.get("task")) in population]
    if waiting_dispatch and not gate_reasons(f, args):
        first = str(waiting_dispatch[0].get("task"))
        problems.append(f"要対応: 振り出し待ち{len(waiting_dispatch)}件があり、門が開いている"
                        f"（例: {first} {task_title(ctx, first, f.ledger)}。board dispatch pop で取り出して振り出す）")

    cpu = "未取得" if f.cpu is None else f"{f.cpu:.0f}%"
    if problems:
        print(f"異常 {len(problems)}件（{hm(f.at)}、稼働{len(active)}本/上限{f.limit}本、CPU {cpu}）")
        for p in problems:
            print(f"  - {p}")
    else:
        print(f"異常なし（{hm(f.at)}、稼働{len(active)}本/上限{f.limit}本、"
              f"監査待ち{len(f.audit_waiting())}本、CPU {cpu}）")
    for line in run_summary_lines(view, detail=False):
        print(line)
    print(budget_line(f.budgets))
    if args.record:
        board = load_board(ctx)
        board["last_check"] = iso(f.at)
        save_board(ctx, board)
        interval = board.get("check_interval_min") if isinstance(board.get("check_interval_min"), int) else 20
        (ctx.dir / "next_check").write_text(f"{int(time.time()) + interval * 60}\n", encoding="ascii", newline="\n")
    return 1 if problems else 0


def fast_common_dir(root: Path) -> Path | None:
    """gitを起こさずに共通ディレクトリを求める（フックは道具を使うたびに走るため、プロセスを足さない）。"""
    dotgit = root / ".git"
    if dotgit.is_dir():
        return dotgit
    try:
        gitdir = Path(dotgit.read_text(encoding="utf-8").strip().removeprefix("gitdir:").strip())
        if not gitdir.is_absolute():
            gitdir = root / gitdir
        commondir = gitdir / "commondir"
        if commondir.exists():
            rel = commondir.read_text(encoding="utf-8").strip()
            return (gitdir / rel).resolve() if not Path(rel).is_absolute() else Path(rel)
        return gitdir
    except OSError:
        return None


def check_if_due(args: argparse.Namespace) -> int:
    """PostToolUseのフック（scripts/orchestration/hook.shの前段を通ったもの）から呼ばれる入口。司令塔のセッションで、前回の確認から確認間隔を過ぎた
    ときだけcheckを走らせ、結果を文脈へ返す。それ以外は何もせずに抜ける（全セッションで走るため）。"""
    try:
        hook = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except ValueError:
        hook = {}
    if hook.get("agent_id"):
        return 0  # サブエージェントの道具の呼び出し
    orch_dir = Path(args.dir) if args.dir else ((c / "orchestration") if (c := fast_common_dir(Path(args.repo))) else None)
    board_path = orch_dir / "board.json" if orch_dir else None
    if board_path is None or not board_path.exists():
        return 0  # 並行実行をしていない
    session = hook.get("session_id")
    command = str((hook.get("tool_input") or {}).get("command", ""))
    ctx = SimpleNamespace(dir=orch_dir, board_path=board_path)
    board = load_board(ctx)
    if session and "orchestrate.py board claim" in command:
        board["coordinator_session"] = session
        save_board(ctx, board)
        # scripts/orchestration/hook.shがpythonを起こさずに読む写し。
        (orch_dir / "coordinator_session").write_text(f"{session}\n", encoding="utf-8", newline="\n")
        hook_context("このセッションを司令塔として記録した（定期確認はこのセッションで走る）")
        return 0
    if not session or board.get("coordinator_session") != session:
        return 0
    interval = board.get("check_interval_min") if isinstance(board.get("check_interval_min"), int) else 20
    last = parse_time(board.get("last_check"))
    if last and now() - last < dt.timedelta(minutes=interval):
        # 次の時刻を写しておき、それまでは前段がpythonを起こさずに抜けられるようにする。
        due = int((last + dt.timedelta(minutes=interval)).timestamp())
        (orch_dir / "next_check").write_text(f"{due}\n", encoding="ascii", newline="\n")
        return 0
    # 同時に走った別の道具の呼び出しが重ねて確認しないよう、先に時刻を取る。
    board["last_check"] = iso(now())
    save_board(ctx, board)
    (orch_dir / "next_check").write_text(f"{int(time.time()) + interval * 60}\n", encoding="ascii", newline="\n")
    r = subprocess.run([sys.executable, str(ENTRY), "--repo", args.repo,
                        *(["--dir", args.dir] if args.dir else []), "check"],
                       capture_output=True, timeout=STATIC_CHECK_TIMEOUT, check=False)
    text = (r.stdout + r.stderr).decode("utf-8", errors="replace").strip()
    hook_context(f"[定期確認 orchestrate.py check]\n{text}")
    return 0


def hook_context(text: str) -> None:
    # ASCIIへ逃がして出す（フックの標準出力の文字コードに頼らない）。
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))


# ---------------------------------------------------------------- audit


def cmd_audit(ctx: Context, args: argparse.Namespace) -> int:
    repo = ctx.repo
    sha = git_out(repo, "rev-parse", "--verify", f"{args.sha}^{{commit}}")
    if sha is None:
        print(f"コミットが見つかりません: {args.sha}")
        return 2
    base_ref = args.base or "origin/master"
    base = git_out(repo, "merge-base", base_ref, sha)
    if base is None:
        print(f"{base_ref}との分岐点が見つかりません")
        return 2
    board = load_board(ctx)
    agent = find_agent(board, args.name)
    queue = [agent["current_task"]] if agent and agent.get("current_task") else []
    base_note = f"{base_ref}との分岐点"
    if agent and not args.base:
        # 前回通したコミットがまだmasterへ届いていなければ、その先だけが今回の範囲。
        passed = [e.get("reported_sha") for e in agent.get("audit_log") or [] if e.get("audit_result") == "通す"]
        last = next((s for s in reversed(passed) if s), None)
        if last and last != sha and is_ancestor(repo, base, str(last)) and is_ancestor(repo, str(last), sha):
            base, base_note = git_out(repo, "rev-parse", str(last)) or base, "前回通したコミット"
    flags = 0

    def flag(text: str) -> None:
        nonlocal flags
        flags += 1
        print(f"  ! {text}")

    print(f"監査: {args.name} {sha[:8]}（範囲 {base[:8]}..{sha[:8]}。基点は{base_note}）")
    if agent is None:
        print("  （状態の表にこの名前のエージェントが無い。キューとの突き合わせは飛ばす）")

    # 1. 範囲
    names = git_out(repo, "diff", "--name-status", "--no-renames", base, sha) or ""
    changes = [line.split("\t", 1) for line in names.splitlines() if "\t" in line]
    files = [p for _, p in changes]
    print(f"\n1. 範囲（{len(files)}ファイル）")
    print("\n".join(f"  {line}" for line in (git_out(repo, "diff", "--stat=120", base, sha) or "").splitlines()))
    for status, path in changes:
        if path in IGNORED_CHANGES:
            flag(f"混入: {path}")
        elif SCRATCH_RE.search(path):
            flag(f"使い捨ての候補: {path}")
        elif status == "A" and E2E_SPEC_RE.match(path):
            flag(f"新しいe2eのspec（CIが拾う。使い捨てでないか）: {path}")
    touched_tasks = [m.group(1) for p in files if (m := TASK_DOC_RE.match(p))]
    for task in touched_tasks:
        if agent and task not in queue:
            print(f"  ? 担当のタスク外の記録を触っている: {task}（起票なら問題ない）")

    # 2. 記録の整合
    print("\n2. 記録の整合（報告のコミット時点）")
    specs = [f"{sha}:{TASKS_DIR}/{t}.md" for t in touched_tasks] + [f"{sha}:{PLAN_DOC}"]
    blobs = cat_files(repo, specs)
    listed = ledger_ids(blobs[f"{sha}:{PLAN_DOC}"])
    if not touched_tasks:
        flag("タスク記録（docs/records/tasks/Txxx.md）を1件も触っていない")
    for task in touched_tasks:
        text = blobs[f"{sha}:{TASKS_DIR}/{task}.md"]
        st = task_state(text)
        row = task in listed
        line = f"{task}: 状態={st or '削除'}  台帳={'あり' if row else 'なし'}"
        if st == "完了" and not row:
            print(f"  ? {line} → 担当が台帳の行を消している（台帳の行は取り込みの後に ledger close が消す。"
                  "隣の行を消した担当と取り込みで衝突しうる）")
        elif st == "未完了" and not row:
            flag(line + " → 未完了なのに台帳に行が無い")
        elif st not in ("完了", "未完了"):
            flag(line + " → 状態行が完了/未完了で始まらない")
        else:
            hold = " 保留の記述あり" if st == "未完了" and text and "保留" in text else ""
            print(f"  {line}{hold}")

    # 4. 検証の証拠
    print("\n4. 検証の証拠（コミットメッセージの記述の有無の目安。判定ではない）")
    log = git_out(repo, "log", "--format=%x00%h %s%x01%B", f"{base}..{sha}") or ""
    for entry in filter(None, log.split("\0")):
        head, _, body = entry.partition("\x01")
        found = [label for label, rx in (("コマンド", COMMAND_HINT_RE), ("観測値", OBSERVED_HINT_RE),
                                          ("増減", DELTA_HINT_RE)) if rx.search(body)]
        missing = [x for x in ("コマンド", "観測値", "増減") if x not in found]
        text = f"{head[:70]}  有: {'・'.join(found) or 'なし'}"
        if missing:
            flag(f"{text}  無: {'・'.join(missing)}")
        else:
            print(f"  {text}")

    # 7. 同期ルール
    print("\n7. 同期ルール")
    decl = [p for p in files if API_DECL_RE.match(p)]
    if decl and not any(p.startswith(GENERATED_PREFIX) for p in files):
        flag(f"API・domainの宣言を変えたが{GENERATED_PREFIX}が変わっていない"
             f"（再生成して差分が出ないなら問題ない）: {'、'.join(decl[:5])}")
    code = [p for p in files if p.endswith((".py", ".ts", ".tsx")) and not p.startswith(GENERATED_PREFIX)]
    modules = [p for p in files if p.startswith("docs/modules/")]
    print(f"  実装ファイル{len(code)}件・docs/modules/{len(modules)}件を変更"
          f"{'（実装を変えてモジュール文書が0件。追従が要らないか）' if code and not modules else ''}")

    # 重い検査は担当が作業ブランチ（orch/<名前>）へpushしてCIに回すため、監査はその結論を読む。
    print("\nCI（報告のコミットに対するGitHub Actionsの結論）")
    latest: list[dict] = []
    if args.no_ci:
        print("  （--no-ci により未取得）")
    else:
        verdicts, latest = ci_verdicts(sha)
        for text, bad in verdicts:
            if bad:
                flag(text)
            else:
                print(f"  {text}")

    needs_user = False
    if not args.no_ci:
        needs_user = audit_ci_duration(ctx, sha, latest)
        from orchestration import effort_ci

        effort_ci.print_proposals(effort_ci.proposals(repo, args.name, base, sha, latest), args.name, sha, base)

    backend = any(p.startswith("backend/") for p in files)
    print("\n未判定（司令塔が判断する）:")
    print("  3. 完了条件 — Txxx.mdの完了条件の各項目に、何で確かめたかが書かれているか")
    print("  5. 主張の抜き取り検証 — 結論が最も強く依存する主張を1つ自分で確かめる")
    print(f"  6. 本番への影響 — backend/**を{'含む。DB行の互換・マイグレーション・本番操作の記述を確かめる' if backend else '含まない'}")
    print("  8. 報告の正確さ・9. 見積もりとのずれ — 記録")
    print(f"\n機械で見た項目の指摘 {flags}件")
    if needs_user:
        print("ユーザー確認（項目10）に当たる: 通さず、所要の比較を添えてユーザーへ上げる"
              "（通す・縮めてから通す・CIの持ち場を変える）")
    print(f"通すなら: python scripts/orchestrate.py board set {args.name} reported_sha={sha[:12]} "
          f"audit_base={base[:12]} audit_done=now audit_result=通す [urgent=true]")
    return 1 if flags else 0


def ci_verdicts(sha: str) -> tuple[list[tuple[str, bool]], list[dict]]:
    """(`sha`に対するワークフローごとの最新の結論、その実行)。結論の2つめの値は、監査を通せない
    （失敗・結論待ち・取得できない・実行が無い）ことを表す。"""
    from check_master_ci import is_failure, latest_per_workflow

    from orchestration.github import actions_runs

    runs, error = actions_runs(f"head_sha={sha}&per_page=30")
    if runs is None:
        return [(f"CIの結論を取得できない（{error}）", True)], []
    latest = sorted(latest_per_workflow(runs, sha), key=lambda r: str(r.get("name")))
    if not latest:
        return [("このコミットに対するCIの実行が無い（orch/<名前>へpushしていないか、pushした先端のコミットではない）", True)], []
    verdicts = []
    for run in latest:
        done = run.get("status") == "completed"
        state = run.get("conclusion") if done else f"結論待ち（{run.get('status')}）"
        verdicts.append((f"{run.get('name')}: {state}  {run.get('html_url', '')}", is_failure(run) or not done))
    return verdicts, latest


def ancestors_of(ctx: Context, sha: str) -> set[str] | None:
    """`sha`の祖先（master側の基準の実行を選ぶため）。コミットが手元に無ければNone。"""
    out = git_out(ctx.repo, "rev-list", f"--max-count={CI_ANCESTRY_DEPTH}", sha)
    return set(out.split()) if out else None


def audit_ci_duration(ctx: Context, sha: str, latest: list[dict]) -> bool:
    """監査の項目10の機械の比較を出す。ユーザー確認に当たればTrue。"""
    from orchestration import ci_duration as cd

    print(f"\n10. 共有資源への波及（CIのジョブごとの所要を、合流点までのmasterの直近{cd.BASELINE_RUNS}回の成功の"
          f"同じジョブの最大値と比べる。{cd.MARGIN_SECONDS}秒以上長ければユーザー確認）")
    target = next((r for r in latest if str(r.get("path", "")).endswith(f"/{cd.CI_WORKFLOW}")), None)
    if target is None:
        print(f"  {cd.CI_WORKFLOW}の実行が無い（docsだけの変更なら対象外）")
        return False
    if target.get("status") != "completed":
        print("  CIが完了していない（完了してから比べる）")
        return False
    masters, error = cd.master_runs()
    if masters is None:
        print(f"  masterの実行を取得できない（{error}）。司令塔がGitHubのジョブの所要から手で出す")
        return False
    rows, base, error = cd.compare_run(target, ancestors_of(ctx, sha), ctx.dir, masters)
    print(f"  基準: master {len(base)}回（" + "、".join(f"{str(r.get('head_sha'))[:8]}" for r in base) + "）")
    if rows is None:
        print(f"  {error}。司令塔がGitHubのジョブの所要から手で出す")
        return False
    for row in rows:
        print(f"  {cd.row_line(row)}")
    if any(row.differs or row.master_only_job for row in rows):
        print("  masterでだけ走る段は作業ブランチのCIに出ない。その段を足す・伸ばす変更は、担当が手元で測った前後の所要で判断する")
    return any(row.needs_user for row in rows)


def ci_duration_problems(ctx: Context, board: dict) -> list[str]:
    """定期確認: 稼働中・監査待ちの担当の作業ブランチ（orch/<名前>）の直近の成功したCIで、masterの基準より
    伸びたジョブ。取得できなければ異常にしない（ネットワークの都合で定期確認を鳴らさない）。"""
    from orchestration import ci_duration as cd
    from orchestration.github import actions_runs

    branches = {f"orch/{a.get('name')}" for a in board.get("agents") or []
                if a.get("state") in ACTIVE_STATES or audit_pending(a)}
    if not branches:
        return []
    runs, _ = actions_runs(f"status=completed&per_page={cd.BRANCH_LISTING}", cd.CI_WORKFLOW)
    latest: dict[str, dict] = {}
    for run in runs or []:
        latest.setdefault(str(run.get("head_branch")), run)
    targets = [r for b, r in sorted(latest.items()) if b in branches and r.get("conclusion") == "success"]
    if not targets:
        return []
    masters, _ = cd.master_runs()
    if masters is None:
        return []
    problems = []
    for run in targets:
        sha = str(run.get("head_sha"))
        rows, _, _ = cd.compare_run(run, ancestors_of(ctx, sha), ctx.dir, masters)
        over = [r for r in rows or [] if r.needs_user]
        if over:
            problems.append(f"共有資源への波及: {run.get('head_branch')} {sha[:8]}のCIで"
                            + "、".join(f"{r.job} {r.seconds}秒（masterの基準の最大{max(r.baseline)}秒より+{r.over}秒）"
                                       for r in over)
                            + f"。監査では項目10のユーザー確認に当たる {run.get('html_url', '')}")
    return problems


# ---------------------------------------------------------------- board


def parse_value(raw: str, at: dt.datetime) -> object:
    if raw == "now":
        return iso(at)
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def nested_key_reason(key: str) -> str | None:
    """`limits.x`・`run.x`の形のキーを表に書いてはならない理由。書いてよければNone。"""
    head, _, sub = key.partition(".")
    leaf = sub.split(".")[0]
    if head == "limits" and sub:
        return FORBIDDEN_KEYS["limits"].get(sub)
    if head == "run" and sub:
        if leaf == "population":
            return "母集団は board run add・remove で足し引きする（各タスクの状態は記録と台帳から導く）"
        if leaf not in RUN_KEYS:
            return (f"回に持つのは {'・'.join(RUN_KEYS)} だけ（母集団の状態・残り・終わりの条件は記録と台帳から"
                    "導き、出来事とまとめは回の記録 Txxx.md へ）")
    return None


def board_copy_keys(board: dict) -> list[str]:
    """状態の表にある写しのキー（手で書かれたものを含む）。コマンドを通した書き込みでは生じない。"""
    out = []
    for key in board:
        if key in FORBIDDEN_KEYS["top"] and key != "run":
            out.append(f"{key}（正本: {FORBIDDEN_KEYS['top'][key]}）")
    for key in (board.get("limits") or {}):
        if key in FORBIDDEN_KEYS["limits"]:
            out.append(f"limits.{key}（正本: {FORBIDDEN_KEYS['limits'][key]}）")
    for agent in board.get("agents") or []:
        for key in agent:
            if key in FORBIDDEN_KEYS["agent"]:
                out.append(f"{agent.get('name')}.{key}（正本: {FORBIDDEN_KEYS['agent'][key]}）")
    for item in board.get("queue") or []:
        for key in item:
            if key in FORBIDDEN_KEYS["queue"]:
                out.append(f"queue {item.get('task')}.{key}（正本: {FORBIDDEN_KEYS['queue'][key]}）")
    run = board.get("run")
    if isinstance(run, dict):
        out += [f"run.{k}（{nested_key_reason('run.' + k)}）" for k in run if k not in RUN_KEYS]
        for item in run.get("population") or []:
            out += [f"run.population {item.get('task')}.{k}（母集団の1件に持つのは"
                    f" {'・'.join(POPULATION_ITEM_KEYS)} だけ。状態・題名は記録と台帳から導く）"
                    for k in item if k not in POPULATION_ITEM_KEYS]
    return out


def apply_pairs(target: dict, pairs: list[str], at: dt.datetime, forbidden: dict[str, str] | None = None) -> None:
    for pair in pairs:
        append = "+=" in pair and pair.index("+=") < pair.index("=") + 1
        key, _, raw = pair.partition("+=" if append else "=")
        if not key or ("=" not in pair):
            raise SystemExit(f"k=v の形ではありません: {pair}")
        reason = (forbidden or {}).get(key) or nested_key_reason(key)
        if reason:
            raise SystemExit(f"{key} は表に書かない（写しになる）。正本: {reason}")
        value = parse_value(raw, at)
        if key == "state" and value not in STATES:
            raise SystemExit(f"状態の語彙に無い: {value}（使えるのは {'・'.join(STATES)}。"
                             "監査の段階は reported・audit_done から導く）")
        *parents, leaf = key.split(".")
        node = target
        for p in parents:
            node = node.setdefault(p, {})
        if append:
            current = node.setdefault(leaf, [])
            if not isinstance(current, list):
                raise SystemExit(f"{key} は配列ではないため += できません")
            current.append(value)
        else:
            node[leaf] = value


def cmd_board(ctx: Context, args: argparse.Namespace) -> int:
    board = load_board(ctx)
    at = now()
    if args.board_cmd in ("set", "add"):
        agent = find_agent(board, args.name)
        if args.board_cmd == "add":
            if agent is not None:
                raise SystemExit(f"既にある: {args.name}（board set で更新する）")
            agent = {"name": args.name, "where": "local", "state": "稼働", "started": iso(at), "expected_min": None}
            board["agents"].append(agent)
        elif agent is None:
            raise SystemExit(f"状態の表に無い: {args.name}（board add で追加する）")
        keys = {p.split("+=", 1)[0].split("=", 1)[0] for p in args.pairs}
        previous_task = agent.get("current_task")
        apply_pairs(agent, args.pairs, at, FORBIDDEN_KEYS["agent"])
        # 振り出し（current_taskの指定）で着手時刻を入れる。差し戻しで同じタスクのまま再開したときは変えない。
        task = agent.get("current_task")
        if "current_task" in keys and task and task != previous_task:
            start_task(agent, str(task), at)
            if (ledger_rows(ctx).get(str(task)) or {}).get("scale") is None:
                print(f"注: {task}は台帳に規模札のある行が無い。見込み超過をタスク単位で測れない")
        if agent.get("state") == "稼働":
            restore_hooks_path(ctx)
        urgent = bool(agent.pop("urgent", False))
        passed = "audit_done" in keys and agent.get("audit_result") == "通す"
        if "audit_done" in keys:
            # 監査の待ち時間（受領→結果）を回の記録で測るため、1件ごとに残す。
            entry = {k: agent.get(k) for k in (
                "reported_sha", "audit_base", "reported", "audit_started", "audit_done",
                "audit_result", "audit_blocked", "audit_errors")}
            entry["urgent"] = urgent
            agent.setdefault("audit_log", []).append(entry)
            if agent.get("audit_result") == "通す":
                # 監査を通ったタスクは表から外す（所要の実績は完了のコミットでTxxx.mdにある）。
                agent["current_task"] = None
                agent["task_first_started"] = None
        save_board(ctx, board)
        print(json.dumps(agent, ensure_ascii=False, indent=1))
        # 差し戻しでは同じ担当が同じスロットで再開するので、印は監査を通すまで外さない。
        if passed and agent.get("state") in STOPPED_STATES:
            release_slot(ctx, agent)
        return 0
    if args.board_cmd == "unpushed":
        return cmd_unpushed(ctx, board, at)
    if args.board_cmd == "run":
        if not args.pairs or args.pairs[0] in RUN_OPS:
            return cmd_run(ctx, board, args.pairs or ["list"], at)
        if isinstance(board.get("run"), str):
            board["run"] = run_of(board)
        apply_pairs(board, args.pairs, at, FORBIDDEN_KEYS["top"])
        save_board(ctx, board)
        print(json.dumps({k: v for k, v in board.items() if k not in ("agents", "run")}, ensure_ascii=False, indent=1))
        return 0
    if args.board_cmd == "claim":
        # セッションの識別子は道具の側からは見えない。直後のPostToolUseのフック（check --if-due）が、
        # この呼び出しのコマンド文字列を見て、自分のsession_idを司令塔として記録する。
        print("このセッションを司令塔として記録する（直後のフックが記録し、文脈へ知らせる）")
        return 0
    if args.board_cmd == "show":
        print(json.dumps(board, ensure_ascii=False, indent=1))
        return 0
    # todo / dispatch: 優先順位の小さい順、同じなら積んだ順に取り出す。
    dispatch = args.board_cmd == "dispatch"
    key = "queue" if dispatch else "coordinator_queue"
    items: list[dict] = board.setdefault(key, [])
    order = sorted(range(len(items)), key=lambda i: (items[i].get("priority", 99), items[i].get("added", ""), i))
    if args.op == "push":
        if dispatch:
            if not re.fullmatch(TASK_ID_RE, args.text):
                raise SystemExit(f"振り出し待ちにはタスク番号を積む（題名は台帳から導く）: {args.text}")
            item = {"task": args.text, "priority": args.priority, "added": iso(at)}
            apply_pairs(item, args.pairs, at, FORBIDDEN_KEYS["queue"])
        else:
            item = {"what": args.text, "priority": args.priority, "added": iso(at)}
            apply_pairs(item, args.pairs, at)
        items.append(item)
        save_board(ctx, board)
        print(f"積んだ（{len(items)}件目）: {json.dumps(item, ensure_ascii=False)}")
        return 0
    # 振り出し待ちは、前提（after）がorigin/masterで完了したものだけが取り出せる。
    done = done_tasks(ctx, sorted({t for i in items for t in prereqs_of_item(i)})) if dispatch else set()
    ready = [i for i in order if all(t in done for t in prereqs_of_item(items[i]))]
    if args.op == "pop":
        candidates = ready if dispatch else order
        if not candidates:
            print("キューは空" if not items else "前提が済んだものが無い（board dispatch list で前提を見る）")
            return 1
        index = candidates[0] if args.index is None else order[args.index - 1]
        item = items.pop(index)
        save_board(ctx, board)
        print(f"取り出した: {json.dumps(item, ensure_ascii=False)}")
        return 0
    if not items:
        print("キューは空")
    rows = ledger_rows(ctx) if dispatch else {}
    for n, i in enumerate(order, 1):
        item = items[i]
        if dispatch:
            waiting = [t for t in prereqs_of_item(item) if t not in done]
            mark = "  前提待ち: " + "・".join(waiting) if waiting else "  前提: 済"
            task = str(item.get("task"))
            rest = {k: v for k, v in item.items() if k not in ("task", "priority", "added", "after")}
            print(f"{n}. [{item.get('priority', '-')}] {task}: {task_title(ctx, task, rows)}"
                  f"  （{hm(parse_time(item.get('added')))}）{mark}"
                  f"{'  ' + json.dumps(rest, ensure_ascii=False) if rest else ''}")
        else:
            rest = {k: v for k, v in item.items() if k not in ("what", "priority", "added")}
            print(f"{n}. [{item.get('priority', '-')}] {item.get('what')}  （{hm(parse_time(item.get('added')))}）"
                  f"{'  ' + json.dumps(rest, ensure_ascii=False) if rest else ''}")
    return 0


def cmd_run(ctx: Context, board: dict, words: list[str], at: dt.datetime) -> int:
    """回の目的と母集団: start <名前> / goal <文> / add <Txxx>... [from=<Tyyy>] / remove <Txxx>... / list。"""
    op, rest = words[0], words[1:]
    if op == "list":
        for line in run_summary_lines(population_view(ctx, board, ledger_rows(ctx)), detail=True):
            print(line)
        return 0
    run = run_of(board)
    if op in ("start", "goal"):
        if not rest:
            raise SystemExit(f"board run {op} の後に{'回の名前' if op == 'start' else '目的の文'}を書く")
        if op == "start":
            if run:
                print("前の回（置き換える）: " + json.dumps(run, ensure_ascii=False))
            run = {"name": " ".join(rest), "started": iso(at), "goal": None, "population": []}
        else:
            run["goal"] = " ".join(rest)
    else:
        origin = None
        tasks = []
        for word in rest:
            if word.startswith("from="):
                origin = word[len("from="):] or None
            elif re.fullmatch(TASK_ID_RE, word):
                tasks.append(word)
            else:
                raise SystemExit(f"タスク番号か from=<Txxx> を書く（題名・状態は台帳と記録から導く）: {word}")
        if origin is not None and not re.fullmatch(TASK_ID_RE, origin):
            raise SystemExit(f"派生元はタスク番号で書く: {origin}")
        if not tasks:
            raise SystemExit(f"board run {op} の後にタスク番号を書く")
        population = run.setdefault("population", [])
        present = {str(i.get("task")) for i in population}
        if op == "add":
            if origin is None:
                print("注: 派生元（from=<Txxx>）が無い。回の始めに決めた母集団なら無くてよい")
            for task in tasks:
                if task in present:
                    raise SystemExit(f"既に母集団にある: {task}（派生元を直すなら remove してから add）")
                item = {"task": task, "added": iso(at)}
                if origin:
                    item["from"] = origin
                population.append(item)
        else:
            missing = [t for t in tasks if t not in present]
            if missing:
                raise SystemExit(f"母集団に無い: {'・'.join(missing)}")
            run["population"] = [i for i in population if str(i.get("task")) not in tasks]
    board["run"] = run
    save_board(ctx, board)
    for line in run_summary_lines(population_view(ctx, board, ledger_rows(ctx)), detail=True):
        print(line)
    return 0


def push_due(ctx: Context, items: list[dict], at: dt.datetime) -> str | None:
    """監査を通して溜めたコミットをmasterへpushする時期か。時期ならその理由。"""
    if not items:
        return None
    if any(i.get("urgent") for i in items):
        return "即時の修正（セキュリティ・利用者に届いている欠陥）がある"
    if len(items) >= PUSH_BATCH_SIZE:
        return f"{len(items)}件溜まった"
    since = master_tip_time(ctx)
    if since and at - since >= dt.timedelta(minutes=PUSH_INTERVAL_MINUTES):
        return f"前回のpushから{minutes(at - since)}分"
    return None


def push_due_line(ctx: Context, items: list[dict], at: dt.datetime) -> str:
    reason = push_due(ctx, items, at)
    return f"監査済み・未push {len(items)}件: " + (f"push時期（{reason}）" if reason else "まだ溜める")


def cmd_unpushed(ctx: Context, board: dict, at: dt.datetime) -> int:
    items = audited_unpushed(ctx, board, at)
    print(push_due_line(ctx, items, at))
    for i in items:
        rng = f"{i.get('base')}..{i.get('sha')}" if i.get("base") else str(i.get("sha"))
        print(f"  {i.get('agent')}: {rng}  監査{hm(parse_time(i.get('audited')))}{'  即時' if i.get('urgent') else ''}")
    if items:
        # 範囲ごとに分けて取り込む（1回のcherry-pickへ並べると、範囲の和として解釈される）。
        picks = " && ".join(f"git cherry-pick {i['base']}..{i['sha']}" if i.get("base")
                            else f"git cherry-pick {i.get('sha')}" for i in items)
        efforts = " && ".join(f"python scripts/orchestrate.py effort-ci {i.get('agent')} {i.get('sha')}"
                              + (f" --base {i['base']}" if i.get("base") else "") for i in items)
        print("\n1回でpushする手順（司令塔の作業ツリーで。枠で包まない。衝突したら中止して担当へ差し戻す）:")
        print(f"  git fetch origin master && git switch -C land origin/master"
              f" && {picks} && {efforts} && python scripts/orchestrate.py ledger close"
              f" && git push origin \"$(git rev-parse HEAD)\":refs/heads/master")
        print("  （effort-ci は、担当の所要の行へ完了のコミットのCIを書き足すコミットを足す。書き足せなければ飛ばす）")
        print("  （ledger close は、取り込んだ記録で状態が完了のタスクの台帳の行を消すコミットを足す。"
              "担当は台帳の行を消さない）")
        print("  （masterに入ったかは git から導くので、pushの後に表を書き換える手順は無い）")
    return 0


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description="並行実行（司令塔）の門・状態・定期確認・監査")
    parser.add_argument("--repo", default=str(REPO_ROOT), help="調べるgitリポジトリ（既定: このスクリプトのリポジトリ）")
    parser.add_argument("--dir", default=os.environ.get("ORCH_DIR"),
                        help="orchestrationディレクトリ（既定: <gitの共通ディレクトリ>/orchestration）")
    parser.add_argument("--active-min", type=int, default=ACTIVE_MINUTES,
                        help="作業ツリーの変更がこの分数以内なら手元で動いていると数える")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("gate", help="振り出してよいか")
    p.add_argument("--concurrent", type=int, help="上限（既定: 状態の表のlimits.concurrent、無ければ3）")
    p.add_argument("--cpu-max", type=float, default=CPU_SATURATED_PERCENT, help="飽和とみなすCPU使用率")
    p = sub.add_parser("status", help="状態の表と事実の突き合わせ")
    p.add_argument("target", nargs="?", help="エージェント名またはTxxx")
    p = sub.add_parser("check", help="定期確認（異常だけを出す）")
    p.add_argument("--concurrent", type=int)
    p.add_argument("--cpu-max", type=float, default=CPU_SATURATED_PERCENT)
    p.add_argument("--stale-min", type=int, default=STALE_COMMIT_MINUTES)
    p.add_argument("--audit-wait-min", type=int, default=AUDIT_WAIT_MINUTES)
    p.add_argument("--record", action="store_true", help="状態の表のlast_checkを更新する")
    p.add_argument("--if-due", action="store_true",
                   help="フック用: 司令塔のセッションで確認間隔を過ぎたときだけ走らせ、結果を文脈へ返す")
    p = sub.add_parser("audit", help="監査のうち機械で見られる項目")
    p.add_argument("name")
    p.add_argument("sha")
    p.add_argument("--base", help="比較の基点（既定: origin/master。分岐点を取る）")
    p.add_argument("--no-ci", action="store_true", help="CIの結論を読まない")

    p = sub.add_parser("board", help="状態の表の更新")
    bsub = p.add_subparsers(dest="board_cmd", required=True)
    for name in ("set", "add"):
        q = bsub.add_parser(name)
        q.add_argument("name")
        q.add_argument("pairs", nargs="*")
    q = bsub.add_parser("run", help="回の値（k=v）と、回の目的・母集団（start・goal・add・remove・list）")
    q.add_argument("pairs", nargs="*")
    bsub.add_parser("show")
    bsub.add_parser("claim", help="このセッションを司令塔として記録する（直後のフックが記録する）")
    for name, help_text in (("todo", "司令塔のキュー（中断・待ちの作業）"), ("dispatch", "振り出し待ちのキュー")):
        q = bsub.add_parser(name, help=help_text)
        ops = q.add_subparsers(dest="op", required=True)
        r = ops.add_parser("push")
        r.add_argument("text", help="todo は作業の文、dispatch はタスク番号（題名・規模は台帳から導く）")
        r.add_argument("--priority", type=int, default=7, help="規約「司令塔の作業の優先順位」の順位（1が最優先）")
        r.add_argument("pairs", nargs="*")
        r = ops.add_parser("pop")
        r.add_argument("index", nargs="?", type=int, help="listの番号（既定: 先頭）")
        ops.add_parser("list")
    bsub.add_parser("unpushed", help="監査を通したコミットのうちmasterに入っていないもの（gitから導く）")

    args = parser.parse_args(argv)
    if args.cmd == "check" and args.if_due:
        return check_if_due(args)
    ctx = Context(Path(args.repo), args.dir)
    handler = {"gate": cmd_gate, "status": cmd_status, "check": cmd_check,
               "audit": cmd_audit, "board": cmd_board}[args.cmd]
    return handler(ctx, args)


if __name__ == "__main__":
    sys.exit(main())
