// 約束 18（担当の後始末で振り出しを止めるか。src/after.js: settle）・26（GitHub の一時的な失敗。src/github.js: GitHub）・
// 27（問いの打ち直し。src/move.js: askTask）・28（開発機の対話のセッションが持つ・手放す。src/hold.js）・30（画像の貼り方。
// src/attach.js: attach）・31（Pull Request の本文の形。src/pullrequest.js: checkBody）を確かめる。設定は架空のもの（fake-github.js: config）を渡し、26・27・28 は GitHub（網）だけを、30 は gh を
// 打つ口だけを差し替える。
// ここで見ないもの: 終わりのコメントの中身（文言で、`bin/after.js --dry-run` が出す姿で見る）・ステータスを動かす道具（src/move.js）の表の照らし
// （rules.js: judge を呼ぶだけなので、照らしは gate.test.js が見る）・打ち直しの回数と間（公式の SDK の既定を写した値で、約束ではない）・
// 道具（bin/attach.js）が打つ gh・31 の断る文言。
import assert from "node:assert/strict";
import { test } from "node:test";
import { settle } from "../src/after.js";
import { GitHub } from "../src/github.js";
import { hold, release } from "../src/hold.js";
import { askTask, moveTask } from "../src/move.js";
import { attach } from "../src/attach.js";
import { checkBody } from "../src/pullrequest.js";
import { config, fakeGitHub } from "./fake-github.js";

test("18 後始末: 利用の上限・認証で止まったときだけ振り出しを止め、一時の失敗と起きる前の落ちは止めない", () => {
  const said = (error) => [{ type: "assistant", error }];
  const at = (messages) => settle({ messages, url: "u", jobStatus: "success" }).pause;
  assert.deepEqual([at(said("rate_limit")), at(said("overloaded")), at(null)], [true, false, false]);
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

test("28 開発機の対話のセッションが持つ: 待ちの開発機の実行は持っているに数えずに待ち直し、手放しは持った実行を一覧に出なくても取り消しを頼んで、止まるまで待たずに戻り、待ちと手放しは GitHub の一時的な失敗1回で落ちない", async () => {
  // runs は担当のワークフローの実行（later は読まれたときに移る状態で、並びなら読まれるたびに1つずつ移る。unlisted は状態で絞った一覧にまだ出ない、refused は取り消しを
  // 断る（409））。fail に挙げた要求（方法と道の頭）は、1回目だけ 502 を返す。
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
        if (run.refused) return new Response("conflict", { status: 409 });
        Object.assign(run, { later: ["in_progress", "completed"], conclusion: "cancelled" });
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
  // 手放しは、持った実行が一覧にまだ出なくても取り消しを頼み、受け付けられたら止まるまで読み直さずに戻る。取り消しが 502 を受けても落ちない。
  s = at([run(6, 7, "開発機", "in_progress", undefined, { unlisted: true }), run(8, 8, "開発機", "in_progress")], ["POST /repos/o/code/actions/runs/6/cancel"]);
  r = await release(gh, config, 7, 6);
  assert.deepEqual([r.status, s.sent.filter((c) => c.includes("/runs/6")).at(-1), s.runs[1].status], ["in_progress", "POST /repos/o/code/actions/runs/6/cancel", "in_progress"]);
  // もう終わった実行は取り消さない。取り消しが受け付けられなければ（409 等）失敗で終える。その番号の開発機の実行でなければ（別の番号の開発機・同じ番号の作る担当）取り消さない。
  s = at([run(9, 7, "開発機", "in_progress", undefined, { refused: true }), run(10, 8, "開発機", "in_progress"), run(11, 7, "作る", "in_progress"), run(12, 7, "開発機", "completed")]);
  await assert.rejects(release(gh, config, 7, 9), /409/);
  assert.equal((await release(gh, config, 7, 12)).status, "completed");
  for (const id of [10, 11]) await assert.rejects(release(gh, config, 7, id));
  assert.deepEqual([s.runs[1].status, s.runs[2].status, s.sent.filter((c) => /runs\/1[012]\/cancel/.test(c))], ["in_progress", "in_progress", []]);
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
