"""段の状態を動かす唯一の口と、作業ツリーのスロットの貸し借り。規約は docs/conventions/flow.md。

仕掛の置き場（非公開のリポジトリの Issues と、その持ち主の Project）と回答ページは git の設定で持つ:

    git config flow.repo <持ち主>/<リポジトリ>
    git config flow.project <Project の番号>
    git config flow.answer <回答ページの URL>

ユーザーへの問いは道具用の別アカウントが書く（環境変数 FLOW_ASK_TOKEN）。それ以外の操作は gh のアカウントのまま。

    python scripts/flow.py propose "<題名>" [--task T1253] [--body "<本文>"]
    python scripts/flow.py take                # ユーザーの回答（承認・見送り・問いへの答え）を取り込む
    python scripts/flow.py move <段> <②|③|④|⑤> [--reason …] [--by … --missing … --review … --choice …]
    python scripts/flow.py land <段>
    python scripts/flow.py ci <40桁のsha>
    python scripts/flow.py setup <持ち主>/<リポジトリ>   # Project の欄を作る gh のコマンドを出す（流すのは人）
    python scripts/flow.py hook-create | hook-remove    # WorktreeCreate・WorktreeRemove フック

GitHub へは gh だけで触る。⑥ は閉じた issue で、状態の欄には書かない。Projects には遷移を断る仕組みが無いので、
遷移の表はここが持つ。
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

STATES = {"①": "① 提案", "②": "② 保留", "③": "③ 未着手", "④": "④ 進行中", "⑤": "⑤ 検証中"}
DONE = "⑥"
ACTORS = ("司令塔", "ユーザー", "担当")
#: 状態ごとの次に動かす人。② だけは止めている人を遷移のたびに受け取る。
NEXT_ACTOR = {"①": "ユーザー", "③": "司令塔", "④": "担当", "⑤": "司令塔"}
#: ② へ入ったときに記録する戻り先。② → ② は今の戻り先を引き継ぐ。
RETURN_TO = {"①": "③", "④": "③", "⑤": "⑤"}
BACK = "戻り先"
#: 遷移の表。docs/conventions/flow.md の遷移の表と同じ行を持つ（テストが突き合わせる）。
TRANSITIONS = {
    ("①", "③"): ("入口", "「承認」の回答があり、前提が欠けていない"),
    ("①", "②"): ("入口", "「承認」の回答があり、本文の「前提:」の段がまだ⑥でない"),
    ("②", BACK): ("止めている人（前提の段が⑥になったら出口）",
                  "欠けていたものが満たされた（ユーザーの問いは回答、前提の段は⑥）。行き先は ② へ入ったときの戻り先（①・④ からは ③、⑤ からは ⑤）"),
    ("②", "②"): ("止めている人", "見直す日を延ばす。1回だけ"),
    ("③", "④"): ("司令塔", "空いたスロットがある"),
    ("④", "⑤"): ("担当", "作業ブランチの master より先のコミットがあり、件名がすべて段で始まる"),
    ("④", "②"): ("担当", "止めている人・欠けているもの・見直す日"),
    ("⑤", "④"): ("司令塔", "差し戻しの理由"),
    ("⑤", "②"): ("司令塔", "ユーザーの操作・目視が要る"),
    ("⑤", "⑥"): ("出口", "④→⑤の条件に加え、コミットの本文に検証の結果があり、CI が緑で、master から早送りできる"),
    ("①〜⑤", "⑥"): ("ユーザー（見送り）", "「見送り」の回答"),
}
APPROVE, DROP = "承認", "見送り"
ASK_TOKEN_ENV = "FLOW_ASK_TOKEN"
#: 回答ページ（tools/answer-form/worker.js）が書くコメントの1行目。答えは括弧の中の選択肢。
ANSWER_RE = re.compile(r"^回答: [A-Z]（(.+)）\s*$")
QUESTION_RE = re.compile(r"^@\S+ 問い: ")
#: 入口が前提の段を待たせるときの見直す日（承認の日から）。
PREREQ_REVIEW_DAYS = 30
PASSING = ("success", "skipped", "neutral")
SLOTS = 4
SLOT_LOCK = "slot "
CI_WAIT_SECONDS, CI_POLL_SECONDS = 20 * 60, 30
#: Project の欄（名前 → gh の型）。single select の選択肢は SELECT_OPTIONS。
FIELDS = {"状態": "SINGLE_SELECT", "段": "TEXT", "次に動かす人": "SINGLE_SELECT", "欠けているもの": "TEXT",
          "見直す日": "DATE", "延ばした回数": "NUMBER", BACK: "SINGLE_SELECT"}
SELECT_OPTIONS = {"状態": list(STATES.values()), "次に動かす人": list(ACTORS),
                  BACK: sorted({STATES[s] for s in RETURN_TO.values()})}
STAGE_RE = re.compile(r"^T\d+-[A-Z]$")
#: `gh project item-list` の JSON は欄の名前の頭の1バイトを小文字にして鍵にするため、日本語の欄の名前が壊れる。
#: GraphQL で名前をそのまま読む。
_VALUE = "field { ... on ProjectV2FieldCommon { name } }"
ITEMS_QUERY = (
    "query($owner: String!, $number: Int!, $endCursor: String) { user(login: $owner) { projectV2(number: $number) {"
    " items(first: 100, after: $endCursor) { pageInfo { hasNextPage endCursor } nodes {"
    " content { ... on Issue { url } } fieldValues(first: 20) { nodes {"
    f" ... on ProjectV2ItemFieldSingleSelectValue {{ name {_VALUE} }}"
    f" ... on ProjectV2ItemFieldTextValue {{ text {_VALUE} }}"
    f" ... on ProjectV2ItemFieldDateValue {{ date {_VALUE} }}"
    f" ... on ProjectV2ItemFieldNumberValue {{ number {_VALUE} }} }} }} }} }} }} }} }}"
)


class FlowError(Exception):
    pass


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> str:
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       check=False)
    if r.returncode != 0:
        raise FlowError(f"{' '.join(cmd[:3])} が失敗: {(r.stderr or r.stdout).strip()}")
    return r.stdout


def git(*args: str, cwd: Path | None = None) -> str:
    return run(["git", *args], cwd).strip()


def gh(*args: str, token: str | None = None) -> str:
    return run(["gh", *args], env={**os.environ, "GH_TOKEN": token} if token else None)


def ask_token() -> str:
    token = os.environ.get(ASK_TOKEN_ENV)
    if not token:
        raise FlowError(f"ユーザーへの問いを書く別アカウントのトークン（環境変数 {ASK_TOKEN_ENV}）が無い")
    return token


class Place:
    """仕掛の置き場。並行する担当が同じ置き場を書くので、読むたびに GitHub から読み直す。"""

    def __init__(self) -> None:
        self.repo = git("config", "--get", "flow.repo")
        self.project = git("config", "--get", "flow.project")
        self.answer = git("config", "--get", "flow.answer").rstrip("/")
        self.owner = self.repo.split("/")[0]

    def answer_url(self, number: int, choices: list[str]) -> str:
        return f"{self.answer}/answer?" + urllib.parse.urlencode([("issue", number), *(("o", c) for c in choices)])

    def open_comments(self) -> dict[int, list[str]]:
        rows = json.loads(gh("issue", "list", "-R", self.repo, "--state", "open", "--limit", "1000",
                             "--json", "number,comments"))
        return {r["number"]: [c["body"] for c in r["comments"]] for r in rows}

    def issues(self) -> list[dict]:
        """全部の issue（閉じたものを含む）と、その Project の欄 `fields`（欄の名前 → 値）。"""
        issues = json.loads(gh("issue", "list", "-R", self.repo, "--state", "all", "--limit", "5000",
                               "--json", "number,title,body,state,labels,url"))
        pages = json.loads(gh("api", "graphql", "--paginate", "--slurp", "-f", f"query={ITEMS_QUERY}",
                              "-F", f"owner={self.owner}", "-F", f"number={self.project}"))
        fields = {}
        for page in pages:
            for node in page["data"]["user"]["projectV2"]["items"]["nodes"]:
                fields[(node.get("content") or {}).get("url")] = {
                    v["field"]["name"]: next(v[k] for k in ("name", "text", "date", "number") if k in v)
                    for v in node["fieldValues"]["nodes"] if v.get("field")}
        for issue in issues:
            issue["fields"] = fields.get(issue["url"], {})
        return issues

    def find(self, stage: str) -> dict:
        found = [i for i in self.issues() if i["title"].startswith(f"{stage}:")]
        if len(found) != 1:
            raise FlowError(f"題名が「{stage}:」で始まる issue が{len(found)}件ある（1件のはず）")
        return found[0]

    def set(self, issue: dict, name: str, value: object) -> None:
        cmd = ["project", "item-edit", self.project, "--owner", self.owner, "--url", issue["url"], "--field", name]
        gh(*cmd, *(["--clear"] if value is None else ["--value", str(value)]))

    def comment(self, issue: dict, text: str) -> None:
        gh("issue", "comment", str(issue["number"]), "-R", self.repo, "--body", text)

    def ask(self, number: int, question: str, choices: list[str]) -> None:
        """ユーザーへの問い。別アカウントが書いて本文で名指しするので、ユーザーに通知が届く。"""
        body = (f"@{self.owner} 問い: {question}\n\n選択肢: {' ／ '.join(choices)}\n\n"
                f"答える: {self.answer_url(number, choices)}")
        gh("issue", "comment", str(number), "-R", self.repo, "--body", body, token=ask_token())


def state_of(issue: dict) -> str | None:
    if issue["state"] == "CLOSED":
        return DONE
    return state_key(issue["fields"].get("状態"))


def state_key(name: str | None) -> str | None:
    return next((key for key, value in STATES.items() if value == name), None)


def answers(comments: list[str]) -> list[str]:
    """回答ページが書いた答え（選択肢）。古い順。"""
    return [m.group(1) for c in comments if (m := ANSWER_RE.match(c.splitlines()[0] if c else ""))]


def latest_answer(comments: list[str]) -> str | None:
    """最後の問いより後の答えのうち最後のもの。前の問いへの答えを次の問いの答えにしない。"""
    last = max((i for i, c in enumerate(comments) if QUESTION_RE.match(c)), default=-1)
    return next(iter(reversed(answers(comments[last + 1:]))), None)


def hold_values(args: argparse.Namespace, issue: dict | None = None) -> dict:
    """② の欄。止めている人・欠けているもの・見直す日はどれも欠かせない（延長では今の値を引き継ぐ）。
    ユーザーが止めるなら、回答ページで選ぶだけで済むよう選択肢（--choice）と、問いを書く別アカウントも欠かせない。"""
    old = (issue or {}).get("fields", {})
    by, missing = args.by or old.get("次に動かす人"), args.missing or old.get("欠けているもの")
    if by not in ACTORS or not missing or not args.review:
        raise FlowError(f"② には --by（{'・'.join(ACTORS)}）・--missing・--review（見直す日）が要る")
    if by == "ユーザー" and not issue:
        if not args.choice:
            raise FlowError("ユーザーが止める ② には選択肢（--choice を1つ以上）が要る")
        ask_token()
    try:
        review = dt.date.fromisoformat(args.review)
    except ValueError as e:
        raise FlowError(f"--review は YYYY-MM-DD: {args.review}") from e
    if review < dt.date.today():
        raise FlowError(f"見直す日 {review} が過去")
    return {"次に動かす人": by, "欠けているもの": missing, "見直す日": review.isoformat()}


def transition(place: Place, issue: dict, to: str, note: str, hold: dict | None = None,
               choices: list[str] | None = None) -> None:
    """表にある遷移だけを書く。欄を書いてから、何がなぜ動いたかを issue のコメントに残し、選択肢があれば問う。
    ② から出る行き先は ② へ入ったときの戻り先だけ（to に BACK を渡せば戻り先へ）。"""
    frm, fields = state_of(issue), issue["fields"]
    if frm is None:
        raise FlowError(f"状態の欄が無い（{issue['title']}）")
    key = (frm, to)
    if frm == "②" and to != "②":
        back = state_key(fields.get(BACK))
        if back is None or to not in (BACK, back):
            raise FlowError(f"② の戻り先は {back}（{issue['title']}）")
        to, key = back, ("②", BACK)
    if key not in TRANSITIONS:
        raise FlowError(f"{frm} → {to} は遷移の表に無い（{issue['title']}）")
    if to == "②":
        count = int(fields.get("延ばした回数") or 0) + 1 if frm == "②" else 0
        if count > 1:
            raise FlowError("見直す日を延ばせるのは1回だけ。2回目は見送るかをユーザーに問う")
        values = {**(hold or {}), "延ばした回数": count}
        if frm != "②":
            values[BACK] = STATES[RETURN_TO[frm]]
    else:
        values = {"次に動かす人": NEXT_ACTOR[to], "欠けているもの": None, "見直す日": None, "延ばした回数": None,
                  BACK: None}
    for name, value in {"状態": STATES[to], **values}.items():
        place.set(issue, name, value)
    place.comment(issue, f"{frm} → {to}" + (f": {note}" if note else ""))
    if choices:
        place.ask(issue["number"], values["欠けているもの"], choices)


# --- 入口と、ユーザーの操作の取り込み ------------------------------------------------

def next_stage(issues: list[dict], task: str | None) -> str:
    """新しいタスクは記録のファイル名と issue の題名の最大の番号＋1、段を足すならそのタスクの次の文字。"""
    if task is None:
        git("fetch", "--quiet", "origin", "master")
        names = git("ls-tree", "--name-only", "origin/master", "docs/records/tasks/").splitlines()
        numbers = [int(m.group(1)) for n in names if (m := re.match(r"T(\d+)", Path(n).name))]
        numbers += [int(m.group(1)) for i in issues if (m := re.match(r"T(\d+)-", i["title"]))]
        return f"T{max(numbers, default=0) + 1}-A"
    subjects = git("log", "--format=%s", "origin/master").splitlines()
    letters = [m.group(1) for i in issues if (m := re.match(rf"{task}-([A-Z]):", i["title"]))]
    letters += [m.group(1) for s in subjects if (m := re.match(rf"{task}(?:-| 段階)([A-Z])\b", s))]
    last = max(letters, default="@")
    if last == "Z":
        raise FlowError(f"{task} の段の文字が尽きた")
    return f"{task}-{chr(ord(last) + 1)}"


def admit(place: Place, issue: dict) -> str:
    """入口。番号を振って題名の頭と欄「段」に書き、以後変えない。本文の「前提: T1234-A」の段がまだ⑥でなければ②へ。
    本文には、ユーザーがいつでも見送れるよう「見送り」の回答ページへのリンクを置く。"""
    task = re.search(r"^タスク: (T\d+)$", issue["body"] or "", re.M)
    stage = next_stage(place.issues(), task.group(1) if task else None)
    body = f"{issue['body'] or ''}\n\n見送る: {place.answer_url(issue['number'], [DROP])}"
    gh("issue", "edit", str(issue["number"]), "-R", place.repo, "--title", f"{stage}: {issue['title']}",
       "--body", body)
    # 採番は読んでから書くので、同時に振った別の issue と同じ番号になりうる。番号の若い issue が勝ち、こちらが振り直す。
    while not task and any(i["number"] < issue["number"] and i["title"].startswith(stage[:-1])
                           for i in place.issues()):
        stage = next_stage(place.issues(), None)
        gh("issue", "edit", str(issue["number"]), "-R", place.repo, "--title", f"{stage}: {issue['title']}")
    place.set(issue, "段", stage)
    prereq = re.search(r"^前提: (T\d+-[A-Z])$", issue["body"] or "", re.M)
    waiting = prereq.group(1) if prereq else None
    if waiting and any(i["title"].startswith(f"{waiting}:") and i["state"] == "CLOSED" for i in place.issues()):
        waiting = None
    review = (dt.date.today() + dt.timedelta(days=PREREQ_REVIEW_DAYS)).isoformat()
    hold = {"次に動かす人": "司令塔", "欠けているもの": waiting, "見直す日": review} if waiting else None
    transition(place, issue, "②" if hold else "③", f"承認済み。{stage} を振った", hold)
    return stage


def cmd_take(place: Place, args: argparse.Namespace) -> None:
    """回答ページの答えを取り込む。見送りはどの段でも、承認は ① で、それ以外の答えはユーザーが止める ② で読む。"""
    comments = place.open_comments()
    for issue in place.issues():
        state, texts = state_of(issue), comments.get(issue["number"], [])
        if state in (None, DONE):
            continue
        answer = latest_answer(texts)
        if DROP in answers(texts):
            gh("issue", "close", str(issue["number"]), "-R", place.repo, "--reason", "not planned",
               "--comment", f"{state} → ⑥: 見送り（ユーザーの回答）")
            print(f"#{issue['number']} {issue['title']}: {state} → ⑥（見送り）")
        elif state == "①" and answer == APPROVE:
            print(f"#{issue['number']}: {admit(place, issue)}")
        elif state == "②" and issue["fields"].get("次に動かす人") == "ユーザー" and answer:
            transition(place, issue, BACK, f"答え: {answer}")
            print(f"{issue['title']}: ② → {BACK}（答え: {answer}）")


def cmd_propose(place: Place, args: argparse.Namespace) -> None:
    if args.task and not re.fullmatch(r"T\d+", args.task):
        raise FlowError(f"--task は T1234 の形: {args.task}")
    ask_token()
    body = (f"タスク: {args.task}\n\n" if args.task else "") + (args.body or "")
    url = gh("issue", "create", "-R", place.repo, "--title", args.title, "--body", body).strip().splitlines()[-1]
    gh("project", "item-add", place.project, "--owner", place.owner, "--url", url)
    issue = {"url": url}
    place.set(issue, "状態", STATES["①"])
    place.set(issue, "次に動かす人", NEXT_ACTOR["①"])
    place.ask(int(url.rstrip("/").rsplit("/", 1)[1]), f"この提案「{args.title}」を承認するか", [APPROVE, DROP])
    print(url)


# --- 遷移と出口 -------------------------------------------------------------------

def ahead_commits(stage: str) -> list[tuple[str, ...]]:
    """作業ブランチ orch/<段> の、origin/master より先のコミット（sha・件名・本文）。古い順。"""
    git("fetch", "--quiet", "origin", "master", f"orch/{stage}")
    out = git("log", "--reverse", "--format=%H%x1f%s%x1f%b%x1e", f"origin/master..origin/orch/{stage}")
    rows = [tuple(r.strip("\n").split("\x1f")) for r in out.split("\x1e") if r.strip()]
    if not rows:
        raise FlowError(f"orch/{stage} に origin/master より先のコミットが無い")
    wrong = [s for _, s, _ in rows if not s.startswith(f"{stage}:")]
    if wrong:
        raise FlowError(f"件名が「{stage}:」で始まらないコミットがある: {wrong}")
    return rows


def cmd_move(place: Place, args: argparse.Namespace) -> None:
    if args.to not in STATES or args.to == "①":
        raise FlowError("move の行き先は ②〜⑤。完成は land、見送りはユーザーの「見送り」の回答")
    issue = place.find(args.stage)
    frm = state_of(issue)
    if frm not in ("②", "③", "④", "⑤"):
        raise FlowError(f"{frm} からは move で動かさない（① は take、⑥ は終点）")
    hold = hold_values(args, issue if frm == "②" else None) if args.to == "②" else None
    if (frm, args.to) == ("③", "④") and not free_slots():
        raise FlowError("空いたスロットが無い")
    if (frm, args.to) == ("④", "⑤"):
        ahead_commits(args.stage)
    if frm == "⑤" and args.to == "④" and not args.reason:
        raise FlowError("差し戻しには --reason が要る")
    transition(place, issue, args.to, args.reason or "", hold, args.choice)
    if frm == "④":
        release(Path(git("rev-parse", "--show-toplevel")))


def cmd_land(place: Place, args: argparse.Namespace) -> None:
    issue = place.find(args.stage)
    if state_of(issue) != "⑤":
        raise FlowError(f"{args.stage} は ⑤ ではない（{state_of(issue)}）")
    rows = ahead_commits(args.stage)
    unverified = [s for _, s, body in rows if not re.search(r"^検証:\s*\S", body, re.M)]
    if unverified:
        raise FlowError(f"本文に「検証:」の結果が無いコミットがある: {unverified}")
    sha = rows[-1][0]
    runs = json.loads(gh("run", "list", "--commit", sha, "--json", "name,status,conclusion,url"))
    if not runs or any(r["status"] != "completed" or r["conclusion"] not in PASSING for r in runs):
        verdicts = " / ".join(f"{r['name']}={r['conclusion'] or r['status']}" for r in runs) or "実行が無い"
        raise FlowError(f"{sha[:8]} の CI が緑でない: {verdicts}")
    try:
        git("merge-base", "--is-ancestor", "origin/master", sha)
    except FlowError as e:
        raise FlowError("master から早送りできない。差し戻して担当が rebase し直す") from e
    git("push", "--quiet", "origin", f"{sha}:refs/heads/master")
    gh("issue", "close", str(issue["number"]), "-R", place.repo, "--reason", "completed",
       "--comment", f"⑤ → ⑥: {sha} を master へ入れた")
    try:
        git("push", "--quiet", "origin", "--delete", f"orch/{args.stage}")
    except FlowError as e:
        print(f"[flow] 作業ブランチを消せなかった: {e}", file=sys.stderr)
    for other in place.issues():
        if state_of(other) == "②" and other["fields"].get("欠けているもの") == args.stage:
            transition(place, other, BACK, f"前提の {args.stage} が⑥になった")
            print(f"{other['title']}: ② → {BACK}")
    print(f"{args.stage}: {sha} を master へ入れた")


def cmd_ci(args: argparse.Namespace) -> None:
    deadline = time.monotonic() + CI_WAIT_SECONDS
    while True:
        runs = json.loads(gh("run", "list", "--commit", args.sha, "--json", "name,status,conclusion,url"))
        if runs and all(r["status"] == "completed" for r in runs):
            break
        if time.monotonic() > deadline:
            raise FlowError(f"{args.sha[:8]} の CI が {CI_WAIT_SECONDS // 60}分で終わらない")
        time.sleep(CI_POLL_SECONDS)
    for r in runs:
        print(f"{r['name']}: {r['conclusion']}  {r['url']}")
    if any(r["conclusion"] not in PASSING for r in runs):
        raise FlowError("緑でない実行がある（落ちたジョブのログは gh run view <id> --log-failed）")


def cmd_setup(args: argparse.Namespace) -> None:
    """Project の欄を作る gh のコマンド。欄の名前と選択肢はこのファイルの宣言から出す。"""
    repo, owner = args.repo, args.repo.split("/")[0]
    print(f'gh project create --owner {owner} --title "RideCompass の段"   # 出た番号を N とする')
    print(f"gh project link N --owner {owner} --repo {repo}")
    for name, kind in FIELDS.items():
        options = f' --single-select-options "{",".join(SELECT_OPTIONS[name])}"' if name in SELECT_OPTIONS else ""
        print(f'gh project field-create N --owner {owner} --name "{name}" --data-type {kind}{options}')
    print(f"git config flow.repo {repo}")
    print("git config flow.project N")
    print("git config flow.answer <回答ページの URL>")


# --- 作業ツリーのスロット ----------------------------------------------------------

def norm(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def worktrees() -> dict[str, str | None]:
    """登録済みの作業ツリー（正規化したパス → ロックの理由。ロックが無ければ None）。"""
    trees: dict[str, str | None] = {}
    path = ""
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = norm(line[len("worktree "):])
            trees[path] = None
        elif line == "locked" or line.startswith("locked "):
            trees[path] = line[len("locked "):] or "(理由なし)"
    return trees


def slot_paths() -> list[Path]:
    root = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")).parent / ".claude" / "worktrees"
    return [root / f"slot-{n}" for n in range(1, SLOTS + 1)]


def free_slots() -> list[Path]:
    trees = worktrees()
    return [p for p in slot_paths() if trees.get(norm(p)) is None]


def unsaved(path: Path) -> list[str]:
    """貸し直すと失う作業。"""
    problems = []
    if git("status", "--porcelain", cwd=path):
        problems.append("未コミットの変更がある")
    if git("rev-list", "HEAD", "--not", "--remotes", cwd=path):
        problems.append("どのリモートからも届かないコミットがある")
    return problems


def release(path: Path) -> None:
    """スロットなら、失う作業が無いときだけ貸した印（git のロック）を外す。"""
    slots = {norm(p) for p in slot_paths()}
    if norm(path) not in slots or not (worktrees().get(norm(path)) or "").startswith(SLOT_LOCK):
        return
    problems = unsaved(path)
    if problems:
        print(f"[flow] {path.name} の印を外さない: {'・'.join(problems)}", file=sys.stderr)
        return
    git("worktree", "unlock", str(path))


def hook_input() -> dict:
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    return json.loads(raw) if raw.strip() else {}


def cmd_hook_create(args: argparse.Namespace) -> None:
    """空いたスロットを origin/master に戻して貸し、パスを標準出力に返す。git のロックは既にあれば失敗するので、
    同時に取りに来た2本のうち片方だけが取れる。"""
    # `worktree list --porcelain` は ASCII でない理由を引用符と8進の形に書き換える（`-z` は git 2.36 から）。
    name = str(hook_input().get("name") or "").encode("ascii", "ignore").decode() or "unknown"
    git("fetch", "--quiet", "origin", "master")
    reasons = []
    for path in free_slots():
        try:
            if not (path / ".git").exists():
                git("worktree", "add", "--quiet", "--detach", str(path), "origin/master")
            git("worktree", "lock", "--reason", f"{SLOT_LOCK}{name} {dt.datetime.now():%m-%d %H:%M}", str(path))
        except FlowError as e:
            reasons.append(f"{path.name}: {e}")
            continue
        problems = unsaved(path)
        if problems:
            git("worktree", "unlock", str(path))
            reasons.append(f"{path.name}: {'・'.join(problems)}")
            continue
        git("switch", "--quiet", "--detach", "origin/master", cwd=path)
        print(path)
        return
    raise FlowError("空いたスロットが無い" + (f"（{' / '.join(reasons)}）" if reasons else ""))


def cmd_hook_remove(args: argparse.Namespace) -> None:
    """スロットのディレクトリは消さず、失う作業が無ければ印を外す。"""
    path = hook_input().get("worktree_path")
    if path:
        release(Path(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flow.py", description="段の状態を動かす唯一の口")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose", help="① の提案を置く")
    p.add_argument("title")
    p.add_argument("--task", help="段を足すタスク（T1234）。無ければ新しいタスク")
    p.add_argument("--body", default="", help="本文。前提の段を待たせるなら「前提: T1234-A」の行を入れる")
    sub.add_parser("take", help="ユーザーの回答（承認・見送り・問いへの答え）を取り込む")
    p = sub.add_parser("move", help="表にある遷移")
    p.add_argument("stage")
    p.add_argument("to")
    p.add_argument("--reason")
    p.add_argument("--by", help="② の止めている人")
    p.add_argument("--missing", help="② の欠けているもの（ユーザーへの問い、前提の段なら T1234-A）")
    p.add_argument("--review", help="② の見直す日（YYYY-MM-DD）")
    p.add_argument("--choice", action="append", help="ユーザーが押して答える選択肢（繰り返す）")
    sub.add_parser("land", help="出口: ⑤ の段を master へ入れる").add_argument("stage")
    sub.add_parser("ci", help="コミットの CI を待って結論を出す").add_argument("sha")
    sub.add_parser("setup", help="Project の欄を作る gh のコマンドを出す").add_argument("repo")
    sub.add_parser("hook-create")
    sub.add_parser("hook-remove")
    args = parser.parse_args(argv)
    if getattr(args, "stage", None) and not STAGE_RE.match(args.stage):
        parser.error(f"段は T1234-A の形: {args.stage}")
    placed = {"propose": cmd_propose, "take": cmd_take, "move": cmd_move, "land": cmd_land}
    local = {"ci": cmd_ci, "setup": cmd_setup, "hook-create": cmd_hook_create, "hook-remove": cmd_hook_remove}
    try:
        if args.cmd in placed:
            placed[args.cmd](Place(), args)
        else:
            local[args.cmd](args)
    except FlowError as e:
        print(f"[flow] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
