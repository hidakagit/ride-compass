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
    python scripts/orchestrate.py audit <名前> <sha> [--checks-in <検査用の作業ツリー>]
                                                              # 監査のうち機械で見られる項目＋CIの結論＋pre-pushと同じ静的検査
    python scripts/orchestrate.py board set <名前> k=v ...    # エージェントの行を更新
    python scripts/orchestrate.py board add <名前> k=v ...    # エージェントの行を追加
    python scripts/orchestrate.py board run k=v ...           # 回の値（limits.concurrent等）を更新
    python scripts/orchestrate.py board todo push|pop|list    # 司令塔のキュー（中断・待ちの作業）
    python scripts/orchestrate.py board dispatch push|pop|list  # 振り出し待ちのキュー
    python scripts/orchestrate.py board unpushed add|done|list  # 監査済み・未pushのコミット

`board set <名前> audit_done=now audit_result=通す`は、監査の記録（audit_log）を1件残し、
`reported_sha`を監査済み・未pushへ積む。

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
import os
import re
import shutil
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
TASKS_DIR = "docs/records/tasks"
PLAN_ENTRY_RE = re.compile(r"^- \[[ x]\] \[(T\d+[a-z0-9-]*)\]\(")
TASK_ID_RE = re.compile(r"T\d+[a-z0-9-]*")
TASK_DOC_RE = re.compile(r"^docs/records/tasks/(T\d+[a-z0-9-]*)\.md$")

#: 状態の表の`state`の語彙。
ACTIVE_STATES = ("稼働", "停止指示")
STOPPED_STATES = ("停止済み", "強制停止")
AUDIT_WAIT_STATES = ("完了・監査待ち", "監査待ち")
DONE_STATES = ("監査済み",)
STATES = ACTIVE_STATES + STOPPED_STATES + AUDIT_WAIT_STATES + DONE_STATES

DEFAULT_CONCURRENT = 3
#: 規模札（CLAUDE.md「規模の目安」）の予算。
SCALE_BUDGET_MINUTES = {"S": 60, "M": 240, "L": 480}
#: 作業ツリーの未コミット変更がこの時間内に更新されていれば「手元で動いている」と数える。
ACTIVE_MINUTES = 15
STALE_COMMIT_MINUTES = 30
AUDIT_WAIT_MINUTES = 30
LOCK_WINDOW_MINUTES = 30
LOCK_WAIT_LIMIT_MINUTES = 10
CPU_SATURATED_PERCENT = 90
CPU_SAMPLE_SECONDS = 2.0
GIT_TIMEOUT_SECONDS = 60
#: 監査を通したコミットは溜めてmasterへ1回でpushする（pre-pushの門を払う回数を減らす）。
PUSH_BATCH_SIZE = 2
PUSH_INTERVAL_MINUTES = 60
UNPUSHED_KEY = "audited_unpushed"
LAST_PUSH_KEY = "last_master_push"
LAST_PUSH_AT_KEY = "last_master_push_at"
EXPECTED_HOOKS_PATH = ".githooks"
#: どの作業ツリーにも自動で作られる設定。作業の進みを表さない。
IGNORED_CHANGES = (".claude/settings.local.json",)

#: 監査の同期ルール（CLAUDE.md「コミット時の同期ルール」）で、生成物の再生成を要する宣言の場所。
#: .githooks/pre-pushが再生成を走らせる条件と同じ。
API_DECL_RE = re.compile(r"^backend/(app/(api|domain)/|app/config\.py|scripts/export_openapi\.py)")
GENERATED_PREFIX = "frontend/src/types/generated/"
#: pre-pushの門が書式を確かめる対象と同じ。
PRETTIER_TARGET_RE = re.compile(r"^frontend/src/.*\.(ts|tsx|css)$")
PRETTIER_BIN = "frontend/node_modules/prettier/bin/prettier.cjs"
#: 変更ファイルを一時ディレクトリで検査するときに、報告のコミットから一緒に書き出す設定。
TOOL_CONFIGS = ("backend/ruff.toml", "frontend/.prettierrc.json", "frontend/.prettierignore")
STATIC_CHECK_TIMEOUT = 600
#: 使い捨ての成果物が紛れ込みやすい形。混入の候補であって判定ではない。
SCRATCH_RE = re.compile(r"(^|/)(scratch|tmp|temp)(/|$)|\.(log|png|jpe?g|webm|zip)$|(^|/)\.git-pre-push-", re.IGNORECASE)
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


