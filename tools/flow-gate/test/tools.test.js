// 約束 18・24（担当の後始末の行き先と手番の記録の置き場。src/after.js: settle・keepLog）・26（GitHub の一時的な失敗。src/github.js: GitHub）・
// 27（問いの形と打ち直し。src/move.js: askTask）・28・29・33・34・37（タスクを持つ印。開発機の対話のセッションが持つ・手放すのと担当の
// 引き受け。src/hold.js）・30（画像の貼り方。src/attach.js: attach）・31（Pull Request の本文の形。src/rules.js: checkBody）・32（試しを
// 持たない道具は --dry-run を断る。bin/cli.js: args）・36（着手可能日時の欄へ書く値の形。src/github.js: setField）を確かめる。設定は架空のもの（fake-github.js: config）を渡し、24・26・27・29 は
// GitHub（網）だけを、30 は gh を打つ口だけを差し替える。持つ印の置き場は手元の裸のリポジトリで、本物の git が受ける。32・33 は本物の
// 道具を別のプロセスで打つ（33 は置き場の URL を git の設定で手元へ向ける）。
// ここで見ないもの: 終わりのコメントの中身（文言で、`bin/after.js --dry-run` が出す姿で見る）・ステータスを動かす道具（src/move.js）の表の照らし
// （rules.js: judge を呼ぶだけなので、照らしは gate.test.js が見る）・打ち直しの回数と間（公式の SDK の既定を写した値で、約束ではない）・
// 道具（bin/attach.js）が打つ gh・31 の断る文言・本物のテンプレート（.github/pull_request_template.md）と照らしの食い違い（
// .github/workflows/claude-gate.yml の flow-gate が、Pull Request の本文に bin/pr-body.js を打って落とす）。
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { keepLog, settle } from "../src/after.js";
import { GitHub, readTask, setField } from "../src/github.js";
import { claim, devHolder, holdRemote, readHolds, release, take, workerHolder } from "../src/hold.js";
import { askTask, moveTask } from "../src/move.js";
import { attach } from "../src/attach.js";
import { checkBody } from "../src/rules.js";
import base from "../flow.config.json" with { type: "json" };
import { config, fakeGitHub } from "./fake-github.js";

