// @vitest-environment node
// しきい値のまとめ入力の解釈・段階ラベルの件数合わせ（DOMを使わない純粋関数）。
import { describe, expect, it } from "vitest";
import { formatThresholdList, parseThresholdList, resizeBandLabels } from "./axisDraft";

describe("parseThresholdList", () => {
  it("カンマ・空白・改行・読点のどれで区切っても同じ並びとして読む", () => {
    const expected = [-10, -5, -1, 1];
    for (const text of ["-10, -5, -1, 1", "-10 -5 -1 1", "-10\n-5\n-1\n1", "-10、-5、-1、1"]) {
      expect(parseThresholdList(text)).toEqual({ values: expected, error: null });
    }
  });

  it("小数・空文字も扱える（空は0件、エラーにしない）", () => {
    expect(parseThresholdList("0.133, 0.267, 0.5").values).toEqual([0.133, 0.267, 0.5]);
    expect(parseThresholdList("   ")).toEqual({ values: [], error: null });
  });

  it("数値として読めない値・昇順でない並び・重複はエラーにする", () => {
    expect(parseThresholdList("1, abc, 3").error).toContain("abc");
    expect(parseThresholdList("3, 1").error).toContain("小さい順");
    expect(parseThresholdList("1, 1").error).toContain("小さい順");
  });

  it("formatThresholdListの出力はそのまま読み戻せる", () => {
    const values = [-10, -5, -1, 1, 2.5];
    expect(parseThresholdList(formatThresholdList(values)).values).toEqual(values);
  });
});

describe("resizeBandLabels", () => {
  it("増えた分は空欄で埋め、減った分は末尾から落とす", () => {
    expect(resizeBandLabels(["a", "b"], 4)).toEqual(["a", "b", "", ""]);
    expect(resizeBandLabels(["a", "b", "c"], 2)).toEqual(["a", "b"]);
    expect(resizeBandLabels([], 1)).toEqual([""]);
  });
});
