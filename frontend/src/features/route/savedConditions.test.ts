// @vitest-environment node
/**
 * `features/route/savedConditions.ts`——保存した生成の条件の一覧を読む・名前の案・何が保存されるかの説明・一覧への入れ方。
 * 読むときは、今の画面が受け付けない件だけを捨ててほかの件を残し、除外は今の項目へ揃える。重みの説明は、上書きしない
 * 重みなら既定の配分を、上書きした重みなら公開軸へ揃えた配分を、軸ごとの割合で出す。同じ名前で保存すると上書きする。
 *
 * ここで見ないもの:
 * - 距離・候補数の範囲（`acceptedDistanceInput`・`acceptedMaxRoutesInput`） → `useGenerationConditions.test.ts`の保存値の読み直し
 * - 説明を保存の前と一覧の行のどこに出すか → `SavedConditionsPanel/SavedConditionsPanel.test.tsx`
 */
import { describe, expect, it } from "vitest";

import { DEFAULT_HARD_FILTERS } from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import { EMPTY_CATALOG } from "@/lib/axisCatalog";
import { catalogEntry, catalogOf } from "@/testing/catalogAxes";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import {
  describeConditions,
  readSavedConditions,
  suggestedConditionName,
  withSavedCondition,
  type SavedCondition,
} from "./savedConditions";

const POINT = { latitude: 35.1, longitude: 139.1 };

const ENTRY: SavedCondition = {
  name: "朝の荒川",
  routeMode: "destination",
  distance: "30",
  maxRoutes: "3",
  origin: POINT,
  waypoints: [POINT],
  destination: POINT,
  routePreference: { axis_a: 0.7 },
  hardFilters: DEFAULT_HARD_FILTERS,
};

describe("readSavedConditions", () => {
  it("読める件はそのまま返す", () => {
    expect(readSavedConditions(JSON.stringify([ENTRY, { ...ENTRY, name: "現在地から", origin: null }]))).toEqual([
      ENTRY,
      { ...ENTRY, name: "現在地から", origin: null },
    ]);
  });

  it.each([
    ["名前が空", { name: " " }],
    ["知らないモード", { routeMode: "zigzag" }],
    ["範囲外の距離", { distance: String(routeGenerateConfig.max_distance_km + 1) }],
    ["範囲外の候補数", { maxRoutes: "0" }],
    ["座標でない出発地", { origin: { latitude: "35" } }],
    ["上限を超える経由地", { waypoints: Array(routeGenerateConfig.max_waypoints + 1).fill(POINT) }],
    ["数でない重み", { routePreference: { axis_a: "0.7" } }],
    ["負の重み", { routePreference: { axis_a: -0.1 } }],
    ["除外が無い", { hardFilters: null }],
  ])("%sの件だけを捨て、ほかの件は残す", (_, broken) => {
    const other = { ...ENTRY, name: "別の件" };

    expect(readSavedConditions(JSON.stringify([{ ...ENTRY, ...broken }, other]))).toEqual([other]);
  });

  it("一覧として読めない保存値は空の一覧にする", () => {
    expect(readSavedConditions("{")).toEqual([]);
    expect(readSavedConditions(JSON.stringify(ENTRY))).toEqual([]);
  });

  it("除外は今の項目へ揃える（無い項目は既定値、今は無い項目は落とす）", () => {
    const [key, ...rest] = Object.keys(DEFAULT_HARD_FILTERS);
    const stored = { [key]: !DEFAULT_HARD_FILTERS[key], retired_filter: true };

    const [read] = readSavedConditions(JSON.stringify([{ ...ENTRY, hardFilters: stored }]));

    expect(read.hardFilters).toEqual({
      ...Object.fromEntries(rest.map((k) => [k, DEFAULT_HARD_FILTERS[k]])),
      [key]: !DEFAULT_HARD_FILTERS[key],
    });
  });
});

describe("suggestedConditionName", () => {
  it.each([
    ["周回は距離", { routeMode: "loop" as const, waypoints: [POINT] }, "周回 30km"],
    [
      "経由地のある目的地は地点の数",
      { routeMode: "destination" as const, waypoints: [POINT, POINT] },
      "目的地 経由2地点",
    ],
    ["経由地の無い目的地", { routeMode: "destination" as const, waypoints: [] }, "目的地"],
  ])("%s", (_, conditions, expected) => {
    expect(suggestedConditionName({ ...ENTRY, ...conditions })).toBe(expected);
  });
});

describe("describeConditions", () => {
  const CATALOG = catalogOf([
    catalogEntry({ axis_id: "axis_a", label: "軸A", chip_label: "A", default_weight: 0.25 }),
    catalogEntry({ axis_id: "axis_b", label: "軸B", default_weight: 0.75 }),
    catalogEntry({ axis_id: "axis_c", label: "軸C", default_weight: 0 }),
  ]);

  it.each([
    ["周回は距離と候補数", { routeMode: "loop" as const }, "周回 30km・候補 3本"],
    ["経由地のある目的地は地点の数", { routeMode: "destination" as const }, "目的地へ・経由 1地点・候補 3本"],
    ["経由地の無い目的地", { routeMode: "destination" as const, waypoints: [] }, "目的地へ・候補 3本"],
  ])("条件: %s", (_, conditions, expected) => {
    expect(describeConditions({ ...ENTRY, ...conditions }, CATALOG).route).toBe(expected);
  });

  it.each([
    ["上書きしない重みは、既定の配分を割合の大きい順に", null, CATALOG, "おすすめの配分（軸B 75%・軸A 25%）"],
    [
      "上書きした重みは、公開軸へ揃えて（無い軸は既定・消えた軸は外す）",
      { axis_a: 0.75, axis_gone: 1 },
      CATALOG,
      "自分で変えた配分（軸A 50%・軸B 50%）",
    ],
    ["軸カタログが届く前は、配分の種類だけ", { axis_a: 1 }, EMPTY_CATALOG, "自分で変えた配分"],
  ])("重み: %s", (_, routePreference, catalog, expected) => {
    expect(describeConditions({ ...ENTRY, routePreference }, catalog).weights).toBe(expected);
  });

  it("除外は除外する道路の名前を並べ、無ければ無いと出す", () => {
    const [first, second] = routeGenerateConfig.hard_filters.filters;
    const none = Object.fromEntries(Object.keys(DEFAULT_HARD_FILTERS).map((key) => [key, false]));

    expect(
      describeConditions({ ...ENTRY, hardFilters: { ...none, [first.key]: true, [second.key]: true } }, CATALOG)
        .exclusions,
    ).toBe(`${first.label}・${second.label}`);
    expect(describeConditions({ ...ENTRY, hardFilters: none }, CATALOG).exclusions).toBe("なし");
  });
});

describe("withSavedCondition", () => {
  it("新しい名前は先頭に足し、同じ名前は上書きして先頭へ移す", () => {
    const a = { ...ENTRY, name: "A" };
    const b = { ...ENTRY, name: "B" };
    const newerA = { ...a, distance: "50" };

    expect(withSavedCondition([a], b)).toEqual([b, a]);
    expect(withSavedCondition([b, a], newerA)).toEqual([newerA, b]);
  });
});
