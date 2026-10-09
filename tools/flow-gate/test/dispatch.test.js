// 約束 19・20・23・25（見回りの判断と状況の更新。src/dispatch.js）を確かめる。設定は架空のもの（fake-github.js: config）を渡し、差し替えるのは
// GitHub（網）だけ。確かめるのは約束の結果（振り出す番号・At risk かどうか・書いたかどうか）。
// ここで見ないもの: 状況の更新の文言・見回りのワークフローの止める（無効・止める時刻。bin/dispatch.js が読む値で決まる）・
// 同じタスクの実行が1本ずつ動くこと（担当のワークフローの concurrency。GitHub の動き）。
import assert from "node:assert/strict";
import { test } from "node:test";
import { pick, putStatus, readActive, ready, summary } from "../src/dispatch.js";
import { GitHub } from "../src/github.js";
import { config, fakeGitHub } from "./fake-github.js";

const task = (number, status, extra = {}) => ({ number, status, blocked: false, labels: [], urgent: false, priority: null, startOn: null, ...extra });
const board = (...tasks) => ({ tasks, ranks: ["上", "並", "下"] });
const now = new Date("2026-10-03T15:30:00Z");

test("19 枠は種類ごと: 上限から動いている数を引いた分だけ上から起こし、貸し借りしない", () => {
  const { 作る: make, 確かめる: check } = config.coordinator.slots;
  const tasks = [...Array.from({ length: make + 2 }, (_, k) => task(100 + k, config.todo)), ...Array.from({ length: check + 2 }, (_, k) => task(200 + k, config.review))];
  const running = [{ number: 1, kind: "確かめる" }];
  const kinds = pick(config, ready(config, board(...tasks), running, now), running).map((t) => t.kind);
  assert.deepEqual([kinds.filter((k) => k === "作る").length, kinds.filter((k) => k === "確かめる").length], [make, check - 1]);
});

test("20 確かめるは検証中を全部、作るは前提が閉じ・開発機のラベルが無く・着手可能日が今日以前の未着手。並びは急ぎ・優先度（空は既定の位置）・番号", () => {
  const dev = config.coordinator.devLabel;
  const tasks = [task(1, config.todo, { blocked: true }), task(2, config.todo, { labels: [dev] }), task(3, config.todo, { startOn: "2026-10-05" }), task(4, config.todo, { startOn: "2026-10-04" }),
    task(5, config.todo, { priority: "下" }), task(6, config.todo, { priority: "上" }), task(7, config.todo, { urgent: true }), task(8, config.review, { blocked: true, labels: [dev] }), task(9, config.working), task(10, config.todo)];
  assert.deepEqual(ready(config, board(...tasks), [{ number: 10, kind: "作る" }], now).map((t) => t.number), [7, 6, 4, 8, 5]);
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

test("23 状況の更新: 進行中なのに動いている担当が無いタスク・仕事があるのに空いた枠・落ちた実行のどれかがあれば At risk。中身が変わったときだけ書く", async () => {
  const tasks = [task(3, config.working), task(4, config.review)];
  const working = { number: 3, kind: "作る", conclusion: null, url: "u0" };
  const base = { watcher: "w", tasks, runs: [working], started: [], waiting: 0, idle: null };
  const failed = [{ number: 4, kind: "確かめる", conclusion: "failure", url: "u2" }, { number: 4, kind: "確かめる", conclusion: "success", url: "u1" }];
  for (const [what, extra, want] of [["無し", {}, "ON_TRACK"], ["進行中の担当が動いていない", { runs: [] }, "AT_RISK"],
    ["動いているのは別の番号", { runs: [{ ...working, number: 4 }] }, "AT_RISK"], ["進行中の担当が終わった", { runs: [{ ...working, conclusion: "success" }] }, "AT_RISK"],
    ["進行中でなければ担当が無くてよい", { tasks: [task(3, config.todo)], runs: [] }, "ON_TRACK"], ["空いた枠", { idle: "止めている" }, "AT_RISK"],
    ["落ちた実行", { runs: [working, ...failed] }, "AT_RISK"], ["落ちた後に通った", { runs: [working, ...failed.toReversed()] }, "ON_TRACK"]])
    assert.equal(summary(config, { ...base, ...extra }).status, want, what);
  const gh = fakeGitHub({ issue: { number: 1 } });
  const calm = summary(config, base);
  const bot = new GitHub("bot-token");
  assert.deepEqual([await putStatus(bot, config, calm), await putStatus(bot, config, calm), await putStatus(bot, config, summary(config, { ...base, idle: "止めている" }))], [true, false, true]);
  assert.equal(gh.updates[0].status, "AT_RISK");
});
