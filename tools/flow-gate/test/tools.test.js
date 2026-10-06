// 約束 18・24（担当の後始末の行き先と手番の記録の置き場。src/after.js: settle・keepLog）・26（GitHub の一時的な失敗。src/github.js: GitHub）・
// 27（問いの打ち直し。src/move.js: askTask）を確かめる。設定は架空のもの（fake-github.js: config）を渡し、24・26・27 は GitHub（網）だけを差し替える。
// ここで見ないもの: 終わりのコメントの中身（文言で、`bin/after.js --dry-run` が出す姿で見る）・ステータスを動かす道具（src/move.js）の表の照らし
// （rules.js: judge を呼ぶだけなので、照らしは gate.test.js が見る）・打ち直しの回数と間（公式の SDK の既定を写した値で、約束ではない）。
import assert from "node:assert/strict";
import { test } from "node:test";
import { keepLog, settle } from "../src/after.js";
import { GitHub } from "../src/github.js";
import { askTask, moveTask } from "../src/move.js";
import { config, fakeGitHub } from "./fake-github.js";

test("18 後始末: 上限・認証は戻して振り出しを止め、一時の失敗と起きる前の落ちは戻すだけ、開発機が要るのラベル・着手可能日が先・開いた前提があれば戻し、それ以外は保留。作業ブランチの開いた Pull Request があれば、どの終わり方でも検証中", () => {
  const said = (error) => [{ type: "assistant", error }];
  const at = (messages, extra = {}) => settle(config, { messages, startOn: null, labels: [], blockers: [], pullRequest: null, url: "u", jobStatus: "success", now: new Date("2026-10-03T15:30:00Z"), ...extra });
  assert.deepEqual([at(said("rate_limit")).to, at(said("rate_limit")).pause], [config.todo, true]);
  for (const m of [said("overloaded"), null]) assert.deepEqual([at(m).to, Boolean(at(m).pause)], [config.todo, false]);
  assert.equal(at([], { startOn: "2026-10-05" }).to, config.todo);
  assert.equal(at([], { labels: [config.coordinator.devLabel] }).to, config.todo);
  assert.equal(at([], { blockers: [7] }).to, config.todo);
  assert.equal(at([]).to, config.hold);
  for (const m of [said("rate_limit"), null]) assert.equal(at(m, { jobStatus: "cancelled" }).to, config.hold);
  const opened = { pullRequest: { number: 3, html_url: "p" } };
  for (const [m, extra] of [[[], {}], [[], { jobStatus: "cancelled" }], [null, {}], [[], { blockers: [7] }]]) assert.equal(at(m, { ...opened, ...extra }).to, config.review);
  assert.deepEqual([at(said("rate_limit"), opened).to, at(said("rate_limit"), opened).pause], [config.review, true]);
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

test("26 GitHub の一時的な失敗（5xx・接続の失敗・GraphQL の「Something went wrong」）は、読むだけの要求なら打ち直して書き終え、書く要求は打ち直さない", async () => {
  const at = async (fail, { writes = false } = {}) => {
    const gh = fakeGitHub({ issue: { number: 7, status: config.todo } });
    const fake = globalThis.fetch;
    let failed = false;
    globalThis.fetch = async (url, init) => {
      if (failed || JSON.parse(init.body).query.startsWith("mutation") !== writes) return fake(url, init);
      failed = true;
      return fail();
    };
    const done = await moveTask(new GitHub("bot-token"), config, 7, config.working).then(() => true, () => false);
    return [done, gh.issue.status, gh.writes.length];
  };
  const bad = () => new Response("bad gateway", { status: 502 });
  for (const fail of [bad, () => Promise.reject(new TypeError("fetch failed")), () => Response.json({ errors: [{ message: "Something went wrong while executing your query. Please try again." }] })])
    assert.deepEqual(await at(fail), [true, config.working, 1]);
  assert.deepEqual(await at(() => new Response("{}", { status: 404 })), [false, config.todo, 0]);
  assert.deepEqual(await at(bad, { writes: true }), [false, config.todo, 0]);
});

test("27 問いは、答えの無い最新の問いが同じ文なら書き直さずに回答待ちへ動かす: 書いたあとに落ちた打ちを打ち直しても問いは1つ", async () => {
  const question = "## 問い\nどちらにするか";
  const answer = "## 回答\n**どちらにするか**\n\n次のステータス: 前";
  const at = async (status, comments) => {
    const gh = fakeGitHub({ issue: { number: 7, status, comments: comments.map((body) => ({ author: "c", body })) } });
    await askTask(new GitHub("bot-token"), config, 7, question);
    return [gh.issue.status, gh.issue.comments.filter((c) => c.body === question).length];
  };
  assert.deepEqual(await at(config.working, []), [config.waiting, 1]);
  assert.deepEqual(await at(config.working, [question]), [config.waiting, 1]);
  assert.deepEqual(await at(config.waiting, [question]), [config.waiting, 1]);
  assert.deepEqual(await at(config.waiting, ["## 問い\n別の問い"]), [config.waiting, 1]);
  assert.deepEqual(await at(config.todo, [question, answer]), [config.waiting, 2]);
});
