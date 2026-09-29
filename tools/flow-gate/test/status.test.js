// 司令塔の見張り（src/status.js: watchCoordinator）を、GitHub（網）だけ差し替えて確かめる。
import assert from "node:assert/strict";
import { test } from "node:test";
import config from "../flow.config.json" with { type: "json" };
import { GitHub } from "../src/github.js";
import { watchCoordinator } from "../src/status.js";
import { fakeGitHub } from "./fake-github.js";

const bot = new GitHub("bot-token");
const now = Date.parse("2026-09-30T12:00:00Z");
const ago = (minutes) => new Date(now - minutes * 60000).toISOString();
const stale = config.coordinator.staleMinutes;

test("司令塔の最後の更新が古ければ Off track を足し、もう足してあれば足さない", async () => {
  const gh = fakeGitHub({ issue: { number: 1 }, updates: [{ id: "SU_0", status: "ON_TRACK", body: "様子", by: "hidakagit-bot", updatedAt: ago(stale + 1) }] });
  assert.match(await watchCoordinator(bot, config, now), /Off track を足した/);
  assert.deepEqual(gh.updates.map((u) => [u.status, u.by]), [["OFF_TRACK", "hidakagit-bot"], ["ON_TRACK", "hidakagit-bot"]]);
  assert.match(gh.updates[0].body, /司令塔が最後に起きた時刻: 2026-09-30 18:59/, "最後に起きた時刻は、司令塔の更新の時刻（見張りの Off track ではない）");

  await watchCoordinator(bot, config, now + 60 * 60000);
  assert.equal(gh.updates.length, 2, "止まっている間は、1時間ごとに履歴を増やさない");
});

test("司令塔の最後の更新が新しければ何もしない。そのあとにゲートの失敗があっても、司令塔の時刻で決める", async () => {
  const gh = fakeGitHub({ issue: { number: 1 }, updates: [
    { id: "SU_1", status: "AT_RISK", body: "ゲートの失敗", by: "gate", updatedAt: ago(1) },
    { id: "SU_0", status: "AT_RISK", body: "様子", by: "hidakagit-bot", updatedAt: ago(stale - 1) },
  ] });
  assert.match(await watchCoordinator(bot, config, now), /止まっていない/);
  assert.deepEqual(gh.writes, []);
});
