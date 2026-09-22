// @vitest-environment node
/** ルートの描画が満たすべき**結果**。実装が入れ替わっても、この期待値は変わらない。
 *
 * 筋書きは[遷移表](../../../../docs/records/tasks/T1001.md)から取っている。書くのは
 * 「どの呼び出しが出たか」ではなく「最後にどうなっているか」——呼び出しの形で書くと、
 * いまの実装が持つ手当て（作成順を後から揃える・毎回表示を明示する）を、次の実装にも
 * 要求することになる。
 */
import { describe, expect, it } from "vitest";

import { createRecordingMap } from "@/testing/mapTrace/recordingMap";
import {
  DETAIL_CASING_LAYER_ID,
  DETAIL_HIT_LAYER_ID,
  DETAIL_LAYER_ID,
  OUTLINE_LAYER_ID,
  ROUTES_HIT_LAYER_ID,
  ROUTES_LAYER_ID,
  ROUTE_ARROW_HALO_LAYER_ID,
  ROUTE_ARROW_LAYER_ID,
  drawBaseRoutes,
  drawDetailSegments,
  drawExperimentSlots,
  drawSelectedOutline,
  hideBaseRoutes,
} from "@/components/Map/MapView.routes";
import type { RouteStyleMode } from "@/components/Map/routeStyleModes";
import type { RouteCandidate, RouteSegmentDetail } from "@/types/route";
import type { ExperimentSlot } from "@/types/experimentSlot";

const SLOTS_LAYER_ID = "experiment-slots-line";

function route(id: string): RouteCandidate {
  return {
    id,
    geometry: {
      type: "LineString",
      coordinates: [
        [139.7, 35.6],
        [139.71, 35.61],
      ],
    },
  } as unknown as RouteCandidate;
}

function segment(): RouteSegmentDetail {
  return {
    start_longitude: 139.7,
    start_latitude: 35.6,
    end_longitude: 139.71,
    end_latitude: 35.61,
    geometry: {
      type: "LineString",
      coordinates: [
        [139.7, 35.6],
        [139.71, 35.61],
      ],
    },
  } as unknown as RouteSegmentDetail;
}

const MODE: RouteStyleMode = {
  id: "difficulty",
  label: "総合難易度",
  colorExpression: ["literal", "#16a34a"],
  legend: [],
} as unknown as RouteStyleMode;

const slot = (): ExperimentSlot => ({ color: "#16a34a", topCandidate: route("s1") }) as unknown as ExperimentSlot;

/** 画面の状態を地図へ伝える入口。**新実装ができたら、この束ね方だけを差し替える**
 * （期待値の側は動かさない）。 */
function bindCurrentImplementation(map: unknown) {
  return {
    showRoutes: (routes: RouteCandidate[], selectedId: string | null, hasDetail = false) =>
      drawBaseRoutes(map as never, routes, selectedId, hasDetail),
    hideRoutes: () => hideBaseRoutes(map as never),
    showSelected: (routes: RouteCandidate[], selectedId: string | null) =>
      drawSelectedOutline(map as never, routes, selectedId),
    showDetail: (segments: RouteSegmentDetail[], mode: RouteStyleMode, hiddenKeys: readonly string[]) =>
      drawDetailSegments(map as never, segments, mode, hiddenKeys),
    showSlots: (slots: ExperimentSlot[]) => drawExperimentSlots(map as never, slots),
  };
}

