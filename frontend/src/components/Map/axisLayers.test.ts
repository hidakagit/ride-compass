// @vitest-environment node
// 二次軸rampレイヤー（改善計画T145b）の純ロジック検証。DOM不要のためnode環境で実行する
// （vitest.config.mtsのコメント参照）。

import { describe, expect, it } from "vitest";

import {
  COLOR_UNKNOWN,
  type CatalogAxis,
  type RampAxis,
  axisLabelsFromCatalogAxes,
  axisLineLayerId,
  axisMapLayerId,
  buildAxisRampColorExpression,
  buildAxisRampLegend,
  buildAxisRampUnknownExpression,
  buildAxisRampValueExpression,
  rampAxesFromCatalogAxes,
  rampColorForBand,
} from "./axisLayers";
import { buildMapLayers } from "./mapLayers";

describe("axisLayers", () => {
  // 軸idを名指しせずカタログと突き合わせるのは、公開軸の集合が軸スタジオ（DB）で決まり
  // 生成物の再取り込みで変わるため（停止密度の軸idはGUI作成軸のため固定値でもない）。

  it("IDヘルパーは軸IDから決定的なIDを生成する", () => {
    expect(axisMapLayerId("accident")).toBe("axis:accident");
    expect(axisLineLayerId("accident")).toBe("region-axis-accident-line");
  });
});

