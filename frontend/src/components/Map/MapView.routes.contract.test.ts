// @vitest-environment node
/** ルートの描画が満たすべき挙動。**実装が入れ替わっても、この期待値は変わらない。**
 *
 * 筋書きは[遷移表](../../../../docs/records/tasks/T1001.md)から取っている。
 * 地図へ出る呼び出しは`createRecordingMap`が記録し、順序・重なり・表示状態を見る。
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

function visibilityOf(handle: ReturnType<typeof createRecordingMap>["handle"], id: string) {
  return handle.layer(id)?.visibility;
}

describe("ルートの描画が満たすこと", () => {
  it("隠したあとにもう一度描くと、表示が戻る", () => {
    const { map, handle } = createRecordingMap();
    drawBaseRoutes(map as never, [route("a")], "a");
    hideBaseRoutes(map as never);
    expect(visibilityOf(handle, ROUTES_LAYER_ID)).toBe("none");

    drawBaseRoutes(map as never, [route("a")], "a");

    expect(visibilityOf(handle, ROUTES_LAYER_ID)).toBe("visible");
    expect(visibilityOf(handle, ROUTES_HIT_LAYER_ID)).toBe("visible");
  });

  // 矢印は選択中候補の色分け線より上に出る。作られる順が2通りある（ページ表示直後に矢印、
  // 最初の生成後に色分け線）ため、どちらの順でも同じ重なりへ収束しなければならない。
  it.each([
    ["ハローが先", true],
    ["色分け線が先", false],
  ])("%s でも、色分け線→当たり判定→矢印ハロー→矢印の順になる", (_label, outlineFirst) => {
    const { map, handle } = createRecordingMap();
    const draw = {
      outline: () => drawSelectedOutline(map as never, [route("a")], "a"),
      detail: () => drawDetailSegments(map as never, [segment()], MODE, []),
    };
    if (outlineFirst) {
      draw.outline();
      draw.detail();
    } else {
      draw.detail();
      draw.outline();
    }

    const order = handle.layerOrder();
    const at = (id: string) => order.indexOf(id);
    expect(at(DETAIL_LAYER_ID)).toBeLessThan(at(ROUTE_ARROW_HALO_LAYER_ID));
    expect(at(DETAIL_HIT_LAYER_ID)).toBeLessThan(at(ROUTE_ARROW_HALO_LAYER_ID));
    expect(at(ROUTE_ARROW_HALO_LAYER_ID)).toBeLessThan(at(ROUTE_ARROW_LAYER_ID));
    expect(at(DETAIL_CASING_LAYER_ID)).toBeLessThan(at(DETAIL_LAYER_ID));
  });

  it("選択中候補のハローは、候補線より下へ入る", () => {
    const { map, handle } = createRecordingMap();
    drawBaseRoutes(map as never, [route("a")], "a");
    drawSelectedOutline(map as never, [route("a")], "a");

    const order = handle.layerOrder();
    expect(order.indexOf(OUTLINE_LAYER_ID)).toBeLessThan(order.indexOf(ROUTES_LAYER_ID));
  });

  it("比較スロットは、詳細があればその下・無ければ最前面へ入る", () => {
    const withDetail = createRecordingMap();
    drawDetailSegments(withDetail.map as never, [segment()], MODE, []);
    drawExperimentSlots(withDetail.map as never, [slot()]);
    const order = withDetail.handle.layerOrder();
    expect(order.indexOf("experiment-slots-line")).toBeLessThan(order.indexOf(DETAIL_LAYER_ID));

    const alone = createRecordingMap();
    drawExperimentSlots(alone.map as never, [slot()]);
    expect(alone.handle.layerOrder()).toContain("experiment-slots-line");
  });

  // 色分けのモードと凡例の絞り込みは、レイヤーが既にある状態でも毎回当て直す。
  // 当てないと、モードを切り替えても色が変わらない。
  it("2回目の描画でも、色式と絞り込みを当て直す", () => {
    const { map, handle } = createRecordingMap();
    drawDetailSegments(map as never, [segment()], MODE, []);
    const before = handle.trace.length;

    drawDetailSegments(map as never, [segment()], MODE, ["step-1"]);

    const after = handle.trace.slice(before);
    expect(
      after.filter((entry) => entry.call === "setPaintProperty" && entry.args[0] === DETAIL_LAYER_ID),
    ).toHaveLength(1);
    const filtered = after.filter((entry) => entry.call === "setFilter").map((entry) => entry.args[0]);
    // 縁取り・当たり判定にも同じ絞り込みが要る（隠した段の縁だけが残らない／押せない）。
    expect(filtered).toEqual([DETAIL_LAYER_ID, DETAIL_CASING_LAYER_ID, DETAIL_HIT_LAYER_ID]);
  });

  // スタイルを差し替えると、このアプリが足したものは全部消える。同じ呼び出しで元へ戻せること。
  it("スタイルを差し替えた後、同じ呼び出しで元の重なりへ戻る", () => {
    const { map, handle } = createRecordingMap();
    const drawAll = () => {
      drawBaseRoutes(map as never, [route("a")], "a", true);
      drawSelectedOutline(map as never, [route("a")], "a");
      drawDetailSegments(map as never, [segment()], MODE, []);
    };
    drawAll();
    const before = handle.layerOrder();

    handle.dropEverything();
    drawAll();

    expect(handle.layerOrder()).toEqual(before);
  });
});
