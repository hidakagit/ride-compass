// @vitest-environment node
/**
 * `features/route/savedConditions.ts`——保存した生成の条件の一覧を読む・名前の案・一覧への入れ方。読むときは、今の画面が
 * 受け付けない件だけを捨ててほかの件を残し、除外は今の項目へ揃える。同じ名前で保存すると上書きする。
 *
 * ここで見ないもの:
 * - 距離・候補数の範囲（`acceptedDistanceInput`・`acceptedMaxRoutesInput`） → `useGenerationConditions.test.ts`の保存値の読み直し
 * - 一覧の行の説明（`savedConditionSummary`） → `SavedConditionsPanel/SavedConditionsPanel.test.tsx`
 */
import { describe, expect, it } from "vitest";

import { DEFAULT_HARD_FILTERS } from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import {
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

describe("withSavedCondition", () => {
  it("新しい名前は先頭に足し、同じ名前は上書きして先頭へ移す", () => {
    const a = { ...ENTRY, name: "A" };
    const b = { ...ENTRY, name: "B" };
    const newerA = { ...a, distance: "50" };

    expect(withSavedCondition([a], b)).toEqual([b, a]);
    expect(withSavedCondition([b, a], newerA)).toEqual([newerA, b]);
  });
});
