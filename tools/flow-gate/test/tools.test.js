// 約束 18・24（担当の後始末の行き先と手番の記録の置き場。src/after.js: settle・keepLog）を確かめる。設定は架空のもの（fake-github.js: config）を
// 渡し、24 は GitHub（網）だけを差し替える。
// ここで見ないもの: 終わりのコメントの中身（文言で、`bin/after.js --dry-run` が出す姿で見る）・ステータスを動かす道具（src/move.js）は表の照らし
// （rules.js: judge）を呼ぶだけなので、照らしは gate.test.js が見る。
import assert from "node:assert/strict";
import { test } from "node:test";
import { keepLog, settle } from "../src/after.js";
import { GitHub } from "../src/github.js";
import { config } from "./fake-github.js";

test("18 後始末: 上限・認証は戻して振り出しを止め、一時の失敗と起きる前の落ちは戻すだけ、開発機が要るのラベル・着手可能日が先・開いた前提があれば戻し、それ以外は保留", () => {
  const said = (error) => [{ type: "assistant", error }];
  const at = (messages, extra = {}) => settle(config, { messages, startOn: null, labels: [], blockers: [], url: "u", jobStatus: "success", now: new Date("2026-10-03T15:30:00Z"), ...extra });
  assert.deepEqual([at(said("rate_limit")).to, at(said("rate_limit")).pause], [config.todo, true]);
  for (const m of [said("overloaded"), null]) assert.deepEqual([at(m).to, Boolean(at(m).pause)], [config.todo, false]);
  assert.equal(at([], { startOn: "2026-10-05" }).to, config.todo);
  assert.equal(at([], { labels: [config.coordinator.devLabel] }).to, config.todo);
  assert.equal(at([], { blockers: [7] }).to, config.todo);
  assert.equal(at([]).to, config.hold);
  for (const m of [said("rate_limit"), null]) assert.equal(at(m, { jobStatus: "cancelled" }).to, config.hold);
});

test("24 手番の記録: 日ごとのリリースに付き、無ければ作り、並んで作られて作れなければ先に作られたものへ付ける", async () => {
  const at = async (releases, { race = false } = {}) => {
    const uploads = [];
    globalThis.fetch = async (url, init) => {
      const { pathname, searchParams } = new URL(url);
      const found = releases.find((r) => pathname.endsWith(`/tags/${r.tag_name}`));
      if (init.method === "GET") return found ? Response.json(found) : new Response("{}", { status: 404 });
      if (pathname.endsWith("/releases")) {
        const made = { ...JSON.parse(init.body), upload_url: `https://uploads.example/${releases.length}{?name,label}` };
        releases.push(made);
        return race ? new Response("{}", { status: 422 }) : Response.json(made);
      }
      uploads.push({ to: pathname, name: searchParams.get("name"), type: init.headers["content-type"] });
      return Response.json({ browser_download_url: `${url}#dl` });
    };
    await keepLog(new GitHub("bot-token"), config.repository, { gz: new Uint8Array([1]), name: "a.json.gz", now: new Date("2026-10-04T23:00:00Z") });
    return { tags: releases.map((r) => r.tag_name), uploads };
  };
  const day = { tag_name: "turns-2026-10-04", upload_url: "https://uploads.example/day{?name,label}" };
  assert.deepEqual(await at([{ tag_name: "turns-2026-10-03", upload_url: "x" }, day]), { tags: ["turns-2026-10-03", "turns-2026-10-04"], uploads: [{ to: "/day", name: "a.json.gz", type: "application/gzip" }] });
  for (const race of [false, true]) {
    const r = await at([], { race });
    assert.deepEqual([r.tags, r.uploads.map((u) => u.to)], [["turns-2026-10-04"], ["/0"]]);
  }
});
