// 決め方（src/decide.js）を、tasks#799 の要件の一覧の行ごとに確かめる。行の頭の記号（R3a 等）は要件の一覧の番号。
// 決め方は事実だけから決める: 「担当が手放した」は作業のステータスなのに持たれていないこと、答えは回答待ちで答えがあること。
import assert from "node:assert/strict";
import test from "node:test";
import config from "../flow.config.json" with { type: "json" };
import { decide, dispatchable } from "../src/decide.js";
import { taskOf } from "../src/facts.js";
import { withButton } from "../src/questions.js";

// 担当が手放した直後の、どの行にも当たらないタスク。各行はここから違う事実だけを変える。
const base = { number: 1, open: true, closedAs: null, board: "actions", status: "進行中", type: "不具合", types: ["不具合"], author: config.user, parent: false,
  priority: "中", parentPriority: null, body: "- [ ] テストが通る\n", remaining: ["テストが通る"], assigned: false, blocked: false, future: false, question: null,
  runs: [], pr: null, merged: false, mergeChecks: null, badQuestion: [], closedBy: null };
const f = (more) => ({ ...base, ...more });
const asked = (kind, answer = null) => ({ kind, text: "問い", plans: [], material: "", answer });
const confirmBody = "- [ ] ユーザーが確かめる: A\n";

