// @vitest-environment node
// 評価軸カタログ（改善計画T168）のaxisId対応ドリフト検知。DOM不要のためnode環境で実行する。

import { describe, expect, it } from "vitest";

import { PREFERENCE_AXES } from "./evaluationAxes";
import { SECONDARY_AXES } from "@/components/Map/secondaryAxes";
import axisCatalog from "@/types/generated/axis-catalog.json";

interface CatalogAxisInputs {
  axis_id: string;
  primary_attribute_ids: string[];
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
  // 必ずaxis-catalog.json（axes[].primary_attribute_ids）に実在する軸を指していること。
  // 誤字・削除済み軸idを指すと、研究タブの材料一覧（T168）が常に空配列（＝何も表示しない）
  // のまま気づかれずに壊れるため、ここで明示的にprimary_attribute_idsの結果が非空である
  // ことを確認する（改善計画T308: axisMaterials自体は撤去済み[primaryAttributes.ts参照]、
  // このテストはビルド時静的生成物自体の整合性検証のため、その生成元
  // axes[].primary_attribute_idsを直接見る。死コード監査（過去の監査）で、GET
  // /api/axis-catalog（実行時API）と同じキー名の唯一の読み手として、以前の重複キー
  // inputsからこちらへ移行した）。
  // 改善計画T367: bicycle_infra_qualityは地図表示に対応した（show_map_icon=true）ため
  // SECONDARY_AXESへ自然に含まれるようになり、地図レイヤーを持たない軸はwindのみになった。
  const AXES_WITHOUT_MAP_LAYER = ["wind"];

  it("地図レイヤーを持たない軸(wind)以外は、axis-catalog.json上に実在し材料を1件以上持つ", () => {
    const axesWithInputs = axisCatalog.axes as CatalogAxisInputs[];
    for (const axis of PREFERENCE_AXES) {
      if (AXES_WITHOUT_MAP_LAYER.includes(axis.axisId)) continue;
      const inputs = axesWithInputs.find((a) => a.axis_id === axis.axisId)?.primary_attribute_ids ?? [];
      expect(inputs.length, `axisId(${axis.axisId})に材料が無い`).toBeGreaterThan(0);
    }
  });

  // windは表示カタログ（axes[]）に対応軸を持たない（動的データ由来でレイヤーなし）。
  // 誤って登録され忘れているだけかもしれない他の軸と区別するため明示的に確認する。
  it("windは表示カタログ（SECONDARY_AXES）に存在しない", () => {
    for (const axisId of AXES_WITHOUT_MAP_LAYER) {
      expect(SECONDARY_AXES.some((axis) => axis.axisId === axisId)).toBe(false);
    }
  });

  // 実機フィードバック「研究タブ、2次要素の調整の仕方が全然わからない。地図表示、地図の
  // 見え方パネルと考え方を併せて再設計して」への対応。SECONDARY_AXES（地図チップ・
  // 地図の見え方パネルの推定グループが共有する単一ソース）の並び・ラベルをそのまま
  // なぞっていることを回帰確認する。
  it("地図レイヤーを持たない軸を除くと、地図（SECONDARY_AXES）と同じ並び順・同じラベルで並ぶ", () => {
    const withoutMapLayerAxes = PREFERENCE_AXES.filter((axis) => !AXES_WITHOUT_MAP_LAYER.includes(axis.axisId));
    expect(withoutMapLayerAxes.map((axis) => axis.axisId)).toEqual(SECONDARY_AXES.map((axis) => axis.axisId));
    expect(withoutMapLayerAxes.map((axis) => axis.label)).toEqual(SECONDARY_AXES.map((axis) => axis.label));
  });

  // windはSECONDARY_AXESに対応軸を持たないため、末尾に追加される
  // （evaluationAxes.ts: PREFERENCE_AXESの定義順）。
  it("windはこの位置（末尾）に位置する", () => {
    expect(PREFERENCE_AXES.at(-1)?.axisId).toBe("wind");
  });
});
