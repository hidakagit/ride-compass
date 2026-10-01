// @vitest-environment node
/**
 * `lib/apiError.ts`——backendのエラー応答の`detail`を、利用者へ出せる1つの文言にする。
 *
 * ここで見ないもの:
 * - 文言を`Error`にして投げること・`detail`が無いときの文言 → `lib/apiClient.test.ts`
 */
import { describe, expect, it } from "vitest";

import { formatErrorDetail } from "@/lib/apiError";

describe("formatErrorDetail", () => {
  it.each([null, undefined])("%s なら文言を作らない（呼び出し側が自分の文言を使う）", (detail) => {
    expect(formatErrorDetail(detail)).toBeUndefined();
  });

  it("文字列はそのまま返す", () => {
    expect(formatErrorDetail("経路が見つかりません")).toBe("経路が見つかりません");
  });

  it("入力検証の失敗（`msg`を持つ項目の配列）は、各項目の`msg`を順に「 / 」でつなぐ", () => {
    const detail = [
      { loc: ["body", "distance_km"], msg: "Input should be less than 200", type: "less_than" },
      { loc: ["body", "start"], msg: "Field required", type: "missing" },
    ];

    expect(formatErrorDetail(detail)).toBe("Input should be less than 200 / Field required");
  });

  it("配列のうち`msg`を持たない項目は飛ばし、文字列でない`msg`は文字列にする", () => {
    const detail = [null, "bare", { loc: ["body"] }, { msg: 42 }];

    expect(formatErrorDetail(detail)).toBe("42");
  });

  it.each([
    ["`msg`を持つ項目が無い配列", [{ loc: ["body"] }], '[{"loc":["body"]}]'],
    ["空の配列", [], "[]"],
    ["配列でないオブジェクト", { reason: "busy" }, '{"reason":"busy"}'],
    ["数値", 503, "503"],
  ])("%sは、JSONの文字列にして中身を残す", (_scene, detail, expected) => {
    expect(formatErrorDetail(detail)).toBe(expected);
  });
});
