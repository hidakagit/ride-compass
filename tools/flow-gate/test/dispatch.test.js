// 約束 19・20・23・25・35（見回りの判断と状況の更新。src/dispatch.js）を確かめる。設定は架空のもの（fake-github.js: config）を渡し、差し替えるのは
// GitHub（網）だけ。確かめるのは約束の結果（振り出す番号・At risk かどうか・書いたかどうか）。
// ここで見ないもの: 状況の更新の文言・見回りのワークフローの止める（無効・止める時刻。bin/dispatch.js が読む値で決まる）・
// 同じタスクの実行が1本ずつ動くこと（担当のワークフローの concurrency。GitHub の動き）・持つ印を読む・消す git の呼び出し（tools.test.js が見る）。
import assert from "node:assert/strict";
import { test } from "node:test";
import { pick, putStatus, readActive, ready, staleHolds, summary, workload } from "../src/dispatch.js";
import { GitHub } from "../src/github.js";
import { notes } from "../src/rules.js";
import { config, fakeGitHub } from "./fake-github.js";

const task = (number, status, extra = {}) => ({ number, status, blocked: false, labels: [], urgent: false, priority: null, size: null, startOn: null, ...extra });
const board = (...tasks) => ({ tasks, ranks: ["上", "並", "下"] });
const now = new Date("2026-10-03T15:30:00Z");

test("19 枠は種類ごと: 上限から動いている数を引いた分だけ上から起こし、貸し借りしない", () => {
  const { 作る: make, 確かめる: check } = config.coordinator.slots;
  const tasks = [...Array.from({ length: make + 2 }, (_, k) => task(100 + k, config.todo)), ...Array.from({ length: check + 2 }, (_, k) => task(200 + k, config.review))];
  const running = [{ number: 1, kind: "確かめる" }];
  const kinds = pick(config, ready(config, board(...tasks), running, now), running).map((t) => t.kind);
  assert.deepEqual([kinds.filter((k) => k === "作る").length, kinds.filter((k) => k === "確かめる").length], [make, check - 1]);
});

test("20 持つ印・開発機のラベルがあれば作るも確かめるも振り出さず、作るは前提が閉じ・着手可能日が今日以前の未着手だけ。並びは急ぎ・優先度（空は既定の位置）・番号", () => {
  const dev = config.coordinator.devLabel;
  const tasks = [task(1, config.todo, { blocked: true }), task(2, config.todo, { labels: [dev] }), task(3, config.todo, { startOn: "2026-10-05" }), task(4, config.todo, { startOn: "2026-10-04" }),
    task(5, config.todo, { priority: "下" }), task(6, config.todo, { priority: "上" }), task(7, config.todo, { urgent: true }), task(8, config.review, { blocked: true, startOn: "2026-10-05" }), task(9, config.working), task(10, config.todo),
    task(11, config.review, { labels: [dev] }), task(12, config.todo, { held: "開発機 a" }), task(13, config.review, { held: "開発機 a" })];
  assert.deepEqual(ready(config, board(...tasks), [{ number: 10, kind: "作る" }], now).map((t) => t.number), [7, 6, 4, 8, 5]);
});

test("35 担当の印は、その実行がもう動いていなければ残ったものとし、動いていれば・開発機の印なら残ったものにしない", () => {
  const hold = (number, who) => ({ number, sha: `s${number}`, who });
  const holds = [hold(1, "作る https://x/actions/runs/11"), hold(2, "確かめる https://x/actions/runs/12"), hold(3, "開発機 a")];
  assert.deepEqual(staleHolds(config, holds, ["https://x/actions/runs/11"]).map((h) => h.number), [2]);
});

test("25 動いている実行は、終わっていない状態ごとに全部のページを読む: 新しい順の先頭100件より後ろの実行も落とさない", async () => {
  // 新しい順に、終わった150件・前の実行を待つ120件（2ページ）・長く動く1件（全体の271件目）。
  const all = [...Array.from({ length: 150 }, (_, k) => ({ id: k, status: "completed" })), ...Array.from({ length: 120 }, (_, k) => ({ id: 1000 + k, status: "pending" })), { id: 9999, status: "in_progress" }];
  const get = async (path) => {
    const q = new URL(path, "https://api.example").searchParams;
    const [n, p] = [Number(q.get("per_page")), Number(q.get("page"))];
    return { workflow_runs: all.filter((r) => r.status === q.get("status")).slice((p - 1) * n, p * n) };
  };
  assert.deepEqual((await readActive(get, config)).map((r) => r.id).sort((a, b) => a - b), all.filter((r) => r.status !== "completed").map((r) => r.id));
});