def ready_to_dispatch(ctx: Context, items: list[dict]) -> list[dict]:
    """振り出し待ちのうち、前提（`after`のTxxx）がorigin/masterで完了しているもの。"""
    deps = sorted({str(i["after"]) for i in items if i.get("after")})
    texts = cat_files(ctx.repo, [f"origin/master:{TASKS_DIR}/{t}.md" for t in deps])
    done = {t for t in deps if task_state(texts[f"origin/master:{TASKS_DIR}/{t}.md"]) == "完了"}
    return [i for i in items if not i.get("after") or str(i["after"]) in done]


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


def queue_tasks(agent: dict) -> list[str]:
    """担当キューの各項目の先頭のタスク番号（項目の注記に出る番号は担当ではない）。"""
    out = []
    for item in agent.get("queue") or []:
        m = TASK_ID_RE.search(str(item))
        if m and m.group(0) not in out:
            out.append(m.group(0))
    return out


def budget_of(agent: dict) -> int | None:
    """タスクの規模札の予算（分）。再開しても変わらない、最初の振り出しからの通算と比べる。"""
    value = agent.get("scale_budget_min")
    if isinstance(value, (int, float)):
        return int(value)
    return SCALE_BUDGET_MINUTES.get(str(agent.get("scale", "")))


def audit_pending(agent: dict) -> bool:
    if agent.get("state") in AUDIT_WAIT_STATES:
        return True
    reported, done = parse_time(agent.get("reported")), parse_time(agent.get("audit_done"))
    return reported is not None and (done is None or done < reported)


# ---------------------------------------------------------------- 事実の収集


class Worktree:
    def __init__(self, path: str, head: str | None, branch: str | None, main: bool):
        self.path, self.head, self.branch, self.main = path, head, branch, main
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
                                  branch, main=not trees))
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


def worktree_of(agent: dict, trees: list[Worktree]) -> Worktree | None:
    explicit = agent.get("worktree")
    if explicit:
        target = os.path.normcase(os.path.normpath(str(explicit)))
        return next((t for t in trees if os.path.normcase(t.path) == target
                     or os.path.basename(t.path) == explicit), None)
    agent_id, name = agent.get("id"), str(agent.get("name", "")).lower()
    if agent_id:
        found = next((t for t in trees if os.path.basename(t.path) == f"agent-{agent_id}"), None)
        if found:
            return found
    return next((t for t in trees if not t.main and t.branch in (name, f"orch/{name}")), None)


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
            if a.get("state") not in ACTIVE_STATES:
                continue
            first, budget = parse_time(a.get("task_first_started")), budget_of(a)
            if first and budget is not None:
                total = minutes(self.at - first)
                if total > budget:
                    out.append(f"{a.get('name')}: 最初の振り出しから通算{total}分 / 規模の予算{budget}分")
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
    for task in queue_tasks(a):
        st, in_ledger = states.get(task), task in listed
        if st is None:
            marks.append(f"! {task}: origin/masterにタスク記録が無い")
        elif st == "完了" and in_ledger:
            marks.append(f"! {task}: 完了なのに台帳に行がある")
        elif st == "未完了" and not in_ledger:
            marks.append(f"! {task}: 未完了なのに台帳に行が無い")
        elif st == "未完了" and state in DONE_STATES:
            marks.append(f"? {task}: 監査済みだが未完了（保留か残りの段階か）")
    return marks


