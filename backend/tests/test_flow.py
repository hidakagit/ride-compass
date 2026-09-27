"""`scripts/flow.py` の遷移の表・問いの種類の表を1行ずつ、3つの入口（道具のコマンド・回答ページの答え・ボード）から通す。

差し替えるのは GitHub（プロセス境界。httpx の MockTransport が GraphQL と Actions の一覧に答える）だけ。git は一時的な
リポジトリの本物を使い、Project の欄は docs/conventions/flow.md「欄の初期設定」の gh のコマンドから作る。
答えは回答ページ（tools/answer-form/worker.js）が書くのと同じ行のコメントで表す。
表の行・種類の操作ごとのテストは表から導いて並べるので、行を足すと、その行を通す場面を書くまで落ちる。
"""

import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import flow  # noqa: E402

FIELD_RE = re.compile(r'gh project field-create \S+ --owner \S+ --name "(.+?)" --data-type (\w+)'
                      r'(?: --single-select-options "(.+?)")?')
LABEL_RE = re.compile(r'gh label create "(.+?)"')
MATERIALS = "".join(f"## {h}\n{h}の中身\n" for kind in flow.KINDS.values() for h in kind.materials)
GREEN = [{"name": "CI", "status": "completed", "conclusion": "success", "html_url": "u"}]
RED = [{"name": "CI", "status": "completed", "conclusion": "failure", "html_url": "u"}]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


class FakeGitHub:
    """GitHub の代わり。道具が投げる問い合わせ（Items・Write・issue 1件）と Actions の実行の一覧に答える。"""

    def __init__(self) -> None:
        doc = (ROOT / "docs" / "conventions" / "flow.md").read_text(encoding="utf-8")
        self.fields = {name: {"id": f"F-{name}", "name": name, "dataType": kind,
                              **({"options": [{"id": f"O-{name}-{o}", "name": o} for o in opts.split(",")]}
                                 if opts else {})}
                       for name, kind, opts in FIELD_RE.findall(doc)}
        self.labels = {name: f"L-{name}" for name in LABEL_RE.findall(doc)}  # 名前 → id
        self.issues: dict[int, dict] = {}
        self.runs: dict[str, list[dict]] = {}
        self.asked: list[int] = []  # 道具用のアカウントのトークンでコメントを書かれた issue

    def issue(self, key: str) -> dict:
        return next(i for i in self.issues.values() if key in (i["id"], i["item"]))

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/actions/runs"):
            return httpx.Response(200, json={"workflow_runs": self.runs.get(request.url.params["head_sha"], [])})
        body = json.loads(request.content)
        query, v, auth = body["query"], body.get("variables", {}), request.headers["authorization"]
        if query.startswith("query Items"):
            return httpx.Response(200, json={"data": self.items(v["inv"])})
        if query.startswith("mutation Write"):
            return httpx.Response(200, json={"data": {a: self.mutate(name, v[a], "ask" in auth)
                                                      for a, name in re.findall(r"(a\d+): (\w+)\(input:", query)}})
        issue = self.issues[v["k"]]
        labels = {"nodes": [{"name": n} for n, i in self.labels.items() if i in issue["labels"]]}
        return httpx.Response(200, json={"data": {"repository": {"issue": {"id": issue["id"], "body": issue["body"],
                                                                           "labels": labels}}}})

    def items(self, inventory: bool) -> dict:
        kind = {"SINGLE_SELECT": "name", "TEXT": "text", "DATE": "date", "NUMBER": "number"}
        nodes = [{"id": i["item"], "content": {k: i[k] for k in ("id", "number", "title", "body", "state", "stateReason")}
                  | {"comments": {"nodes": i["comments"]}},
                  "fieldValues": {"nodes": [{kind[self.fields[n]["dataType"]]: val, "field": {"name": n}}
                                            for n, val in i["values"].items()]}}
                 for i in self.issues.values() if i["item"]]
        label = self.labels.get(flow.INVENTORY_LABEL)
        return {"rateLimit": {"cost": 1, "remaining": 5000},
                "repository": {"id": "R", **({"label": label and {"id": label}} if inventory else {})},
                "user": {"projectV2": {"id": "P", "fields": {"nodes": list(self.fields.values())},
                                       "items": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}},
                **({"search": {"nodes": []}} if inventory else {})}

    def mutate(self, name: str, inp: dict, ask: bool) -> dict:
        """道具が1回にまとめて書く各操作（入力は GitHub の GraphQL の input の形のまま）。"""
        if name == "createIssue":
            n = len(self.issues) + 1
            self.issues[n] = {"id": f"I{n}", "number": n, "title": inp["title"], "body": inp["body"], "state": "OPEN",
                              "stateReason": None, "comments": [], "item": None, "values": {},
                              "labels": inp.get("labelIds", [])}
            return {"issue": {"id": f"I{n}", "number": n}}
        issue = self.issue(next(inp[k] for k in ("itemId", "subjectId", "issueId", "id", "contentId") if k in inp))
        if name == "addProjectV2ItemById":
            issue["item"] = f"P{issue['id']}"
            return {"item": {"id": issue["item"]}}
        if name == "addComment":
            self.comment(issue["number"], inp["body"], ask)
        elif name == "closeIssue":
            issue.update(state="CLOSED", stateReason=inp["stateReason"])
        elif name == "reopenIssue":
            issue.update(state="OPEN", stateReason="REOPENED")
        elif name == "updateIssue":
            issue.update(title=inp["title"], body=inp["body"])
        else:
            f = next(f for f in self.fields.values() if f["id"] == inp["fieldId"])
            if name == "clearProjectV2ItemFieldValue":
                issue["values"].pop(f["name"], None)
            else:
                value = next(iter(inp["value"].values()))
                issue["values"][f["name"]] = next((o["name"] for o in f.get("options", []) if o["id"] == value), value)
        return {}

    def comment(self, number: int, body: str, ask: bool = False) -> None:
        seq = sum(len(i["comments"]) for i in self.issues.values()) + 1
        self.issues[number]["comments"].append({"databaseId": 100 + seq, "body": body,
                                                "createdAt": f"2026-01-01T{seq:08d}"})
        if ask:
            self.asked.append(number)


