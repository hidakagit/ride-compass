// @vitest-environment node
// 評価軸カタログ（改善計画T168）のaxisId対応ドリフト検知。DOM不要のためnode環境で実行する。

import { describe, expect, it } from "vitest";

import { PREFERENCE_AXES } from "./evaluationAxes";
import { axisMaterials } from "@/components/Map/primaryAttributes";

describe("evaluationAxes", () => {
  // ドリフト検知: axisIdを持つ軸は、必ずaxis-catalog.json（axisMaterials経由）に実在する
  // 軸を指していること。誤字・削除済み軸idを指すと、研究タブの材料一覧（T168）が
  // 常に空配列（＝何も表示しない）のまま気づかれずに壊れるため、axisMaterialsが空を返す
  // ことを「軸が無い」の判定に使わない設計（primaryAttributes.tsのコメント）どおり、
  // ここで明示的にaxisMaterialsの結果が非空であることを確認する。
  it("axisIdを持つ全軸は、axis-catalog.json上に実在し材料を1件以上持つ", () => {
    for (const axis of PREFERENCE_AXES) {
      if (!axis.axisId) continue;
      expect(axisMaterials(axis.axisId).length, `${axis.weightKey}のaxisId(${axis.axisId})に材料が無い`).toBeGreaterThan(
        0,
      );
    }
  });

  // windはレジストリ未登録（axisLayers.tsのAXIS_LABELSコメント参照）のため、意図的に
  // axisIdを持たない。誤って登録され忘れているだけかもしれない他の軸と区別するため
  // 明示的に確認する。
  it("wind_weightは意図的にaxisIdを持たない（レジストリ未登録軸）", () => {
    const wind = PREFERENCE_AXES.find((axis) => axis.weightKey === "wind_weight");
    expect(wind?.axisId).toBeUndefined();
  });

  // 全7軸のうちwind以外の6軸がaxisIdを持つこと（登録漏れの検知）。
  it("wind以外の全軸がaxisIdを持つ", () => {
    const withoutAxisId = PREFERENCE_AXES.filter((axis) => !axis.axisId).map((axis) => axis.weightKey);
    expect(withoutAxisId).toEqual(["wind_weight"]);
  });
});
