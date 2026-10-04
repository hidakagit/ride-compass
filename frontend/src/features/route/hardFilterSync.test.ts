// @vitest-environment node
/**
 * `features/route/hardFilterSync.ts: syncHardFilterKeys`——保存された除外の指定を、今の正本のキー集合へ揃える。
 * 正本にあるキーは保存した選択を使い、保存に無いキーは正本の既定値で補い、正本に無いキーは落とす。
 *
 * ここで見ないもの:
 * - 保存値を読むときにこの関数を通すこと・壊れた保存値を捨てること → `useGenerationConditions.test.ts`
 * - 正本（`HardFilterPanel.tsx: DEFAULT_HARD_FILTERS`）の中身 → 生成物から導く側
 */
import { describe, expect, it } from "vitest";

import { syncHardFilterKeys } from "./hardFilterSync";

const CANONICAL = { exclude_a: true, exclude_b: false };

describe("syncHardFilterKeys", () => {
  it("正本と同じキーを持つ保存値は、保存した選択のまま返す", () => {
    expect(syncHardFilterKeys({ exclude_a: false, exclude_b: true }, CANONICAL)).toEqual({
      exclude_a: false,
      exclude_b: true,
    });
  });

  it("保存に無いキー（あとから足されたフィルタ）は正本の既定値で補う", () => {
    expect(syncHardFilterKeys({ exclude_a: false }, CANONICAL)).toEqual({ exclude_a: false, exclude_b: false });
  });

  it("正本に無いキー（取り下げられたフィルタ）は送る値に残さない", () => {
    expect(syncHardFilterKeys({ exclude_a: false, exclude_b: true, removed: true }, CANONICAL)).toEqual({
      exclude_a: false,
      exclude_b: true,
    });
  });

  it("保存値の中身が真偽でないキーは、正本の既定値にする", () => {
    const stored = JSON.parse('{"exclude_a": "false", "exclude_b": null}');
    expect(syncHardFilterKeys(stored, CANONICAL)).toEqual(CANONICAL);
  });
});
