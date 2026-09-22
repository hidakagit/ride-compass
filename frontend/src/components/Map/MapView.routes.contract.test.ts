// @vitest-environment node
/** ルートの描画が満たすべき**結果**。実装が入れ替わっても、この期待値は変わらない。
 *
 * 筋書きは[遷移表](../../../../docs/records/tasks/T1001.md)から取っている。書くのは
 * 「どの呼び出しが出たか」ではなく「最後にどうなっているか」——呼び出しの形で書くと、
 * そのときの実装が持つ手当て（作成順を後から揃える・毎回表示を明示する）を、次の実装にも
 * 要求することになる。
 */
import { describe, expect, it } from "vitest";

import { createRecordingMap } from "@/testing/mapTrace/recordingMap";
import { applyMapScene } from "@/features/map/scene/applyMapScene";
import { EMPTY_MAP_SCENE, sceneLayerIdsForRole, type MapScene } from "@/features/map/scene/mapScene";
import { routeGroup, type RoutePath, type RouteState } from "@/features/map/scene/groups/routes";
import { composeScene } from "@/features/map/scene/mapSceneGroups";


type RouteCandidateShape = RouteState["candidates"][number];
type RoutePathShape = RouteState["segments"][number];
type ComparisonSlotShape = RouteState["comparisonSlots"][number];

/** 役割からレイヤーidを引く。**綴りを組み立て直さない**——idはソース名＋役割で、ソース名は
 * 宣言する側が決めるため、外から組み直すと規則を変えたときにここだけ古い綴りで残る。 */
const DECLARED_SCENE = composeScene([routeGroup], {
  visible: true,
  candidates: [],
  selectedRouteId: null,
  segments: [],
  segmentColor: "#16a34a",
  spliceBands: [],
  composite: null,
  comparisonSlots: [],
  arrowIconImage: "arrow",
});
const routeSceneLayerId = (role: string) => sceneLayerIdsForRole(DECLARED_SCENE, role)[0];

const PATH: RoutePath = [
  [139.7, 35.6],
  [139.71, 35.61],
];

const CANDIDATE: RouteCandidateShape = { routeId: "a", path: PATH };
const SEGMENT: RoutePathShape = { path: PATH, properties: { osm_way_id: 1 } };
const SLOT: ComparisonSlotShape = { path: PATH, color: "#16a34a" };

const CANDIDATE_LINE = routeSceneLayerId("candidateLine");
const CANDIDATE_HIT = routeSceneLayerId("candidateHit");
const SELECTED_HALO = routeSceneLayerId("selectedHalo");
const DETAIL_CASING = routeSceneLayerId("detailCasing");
const DETAIL_LINE = routeSceneLayerId("detailLine");
const DETAIL_HIT = routeSceneLayerId("detailHit");
const ARROW_HALO = routeSceneLayerId("arrowHalo");
const ARROW = routeSceneLayerId("arrow");
const SLOT_LINE = routeSceneLayerId("slotLine");

/** 画面の状態を地図へ伝える入口。**実装が入れ替わったら、この束ね方だけを差し替える**
 * （期待値の側は動かさない）。 */
function bindCurrentImplementation(map: unknown) {
  let state: RouteState = {
    visible: true,
    candidates: [],
    selectedRouteId: null,
    segments: [],
    segmentColor: "#16a34a",
    spliceBands: [],
    composite: null,
    comparisonSlots: [],
    arrowIconImage: "arrow",
  };
  let previous: MapScene = EMPTY_MAP_SCENE;

  const apply = (next: Partial<RouteState>) => {
    state = { ...state, ...next };
    const scene = composeScene([routeGroup], state);
    applyMapScene(map as never, { scene, previous });
    previous = scene;
  };

  return {
    showRoutes: (candidates: readonly RouteCandidateShape[], selectedRouteId: string | null) =>
      apply({ visible: true, candidates, selectedRouteId }),
    hideRoutes: () => apply({ visible: false }),
    showSelected: (candidates: readonly RouteCandidateShape[], selectedRouteId: string | null) =>
      apply({ visible: true, candidates, selectedRouteId }),
    showDetail: (segments: readonly RoutePathShape[], lineColor: string) =>
      apply({ visible: true, segments, segmentColor: lineColor }),
    showSlots: (comparisonSlots: readonly ComparisonSlotShape[]) => apply({ visible: true, comparisonSlots }),
    /** スタイルの差し替え。地図から全部消えた状態で、同じ状態を伝え直す。 */
    replaceStyle: () => {
      previous = EMPTY_MAP_SCENE;
      apply({});
    },
  };
}