test("決め方: 事実の組ごとの行き先と、保つ値", () => {
  const rows = [
    // [要件, 事実, 行き先, 違う値]
    ["R2 作る担当が持っている", f({ runs: [{ id: 1, kind: "作る" }] }), "進行中", {}],
    ["R2 確かめる担当が持っている（順番待ちも持つ）", f({ status: "検証待ち", runs: [{ id: 2, kind: "確かめる" }] }), "検証中", {}],
    ["R2 持たれている間は答えがあっても決め直さない", f({ status: "回答待ち", runs: [{ id: 1, kind: "作る" }], question: asked("判断", { decision: "続ける", items: [] }) }), "進行中", {}],
    ["R7 持っているタスクをユーザーが保留へ", f({ status: "保留", runs: [{ id: 7, kind: "作る" }] }), "保留", { cancel: [7], assigned: true }],
    ["R3a 答えの無い問い", f({ question: asked("判断") }), "回答待ち", { assigned: true, button: true }],
    ["R3b 下書きの PR を残した・CI が終わっていない", f({ pr: { draft: true, checks: "PENDING" } }), "CI待ち", {}],
    ["R3b 下書きの PR・検査がまだ無い", f({ pr: { draft: true, checks: null } }), "CI待ち", {}],
    ["R4 CI が通った → レビュー可能にして検証待ち", f({ status: "CI待ち", pr: { draft: true, checks: "SUCCESS" } }), "検証待ち", { ready: true }],
    ["R4 CI が落ちた", f({ status: "CI待ち", pr: { draft: true, checks: "FAILURE" } }), "未着手", {}],
    ["D3 変異テストの新しい生き残り", f({ status: "CI待ち", pr: { draft: true, checks: "SUCCESS", newSurvivors: true } }), "未着手", {}],
    ["R3d・D7 通ったあとに下書きへ戻された（差し戻し）", f({ status: "検証中", pr: { draft: true, checks: "SUCCESS", backToDraft: true } }), "未着手", {}],
    ["R3c 下書きでない開いた PR", f({ pr: { draft: false, checks: "SUCCESS" } }), "検証待ち", {}],
    ["R3c 下書きでなくても、CI が終わるまでは CI待ち", f({ pr: { draft: false, checks: "PENDING" } }), "CI待ち", {}],
    ["R3c 下書きでなくても、CI が落ちたら未着手", f({ pr: { draft: false, checks: "FAILURE" } }), "未着手", {}],
    ["確かめる担当が何も出さずに手放した → イレギュラー", f({ status: "検証中", pr: { draft: false, checks: "SUCCESS" } }), "回答待ち",
      { ask: "イレギュラー", assigned: true, button: true }],
    ["マージのあと、master の CI（デプロイを含む）が終わるまで確かめを問わない", f({ merged: true, mergeChecks: "PENDING", remaining: ["ユーザーが確かめる: A"], body: confirmBody }), "CI待ち", {}],
    ["マージのコミットの CI が終わったら確かめを問う", f({ merged: true, mergeChecks: "SUCCESS", remaining: ["ユーザーが確かめる: A"], body: confirmBody }), "回答待ち",
      { ask: "確かめ", assigned: true, button: true }],
    ["R3e 完了の条件が残っていない", f({ remaining: [] }), "完了", { open: false, closeAs: "COMPLETED" }],
    ["R3f 残りが全部ユーザーの確かめ", f({ remaining: ["ユーザーが確かめる: A"], body: confirmBody }), "回答待ち", { ask: "確かめ", assigned: true, button: true }],
    ["R3g 開いた前提", f({ blocked: true }), "未着手", {}],
    ["R3g 未来の着手可能日時", f({ future: true }), "未着手", {}],
    ["R3h・D1 どれでもない（担当が手放した）", f({}), "回答待ち", { ask: "イレギュラー", assigned: true, button: true }],
    ["D1 マージした PR があればイレギュラーにしない", f({ merged: true }), "未着手", {}],
    ["D1 担当が手放したのでなければイレギュラーにしない", f({ status: "未着手" }), "未着手", {}],
    ["R5 答えで続ける → 表で決め直す", f({ status: "回答待ち", remaining: [], question: asked("判断", { decision: "続ける", items: [] }) }), "完了", { open: false, closeAs: "COMPLETED" }],
    ["R5 答えが保留", f({ status: "回答待ち", question: asked("イレギュラー", { decision: "保留", items: [] }) }), "保留", { assigned: true }],
    ["R12 確かめが全部よい → 印を付けて完了", f({ status: "回答待ち", remaining: ["ユーザーが確かめる: A"], body: confirmBody,
      question: asked("確かめ", { decision: "続ける", items: [{ text: "ユーザーが確かめる: A", ok: true }] }) }), "完了", { open: false, closeAs: "COMPLETED", body: "- [x] ユーザーが確かめる: A\n" }],
    ["D2 確かめによくない → 直す行を足して未着手", f({ status: "回答待ち", remaining: ["ユーザーが確かめる: A"], body: confirmBody,
      question: asked("確かめ", { decision: "続ける", items: [{ text: "A", ok: false, note: "周回にならない" }] }) }), "未着手",
      { body: "- [ ] ユーザーが確かめる: A\n- [ ] 直す: 周回にならない\n" }],
    ["D2 直す行は二度足さない", f({ status: "回答待ち", remaining: ["ユーザーが確かめる: A", "直す: 周回にならない"], body: "- [ ] ユーザーが確かめる: A\n- [ ] 直す: 周回にならない\n",
      question: asked("確かめ", { decision: "続ける", items: [{ text: "A", ok: false, note: "周回にならない" }] }) }), "未着手", { body: "- [ ] ユーザーが確かめる: A\n- [ ] 直す: 周回にならない\n" }],
    ["R6 ユーザーが置いた保留は、ほかの事実で動かさない", f({ status: "保留", remaining: [] }), "保留", { assigned: true }],
    ["D5 ユーザーが保留から出した → 表で決め直す", f({ status: "未着手", blocked: true }), "未着手", {}],
    ["ユーザーが完了へ動かした（条件が残っていても）→ 完成として閉じ、持っている実行を取り消す", f({ status: "完了", runs: [{ id: 3, kind: "作る" }] }), "完了",
      { open: false, closeAs: "COMPLETED", cancel: [3] }],
    ["R9・D4 ユーザーの起票は未着手", f({ status: null, board: null, type: "要望" }), "未着手", {}],
    ["R9・D4 Claude が起こした改善は未着手", f({ status: null, board: null, author: config.claude, type: "保守" }), "未着手", {}],
    ["R9・D4 Claude が起こした段階は未着手", f({ status: null, board: null, author: config.claude, type: "要望", parent: true }), "未着手", {}],
    ["R9・D4 Claude が起こした要望は採否を問う", f({ status: null, board: null, author: config.claude, type: "要望" }), "回答待ち", { ask: "採否", assigned: true, button: true }],
    ["K5 段階は親の優先度を継ぐ", f({ status: null, board: null, parent: true, priority: null, parentPriority: "高" }), "未着手", { priority: "高" }],
    ["ユーザーが条件を残したまま完成で閉じた → 受ける", f({ open: false, closedAs: "COMPLETED", closedBy: config.user }), "完了", { open: false }],
    ["K2 Claude が条件を残したまま完成で閉じた → 開き直す", f({ open: false, closedAs: "COMPLETED", closedBy: config.claude }), "回答待ち", { open: true, ask: "イレギュラー", assigned: true, button: true }],
    ["R6 見送りで閉じた（条件が残っていても）", f({ open: false, closedAs: "NOT_PLANNED" }), "完了", { open: false, closeAs: "NOT_PLANNED" }],
    ["R16 対話作業の種類は、対話作業のボードへ", f({ status: null, board: null, type: config.dialogType, types: [config.dialogType] }), "未着手", { board: "dialog", type: config.dialogType }],
    ["R16 Actions のボードの issue を対話作業へ変えた → 前の種類へ戻す", f({ type: config.dialogType, types: ["保守", config.dialogType] }), "回答待ち",
      { type: "保守", ask: "イレギュラー", assigned: true, button: true }],
    ["R16 対話作業のボードの issue を別の種類へ変えた → 対話作業へ戻す", f({ board: "dialog", status: "未着手", type: "保守", types: [config.dialogType, "保守"] }), "未着手", { board: "dialog", type: config.dialogType }],
    ["R16 境目をまたがない変更は通す", f({ status: "未着手", type: "保守", types: ["不具合", "保守"] }), "未着手", { type: "保守" }],
  ];
  for (const [name, facts, status, more] of rows) {
    const got = decide(facts, config);
    const { button, body, ...rest } = more;
    const want = { board: "actions", type: facts.type, status, open: true, closeAs: facts.closedAs ?? "COMPLETED", ask: null, cancel: [], ready: false, assigned: false,
      priority: facts.priority, ...rest };
    for (const key of Object.keys(want)) assert.deepEqual(got[key], want[key], `${name}（${key}）`);
    const text = body ?? facts.body;
    assert.equal(got.body, button ? withButton(text, config, facts.number) : text, `${name}（本文。ボタンは回答待ちのときだけ）`);
  }
});

