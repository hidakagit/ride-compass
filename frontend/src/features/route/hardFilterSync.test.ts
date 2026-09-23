// @vitest-environment node
import { describe, expect, it } from "vitest";

import { syncHardFilterKeys } from "./hardFilterSync";

describe("syncHardFilterKeys（保存された除外条件を、今の除外条件の一覧へ合わせる）", () => {
  const canonical = { stairs: true, unpaved: false };

  it("キーは今の一覧と同じになる（backendはキーの完全一致を要求する）", () => {
    const synced = syncHardFilterKeys({ stairs: false, removed_filter: true }, canonical);
    expect(Object.keys(synced).sort()).toEqual(["stairs", "unpaved"]);
  });

  it("保存されている選択は残し、新しく増えた条件は既定値にする", () => {
    expect(syncHardFilterKeys({ stairs: false }, canonical)).toEqual({ stairs: false, unpaved: false });
  });

  it("真偽値でない保存値は選択として扱わず、既定値にする", () => {
    const stored = { stairs: "yes", unpaved: null } as unknown as Record<string, boolean>;
    expect(syncHardFilterKeys(stored, canonical)).toEqual(canonical);
  });
});