def cmd_status(ctx: Context, args: argparse.Namespace) -> int:
    f = Facts(ctx, args, cpu=False)
    agents = f.board["agents"]
    if args.target:
        key = args.target.lower()
        agents = [a for a in agents if str(a.get("name", "")).lower() == key
                  or args.target in queue_tasks(a)]
        if not agents:
            print(f"該当するエージェントがありません: {args.target}")
            return 1
    tasks = sorted({t for a in agents for t in queue_tasks(a)})
    specs = [f"origin/master:{TASKS_DIR}/{t}.md" for t in tasks] + [f"origin/master:{PLAN_DOC}"]
    blobs = cat_files(ctx.repo, specs)
    states = {t: task_state(blobs[f"origin/master:{TASKS_DIR}/{t}.md"]) for t in tasks}
    listed = ledger_ids(blobs[f"origin/master:{PLAN_DOC}"])
    master = git_out(ctx.repo, "log", "-1", "--format=%h %ct", "origin/master") or ""
    master_sha, _, master_ts = master.partition(" ")

    b = f.board
    print(f"回: {b.get('run', '-')}  上限{f.limit}本  最終確認 {hm(parse_time(b.get('last_check')))}"
          f"  origin/master {master_sha}"
          f"（{hm(dt.datetime.fromtimestamp(int(master_ts)).astimezone()) if master_ts else '-'}。fetchはしない）")
    print(f"稼働（手元）{len(f.active())}本  監査待ち{len(f.audit_waiting())}本"
          f"  停止ファイル{'あり' if f.stop else 'なし'}  core.hooksPath={f.hooks_path}")
    for a in agents:
        state = a.get("state", "-")
        start, expected = parse_time(a.get("started")), a.get("expected_min")
        progress = ""
        if state in ACTIVE_STATES and start:
            progress = f"  経過{minutes(f.at - start)}分/見込み{expected if expected is not None else '-'}分"
            first = parse_time(a.get("task_first_started"))
            if first:
                progress += f"  通算{minutes(f.at - first)}分/予算{budget_of(a) or '-'}分"
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
        for task in queue_tasks(a):
            print(f"  {task}: master上の状態={states.get(task) or '記録なし'}"
                  f"  台帳={'あり' if task in listed else 'なし'}")
        for mark in agent_marks(f, a, states, listed):
            print(f"  {mark}")
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
    if push_due(f.board, f.at):
        problems.append(f"要対応: {push_due_line(f.board, f.at)}（board unpushed list）")
    if f.board.get("push_blocked"):
        problems.append(f"masterへのpushが止まっている: {f.board['push_blocked']}")
    # 門がNGで見送った振り出しは、門が開いた最初の確認で拾う（「落ち着いたら」を人の注意に頼らない）。
    waiting_dispatch = ready_to_dispatch(ctx, f.board.get("queue") or [])
    if waiting_dispatch and not gate_reasons(f, args):
        problems.append(f"要対応: 振り出し待ち{len(waiting_dispatch)}件があり、門が開いている"
                        f"（例: {waiting_dispatch[0].get('what')}。board dispatch pop で取り出して振り出す）")

    cpu = "未取得" if f.cpu is None else f"{f.cpu:.0f}%"
    if problems:
        print(f"異常 {len(problems)}件（{hm(f.at)}、稼働{len(active)}本/上限{f.limit}本、CPU {cpu}）")
        for p in problems:
            print(f"  - {p}")
    else:
        print(f"異常なし（{hm(f.at)}、稼働{len(active)}本/上限{f.limit}本、"
              f"監査待ち{len(f.audit_waiting())}本、CPU {cpu}）")
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
    queue = queue_tasks(agent) if agent else []
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
            print(f"  ? キュー外のタスク記録を触っている: {task}（起票なら問題ない）")

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
        if st == "完了" and row:
            flag(line + " → 完了なのに台帳に行がある")
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
    if args.no_ci:
        print("  （--no-ci により未取得）")
    else:
        for text, bad in ci_verdicts(sha):
            if bad:
                flag(text)
            else:
                print(f"  {text}")

    # 静的検査（pre-pushの門と同じもの）。masterへまとめてpushする時に初めて門で落ちると、
    # まとめた全体が止まるため、監査の時点で同じ検査を通す。
    live = [p for s, p in changes if s != "D"]
    print("\n静的検査（pre-pushの門と同じ。変更ファイルへのruff・prettier、docs検査、OpenAPI生成物のずれ）")
    if args.no_checks:
        print("  （--no-checks により未実行）")
    else:
        for name, ok, detail in static_checks(ctx, args, sha, agent, live):
            if ok:
                print(f"  {name}: 通過{('（' + detail + '）') if detail else ''}")
            elif ok is None:
                print(f"  {name}: 対象なし")
            else:
                flag(f"{name}: {detail}")

    backend = any(p.startswith("backend/") for p in files)
    print("\n未判定（司令塔が判断する）:")
    print("  3. 完了条件 — Txxx.mdの完了条件の各項目に、何で確かめたかが書かれているか")
    print("  5. 主張の抜き取り検証 — 結論が最も強く依存する主張を1つ自分で確かめる")
    print(f"  6. 本番への影響 — backend/**を{'含む。DB行の互換・マイグレーション・本番操作の記述を確かめる' if backend else '含まない'}")
    print("  8. 報告の正確さ・9. 見積もりとのずれ — 記録")
    print(f"\n機械で見た項目の指摘 {flags}件")
    print(f"通すなら: python scripts/orchestrate.py board set {args.name} reported_sha={sha[:12]} "
          f"audit_base={base[:12]} audit_done=now audit_result=通す [urgent=true]")
    return 1 if flags else 0


