// 事実からステータスを決める表（src/rules.js: decide）と、問い・答え・本文の形（同じ所の parseQuestion・checkQuestion・parseAnswer・
// takeAnswer・checkBody）を確かめる。GitHub に触れない計算だけで、出来事から事実を読む結線は gate.test.js が見る。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { answerBody, checkBody, checkQuestion, decide, parseAnswer, parseQuestion, takeAnswer } from "../src/rules.js";
import { config } from "./fake-github.js";

const S = config.status;
const now = new Date("2026-10-03T15:30:00Z"); // 日本時間の 2026-10-04 00:30
const conditions = (...lines) => `要約\n\n<details><summary>完了の条件</summary>\n\n${lines.join("\n")}\n</details>`;
const base = { state: "OPEN", status: S.todo, holder: null, unhold: false, released: false, asked: false, adopt: false, pr: null, merged: false,
  body: conditions("- [x] 済んだこと", "- [ ] 作ること"), blocked: false, start: null, now };
const at = (extra) => decide(config, { ...base, ...extra });

test("手放したときの表: 上から最初に当たる行で決まる", () => {
  const rows = [
    ["答えの無い問いがある", { asked: true, pr: { draft: true, ci: "pending" } }, { status: S.waiting }],
    ["下書きの PR で CI が終わっていない", { pr: { draft: true, ci: "pending" } }, { status: S.ci }],
    ["下書きの PR で CI が通った（下書きへ戻されていない）", { pr: { draft: true, ci: "pass" } }, { status: S.ready, ready: true }],
    ["下書きの PR で CI が落ちた", { pr: { draft: true, ci: "fail" } }, { status: S.todo }],
    ["下書きの PR で CI が通ったあとに下書きへ戻された（差し戻し）", { pr: { draft: true, ci: "pass", demoted: true } }, { status: S.todo }],
    ["下書きでない開いた PR", { pr: { draft: false } }, { status: S.ready }],
    ["完了の条件が全部チェック済み", { body: conditions("- [x] a", "- [x] b") }, { status: S.done, close: "COMPLETED" }],
    ["残りが全部ユーザーの確かめ", { body: conditions("- [x] a", `- [ ] ${config.userCheck}: 画面`, `  - [ ] ${config.userCheck}: 地図`) }, { status: S.waiting, ask: "確かめ" }],
    ["開いた前提", { blocked: true }, { status: S.todo }],
    ["未来の着手可能日時", { start: "2026-10-04 00:31" }, { status: S.todo }],
    ["形の合わない着手可能日時", { start: "2026-10-04 0:31" }, { status: S.todo }],
    ["どれでもない手放し", {}, { status: S.waiting, ask: "イレギュラー" }],
    ["どれでもない手放しでも、マージした PR があれば（マージのあとの残り）", { merged: true }, { status: S.todo }],
  ];
  for (const [what, extra, want] of rows) assert.deepEqual(at({ released: true, ...extra }), want, what);
  // 前の行に当たらない形で、各行の境の反対側: 着手可能日時が今ちょうど・前提が閉じた・チェックの無い本文は完了にしない。
  for (const [what, extra] of [["今ちょうどの着手可能日時", { start: "2026-10-04 00:30" }], ["チェックの欄が無い本文", { body: "要約だけ" }]])
    assert.deepEqual(at({ released: true, ...extra }), { status: S.waiting, ask: "イレギュラー" }, what);
});

test("手放し以外のきっかけで、どの行にも当たらなければ未着手（イレギュラーにしない）", () => {
  assert.deepEqual(at({}), { status: S.todo });
});

test("持たれている間は担当の種類で決まり、ほかの事実を見ない。閉じたものは完了", () => {
  assert.deepEqual(at({ holder: "作る", asked: true, pr: { draft: false } }), { status: S.working });
  assert.deepEqual(at({ holder: "確かめる", body: conditions("- [x] a") }), { status: S.review });
  assert.deepEqual(at({ state: "CLOSED", holder: "作る" }), { status: S.done });
});

test("保留はユーザーが出すまで保留のまま。出したら表で決め直す。保留でも担当が持てば担当の種類", () => {
  assert.deepEqual(at({ status: S.hold, pr: { draft: false } }), { status: S.hold });
  assert.deepEqual(at({ status: S.hold, unhold: true, pr: { draft: false } }), { status: S.ready });
  assert.deepEqual(at({ status: S.hold, holder: "作る" }), { status: S.working });
});

