// 振り出しの見回りの判断と状況の更新（src/dispatch.js）を、本物の設定で確かめる。
import assert from "node:assert/strict";
import { test } from "node:test";
import config from "../flow.config.json" with { type: "json" };
import { claudeHours, expected, pick, putStatus, ready, summary } from "../src/dispatch.js";
import { GitHub } from "../src/github.js";
import { fakeGitHub } from "./fake-github.js";

const task = (number, status, extra = {}) => ({ number, status, blocked: false, labels: [], urgent: false, priority: null, size: null, startOn: null, claudeHours: 0, ...extra });
const board = (...tasks) => ({ tasks, ranks: ["高", "中", "低"] });
const now = new Date("2026-10-03T15:30:00Z");

test("枠は種類ごと: 上限から動いている数を引いた分だけ上から起こし、貸し借りしない", () => {
  const { 作る: make, 確かめる: check } = config.coordinator.slots;
  const tasks = [...Array.from({ length: make + 2 }, (_, k) => task(100 + k, "未着手")), ...Array.from({ length: check + 2 }, (_, k) => task(200 + k, "検証中"))];
  const running = [{ number: 1, kind: "確かめる" }];
  const kinds = pick(config, ready(config, board(...tasks), running, now), running).map((t) => t.kind);
  assert.deepEqual([kinds.filter((k) => k === "作る").length, kinds.filter((k) => k === "確かめる").length], [make, check - 1]);
});

test("確かめるは検証中を全部、作るは前提が閉じ・開発機のラベルが無く・着手可能日が今日以前の未着手。並びは急ぎ・優先度・番号", () => {
  const dev = config.coordinator.devLabel;
  const tasks = [task(1, "未着手", { blocked: true }), task(2, "未着手", { labels: [dev] }), task(3, "未着手", { startOn: "2026-10-05" }), task(4, "未着手", { startOn: "2026-10-04" }),
    task(5, "未着手", { priority: "低" }), task(6, "未着手", { priority: "高" }), task(7, "未着手", { urgent: true }), task(8, "検証中", { blocked: true, labels: [dev] }), task(9, "進行中"), task(10, "未着手")];
  assert.deepEqual(ready(config, board(...tasks), [{ number: 10, kind: "作る" }], now).map((t) => t.number), [7, 6, 5, 4, 8]);
});

test("想定は、Claude の番の時間（ユーザーの番を除く）の、同じ規模で完成した直近の件の p90", () => {
  const turn = (type, login, at) => ({ __typename: type, assignee: { login }, createdAt: `2026-10-01T${at}:00:00Z` });
  const events = [turn("AssignedEvent", config.claude, "00"), turn("UnassignedEvent", config.claude, "02"), turn("AssignedEvent", config.user, "02"),
    turn("UnassignedEvent", config.user, "10"), turn("AssignedEvent", config.claude, "10")];
  assert.equal(claudeHours(config, events, "2026-10-01T13:00:00Z"), 5);
  const { recent } = config.coordinator;
  const done = Array.from({ length: recent + 10 }, (_, k) => ({ size: "S", closedAt: `2026-08-${String(k + 1).padStart(2, "0")}`, claudeHours: k + 1 }));
  assert.deepEqual(expected(config, [...done, { size: "M", closedAt: "2026-09-01", claudeHours: 7 }]), { S: 11 + Math.floor(0.9 * recent), M: 7 });
});

test("状況の更新: 想定を超えた Claude の番のタスク・空いた枠の理由・一番新しい実行が失敗したタスクがあれば At risk", () => {
  const base = { watcher: "w", tasks: [task(3, "進行中", { size: "S", claudeHours: 2 })], expected: { S: 4 }, runs: [], started: [], waiting: 0, idle: null };
  assert.equal(summary(config, base).status, "ON_TRACK");
  const late = summary(config, { ...base, tasks: [task(3, "進行中", { size: "S", claudeHours: 5 }), task(4, "回答待ち", { size: "S", claudeHours: 9 })] });
  assert.deepEqual([late.status, /#3（S）が想定を超えている: Claude の番の累計 5時間 ／ 想定 4時間/.test(late.body), /#4/.test(late.body)], ["AT_RISK", true, false]);
  assert.match(summary(config, { ...base, idle: "止めている" }).body, /振り出せる仕事があるのに枠が空いている: 止めている/);
  const runs = [{ number: 3, kind: "作る", conclusion: "failure", url: "u2" }, { number: 3, kind: "作る", conclusion: "success", url: "u1" }];
  assert.match(summary(config, { ...base, runs }).body, /#3 の作る担当の実行が失敗で終わった \[実行\]\(u2\)/);
  assert.equal(summary(config, { ...base, runs: runs.toReversed() }).status, "ON_TRACK", "失敗の後に成功していれば出さない");
});

test("状況の更新は、中身が同じなら書かず、状態が同じなら書き換え、状態が変わるかほかの者の更新が最新なら足す", async () => {
  const gh = fakeGitHub({ issue: { number: 1 }, updates: [{ id: "U0", status: "AT_RISK", body: "ほかの者", by: "gate" }] });
  const bot = new GitHub("bot-token");
  const calm = summary(config, { watcher: "w", tasks: [], expected: {}, runs: [], started: [], waiting: 0, idle: null });
  assert.deepEqual([await putStatus(bot, config, calm), await putStatus(bot, config, calm), await putStatus(bot, config, { ...calm, body: `${calm.body}!` }), await putStatus(bot, config, { ...calm, status: "AT_RISK" })], [true, false, true, true]);
  assert.deepEqual(gh.updates.map((u) => [u.status, u.by]), [["AT_RISK", config.claude], ["ON_TRACK", config.claude], ["AT_RISK", "gate"]]);
});