def ci_verdicts(sha: str) -> list[tuple[str, bool]]:
    """`sha`に対するワークフローごとの最新の結論。2つめの値は、監査を通せない（失敗・結論待ち・
    取得できない・実行が無い）ことを表す。"""
    from check_master_ci import RUNS_API, fetch_runs, is_failure, latest_per_workflow

    runs = fetch_runs(f"{RUNS_API}?head_sha={sha}&per_page=30")
    if runs is None:
        return [("CIの結論を取得できない（GitHub APIに届かない・未認証の上限超過等）", True)]
    latest = sorted(latest_per_workflow(runs, sha), key=lambda r: str(r.get("name")))
    if not latest:
        return [("このコミットに対するCIの実行が無い（orch/<名前>へpushしていないか、pushした先端のコミットではない）", True)]
    verdicts = []
    for run in latest:
        done = run.get("status") == "completed"
        state = run.get("conclusion") if done else f"結論待ち（{run.get('status')}）"
        verdicts.append((f"{run.get('name')}: {state}  {run.get('html_url', '')}", is_failure(run) or not done))
    return verdicts


def find_venv_python(place: Path, ctx: Context) -> str | None:
    """backend/.venvは作業ツリーへ複製されないため、本体のチェックアウトの側へ落ちる。"""
    for root in (place, ctx.common.parent):
        for rel in ("backend/.venv/Scripts/python.exe", "backend/.venv/bin/python"):
            if (root / rel).exists():
                return str(root / rel)
    return None


def run_tool(cmd: list[str], cwd: Path) -> tuple[bool, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", GIT_OPTIONAL_LOCKS="0")
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, env=env, timeout=STATIC_CHECK_TIMEOUT, check=False)
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, f"実行できない（{e.__class__.__name__}）"
    out = (r.stdout + r.stderr).decode("utf-8", errors="replace").strip().splitlines()
    return r.returncode == 0, "\n      ".join(out[-12:])


def checks_place(ctx: Context, args: argparse.Namespace, sha: str, agent: dict | None) -> tuple[Path | None, str]:
    """検査を走らせる作業ツリー。指定があればそこへshaを取り出し、無ければ担当の作業ツリーが
    ちょうどshaで変更なしのときだけ使う（検査は手元のファイルを読むため）。"""
    if args.checks_in:
        place = Path(args.checks_in)
        common = git_out(place, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if common is None or os.path.normcase(common) != os.path.normcase(str(ctx.common)):
            return None, f"{place} は同じリポジトリの作業ツリーではない"
        tree = Worktree(str(place), None, None, main=False)
        inspect_changes(tree)
        if tree.dirty:
            return None, f"{place} に未コミットの変更がある（検査用の作業ツリーは変更なしで使う）"
        r = git(place, "checkout", "--detach", "--quiet", sha)
        if r is None or r.returncode != 0:
            return None, f"{place} へ {sha[:8]} を取り出せない"
        return place, f"{place}（{sha[:8]}を取り出した）"
    if agent is not None:
        tree = worktree_of(agent, list_worktrees(ctx))
        if tree is not None and tree.exists and tree.head == sha:
            inspect_changes(tree)
            if tree.dirty == 0:
                return Path(tree.path), f"担当の作業ツリー {tree.label}"
    return None, "担当の作業ツリーが報告のshaのまま変更なし、になっていない（--checks-in <検査用の作業ツリー>で走らせる）"


def blob_checks(ctx: Context, sha: str, live: list[str], roots: list[Path]) -> list[tuple[str, bool | None, str]]:
    """ruffとprettierを、報告のコミットの中身（blob）へ当てる。変更ファイルと設定ファイルだけを
    一時ディレクトリへ同じパスで書き出して1回ずつ走らせるため、作業ツリーへの取り出しが要らず、
    担当の作業ツリーが先へ進んでいても、道具（venv・node_modules）のある場所ならどこでも走る。"""
    results: list[tuple[str, bool | None, str]] = []
    py_files = [p for p in live if p.startswith("backend/") and p.endswith(".py")]
    fe_files = [p for p in live if PRETTIER_TARGET_RE.match(p)]
    if not py_files:
        results.append(("ruff", None, ""))
    if not fe_files:
        results.append(("prettier", None, ""))
    if not py_files and not fe_files:
        return results
    wanted = py_files + fe_files + list(TOOL_CONFIGS)
    blobs = cat_files(ctx.repo, [f"{sha}:{p}" for p in wanted])
    with tempfile.TemporaryDirectory(prefix="orch-audit-") as tmp:
        for p in wanted:
            if blobs[f"{sha}:{p}"] is not None:
                target = Path(tmp, p)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blobs[f"{sha}:{p}"].encode("utf-8"))

        python = next((p for r in roots if (p := find_venv_python(r, ctx))), None)
        if py_files and python is None:
            results.append(("ruff", False, "未実行: backend/.venv が見つからない"))
        elif py_files:
            ok, out = run_tool([python, "-m", "ruff", "check", *py_files], Path(tmp))
            results.append(("ruff", ok, f"{len(py_files)}件" if ok else out))

        root = next((r for r in roots if (r / PRETTIER_BIN).exists()), None)
        if fe_files and root is None:
            results.append(("prettier", False, "未実行: frontend/node_modules のある作業ツリーが見つからない"))
        elif fe_files:
            ok, out = run_tool(["node", str(root / PRETTIER_BIN), "--check", "--log-level", "warn",
                                *[p.removeprefix("frontend/") for p in fe_files]], Path(tmp, "frontend"))
            results.append(("prettier", ok, f"{len(fe_files)}件" if ok else out))
    return results