test("入口で採否を問うタスクは、まだ問いが無ければ採否の問いを出す", () => {
  assert.deepEqual(at({ adopt: true }), { status: S.waiting, ask: "採否" });
  assert.deepEqual(at({ adopt: false }), { status: S.todo });
});

test("問いは「## 問い（種類）」・問いの文・「### 案」と1行1案・判断材料だけ。種類の無い前の形は判断として読む", () => {
  assert.deepEqual(parseQuestion("## 問い（判断）\nどうする？\n\n### 案\n- A\n- B\n\n<details><summary>判断材料</summary>\n### 見出し\n</details>"),
    { kind: "判断", text: "どうする？", plans: ["A", "B"], material: "### 見出し" });
  assert.equal(parseQuestion("## 問い\nどうする？").kind, "判断");
  assert.equal(parseQuestion("## 問い（確かめ）\n完成にしてよいか").kind, "確かめ");
  for (const bad of ["## 問い（ほか）\nどうする？", "## 問い\n\n### 案\n- A", "## 問い\nどうする？\n補足の行", "## 問い\nどうする？\n\n### 案\n", "## 問い\nどうする？\n\n### 案\n- A\nB"])
    assert.equal(parseQuestion(bad), null, bad);
});

test("担当の問い（判断）は形の節を持つときだけ通り、本物の形は埋めれば通ってそのままでは通らない", () => {
  const ok = "## 問い（判断）\nどうする？\n\n<details><summary>判断材料</summary>\n\n**約束**: 約束\n**案ごと**: A なら…\n**推奨**: A\n</details>";
  assert.deepEqual(checkQuestion(config.questionTemplate, ok), []);
  assert.notDeepEqual(checkQuestion(config.questionTemplate, ok.replace("**案ごと**: A なら…\n", "")), []);
  assert.notDeepEqual(checkQuestion(config.questionTemplate, ok.replace("（判断）", "（確かめ）")), []); // 担当はゲートの種類の問いを出さない
  const template = readFileSync(new URL("../question_template.md", import.meta.url), "utf8");
  assert.deepEqual(checkQuestion(template, template.replace(/<(?![a-z/])[^<>]+>/g, "埋めた")), []);
  assert.notDeepEqual(checkQuestion(template, template), []);
});

test("答え: 書いた答えのコメントを読み戻すと同じ決定と項目になり、確かめのよい項目は本文にチェックが付き、よくない項目は直す行が足される", () => {
  const user = `${config.userCheck}: 画面`;
  const body = conditions("- [x] a", `- [ ] ${user}`, `- [ ] ${config.userCheck}: 地図`);
  const text = answerBody({ question: { text: "完成にしてよいか" }, decision: "続ける", good: [user], bad: [{ item: `${config.userCheck}: 地図`, why: "線が\n切れる" }], note: "" });
  const answer = parseAnswer(text);
  assert.deepEqual(answer, { decision: "続ける", good: [user], bad: [{ item: `${config.userCheck}: 地図`, why: "線が 切れる" }] });
  const after = takeAnswer(body, answer);
  assert.match(after, /- \[x\] 人が見る: 画面\n- \[ \] 人が見る: 地図\n- \[ \] 直す: 線が 切れる\n<\/details>/);
  assert.deepEqual(at({ body: after }), { status: S.todo }); // 直す行があるので確かめの問いに戻らない
  assert.equal(parseAnswer("## 回答\n**問い**\n\n補足: x"), null); // 決定の無いものは答えに数えない
});

test("PR の本文は、テンプレートの節を全部この順で1つずつ持ち、どの節も埋めてあるときだけ通る", () => {
  const template = "背景: <なぜ>\n課題: <何を>\n残り: <何が>\n";
  const rows = [
    ["背景: a\n課題:\n- 足した約束: b\n範囲: c\n残り: なし\n\n🤖 Generated", true], // 節の中の「名前: 」の行と、最後の節のあとの行
    ["背景: a\r\n課題: b\r\n残り: なし\r\n", true], // GitHub の画面から書いた本文
    ["tasks#1。\n背景: a\n課題: b\n残り: なし", false], // 最初の節より前の行
    ["背景: a\n残り: なし", false], // 欠けた節
    ["課題: b\n背景: a\n残り: なし", false], // 違う順
    ["背景: a\n課題: b\n課題: c\n残り: なし", false], // 2度出る節
    ["背景: a\n課題:\n\n残り: なし", false], // 空の節
    ["背景: a\n課題: <何を>\n残り: なし", false], // テンプレートのままの節
  ];
  assert.deepEqual(rows.map(([body]) => checkBody(template, body).length === 0), rows.map(([, ok]) => ok));
});