test("形に合わない問いには、合わない所を返す（最新のコメントがその問いのときだけ facts が渡す）", () => {
  assert.match(decide(f({ badQuestion: ["判断材料の節が足りない"] }), config).notice, /判断材料の節が足りない/);
  assert.equal(decide(f({}), config).notice, null);
});

test("着手可能日時: 読めない値はまだ先と読む（待つと決めた意図を守る）", () => {
  const item = (text) => [{ id: "I", project: { number: config.boards.actions }, status: null, priority: null, start: text === null ? null : { text } }];
  const now = new Date("2026-10-11T00:00:00+09:00");
  assert.equal(taskOf(config, {}, item("2026-10-12"), now).future, true);
  assert.equal(taskOf(config, {}, item("2026-10-10 09:00"), now).future, false);
  assert.equal(taskOf(config, {}, item("10月12日"), now).future, true);
  assert.equal(taskOf(config, {}, item(null), now).future, false);
});

test("振り出す担当の種類（R14・R17: CI待ちは枠を使わず振り出さない）", () => {
  const rows = [
    [f({ status: "未着手" }), "作る"],
    [f({ status: "検証待ち" }), "確かめる"],
    [f({ status: "CI待ち" }), null],
    [f({ status: "未着手", blocked: true }), null],
    [f({ status: "未着手", future: true }), null],
    [f({ status: "未着手", type: config.dialogType }), null],
    [f({ status: "未着手", runs: [{ id: 1, kind: "作る" }] }), null],
  ];
  for (const [facts, kind] of rows) assert.equal(dispatchable(facts, config), kind, `${facts.status} ${JSON.stringify({ blocked: facts.blocked, future: facts.future, type: facts.type })}`);
});