def static_checks(ctx: Context, args: argparse.Namespace, sha: str, agent: dict | None,
                  live: list[str]) -> list[tuple[str, bool | None, str]]:
    place, where = checks_place(ctx, args, sha, agent)
    roots = [r for r in (place, ctx.repo, ctx.common.parent) if r is not None]
    results = blob_checks(ctx, sha, live, roots)
    if place is None:
        results.append(("docs検査・OpenAPI生成物", False, f"未実行: {where}"))
        return results
    print(f"  取り出した場所: {where}")
    python = find_venv_python(place, ctx)

    ok, out = run_tool([python or sys.executable, "scripts/review_checks.py", "docs"], place)
    results.append(("docs検査", ok, "" if ok else out))

    if not any(API_DECL_RE.match(p) for p in live):
        results.append(("OpenAPI生成物", None, ""))
    elif not args.checks_in:
        results.append(("OpenAPI生成物", False, "未実行: 再生成は作業ツリーを書き換えるため、--checks-in の検査用の作業ツリーでだけ走らせる"))
    elif python is None or not (place / "frontend/node_modules").exists():
        results.append(("OpenAPI生成物", False, "未実行: backend/.venv か frontend/node_modules が無い"))
    else:
        npm = shutil.which("npm") or "npm"
        run_tool([python, "backend/scripts/export_openapi.py"], place)
        run_tool([npm, "run", "--silent", "generate:api"], place / "frontend")
        drift = git(place, "diff", "--quiet", "--", GENERATED_PREFIX)
        ok = drift is not None and drift.returncode == 0
        if not ok:
            # 検査用の作業ツリーで自分が再生成した差分なので、次の監査のために戻す。
            git(place, "checkout", "--", GENERATED_PREFIX)
        results.append(("OpenAPI生成物", ok, "" if ok else "再生成すると差分が出る（生成物をコミットしていない）"))
    return results


# ---------------------------------------------------------------- board


