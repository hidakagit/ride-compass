// 約束 18・24（担当の後始末の行き先と手番の記録の置き場。src/after.js: settle・keepLog）・26（GitHub の一時的な失敗。src/github.js: GitHub）・
// 27（問いの打ち直し。src/move.js: askTask）・28（開発機の対話のセッションが持つ・手放す。src/hold.js）・29（ランナーが付かずに取り消された
// 実行の見分け。src/rerun.js: verdict）・30（画像の貼り方。src/attach.js: attach）を確かめる。設定は架空のもの（fake-github.js: config）を渡し、
// 24・26・27・28 は GitHub（網）だけを、30 は gh を打つ口と待つ口だけを差し替える。
// ここで見ないもの: 終わりのコメントの中身（文言で、`bin/after.js --dry-run` が出す姿で見る）・ステータスを動かす道具（src/move.js）の表の照らし
// （rules.js: judge を呼ぶだけなので、照らしは gate.test.js が見る）・打ち直しの回数と間（公式の SDK の既定を写した値で、約束ではない）・
// 道具（bin/rerun.js・bin/attach.js）が読む API と打つ gh（`bin/rerun.js --dry-run` で本物の実行を読んで見る）。
import assert from "node:assert/strict";
import { test } from "node:test";
import { keepLog, settle } from "../src/after.js";
import { GitHub } from "../src/github.js";
import { hold, release } from "../src/hold.js";
import { askTask, moveTask } from "../src/move.js";
import { RERUNS, verdict } from "../src/rerun.js";
import { attach, TRIES, WAIT } from "../src/attach.js";
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

test("28 開発機の対話のセッションが持つ: 待ちの開発機の実行は持っているに数えずに待ち直し、手放しは持った実行を一覧に出なくても取り消して止まるまで待ち、待ちと手放しは GitHub の一時的な失敗1回で落ちない", async () => {
  // runs は担当のワークフローの実行（later は読まれたときに移る状態で、並びなら読まれるたびに1つずつ移る。unlisted は状態で絞った一覧にまだ出ない、stuck は取り消しても
  // 止まらない）。fail に挙げた要求（方法と道の頭）は、1回目だけ 502 を返す。
  const at = (runs, fail = []) => {
    const s = { runs, sent: [] };
    globalThis.fetch = async (url, init = {}) => {
      const { pathname: path, searchParams: q } = new URL(url);
      const call = `${init.method} ${path}`;
      const k = fail.findIndex((f) => call.startsWith(f));
      if (k >= 0) {
        fail.splice(k, 1);
        return new Response("bad gateway", { status: 502 });
      }
      s.sent.push(call);
      const run = s.runs.find((r) => path.endsWith(`/actions/runs/${r.id}`) || path.endsWith(`/actions/runs/${r.id}/cancel`));
      if (path.endsWith("/w.yml/runs")) return Response.json({ workflow_runs: Number(q.get("page")) > 1 ? [] : s.runs.filter((r) => !r.unlisted && r.status === q.get("status")) });
      if (path.endsWith("/w.yml/dispatches")) {
        s.runs.push({ id: 100, status: "queued", later: "in_progress", display_title: `#${JSON.parse(init.body).inputs.issue} 開発機` });
        return Response.json({ workflow_run_id: 100 });
      }
      if (path.endsWith("/cancel")) {
        if (!run.stuck) Object.assign(run, { later: ["in_progress", "completed"], conclusion: "cancelled" });
        return new Response(null, { status: 202 });
      }
      run.status = (Array.isArray(run.later) ? run.later.shift() : run.later) ?? run.status;
      return Response.json(run);
    };
    return s;
  };
  const gh = new GitHub("code-token");
  const wait = async () => {};
  const run = (id, number, kind, status, later, extra) => ({ id, status, later, display_title: `#${number} ${kind}`, ...extra });

  // 待ちの開発機の実行（前に打って落ちた自分のもの）は持っているに数えず、起こし直さずにそれが動き始めるまで待つ。
  let s = at([run(1, 7, "開発機", "pending", "in_progress"), run(2, 8, "開発機", "in_progress")]);
  let r = await hold(gh, config, 7, wait);
  assert.deepEqual([r.held, r.mine.id, r.mine.status, s.sent.filter((c) => c.startsWith("POST"))], [undefined, 1, "in_progress", []]);
  // 動いている開発機の実行だけが持っている。
  s = at([run(3, 7, "開発機", "in_progress"), run(4, 7, "作る", "pending")]);
  assert.equal((await hold(gh, config, 7, wait)).held.id, 3);
  // 無ければ起こし、起こした実行を待つ。一覧の読みと待ちの読みが1回ずつ 502 を受けても落ちない。
  s = at([run(5, 7, "作る", "in_progress")], ["GET /repos/o/code/actions/workflows/w.yml/runs", "GET /repos/o/code/actions/runs/100"]);
  r = await hold(gh, config, 7, wait);
  assert.deepEqual([r.mine.id, r.mine.status], [100, "in_progress"]);
  // 手放しは、持った実行が一覧にまだ出なくても取り消し、止まるまで読み直す。取り消しが 502 を受けても落ちない。
  s = at([run(6, 7, "開発機", "in_progress", undefined, { unlisted: true }), run(8, 8, "開発機", "in_progress")], ["POST /repos/o/code/actions/runs/6/cancel"]);
  r = await release(gh, config, 7, 6, wait);
  assert.deepEqual([r.status, r.conclusion, s.runs.map((x) => x.status)], ["completed", "cancelled", ["completed", "in_progress"]]);
  // 取り消しても止まらなければ、終わっていない実行を返す。その番号の開発機の実行でなければ（別の番号の開発機・同じ番号の作る担当）取り消さない。
  s = at([run(9, 7, "開発機", "in_progress", undefined, { stuck: true }), run(10, 8, "開発機", "in_progress"), run(11, 7, "作る", "in_progress")]);
  assert.equal((await release(gh, config, 7, 9, wait, 2)).status, "in_progress");
  for (const id of [10, 11]) await assert.rejects(release(gh, config, 7, id, wait));
  assert.deepEqual([s.runs[1].status, s.runs[2].status, s.sent.filter((c) => /runs\/1[01]\/cancel/.test(c))], ["in_progress", "in_progress", []]);
});