class World:
    """一時的な git のリポジトリと偽の GitHub の上で、道具を入口から動かす。"""

    def __init__(self, main: Path, fake: FakeGitHub, md: str) -> None:
        self.main, self.fake, self.md = main, fake, md

    def run(self, *args: str) -> int:
        return flow.main(list(args))

    def take(self) -> None:
        assert self.run("take") == 0

    def seed(self, state: str, stage: str = "T6-A", **values: str) -> int:
        """GitHub にもうある段（道具が前に書いた欄を持つ issue）を置き、その番号を返す。"""
        n = self.fake.mutate("createIssue", {"title": f"{stage}: 作業", "body": ""}, False)["issue"]["number"]
        self.fake.mutate("addProjectV2ItemById", {"contentId": f"I{n}"}, False)
        self.fake.issues[n]["values"] = {"状態": flow.STATES[state], "確定状態": flow.STATES[state], "段": stage, **values}
        return n

    def propose(self, *extra: str) -> int:
        assert self.run("propose", "作業", "--file", self.md, *extra) == 0
        return len(self.fake.issues)

    def question(self, kind: str, *choices: str) -> list[str]:
        """hold・ask に渡す問いの引数（判断材料はすべての見出しを持つ）。"""
        return ["--kind", kind, "--file", self.md, *[a for c in choices for a in ("--choice", c)]]

    def answer(self, n: int, kind: str, pick: str, text: str = "", asked: str | None = None) -> None:
        """回答ページが書く答えを置いて取り込む。問いの番号は既定で最後の問い（中止は本文）。"""
        if asked is None:
            last = [c for c in self.fake.issues[n]["comments"] if "<!-- flow" in c["body"]][-1:]
            asked = f"#{n}-本文" if kind == "中止" else f"#{n}-c{last[0]['databaseId']}"
        self.fake.comment(n, f"種別: {kind}\n問い: {asked}\n選んだもの: {pick}\n本文: {text}")
        self.take()

    def state(self, n: int) -> str:
        return str(self.fake.issues[n]["values"].get("確定状態", " "))[0]

    def value(self, n: int, name: str) -> str | None:
        return self.fake.issues[n]["values"].get(name)

    def last(self, n: int) -> str:
        return self.fake.issues[n]["comments"][-1]["body"]

    def commit(self, stage: str, record: str = "# T6\n") -> str:
        """作業ブランチ orch/<段> に段のコミットを積んで push し、sha を返す。"""
        main = self.main
        if git(main, "branch", "--list", f"orch/{stage}"):
            git(main, "switch", "--quiet", f"orch/{stage}")
        else:
            git(main, "switch", "--quiet", "-c", f"orch/{stage}", "origin/master")
        (main / "docs" / "records" / "tasks" / f"{stage[:-2]}.md").write_text(record, encoding="utf-8")
        git(main, "add", ".")
        git(main, "commit", "--quiet", "-m", f"{stage}: 作業が済む", "-m", "検証: pytest → 1 passed")
        git(main, "push", "--quiet", "origin", f"orch/{stage}")
        git(main, "switch", "--quiet", "master")
        return git(main, "rev-parse", f"orch/{stage}")


