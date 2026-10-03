// 担当の終わり方の見分け（src/after.js）を確かめる。
import assert from "node:assert/strict";
import { test } from "node:test";
import { classify } from "../src/after.js";

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
