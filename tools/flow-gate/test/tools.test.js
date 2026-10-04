// Claude の道具の判断（src/move.js・src/after.js）と担当へ渡す設定を確かめる。差し替えるのは GitHub（網）だけ。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import config from "../flow.config.json" with { type: "json" };
import { endReport, settle } from "../src/after.js";
import { GitHub } from "../src/github.js";
import { moveTask } from "../src/move.js";
import { fakeGitHub } from "./fake-github.js";

const bot = new GitHub("bot-token");

test("動かすのは表で照らして通るときだけ。進行中へ入る引き受けは、同じ回に先の印があれば自分の印を消して断る", async () => {
  let gh = fakeGitHub({ issue: { number: 3, status: "保留" } });
  await assert.rejects(moveTask(bot, config, 3, "進行中"), /遷移の表に無い/);
  gh = fakeGitHub({ issue: { number: 3, status: "未着手" } });
  assert.equal(await moveTask(bot, config, 3, "進行中", { comment: "着手" }), "#3: 未着手 → 進行中");
  assert.match(gh.issue.comments[0].body, /^着手\n\n<!-- 引き受け 2026-10-03T00:00:00Z -->$/);
  gh = fakeGitHub({ issue: { number: 3, status: "未着手", comments: [{ author: config.claude, body: "先の者\n\n<!-- 引き受け 2026-10-03T00:00:00Z -->" }] } });
  await assert.rejects(moveTask(bot, config, 3, "進行中", { comment: "後の者" }), /先に引き受けた書き手がいます/);
  assert.deepEqual([gh.issue.status, gh.issue.comments.map((c) => c.body).filter(Boolean).length], ["未着手", 1], "後の者の印は消え、ステータスは動かない");
});

test("後始末: 上限・認証は戻して振り出しを止め、一時の失敗と起きる前の落ちは戻すだけ、着手可能日が先なら戻し、Cancel とそれ以外は保留", () => {
  const said = (error) => [{ type: "assistant", error }];
  const at = (messages, extra = {}) => settle(config, { messages, startOn: null, url: "u", jobStatus: "success", now: new Date("2026-10-03T15:30:00Z"), ...extra });
  assert.deepEqual([at(said("rate_limit")).to, at(said("rate_limit")).pause], [config.todo, true]);
  for (const m of [said("overloaded"), null]) assert.deepEqual([at(m).to, Boolean(at(m).pause)], [config.todo, false]);
  assert.equal(at([], { startOn: "2026-10-05" }).to, config.todo);
  assert.equal(at([]).to, config.hold, "PR も問いも出さずに終わった");
  for (const m of [said("rate_limit"), null]) assert.equal(at(m, { jobStatus: "cancelled" }).to, config.hold, "Cancel・持ち時間切れは担当の側の止まり");
  const report = endReport({ kind: "作る", url: "u", jobStatus: "success", status: "検証中", done: ["a|b"], elapsedMs: 125e3,
    messages: [{ type: "result", result: "最後の発言", num_turns: 3, permission_denials: [{ tool_name: "Bash", tool_input: { command: "git push" } }] }] });
  assert.match(report, /\| 後始末がしたこと \| a\\\|b \|[\s\S]*\| かかった時間（実行の開始から） \| 2分 \|[\s\S]*\| 判定に断られた操作 \| 1件<br>Bash: git push \|[\s\S]*> 最後の発言$/);
});

test("担当へ渡す設定の autoMode の一覧は、どれも既定の規則（$defaults）を残す（書かないと、その一覧の既定の守りを全部捨てる）", () => {
  const { autoMode } = JSON.parse(readFileSync(new URL("../settings.json", import.meta.url), "utf8"));
  for (const [name, list] of Object.entries(autoMode)) assert.ok(list.includes("$defaults"), name);
});
