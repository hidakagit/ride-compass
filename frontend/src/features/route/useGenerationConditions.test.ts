/**
 * 生成の条件（`useGenerationConditions.ts`）——周回か目的地か・距離・候補数・地点（出発地以外）・重み・除外と、地図の
 * タップで置ける地点の役割を返す。保存する値（地点以外）は開き直しても残り、読むときに今の画面が受け付ける範囲・
 * 今の項目へ揃える。重みは軸カタログの公開軸へ揃えた値を返し、送るのは上書きを有効にしてカタログが届いた後だけ。
 *
 * ここで見ないもの:
 * - 重み・除外の揃え方の細部（増えた軸を既定の重みで補う・消えた軸を外す・取得が決まるまで揃えない） →
 *   `routePreferenceSync.test.ts`・`hardFilterSync.test.ts`。ここでは揃えた値を返すことを1件ずつ見る
 * - 保存の読み書きそのもの（読めない・書けない端末で既定値になる） → `hooks/useStoredState.test.ts`
 * - 地図で置いた出発地を位置の持ち主が受け取ったあと → `hooks/useLocation.test.ts`
 * - 置ける役割が効く場所（「条件」タブを開いている間だけ・周回の間は出発地だけ） → `app/page.test.tsx`
 * - 条件を生成へ送る形 → `useRouteGeneration.test.ts`
 *
 * 差し替えたもの: 軸カタログの応答（網の層）。保存はテスト環境の`localStorage`を
 * 本物のまま使い、開き直しは同じ保存の上でフックを描き直して作る。
 *
 * 経由地の上限を超えて置かせない分岐（`placePin`の`prev.length >= max_waypoints`）は通さない: 上限に達すると置ける
 * 役割を解き、経由地の行も押せなくなる（`RouteForm/RouteForm.test.tsx`）ので、上限のあとに経由地を置く操作は作れない。
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_HARD_FILTERS } from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import { heldReplies, onBackend, serveAxisCatalog } from "@/testing/backendServer";
import { catalogEntry, catalogResponse } from "@/testing/catalogAxes";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { Coordinates } from "@/types/route";

import { useGenerationConditions } from "./useGenerationConditions";

const A: Coordinates = { latitude: 35.1, longitude: 139.1 };
const B: Coordinates = { latitude: 35.2, longitude: 139.2 };
const C: Coordinates = { latitude: 35.3, longitude: 139.3 };

const CATALOG = catalogResponse([
  catalogEntry({ axis_id: "axis_a", default_weight: 0.4 }),
  catalogEntry({ axis_id: "axis_b", default_weight: 0.6 }),
]);

function renderConditions() {
  const onOriginPlace = vi.fn();
  const rendered = renderHook(() => useGenerationConditions({ onOriginPlace }));
  return { ...rendered, onOriginPlace };
}

/** 同じ保存の上で開き直す。 */
function reopen(rendered: { unmount: () => void }) {
  rendered.unmount();
  return renderConditions();
}

function point(index: number): Coordinates {
  return { latitude: 35 + index / 100, longitude: 139 };
}

beforeEach(() => {
  window.localStorage.clear();
  // 既定は届かないまま（重みを見るテストだけが届ける）。
  onBackend("GET", "/api/axis-catalog", heldReplies().reply);
});

describe("周回か目的地か", () => {
  it("既定は周回で何も置けず、選んだモードは開き直しても残る", () => {
    const first = renderConditions();
    expect(first.result.current.routeMode).toBe("loop");
    expect(first.result.current.armedPinRole).toBeNull();

    act(() => first.result.current.changeRouteMode("destination"));

    expect(reopen(first).result.current.routeMode).toBe("destination");
  });

  it("知らない値の保存値は捨てて周回で始める", () => {
    window.localStorage.setItem("ridecompass:route-mode", "zigzag");

    expect(renderConditions().result.current.routeMode).toBe("loop");
  });

  it("目的地へ切り替えたとき、何も置いていなければ次のタップで目的地を置け、周回へ戻すとやめる", () => {
    const { result } = renderConditions();

    act(() => result.current.changeRouteMode("destination"));
    expect(result.current.armedPinRole).toBe("destination");

    act(() => result.current.changeRouteMode("loop"));
    expect(result.current.armedPinRole).toBeNull();
  });

  it("目的地モードで開き直したとき、何も置いていなければ目的地を置け、役割を選び直せばそれに従う", () => {
    window.localStorage.setItem("ridecompass:route-mode", "destination");
    const { result } = renderConditions();
    expect(result.current.armedPinRole).toBe("destination");

    act(() => result.current.armPinRole(null));
    expect(result.current.armedPinRole).toBeNull();
  });

  it.each([
    { label: "目的地", place: (r: ReturnType<typeof useGenerationConditions>) => r.setDestination(A) },
    { label: "経由地", place: (r: ReturnType<typeof useGenerationConditions>) => r.placePin("waypoint", A) },
  ])("「$label」が既に置いてあれば、目的地へ切り替えても自動では置けるようにしない", ({ place }) => {
    const { result } = renderConditions();
    act(() => place(result.current));

    act(() => result.current.changeRouteMode("destination"));

    expect(result.current.armedPinRole).toBeNull();
  });

  it("モードを切り替えても置いた地点は消さない", () => {
    const { result } = renderConditions();
    act(() => result.current.changeRouteMode("destination"));
    act(() => result.current.placePin("destination", A));
    act(() => result.current.placePin("waypoint", B));

    act(() => result.current.changeRouteMode("loop"));

    expect(result.current.destination).toEqual(A);
    expect(result.current.waypoints).toEqual([B]);
  });
});

