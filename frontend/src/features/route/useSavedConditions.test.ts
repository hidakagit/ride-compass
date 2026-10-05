/**
 * 保存した生成の条件（`useSavedConditions.ts`）——いまの生成の条件を名前を付けて保存し、呼び出すと生成の条件
 * （`useGenerationConditions.ts`。本物を通す）が保存した値に入れ替わる。出発地は位置の持ち主へ渡す: 固定して保存した
 * ものは保存したときの出発地に、固定せずに保存したものは現在地へ戻す。一覧は開き直しても残る。
 *
 * ここで見ないもの:
 * - 保存値の1件ずつの読み方・名前の案・同じ名前の上書き → `savedConditions.test.ts`
 * - 一覧の表示と押した操作・出発地を固定するかの既定 → `SavedConditionsPanel/SavedConditionsPanel.test.tsx`
 * - 出発地を受け取ったあと（地図で置いた出発地・現在地の取り直し） → `hooks/useLocation.test.ts`
 *
 * 差し替えたもの: 軸カタログの応答（網の層）。保存はテスト環境の`localStorage`を本物のまま使う。
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_HARD_FILTERS } from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import { serveAxisCatalog } from "@/testing/backendServer";
import { catalogEntry, catalogResponse } from "@/testing/catalogAxes";
import type { Coordinates } from "@/types/route";

import { useGenerationConditions } from "./useGenerationConditions";
import { useSavedConditions } from "./useSavedConditions";

const A: Coordinates = { latitude: 35.1, longitude: 139.1 };
const B: Coordinates = { latitude: 35.2, longitude: 139.2 };
const ORIGIN: Coordinates = { latitude: 35.3, longitude: 139.3 };

const CATALOG = catalogResponse([
  catalogEntry({ axis_id: "axis_a", default_weight: 0.4 }),
  catalogEntry({ axis_id: "axis_b", default_weight: 0.6 }),
]);

interface OriginProps {
  origin: Coordinates | null;
  originManual: boolean;
}

function renderSaved(initialOrigin: OriginProps = { origin: ORIGIN, originManual: false }) {
  const onOriginPlace = vi.fn();
  const onOriginFollowCurrent = vi.fn();
  const rendered = renderHook(
    ({ origin, originManual }: OriginProps) => {
      const conditions = useGenerationConditions({ onOriginPlace: () => {} });
      return {
        conditions,
        saved: useSavedConditions({ conditions, origin, originManual, onOriginPlace, onOriginFollowCurrent }),
      };
    },
    { initialProps: initialOrigin },
  );
  return { ...rendered, onOriginPlace, onOriginFollowCurrent };
}

beforeEach(() => {
  window.localStorage.clear();
  serveAxisCatalog(CATALOG);
});

describe("保存して呼び出す", () => {
  it("保存したあとに変えた条件が、呼び出すと保存した値へ戻る", async () => {
    const { result } = renderSaved();
    await waitFor(() => expect(result.current.conditions.routePreference).toEqual({ axis_a: 0.4, axis_b: 0.6 }));
    const [filterKey] = Object.keys(DEFAULT_HARD_FILTERS);
    act(() => {
      result.current.conditions.changeRouteMode("destination");
      result.current.conditions.setMaxRoutesInput("3");
      result.current.conditions.placePin("waypoint", A);
      result.current.conditions.setDestination(B);
      result.current.conditions.setRoutePreference({ axis_a: 0.7, axis_b: 0.3 });
      result.current.conditions.setWeightOverrideEnabled(true);
      result.current.conditions.setHardFilters({
        ...DEFAULT_HARD_FILTERS,
        [filterKey]: !DEFAULT_HARD_FILTERS[filterKey],
      });
    });
    act(() => result.current.saved.save("荒川へ", false));

    act(() => {
      result.current.conditions.changeRouteMode("loop");
      result.current.conditions.setDistanceInput("80");
      result.current.conditions.setMaxRoutesInput("5");
      result.current.conditions.clearWaypoints();
      result.current.conditions.clearDestination();
      result.current.conditions.setWeightOverrideEnabled(false);
      result.current.conditions.setHardFilters(DEFAULT_HARD_FILTERS);
    });
    act(() => result.current.saved.recall(result.current.saved.saved[0]));

    const conditions = result.current.conditions;
    expect(conditions.routeMode).toBe("destination");
    expect(conditions.distanceInput).toBe("30");
    expect(conditions.maxRoutesInput).toBe("3");
    expect(conditions.waypoints).toEqual([A]);
    expect(conditions.destination).toEqual(B);
    expect(conditions.armedPinRole).toBeNull();
    expect(conditions.routePreferenceToSend).toEqual({ axis_a: 0.7, axis_b: 0.3 });
    expect(conditions.hardFilters[filterKey]).toBe(!DEFAULT_HARD_FILTERS[filterKey]);
  });

  it("重みを上書きせずに保存した条件は、呼び出すと上書きをやめる", async () => {
    const { result } = renderSaved();
    act(() => result.current.saved.save("既定の重み", false));
    act(() => {
      result.current.conditions.setRoutePreference({ axis_a: 0.7, axis_b: 0.3 });
      result.current.conditions.setWeightOverrideEnabled(true);
    });
    await waitFor(() => expect(result.current.conditions.routePreferenceToSend).not.toBeNull());

    act(() => result.current.saved.recall(result.current.saved.saved[0]));

    expect(result.current.conditions.routePreferenceToSend).toBeNull();
  });

  it("名前が空なら仮の名前で保存し、一覧は開き直しても残る", () => {
    const first = renderSaved();
    act(() => first.result.current.saved.save("  ", false));
    first.unmount();

    expect(renderSaved().result.current.saved.saved.map((entry) => entry.name)).toEqual(["周回 30km"]);
  });

  it("消すとその件だけが一覧から外れる", () => {
    const { result } = renderSaved();
    act(() => result.current.saved.save("A", false));
    act(() => result.current.saved.save("B", false));

    act(() => result.current.saved.remove("A"));

    expect(result.current.saved.saved.map((entry) => entry.name)).toEqual(["B"]);
  });
});

describe("出発地", () => {
  it("固定して保存したものは、呼び出すと保存したときの出発地にする（現在地のままでも）", () => {
    const { result, rerender, onOriginPlace, onOriginFollowCurrent } = renderSaved({
      origin: ORIGIN,
      originManual: false,
    });
    act(() => result.current.saved.save("ここに固定", true));
    rerender({ origin: A, originManual: true });

    act(() => result.current.saved.recall(result.current.saved.saved[0]));

    expect(onOriginPlace).toHaveBeenCalledExactlyOnceWith(ORIGIN);
    expect(onOriginFollowCurrent).not.toHaveBeenCalled();
  });

  it("固定せずに保存したものは、呼び出したとき地図で置いた出発地があれば現在地へ戻し、現在地のままなら何もしない", () => {
    const { result, rerender, onOriginFollowCurrent } = renderSaved({ origin: A, originManual: true });
    act(() => result.current.saved.save("現在地から", false));
    rerender({ origin: ORIGIN, originManual: false });

    act(() => result.current.saved.recall(result.current.saved.saved[0]));
    expect(onOriginFollowCurrent).not.toHaveBeenCalled();

    rerender({ origin: A, originManual: true });
    act(() => result.current.saved.recall(result.current.saved.saved[0]));

    expect(onOriginFollowCurrent).toHaveBeenCalledOnce();
  });
});
