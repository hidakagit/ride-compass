// 約束 18（担当の後始末の行き先。src/after.js: settle）を確かめる。設定は架空のもの（fake-github.js: config）を渡す。
// ここで見ないもの: 終わりのコメントの中身（文言で、`bin/after.js --dry-run` が出す姿で見る）・ステータスを動かす道具（src/move.js）は表の照らし
// （rules.js: judge）を呼ぶだけなので、照らしは gate.test.js が見る。
import assert from "node:assert/strict";
import { test } from "node:test";
import { settle } from "../src/after.js";
import { config } from "./fake-github.js";

test("18 後始末: 上限・認証は戻して振り出しを止め、一時の失敗と起きる前の落ちは戻すだけ、着手可能日が先なら戻し、それ以外は保留", () => {
  const said = (error) => [{ type: "assistant", error }];
  const at = (messages, extra = {}) => settle(config, { messages, startOn: null, url: "u", jobStatus: "success", now: new Date("2026-10-03T15:30:00Z"), ...extra });
  assert.deepEqual([at(said("rate_limit")).to, at(said("rate_limit")).pause], [config.todo, true]);
  for (const m of [said("overloaded"), null]) assert.deepEqual([at(m).to, Boolean(at(m).pause)], [config.todo, false]);
  assert.equal(at([], { startOn: "2026-10-05" }).to, config.todo);
  assert.equal(at([]).to, config.hold);
  for (const m of [said("rate_limit"), null]) assert.equal(at(m, { jobStatus: "cancelled" }).to, config.hold);
});
