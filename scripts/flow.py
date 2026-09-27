"""段の状態を動かす唯一の口。表の意味・欄の初期設定・入口ごとの使い方は docs/conventions/flow.md。

    python scripts/flow.py propose "<題>" --file <判断材料.md> [--task T1234] [--after T1234-A]
    python scripts/flow.py take
    python scripts/flow.py do <段> <遷移> --as <司令塔|担当> [--text …] [--slot N]
    python scripts/flow.py hold <段> <止めている理由> <欠けているもの> --as <司令塔|担当> [--kind … --file … --choice …]
    python scripts/flow.py ask <段|#番号> <種類> "<問いの題>" --file <判断材料.md> [--choice …]
    python scripts/flow.py land <段>
    python scripts/flow.py inventory [--close <棚卸の issue の番号>]

GitHub へはユーザーのトークン（GH_TOKEN か `gh auth token`）で読み書きし、ユーザーを名指す書き込み（問い・棚卸）
だけを道具用のアカウントのトークン（環境変数 FLOW_ASK_TOKEN）で書く。名指しの通知は本人以外が書いたときだけ届く。
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Callable

import httpx
from githubkit import GitHub
from transitions import Machine, MachineError

import worktree_slots

STATES = {"①": "① 提案", "②": "② 保留", "③": "③ 未着手", "④": "④ 進行中", "⑤": "⑤ 検証中", "⑥": "⑥ 完了"}
OPEN = ("①", "②", "③", "④", "⑤")
DONE = "⑥"
USER, COORD, WORKER, TOOL = "ユーザー", "司令塔", "担当", "道具"
BLOCKER = "止めている人"
#: ② へ入ったときの戻り先（① からは承認で入る）。
RETURN = {"①": "③", "③": "③", "④": "③", "⑤": "⑤"}
HOLD_FIELDS = (BLOCKER, "欠けているもの", "戻り先", "見る時機", "最初に止まった日", "持ち越した回数")
#: 止めている理由 → 止めている人（docs/conventions/flow.md「② の止めている人の決め方」）。
HOLD_REASONS = {"前提": COORD, "時機": COORD, "判断": USER, "担当": WORKER}


@dataclass(frozen=True)
class Row:
    trigger: str
    sources: tuple[str, ...]
    dest: str  # "=" は状態を変えない
    roles: tuple[str, ...]  # BLOCKER は欄「止めている人」が指す役割
    inputs: tuple[str, ...] = ()
    when: str | None = None  # 同じ遷移の行き先を選ぶ条件（WHEN）


#: 遷移の表。表に無い遷移・必要な入力が欠けた遷移は、どの入口から来ても断る。
ROWS = (
    Row("承認", ("①",), "③", (USER,), (), "前提が無い"),
    Row("承認", ("①",), "②", (USER,), (), "前提がある"),
    Row("棚卸まで保留", ("①", "②"), "=", (USER,)),
    Row("中止", OPEN, DONE, (USER,), ("理由",)),
    Row("再開", ("②",), "③", (BLOCKER, TOOL), ("答え",), "戻り先が③"),
    Row("再開", ("②",), "⑤", (BLOCKER, TOOL), ("答え",), "戻り先が⑤"),
    Row("NG", ("②",), "③", (USER,), ("理由",), "戻り先が⑤"),
    Row("どれでもない", ("②",), "=", (USER,), ("記述",)),
    Row("着手", ("③",), "④", (COORD,), ("スロット",)),
    Row("止める", ("③", "④", "⑤"), "②", (COORD, WORKER), (BLOCKER, "欠けているもの")),
    Row("検証へ", ("④",), "⑤", (WORKER,), ("作業ブランチ",)),
    Row("差し戻し", ("⑤",), "③", (COORD,), ("理由",)),
    Row("完成", ("⑤",), DONE, (TOOL,), ("CI", "検証", "早送り", "範囲外の行き先")),
    Row("判断できない", OPEN, "=", (USER,), ("質問",)),
)
WHEN: dict[str, Callable[[Any, dict], bool]] = {
    "前提が無い": lambda item, given: not given.get("前提"),
    "前提がある": lambda item, given: bool(given.get("前提")),
    "戻り先が③": lambda item, given: item.code("戻り先") == "③",
    "戻り先が⑤": lambda item, given: item.code("戻り先") == "⑤",
}
CHOICE = "選択肢"


@dataclass(frozen=True)
class Op:
    key: str  # 答えの「選んだもの」。CHOICE は問いの選択肢の番号
    trigger: str
    text: str | None = None  # 答えの「本文」に要る入力の名前


@dataclass(frozen=True)
class Kind:
    materials: tuple[str, ...]  # 問いの判断材料に要る見出し
    ops: tuple[Op, ...]


_DEFER, _CANCEL = Op("棚卸まで保留", "棚卸まで保留"), Op("中止する", "中止", "理由")
_UNSURE = Op("判断できない", "判断できない", "質問")
#: 問いの種類の表。回答ページは問いに書かれた操作だけを出し、道具は答えをこの表で読む。
KINDS = {
    "起票": Kind(("背景", "やること", "なぜ既存に入らないか"), (Op("承認", "承認"), _DEFER, _CANCEL, _UNSURE)),
    "保留の問い": Kind(("いま起きていること", "選択肢ごとの結果", "推奨"),
                   (Op(CHOICE, "再開"), Op("どれでもない", "どれでもない", "記述"), _DEFER, _CANCEL, _UNSURE)),
    "確認": Kind(("何が変わったか", "どこで見るか", "期待する見え方"), (Op("OK", "再開"), Op("NG", "NG", "理由"), _UNSURE)),
    "中止": Kind((), (_CANCEL,)),
}
ASK_TOKEN_ENV = "FLOW_ASK_TOKEN"
NOTE = "〔flow〕"
BLOCK_RE = re.compile(r"<!-- flow\n種類: (\S+)\n(.*?)-->", re.S)
OP_RE = re.compile(r"^操作: (.+?) \| (.+?) \| (.*)$", re.M)
ANSWER_RE = re.compile(r"^種別: ([^\n]+)\n問い: (\S+)\n選んだもの: ([^\n]+)\n本文: ?(.*)$", re.S)
STAGE_RE = re.compile(r"^T\d+-[A-Z]$")
PASSING = ("success", "skipped", "neutral")
#: テストが GitHub の代わりを差し込む口（プロセス境界）。
TRANSPORT: httpx.BaseTransport | None = None

_VALUE = "field { ... on ProjectV2FieldCommon { name } }"
ITEMS_QUERY = f"""query Items($owner: String!, $name: String!, $number: Int!, $after: String, $inv: Boolean!,
 $q: String!) {{ rateLimit {{ cost remaining }} repository(owner: $owner, name: $name) {{ id }}
 search(query: $q, type: ISSUE, first: 1) @include(if: $inv) {{ nodes {{ ... on Issue {{ closedAt }} }} }}
 user(login: $owner) {{ projectV2(number: $number) {{ id
  fields(first: 50) {{ nodes {{ ... on ProjectV2FieldCommon {{ id name dataType }}
   ... on ProjectV2SingleSelectField {{ options {{ id name }} }} }} }}
  items(first: 100, after: $after) {{ pageInfo {{ hasNextPage endCursor }} nodes {{ id
   content {{ ... on Issue {{ id number title body state stateReason
    comments(last: 30) {{ nodes {{ databaseId body createdAt }} }} }} }}
   fieldValues(first: 20) {{ nodes {{ ... on ProjectV2ItemFieldSingleSelectValue {{ name {_VALUE} }}
    ... on ProjectV2ItemFieldTextValue {{ text {_VALUE} }} ... on ProjectV2ItemFieldDateValue {{ date {_VALUE} }}
    ... on ProjectV2ItemFieldNumberValue {{ number {_VALUE} }} }} }} }} }} }} }} }}"""
#: 書き込みの結果として読むもの。無いものは clientMutationId だけを読む。
RESULT = {"createIssue": "issue { id number }", "addProjectV2ItemById": "item { id }"}


class FlowError(Exception):
    pass


class Refused(FlowError):
    """表に無い遷移・入力の欠けた遷移・受け取れない答え。"""


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if r.returncode != 0:
        raise FlowError(f"git {' '.join(args[:2])} が失敗: {(r.stderr or r.stdout).strip()}")
    return r.stdout.strip()


def token(ask: bool = False) -> str:
    """ユーザーのトークン（GH_TOKEN か gh のログイン）。ask なら名指しを書く道具用のアカウントのトークン。"""
    if ask:
        if not os.environ.get(ASK_TOKEN_ENV):
            raise FlowError(f"名指しを書く道具用のアカウントのトークン（環境変数 {ASK_TOKEN_ENV}）が無い")
        return os.environ[ASK_TOKEN_ENV]
    if os.environ.get("GH_TOKEN"):
        return os.environ["GH_TOKEN"]
    gh = shutil.which("gh")
    found = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, check=False).stdout.strip() if gh else ""
    if not found:
        raise FlowError("ユーザーのトークンが無い（GH_TOKEN を置くか gh auth login）")
    return found


def client(secret: str) -> GitHub:
    return GitHub(secret, transport=TRANSPORT, auto_retry=False)


@dataclass
class Item:
    id: str
    issue_id: str
    number: int
    title: str
    body: str
    closed: bool
    reason: str | None
    values: dict[str, Any]
    comments: list[dict] = field(default_factory=list)

    def code(self, name: str) -> str | None:
        """状態の欄（状態・確定状態・戻り先）の値の頭の記号。"""
        value = self.values.get(name)
        return str(value)[0] if value else None

    @property
    def confirmed(self) -> str | None:
        """道具が最後に書いた状態。"""
        return self.code("確定状態")

    @property
    def shown(self) -> str | None:
        """ボードに見えている状態（閉じていれば ⑥）。"""
        return DONE if self.closed else self.code("状態")

    @property
    def stage(self) -> str:
        return str(self.values.get("段") or f"#{self.number}")

    def question(self) -> dict | None:
        """最後の問い（機械で読む部分のあるコメント）。"""
        return next((c for c in reversed(self.comments) if BLOCK_RE.search(c["body"])), None)

    def after_tool(self) -> list[dict]:
        """道具が最後に書いた後のコメント。取り込んだ答えは道具の記録より前になり、二度読まれない。"""
        last = max((i for i, c in enumerate(self.comments) if is_tool(c["body"])), default=-1)
        return self.comments[last + 1:]


def is_tool(body: str) -> bool:
    return body.startswith(NOTE) or bool(BLOCK_RE.search(body))


class Place:
    """仕掛の置き場（git の設定 flow.repo・flow.project・flow.answer）。読むたびに全件を読み直す。"""

    def __init__(self) -> None:
        self.repo = git("config", "--get", "flow.repo")
        self.owner, self.name = self.repo.split("/")
        self.number = int(git("config", "--get", "flow.project"))
        self.answer = git("config", "--get", "flow.answer").rstrip("/")
        self.hub = client(token())
        self.items: list[Item] = []
        self.last_inventory: str | None = None

    def read(self, inventory: bool = False) -> list[Item]:
        """Project の全件を、欄と最近のコメントごと、100件ごとに1回の問い合わせで読む。"""
        items, after = [], None
        q = f"repo:{self.repo} is:issue is:closed in:title 棚卸 sort:created-desc"
        while True:
            data = self.hub.graphql(ITEMS_QUERY, {"owner": self.owner, "name": self.name, "number": self.number,
                                                  "after": after, "inv": inventory, "q": q})
            project = data["user"]["projectV2"]
            self.repo_id, self.project_id = data["repository"]["id"], project["id"]
            self.fields = {f["name"]: f for f in project["fields"]["nodes"] if f}
            if inventory:
                self.last_inventory = next((n["closedAt"] for n in data["search"]["nodes"] if n), None)
            for node in project["items"]["nodes"]:
                issue = node.get("content") or {}
                if "number" in issue:
                    values = {v["field"]["name"]: next(v[k] for k in ("name", "text", "date", "number") if k in v)
                              for v in node["fieldValues"]["nodes"] if v and v.get("field")}
                    items.append(Item(node["id"], issue["id"], issue["number"], issue["title"], issue["body"] or "",
                                      issue["state"] == "CLOSED", issue.get("stateReason"), values,
                                      issue["comments"]["nodes"]))
            page = project["items"]["pageInfo"]
            if not page["hasNextPage"]:
                self.items = items
                return items
            after = page["endCursor"]

    def find(self, ref: str) -> Item:
        self.read()
        found = [i for i in self.items if (f"#{i.number}" == ref if ref.startswith("#") else i.values.get("段") == ref)]
        if len(found) != 1:
            raise FlowError(f"{ref} の段が{len(found)}件ある（1件のはず）")
        return found[0]

    def write(self, ops: list[tuple[str, dict]], ask: bool = False) -> dict:
        """書き込みを1回の問い合わせにまとめる（枠の点数は問い合わせの回数で増える）。"""
        heads = ", ".join(f"$a{i}: {n[0].upper()}{n[1:]}Input!" for i, (n, _) in enumerate(ops))
        body = " ".join(f"a{i}: {n}(input: $a{i}) {{ {RESULT.get(n, 'clientMutationId')} }}"
                        for i, (n, _) in enumerate(ops))
        hub = client(token(ask=True)) if ask else self.hub
        return hub.graphql(f"mutation Write({heads}) {{ {body} }}", {f"a{i}": v for i, (_, v) in enumerate(ops)})

    def set_ops(self, item_id: str, values: dict[str, Any]) -> list[tuple[str, dict]]:
        ops = []
        for name, value in values.items():
            f = self.fields.get(name)
            if not f:
                raise FlowError(f"Project に欄「{name}」が無い（docs/conventions/flow.md「欄の初期設定」）")
            base = {"projectId": self.project_id, "itemId": item_id, "fieldId": f["id"]}
            if value is None:
                ops.append(("clearProjectV2ItemFieldValue", base))
                continue
            if f.get("options"):
                option = next((o["id"] for o in f["options"] if o["name"] == value), None)
                if option is None:
                    raise FlowError(f"欄「{name}」に選択肢「{value}」が無い")
                v: dict[str, Any] = {"singleSelectOptionId": option}
            else:
                kind = {"DATE": "date", "NUMBER": "number"}.get(f["dataType"], "text")
                v = {kind: float(value) if kind == "number" else str(value)}
            ops.append(("updateProjectV2ItemFieldValue", {**base, "value": v}))
        return ops

    def question(self, number: int, kind: str, title: str, text: str, choices: list[str]) -> str:
        """問いの本文。判断材料・選択肢が欠けていれば書く前に断る。"""
        spec = KINDS[kind]
        sections = dict(re.findall(r"^## (.+?)\n(.*?)(?=^## |\Z)", text, re.M | re.S))
        if lack := [h for h in spec.materials if not sections.get(h, "").strip()]:
            raise FlowError(f"判断材料が欠けている: {'・'.join(lack)}（--file に「## 見出し」で書く）")
        wants = any(op.key == CHOICE for op in spec.ops)
        if wants != bool(choices) or (wants and len(choices) < 2):
            raise FlowError(f"「{kind}」の選択肢は{'2つ以上要る' if wants else '持たない'}")
        lines = [f"操作: {i} | {c} | " for i, c in enumerate(choices, 1)]
        lines += [f"操作: {op.key} | {op.key} | {op.text or ''}" for op in spec.ops if op.key != CHOICE]
        return (f"@{self.owner} 問い（{kind}）: {title}\n\n{text.strip()}\n\n<!-- flow\n種類: {kind}\n"
                + "\n".join(lines) + f"\n-->\n\n答える: {self.answer}/answer?issue={number}")


def comment(item: Item, body: str) -> tuple[str, dict]:
    return ("addComment", {"subjectId": item.issue_id, "body": body})


# --- 表での判定（transitions） ----------------------------------------------------

def missing(row: Row, item: Item, given: dict) -> list[str]:
    """表の「必要な入力」のうち欠けているもの。答えは止めている人がユーザーのときだけ要る（表の但し書き）。"""
    return [n for n in row.inputs if not given.get(n) and not (n == "答え" and item.values.get(BLOCKER) != USER)]


class Card:
    """transitions の状態機械が載る1枚。どの行で通ったか・なぜ断ったかを持つ。"""

    trigger: Callable[..., bool]  # transitions が載せる

    def __init__(self) -> None:
        self.row: Row | None = None
        self.refusals: list[str] = []


def admits(row: Row, event: Any) -> bool:
    card, kw = event.model, event.kwargs
    item, actor = kw["item"], kw["actor"]
    if kw["dest"] and row.dest != kw["dest"]:
        return False
    if actor not in row.roles and not (BLOCKER in row.roles and actor == item.values.get(BLOCKER)):
        card.refusals.append(f"「{row.trigger}」は{'・'.join(row.roles)}が行う（{actor}ではない）")
        return False
    if row.when and not WHEN[row.when](item, kw["given"]):
        return False
    if lack := missing(row, item, kw["given"]):
        card.refusals.append("必要な入力が欠けている: " + "・".join(
            n + (f"（{kw['why'][n]}）" if n in kw["why"] else "") for n in lack))
        return False
    card.row = row
    return True


TABLE = [{"trigger": r.trigger, "source": list(r.sources), "dest": r.dest, "conditions": partial(admits, r)}
         for r in ROWS]


def fire(item: Item, trigger: str, actor: str, given: dict, dest: str | None = None,
         why: dict | None = None) -> tuple[Row, str]:
    """表で判定する。通れば（行, 行き先）、通らなければ Refused。GitHub へはまだ書かない。"""
    frm = item.confirmed
    if frm is None:
        raise Refused(f"#{item.number} は道具の段ではない（確定状態が無い）")
    card = Card()
    Machine(model=card, states=list(STATES), initial=frm, transitions=TABLE, auto_transitions=False,
            send_event=True)
    try:
        passed = card.trigger(trigger, item=item, actor=actor, given=given, dest=dest, why=why or {})
    except (MachineError, AttributeError) as e:
        raise Refused(f"{frm} で「{trigger}」は遷移の表に無い") from e
    if not passed or card.row is None:
        raise Refused("・".join(dict.fromkeys(card.refusals)) or f"{frm} で「{trigger}」の条件に合う行が無い")
    return card.row, frm if card.row.dest == "=" else card.row.dest


def effects(place: Place, item: Item, row: Row, to: str, actor: str, given: dict) -> list[tuple[str, dict]]:
    """通った遷移で書くもの（欄・記録のコメント・閉じる）。"""
    frm, t, ops = str(item.confirmed), row.trigger, []
    values: dict[str, Any] = {"確定状態": STATES[to]}
    if to != DONE:
        values["状態"] = STATES[to]
    if t == "承認":
        # 同じ take の次の承認が採番で読むので、読んだ件にも書いておく。
        values["段"] = item.values["段"] = stage = next_stage(place, re.search(r"^タスク: (T\d+)$", item.body, re.M))
        cancel = (f"\n\n中止する: {place.answer}/answer?issue={item.number}&from=body\n\n<!-- flow\n種類: 中止\n"
                  "操作: 中止する | 中止する | 理由\n-->")
        ops.append(("updateIssue", {"id": item.issue_id, "title": f"{stage}: {item.title}", "body": item.body + cancel}))
        given = {**given, BLOCKER: COORD, "欠けているもの": given["前提"]} if to == "②" else given
    if to == "②" and frm != "②":
        values.update({BLOCKER: given[BLOCKER], "欠けているもの": given["欠けているもの"], "見る時機": "すぐ",
                       "戻り先": STATES[RETURN[frm]], "最初に止まった日": dt.date.today().isoformat(),
                       "持ち越した回数": 0})
    if frm == "②" and to != "②":
        values.update(dict.fromkeys(HOLD_FIELDS))
    if t in ("どれでもない", "判断できない"):
        values[BLOCKER] = COORD
    if t == "棚卸まで保留":
        values["見る時機"] = "次の棚卸"
    if to == DONE:
        values["終わり方"] = "完成" if t == "完成" else "中止"
        if not item.closed:
            ops.append(("closeIssue", {"issueId": item.issue_id,
                                       "stateReason": "COMPLETED" if t == "完成" else "NOT_PLANNED"}))
    said = "".join(f"\n{k}: {given[k]}" for k in ("答え", "理由", "記述", "質問", "欠けているもの", "スロット", "作業ブランチ")
                   if given.get(k) and isinstance(given[k], str))
    return [*place.set_ops(item.id, values), comment(item, f"{NOTE} {frm} → {to} {t}（{actor}）{said}"), *ops]


def transition(place: Place, item: Item, trigger: str, actor: str, given: dict, dest: str | None = None,
               why: dict | None = None) -> str:
    if trigger == "承認":
        given = {**given, "前提": prerequisite(place, item)}
    row, to = fire(item, trigger, actor, given, dest, why)
    place.write(effects(place, item, row, to, actor, given))
    print(f"{item.stage}: {item.confirmed} → {to} {trigger}（{actor}）")
    return to


def refuse(place: Place, item: Item, reason: str) -> None:
    """断った入口の跡を確定状態へ戻し（ボードの列・閉じ方）、理由を記録する。"""
    frm, ops = item.confirmed, []
    if frm in OPEN and item.shown != frm:
        ops += place.set_ops(item.id, {"状態": STATES[str(frm)]})
        if item.closed:
            ops.append(("reopenIssue", {"issueId": item.issue_id}))
    if frm == DONE and not item.closed:
        ops.append(("closeIssue", {"issueId": item.issue_id, "stateReason":
                                   "COMPLETED" if item.values.get("終わり方") == "完成" else "NOT_PLANNED"}))
    place.write([*ops, comment(item, f"{NOTE} 断った: {reason}")])
    print(f"{item.stage}: 断った: {reason}", file=sys.stderr)


# --- 入口 ------------------------------------------------------------------------

def next_stage(place: Place, task: re.Match | None) -> str:
    """新しいタスクは記録のファイル名と振った段の最大の番号＋1、段を足すならそのタスクの次の文字。"""
    stages = [str(i.values["段"]) for i in place.items if i.values.get("段")]
    git("fetch", "--quiet", "origin", "master")
    if task is None:
        names = git("ls-tree", "--name-only", "origin/master", "docs/records/tasks/").splitlines()
        numbers = [int(m.group(1)) for n in names + stages if (m := re.match(r"T(\d+)", Path(n).name))]
        return f"T{max(numbers, default=0) + 1}-A"
    subjects = git("log", "--format=%s", "origin/master").splitlines()
    letters = [s[-1] for s in stages if s.startswith(f"{task.group(1)}-")]
    letters += [m.group(1) for s in subjects if (m := re.match(rf"{task.group(1)}(?:-| 段階)([A-Z])\b", s))]
    last = max(letters, default="@")
    if last == "Z":
        raise FlowError(f"{task.group(1)} の段の文字が尽きた")
    return f"{task.group(1)}-{chr(ord(last) + 1)}"


def prerequisite(place: Place, item: Item) -> str | None:
    """本文の「前提:」の段がまだ完成していなければ、その段。"""
    m = re.search(r"^前提: (T\d+-[A-Z])$", item.body, re.M)
    done = m and any(i.values.get("段") == m.group(1) and i.values.get("終わり方") == "完成" for i in place.items)
    return m.group(1) if m and not done else None


def read_answer(item: Item) -> tuple[str, dict] | None:
    """回答ページの答え（種別・問い・選んだもの・本文の行）を、問いの種類の表で遷移と入力へ読む。"""
    answers = [m for c in item.after_tool() if (m := ANSWER_RE.match(c["body"]))]
    if not answers:
        return None
    kind, asked, pick, text = (s.strip() for s in answers[-1].groups())
    expected, choices = f"#{item.number}-本文", []
    if kind != "中止":
        q = item.question()
        block = BLOCK_RE.search(q["body"]) if q else None
        if not q or not block or block.group(1) != kind:
            raise Refused(f"答えの種別「{kind}」に合う問いが無い")
        expected = f"#{item.number}-c{q['databaseId']}"
        choices = [label for key, label, _ in OP_RE.findall(block.group(2)) if key.isdigit()]
    if asked != expected:
        raise Refused(f"古い問い・別の問いへの答え（{asked}。今の問いは {expected}）")
    # 選択肢の番号は、問いに書いた選択肢の数の範囲だけを選択肢として読む。
    key = CHOICE if pick.isdigit() and 0 < int(pick) <= len(choices) else pick
    op = next((o for o in KINDS[kind].ops if o.key == key), None) if kind in KINDS else None
    if op is None:
        raise Refused(f"「{kind}」で選べない操作: {pick}")
    if op.text and not text:
        raise Refused(f"「{pick}」には{op.text}が要る")
    given = {"答え": choices[int(pick) - 1] if op.key == CHOICE else pick}
    return op.trigger, {**given, op.text: text} if op.text else given


def free_text(item: Item) -> str:
    """道具の記録より後に、ユーザーが自由に書いたコメント（ボードの操作の理由）。"""
    return "\n".join(c["body"] for c in item.after_tool() if not ANSWER_RE.match(c["body"]))


def from_board(place: Place, item: Item) -> None:
    """ボードで動かされた（状態・閉じ方が確定状態と食い違う）1枚を、ユーザーの遷移として表で判定する。"""
    given = {"理由": free_text(item), "答え": "ボードで動かした"}
    if item.closed and item.confirmed in OPEN:
        if item.reason != "NOT_PLANNED":
            raise Refused("閉じてよいのは中止（Close as not planned）だけ。完成は道具が閉じる")
        transition(place, item, "中止", USER, given)
        return
    if item.confirmed == DONE:
        raise Refused("⑥ は終点（続きは新しい提案）")
    triggers = dict.fromkeys(r.trigger for r in ROWS if item.confirmed in r.sources and r.dest == item.shown)
    reasons = [f"{item.confirmed} → {item.shown} は遷移の表に無い"] if not triggers else []
    for trigger in triggers:
        try:
            transition(place, item, trigger, USER, given, dest=item.shown)
            return
        except Refused as e:
            reasons.append(str(e))
    raise Refused(" / ".join(reasons))


def cmd_take(place: Place, args: argparse.Namespace) -> None:
    """ユーザーの2つの入口（回答ページの答え・ボードの操作）を1回の読みで取り込む。"""
    for item in place.read():
        if item.confirmed is None or (item.closed and item.confirmed == DONE):
            continue
        try:
            if item.shown != item.confirmed:
                from_board(place, item)
            elif answer := read_answer(item):
                transition(place, item, answer[0], USER, answer[1])
        except Refused as e:
            refuse(place, item, str(e))


def cmd_propose(place: Place, args: argparse.Namespace) -> None:
    for name, value, pattern in (("--task", args.task, r"T\d+"), ("--after", args.after, r"T\d+-[A-Z]")):
        if value and not re.fullmatch(pattern, value):
            raise FlowError(f"{name} の形が違う: {value}")
    token(ask=True)
    text = Path(args.file).read_text(encoding="utf-8")
    place.question(0, "起票", args.title, text, [])
    place.read()
    body = "\n".join(f"{k}: {v}" for k, v in (("タスク", args.task), ("前提", args.after)) if v)
    # 作成・Project への追加・欄の書き込みは、前の結果の id が要るので3回に分かれる。
    issue = place.write([("createIssue", {"repositoryId": place.repo_id, "title": args.title,
                                          "body": body})])["a0"]["issue"]
    added = place.write([("addProjectV2ItemById", {"projectId": place.project_id, "contentId": issue["id"]})])
    item = Item(added["a0"]["item"]["id"], issue["id"], issue["number"], args.title, body, False, None, {})
    place.write(place.set_ops(item.id, {"状態": STATES["①"], "確定状態": STATES["①"], BLOCKER: USER, "見る時機": "すぐ"}))
    place.write([comment(item, place.question(item.number, "起票", args.title, text, []))], ask=True)
    print(f"#{item.number} {args.title}")


def cmd_ask(place: Place, args: argparse.Namespace) -> None:
    """問いを（書き直して）ユーザーへ渡す。状態は変えず、止めている人をユーザーにする。"""
    item = place.find(args.ref)
    if item.confirmed not in ("①", "②"):
        raise FlowError(f"問いを置けるのは ①・② だけ（{item.confirmed}。③〜⑤ から問うなら hold … 判断）")
    body = place.question(item.number, args.kind, args.title, Path(args.file).read_text(encoding="utf-8"),
                          args.choice or [])
    token(ask=True)
    values = {BLOCKER: USER, "見る時機": "すぐ", **({"欠けているもの": args.title} if item.confirmed == "②" else {})}
    place.write(place.set_ops(item.id, values))
    place.write([comment(item, body)], ask=True)


def cmd_hold(place: Place, args: argparse.Namespace) -> None:
    item = place.find(args.stage)
    blocker = HOLD_REASONS.get(args.reason)
    if blocker is None:
        raise FlowError(f"止めている理由は {'・'.join(HOLD_REASONS)} のどれか")
    if args.reason == "前提" and not STAGE_RE.match(args.missing):
        raise FlowError(f"前提で止めるなら、欠けているものは段（T1234-A）: {args.missing}")
    body = None
    if blocker == USER:
        if not args.kind or not args.file:
            raise FlowError("ユーザーが止める ② には問い（--kind 保留の問い|確認 と --file）が要る")
        body = place.question(item.number, args.kind, args.missing, Path(args.file).read_text(encoding="utf-8"),
                              args.choice or [])
        token(ask=True)
    transition(place, item, "止める", args.actor, {BLOCKER: blocker, "欠けているもの": args.missing})
    if body:
        place.write([comment(item, body)], ask=True)


def ahead_commits(stage: str) -> tuple[list[tuple[str, ...]], str | None]:
    """作業ブランチ orch/<段> の、origin/master より先のコミット（sha・件名・本文）と、使えない理由。"""
    try:
        git("fetch", "--quiet", "origin", "master", f"orch/{stage}")
    except FlowError as e:
        return [], str(e)
    out = git("log", "--reverse", "--format=%H%x1f%s%x1f%b%x1e", f"origin/master..origin/orch/{stage}")
    rows = [tuple(r.strip("\n").split("\x1f")) for r in out.split("\x1e") if r.strip()]
    wrong = [s for _, s, _ in rows if not s.startswith(f"{stage}:")]
    if not rows or wrong:
        return rows, f"orch/{stage} に件名が「{stage}:」で始まるコミットだけが要る（{wrong or '先のコミットが無い'}）"
    return rows, None


def cmd_do(place: Place, args: argparse.Namespace) -> None:
    item = place.find(args.stage)
    given: dict[str, Any] = {"理由": args.text, "記述": args.text, "答え": args.text}
    why: dict[str, str] = {}
    if args.slot:
        if any(Path(p).name == f"slot-{args.slot}" for p in worktree_slots.lent()):
            why["スロット"] = f"slot-{args.slot} は貸し出し中"
        else:
            given["スロット"] = f"slot-{args.slot}"
    if args.trigger == "検証へ":
        rows, problem = ahead_commits(args.stage)
        if problem:
            why["作業ブランチ"] = problem
        else:
            given["作業ブランチ"] = rows[-1][0]
    transition(place, item, args.trigger, args.actor, given, why=why)


def out_of_scope(sha: str, stage: str) -> str | None:
    """記録の「範囲外で見つけたもの」の各項目に「行き先:」があるか。無ければ理由。"""
    try:
        text = git("show", f"{sha}:docs/records/tasks/{stage.split('-')[0]}.md")
    except FlowError:
        return None
    lacking = [b for section in re.findall(r"^#+ [^\n]*範囲外[^\n]*\n(.*?)(?=^#|\Z)", text, re.M | re.S)
               for b in re.findall(r"^- (.+)$", section, re.M) if not re.search(r"行き先: ?\S", b)]
    return f"行き先の無い項目: {lacking}" if lacking else None


def code_repo() -> str:
    """本体のリポジトリ（CI の結論を読む先）。origin が GitHub でなければ git の設定 flow.code。"""
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", git("remote", "get-url", "origin"))
    return m.group(1) if m else git("config", "--get", "flow.code")


def cmd_land(place: Place, args: argparse.Namespace) -> None:
    """出口。⑤ の段を、作業ブランチのコミットを書き換えずに master へ入れて閉じる。"""
    item = place.find(args.stage)
    rows, problem = ahead_commits(args.stage)
    needs, sha = ("CI", "検証", "早送り", "範囲外の行き先"), rows[-1][0] if rows else ""
    why: dict[str, str] = dict.fromkeys(needs, problem) if problem else {}
    if not problem:
        if unverified := [s for _, s, body in rows if not re.search(r"^検証:\s*\S", body, re.M)]:
            why["検証"] = f"本文に「検証:」の結果が無いコミット: {unverified}"
        runs = place.hub.request("GET", f"/repos/{code_repo()}/actions/runs",
                                 params={"head_sha": sha}).json()["workflow_runs"]
        if not runs or any(r["status"] != "completed" or r["conclusion"] not in PASSING for r in runs):
            why["CI"] = " / ".join(f"{r['name']}={r['conclusion'] or r['status']}" for r in runs) or "実行が無い"
        try:
            git("merge-base", "--is-ancestor", "origin/master", sha)
        except FlowError:
            why["早送り"] = "master から早送りできない（差し戻して rebase し直す）"
        if scope := out_of_scope(sha, args.stage):
            why["範囲外の行き先"] = scope
    given = {n: True for n in needs if n not in why}
    row, to = fire(item, "完成", TOOL, given, why=why)
    git("push", "--quiet", "origin", f"{sha}:refs/heads/master")
    place.write(effects(place, item, row, to, TOOL, {"答え": sha}))
    print(f"{args.stage}: {sha} を master へ入れた")
    try:
        git("push", "--quiet", "origin", "--delete", f"orch/{args.stage}")
    except FlowError as e:
        print(f"[flow] 作業ブランチを消せなかった: {e}", file=sys.stderr)
    for other in place.read():
        if other.confirmed == "②" and other.values.get("欠けているもの") == args.stage:
            transition(place, other, "再開", TOOL, {"答え": f"前提の {args.stage} が完成した"})


def cmd_inventory(place: Place, args: argparse.Namespace) -> None:
    """棚卸。① ② の全件の変わったことを出し、前提が完成した ② は戻り先へ、ユーザーが決める件は1つの issue で名指す。"""
    if args.close:
        return close_inventory(place, args.close)
    place.read(inventory=True)
    stages, asked = {i.values.get("段"): i for i in place.items}, []
    for item in [i for i in place.items if not i.closed and i.confirmed in ("①", "②")]:
        pre = stages.get(item.values.get("欠けているもの"))
        if item.confirmed == "②" and pre and pre.values.get("終わり方") == "完成":
            transition(place, item, "再開", TOOL, {"答え": f"前提の {pre.stage} が完成した"})
            continue
        since = sum(not is_tool(c["body"]) and c["createdAt"] > (place.last_inventory or "") for c in item.comments)
        line = (f"- #{item.number} {item.title}（{item.confirmed}・止めている人 {item.values.get(BLOCKER, '―')}・"
                f"前提 {f'{pre.stage} {pre.confirmed}' if pre else '―'}・前回からのコメント {since}・"
                f"最初に止まった日 {item.values.get('最初に止まった日', '―')}・"
                f"持ち越し {int(item.values.get('持ち越した回数') or 0)}回）")
        print(line)
        if item.confirmed == "①" or item.values.get(BLOCKER) == USER:
            asked.append(line)
    if asked:
        body = (f"@{place.owner} 棚卸です。続けるなら何もしない、再開はボードで戻り先の列へ、中止は Close as not planned"
                "（理由はコメント）、判断できなければコメントへ。\n\n" + "\n".join(asked))
        issue = place.write([("createIssue", {"repositoryId": place.repo_id, "body": body,
                                              "title": f"棚卸 {dt.date.today().isoformat()}"})], ask=True)
        print(f"棚卸の issue: #{issue['a0']['issue']['number']}")


def close_inventory(place: Place, number: int) -> None:
    """棚卸を閉じる。載せた件のうちまだ ② のものの持ち越した回数を1つ増やす。閉じた日が棚卸の日になる。"""
    issue = place.hub.graphql("query($o: String!, $n: String!, $k: Int!) { repository(owner: $o, name: $n) {"
                              " issue(number: $k) { id body } } }",
                              {"o": place.owner, "n": place.name, "k": number})["repository"]["issue"]
    listed = {int(n) for n in re.findall(r"^- #(\d+) ", issue["body"], re.M)}
    ops = [op for item in place.read() if item.number in listed and item.confirmed == "②" and not item.closed
           for op in place.set_ops(item.id, {"持ち越した回数": int(item.values.get("持ち越した回数") or 0) + 1})]
    place.write([*ops, ("closeIssue", {"issueId": issue["id"], "stateReason": "COMPLETED"})])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flow.py", description="段の状態を動かす唯一の口")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose", help="① の提案を置き、起票の問いを書く")
    p.add_argument("title")
    p.add_argument("--file", required=True, help="判断材料（「## 背景」等の見出しで書く）")
    p.add_argument("--task", help="段を足すタスク（T1234）。無ければ新しいタスク")
    p.add_argument("--after", help="前提の段（T1234-A）")
    sub.add_parser("take", help="回答ページの答えとボードの操作を取り込む")
    p = sub.add_parser("do", help="司令塔・担当の遷移")
    p.add_argument("stage")
    p.add_argument("trigger", choices=sorted({r.trigger for r in ROWS}))
    p.add_argument("--as", dest="actor", required=True, choices=(COORD, WORKER))
    p.add_argument("--text", help="理由など、その遷移に要る文")
    p.add_argument("--slot", type=int, help="着手に使う空いたスロットの番号")
    p = sub.add_parser("hold", help="③〜⑤ を ② へ止める")
    p.add_argument("stage")
    p.add_argument("reason", choices=list(HOLD_REASONS), help="止めている理由")
    p.add_argument("missing", help="欠けているもの（前提なら段、判断なら問いの題）")
    p.add_argument("--as", dest="actor", required=True, choices=(COORD, WORKER))
    p.add_argument("--kind", choices=("保留の問い", "確認"), help="判断で止めるときの問いの種類")
    p.add_argument("--file", help="判断で止めるときの問いの判断材料")
    p.add_argument("--choice", action="append", help="保留の問いの選択肢（2つ以上）")
    p = sub.add_parser("ask", help="①・② の問いを（書き直して）ユーザーへ渡す")
    p.add_argument("ref", help="段か #issue の番号")
    p.add_argument("kind", choices=[k for k in KINDS if k != "中止"])
    p.add_argument("title")
    p.add_argument("--file", required=True, help="判断材料")
    p.add_argument("--choice", action="append", help="保留の問いの選択肢（2つ以上）")
    sub.add_parser("land", help="出口: ⑤ の段を master へ入れる").add_argument("stage")
    p = sub.add_parser("inventory", help="棚卸")
    p.add_argument("--close", type=int, help="閉じる棚卸の issue の番号")
    args = parser.parse_args(argv)
    if getattr(args, "stage", None) and not STAGE_RE.match(args.stage):
        parser.error(f"段は T1234-A の形: {args.stage}")
    commands = {"propose": cmd_propose, "take": cmd_take, "do": cmd_do, "hold": cmd_hold, "ask": cmd_ask,
                "land": cmd_land, "inventory": cmd_inventory}
    try:
        commands[args.cmd](Place(), args)
    except FlowError as e:
        print(f"[flow] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