describe("地点", () => {
  it("出発地は位置の持ち主へ渡し、置ける役割を解く。自分では持たない", () => {
    const { result, onOriginPlace } = renderConditions();
    act(() => result.current.armPinRole("origin"));

    act(() => result.current.placePin("origin", A));

    expect(onOriginPlace).toHaveBeenCalledWith(A);
    expect(result.current.armedPinRole).toBeNull();
    expect(result.current.destination).toBeNull();
    expect(result.current.waypoints).toEqual([]);
  });

  it("目的地は置いてあっても置き直せば置き換わり、置ける役割を解く", () => {
    const { result } = renderConditions();
    act(() => result.current.placePin("destination", A));
    act(() => result.current.armPinRole("destination"));
    expect(result.current.destination).toEqual(A);

    act(() => result.current.placePin("destination", B));

    expect(result.current.destination).toEqual(B);
    expect(result.current.armedPinRole).toBeNull();
  });

  it("経由地は置いた順に足す", () => {
    const { result } = renderConditions();

    act(() => result.current.placePin("waypoint", A));
    act(() => result.current.placePin("waypoint", B));

    expect(result.current.waypoints).toEqual([A, B]);
  });

  it("経由地は置いたあとも続けて置け、生成が受け付ける数に達したところで置ける役割を解く", () => {
    const max = routeGenerateConfig.max_waypoints;
    const { result } = renderConditions();
    act(() => result.current.armPinRole("waypoint"));

    for (let i = 0; i < max - 1; i++) act(() => result.current.placePin("waypoint", point(i)));
    expect(result.current.armedPinRole).toBe("waypoint");

    act(() => result.current.placePin("waypoint", point(max - 1)));

    expect(result.current.waypoints).toHaveLength(max);
    expect(result.current.armedPinRole).toBeNull();
  });

  it("経由地は位置を指して動かす・消す・まとめて消せ、目的地も消せる", () => {
    const { result } = renderConditions();
    act(() => result.current.placePin("waypoint", A));
    act(() => result.current.placePin("waypoint", B));
    act(() => result.current.setDestination(A));

    act(() => result.current.moveWaypoint(1, C));
    expect(result.current.waypoints).toEqual([A, C]);

    act(() => result.current.removeWaypoint(0));
    expect(result.current.waypoints).toEqual([C]);

    act(() => result.current.clearWaypoints());
    act(() => result.current.clearDestination());
    expect(result.current.waypoints).toEqual([]);
    expect(result.current.destination).toBeNull();
  });

  it("地点は保存せず、開き直すと置いていない状態から始まる", () => {
    const first = renderConditions();
    act(() => first.result.current.placePin("waypoint", A));
    act(() => first.result.current.setDestination(B));

    const { result } = reopen(first);

    expect(result.current.waypoints).toEqual([]);
    expect(result.current.destination).toBeNull();
  });
});