describe.each([["現行の実装", bindCurrentImplementation]])("ルートの描画（%s）", (_label, bind) => {
  function setup() {
    const { map, handle } = createRecordingMap();
    return { handle, drawing: bind(map) };
  }

  it("表示ONの状態は、途中で隠していても最後に見えている", () => {
    const { handle, drawing } = setup();

    drawing.showRoutes([route("a")], "a");
    drawing.hideRoutes();
    drawing.showRoutes([route("a")], "a");

    expect(handle.layer(ROUTES_LAYER_ID)?.visibility).toBe("visible");
    expect(handle.layer(ROUTES_HIT_LAYER_ID)?.visibility).toBe("visible");
  });

  // 矢印は選択中候補の色分け線より上に出る。**どちらを先に出しても同じ重なりになること**が
  // 要求で、いまの実装が持つ「後から寄せ直す」手当ては要求ではない。
  it.each([
    ["選択中の候補が先", true],
    ["区間の色分けが先", false],
  ])("%s でも、重なりは 縁取り→色分け線→当たり判定→矢印 になる", (_order, selectedFirst) => {
    const { handle, drawing } = setup();

    if (selectedFirst) {
      drawing.showSelected([route("a")], "a");
      drawing.showDetail([segment()], MODE, []);
    } else {
      drawing.showDetail([segment()], MODE, []);
      drawing.showSelected([route("a")], "a");
    }

    const order = handle.layerOrder();
    const at = (id: string) => order.indexOf(id);
    expect(at(DETAIL_CASING_LAYER_ID)).toBeLessThan(at(DETAIL_LAYER_ID));
    expect(at(DETAIL_LAYER_ID)).toBeLessThan(at(ROUTE_ARROW_HALO_LAYER_ID));
    expect(at(DETAIL_HIT_LAYER_ID)).toBeLessThan(at(ROUTE_ARROW_HALO_LAYER_ID));
    expect(at(ROUTE_ARROW_HALO_LAYER_ID)).toBeLessThan(at(ROUTE_ARROW_LAYER_ID));
  });

  it("選択中候補のハローは、候補線より下にある", () => {
    const { handle, drawing } = setup();

    drawing.showRoutes([route("a")], "a");
    drawing.showSelected([route("a")], "a");

    const order = handle.layerOrder();
    expect(order.indexOf(OUTLINE_LAYER_ID)).toBeLessThan(order.indexOf(ROUTES_LAYER_ID));
  });

  it("比較スロットは、区間の色分けがあればその下にある", () => {
    const { handle, drawing } = setup();

    drawing.showDetail([segment()], MODE, []);
    drawing.showSlots([slot()]);

    const order = handle.layerOrder();
    expect(order.indexOf(SLOTS_LAYER_ID)).toBeLessThan(order.indexOf(DETAIL_LAYER_ID));
  });

  it("比較スロットは、区間の色分けが無くても出る", () => {
    const { handle, drawing } = setup();

    drawing.showSlots([slot()]);

    expect(handle.layerOrder()).toContain(SLOTS_LAYER_ID);
  });

  // 隠した段は、線だけでなく縁取り・当たり判定からも消える（縁だけが残らない・押せない）。
  it("凡例で段を隠すと、色分け線・縁取り・当たり判定の絞り込みが揃う", () => {
    const { handle, drawing } = setup();

    drawing.showDetail([segment()], MODE, []);
    drawing.showDetail([segment()], MODE, ["step-1"]);

    const filters = [DETAIL_LAYER_ID, DETAIL_CASING_LAYER_ID, DETAIL_HIT_LAYER_ID].map(
      (id) => handle.layer(id)?.filter,
    );
    expect(filters[0]).toBeDefined();
    expect(filters[1]).toEqual(filters[0]);
    expect(filters[2]).toEqual(filters[0]);
  });

  it("モードを切り替えると、色分け線の色式が入れ替わる", () => {
    const { handle, drawing } = setup();
    const other = { ...MODE, id: "other", colorExpression: ["literal", "#dc2626"] } as unknown as RouteStyleMode;

    drawing.showDetail([segment()], MODE, []);
    drawing.showDetail([segment()], other, []);

    expect(handle.layer(DETAIL_LAYER_ID)?.paint["line-color"]).toEqual(other.colorExpression);
  });

  // スタイルを差し替えると、このアプリが足したものは全部消える。同じ状態を伝え直せば戻る。
  it("スタイルを差し替えても、同じ状態を伝え直せば元の重なりへ戻る", () => {
    const { handle, drawing } = setup();
    const showAll = () => {
      drawing.showRoutes([route("a")], "a", true);
      drawing.showSelected([route("a")], "a");
      drawing.showDetail([segment()], MODE, []);
    };
    showAll();
    const before = handle.layerOrder();

    handle.dropEverything();
    showAll();

    expect(handle.layerOrder()).toEqual(before);
  });
});
