// 担当の終わり方の見分け（src/after.js）を確かめる。
import assert from "node:assert/strict";
import { test } from "node:test";
import { classify, endReport, lastWords } from "../src/after.js";

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
  for (const s of ["| 保留 |", "| #9: 落ちた 進行中 → 保留 |", "| 8分40秒 |", "| 74 |", "https://example.test/runs/1", "> 1行目\n> 2行目"]) assert.ok(body.includes(s), s);
});

test("実行のファイルが無いときも、分からない欄を不明として書ける", () => {
  const body = endReport({ kind: "確かめる", url: "u", jobStatus: "cancelled", messages: null, done: [], status: undefined, elapsedMs: null });
  assert.ok(body.includes("| 不明 |") && body.includes("（無い）") && body.includes("| なし |"));
});