describe("ルートの描画", () => {
  function setup() {
    const { map, handle } = createRecordingMap();
    return { handle, drawing: bindCurrentImplementation(map) };
  }

  it("表示ONの状態は、途中で隠していても最後に見えている", () => {
    const { handle, drawing } = setup();

    drawing.showRoutes([CANDIDATE], "a");
    drawing.hideRoutes();
    drawing.showRoutes([CANDIDATE], "a");

    expect(handle.layer(CANDIDATE_LINE)?.visibility).toBe("visible");
    expect(handle.layer(CANDIDATE_HIT)?.visibility).toBe("visible");
  });

  // 選択中候補と区間の色分けは別のきっかけで届く。**どちらが先でも同じ重なりになること**が
  // 要求で、「後から寄せ直す」手当ては要求ではない。
  it.each([
    ["選択中の候補が先", true],
    ["区間の色分けが先", false],
  ])("%s でも、重なりは 縁取り→色分け線→当たり判定→矢印 になる", (_order, selectedFirst) => {
    const { handle, drawing } = setup();

    if (selectedFirst) {
      drawing.showSelected([CANDIDATE], "a");
      drawing.showDetail([SEGMENT], "#16a34a");
    } else {
      drawing.showDetail([SEGMENT], "#16a34a");
      drawing.showSelected([CANDIDATE], "a");
    }

    const order = handle.layerOrder();
    const at = (id: string) => order.indexOf(id);
    expect(at(DETAIL_CASING)).toBeLessThan(at(DETAIL_LINE));
    expect(at(DETAIL_LINE)).toBeLessThan(at(ARROW_HALO));
    expect(at(DETAIL_HIT)).toBeLessThan(at(ARROW_HALO));
    expect(at(ARROW_HALO)).toBeLessThan(at(ARROW));
  });

  it("選択中候補のハローは、候補線より下にある", () => {
    const { handle, drawing } = setup();

    drawing.showRoutes([CANDIDATE], "a");

    const order = handle.layerOrder();
    expect(order.indexOf(SELECTED_HALO)).toBeLessThan(order.indexOf(CANDIDATE_LINE));
  });

  it("比較スロットは、候補線より上・区間の色分けより下にある", () => {
    const { handle, drawing } = setup();

    drawing.showRoutes([CANDIDATE], "a");
    drawing.showDetail([SEGMENT], "#16a34a");
    drawing.showSlots([SLOT]);

    const order = handle.layerOrder();
    expect(order.indexOf(CANDIDATE_LINE)).toBeLessThan(order.indexOf(SLOT_LINE));
    expect(order.indexOf(SLOT_LINE)).toBeLessThan(order.indexOf(DETAIL_CASING));
  });

  // 縁取りは、線の色（レンズの配色）と同系色の背景でも輪郭が残るようにする。
  it("区間の縁取りは、色分け線より太く、線の色に依存しない一定色で描く", () => {
    const { handle, drawing } = setup();

    drawing.showDetail([SEGMENT], "#16a34a");

    const casing = handle.layer(DETAIL_CASING);
    const line = handle.layer(DETAIL_LINE);
    expect(Number(casing?.paint["line-width"])).toBeGreaterThan(Number(line?.paint["line-width"]));
    expect(typeof casing?.paint["line-color"]).toBe("string");
  });

  it("モードを切り替えると、色分け線の色式が入れ替わる", () => {
    const { handle, drawing } = setup();

    drawing.showDetail([SEGMENT], "#16a34a");
    drawing.showDetail([SEGMENT], "#dc2626");

    expect(handle.layer(DETAIL_LINE)?.paint["line-color"]).toBe("#dc2626");
  });

  // スタイルを差し替えると、このアプリが足したものは全部消える。同じ状態を伝え直せば戻る。
  it("スタイルを差し替えても、同じ状態を伝え直せば元の重なりへ戻る", () => {
    const { handle, drawing } = setup();
    drawing.showRoutes([CANDIDATE], "a");
    drawing.showDetail([SEGMENT], "#16a34a");
    drawing.showSlots([SLOT]);
    const before = handle.layerOrder();
    expect(before.length).toBeGreaterThan(5);

    handle.dropEverything();
    drawing.replaceStyle();

    expect(handle.layerOrder()).toEqual(before);
  });
});