test("23 作業時間は作業の状態にいた区間の和で、回答待ち・未着手の待ち・記録の始まりより前の着手は数えない。想定は完成で閉じた同じ規模の直近の件のうち作業時間を持つものの p90。閉じた issue は規模ごとの直近の件がそろうか記録の始まりより前に当たるまでだけ読み、記録は規模を持つ作業の状態のタスクとその直近の件の分だけ読む", async () => {
  const ago = (hours) => new Date(now.getTime() - hours * 3600e3).toISOString();
  const [c, u, gate] = [config.claude, config.user, config.gate];
  const start = (at, kind = "作る") => ({ by: c, at, body: notes.start(kind, "u") });
  const asked = (at) => ({ by: c, at, body: "## 問い\nどうする？" });
  const answered = (at) => ({ by: u, at, body: "## 回答\n**どうする？**\n\n次のステータス: 前" });
  const merged = (at) => [{ by: gate, at, body: notes.pullRequest({ number: 9, title: "題名", html_url: "u" }, "をマージしました。完了にします。") }, { closed: at }];
  const records = {
    1: [start(ago(2))],
    2: [start(ago(10)), { by: c, at: ago(9.9), body: notes.reason(config.todo, "段階に分けた") }], // 段階を待つ親
    3: [{ by: gate, at: ago(40), body: "## 問い\nどうする？" }, answered(ago(31)), start(ago(30)), asked(ago(29.5)), answered(ago(2)), start(ago(1))],
    4: [start(ago(3)), { by: gate, at: ago(2), body: notes.back("表に無い。", config.review) }, start(ago(1), "確かめる")],
    5: [start("2026-09-30T00:00:00Z")],
    6: [start(ago(50))], // 規模が無い
    21: [answered(ago(1.5)), { closed: ago(1) }],
    22: [start(ago(2.5)), { closed: ago(2) }],
    23: [start(ago(4)), { closed: ago(3) }],
    24: [start(ago(5.5)), ...merged(ago(4))],
    // 10:00 着手 → 10:40 問い（40分）、13:05 着手 → 14:10 マージで完了（65分）→ 105分。閉じたあとに更新されて先に読まれるが、
    // 閉じた日が直近 recent 件の外なので数えない。
    25: [start("2026-10-02T10:00:00Z"), asked("2026-10-02T10:40:00Z"), answered("2026-10-02T12:00:00Z"), start("2026-10-02T13:05:00Z"), ...merged("2026-10-02T14:10:00Z")],
  };
  const minutesBefore = (at, k) => new Date(Date.parse(at) - k * 60e3).toISOString();
  // 更新日の新しい順に3ページ（100件ずつ）。1ページ目の終わりまでで S の直近4件がそろい、2ページ目で記録の始まりより前に当たる。
  const closed = [
    { number: 21, size: "S", closedAt: ago(1), updatedAt: ago(0.05) }, // 読む間に更新されて2度出た（番号で1つにする）
    { number: 30, size: "S", closedAt: ago(0.1), project: 9 }, // ほかの Project
    { number: 29, size: "S", closedAt: ago(0.2), stateReason: "NOT_PLANNED" },
    { number: 25, size: "S", closedAt: "2026-10-02T14:10:00Z", updatedAt: ago(0.5) },
    ...[21, 22, 23, 24].map((k) => ({ number: k, size: "S", closedAt: ago(k - 20) })), { number: 27, size: "L", closedAt: ago(1) },
    ...Array.from({ length: 150 }, (_, k) => ({ number: 101 + k, size: "S", closedAt: minutesBefore("2026-10-02T00:00:00Z", k) })),
    { number: 28, size: "S", closedAt: "2026-09-30T00:00:00Z" },
    ...Array.from({ length: 100 }, (_, k) => ({ number: 301 + k, size: "L", closedAt: minutesBefore("2026-09-20T00:00:00Z", k) })),
  ];
  const at = async (open) => {
    const gh = fakeGitHub({ issue: { number: 1 }, records, closed });
    return { load: await workload(new GitHub("bot-token"), config, open, now), pages: gh.closedPages, read: gh.read.toSorted((a, b) => a - b) };
  };
  const open = [task(1, config.working, { size: "S" }), task(2, config.todo, { size: "S" }), task(3, config.working, { size: "S" }), task(4, config.review, { size: "S" }),
    task(5, config.working, { size: "S" }), task(6, config.working)];
  let r = await at(open);
  assert.deepEqual(Object.fromEntries(r.load.tasks.map((t) => [t.number, t.workHours])), { 1: 2, 3: 1.5, 4: 3 });
  assert.deepEqual([r.load.expected, r.pages, r.read], [{ S: 1.5 }, 1, [1, 3, 4, 5, 21, 22, 23, 24]]);
  r = await at([...open, task(7, config.working, { size: "L" })]); // L は1件しか無いので、記録の始まりより前に当たるまで読む
  assert.deepEqual([r.load.expected, r.pages, r.read], [{ S: 1.5 }, 2, [1, 3, 4, 5, 7, 21, 22, 23, 24, 27]]);
  assert.equal((await at([task(2, config.todo, { size: "S" })])).pages, 0); // 作業中の規模つきが無ければ読まない
});

