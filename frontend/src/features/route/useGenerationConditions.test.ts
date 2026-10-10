/**
 * 生成の条件（`useGenerationConditions.ts`）——全長の目標を決めるか・距離・候補数・地点（出発地以外）・重み・除外と、地図の
 * タップで置ける地点の役割（経由地は足すか、何番目を置き直すか）と、検索で置いた地点の候補（その位置のままの間だけ）を返す。保存する値（地点以外）は開き直しても残り、読むときに今の画面が受け付ける範囲・
 * 今の項目へ揃える。重みは軸カタログの公開軸へ揃えた値を返し、送るのは上書きを有効にしてカタログが届いた後だけ。
 *
 * ここで見ないもの:
 * - 重み・除外の揃え方の細部（増えた軸を既定の重みで補う・消えた軸を外す・取得が決まるまで揃えない） →
 *   `routePreferenceSync.test.ts`・`hardFilterSync.test.ts`。ここでは揃えた値を返すことを1件ずつ見る
 * - 重みを送るかの判断（上書きしていない・カタログが届かない間は送らない） → `routePreferenceSync.test.ts`。
 *   ここでは開き直した後に送る重みを1件見る
 * - 保存の読み書きそのもの（読めない・書けない端末で既定値になる） → `hooks/useStoredState.test.ts`
 * - 地図で置いた出発地を位置の持ち主が受け取ったあと → `hooks/useLocation.test.ts`
 * - 置ける役割が効く場所（「条件」タブを開いている間だけ） → `app/page.test.tsx`
 * - 条件を生成へ送る形 → `useRouteGeneration.test.ts`
 *
 * 差し替えたもの: 軸カタログの応答（網の層）。保存はテスト環境の`localStorage`を
 * 本物のまま使い、開き直しは同じ保存の上でフックを描き直して作る。
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_HARD_FILTERS } from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import { heldReplies, onBackend, serveAxisCatalog } from "@/testing/backendServer";
import { catalogEntry, catalogResponse, TWO_AXIS_CATALOG } from "@/testing/catalogAxes";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { Coordinates, PlaceCandidate } from "@/types/route";

import { useGenerationConditions } from "./useGenerationConditions";

const A: Coordinates = { latitude: 35.1, longitude: 139.1 };
const B: Coordinates = { latitude: 35.2, longitude: 139.2 };
const C: Coordinates = { latitude: 35.3, longitude: 139.3 };

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

/** 地点`at`で当たった施設の候補。 */
function candidateAt(at: Coordinates, name: string): PlaceCandidate {
  return { kind: "facility", level: "point", name, area: null, ...at };
}

function point(index: number): Coordinates {
  return { latitude: 35 + index / 100, longitude: 139 };
}

beforeEach(() => {
  window.localStorage.clear();
  // 既定は届かないまま（重みを見るテストだけが届ける）。
  onBackend("GET", "/api/axis-catalog", heldReplies().reply);
});