@pytest.fixture
def w(tmp_path, monkeypatch) -> World:
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
    for key, value in (("repo", "owner/tasks"), ("project", "1"), ("answer", "https://a.example"), ("code", "o/c")):
        git(main, "config", f"flow.{key}", value)
    monkeypatch.setenv("GH_TOKEN", "user")
    monkeypatch.setenv(flow.ASK_TOKEN_ENV, "ask")
    monkeypatch.chdir(main)
    fake = FakeGitHub()
    monkeypatch.setattr(flow, "TRANSPORT", httpx.MockTransport(fake.handler))
    (tmp_path / "m.md").write_text(MATERIALS, encoding="utf-8")
    return World(main, fake, str(tmp_path / "m.md"))


# --- 遷移の表の1行ずつ（通る入口と、必要な入力・役割が欠けたときに断ること） -----------------

ROW_CASES: dict[tuple[str, str], Callable[[World], None]] = {}


def row(trigger: str, dest: str) -> Callable:
    def register(case: Callable[[World], None]) -> Callable[[World], None]:
        ROW_CASES[(trigger, dest)] = case
        return case
    return register


@row("承認", "③")
def _approve(w: World) -> None:
    n = w.propose()
    assert w.fake.asked == [n]  # 起票の問いは道具用のアカウントが書く
    w.answer(n, "起票", "承認")
    assert (w.state(n), w.fake.issues[n]["title"]) == ("③", "T6-A: 作業")
    assert "&from=body" in w.fake.issues[n]["body"]  # ③〜⑤ の中止の口


@row("承認", "②")
def _approve_waiting(w: World) -> None:
    n = w.propose("--after", "T5-A")
    w.answer(n, "起票", "承認")
    assert (w.state(n), w.value(n, "止めている人"), w.value(n, "欠けているもの")) == ("②", "司令塔", "T5-A")
    assert w.value(n, "戻り先") == flow.STATES["③"]


@row("棚卸まで保留", "=")
def _defer(w: World) -> None:
    n = w.propose()
    w.answer(n, "起票", "棚卸まで保留")
    assert (w.state(n), w.value(n, "見る時機")) == ("①", "次の棚卸")


@row("中止", "⑥")
def _cancel(w: World) -> None:
    n = w.seed("④")
    w.answer(n, "中止", "中止する")
    assert w.state(n) == "④" and "理由が要る" in w.last(n)
    w.answer(n, "中止", "中止する", "もう要らない")
    assert (w.state(n), w.value(n, "終わり方"), w.fake.issues[n]["stateReason"]) == ("⑥", "中止", "NOT_PLANNED")


@row("再開", "③")
def _resume(w: World) -> None:
    n = w.seed("②", 止めている人="司令塔", 欠けているもの="冬の前", 戻り先=flow.STATES["③"])
    assert w.run("do", "T6-A", "再開", "--as", "担当") == 1  # 止めている人ではない
    assert w.run("do", "T6-A", "再開", "--as", "司令塔") == 0
    assert (w.state(n), w.value(n, "止めている人"), w.value(n, "戻り先")) == ("③", None, None)


@row("再開", "⑤")
def _resume_checked(w: World) -> None:
    n = w.seed("⑤")
    assert w.run("hold", "T6-A", "判断", "画面を見る", "--as", "司令塔", *w.question("確認")) == 0
    assert w.run("do", "T6-A", "再開", "--as", "司令塔") == 1  # 止めているのはユーザー
    w.answer(n, "確認", "OK")
    assert w.state(n) == "⑤"


@row("NG", "③")
def _ng(w: World) -> None:
    n = w.seed("⑤")
    w.run("hold", "T6-A", "判断", "画面を見る", "--as", "司令塔", *w.question("確認"))
    w.answer(n, "確認", "NG")
    assert w.state(n) == "②" and "理由が要る" in w.last(n)
    w.answer(n, "確認", "NG", "崩れている")
    assert w.state(n) == "③"


