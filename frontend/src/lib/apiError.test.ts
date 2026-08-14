import { describe, expect, it } from "vitest";
import { formatErrorDetail } from "./apiError";

describe("formatErrorDetail", () => {
  it("文字列のdetailはそのまま返す", () => {
    expect(formatErrorDetail("エラー詳細")).toBe("エラー詳細");
  });

  it("FastAPIのバリデーションエラー配列(422)はmsgを結合した文字列にする", () => {
    const detail = [
      { loc: ["body", "distance_km"], msg: "Input should be less than or equal to 100", type: "less_than_equal" },
      { loc: ["body", "latitude"], msg: "Input should be greater than or equal to -90", type: "greater_than_equal" },
    ];
    expect(formatErrorDetail(detail)).toBe(
      "Input should be less than or equal to 100 / Input should be greater than or equal to -90",
    );
  });

  it("nullやundefinedはundefinedを返す(呼び出し元のフォールバックに委ねる)", () => {
    expect(formatErrorDetail(null)).toBeUndefined();
    expect(formatErrorDetail(undefined)).toBeUndefined();
  });
});
