// 道具の部品を確かめる: 後始末（src/after.js: pauseOf・keepLog）・GitHub の一時的な失敗（src/github.js: GitHub）・担当の問い（src/ask.js: askTask）・
// 段階を作る（src/github.js: createStage）・移行の準備（src/prepare.js: prepare）・画像の貼り方（src/attach.js: attach）・試しを持たない道具は --dry-run を断る（bin/cli.js: args）・
// 着手可能日時の欄へ書く値の形（src/github.js: setField）。設定は架空のもの（fake-github.js: config）を渡し、GitHub（網）か gh を打つ口だけを
// 差し替える。試しの確かめは本物の道具を別のプロセスで打つ。
// ここで見ないもの: 終わりのコメントの中身（文言で、`bin/after.js --dry-run` が出す姿で見る）・打ち直しの回数と間（公式の SDK の既定を写した値で、
// 約束ではない）・道具（bin/attach.js）が打つ gh・本物のテンプレート（.github/pull_request_template.md）と照らしの食い違い（
// .github/workflows/claude-gate.yml の flow-gate が、PR の本文に bin/pr-body.js を打って落とす）・問いを受けたゲートのステータス（gate.test.js）。
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { keepLog, pauseOf } from "../src/after.js";
import { askTask } from "../src/ask.js";
import { attach } from "../src/attach.js";
import { createStage, GitHub, readTask, setField } from "../src/github.js";
import { prepare } from "../src/prepare.js";
import { config, fakeGitHub } from "./fake-github.js";

test("後始末: Cancel されずに利用の上限・認証で止まったときだけ振り出しを止める", () => {
  const said = (error) => [{ type: "assistant", error }];
  const rows = [[said("rate_limit"), "success", "rate_limit"], [said("authentication_failed"), "failure", "authentication_failed"], [said("overloaded"), "failure", null],
    [null, "failure", null], [said("rate_limit"), "cancelled", null]];
  assert.deepEqual(rows.map(([m, job]) => pauseOf(m, job)), rows.map(([, , want]) => want));
});