@row("どれでもない", "=")
def _none_of_these(w: World) -> None:
    n = w.seed("④")
    w.run("hold", "T6-A", "判断", "どちらで測るか", "--as", "担当", *w.question("保留の問い", "本番", "開発"))
    w.answer(n, "保留の問い", "どれでもない")
    assert w.value(n, "止めている人") == "ユーザー" and "記述が要る" in w.last(n)
    w.answer(n, "保留の問い", "どれでもない", "両方で測る")
    assert (w.state(n), w.value(n, "止めている人")) == ("②", "司令塔")


@row("着手", "④")
def _start(w: World) -> None:
    n = w.seed("③")
    assert w.run("do", "T6-A", "着手", "--as", "司令塔") == 1  # スロットが無い
    assert w.run("do", "T6-A", "着手", "--as", "担当", "--slot", "1") == 1
    assert w.run("do", "T6-A", "着手", "--as", "司令塔", "--slot", "1") == 0 and w.state(n) == "④"


@row("止める", "②")
def _hold(w: World) -> None:
    n, m = w.seed("④"), w.seed("⑤", "T7-A")
    assert w.run("hold", "T6-A", "判断", "どちらで測るか", "--as", "担当") == 1  # 問いが無い
    assert w.run("hold", "T6-A", "判断", "q", "--as", "担当", *w.question("保留の問い", "本番")) == 1  # 選択肢が1つ
    assert w.run("hold", "T6-A", "時機", "冬の前", "--as", "担当") == 0
    assert w.run("hold", "T7-A", "担当", "計測の手順", "--as", "担当") == 0
    assert (w.state(n), w.value(n, "止めている人"), w.value(n, "戻り先")) == ("②", "司令塔", flow.STATES["③"])
    assert (w.state(m), w.value(m, "止めている人"), w.value(m, "戻り先")) == ("②", "担当", flow.STATES["⑤"])


@row("検証へ", "⑤")
def _submit(w: World) -> None:
    n = w.seed("④")
    assert w.run("do", "T6-A", "検証へ", "--as", "担当") == 1  # 作業ブランチが無い
    w.commit("T6-A")
    assert w.run("do", "T6-A", "検証へ", "--as", "担当") == 0 and w.state(n) == "⑤"


@row("差し戻し", "③")
def _send_back(w: World) -> None:
    n = w.seed("⑤")
    assert w.run("do", "T6-A", "差し戻し", "--as", "司令塔") == 1  # 理由が無い
    assert w.run("do", "T6-A", "差し戻し", "--as", "司令塔", "--text", "条件が足りない") == 0 and w.state(n) == "③"


@row("完成", "⑥")
def _land(w: World) -> None:
    n = w.seed("⑤")
    waiting = w.seed("②", "T7-A", 止めている人="司令塔", 欠けているもの="T6-A", 戻り先=flow.STATES["③"])
    w.fake.runs[w.commit("T6-A", "# T6\n\n## 範囲外で見つけたもの\n\n- 古い説明が残る\n")] = GREEN
    assert w.run("land", "T6-A") == 1  # 範囲外の項目に行き先が無い
    sha = w.commit("T6-A", "# T6\n\n## 範囲外で見つけたもの\n\n- 古い説明が残る（行き先: 起票案）\n")
    w.fake.runs[sha] = RED
    assert w.run("land", "T6-A") == 1 and w.state(n) == "⑤"
    w.fake.runs[sha] = GREEN
    assert w.run("land", "T6-A") == 0 and git(w.main, "ls-remote", "origin", "master").split()[0] == sha
    assert (w.state(n), w.value(n, "終わり方"), w.fake.issues[n]["stateReason"]) == ("⑥", "完成", "COMPLETED")
    assert w.state(waiting) == "③"  # 前提が完成したので戻り先へ


@row("判断できない", "=")
def _unsure(w: World) -> None:
    n = w.propose()
    w.answer(n, "起票", "判断できない")
    assert "質問が要る" in w.last(n)
    w.answer(n, "起票", "判断できない", "何を作るのか")
    assert (w.state(n), w.value(n, "止めている人")) == ("①", "司令塔")
    assert w.run("ask", f"#{n}", "起票", "作業", "--file", w.md) == 0  # 司令塔が答えて問いを戻す
    assert w.value(n, "止めている人") == "ユーザー"


