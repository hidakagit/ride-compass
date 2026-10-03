// Claude がステータスを動かす道具（src/move.js）を確かめる。
import assert from "node:assert/strict";
import { test } from "node:test";
import config from "../flow.config.json" with { type: "json" };
import { GitHub } from "../src/github.js";
import { moveTask } from "../src/move.js";
import { fakeGitHub } from "./fake-github.js";

const claimBoth = (gh) => Promise.allSettled(["作る担当の着手", "進行中にする理由: 対話で直す"].map((comment) => moveTask(gh, config, 7, config.working, { comment })));

test("2者がほぼ同時に同じ未着手を引き受けると、片方だけが進行中にし、もう片方は断られて自分のコメントを消す", async () => {
  const state = fakeGitHub({ issue: { number: 7, status: config.todo } });
  const [first, second] = await claimBoth(new GitHub("bot-token"));
  assert.equal(first.status, "fulfilled");
  assert.equal(second.status, "rejected");
  assert.match(second.reason.message, /先に引き受けた/);
  assert.equal(state.issue.status, config.working);
  assert.deepEqual(state.issue.comments.map((c) => c.body.split("\n")[0]), ["作る担当の着手"]);
});

test("進行中から未着手へ戻ったタスクは、前の回の引き受けの印に止められずに引き受け直せる", async () => {
  const state = fakeGitHub({ issue: { number: 7, status: config.todo } });
  const gh = new GitHub("bot-token");
  await claimBoth(gh);
  await moveTask(gh, config, 7, config.todo);
  assert.equal((await claimBoth(gh))[0].status, "fulfilled");
  assert.equal(state.issue.status, config.working);
});
