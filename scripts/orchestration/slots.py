"""並行実行の作業ツリーを固定数のスロットとして使い回す。依頼で足した側の機能。

エージェントの作業ツリーは`<本体>/.claude/worktrees/slot-<N>`に固定数だけ置き、消さずに次の
タスクへ渡し直す。数は回の上限（状態の表の`limits.concurrent`、無ければ既定）と同じ。

    python scripts/orchestrate.py slot list          # スロットごとの事実
    python scripts/orchestrate.py slot release <N>   # 渡した印（ロック）を外す
    python scripts/orchestrate.py slot hook-create   # WorktreeCreateフックの入口（標準入力がJSON）
    python scripts/orchestrate.py slot hook-remove   # WorktreeRemoveフックの入口

## 渡したかどうかは作業ツリー自身が持つ

渡した印は`git worktree lock`の理由（`slot <名前> <時刻>`）で、状態の表には書かない。gitの
ロックは作成が原子的なので、2本が同時に同じスロットを取りに来ても片方だけが取れる。

印を外す契機（監査で通したとき・`slot release`）は規約「作業ツリーのスロット」節。

## 渡し直すときに止まる条件（黙って消さない）

- 未コミットの変更がある
- どのリモートの枝からも届かないコミットがある（pushしていない成果）。ただし取り込み済みのもの——監査で
  通した報告のshaから届き、そのタスクが監査の後にmasterへ入ったもの——は数えない。masterへは畳み直した
  別のコミットが入り、作業ブランチも消えるので、担当の元のコミットはどの枝からも届かなくなる
  （判定は`core.unlanded_commits`で、`board unpushed`のmasterへ入ったかの判定と同じもの）
- 作業ツリーの中にリンク（ジャンクション・シンボリックリンク）がある——`git worktree remove`の
  再帰削除がリンクの先を消すため、作業ツリーの中に置かない

## 依存

`frontend/package-lock.json`の中身が、前回`npm ci`した時点と違うとき（または`node_modules`が
無いとき）だけ`npm ci`を`heavy`の枠で走らせる。前回の値は`node_modules`の中の印に置く——
`node_modules`を消せば印も消え、入れ直しになる。

## 渡す前に温める

    python scripts/orchestrate.py slot warm          # 空いていて冷えたスロットを最新のmasterで温める

渡すその場で`npm ci`を走らせると、その数分は担当が着手できない。そこで定期確認（`check`）が、
空いている（印の無い）スロットの印がorigin/masterの`package-lock.json`と違えば`slot warm`を裏で起こす
（`start_warm`）。確認そのものは待たない——`npm ci`は枠の待ちを含めて10分を超えうるので、同期で
走らせると確認の結果が返らず、その間は次の確認も止まる。起こした処理の出力は`<orchestrationディレクトリ>/warm.log`
（起こすたびに上書き）。

温めている間は、そのスロットに印（`slot warm-<pid> <時刻>`）を付ける。渡す側（フック）は温めている
スロットしか空いていなければ、温め終わるのを待ってから渡す——待つ時間は、その場で`npm ci`を
走らせる時間を超えない。温める処理が死んで印だけが残ったら（pidのプロセスが無い）、渡す側が外す。
担当に渡しているスロットには触らない。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from orchestration import procs
from orchestration.core import (
    DEFAULT_CONCURRENT,
    ENTRY,
    EXPECTED_HOOKS_PATH,
    SLOT_LOCK_PREFIX,
    Context,
    git,
    git_out,
    list_worktrees,
    load_board,
    restore_hooks_path,
    unsaved_work,
)

SLOT_PREFIX = "slot-"
PACKAGE_LOCK = "frontend/package-lock.json"
NPM_MARK = "frontend/node_modules/.slot-package-lock.sha1"
#: 温めている間の印の渡し先の頭（`warm-<pid>`）。
WARM_OWNER_PREFIX = "warm-"
WARM_LOG = "warm.log"
#: 渡す側が温め終わりを待つ上限。WorktreeCreateフックの時間切れ（.claude/settings.jsonの1800秒）より短く、
#: 枠の保持の上限（10分）に枠の待ちを足した長さを覆う。
WARM_WAIT_SECONDS = 1200
WARM_POLL_SECONDS = 5
#: 作業ツリーの中にあってはならないリンクの置き場（過去に共有元を指すジャンクションが置かれた所）。
LINK_CANDIDATES = ("frontend/node_modules", "node_modules", "backend/data", "backend/.venv")
DEFAULT_BASE = "origin/master"


class SlotError(Exception):
    """渡し直しを止める理由。スロットには手を付けずに報告する。"""


class Warming(SlotError):
    """温めている途中のスロット。終われば渡せる。"""


def main_root(ctx: Context) -> Path:
    return ctx.common.parent


def slot_count(ctx: Context) -> int:
    value = load_board(ctx).get("limits", {}).get("concurrent")
    return value if isinstance(value, int) and value > 0 else DEFAULT_CONCURRENT


def slot_path(ctx: Context, n: int) -> Path:
    return main_root(ctx) / ".claude" / "worktrees" / f"{SLOT_PREFIX}{n}"


def slot_number(ctx: Context, path: str) -> int | None:
    p = Path(os.path.normpath(path))
    if os.path.normcase(str(p.parent)) != os.path.normcase(str(slot_path(ctx, 1).parent)):
        return None
    name = p.name
    return int(name[len(SLOT_PREFIX):]) if name.startswith(SLOT_PREFIX) and name[len(SLOT_PREFIX):].isdigit() else None


def registered(ctx: Context) -> dict[str, str]:
    """登録済みの作業ツリー（正規化したパス → ロックの理由。ロックが無ければ空文字）。"""
    return {os.path.normcase(t.path): (t.locked or "(理由なし)") if t.locked is not None else ""
            for t in list_worktrees(ctx)}


def lock_reason(ctx: Context, path: Path) -> str | None:
    """ロックの理由。ロックされていなければNone、登録されていなければKeyError。"""
    trees = registered(ctx)
    key = os.path.normcase(os.path.normpath(str(path)))
    if key not in trees:
        raise KeyError(str(path))
    return trees[key] or None


def run_git(cwd: Path, *args: str, strip: bool = True) -> str:
    r = git(cwd, *args)
    if r is None or r.returncode != 0:
        err = "" if r is None else r.stderr.decode("utf-8", errors="replace").strip()
        raise SlotError(f"git {' '.join(args)} が失敗: {err or '時間切れ'}")
    out = r.stdout.decode("utf-8", errors="replace")
    return out.strip() if strip else out


def is_link(path: Path) -> bool:
    return os.path.islink(path) or bool(getattr(os.path, "isjunction", lambda _: False)(path))


def blockers(ctx: Context, path: Path) -> list[str]:
    """渡し直しを止める事実。空なら渡し直してよい。"""
    links = [f"作業ツリーの中にリンクがある: {rel}" for rel in LINK_CANDIDATES if is_link(path / rel)]
    return links + unsaved_work(ctx, path)


def lock_file_sha(path: Path) -> str | None:
    lock = path / PACKAGE_LOCK
    return hashlib.sha1(lock.read_bytes()).hexdigest() if lock.exists() else None


def lock_sha_at(ctx: Context, rev: str) -> str | None:
    """revの`package-lock.json`の、印と同じ形の値（中身のsha1）。"""
    r = git(ctx.repo, "show", f"{rev}:{PACKAGE_LOCK}")
    return hashlib.sha1(r.stdout).hexdigest() if r is not None and r.returncode == 0 else None


def deps_mark(path: Path) -> str | None:
    mark = path / NPM_MARK
    return mark.read_text(encoding="utf-8").strip() if mark.exists() else None


def ensure_deps(path: Path) -> str:
    """package-lock.jsonが前回のnpm ciから変わったときだけnpm ciを走らせる。何をしたかを返す。"""
    want = lock_file_sha(path)
    if want is None:
        return "frontend/package-lock.jsonが無い"
    mark = path / NPM_MARK
    if deps_mark(path) == want:
        return "npm ciは不要（package-lock.jsonが前回と同じ）"
    lockrun = Path(__file__).resolve().parents[1] / "lockrun.py"
    cmd = [sys.executable, str(lockrun), "--",
           f"cd '{(path / 'frontend').as_posix()}' && npm ci --no-audit --no-fund"]
    r = subprocess.run(cmd, stdout=sys.stderr, stderr=sys.stderr, check=False)
    if r.returncode != 0:
        raise SlotError(f"npm ciが失敗（終了コード{r.returncode}）")
    mark.write_text(want + "\n", encoding="utf-8")
    return "npm ciを実行した（package-lock.jsonが前回と違う、またはnode_modulesが無い）"


def claim(ctx: Context, path: Path, owner: str) -> None:
    """渡した印を付ける。`git worktree lock`は既にロックがあれば失敗するので、同時に取りに来た
    2本のうち片方だけが取れる。"""
    at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    run_git(ctx.repo, "worktree", "lock", "--reason", f"{SLOT_LOCK_PREFIX}{owner} {at}", str(path))


def reset_to(ctx: Context, path: Path, branch: str, base: str) -> None:
    """止める理由が無いことを確かめてから、作業用の枝をbaseから作り直す。"""
    problems = blockers(ctx, path)
    if problems:
        raise SlotError(f"{path.name} を渡し直せない: " + " / ".join(problems))
    run_git(path, "switch", "--quiet", "-C", branch, base)


def prepare(ctx: Context, n: int, owner: str, base: str) -> Path:
    """スロットNを最新のbaseから渡せる状態にし、ownerへ渡した印を付ける。
    止める理由があれば中身を変えずにSlotError（付けた印は外す）。"""
    path = slot_path(ctx, n)
    branch = f"{SLOT_PREFIX}{n}"
    try:
        reason = lock_reason(ctx, path)
        created = False
    except KeyError:
        if path.exists():
            raise SlotError(f"{path} は作業ツリーとして登録されていないのにディレクトリがある")
        run_git(ctx.repo, "worktree", "add", "--quiet", "-B", branch, str(path), base)
        reason, created = None, True
    pid = warm_pid(reason)
    if pid is not None:
        if process_alive(pid):
            raise Warming(f"{path.name} は温めている途中（{reason}）")
        run_git(ctx.repo, "worktree", "unlock", str(path))
        print(f"[slot] {path.name}: 温める処理が死んで残った印を外した（{reason}）", file=sys.stderr)
        reason = None
    if reason and not reason.startswith(f"{SLOT_LOCK_PREFIX}{owner} "):
        raise SlotError(f"{path.name} は渡し済み（{reason}）")
    if reason:
        run_git(ctx.repo, "worktree", "unlock", str(path))
    claim(ctx, path, owner)
    try:
        if not created:
            reset_to(ctx, path, branch, base)
        print(f"[slot] {path.name}: {ensure_deps(path)}", file=sys.stderr)
    except SlotError:
        run_git(ctx.repo, "worktree", "unlock", str(path))
        raise
    restore_hooks_path(ctx)
    return path


def acquire(ctx: Context, owner: str, base: str) -> Path:
    """空いているスロットを1つ渡す。空きが無ければSlotError（上限を仕組みで守る）。
    温めている途中のスロットしか空いていなければ、温め終わるのを待つ。"""
    run_git(ctx.repo, "fetch", "--quiet", "origin", "master")
    deadline = time.monotonic() + WARM_WAIT_SECONDS
    announced = False
    while True:
        reasons, warming = [], False
        for n in range(1, slot_count(ctx) + 1):
            try:
                return prepare(ctx, n, owner, base)
            except SlotError as e:
                reasons.append(str(e))
                warming = warming or isinstance(e, Warming)
        if not warming or time.monotonic() > deadline:
            raise SlotError("空いているスロットが無い: " + " / ".join(reasons))
        if not announced:
            print("[slot] 温めている途中のスロットしか空いていないため、温め終わるのを待つ", file=sys.stderr)
            announced = True
        time.sleep(WARM_POLL_SECONDS)


def warm_pid(reason: str | None) -> int | None:
    """温めている間の印なら、温める処理のpid。"""
    head = f"{SLOT_LOCK_PREFIX}{WARM_OWNER_PREFIX}"
    if not reason or not reason.startswith(head):
        return None
    digits = reason[len(head):].split(" ", 1)[0]
    return int(digits) if digits.isdigit() else None


def process_alive(pid: int) -> bool:
    """温める処理がまだ動いているか。pidは使い回されうるので、コマンドラインが読めればそれも見る。
    確かめられないときは生きているとみなす（温めている途中のスロットを渡さない側へ倒す）。"""
    table = procs.processes()
    if table is None:
        return True
    p = table.get(pid)
    return p is not None and (p.cmdline is None or "warm" in p.cmdline)


def cold_slots(ctx: Context, base: str = DEFAULT_BASE) -> list[int]:
    """空いていて（印が無い）、渡すとnpm ciが走る（印がbaseのpackage-lock.jsonと違う）スロット。
    作っていないスロットは数えない（作るのは渡す側）。"""
    want = lock_sha_at(ctx, base)
    if want is None:
        return []
    trees = registered(ctx)
    return [n for n in range(1, slot_count(ctx) + 1)
            if trees.get(os.path.normcase(os.path.normpath(str(slot_path(ctx, n))))) == ""
            and deps_mark(slot_path(ctx, n)) != want]


def warm(ctx: Context, base: str) -> int:
    """空いていて冷えたスロットを、印を付けてから最新のbaseへ作り直し、依存を入れて印を外す。
    止める理由（未コミットの変更等）があるスロットは中身を変えずに飛ばす。"""
    run_git(ctx.repo, "fetch", "--quiet", "origin", "master")
    owner = f"{WARM_OWNER_PREFIX}{os.getpid()}"
    failed = 0
    for n in cold_slots(ctx, base):
        path = slot_path(ctx, n)
        try:
            claim(ctx, path, owner)
        except SlotError as e:
            print(f"[slot] {path.name}: 温めない（先に印が付いた）: {e}", file=sys.stderr)
            continue
        try:
            reset_to(ctx, path, f"{SLOT_PREFIX}{n}", base)
            print(f"[slot] {path.name}: {ensure_deps(path)}", file=sys.stderr)
        except SlotError as e:
            print(f"[slot] {path.name}: 温められない: {e}", file=sys.stderr)
            failed += 1
        finally:
            run_git(ctx.repo, "worktree", "unlock", str(path))
    return 1 if failed else 0


def start_warm(ctx: Context) -> str | None:
    """空いていて冷えたスロットがあれば、`slot warm`を裏で起こし、何をしたかの1行を返す。無ければNone。
    起こした処理は呼び出し元（定期確認・フック）の終了を待たずに残る。"""
    cold = cold_slots(ctx)
    if not cold:
        return None
    names = "・".join(f"{SLOT_PREFIX}{n}" for n in cold)
    log = ctx.dir / WARM_LOG
    cmd = [sys.executable, str(ENTRY), "--repo", str(ctx.repo), "--dir", str(ctx.dir), "slot", "warm"]
    try:
        ctx.dir.mkdir(parents=True, exist_ok=True)
        with open(log, "wb") as out:
            spawn_detached(cmd, ctx.repo, out)
    except OSError as e:
        return f"{names}のpackage-lock.jsonがorigin/masterと違うが、温める処理を起こせなかった（{e}）"
    return f"{names}のpackage-lock.jsonがorigin/masterと違うため、npm ciを裏で起こした（出力は{log}）"


def spawn_detached(cmd: list[str], cwd: Path, out) -> None:
    kwargs: dict = {"cwd": str(cwd), "stdin": subprocess.DEVNULL, "stdout": out, "stderr": subprocess.STDOUT}
    if sys.platform != "win32":
        subprocess.Popen(cmd, start_new_session=True, **kwargs)
        return
    # 窓を出さず（子のgit・bashも同じ隠れたコンソールを使う）、呼び出し元のジョブの終了に巻き込まれないよう
    # ジョブから抜ける。抜けることを許さないジョブの中では、抜けずに起こす。
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    try:
        subprocess.Popen(cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs)
    except OSError:
        subprocess.Popen(cmd, creationflags=flags, **kwargs)


def cmd_list(ctx: Context) -> int:
    trees = registered(ctx)
    want = lock_sha_at(ctx, DEFAULT_BASE)
    for n in range(1, slot_count(ctx) + 1):
        path = slot_path(ctx, n)
        key = os.path.normcase(os.path.normpath(str(path)))
        if key not in trees:
            print(f"{path.name}: 未作成")
            continue
        facts = [f"渡し先 {trees[key]}" if trees[key] else "空き（ロックなし）"]
        facts += blockers(ctx, path) or ["渡し直せる"]
        facts.append("依存はorigin/masterと同じ" if want and deps_mark(path) == want
                     else "依存がorigin/masterと違う（渡すか温めるとnpm ci）")
        head = git_out(path, "log", "-1", "--format=%h %cd", "--date=format:%m-%d %H:%M") or "?"
        print(f"{path.name}: {head} / " + " / ".join(facts))
    extra = [p for p in trees if os.path.basename(p) not in
             {f"{SLOT_PREFIX}{n}" for n in range(1, slot_count(ctx) + 1)}]
    print(f"スロット以外の作業ツリー: {len(extra) - 1}本（本体を除く）")
    hooks = git_out(ctx.repo, "config", "--get", "core.hooksPath")
    print(f"core.hooksPath={hooks}" + ("" if hooks == EXPECTED_HOOKS_PATH else "（相対の.githooksでない）"))
    return 0


def read_hook_input() -> dict:
    # Windowsの標準入力は既定でロケールの文字コードとして読まれ、UTF-8のパス（日本語を含む）が化ける。
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    return json.loads(raw) if raw.strip() else {}


def hook_create(ctx: Context) -> int:
    """WorktreeCreateフック。標準入力の`name`を渡し先として、空きスロットのパスを最後の行に出す。
    失敗（空きが無い等）は0以外で終わり、Claude Codeは作業ツリーを作らずに起動を止める。"""
    data = read_hook_input()
    owner = str(data.get("name") or "unknown")
    try:
        path = acquire(ctx, owner, DEFAULT_BASE)
    except SlotError as e:
        print(f"[slot] 作業ツリーを渡せない: {e}", file=sys.stderr)
        return 1
    print(str(path))
    return 0


def hook_remove(ctx: Context) -> int:
    """WorktreeRemoveフック。スロットなら渡した印を外すだけで、ディレクトリは消さない。
    Claude Codeがこれを呼ぶのは利用者が作業ツリーを明示的に破棄したときだけ（担当の終了では
    呼ばない）。登録しておく理由は、フックが無いと破棄の処理が既定の`git worktree remove`へ
    落ち、スロットのディレクトリごと消えうること。"""
    data = read_hook_input()
    path = str(data.get("worktree_path") or "")
    n = slot_number(ctx, path) if path else None
    if n is not None:
        try:
            if lock_reason(ctx, slot_path(ctx, n)):
                run_git(ctx.repo, "worktree", "unlock", str(slot_path(ctx, n)))
        except (KeyError, SlotError) as e:
            print(f"[slot] 印を外せない: {e}", file=sys.stderr)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="orchestrate.py slot", description="作業ツリーのスロット")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--dir", default=os.environ.get("ORCH_DIR"))
    sub = parser.add_subparsers(dest="op", required=True)
    sub.add_parser("list")
    p = sub.add_parser("release")
    p.add_argument("n", type=int)
    sub.add_parser("hook-create")
    sub.add_parser("hook-remove")
    sub.add_parser("warm")
    args = parser.parse_args(argv)
    ctx = Context(Path(args.repo), args.dir)
    try:
        if args.op == "list":
            return cmd_list(ctx)
        if args.op == "release":
            path = slot_path(ctx, args.n)
            if lock_reason(ctx, path):
                run_git(ctx.repo, "worktree", "unlock", str(path))
            return 0
        if args.op == "hook-create":
            return hook_create(ctx)
        if args.op == "warm":
            return warm(ctx, DEFAULT_BASE)
        return hook_remove(ctx)
    except SlotError as e:
        print(f"[slot] {e}", file=sys.stderr)
        return 2
    except KeyError as e:
        print(f"[slot] 作業ツリーとして登録されていない: {e}", file=sys.stderr)
        return 2
