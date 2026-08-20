// @vitest-environment node
import { describe, expect, it } from "vitest";
import surfaceTags from "@/types/generated/surface-tags.json";
import { buildCombinedLegendFilterExpression, buildLegendFilterExpression } from "./legendFilter";
import {
  ROAD_FILTER_AXES,
  ROAD_LINE_COLOR_AXIS_ID,
  ROAD_LINE_WIDTH_AXIS_ID,
  ROAD_LINE_DASH_AXIS_ID,
  SURFACE_GROUPS,
  getRoadFilterAxis,
} from "./roadFilterAxes";

describe("路面グループとbackend正準分類（surface-tags.json）の整合", () => {
  // surface-tags.jsonはbackendのdomain/road.py（GOOD/BAD_OSM_SURFACE_TAGS）から
  // backend/scripts/export_openapi.pyが生成する（CIのapi-contractジョブがドリフト検知）。
  // かつてchipsealが表示上はアスファルト（緑）なのに評価上は不明（road_scoreの分母から
  // 除外）で、地図の色とルート評価が食い違っていた（設計レビューF1）。この検証で
  // 「片側だけタグを増減した」状態をCIで検出する。
  const good = new Set(surfaceTags.good);
  const bad = new Set(surfaceTags.bad);
  const allGroupValues = SURFACE_GROUPS.flatMap((g) => g.values);

  it("表示グループの全タグ集合は正準分類済みタグ（good∪bad）と一致し、重複割り当ても無い", () => {
    expect(new Set(allGroupValues)).toEqual(new Set([...surfaceTags.good, ...surfaceTags.bad]));
    expect(new Set(allGroupValues).size).toBe(allGroupValues.length);
  });

  it("舗装系グループ（asphalt/concrete）はgoodのみ、未舗装系（gravel/dirt）はbadのみを含む", () => {
    const byKey = Object.fromEntries(SURFACE_GROUPS.map((g) => [g.key, g.values]));
    for (const tag of [...byKey.asphalt, ...byKey.concrete]) {
      expect(good.has(tag), `${tag} は舗装系グループにあるが正準分類はgoodでない`).toBe(true);
    }
    for (const tag of [...byKey.gravel, ...byKey.dirt]) {
      expect(bad.has(tag), `${tag} は未舗装系グループにあるが正準分類はbadでない`).toBe(true);
    }
    // 「石畳・敷石」はgood（paving_stones/bricks）とbad（sett等）が混在する意図的な
    // 中立グループ（roadFilterAxes.tsのコメント参照）。混在が保たれていることを確認する。
    expect(byKey.stones.some((tag) => good.has(tag))).toBe(true);
    expect(byKey.stones.some((tag) => bad.has(tag))).toBe(true);
  });
});

