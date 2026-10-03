// 担当の終わり方の見分け（src/after.js）を確かめる。
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { test } from "node:test";
import config from "../flow.config.json" with { type: "json" };
import { classify, endReport, lastWords, refusal, settle } from "../src/after.js";

const said = (error) => ({ type: "assistant", message: { content: [] }, ...(error ? { error } : {}) });

test("利用の上限・認証で止まったら担当の外の失敗で、振り出しも止める", () => {
  for (const e of ["rate_limit", "authentication_failed", "billing_error"]) {
    const v = classify([said(), said(e), { type: "result", is_error: true }]);
    assert.deepEqual([v.outside, v.pause], [true, true], e);
  }
});

test("実行のファイルが無い（担当が動けなかった）ときも、担当の外の失敗で振り出しを止める", () => {
  assert.deepEqual([classify(null).outside, classify(null).pause], [true, true]);
});

test("サーバーの混雑は担当の外の失敗だが、一時のものなので振り出しは止めない", () => {
  const v = classify([said("overloaded")]);
  assert.deepEqual([v.outside, v.pause], [true, false]);
});

test("担当の発言に失敗が無ければ担当の側の終わり方（落ちたかは後始末がステータスで決める）", () => {
  const v = classify([said(), { type: "result", is_error: false }]);
  assert.deepEqual([v.outside, v.pause], [false, false]);
});

const done = { outside: false, pause: false, reason: "" };

test("作る担当が開いた子の段階を残して終えたら、親は進行中のまま置く（落ちたにしない）", () => {
  assert.equal(settle(config, { verdict: done, children: [{ state: "OPEN" }, { state: "CLOSED" }], url: "u", jobStatus: "success" }), null);
});

test("子が無い・子が全部閉じたタスクで PR も問いも出さずに終わったら、落ちたで保留にする", () => {
  for (const children of [[], [{ state: "CLOSED" }]]) {
    const step = settle(config, { verdict: done, children, url: "u", jobStatus: "cancelled" });
    assert.equal(step.to, config.hold);
    assert.ok(step.reason.includes("Cancel された"), step.reason);
  }
});

test("着手可能日を先の日へ入れて終えたら、落ちたにせず未着手へ戻す。今日（日本時間）以前の日なら落ちた", () => {
  const now = new Date("2026-10-03T15:30:00Z");
  const step = settle(config, { verdict: done, children: [], startOn: "2026-10-05", url: "u", jobStatus: "success", now });
  assert.equal(step.to, config.todo);
  assert.ok(step.reason.includes("2026-10-05"), step.reason);
  assert.equal(settle(config, { verdict: done, children: [], startOn: "2026-10-04", url: "u", jobStatus: "success", now }).to, config.hold);
});

test("担当の外の失敗なら、開いた子があっても未着手へ戻す", () => {
  assert.equal(settle(config, { verdict: classify([said("overloaded")]), children: [{ state: "OPEN" }], url: "u", jobStatus: "failure" }).to, config.todo);
});

const text = (t) => ({ type: "assistant", message: { content: [{ type: "text", text: t }] } });
const tool = () => ({ type: "assistant", message: { content: [{ type: "tool_use", name: "Bash", input: {} }] } });

test("最後の発言は result の文を採り、無ければ最後の担当の文を採る（道具の呼び出しだけの発言は飛ばす）", () => {
  assert.equal(lastWords([text("前"), { type: "result", result: "PR を出した" }]), "PR を出した");
  assert.equal(lastWords([text("前"), text("ここで終える"), tool(), { type: "result", is_error: true }]), "ここで終える");
  assert.equal(lastWords([tool()]), null);
  assert.equal(lastWords(null), null);
});

test("長い最後の発言は頭から決まった長さで切り、切ったことを書く", () => {
  assert.equal(lastWords([{ type: "result", result: "あいうえお" }], 3), "あいう…（5字のうち頭の3字）");
});

test("終わりのコメントに、ステータス・後始末がしたこと・時間・手数・実行・引用した最後の発言が出る", () => {
  const body = endReport({
    kind: "作る",
    url: "https://example.test/runs/1",
    jobStatus: "success",
    messages: [text("調べた"), { type: "result", num_turns: 74, result: "1行目\n2行目" }],
    done: ["#9: 落ちた 進行中 → 保留"],
    status: "保留",
    elapsedMs: 520000,
  });
  for (const s of ["| 保留 |", "| #9: 落ちた 進行中 → 保留 |", "| 8分40秒 |", "| 74 |", "| 判定に断られた操作 | 0件 |", "https://example.test/runs/1", "> 1行目\n> 2行目"])
    assert.ok(body.includes(s), s);
});

test("終わりのコメントに、判定に断られた操作の数と、道具・打とうとしたものが出る（表を壊す縦線と改行は残さない）", () => {
  const permission_denials = [
    { tool_name: "Edit", tool_input: { file_path: ".claude/settings.json", old_string: "a" } },
    { tool_name: "Bash", tool_input: { command: "gh pr merge 3 | tee x\n  --rebase" } },
  ];
  const body = endReport({ kind: "作る", url: "u", jobStatus: "success", messages: [{ type: "result", num_turns: 3, permission_denials }], done: [], status: "進行中", elapsedMs: 1000 });
  const row = body.split("\n").find((l) => l.startsWith("| 判定に断られた操作 |"));
  assert.equal(row, "| 判定に断られた操作 | 2件<br>Edit: .claude/settings.json<br>Bash: gh pr merge 3 \\| tee x --rebase |");
});

test("実行のファイルが無いときも、分からない欄を不明として書ける", () => {
  const body = endReport({ kind: "確かめる", url: "u", jobStatus: "cancelled", messages: null, done: [], status: undefined, elapsedMs: null });
  assert.ok(body.includes("| 不明 |") && body.includes("（無い）") && body.includes("| なし |"));
});

test("かかった時間は秒で丸めてから分と秒に分け、60秒を繰り上げる", () => {
  const time = (elapsedMs) => endReport({ kind: "作る", url: "u", jobStatus: "success", messages: null, done: [], status: "検証中", elapsedMs }).match(/かかった時間[^|]*\| ([^|]+) \|/)[1];
  assert.equal(time(119600), "2分0秒");
  assert.equal(time(119400), "1分59秒");
});

// 子の node が断ったときの出力は Node.js が組み立てるので、本物の子を走らせて採る。
const failed = (code) => {
  try {
    execFileSync(process.execPath, ["--input-type=module", "-e", code], { encoding: "utf8", stdio: "pipe" });
  } catch (e) {
    return e;
  }
  throw new Error("子が断らなかった");
};

test("子が例外で断ったら、積み跡と版の行ではなく例外の文を理由に採る", () => {
  assert.equal(refusal(failed('throw new Error("「検証中」から「保留」へは動かせません")')), "「検証中」から「保留」へは動かせません");
  assert.equal(refusal(failed('throw new TypeError("fetch failed")')), "TypeError: fetch failed");
});

test("例外の行が無い断り（使い方の誤り等）は最後の行を理由に採る", () => {
  assert.equal(refusal(failed('console.error("使い方: move.js <番号> <出来事>"); process.exit(2)')), "使い方: move.js <番号> <出来事>");
});