test("23 状況の更新: 想定を超えた作業中のタスク・進行中なのに動いている担当が無いタスク・仕事があるのに空いた枠・落ちた実行のどれかがあれば At risk。中身が変わったときだけ書く", async () => {
  const tasks = [task(3, config.working, { size: "S" }), task(4, config.review)];
  const working = { number: 3, kind: "作る", conclusion: null, url: "u0" };
  const base = { watcher: "w", tasks, working: [{ ...tasks[0], workHours: 2 }], expected: { S: 4 }, runs: [working], started: [], waiting: 0, idle: null };
  const failed = [{ number: 4, kind: "確かめる", conclusion: "failure", url: "u2" }, { number: 4, kind: "確かめる", conclusion: "success", url: "u1" }];
  for (const [what, extra, want] of [["無し", {}, "ON_TRACK"], ["想定超え", { working: [{ ...tasks[0], workHours: 5 }] }, "AT_RISK"],
    ["想定の無い規模は数えない", { working: [{ ...tasks[0], size: "M", workHours: 9 }] }, "ON_TRACK"], ["進行中の担当が動いていない", { runs: [] }, "AT_RISK"],
    ["動いているのは別の番号", { runs: [{ ...working, number: 4 }] }, "AT_RISK"], ["進行中の担当が終わった", { runs: [{ ...working, conclusion: "success" }] }, "AT_RISK"],
    ["進行中でなければ担当が無くてよい", { tasks: [task(3, config.todo)], runs: [] }, "ON_TRACK"], ["空いた枠", { idle: "止めている" }, "AT_RISK"],
    ["落ちた実行", { runs: [working, ...failed] }, "AT_RISK"], ["落ちた後に通った", { runs: [working, ...failed.toReversed()] }, "ON_TRACK"]])
    assert.equal(summary(config, { ...base, ...extra }).status, want, what);
  // 担当の無い進行中のタスクが想定も超えていれば、1行にまとめる。
  const lines = (extra) => summary(config, { ...base, ...extra }).body.split("\n").filter((l) => l.startsWith("- #3"));
  const both = lines({ working: [{ ...tasks[0], workHours: 5 }], runs: [] });
  assert.deepEqual([both.length, /動いている担当が無い.*想定も超えている/.test(both[0])], [1, true]);
  const gh = fakeGitHub({ issue: { number: 1 } });
  const calm = summary(config, base);
  const bot = new GitHub("bot-token");
  assert.deepEqual([await putStatus(bot, config, calm), await putStatus(bot, config, calm), await putStatus(bot, config, summary(config, { ...base, idle: "止めている" }))], [true, false, true]);
  assert.equal(gh.updates[0].status, "AT_RISK");
});
