// @vitest-environment node
/**
 * `lib/cardinalLabel.ts`——角度を方位の呼び名へ丸める。
 *
 * 呼び名と丸めの答えはbackendが出す表（生成物`geo-expectations.json`の`compass_label`）が持つ。表の入力は区分の
 * 境界ちょうどとその少し手前・負の角度・一周を超える角度で、丸めの向き・正規化・呼び名の並びはこの表で決まる
 * （testing-patterns-data.md「パターン11」）。
 *
 * ここで見ないもの:
 * - 表の答えが正しいこと → backendのテスト（`domain/geo.py`）
 * - 呼び名をどこに出すか → 使う部品（`features/conditions/WindBearingSlider`等）
 */
import { describe, expect, it } from "vitest";

import geoExpectations from "@/types/generated/geo-expectations.json";
import { cardinalLabel } from "@/lib/cardinalLabel";

describe("cardinalLabel", () => {
  it("backendが出す表の全行で、backendと同じ呼び名になる", () => {
    const rows = geoExpectations.compass_label;
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(cardinalLabel(row.bearing_deg), `${row.bearing_deg}度`).toBe(row.label);
    }
  });
});