@pytest.mark.parametrize("table_row", flow.ROWS, ids=lambda r: f"{'・'.join(r.sources)}→{r.dest} {r.trigger}")
def test_each_row_of_the_transition_table(w, table_row):
    ROW_CASES[(table_row.trigger, table_row.dest)](w)
    fired = [c["body"] for i in w.fake.issues.values() for c in i["comments"]
             if re.match(rf"{flow.NOTE} (.) → (.) {table_row.trigger}（", c["body"])]
    assert fired, f"「{table_row.trigger}」の記録が無い"


# --- 問いの種類の表の1操作ずつ ----------------------------------------------------------------

def asked(w: World, kind: str) -> int:
    """その種類の問いが最後の問いになっている段。"""
    if kind == "起票":
        return w.propose()
    if kind == "中止":
        return w.seed("⑤")
    n = w.seed("⑤" if kind == "確認" else "④")
    choices = ("本番", "開発") if kind == "保留の問い" else ()
    assert w.run("hold", "T6-A", "判断", "問い", "--as", "司令塔", *w.question(kind, *choices)) == 0
    return n


@pytest.mark.parametrize(("kind", "op"), [(k, op) for k, spec in flow.KINDS.items() for op in spec.ops],
                         ids=lambda v: v if isinstance(v, str) else v.key)
def test_each_operation_of_each_question_kind(w, kind, op):
    n = asked(w, kind)
    pick = "1" if op.key == flow.CHOICE else op.key
    if op.text:  # 必須の入力の無い答えは断る
        w.answer(n, kind, pick)
        assert "断った" in w.last(n)
    w.answer(n, kind, pick, "文" if op.text else "")
    assert re.match(rf"{flow.NOTE} . → . {op.trigger}（ユーザー）", w.last(n)), w.last(n)


# --- 入口ごとに断ること -----------------------------------------------------------------------

def test_board_moves_are_judged_by_the_same_table_and_written_back_when_refused(w):
    skipped, by_coordinator = w.seed("③"), w.seed("②", "T7-A", 止めている人="司令塔", 戻り先=flow.STATES["③"])
    by_user = w.seed("②", "T8-A", 止めている人="ユーザー", 戻り先=flow.STATES["③"])
    completed, cancelled = w.seed("④", "T9-A"), w.seed("④", "T11-A")
    reopened = w.seed("⑥", "T10-A", 状態=flow.STATES["⑤"], 終わり方="完成")  # 完成で閉じた後に開けられた
    for n in (skipped, by_coordinator, by_user):
        w.fake.issues[n]["values"]["状態"] = flow.STATES["⑤" if n == skipped else "③"]
    w.fake.issues[completed].update(state="CLOSED", stateReason="COMPLETED")
    w.fake.comment(cancelled, "重複していた")
    w.fake.issues[cancelled].update(state="CLOSED", stateReason="NOT_PLANNED")
    w.take()
    assert w.value(skipped, "状態") == flow.STATES["③"] and "遷移の表に無い" in w.last(skipped)
    # ユーザーはどの ② もボードで再開できる（止めている人が司令塔でも）。役割の違いで断る場面は _resume が持つ
    assert (w.state(by_coordinator), w.value(by_coordinator, "止めている人")) == ("③", None)
    assert w.state(by_user) == "③"
    assert (w.fake.issues[completed]["state"], w.value(completed, "状態")) == ("OPEN", flow.STATES["④"])
    assert (w.fake.issues[reopened]["state"], w.fake.issues[reopened]["stateReason"]) == ("CLOSED", "COMPLETED")
    assert (w.state(cancelled), w.value(cancelled, "終わり方")) == ("⑥", "中止") and "重複していた" in w.last(cancelled)


def test_answers_to_an_old_question_or_of_another_kind_are_refused(w):
    n = w.seed("④")
    w.run("hold", "T6-A", "判断", "どちらで測るか", "--as", "担当", *w.question("保留の問い", "本番", "開発"))
    old = f"#{n}-c{w.fake.issues[n]['comments'][-1]['databaseId']}"
    w.run("ask", "T6-A", "保留の問い", "どちらで測るか", *w.question("保留の問い", "本番", "開発")[2:])
    w.answer(n, "保留の問い", "1", asked=old)
    assert w.state(n) == "②" and "古い問い" in w.last(n)
    w.answer(n, "確認", "OK")
    assert w.state(n) == "②" and "合う問いが無い" in w.last(n)
    w.answer(n, "保留の問い", "3")  # 選択肢は2つ
    assert w.state(n) == "②" and "選べない操作" in w.last(n)


