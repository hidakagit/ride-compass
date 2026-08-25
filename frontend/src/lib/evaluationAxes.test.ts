// @vitest-environment node
// 評価軸カタログ（改善計画T168）のaxisId対応ドリフト検知。DOM不要のためnode環境で実行する。

import { describe, expect, it } from "vitest";

import { PREFERENCE_AXES } from "./evaluationAxes";
import { SECONDARY_AXES } from "@/components/Map/secondaryAxes";
import axisCatalog from "@/types/generated/axis-catalog.json";

interface CatalogAxisInputs {
  axis_id: string;
  inputs: string[];
}

describe("evaluationAxes", () => {
  // ドリフト検知（改善計画T221 Stage B）: PREFERENCE_AXESのaxisId集合は、
  // axis-catalog.jsonのpreference_defaults（backend AXIS_DEFINITIONSのdefault_weightの
  // 生成物）のキー集合と厳密一致すること。route_preferenceがaxis_idキーの辞書へ
  // 一般化されたことで旧来のTypeScriptコンパイル時のキー照合（Record<keyof
  // RoutePreferenceWeights, ...>）が効かなくなったため、このテストが代替する。
  it("PREFERENCE_AXESの軸集合はpreference_defaults（生成物）と一致する", () => {
    const axisIds = PREFERENCE_AXES.map((axis) => axis.axisId).sort();
    const defaultKeys = Object.keys(axisCatalog.preference_defaults).sort();
    expect(axisIds).toEqual(defaultKeys);
  });

  // ドリフト検知: wind（動的データ由来、表示カタログ未登録・材料一覧なし）を除く全軸は、
  // 必ずaxis-catalog.json（axes[].inputs）に実在する軸を指していること。誤字・
  // 削除済み軸idを指すと、研究タブの材料一覧（T168）が常に空配列（＝何も表示しない）
  // のまま気づかれずに壊れるため、ここで明示的にinputsの結果が非空であることを確認する
  // （改善計画T308: axisMaterials自体は撤去済み[primaryAttributes.ts参照]、このテストは
  // ビルド時静的生成物自体の整合性検証のため、その生成元axes[].inputsを直接見る）。
  it("wind以外の全軸は、axis-catalog.json上に実在し材料を1件以上持つ", () => {
    const axesWithInputs = axisCatalog.axes as CatalogAxisInputs[];
    for (const axis of PREFERENCE_AXES) {
      if (axis.axisId === "wind") continue;
      const inputs = axesWithInputs.find((a) => a.axis_id === axis.axisId)?.inputs ?? [];
      expect(inputs.length, `axisId(${axis.axisId})に材料が無い`).toBeGreaterThan(0);
    }
  });

  // windは表示カタログ（axes[]）に対応軸を持たない（動的データ由来でレイヤーなし）。
  // 誤って登録され忘れているだけかもしれない他の軸と区別するため明示的に確認する。
  it("windは表示カタログ（SECONDARY_AXES）に存在しない", () => {
    expect(SECONDARY_AXES.some((axis) => axis.axisId === "wind")).toBe(false);
  });

  // 実機フィードバック「研究タブ、2次要素の調整の仕方が全然わからない。地図表示、地図の
  // 見え方パネルと考え方を併せて再設計して」への対応。SECONDARY_AXES（地図チップ・
  // 地図の見え方パネルの推定グループが共有する単一ソース）の並び・ラベルをそのまま
  // なぞっていることを回帰確認する。
  it("wind以外の軸は、地図（SECONDARY_AXES）と同じ並び順・同じラベルで並ぶ", () => {
    const withoutWind = PREFERENCE_AXES.filter((axis) => axis.axisId !== "wind");
    expect(withoutWind.map((axis) => axis.axisId)).toEqual(SECONDARY_AXES.map((axis) => axis.axisId));
    expect(withoutWind.map((axis) => axis.label)).toEqual(SECONDARY_AXES.map((axis) => axis.label));
  });

  // windはSECONDARY_AXESに対応軸を持たないため、末尾に追加される。
  it("windは末尾に位置する", () => {
    expect(PREFERENCE_AXES[PREFERENCE_AXES.length - 1].axisId).toBe("wind");
  });
});
