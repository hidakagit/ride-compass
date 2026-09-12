// @vitest-environment node
// 評価軸カタログ（改善計画T168）のaxisId対応ドリフト検知。DOM不要のためnode環境で実行する。

import { describe, expect, it } from "vitest";

import type { PreferenceAxisDef } from "./evaluationAxes";
import { PREFERENCE_AXES, preferenceAxisFromCatalog } from "./evaluationAxes";
import type { CatalogAxis } from "@/components/Map/axisLayers";
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
  // 地図チップに出ない軸（SECONDARY_AXESから落ちる軸）。どの軸が該当するかは軸スタジオの
  // 設定（category・show_map_icon）で決まり生成物の再取り込みで変わるため、軸idを
  // 名指しせずSECONDARY_AXESとの差から導く。
  const AXES_WITHOUT_MAP_LAYER = PREFERENCE_AXES.map((axis) => axis.axisId).filter(
    (axisId) => !SECONDARY_AXES.some((axis) => axis.axisId === axisId)
  );

  // 誤字・削除済み軸idを指していると、研究タブの材料一覧（T168）が常に空配列のまま
  // 気づかれずに壊れる。「材料を1件以上持つ」ではなく「カタログに実在する」で見るのは、
  // 材料が実行時の動的気象だけの軸（風）はprimary_attribute_idsが正当に空になるため
  // ——空であること自体は誤りの証拠にならない。
  it("全軸がaxis-catalog.json上に実在する", () => {
    const catalogIds = new Set((axisCatalog.axes as CatalogAxisInputs[]).map((axis) => axis.axis_id));
    for (const axis of PREFERENCE_AXES) {
      expect(catalogIds.has(axis.axisId), `axisId(${axis.axisId})がカタログに無い`).toBe(true);
    }
  });

  // 地図チップに出すかどうかと、重みを設定できるかどうかは別の判断（evaluationAxes.ts参照）。
  // 地図チップから落ちた公開軸も重み一覧には必ず出ること。
  it("地図チップに出ない公開軸も重み一覧には出る", () => {
    const catalogIds = (axisCatalog.axes as CatalogAxisInputs[]).map((axis) => axis.axis_id);
    const preferenceIds = PREFERENCE_AXES.map((axis) => axis.axisId);
    for (const axisId of catalogIds) {
      expect(preferenceIds, `公開軸(${axisId})が重み一覧に無い`).toContain(axisId);
    }
  });

  // 実機フィードバック「研究タブ、2次要素の調整の仕方が全然わからない。地図表示、地図の
  // 見え方パネルと考え方を併せて再設計して」への対応。SECONDARY_AXES（地図チップ・
  // 地図の見え方パネルの推定グループが共有する単一ソース）の並び・ラベルをそのまま
  // なぞっていることを回帰確認する。
  it("先頭は地図（SECONDARY_AXES）と同じ並び順・同じラベルで並ぶ", () => {
    const head = PREFERENCE_AXES.slice(0, SECONDARY_AXES.length);
    expect(head.map((axis) => axis.axisId)).toEqual(SECONDARY_AXES.map((axis) => axis.axisId));
    expect(head.map((axis) => axis.label)).toEqual(SECONDARY_AXES.map((axis) => axis.label));
  });

  // 地図チップに出ない軸はカタログの並び順のまま後ろへ続く（evaluationAxes.ts参照）。
  it("地図チップに出ない軸は末尾へ続く", () => {
    const tail = PREFERENCE_AXES.slice(SECONDARY_AXES.length).map((axis) => axis.axisId);
    expect(tail).toEqual(AXES_WITHOUT_MAP_LAYER);
  });

  // ドリフト検知: 説明文はaxis-catalog.jsonのaxes[].description（backendのAXIS_DEFINITIONS
  // 由来）から引く。生成物側に説明文が無いと黙って空文字になり、RouteSettingsPanel/
  // RouteAxisProfileにその軸の説明文だけが表示されない不具合が気づかれないまま残る。
  it("全軸が説明文を持つ（空文字への黙ったフォールバックが無い）", () => {
    const missing = PREFERENCE_AXES.filter((axis) => axis.description === "").map((axis) => axis.axisId);
    expect(missing, `説明文が無い軸: ${missing.join(", ")}`).toEqual([]);
  });

  // 回帰テスト（改善計画T473）: 以前はSECONDARY_AXES由来の全軸のdedicatedWayValueLayerを
  // 「kind='ramp'軸のみを含むため常にfalse」という誤った前提で一律falseに固定していたが、
  // gradientはkind="none"（材料がタイル非依存）でありながらdedicated_way_value_layer=true
  // という組み合わせが実在するため、axis-catalog.json（backend由来）の値と食い違っていた。
  // page.tsx（dedicatedWayValueBoundaries）がPREFERENCE_AXESのこのフィールドを軸カタログ
  // 取得完了前のフォールバック値として使うため、静的生成物の値と一致していないと
  // gradientの評価軸グループ色分けしきい値配線が取得完了前だけ欠落する。
  it("PREFERENCE_AXESのdedicatedWayValueLayerはaxis-catalog.jsonのdedicated_way_value_layerと一致する", () => {
    const catalogAxesById = new Map(
      (axisCatalog.axes as { axis_id: string; dedicated_way_value_layer?: boolean }[]).map((axis) => [
        axis.axis_id,
        axis.dedicated_way_value_layer ?? false,
      ])
    );
    // 除外は置かない。地図チップに出ない軸（wind等）こそ
    // dedicated_way_value_layer=trueの実例で、**検証したい対象そのもの**である。
    for (const axis of PREFERENCE_AXES) {
      expect(
        axis.dedicatedWayValueLayer,
        `axisId(${axis.axisId})のdedicatedWayValueLayerが一致しない`
      ).toBe(catalogAxesById.get(axis.axisId));
    }
    // gradientは実際にdedicated_way_value_layer=trueを持つ代表例（回帰の直接検知）。
    expect(PREFERENCE_AXES.find((axis) => axis.axisId === "gradient")?.dedicatedWayValueLayer).toBe(true);
  });

  // 実行時API経路（useAxisCatalog: buildCatalog）と静的フォールバック（PREFERENCE_AXES）が
  // 同じ変換を通ることを固定する。別々に組み立てていたころ、実行時経路だけ
  // materialBreakdownを落とし、静的経路の一部だけdisplayThresholdsOverrideを落としていた
  // ——PreferenceAxisDefのフィールドがすべてoptionalのため型検査では現れない。
  it("同じカタログ1件からは、どの経路でも同じPreferenceAxisDefができる", () => {
    const catalogAxes = axisCatalog.axes as CatalogAxis[];
    expect(catalogAxes.length).toBeGreaterThan(0);

    for (const axis of catalogAxes) {
      const fromStatic = PREFERENCE_AXES.find((entry) => entry.axisId === axis.axis_id);
      expect(fromStatic, `axisId(${axis.axis_id})が静的フォールバックに無い`).toBeDefined();
      expect(fromStatic).toEqual(preferenceAxisFromCatalog(axis));
    }
  });

  // 経路が1本になった以上、両経路の一致だけでは「その1本がフィールドを落とした」ことを
  // 見つけられない。カタログ側に値がある軸について、変換後にも値が残ることを見る。
  it("カタログが値を持つフィールドは変換後も落ちない", () => {
    const catalogAxes = axisCatalog.axes as CatalogAxis[];
    const checks: { field: string; has: (axis: CatalogAxis) => boolean; kept: (def: PreferenceAxisDef) => boolean }[] = [
      {
        field: "display_thresholds_override",
        has: (axis) => (axis.display_thresholds_override?.length ?? 0) > 0,
        kept: (def) => (def.displayThresholdsOverride?.length ?? 0) > 0,
      },
      {
        field: "display_band_labels_override",
        has: (axis) => (axis.display_band_labels_override?.length ?? 0) > 0,
        kept: (def) => (def.displayBandLabelsOverride?.length ?? 0) > 0,
      },
      {
        field: "material_breakdown",
        has: (axis) => (axis.material_breakdown?.length ?? 0) > 0,
        kept: (def) => (def.materialBreakdown?.length ?? 0) > 0,
      },
      {
        field: "raw_value_unit",
        has: (axis) => Boolean(axis.raw_value_unit),
        kept: (def) => Boolean(def.rawValueUnit),
      },
    ];

    for (const check of checks) {
      const withValue = catalogAxes.filter(check.has);
      // 検査が空回りしていないこと（カタログに実例が1つも無ければ、この検査は何も守らない）。
      expect(withValue.length, `${check.field}を持つ軸がカタログに無い`).toBeGreaterThan(0);
      for (const axis of withValue) {
        expect(check.kept(preferenceAxisFromCatalog(axis)), `${axis.axis_id}の${check.field}が落ちている`).toBe(true);
      }
    }
  });

  // 並び順はSECONDARY_AXESをなぞり、そこに無い公開軸はカタログ順で後ろへ足す。
  it("PREFERENCE_AXESは公開軸を1つも落とさない", () => {
    const catalogIds = (axisCatalog.axes as CatalogAxis[]).map((axis) => axis.axis_id).sort();
    expect(PREFERENCE_AXES.map((axis) => axis.axisId).sort()).toEqual(catalogIds);
  });
});