test("29 流し直すのは、取り消されたジョブがどれも段0で注記にランナーが付かなかったとあり、ほかに段を走らせて落ちたのがまとめのジョブだけのときで、流し直しは上限まで", () => {
  const job = (id, name, conclusion, steps = 0) => ({ id, name, conclusion, steps: Array(steps).fill({}) });
  const run = (attempt = 1, status = "completed") => ({ status, run_attempt: attempt });
  const note = { 1: ["警告", "The job was not acquired by Runner of type hosted even after multiple attempts"] };
  const at = (jobs, notes = note, r = run()) => verdict(r, jobs, notes, config.code.gather).kind;
  const cancelled = [job(1, "e2e", "cancelled"), job(2, config.code.gather, "failure", 2), job(3, "backend", "success", 5), job(4, "deploy", "skipped")];
  assert.equal(at(cancelled), "流す");
  assert.equal(at(cancelled, note, run(RERUNS)), "流す");
  assert.equal(at(cancelled, note, run(RERUNS + 1)), "使い切った");
  assert.equal(at(cancelled, { 1: ["警告"] }), "落ちた"); // 注記にランナーの文が無い
  assert.equal(at([job(1, "e2e", "cancelled", 3), job(2, config.code.gather, "failure", 2)]), "落ちた"); // 段を走らせてから取り消された
  assert.equal(at([...cancelled, job(5, "frontend", "failure", 4)]), "落ちた"); // ほかに落ちたジョブがある
  assert.equal(at([job(2, config.code.gather, "failure", 2)]), "落ちた"); // 取り消されたジョブが無い
  assert.equal(at(cancelled, note, run(1, "in_progress")), "終わっていない");
});

test("30 画像は1枚ずつ貼り、名義の誤りは止め、rate limited は出た時間だけ待ち、ほかの失敗は上限まで打ち直して、使い切ったら置き場の issue へ貼って Pull Request にリンクを書く", async () => {
  const at = async (replies) => {
    const calls = [];
    const waits = [];
    const run = (a, as) => {
      calls.push(`${as} ${a[0]} ${a[1]}`);
      return replies.shift() ?? { status: 0, stdout: `https://github.com/${as}/${calls.length}\n`, stderr: "" };
    };
    const said = await attach({ run, sleep: async (s) => waits.push(s), code: config.code.repository, tasks: config.repository, pr: 3, issue: 7, images: ["a.png#前", "b.png#後"] });
    return { calls, waits, said };
  };
  const fail = (stderr) => ({ status: 1, stdout: "", stderr });
  const upload = fail("failed to upload a.png: HTTP 502");
  let r = await at([fail("could not upload a.png: rate limited; retry after 30 seconds"), fail("could not upload a.png: rate limited; wait and try again")]);
  assert.deepEqual([r.calls, r.waits], [["code pr comment", "code pr comment", "code pr comment", "code pr comment"], [30, WAIT]]);
  r = await at(Array(TRIES).fill(upload));
  assert.deepEqual(r.calls, [...Array(TRIES).fill("code pr comment"), "bot issue comment", "code pr comment", "code pr comment"]);
  assert.match(r.said[0], /^前: https:\/\/github.com\/bot\/\d+（Pull Request に貼れず、置き場の issue へ）$/);
  r = await at([upload, upload]);
  assert.deepEqual([r.calls.length, r.said.map((l) => l.split(":")[0])], [TRIES + 1, ["前", "後"]]);
  await assert.rejects(at([fail("could not upload a.png: attaching files requires write access to the repository")]), /名義の誤り/);
});