test("手番の記録: 日ごとのリリースに付き、無ければ作り、並んで作られて作れなければ先に作られたものへ付ける", async () => {
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

const Q = "## 問い（判断）\nどちらにするか\n\n<details><summary>判断材料</summary>\n\n**約束**: 約束\n**案ごと**: 案なし\n**推奨**: こうする\n</details>";

test("GitHub の一時的な失敗（5xx・接続の失敗・GraphQL の「Something went wrong」）は、読むだけの要求なら打ち直して書き終え、書く要求は打ち直さない", async () => {
  const at = async (fail, { writes = false } = {}) => {
    const gh = fakeGitHub({ issues: [{ number: 7, status: config.status.working }] });
    const fake = globalThis.fetch;
    let failed = false;
    globalThis.fetch = async (url, init) => {
      if (failed || JSON.parse(init.body).query.startsWith("mutation") !== writes) return fake(url, init);
      failed = true;
      return fail();
    };
    const done = await askTask(new GitHub("bot-token"), config, 7, Q).then(() => true, () => false);
    return [done, gh.writes.length > 0];
  };
  const bad = () => new Response("bad gateway", { status: 502 });
  for (const fail of [bad, () => Promise.reject(new TypeError("fetch failed")), () => Response.json({ errors: [{ message: "Something went wrong while executing your query. Please try again." }] })])
    assert.deepEqual(await at(fail), [true, true]);
  assert.deepEqual(await at(() => new Response("{}", { status: 404 })), [false, false]);
  assert.deepEqual(await at(bad, { writes: true }), [false, false]);
});

test("担当の問いは、形に合わなければ何も書かずに断り、本文の頭にボタンを書いてから問いを書く。答えの無い最新の問いが同じ文なら書き直さない", async () => {
  const at = async (comments, asked = Q) => {
    const gh = fakeGitHub({ issues: [{ number: 7, status: config.status.working, comments: comments.map((body) => ({ author: "c", body })) }] });
    const done = await askTask(new GitHub("bot-token"), config, 7, asked).then(() => true, () => false);
    const ops = gh.writes.map((w) => w.op);
    return { done, questions: gh.issue.comments.filter((c) => c.body === Q).length, ops, status: gh.issue.status,
      button: gh.issue.body.includes(`](${config.urls.form}/answer?issue=7)`) };
  };
  assert.deepEqual(await at([], "## 問い（判断）\nどちらにするか"), { done: false, questions: 0, ops: [], status: config.status.working, button: false });
  assert.deepEqual(await at([]), { done: true, questions: 1, ops: ["updateIssue", "addComment"], status: config.status.working, button: true });
  assert.deepEqual((await at([Q])).questions, 1);
  assert.deepEqual((await at([Q, "## 回答\n**どちらにするか**\n\n決定: 続ける"])).questions, 2);
});

test("段階は親の子として作り、前の段階を段階の前提に、段階を親の前提に張る。対話作業の段階は対話作業の種類で作る", async () => {
  const gh = fakeGitHub({ issues: [{ number: 5, type: "要" }, { number: 6 }] });
  const bot = new GitHub("bot-token");
  const parent = (await readTask(bot, config, { number: 5 })).issue;
  const earlier = (await readTask(bot, config, { number: 6 })).issue;
  const stage = await createStage(bot, config, parent, { title: "段", body: "本文", before: [earlier], dialog: true });
  const blocks = gh.writes.filter((w) => w.op === "addBlockedBy").map((w) => [w.issueId, w.blockingIssueId]);
  assert.deepEqual([gh.created[0].issueTypeId, gh.created[0].parentIssueId, blocks], [`T:${config.dialog.type}`, "I5", [[`I${stage.number}`, "I6"], ["I5", `I${stage.number}`]]]);
  await createStage(bot, config, parent, { title: "段", body: "本文" });
  assert.equal(gh.created[1].issueTypeId, "T:要");
});

test("画像は1枚ずつ貼り、貼れなければそこで止まって、それまでに貼った分を知らせる", () => {
  const at = (replies) => {
    const calls = [];
    const run = (a) => (calls.push(a.at(-1)), replies.shift() ?? { status: 0, stdout: `https://github.com/c/${calls.length}\n`, stderr: "" });
    try {
      return { calls, said: attach({ run, code: config.code.repository, pr: 3, images: ["a.png#前", "b.png#後", "c.png#横"] }) };
    } catch (e) {
      return { calls, error: e.message };
    }
  };
  assert.deepEqual(at([]), { calls: ["a.png#前", "b.png#後", "c.png#横"], said: ["前: https://github.com/c/1", "後: https://github.com/c/2", "横: https://github.com/c/3"] });
  const r = at([{ status: 0, stdout: "https://github.com/c/1\n", stderr: "" }, { status: 1, stdout: "", stderr: "HTTP 502" }]);
  assert.deepEqual(r.calls, ["a.png#前", "b.png#後"]);
  assert.match(r.error, /b\.png#後 を貼れなかった（HTTP 502）\n貼った: 前: https:\/\/github.com\/c\/1/);
});

test("試しを持たない道具は --dry-run を断り、書かずに 1 で終える。試しを持つ道具は --dry-run を断らない", (t) => {
  // 道具は bin/ のうち bin/cli.js を読むもの（本物の GitHub か手元の設定へ書く。cli.js は共通の部分で、GitHub に触れず書かない
  // pr-body.js は読まない）。試しを持つかは、使い方の1行に `[--dry-run]` を書くか。
  const bin = new URL("../bin/", import.meta.url);
  const tools = readdirSync(bin).filter((f) => f !== "cli.js").map((f) => [f, readFileSync(new URL(f, bin), "utf8")])
    .filter(([, src]) => src.includes('from "./cli.js"')).map(([f, src]) => [f, src.includes("[--dry-run]")]);
  assert.deepEqual([tools.some(([, dry]) => dry), tools.some(([, dry]) => !dry)], [true, true]);
  // 断り損ねても本物へ書かないよう、トークンは通らない値にし、ホーム（~/.claude/settings.json の置き場）は一時の場所にする
  // （gh auth token も GH_TOKEN を返す）。試しを持つ道具は、引数が使い方に合わないので断らずに使い方（2）で終わる（ここで書かずに止める）。
  const home = mkdtempSync(join(tmpdir(), "flow-gate-home-"));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  const env = { ...process.env, FLOW_BOT_TOKEN: "invalid", GH_TOKEN: "invalid", HOME: home, USERPROFILE: home };
  for (const [tool, dry] of tools) {
    const r = spawnSync(process.execPath, [fileURLToPath(new URL(tool, bin)), "--dry-run", "x", "y", "z", "w", "v", "u"], { encoding: "utf8", env });
    assert.deepEqual([tool, r.status, /試し（--dry-run）を持たないので/.test(r.stderr)], [tool, dry ? 2 : 1, !dry]);
  }
});

test("着手可能日時の欄へは、日本時間の YYYY-MM-DD HH:MM か YYYY-MM-DD（00:00 にそろえる）だけを書き、形の合わない日時は書かずに断る", async () => {
  const field = config.project.startField;
  const at = async (value) => {
    const gh = fakeGitHub({ issues: [{ number: 7, status: config.status.todo }] });
    const github = new GitHub("bot-token");
    const { project, issue } = await readTask(github, config, { number: 7 });
    const done = await Promise.resolve().then(() => github.write([setField(project, issue.item, field, value)])).then(() => true, (e) => /YYYY-MM-DD HH:MM/.test(e.message) && "断った");
    return [done, gh.issue.fields[field] ?? null];
  };
  assert.deepEqual(await at("2026-10-11 06:30"), [true, "2026-10-11 06:30"]);
  assert.deepEqual(await at("2026-10-11"), [true, "2026-10-11 00:00"]);
  for (const value of ["2026-10-11 6:30", "2026-10-11 24:00", "2026-02-30"]) assert.deepEqual(await at(value), ["断った", null], value);
});

test("移行の準備: Status に無い選択肢を設定の並びで足し（今ある選択肢は id・色・説明を保ち、タスクのステータスを消さない）、対話作業のボードと種類が無ければ作る。2度目は何も書かない", async () => {
  const S = config.status;
  const gh = fakeGitHub({ issues: [{ number: 1, status: S.todo }, { number: 2, status: S.review }, { number: 3, status: S.hold }],
    options: [S.todo, S.working, S.review, S.waiting, S.hold, S.done], types: ["保"], dialog: false });
  const bot = new GitHub("bot-token");
  assert.equal((await prepare(bot, config, { dry: true })).length, 3); // 試しは書かずに、今足りないもの（選択肢・ボード・種類）を出す
  assert.equal(gh.writes.length, 0);
  assert.deepEqual(await prepare(bot, config), []);
  const field = gh.writes.find((w) => w.op === "updateProjectV2Field").singleSelectOptions;
  assert.deepEqual(field.map((o) => [o.name, o.id ?? null, o.color, o.description]),
    Object.values(S).map((name) => [name, [S.ci, S.ready].includes(name) ? null : `S:${name}`, [S.ci, S.ready].includes(name) ? "GRAY" : "BLUE", [S.ci, S.ready].includes(name) ? "" : `${name}の説明`]));
  assert.deepEqual([gh.issues.map((i) => i.status), gh.dialog, gh.types.includes(config.dialog.type)], [[S.todo, S.review, S.hold], true, true]);
  const written = gh.writes.length;
  assert.deepEqual(await prepare(bot, config), []);
  assert.equal(gh.writes.length, written);
});

test("移行の準備の確かめ: bot が対話作業のボードに書けない・ゲートの App の組織のインストールに権限か出来事が足りないときは、直し方を出す", async () => {
  const at = async (extra) => {
    fakeGitHub(extra);
    return (await prepare(new GitHub("bot-token"), config)).length;
  };
  assert.equal(await at({}), 0);
  assert.equal(await at({ dialog: "読むだけ" }), 1);
  assert.equal(await at({ app: { permissions: { issues: "write", organization_projects: "read", contents: "read" }, events: ["issues", "issue_comment", "projects_v2_item", "repository_dispatch"] } }), 1);
  assert.equal(await at({ app: { permissions: { issues: "write", organization_projects: "write", contents: "read" }, events: ["issues"] } }), 1);
});