def parse_value(raw: str, at: dt.datetime) -> object:
    if raw == "now":
        return iso(at)
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def apply_pairs(target: dict, pairs: list[str], at: dt.datetime) -> None:
    for pair in pairs:
        append = "+=" in pair and pair.index("+=") < pair.index("=") + 1
        key, _, raw = pair.partition("+=" if append else "=")
        if not key or ("=" not in pair):
            raise SystemExit(f"k=v の形ではありません: {pair}")
        value = parse_value(raw, at)
        if key == "state" and value not in STATES:
            raise SystemExit(f"状態の語彙に無い: {value}（使えるのは {'・'.join(STATES)}）")
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
            # task_first_startedは再開しても上書きしない（見込み超過を通算で見るため）。
            agent = {"name": args.name, "queue": [], "where": "local", "state": "稼働",
                     "started": iso(at), "task_first_started": iso(at), "expected_min": None}
            board["agents"].append(agent)
        elif agent is None:
            raise SystemExit(f"状態の表に無い: {args.name}（board add で追加する）")
        apply_pairs(agent, args.pairs, at)
        if agent.get("state") == "稼働":
            restore_hooks_path(ctx)
        urgent = bool(agent.pop("urgent", False))
        if any(p.split("=", 1)[0] == "audit_done" for p in args.pairs):
            # 監査の待ち時間（受領→結果）を回の記録で測るため、1件ごとに残す。
            agent.setdefault("audit_log", []).append({k: agent.get(k) for k in (
                "reported_sha", "audit_base", "reported", "audit_started", "audit_done",
                "audit_result", "audit_blocked", "audit_errors")})
            if agent.get("audit_result") == "通す" and agent.get("reported_sha"):
                board.setdefault(UNPUSHED_KEY, []).append({
                    "agent": agent.get("name"), "sha": agent.get("reported_sha"),
                    "base": agent.get("audit_base"), "audited": agent.get("audit_done"), "urgent": urgent})
        save_board(ctx, board)
        print(json.dumps(agent, ensure_ascii=False, indent=1))
        if board.get(UNPUSHED_KEY):
            print(push_due_line(board, at))
        return 0
    if args.board_cmd == "unpushed":
        return cmd_unpushed(ctx, board, args, at)
    if args.board_cmd == "run":
        apply_pairs(board, args.pairs, at)
        save_board(ctx, board)
        print(json.dumps({k: v for k, v in board.items() if k != "agents"}, ensure_ascii=False, indent=1))
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
    key = "coordinator_queue" if args.board_cmd == "todo" else "queue"
    items: list[dict] = board.setdefault(key, [])
    order = sorted(range(len(items)), key=lambda i: (items[i].get("priority", 99), items[i].get("added", ""), i))
    if args.op == "push":
        item = {"what": args.text, "priority": args.priority, "added": iso(at)}
        apply_pairs(item, args.pairs, at)
        items.append(item)
        save_board(ctx, board)
        print(f"積んだ（{len(items)}件目）: {json.dumps(item, ensure_ascii=False)}")
        return 0
    if args.op == "pop":
        if not items:
            print("キューは空")
            return 1
        index = order[0] if args.index is None else order[args.index - 1]
        item = items.pop(index)
        save_board(ctx, board)
        print(f"取り出した: {json.dumps(item, ensure_ascii=False)}")
        return 0
    if not items:
        print("キューは空")
    for n, i in enumerate(order, 1):
        item = items[i]
        rest = {k: v for k, v in item.items() if k not in ("what", "priority", "added")}
        print(f"{n}. [{item.get('priority', '-')}] {item.get('what')}  （{hm(parse_time(item.get('added')))}）"
              f"{'  ' + json.dumps(rest, ensure_ascii=False) if rest else ''}")
    return 0


def push_due(board: dict, at: dt.datetime) -> str | None:
    """監査を通して溜めたコミットをmasterへpushする時期か。時期ならその理由。"""
    items = board.get(UNPUSHED_KEY) or []
    if not items:
        return None
    if any(i.get("urgent") for i in items):
        return "即時の修正（セキュリティ・利用者に届いている欠陥）がある"
    if len(items) >= PUSH_BATCH_SIZE:
        return f"{len(items)}件溜まった"
    since = parse_time(board.get(LAST_PUSH_AT_KEY)) or min(
        (t for i in items if (t := parse_time(i.get("audited")))), default=None)
    if since and at - since >= dt.timedelta(minutes=PUSH_INTERVAL_MINUTES):
        return f"前回のpushから{minutes(at - since)}分"
    return None


def push_due_line(board: dict, at: dt.datetime) -> str:
    n = len(board.get(UNPUSHED_KEY) or [])
    reason = push_due(board, at)
    return f"監査済み・未push {n}件: " + (f"push時期（{reason}）" if reason else "まだ溜める")