describe("roadFilterAxes", () => {
  it("2つの独立した軸（路面の種類・道路の種類）を定義している", () => {
    // 「舗装/未舗装」はsurfaceタグを2値に粗く束ねただけで路面の種類と独立でないため廃止済み
    // （backend/app/domain/road.pyのGOOD/BAD_OSM_SURFACE_TAGSと同一のsurfaceタグに基づく）
    expect(ROAD_FILTER_AXES.map((a) => a.id)).toEqual(["surface", "highway"]);
    expect(ROAD_LINE_COLOR_AXIS_ID).toBe("surface");
  });

  it("各軸は凡例と色式を持ち、凡例の色・キーに重複がない（見分けられる配色）", () => {
    for (const axis of ROAD_FILTER_AXES) {
      expect(axis.legend.length).toBeGreaterThanOrEqual(3);
      expect(axis.colorExpression.length).toBeGreaterThan(0);
      const colors = axis.legend.map((entry) => entry.color);
      expect(new Set(colors).size).toBe(colors.length);
      const keys = axis.legend.map((entry) => entry.key);
      expect(new Set(keys).size).toBe(keys.length);
    }
  });

  it("各軸はmatch式で、プロパティ欠落・未知タグ時のフォールバック色（グレー）を末尾に持つ", () => {
    for (const id of ["surface", "highway"] as const) {
      const axis = getRoadFilterAxis(id);
      expect(axis.colorExpression[0]).toBe("match");
      // プロパティ欠落（null）をmatchへ直接渡さないようcoalesceで空文字へ倒す
      expect(axis.colorExpression[1]).toEqual(["coalesce", ["get", id], ""]);
      expect(axis.colorExpression[axis.colorExpression.length - 1]).toBe("#9ca3af");
    }
  });

  it("凡例の色と色式に出てくる色が一致する（凡例に無い色で描画されない）", () => {
    for (const axis of ROAD_FILTER_AXES) {
      const legendColors = new Set(axis.legend.map((entry) => entry.color));
      const expressionColors = axis.colorExpression.filter(
        (item): item is string => typeof item === "string" && item.startsWith("#"),
      );
      for (const color of expressionColors) {
        expect(legendColors.has(color)).toBe(true);
      }
    }
  });

  it("getRoadFilterAxisは未知のIDでも最初の軸へフォールバックする", () => {
    // @ts-expect-error 実行時の防御を確認するため意図的に不正なIDを渡す
    expect(getRoadFilterAxis("unknown")).toBe(ROAD_FILTER_AXES[0]);
  });

  // 実機フィードバック「道路種別が支配的な場合、色がすべて灰色で違和感がある」への対応
  // （「路面の種類」OFF・「道路の種類」ONのときは道路の種類側の濃淡パレット、
  // COLOR_HIGHWAY_*を使う）。太さ軸（道路の種類）も色軸（路面の種類）と同じく
  // opacityExpressionを持つようになったことを確認する。
  it("太さ軸（道路の種類）もopacityExpressionを持つ（「路面の種類」OFF時に地図の色分けへ使う）", () => {
    expect(getRoadFilterAxis("highway").opacityExpression).toBeDefined();
  });

  // 竹（1次/2次の地図上表現の統一）でSURFACE_GROUPSから評価色（緑〜赤）を排した理由と
  // 同じ懸念が、道路の種類の濃淡パレットにも当てはまる。両軸を同時にONにすることは無い
  // （路面の種類がONの間は道路の種類側の色は使われない、MapView.tsx: applyRoadLayerState）が、
  // 2次のramp軸（car_stress等、axisLayers.ts: AXIS_RAMP_COLORS）とは同時に表示されうるため、
  // 評価色の緑〜赤を道路の種類の配色として使わないことを回帰確認する。
  it("道路の種類の配色は2次のramp軸の評価色（AXIS_RAMP_COLORS）と重複しない", async () => {
    const { AXIS_RAMP_COLORS } = await import("./axisLayers");
    const highwayColors = getRoadFilterAxis("highway").legend.map((entry) => entry.color.toLowerCase());
    const rampColors = new Set(AXIS_RAMP_COLORS.map((c) => c.toLowerCase()));
    for (const color of highwayColors) {
      expect(rampColors.has(color), `${color} はAXIS_RAMP_COLORSと重複している`).toBe(false);
    }
  });

  // 色を2軸掛け合わせず、道路の種類は太さ（line-width）で別チャンネルとして地図に反映する
  // （色を掛け合わせると最大30通りになり細い線では判別できないため）。
  describe("道路の種類の太さ（widthExpression）", () => {
    it("色軸（路面の種類）はwidthExpressionを持たず、太さ軸（道路の種類）だけが持つ", () => {
      expect(ROAD_LINE_WIDTH_AXIS_ID).toBe("highway");
      expect(getRoadFilterAxis("surface").widthExpression).toBeUndefined();
      expect(getRoadFilterAxis("highway").widthExpression).toBeDefined();
    });

    it("match式で、幹線道路ほど太く・自転車専用道路ほど細い（実際の道幅の感覚に合わせる）", () => {
      const widthExpression = getRoadFilterAxis("highway").widthExpression!;
      expect(widthExpression[0]).toBe("match");

      function widthFor(values: string[]): number {
        const index = widthExpression.findIndex(
          (item) => Array.isArray(item) && item.length === values.length && item.every((v, i) => v === values[i])
        );
        expect(index).toBeGreaterThan(-1);
        return widthExpression[index + 1] as number;
      }

      const arterialWidth = widthFor(["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"]);
      const cyclewayWidth = widthFor(["cycleway", "path", "footway", "pedestrian", "bridleway", "steps"]);
      expect(arterialWidth).toBeGreaterThan(cyclewayWidth);

      // プロパティ欠落・未知タグ時のフォールバック太さが末尾にある
      const fallbackWidth = widthExpression[widthExpression.length - 1];
      expect(typeof fallbackWidth).toBe("number");
    });

    // 凡例側にもwidthを持たせておくことで、ダイアログ・サイドバー凡例のプレビューが
    // 色スウォッチではなく実際の太さバーを描ける（色はこの軸では地図に出ないため）。
    it("道路の種類の凡例エントリは全て（不明・他を含め）widthを持ち、路面の種類は持たない", () => {
      for (const entry of getRoadFilterAxis("highway").legend) {
        expect(typeof entry.width).toBe("number");
      }
      for (const entry of getRoadFilterAxis("surface").legend) {
        expect(entry.width).toBeUndefined();
      }
    });
  });

  // 「不明・他」は実際の道幅と無関係なタグ欠落・未分類の受け皿なので、太さでは目立たせず
  // 破線（line-dasharray）にして既知カテゴリと見分けられるようにする。
  describe("道路の種類の線種（dashArrayExpression、不明・他だけ破線）", () => {
    it("色軸（路面の種類）はdashArrayExpressionを持たず、太さ軸（道路の種類）だけが持つ", () => {
      expect(ROAD_LINE_DASH_AXIS_ID).toBe("highway");
      expect(getRoadFilterAxis("surface").dashArrayExpression).toBeUndefined();
      expect(getRoadFilterAxis("highway").dashArrayExpression).toBeDefined();
    });

    it("match式で、既知カテゴリは実線・未知タグは破線になる", () => {
      const dashArrayExpression = getRoadFilterAxis("highway").dashArrayExpression!;
      expect(dashArrayExpression[0]).toBe("match");

      const knownValues = dashArrayExpression[2] as unknown[];
      // 出力の生配列（[1, 0]等）をそのままmatchへ渡すとMapLibreが式と誤解釈してaddLayerが
      // 失敗する（実機で確認済みの不具合）ため、["literal", [...]]で包む必要がある。
      const solidBranch = dashArrayExpression[3] as unknown[];
      const fallbackBranch = dashArrayExpression[4] as unknown[];

      expect(knownValues).toContain("motorway");
      expect(knownValues).toContain("cycleway");
      expect(solidBranch[0]).toBe("literal");
      expect(fallbackBranch[0]).toBe("literal");

      const solidPattern = solidBranch[1] as number[];
      const fallbackPattern = fallbackBranch[1] as number[];
      expect(solidPattern).not.toEqual(fallbackPattern);
      // 実線=途切れなし（off=0）、破線=on/offとも0より大きい
      expect(solidPattern).toEqual([1, 0]);
      expect(fallbackPattern.every((v) => v > 0)).toBe(true);
    });

    it("凡例側は「不明・他」だけdashed:trueを持ち、既知カテゴリは持たない", () => {
      const highway = getRoadFilterAxis("highway");
      const unknownEntry = highway.legend.find((e) => e.key === "unknown")!;
      expect(unknownEntry.dashed).toBe(true);
      for (const entry of highway.legend) {
        if (entry.key === "unknown") continue;
        expect(entry.dashed).toBeUndefined();
      }
    });
  });

  describe("buildLegendFilterExpression（路面軸の凡例）", () => {
    it("非表示カテゴリが無ければnull（フィルタ解除）", () => {
      expect(buildLegendFilterExpression(getRoadFilterAxis("surface").legend, [])).toBeNull();
    });

    it("非表示カテゴリの述語を否定してallで束ねる", () => {
      const surface = getRoadFilterAxis("surface");
      const gravelEntry = surface.legend.find((e) => e.key === "gravel")!;
      const unknownEntry = surface.legend.find((e) => e.key === "unknown")!;

      const filter = buildLegendFilterExpression(surface.legend, ["gravel", "unknown"]);

      expect(filter).toEqual(["all", ["!", gravelEntry.filter], ["!", unknownEntry.filter]]);
    });

    it("未知のキー（軸切替や定義変更の残骸）は無視する", () => {
      expect(buildLegendFilterExpression(getRoadFilterAxis("surface").legend, ["no-such-key"])).toBeNull();
    });

    it("全軸の全凡例キーがフィルタ述語を持つ", () => {
      for (const axis of ROAD_FILTER_AXES) {
        for (const entry of axis.legend) {
          const filter = buildLegendFilterExpression(axis.legend, [entry.key]);
          expect(filter).toEqual(["all", ["!", entry.filter]]);
        }
      }
    });
  });

  describe("buildCombinedLegendFilterExpression（路面の種類・道路の種類の同時絞り込み）", () => {
    it("どの軸にも非表示カテゴリが無ければnull", () => {
      const axes = ROAD_FILTER_AXES.map((axis) => ({ legend: axis.legend, hiddenKeys: [] }));
      expect(buildCombinedLegendFilterExpression(axes)).toBeNull();
    });

    it("1軸だけ絞り込みがあれば、その軸のbuildLegendFilterExpressionと同じ式になる", () => {
      const surface = getRoadFilterAxis("surface");
      const axes = [
        { legend: surface.legend, hiddenKeys: ["gravel"] },
        { legend: getRoadFilterAxis("highway").legend, hiddenKeys: [] },
      ];
      expect(buildCombinedLegendFilterExpression(axes)).toEqual(buildLegendFilterExpression(surface.legend, ["gravel"]));
    });

    it("複数軸に絞り込みがあれば、各軸の式をallで束ねる（路面の種類=アスファルトのみ かつ 道路の種類=自転車・歩行者道のみ、のような組み合わせ）", () => {
      const surface = getRoadFilterAxis("surface");
      const highway = getRoadFilterAxis("highway");
      const hiddenSurfaceKeys = surface.legend.map((e) => e.key).filter((k) => k !== "asphalt");
      const hiddenHighwayKeys = highway.legend.map((e) => e.key).filter((k) => k !== "cycleway");

      const filter = buildCombinedLegendFilterExpression([
        { legend: surface.legend, hiddenKeys: hiddenSurfaceKeys },
        { legend: highway.legend, hiddenKeys: hiddenHighwayKeys },
      ]);

      expect(filter).toEqual([
        "all",
        buildLegendFilterExpression(surface.legend, hiddenSurfaceKeys),
        buildLegendFilterExpression(highway.legend, hiddenHighwayKeys),
      ]);
    });
  });
});
