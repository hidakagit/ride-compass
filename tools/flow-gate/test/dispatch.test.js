// 約束 19・20・23（見回りの判断と状況の更新。src/dispatch.js）を確かめる。差し替えるのは GitHub（網）だけ。
// 確かめるのは約束の結果（振り出す番号・At risk かどうか・書いたかどうか）で、文言は確かめない。
import assert from "node:assert/strict";
import { test } from "node:test";
import config from "../flow.config.json" with { type: "json" };
import { claudeHours, expected, pick, putStatus, ready, summary } from "../src/dispatch.js";
import { GitHub } from "../src/github.js";
import { fakeGitHub } from "./fake-github.js";

const task = (number, status, extra = {}) => ({ number, status, blocked: false, labels: [], urgent: false, priority: null, size: null, startOn: null, claudeHours: 0, ...extra });
const board = (...tasks) => ({ tasks, ranks: ["高", "中", "低"] });
const now = new Date("2026-10-03T15:30:00Z");

test("19 枠は種類ごと: 上限から動いている数を引いた分だけ上から起こし、貸し借りしない", () => {
  const { 作る: make, 確かめる: check } = config.coordinator.slots;
  const tasks = [...Array.from({ length: make + 2 }, (_, k) => task(100 + k, config.todo)), ...Array.from({ length: check + 2 }, (_, k) => task(200 + k, config.review))];
  const running = [{ number: 1, kind: "確かめる" }];
  const kinds = pick(config, ready(config, board(...tasks), running, now), running).map((t) => t.kind);
  assert.deepEqual([kinds.filter((k) => k === "作る").length, kinds.filter((k) => k === "確かめる").length], [make, check - 1]);
});

test("20 確かめるは検証中を全部、作るは前提が閉じ・開発機のラベルが無く・着手可能日が今日以前の未着手。並びは急ぎ・優先度・番号", () => {
  const dev = config.coordinator.devLabel;
  const tasks = [task(1, config.todo, { blocked: true }), task(2, config.todo, { labels: [dev] }), task(3, config.todo, { startOn: "2026-10-05" }), task(4, config.todo, { startOn: "2026-10-04" }),
    task(5, config.todo, { priority: "低" }), task(6, config.todo, { priority: "高" }), task(7, config.todo, { urgent: true }), task(8, config.review, { blocked: true, labels: [dev] }), task(9, config.working), task(10, config.todo)];
  assert.deepEqual(ready(config, board(...tasks), [{ number: 10, kind: "作る" }], now).map((t) => t.number), [7, 6, 5, 4, 8]);
});

test("23 想定は Claude の番の時間（ユーザーの番を除く）の、同じ規模で完成した直近の件の p90", () => {
  const turn = (type, login, at) => ({ __typename: type, assignee: { login }, createdAt: `2026-10-01T${at}:00:00Z` });
  const events = [turn("AssignedEvent", config.claude, "00"), turn("UnassignedEvent", config.claude, "02"), turn("AssignedEvent", config.user, "02"),
    turn("UnassignedEvent", config.user, "10"), turn("AssignedEvent", config.claude, "10")];
  assert.equal(claudeHours(config, events, "2026-10-01T13:00:00Z"), 5);
  const { recent } = config.coordinator;
  const done = Array.from({ length: recent + 10 }, (_, k) => ({ size: "S", closedAt: `2026-08-${String(k + 1).padStart(2, "0")}`, claudeHours: k + 1 }));
  assert.deepEqual(expected(config, [...done, { size: "M", closedAt: "2026-09-01", claudeHours: 7 }]), { S: 11 + Math.floor(0.9 * recent), M: 7 });
});

test("23 状況の更新: 想定を超えた Claude の番のタスク・仕事があるのに空いた枠・落ちた実行のどれかがあれば At risk。中身が変わったときだけ書く", async () => {
  const base = { watcher: "w", tasks: [task(3, config.working, { size: "S", claudeHours: 2 })], expected: { S: 4 }, runs: [], started: [], waiting: 0, idle: null };
  const failed = [{ number: 3, kind: "作る", conclusion: "failure", url: "u2" }, { number: 3, kind: "作る", conclusion: "success", url: "u1" }];
  for (const [what, extra, want] of [["無し", {}, "ON_TRACK"], ["想定超え", { tasks: [task(3, config.working, { size: "S", claudeHours: 5 })] }, "AT_RISK"],
    ["ユーザーの番は数えない", { tasks: [task(3, config.waiting, { size: "S", claudeHours: 9 })] }, "ON_TRACK"], ["空いた枠", { idle: "止めている" }, "AT_RISK"],
    ["落ちた実行", { runs: failed }, "AT_RISK"], ["落ちた後に通った", { runs: failed.toReversed() }, "ON_TRACK"]])
    assert.equal(summary(config, { ...base, ...extra }).status, want, what);
  const gh = fakeGitHub({ issue: { number: 1 } });
  const calm = summary(config, base);
  const bot = new GitHub("bot-token");
  assert.deepEqual([await putStatus(bot, config, calm), await putStatus(bot, config, calm), await putStatus(bot, config, summary(config, { ...base, idle: "止めている" }))], [true, false, true]);
  assert.equal(gh.updates[0].status, "AT_RISK");
});