def cmd_unpushed(ctx: Context, board: dict, args: argparse.Namespace, at: dt.datetime) -> int:
    items: list[dict] = board.setdefault(UNPUSHED_KEY, [])
    if args.op == "add":
        items.append({"agent": args.agent, "sha": args.sha, "base": args.base,
                      "audited": iso(at), "urgent": args.urgent})
        save_board(ctx, board)
    elif args.op == "done":
        # masterへ届いたものを外し、次の「前回から」の起点を記録する。
        kept = [] if args.all else [
            i for i in items if not any(str(i.get("sha", "")).startswith(s) for s in args.shas)]
        removed = len(items) - len(kept)
        board[UNPUSHED_KEY], board[LAST_PUSH_AT_KEY] = kept, iso(at)
        if args.pushed:
            board[LAST_PUSH_KEY] = args.pushed
        save_board(ctx, board)
        print(f"{removed}件をpush済みとして外した")
        items = kept
    print(push_due_line(board, at))
    for i in items:
        rng = f"{i.get('base')}..{i.get('sha')}" if i.get("base") else str(i.get("sha"))
        who = i.get("agent") or i.get("branch") or "-"
        print(f"  {who}: {rng}  監査{hm(parse_time(i.get('audited')))}{'  即時' if i.get('urgent') else ''}")
    if items and args.op == "list":
        # 範囲ごとに分けて取り込む（1回のcherry-pickへ並べると、範囲の和として解釈される）。
        picks = " && ".join(f"git cherry-pick {i['base']}..{i['sha']}" if i.get("base")
                            else f"git cherry-pick {i.get('sha')}" for i in items)
        print("\n1回でpushする手順（司令塔の作業ツリーで、heavyの枠の中。衝突したら中止して担当へ差し戻す）:")
        print(f"  python scripts/lockrun.py heavy -- 'git fetch origin master && git switch -C land origin/master"
              f" && {picks} && git push origin \"$(git rev-parse HEAD)\":refs/heads/master'")
        print("  python scripts/orchestrate.py board unpushed done --all --pushed <pushしたsha>")
    return 0


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
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
    p.add_argument("--checks-in", help="静的検査を走らせる検査用の作業ツリー（shaを取り出す。変更なしであること）")
    p.add_argument("--no-checks", action="store_true", help="静的検査を走らせない")
    p.add_argument("--no-ci", action="store_true", help="CIの結論を読まない")

    p = sub.add_parser("board", help="状態の表の更新")
    bsub = p.add_subparsers(dest="board_cmd", required=True)
    for name in ("set", "add"):
        q = bsub.add_parser(name)
        q.add_argument("name")
        q.add_argument("pairs", nargs="*")
    q = bsub.add_parser("run")
    q.add_argument("pairs", nargs="+")
    bsub.add_parser("show")
    bsub.add_parser("claim", help="このセッションを司令塔として記録する（直後のフックが記録する）")
    for name, help_text in (("todo", "司令塔のキュー（中断・待ちの作業）"), ("dispatch", "振り出し待ちのキュー")):
        q = bsub.add_parser(name, help=help_text)
        ops = q.add_subparsers(dest="op", required=True)
        r = ops.add_parser("push")
        r.add_argument("text")
        r.add_argument("--priority", type=int, default=7, help="規約「司令塔の作業の優先順位」の順位（1が最優先）")
        r.add_argument("pairs", nargs="*")
        r = ops.add_parser("pop")
        r.add_argument("index", nargs="?", type=int, help="listの番号（既定: 先頭）")
        ops.add_parser("list")
    q = bsub.add_parser("unpushed", help="監査済み・未pushのコミット")
    ops = q.add_subparsers(dest="op", required=True)
    r = ops.add_parser("add")
    r.add_argument("agent")
    r.add_argument("sha")
    r.add_argument("--base", help="監査した範囲の基点")
    r.add_argument("--urgent", action="store_true", help="セキュリティ・利用者に届いている欠陥の修正（即時push）")
    r = ops.add_parser("done", help="masterへ届いたものを外す")
    r.add_argument("shas", nargs="*")
    r.add_argument("--all", action="store_true")
    r.add_argument("--pushed", help="masterへpushしたsha（last_master_pushへ記録）")
    ops.add_parser("list")

    args = parser.parse_args(argv)
    if args.cmd == "check" and args.if_due:
        return check_if_due(args)
    ctx = Context(Path(args.repo), args.dir)
    handler = {"gate": cmd_gate, "status": cmd_status, "check": cmd_check,
               "audit": cmd_audit, "board": cmd_board}[args.cmd]
    return handler(ctx, args)


if __name__ == "__main__":
    sys.exit(main())
