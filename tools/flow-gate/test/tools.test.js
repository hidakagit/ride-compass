// 約束 12・18・24（ステータスを動かす道具と引き受け・担当の後始末）を確かめる。差し替えるのは GitHub（網）だけ。
// 確かめるのは約束の結果で、文言は確かめない。
import assert from "node:assert/strict";
import { test } from "node:test";
import config from "../flow.config.json" with { type: "json" };
import { settle } from "../src/after.js";
import { GitHub } from "../src/github.js";
import { moveTask } from "../src/move.js";
import { fakeGitHub } from "./fake-github.js";

const bot = new GitHub("bot-token");
const marks = (gh) => gh.issue.comments.filter((c) => c.body !== null).length;

test("12・24 ステータスは表で照らして通るときだけ動く。進行中へ入る引き受けは、ほぼ同時に2者が来ても1者だけが通る", async () => {
  let gh = fakeGitHub({ issue: { number: 3, status: config.hold } });
  await assert.rejects(moveTask(bot, config, 3, config.working));
  assert.equal(gh.issue.status, config.hold);
  gh = fakeGitHub({ issue: { number: 3, status: config.todo } });
  await moveTask(bot, config, 3, config.working, { comment: "着手" });
  assert.deepEqual([gh.issue.status, marks(gh)], [config.working, 1]);
  gh = fakeGitHub({ issue: { number: 3, status: config.todo } });
  const both = await Promise.allSettled([moveTask(bot, config, 3, config.working, { comment: "先の者" }), moveTask(bot, config, 3, config.working, { comment: "後の者" })]);
  assert.deepEqual([both.map((r) => r.status), gh.issue.status, marks(gh)], [["fulfilled", "rejected"], config.working, 1], "同時に来ても通るのは1者で、後の者の印は消える");
});

test("18 後始末: 上限・認証は戻して振り出しを止め、一時の失敗と起きる前の落ちは戻すだけ、着手可能日が先なら戻し、それ以外は保留", () => {
  const said = (error) => [{ type: "assistant", error }];
  const at = (messages, extra = {}) => settle(config, { messages, startOn: null, url: "u", jobStatus: "success", now: new Date("2026-10-03T15:30:00Z"), ...extra });
  assert.deepEqual([at(said("rate_limit")).to, at(said("rate_limit")).pause], [config.todo, true]);
  for (const m of [said("overloaded"), null]) assert.deepEqual([at(m).to, Boolean(at(m).pause)], [config.todo, false]);
  assert.equal(at([], { startOn: "2026-10-05" }).to, config.todo);
  assert.equal(at([]).to, config.hold);
  for (const m of [said("rate_limit"), null]) assert.equal(at(m, { jobStatus: "cancelled" }).to, config.hold);
});