describe("距離と候補数", () => {
  it("入力した値は文字列のまま持ち、開き直しても残る", () => {
    const first = renderConditions();
    act(() => first.result.current.setDistanceInput("55"));
    act(() => first.result.current.setMaxRoutesInput("3"));

    const { result } = reopen(first);

    expect(result.current.distanceInput).toBe("55");
    expect(result.current.maxRoutesInput).toBe("3");
  });

  it.each([
    { label: "1kmちょうど", saved: "1", accepted: true },
    { label: "上限ちょうど", saved: String(routeGenerateConfig.max_distance_km), accepted: true },
    { label: "1kmより短い", saved: "0.9", accepted: false },
    { label: "上限より長い", saved: String(routeGenerateConfig.max_distance_km + 1), accepted: false },
    { label: "数でない", saved: "abc", accepted: false },
  ])("距離の保存値は範囲の中だけを受け入れる（$label）", ({ saved, accepted }) => {
    window.localStorage.setItem("ridecompass:distance-km", saved);

    expect(renderConditions().result.current.distanceInput).toBe(accepted ? saved : "30");
  });

  it.each([
    { label: "1件ちょうど", saved: "1", accepted: true },
    { label: "上限ちょうど", saved: String(routeGenerateConfig.max_routes), accepted: true },
    { label: "0件", saved: "0", accepted: false },
    { label: "上限より多い", saved: String(routeGenerateConfig.max_routes + 1), accepted: false },
    { label: "整数でない", saved: "2.5", accepted: false },
  ])("候補数の保存値は範囲の中の整数だけを受け入れる（$label）", ({ saved, accepted }) => {
    window.localStorage.setItem("ridecompass:max-routes", saved);

    expect(renderConditions().result.current.maxRoutesInput).toBe(
      accepted ? saved : String(routeGenerateConfig.default_max_routes),
    );
  });
});

describe("重み", () => {
  it("カタログが届くと公開軸へ揃えた重みを返し、上書きを有効にするまでは送らない", async () => {
    serveAxisCatalog(CATALOG);
    const { result } = renderConditions();

    await waitFor(() => expect(result.current.routePreference).toEqual({ axis_a: 0.4, axis_b: 0.6 }));
    expect(result.current.weightOverrideEnabled).toBe(false);
    expect(result.current.routePreferenceToSend).toBeNull();

    act(() => result.current.setWeightOverrideEnabled(true));

    expect(result.current.routePreferenceToSend).toEqual({ axis_a: 0.4, axis_b: 0.6 });
  });

  it("カタログが届かない間は、上書きを有効にしていても送らない", () => {
    const { result } = renderConditions();

    act(() => result.current.setWeightOverrideEnabled(true));

    expect(result.current.routePreferenceToSend).toBeNull();
  });

  it("揃えても保存した重みは書き換えず、公開を取り下げた軸が戻ればその重みも戻る", async () => {
    window.localStorage.setItem("ridecompass:route-preference", JSON.stringify({ axis_a: 0.7, axis_c: 0.2 }));
    serveAxisCatalog(CATALOG);
    const first = renderConditions();
    await waitFor(() => expect(first.result.current.routePreference).toEqual({ axis_a: 0.7, axis_b: 0.6 }));

    serveAxisCatalog(
      catalogResponse([
        catalogEntry({ axis_id: "axis_a", default_weight: 0.4 }),
        catalogEntry({ axis_id: "axis_c", default_weight: 0.6 }),
      ]),
    );
    const { result } = reopen(first);

    await waitFor(() => expect(result.current.routePreference).toEqual({ axis_a: 0.7, axis_c: 0.2 }));
  });

  it("動かした重みと上書きの有効は開き直しても残る", async () => {
    serveAxisCatalog(CATALOG);
    const first = renderConditions();
    act(() => first.result.current.setRoutePreference({ axis_a: 0.7, axis_b: 0.3 }));
    act(() => first.result.current.setWeightOverrideEnabled(true));

    const { result } = reopen(first);

    await waitFor(() => expect(result.current.routePreferenceToSend).toEqual({ axis_a: 0.7, axis_b: 0.3 }));
  });
});

describe("除外", () => {
  it("保存値が無ければ既定の除外で始め、変えた値は開き直しても残る", () => {
    const first = renderConditions();
    expect(first.result.current.hardFilters).toEqual(DEFAULT_HARD_FILTERS);
    const [key] = Object.keys(DEFAULT_HARD_FILTERS);
    const changed = { ...DEFAULT_HARD_FILTERS, [key]: !DEFAULT_HARD_FILTERS[key] };

    act(() => first.result.current.setHardFilters(changed));

    expect(reopen(first).result.current.hardFilters).toEqual(changed);
  });

  it("保存値に今は無い項目があっても今の項目へ揃え、読めない保存値は既定に戻す", () => {
    const [key] = Object.keys(DEFAULT_HARD_FILTERS);
    window.localStorage.setItem(
      "ridecompass:hard-filters",
      JSON.stringify({ [key]: !DEFAULT_HARD_FILTERS[key], retired_filter: true }),
    );
    expect(renderConditions().result.current.hardFilters).toEqual({
      ...DEFAULT_HARD_FILTERS,
      [key]: !DEFAULT_HARD_FILTERS[key],
    });

    window.localStorage.setItem("ridecompass:hard-filters", "{broken");
    expect(renderConditions().result.current.hardFilters).toEqual(DEFAULT_HARD_FILTERS);
  });
});
