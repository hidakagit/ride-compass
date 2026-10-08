// @vitest-environment node
/** ルートの描画が満たすべき**結果**。実装が入れ替わっても、この期待値は変わらない。
 *
 * 書くのは「どの呼び出しが出たか」ではなく「最後にどうなっているか」——呼び出しの形で書くと、
 * そのときの実装が持つ手当て（作成順を後から揃える・毎回表示を明示する）を、次の実装にも
 * 要求することになる。
 *
 * ここで見ないもの:
 * - ルートのレイヤーの重なり順（縁取り→色分け線→当たり判定→矢印・ハローは候補線の下） →
 *   `groups/routes.ts`の宣言の並びそのもの（testing.md「そのテストは要るか」の1問目の「並びそのもので順序を表す」）。
 *   同じ段の中を宣言の順で載せ、届く順によらないことは`applyMapScene.test.ts`が見る
 */
import { describe, expect, it } from "vitest";

import { createRecordingMap } from "@/testing/mapTrace/recordingMap";
import { applyMapScene } from "@/features/map/scene/applyMapScene";
import { EMPTY_MAP_SCENE, type MapScene } from "@/features/map/scene/mapScene";
import { routeGroup, type RoutePath, type RouteState } from "@/features/map/scene/groups/routes";
import { composeScene } from "@/features/map/scene/mapSceneGroups";
import { sceneLayerId } from "@/features/map/scene/sceneBuilders";

type RoutePathShape = RouteState["segments"][number];

const NO_ROUTES: RouteState = {
  visible: true,
  candidates: [],
  selectedRouteId: null,
  segments: [],
  segmentColor: "#16a34a",
  spliceBands: [],
  composite: null,
  arrowIconImage: "arrow",
};

const DECLARED_LAYERS = routeGroup.build(NO_ROUTES).layers;

/** 役割からレイヤーidを引く。**ソース名を書き写さない**——ソース名は宣言する側が決めるため、
 * 宣言のソース名を本番と同じ規則に通す。外で綴ると、綴りを変えたときにここだけ古い綴りで残る。 */
function routeSceneLayerId(role: string): string {
  const entry = DECLARED_LAYERS.find((candidate) => candidate.role === role);
  if (entry === undefined) throw new Error(`役割${role}のレイヤーが宣言に無い`);
  return sceneLayerId(entry.source, entry.role);
}

const PATH: RoutePath = [
  [139.7, 35.6],
  [139.71, 35.61],
];

const SEGMENT: RoutePathShape = { path: PATH, properties: { osm_way_id: 1 } };

/** 画面の状態を、届いた順に地図へ伝える。**実装が入れ替わったら、この束ね方だけを差し替える**
 * （期待値の側は動かさない）。 */
function bindCurrentImplementation(map: unknown) {
  let state = NO_ROUTES;
  let previous: MapScene = EMPTY_MAP_SCENE;
  return (next: Partial<RouteState>) => {
    state = { ...state, ...next };
    const scene = composeScene([routeGroup], state);
    applyMapScene(map as never, { scene, previous, basemapAnchors: { roads: undefined, labels: undefined } });
    previous = scene;
  };
}

describe("ルートの描画", () => {
  // 3枚のどれかだけが絞られると、隠した段に縁取りだけが残るか、見えない段を押せてしまう。
  it("凡例で段を隠すと、区間の縁取り・色分け線・当たり判定が同じ段を隠す", () => {
    const { map, handle } = createRecordingMap();
    const tell = bindCurrentImplementation(map);
    const filter = ["!=", ["get", "band"], "hard"] as RouteState["hiddenBandFilter"];

    tell({ segments: [SEGMENT] });
    tell({ hiddenBandFilter: filter });

    for (const role of ["detailCasing", "detailLine", "detailHit"]) {
      expect(handle.layer(routeSceneLayerId(role))?.filter).toEqual(filter);
    }
  });
});