def test_proposals_without_materials_are_refused_before_writing_and_numbers_do_not_collide(w):
    thin = Path(w.md).with_name("薄い.md")
    thin.write_text("## 背景\nx\n", encoding="utf-8")
    assert w.run("propose", "薄い", "--file", str(thin)) == 1 and not w.fake.issues
    proposals = [w.propose(), w.propose(), w.propose("--task", "T5")]
    for n in proposals:
        w.fake.comment(n, f"種別: 起票\n問い: #{n}-c{w.fake.issues[n]['comments'][-1]['databaseId']}\n"
                          "選んだもの: 承認\n本文: ")
    w.take()  # 1回の取り込みで3件を承認しても番号が重ならない。段を足す提案は master の件名の次の文字
    assert [w.fake.issues[n]["title"] for n in proposals] == ["T6-A: 作業", "T7-A: 作業", "T5-C: 作業"]


def test_inventory_names_the_user_once_and_closing_carries_the_holds_over(w):
    held = w.seed("②", 止めている人="ユーザー", 欠けているもの="どちらで測るか", 戻り先=flow.STATES["③"])
    w.seed("②", "T7-A", 止めている人="司令塔", 欠けているもの="冬の前", 戻り先=flow.STATES["③"])
    assert w.run("inventory") == 0
    sheet = max(w.fake.issues)
    assert w.fake.issues[sheet]["labels"] == [w.fake.labels[flow.INVENTORY_LABEL]]  # 棚卸はラベルで見分ける
    assert w.fake.issues[sheet]["body"].startswith("@owner")
    assert f"- #{held} " in w.fake.issues[sheet]["body"] and "- #2 " not in w.fake.issues[sheet]["body"]
    assert w.run("inventory", "--close", str(held)) == 1  # ラベルの無い issue は棚卸として閉じない
    assert w.run("inventory", "--close", str(sheet)) == 0
    assert (w.value(held, "持ち越した回数"), w.fake.issues[sheet]["state"]) == (1.0, "CLOSED")
    w.fake.labels.clear()  # 置き場にラベルが無ければ、棚卸の issue を作る前に断る
    before = len(w.fake.issues)
    assert w.run("inventory") == 1 and len(w.fake.issues) == before


def test_table_shows_every_row_and_every_kind(capsys):
    assert flow.main(["table"]) == 0
    out = capsys.readouterr().out.splitlines()
    for row in flow.ROWS:
        dest = "状態を変えない" if row.dest == "=" else row.dest
        assert any(line.startswith(f"| {row.trigger} | {'・'.join(row.sources)} | {dest} | ") and row.does in line
                   for line in out), row
    kinds = out[out.index("## 問いの種類の表"):]  # 遷移の表にも同じ語（中止）の行がある
    for kind, spec in flow.KINDS.items():
        line = next(line for line in kinds if line.startswith(f"| {kind} | "))
        assert all(op.key in line or op.key == flow.CHOICE for op in spec.ops) and all(m in line for m in spec.materials)
    for name in {n for row in flow.ROWS for n in row.inputs}:
        assert any(line.startswith(f"| {name} | ") for line in out), name
    for reason, hold in flow.HOLD_REASONS.items():
        assert f"| {reason} | {hold.blocker} | {hold.missing} | {hold.moves} |" in out


def test_slots_are_lent_once_and_kept_while_work_would_be_lost(w):
    def hook(command: str, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "worktree_slots.py"), command], cwd=w.main,
                              input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8")

    lent = [Path(hook("create", {"name": "担当"}).stdout.strip()) for _ in range(4)]
    assert len(set(lent)) == 4 and hook("create", {"name": "担当"}).returncode == 1
    (lent[0] / "作業中.txt").write_text("x", encoding="utf-8")
    hook("remove", {"worktree_path": str(lent[0])})
    assert hook("create", {"name": "担当"}).returncode == 1
    (lent[0] / "作業中.txt").unlink()
    hook("remove", {"worktree_path": str(lent[0])})
    assert Path(hook("create", {"name": "次"}).stdout.strip()) == lent[0]