test("18 後始末: 上限・認証は戻して振り出しを止め、一時の失敗と起きる前の落ちは戻すだけ、開いた Pull Request・待つ理由があれば戻し、それ以外（持ち時間を超えた・Cancel されたも）は保留", () => {
  const said = (error) => [{ type: "assistant", error }];
  const at = (messages, extra = {}) => settle(config, { messages, waits: null, pullRequest: null, url: "u", jobStatus: "success", ...extra });
  assert.deepEqual([at(said("rate_limit")).to, at(said("rate_limit")).pause], [config.todo, true]);
  for (const m of [said("overloaded"), null]) assert.deepEqual([at(m).to, at(m).pause], [config.todo, false]);
  assert.equal(at([], { waits: "開いた前提（blocked by）" }).to, config.todo);
  assert.equal(at([], { pullRequest: { number: 3, html_url: "p" } }).to, config.todo);
  assert.equal(at([]).to, config.hold);
  for (const m of [said("rate_limit"), null]) assert.deepEqual([at(m, { jobStatus: "cancelled" }).to, at(m, { jobStatus: "cancelled" }).pause], [config.hold, false]);
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

test("27 問いは、形に合わなければ何も書かずに断り、答えの無い最新の問いが同じ文なら書き直さずに回答待ちへ動かす: 書いたあとに落ちた打ちを打ち直しても問いは1つ", async () => {
  const question = "## 問い\nどちらにするか\n\n<details><summary>判断材料</summary>\n\n**約束**: 約束\n**案ごと**: 案なし\n**推奨**: こうする\n</details>";
  const answer = "## 回答\n**どちらにするか**\n\n次のステータス: 前";
  const at = async (status, comments, asked = question) => {
    const gh = fakeGitHub({ issue: { number: 7, status, comments: comments.map((body) => ({ author: "c", body })) } });
    const done = await askTask(new GitHub("bot-token"), config, 7, asked).then(() => true, () => false);
    return done ? [gh.issue.status, gh.issue.comments.filter((c) => c.body === question).length] : [false, gh.writes.length];
  };
  assert.deepEqual(await at(config.waiting, [], "## 問い\nどちらにするか"), [false, 0]);
  assert.deepEqual(await at(config.working, []), [config.waiting, 1]);
  assert.deepEqual(await at(config.working, [question]), [config.waiting, 1]);
  assert.deepEqual(await at(config.waiting, [question]), [config.waiting, 1]);
  assert.deepEqual(await at(config.waiting, ["## 問い\n別の問い"]), [config.waiting, 1]);
  assert.deepEqual(await at(config.todo, [question, answer]), [config.waiting, 2]);
});

// 印の置き場は手元の裸のリポジトリ（本物の git が受ける）。
const origin = () => {
  const dir = mkdtempSync(join(tmpdir(), "flow-origin-"));
  execFileSync("git", ["init", "-q", "--bare", dir]);
  return dir;
};
const workerUrl = "https://example.invalid/actions/runs/5";

// 開発機（take）と担当（claim）の、印の置き場に触れる git の呼び出し（push・fetch）を1つずつ通す。両方が呼び出しの前で待っているときは
// choose() が返す側（"dev" か "worker"）を通す。ほかの呼び出し（手元の git・GitHub）は止めない。
async function interleave(dir, choose) {
  const sides = { dev: { state: "running" }, worker: { state: "running" } };
  let wake = () => {};
  const gated = (name) => {
    const r = holdRemote(dir);
    return { ...r, git: async (a, input) => {
      if (["push", "fetch"].includes(a[0])) {
        await new Promise((go) => {
          Object.assign(sides[name], { state: "waiting", go });
          wake();
        });
      }
      return r.git(a, input);
    } };
  };
  const results = {};
  const done = (name) => (v) => {
    results[name] = v;
    sides[name].state = "done";
    wake();
  };
  take(gated("dev"), config, 7, devHolder("a")).then(done("dev"), done("dev"));
  claim(new GitHub("bot-token"), gated("worker"), config, 7, "作る", workerUrl).then(() => done("worker")(true), () => done("worker")(false));
  for (;;) {
    while (Object.values(sides).some((s) => s.state === "running")) await new Promise((r) => (wake = r));
    const waiting = Object.keys(sides).filter((k) => sides[k].state === "waiting");
    if (!waiting.length) return results;
    const side = sides[waiting.length === 2 ? choose() : waiting[0]];
    side.state = "running";
    side.go();
  }
}

test("28 持つ印は1者だけ: 開発機が持つのと担当の引き受けを、置き場への書き込みと読みのどの並びで重ねても、片方だけが持ち、負けた側は印を残さない", async () => {
  const winners = new Set();
  const explore = async (prefix) => {
    const dir = origin();
    const gh = fakeGitHub({ issue: { number: 7, status: config.todo } });
    const taken = [];
    const r = await interleave(dir, () => taken[taken.push(taken.length < prefix.length ? prefix[taken.length] : "dev") - 1]);
    const marks = await readHolds(holdRemote(dir), config);
    const winner = r.dev.held ? devHolder("a") : workerHolder("作る", workerUrl);
    assert.deepEqual([r.dev.held !== r.worker, marks.map((m) => m.who), gh.issue.status], [true, [winner], r.worker ? config.working : config.todo], `並び ${taken.join("→")}`);
    winners.add(winner);
    rmSync(dir, { recursive: true, force: true });
    for (let j = prefix.length; j < taken.length; j++) await explore([...taken.slice(0, j), "worker"]);
  };
  await explore([]);
  assert.equal(winners.size, 2);
});

test("29 引き受けは、印・開発機のラベルのあるタスクを作るでも確かめるでも引き受けず、前提・着手可能日時は作るだけが待つ。引き受けなければ書かず、印も残さない", async () => {
  const dev = config.coordinator.devLabel;
  const at = async (kind, issue, { held = false } = {}) => {
    const dir = origin();
    const gh = fakeGitHub({ issue: { number: 7, status: kind === "作る" ? config.todo : config.review, ...issue } });
    if (held) await take(holdRemote(dir), config, 7, devHolder("a"));
    const ok = await claim(new GitHub("bot-token"), holdRemote(dir), config, 7, kind, workerUrl).then(() => true, () => false);
    const marks = (await readHolds(holdRemote(dir), config)).map((m) => m.who);
    rmSync(dir, { recursive: true, force: true });
    return [ok, gh.writes.length > 0, marks];
  };
  for (const kind of ["作る", "確かめる"]) {
    const me = [workerHolder(kind, workerUrl)];
    assert.deepEqual(await at(kind, {}), [true, true, me], kind);
    assert.deepEqual(await at(kind, { labels: [dev] }), [false, false, []], kind);
    assert.deepEqual(await at(kind, {}, { held: true }), [false, false, [devHolder("a")]], kind);
  }
  assert.deepEqual(await at("作る", { blockedBy: ["OPEN"] }), [false, false, []]);
  assert.deepEqual(await at("作る", { fields: { [config.project.startField]: "2999-01-01 06:30" } }), [false, false, []]);
  assert.deepEqual(await at("確かめる", { blockedBy: ["OPEN"], fields: { [config.project.startField]: "2999-01-01 06:30" } }), [true, true, [workerHolder("確かめる", workerUrl)]]);
  assert.deepEqual(await at("作る", { status: config.working }), [false, false, []]);
});

test("33 開発機の hold.js: 持てなければ「持てなかった」を出して 1 で終え自分の印を残さず、手放すは何度打っても同じ結果で、どちらも GitHub の API（Actions の実行）を呼ばない", async () => {
  const dir = origin();
  const root = fileURLToPath(new URL("../", import.meta.url));
  // 置き場の URL を手元の裸のリポジトリへ向け、GitHub の API を呼んだら 9 で終わらせる。master の版へ打ち直さない（FLOW_GATE_REPO）。
  const env = {
    ...process.env, FLOW_BOT_TOKEN: "t", FLOW_GATE_REPO: fileURLToPath(new URL("../../../", import.meta.url)),
    GIT_CONFIG_COUNT: "1", GIT_CONFIG_KEY_0: `url.${dir}.insteadOf`, GIT_CONFIG_VALUE_0: `https://github.com/${base.repository}.git`,
  };
  const hold = (...a) => spawnSync(process.execPath, ["--import", "data:text/javascript,globalThis.fetch=()=>process.exit(9)", join(root, "bin/hold.js"), "7", ...a], { env, encoding: "utf8" });
  const marks = async () => (await readHolds(holdRemote(dir), base)).map((m) => m.who);

  await take(holdRemote(dir), base, 7, workerHolder("作る", workerUrl));
  let r = hold();
  assert.deepEqual([r.status, /持てなかった/.test(r.stdout), await marks()], [1, true, [workerHolder("作る", workerUrl)]], r.stderr);
  await release(holdRemote(dir), base, 7, workerHolder("作る", workerUrl));

  r = hold();
  const word = /--release (\S+)）/.exec(r.stdout)?.[1];
  assert.deepEqual([r.status, (await marks()).length, Boolean(word)], [0, 1, true], r.stderr);
  assert.deepEqual(hold("--release", "別の合言葉").status, 1);
  for (let k = 0; k < 2; k++) {
    r = hold("--release", word);
    assert.deepEqual([r.status, await marks()], [0, []], r.stderr);
  }
  rmSync(dir, { recursive: true, force: true });
});

test("34 持てたかは読み直しで決める: 押し込みのあとの読みが落ちたら、持てなかったとして自分の印を消す", async () => {
  const dir = origin();
  const r = holdRemote(dir);
  let fetches = 0;
  const flaky = { ...r, git: (a, input) => (a[0] === "fetch" && fetches++ === 0 ? Promise.resolve({ status: 128, stdout: "", stderr: "fatal: 読めない" }) : r.git(a, input)) };
  assert.deepEqual(await take(flaky, config, 7, devHolder("a")), { held: false, by: null });
  assert.deepEqual(await readHolds(r, config), []);
  rmSync(dir, { recursive: true, force: true });
});

test("37 git が標準入力を読まずに終わっても、印の道具は落ちずに git の終わりの状態を返す", async () => {
  const dir = origin();
  const r = holdRemote(dir);
  await r.ready;
  // パイプの容量より大きい入力を、入力を読まずにすぐ終わる git へ渡す（書き込みが EPIPE になる並び）。
  const done = await r.git(["version"], "x".repeat(8 * 1024 * 1024));
  assert.deepEqual([done.status, /^git version/.test(done.stdout)], [0, true]);
  rmSync(dir, { recursive: true, force: true });
});

test("30 画像は1枚ずつ貼り、貼れなければそこで止まって、それまでに貼った分を知らせる", () => {
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

test("31 Pull Request の本文は、テンプレートの節を全部この順で1つずつ持ち、どの節も埋めてあるときだけ通る", () => {
  const template = "背景: <なぜ>\n課題: <何を>\n残り: <何が>\n";
  const passes = (body) => checkBody(template, body).length === 0;
  const rows = [
    ["背景: a\n課題:\n- 足した約束: b\n範囲: c\n残り: なし\n\n🤖 Generated", true], // 節の中の「名前: 」の行と、最後の節のあとの行
    ["背景: a\r\n課題: b\r\n残り: なし\r\n", true], // GitHub の画面から書いた本文
    ["tasks#1。\n背景: a\n課題: b\n残り: なし", false], // 最初の節より前の行
    ["背景: a\n残り: なし", false], // 欠けた節
    ["課題: b\n背景: a\n残り: なし", false], // 違う順
    ["背景: a\n課題: b\n課題: c\n残り: なし", false], // 2度出る節
    ["背景: a\n課題:\n\n残り: なし", false], // 空の節
    ["背景: a\n課題: <何を>\n残り: なし", false], // テンプレートのままの節
  ];
  assert.deepEqual(rows.map(([body]) => passes(body)), rows.map(([, ok]) => ok));
});

test("32 試しを持たない道具は --dry-run を断り、書かずに 1 で終える。試しを持つ道具は --dry-run を断らない", (t) => {
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

test("36 着手可能日時の欄へは、日本時間の YYYY-MM-DD HH:MM か YYYY-MM-DD（00:00 にそろえる）だけを書き、形の合わない日時は書かずに断る", async () => {
  const field = config.project.startField;
  const at = async (value) => {
    const gh = fakeGitHub({ issue: { number: 7, status: config.todo } });
    const github = new GitHub("bot-token");
    const { project, issue } = await readTask(github, config, { number: 7 });
    const done = await Promise.resolve().then(() => github.write([setField(project, issue.item, field, value)])).then(() => true, (e) => /YYYY-MM-DD HH:MM/.test(e.message) && "断った");
    return [done, gh.issue.fields[field] ?? null];
  };
  assert.deepEqual(await at("2026-10-11 06:30"), [true, "2026-10-11 06:30"]);
  assert.deepEqual(await at("2026-10-11"), [true, "2026-10-11 00:00"]);
  for (const value of ["2026-10-11 6:30", "2026-10-11 24:00", "2026-10-11 06:60", "2026-02-30", "2026-10-11T06:30"]) assert.deepEqual(await at(value), ["断った", null], value);
});