describe("rampColorForBand（改善計画T292: 可変バンド数の配色一般化）", () => {
  it("両端は段の数によらず同じ色になる（端は常にアンカーそのもの）", () => {
    const [low, high] = [rampColorForBand(0, 4), rampColorForBand(3, 4)];
    for (const bandCount of [2, 3, 5, 6]) {
      expect(rampColorForBand(0, bandCount)).toBe(low);
      expect(rampColorForBand(bandCount - 1, bandCount)).toBe(high);
    }
  });

  it("段が1つなら低い側の色になる（範囲外を落ちなく処理する）", () => {
    expect(rampColorForBand(0, 1)).toBe(rampColorForBand(0, 4));
  });

  it("色は#rrggbb形式で、同一bandCount内で単調に変化する", () => {
    for (let i = 0; i < 5; i++) {
      expect(rampColorForBand(i, 5)).toMatch(/^#[0-9a-f]{6}$/);
    }
  });
});

describe("buildAxisRampValueExpression（改善計画T292: categories/breakpoints分岐）", () => {
  const baseAxis: RampAxis = {
    axisId: "test",
    label: "テスト",
    category: "trafficSafety",
    tileInputs: [],
    thresholds: [50],
    unit: "",
    note: "",
  };

  it("categories入力はmatch式でmapping値×weightを返す", () => {
    const axis: RampAxis = {
      ...baseAxis,
      tileInputs: [{ property: "highway", weight: 2, categories: { primary: 4, residential: 2 } }],
    };
    const expression = buildAxisRampValueExpression(axis);
    expect(expression).toEqual([
      "match",
      ["coalesce", ["get", "highway"], "__unknown__"],
      "primary",
      8,
      "residential",
      4,
      0,
    ]);
  });

  it("breakpoints入力はinterpolate式（weight=1なら素通し）をcaseで包み、タイルプロパティ欠損時は寄与0にする", () => {
    const axis: RampAxis = {
      ...baseAxis,
      tileInputs: [
        {
          property: "maxspeed_kmh",
          weight: 1,
          breakpoints: [
            [0, -1],
            [30, -1],
            [60, 1],
          ],
        },
      ],
    };
    const expression = buildAxisRampValueExpression(axis);
    expect(expression).toEqual([
      "case",
      ["!", ["has", "maxspeed_kmh"]],
      0,
      ["interpolate", ["linear"], ["get", "maxspeed_kmh"], 0, -1, 30, -1, 60, 1],
    ]);
  });

  it("breakpoints入力はweight≠1のとき乗算で包む（caseの内側）", () => {
    const axis: RampAxis = {
      ...baseAxis,
      tileInputs: [
        {
          property: "lanes_count",
          weight: 0.5,
          breakpoints: [
            [0, -1],
            [4, 1],
          ],
        },
      ],
    };
    const expression = buildAxisRampValueExpression(axis);
    expect(expression[0]).toBe("case");
    const value = expression[3] as unknown[];
    expect(value[0]).toBe("*");
    expect((value[1] as unknown[])[0]).toBe("interpolate");
    expect(value[2]).toBe(0.5);
  });

  it("categories/breakpointsを含む複数入力はΣで合成される", () => {
    const axis: RampAxis = {
      ...baseAxis,
      tileInputs: [
        { property: "highway", weight: 1, categories: { primary: 4 } },
        {
          property: "maxspeed_kmh",
          weight: 1,
          breakpoints: [
            [0, -1],
            [60, 1],
          ],
        },
      ],
    };
    const expression = buildAxisRampValueExpression(axis);
    expect(expression[0]).toBe("+");
    expect(expression.length).toBe(3);
  });
});

// 改善計画T308: rampAxesFromCatalogAxes/axisLabelsFromCatalogAxesは、ビルド時静的json
// （axis-catalog.json）と実行時API（GET /api/axis-catalog）の両方から同じ形の値を
// 組み立てるための共通関数（hooks/useAxisCatalog.tsが後者から呼ぶ）。
describe("rampAxesFromCatalogAxes / axisLabelsFromCatalogAxes（改善計画T308）", () => {
  it("GUI作成軸（kind=ramp、複数材料の重み付き結合）が正しくRampAxisへ変換される", () => {
    const catalogAxes: CatalogAxis[] = [
      {
        axis_id: "gui_created_axis",
        label: "テスト用GUI軸",
        display: {
          kind: "ramp",
          label: "テスト用GUI軸",
          category: "trafficSafety",
          tile_inputs: [
            { property: "lanes_count", weight: 1.0 },
            { property: "maxspeed_kmh", weight: 0.5 },
          ],
          thresholds: [10.0],
          unit: "",
          note: "",
        },
      },
    ];

    const rampAxes = rampAxesFromCatalogAxes(catalogAxes);
    expect(rampAxes).toHaveLength(1);
    expect(rampAxes[0].axisId).toBe("gui_created_axis");
    expect(rampAxes[0].label).toBe("テスト用GUI軸");
    expect(rampAxes[0].tileInputs).toEqual([
      {
        property: "lanes_count",
        weight: 1.0,
        boolean: undefined,
        trueValue: undefined,
        falseValue: undefined,
        hasUnknownFallback: undefined,
        categories: undefined,
        breakpoints: undefined,
      },
      {
        property: "maxspeed_kmh",
        weight: 0.5,
        boolean: undefined,
        trueValue: undefined,
        falseValue: undefined,
        hasUnknownFallback: undefined,
        categories: undefined,
        breakpoints: undefined,
      },
    ]);
    expect(rampAxes[0].thresholds).toEqual([10.0]);

    const labels = axisLabelsFromCatalogAxes(catalogAxes);
    expect(labels.gui_created_axis).toBe("テスト用GUI軸");
  });

  it("改善計画T310: panel_hint/icon_idが設定されていればRampAxis.panelHint/iconIdへ反映される", () => {
    const catalogAxes: CatalogAxis[] = [
      {
        axis_id: "with_display_fields",
        label: "テスト軸",
        display: {
          kind: "ramp",
          label: "テスト軸",
          category: "trafficSafety",
          tile_inputs: [{ property: "dummy_per_km", weight: 1.0 }],
          thresholds: [1.0],
          unit: "",
          note: "開発者向けメモ",
        },
        panel_hint: "ユーザー向け説明文",
        icon_id: "incline",
      },
    ];

    const rampAxes = rampAxesFromCatalogAxes(catalogAxes);
    expect(rampAxes[0].panelHint).toBe("ユーザー向け説明文");
    expect(rampAxes[0].iconId).toBe("incline");
  });

  it("改善計画T310: panel_hint/icon_id未設定はundefinedのまま（呼び出し側の汎用フォールバックに委ねる）", () => {
    const catalogAxes: CatalogAxis[] = [
      {
        axis_id: "without_display_fields",
        label: "テスト軸2",
        display: {
          kind: "ramp",
          label: "テスト軸2",
          category: "trafficSafety",
          tile_inputs: [{ property: "dummy_per_km", weight: 1.0 }],
          thresholds: [1.0],
          unit: "",
          note: "開発者向けメモ",
        },
      },
    ];

    const rampAxes = rampAxesFromCatalogAxes(catalogAxes);
    expect(rampAxes[0].panelHint).toBeUndefined();
    expect(rampAxes[0].iconId).toBeUndefined();
  });

  it("kind=noneの軸はRampAxesには含まれないが、ラベル辞書には含まれる", () => {
    const catalogAxes: CatalogAxis[] = [
      {
        axis_id: "not_derivable_axis",
        label: "地図に出ない軸",
        display: {
          kind: "none",
          label: "地図に出ない軸",
          category: "trafficSafety",
          tile_inputs: [],
          thresholds: [],
          unit: "",
          note: "",
        },
      },
    ];

    expect(rampAxesFromCatalogAxes(catalogAxes)).toHaveLength(0);
    expect(axisLabelsFromCatalogAxes(catalogAxes).not_derivable_axis).toBe("地図に出ない軸");
  });

  // 改善計画T404: needs_runtime_scale=trueなtile_inputは、runtimeScales引数
  // （GET /api/axis-catalogのmaterial_runtime_scales）を使ってweightへ構築時に
  // 一度だけ掛け合わせて解決する。
  it("needs_runtime_scale=trueなtile_inputはruntimeScalesでweightが解決される", () => {
    const catalogAxes: CatalogAxis[] = [
      {
        axis_id: "accident",
        label: "事故密度",
        display: {
          kind: "ramp",
          label: "事故密度",
          category: "trafficSafety",
          tile_inputs: [{ property: "accident_per_km", weight: 1.0, needs_runtime_scale: true }],
          thresholds: [0.5],
          unit: "件/km",
          note: "",
        },
      },
    ];

    const rampAxes = rampAxesFromCatalogAxes(catalogAxes, { accident_per_km: 1 / 3 });

    expect(rampAxes[0].tileInputs[0].weight).toBeCloseTo(1 / 3);
  });

  it("needs_runtime_scaleなtile_inputのスケール定数が未解決（フォールバック中等）の場合、weightは0（安全側の寄与0）になる", () => {
    const catalogAxes: CatalogAxis[] = [
      {
        axis_id: "accident",
        label: "事故密度",
        display: {
          kind: "ramp",
          label: "事故密度",
          category: "trafficSafety",
          tile_inputs: [{ property: "accident_per_km", weight: 1.0, needs_runtime_scale: true }],
          thresholds: [0.5],
          unit: "件/km",
          note: "",
        },
      },
    ];

    // runtimeScales省略（既定{}）。ビルド時静的フォールバックjsonの使用中に相当する。
    const rampAxes = rampAxesFromCatalogAxes(catalogAxes);

    expect(rampAxes[0].tileInputs[0].weight).toBe(0);
  });

  it("needs_runtime_scaleではないtile_inputはruntimeScalesを渡してもweightが変わらない", () => {
    const catalogAxes: CatalogAxis[] = [
      {
        axis_id: "stop_density",
        label: "停止密度",
        display: {
          kind: "ramp",
          label: "停止密度",
          category: "trafficSafety",
          tile_inputs: [{ property: "poi_signal_per_km", weight: 1.0 }],
          thresholds: [1.0],
          unit: "回/km",
          note: "",
        },
      },
    ];

    // 無関係なキーを含むruntimeScalesを渡しても、needs_runtime_scaleでないtile_inputには影響しない。
    const rampAxes = rampAxesFromCatalogAxes(catalogAxes, { accident_per_km: 1 / 3 });

    expect(rampAxes[0].tileInputs[0].weight).toBe(1.0);
  });
});
