// @vitest-environment node
import { describe, expect, it } from "vitest";
import { syncHardFilterKeys } from "./hardFilterSync";

// backendはキー集合の完全一致を要求するため、保存値と正本がずれた状態で送ると
// ルート生成が全て422になる。ずれの両方向（増えた・消えた）を固定する。
describe("syncHardFilterKeys", () => {
  const canonical = { motorway: true, no_bicycle: true, trunk: true };

  it("保存値のキーがすべて正本に在るときは選択をそのまま保つ", () => {
    const stored = { motorway: false, no_bicycle: true, trunk: false };

    expect(syncHardFilterKeys(stored, canonical)).toEqual(stored);
  });

  it("正本に増えたキーは既定値で補う（利用者の既存の選択は保つ）", () => {
    const stored = { motorway: false, no_bicycle: true };

    expect(syncHardFilterKeys(stored, canonical)).toEqual({
      motorway: false,
      no_bicycle: true,
      trunk: true,
    });
  });

  it("正本から消えたキーは落とす", () => {
    const stored = { motorway: false, no_bicycle: true, trunk: true, removed_filter: false };

    expect(syncHardFilterKeys(stored, canonical)).toEqual({
      motorway: false,
      no_bicycle: true,
      trunk: true,
    });
  });

  it("boolean以外が保存されていたキーは既定値へ倒す", () => {
    // 手で書き換えられた・古い形式が残っている場合。型を信じずに正本の型へ揃える。
    const stored = { motorway: "no" as unknown as boolean, no_bicycle: true, trunk: true };

    expect(syncHardFilterKeys(stored, canonical).motorway).toBe(true);
  });

  it("保存値が空でも正本の全キーを既定値で返す", () => {
    expect(syncHardFilterKeys({}, canonical)).toEqual(canonical);
  });
});