describe("全長の目標", () => {
  it("既定は決める形で、外したことは開き直しても残る", () => {
    const first = renderConditions();
    expect(first.result.current.distanceTargeted).toBe(true);

    act(() => first.result.current.setDistanceTargeted(false));

    expect(reopen(first).result.current.distanceTargeted).toBe(false);
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

  it("経由地は位置を指して動かす・消せ、目的地も消せる", () => {
    const { result } = renderConditions();
    act(() => result.current.placePin("waypoint", A));
    act(() => result.current.placePin("waypoint", B));
    act(() => result.current.setDestination(A));

    act(() => result.current.moveWaypoint(1, C));
    expect(result.current.waypoints).toEqual([A, C]);

    act(() => result.current.removeWaypoint(0));
    act(() => result.current.clearDestination());
    expect(result.current.waypoints).toEqual([C]);
    expect(result.current.destination).toBeNull();
  });

  it("経由地と目的地は一度に消せ、出発地はそのまま残し、地図のタップで置く状態を解く", () => {
    const { result, onOriginPlace } = renderConditions();
    act(() => result.current.armPinRole("waypoint"));
    act(() => result.current.placePin("waypoint", A));
    act(() => result.current.placePin("waypoint", B));
    act(() => result.current.placePin("destination", C));

    act(() => result.current.clearPoints());

    expect(result.current.waypoints).toEqual([]);
    expect(result.current.destination).toBeNull();
    expect(result.current.armedPinRole).toBeNull();
    expect(onOriginPlace).not.toHaveBeenCalled();
  });

  it("何番目かを指して経由地を置ける役割にすると、次のタップはその経由地を置き直し、置ける役割を解く", () => {
    const { result } = renderConditions();
    act(() => result.current.placePin("waypoint", A));
    act(() => result.current.placePin("waypoint", B));

    act(() => result.current.armPinRole("waypoint", 0));
    expect(result.current.waypointToReplace).toBe(0);
    act(() => result.current.placePin("waypoint", C));

    expect(result.current.waypoints).toEqual([C, B]);
    expect(result.current.armedPinRole).toBeNull();
    expect(result.current.waypointToReplace).toBeNull();
  });

  it("検索で選んだ地点はその役割で置き（経由地は番号を指せばそれを置き直し、指さなければ置き直す途中でも足す）、地図のタップで置く状態を解く", () => {
    const { result, onOriginPlace } = renderConditions();
    act(() => result.current.armPinRole("origin"));

    act(() => result.current.placeFound("origin", candidateAt(A, "出発の店"), null));
    expect(onOriginPlace).toHaveBeenCalledWith(A);

    // 経由地は地図のタップなら置いたあとも置く状態を続けるので、検索で置いたときに解けるかはここで分かる。
    act(() => result.current.armPinRole("waypoint"));
    act(() => result.current.placeFound("waypoint", candidateAt(B, "寄る店"), null));
    expect(result.current.waypoints).toEqual([B]);
    expect(result.current.armedPinRole).toBeNull();

    act(() => result.current.placeFound("destination", candidateAt(C, "着く店"), null));
    expect(result.current.destination).toEqual(C);

    act(() => result.current.placeFound("waypoint", candidateAt(A, "寄り直す店"), 0));
    expect(result.current.waypoints).toEqual([A]);

    // 地図の小窓から足すときは、置き直す経由地を選んで地図のタップを待つ途中でも、置き直さずに足す。
    act(() => result.current.armPinRole("waypoint", 0));
    act(() => result.current.placeFound("waypoint", candidateAt(C, "小窓の店"), null));
    expect(result.current.waypoints).toEqual([A, C]);
  });

  it("検索で置いた地点の候補は、その位置のままの間だけ返す（ピンを動かす・地図で置き直すと外れる）", () => {
    const { result } = renderConditions();
    const destinationShop = candidateAt(C, "着く店");
    const originShop = candidateAt(A, "出発の店");
    const waypointShop = candidateAt(B, "寄る店");
    act(() => result.current.placeFound("destination", destinationShop, null));
    act(() => result.current.placeFound("origin", originShop, null));
    act(() => result.current.placeFound("waypoint", waypointShop, null));

    expect(result.current.foundAt(result.current.destination)).toEqual(destinationShop);
    expect(result.current.foundAt({ ...A })).toEqual(originShop);
    expect(result.current.foundAt(result.current.waypoints[0])).toEqual(waypointShop);
    expect(result.current.foundAt(point(0))).toBeNull();

    act(() => result.current.placePin("destination", point(0)));
    expect(result.current.foundAt(result.current.destination)).toBeNull();
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
  it("揃えても保存した重みは書き換えず、公開を取り下げた軸が戻ればその重みも戻る", async () => {
    window.localStorage.setItem("ridecompass:route-preference", JSON.stringify({ axis_a: 0.7, axis_c: 0.2 }));
    serveAxisCatalog(TWO_AXIS_CATALOG);
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

  it("上書きは既定で無効で、動かした重みと上書きの有効は開き直しても残る", async () => {
    serveAxisCatalog(TWO_AXIS_CATALOG);
    const first = renderConditions();
    expect(first.result.current.weightOverrideEnabled).toBe(false);
    act(() => first.result.current.setRoutePreference({ axis_a: 0.7, axis_b: 0.3 }));
    act(() => first.result.current.setWeightOverrideEnabled(true));

    const { result } = reopen(first);

    await waitFor(() => expect(result.current.routePreferenceToSend).toEqual({ axis_a: 0.7, axis_b: 0.3 }));
  });
});

describe("除外", () => {
  it("変えた除外は開き直しても残る", () => {
    const first = renderConditions();
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
