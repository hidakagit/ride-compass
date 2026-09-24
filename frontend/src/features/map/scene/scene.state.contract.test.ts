// @vitest-environment node
/** 画面の状態を地図へ伝えたとき、**最後にどうなっているか**。
 *
 * 入口は本番と同じ`sceneInputsFrom`→`buildMapScene`→`applyScene`の1本で、面・道路の線・点・
 * 評価軸・気象・ルートのすべてがここを通る。
 */
import { validateStyleMin } from "@maplibre/maplibre-gl-style-spec";
import { beforeEach, describe, expect, it } from "vitest";

import { setTileVersions } from "@/services/regionApi";
import { createRecordingMap } from "@/testing/mapTrace/recordingMap";
import { catalogAxis } from "@/lib/mapDisplay/__fixtures__/catalogAxes";
import { dedicatedWayValueAxesFromCatalogAxes, rampAxesFromCatalogAxes } from "@/lib/mapDisplay/axisLayers";
import { AREA_SOURCE_ID } from "@/features/map/scene/groups/areaRasters";
import { POINT_LAYERS, pointSourceId } from "@/features/map/scene/groups/points";
import { ROAD_LINE_SOURCE_ID, ROAD_TRACKS } from "@/features/map/scene/groups/roadLines";
import { pointLegendAxes, roadLegendAxes } from "@/features/map/scene/legends";
import { LEGEND_NO_DATA_KEY, legendBandKey } from "@/lib/mapDisplay/mapColorLegend";
import { applyScene, sceneInputsFrom } from "@/features/map/scene/applyToMap";
import { sceneState, type SceneState, type SceneStateOverrides } from "@/features/map/scene/__fixtures__/sceneState";
import { buildMapScene } from "@/features/map/scene/buildScene";
import { sceneLayerId } from "@/features/map/scene/sceneBuilders";
import { mapDisplay } from "@/types/generated/mapDisplay";

const RAMP_AXES = rampAxesFromCatalogAxes([
  catalogAxis({
    axis_id: "ramp",
    display: { tile_inputs: [{ property: "v", weight: 1, has_unknown_fallback: true }], thresholds: [50] },
  }),
]);
const DEDICATED_AXES = dedicatedWayValueAxesFromCatalogAxes([
  catalogAxis({ axis_id: "ded1", dedicated_way_value_layer: true }),
  catalogAxis({ axis_id: "ded2", dedicated_way_value_layer: true }),
]);

type State = SceneState;
const CATALOG = { rampAxes: RAMP_AXES, dedicatedAxes: DEDICATED_AXES };

/** 表示ONのレイヤーだけを持つ状態。 */
function shown(layerVisibility: Record<string, boolean>, look: SceneStateOverrides["look"] = {}) {
  return sceneState({ catalog: CATALOG, look: { ...look, layerVisibility } });
}

// レイヤーidは**ソース名＋役割**で決まる。綴りは`sceneLayerId`からしか作らない
// ——ここで組み立て直すと、規則を変えたときテストだけが古い綴りのまま残る。
const areaLayerId = (role: keyof typeof AREA_SOURCE_ID) => sceneLayerId(AREA_SOURCE_ID[role], role);
const roadLayerId = (role: string) => sceneLayerId(ROAD_LINE_SOURCE_ID, role);
const axisLayerId = (role: string) => sceneLayerId(ROAD_LINE_SOURCE_ID, role);
const pointLayerId = (role: string) =>
  sceneLayerId(pointSourceId(POINT_LAYERS.find((layer) => layer.attr_id === role)!.tile_kind), role);

const READY_VERSIONS = { road_surface: "1-test", poi: "1-test", accident: "1-test" };

/** 作り直さずに伝える経路（画面の状態が変わるたびに通るのはこちら）。 */
function show(map: unknown, state: State) {
  applyScene(map as never, buildMapScene(sceneInputsFrom(state)));
}

/** 空から作り直す経路（スタイルを差し替えた後に通るのはこちら）。 */
function rebuild(map: unknown, state: State) {
  applyScene(map as never, buildMapScene(sceneInputsFrom(state)), { reset: true });
}

describe("状態を地図へ伝えた結果", () => {
  beforeEach(() => {
    setTileVersions(READY_VERSIONS);
  });

  describe("面（標高図・土地被覆・起伏）", () => {
    it("表示ONにしたものだけが見えている", () => {
      const { map, handle } = createRecordingMap();

      rebuild(map as never, shown({ elevation: true, landcover: false, hillshade: false }));

      expect(handle.layer(areaLayerId("elevation"))?.visibility).toBe("visible");
      expect(handle.layer(areaLayerId("landcover"))?.visibility).toBe("none");
      expect(handle.layer(areaLayerId("hillshade"))?.visibility).toBe("none");
    });

    it("面は、道路の線より背面にある", () => {
      const { map, handle } = createRecordingMap();

      rebuild(map as never, shown({ elevation: true, surface: true, tunnel: true }));

      const order = handle.layerOrder();
      expect(order.indexOf(areaLayerId("elevation"))).toBeLessThan(order.indexOf(roadLayerId("tunnel")));
    });
  });

  describe("道路の線", () => {
    it("タイル世代が無い間は、道路のソースを作らない", () => {
      setTileVersions({});
      const { map, handle } = createRecordingMap();

      rebuild(map as never, shown({ surface: true }));

      expect(handle.sources()).not.toContain(ROAD_LINE_SOURCE_ID);
    });

    it("世代が届いた後に同じ状態を伝えると、道路の線が見えている", () => {
      setTileVersions({});
      const { map, handle } = createRecordingMap();
      const state = shown({ surface: true });
      rebuild(map as never, state);

      setTileVersions(READY_VERSIONS);
      rebuild(map as never, state);

      expect(handle.sources()).toContain(ROAD_LINE_SOURCE_ID);
      expect(handle.layer(roadLayerId("surface"))?.visibility).toBe("visible");
    });

    // 同じ道へ複数の線を重ねると後から描いた方が隠す。ON中の本数から対称に割り付ける。
    it("路面と道路種別を同時に出すと、線が左右へ分かれる", () => {
      const { map, handle } = createRecordingMap();

      rebuild(map as never, shown({ surface: true, highway: true }));

      const offsets = ROAD_TRACKS.map((track) => handle.layer(roadLayerId(track.attr_id))?.paint["line-offset"]).filter(
        (value) => value !== undefined,
      );
      expect(new Set(offsets).size).toBeGreaterThan(1);
      expect(offsets).toContain(0);
    });

    it("凡例で隠した分類は、その線から落ちる", () => {
      const { map, handle } = createRecordingMap();

      rebuild(map as never, shown({ surface: true }, { hiddenLegendKeys: { surface: ["asphalt"] } }));

      expect(handle.layer(roadLayerId("surface"))?.filter).toBeDefined();
    });
  });

  describe("点（事故・停止要因POI・補給休憩POI）", () => {
    it("停止要因と補給は、同じソースの別レイヤーとして出る", () => {
      const { map, handle } = createRecordingMap();

      rebuild(map as never, shown({ stop_poi: true, supply_poi: true }));

      const stop = handle.layer(pointLayerId("stop_poi"));
      const supply = handle.layer(pointLayerId("supply_poi"));
      expect(stop?.visibility).toBe("visible");
      expect(supply?.visibility).toBe("visible");
      expect(stop?.source).toBe(supply?.source);
      expect(stop?.id).not.toBe(supply?.id);
    });

    it("同じタイルを分け合う点は、互いの種別を混ぜない", () => {
      const { map, handle } = createRecordingMap();

      rebuild(map as never, shown({ stop_poi: true }));

      // 分ける条件を持たないと、補給の点が停止要因の色で出る。
      expect(handle.layer(pointLayerId("stop_poi"))?.filter).toBeDefined();
    });
  });

  describe("評価軸の線", () => {
    const delivered = (values: Record<string, Record<string, number>>) =>
      new Map(
        Object.entries(values).map(([axisId, byWay]) => [
          axisId,
          { values: new Map(Object.entries(byWay)), loading: false },
        ]),
      );

    it("配られた値は、道路のソースの地物へ載り、塗っている軸の線が見える", () => {
      const { map, handle } = createRecordingMap();
      rebuild(
        map as never,
        shown(
          { surface: true },
          { paintedAxisId: "ded1", dedicatedWayValues: delivered({ ded1: { w1: 3 }, ded2: { w1: 7 } }) },
        ),
      );

      expect(handle.featureState(ROAD_LINE_SOURCE_ID, "w1")).toEqual({ ded1Value: 3, ded2Value: 7 });
      expect(handle.layer(axisLayerId("ded1"))?.visibility).toBe("visible");
      expect(handle.layer(axisLayerId("ded2"))?.visibility).toBe("none");
    });

    it("片方の軸の値が来なくなっても、もう片方の値は残る", () => {
      const { map, handle } = createRecordingMap();
      show(
        map,
        shown({}, { paintedAxisId: "ded1", dedicatedWayValues: delivered({ ded1: { w1: 3 }, ded2: { w1: 7 } }) }),
      );

      show(map, shown({}, { paintedAxisId: "ded2", dedicatedWayValues: delivered({ ded2: { w1: 7 } }) }));

      expect(handle.featureState(ROAD_LINE_SOURCE_ID, "w1")).toEqual({ ded2Value: 7 });
    });
  });
});

describe("レイヤーを横断する要求", () => {
  const EMPTY_GEOJSON: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

  /** 宣言された描き方に合う中身を、全要素ぶん作る。**名指ししない**——母集団は源泉の
   * 宣言（生成物）なので、backendが要素を増やせばそのまま対象になる。 */
  function everyWeatherGroupState(): Record<string, Record<string, unknown>> {
    const groups: Record<string, Record<string, unknown>> = {};
    for (const element of mapDisplay.weatherElements) {
      const payload =
        element.kind === "rasterTile"
          ? { kind: "rasterTile", tileUrlTemplate: "https://example.test/{z}/{x}/{y}.png" }
          : element.kind === "vectorTile"
            ? { kind: "vectorTile", tileUrlTemplate: "https://example.test/{z}/{x}/{y}.pbf" }
            : { kind: element.kind, geojson: EMPTY_GEOJSON };
      groups[element.group] = { ...groups[element.group], [element.source]: { visible: true, payload } };
    }
    return groups;
  }

  /** 出せるものを全部出した状態。チップのidは各グループの宣言から取る。 */
  function everythingVisible(): State {
    const visibility: Record<string, boolean> = {};
    for (const track of ROAD_TRACKS) visibility[track.attr_id] = true;
    for (const layer of POINT_LAYERS) visibility[layer.attr_id] = true;
    for (const role of ["elevation", "landcover", "hillshade"]) visibility[role] = true;
    visibility.route = true;
    const mode = { id: "difficulty", label: "難易度", colorExpression: ["literal", "#16a34a"], legend: [] };
    const candidate = {
      id: "a",
      geometry: {
        type: "LineString",
        coordinates: [
          [139.7, 35.6],
          [139.71, 35.61],
        ],
      },
      segments: [
        {
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
        },
      ],
    };
    // 絞り込みの式も検証の対象にするため、凡例の先頭の行と「値なし」を隠しておく。
    const firstKeyHidden = (axes: readonly { axisId: string; entries: readonly { key: string }[] }[]) =>
      Object.fromEntries(axes.map((axis) => [axis.axisId, axis.entries.slice(0, 1).map((entry) => entry.key)]));
    const bandsHidden = [legendBandKey(0), LEGEND_NO_DATA_KEY];
    // 評価軸は一度に1本しか塗らないが、どの軸のレイヤーも常に宣言され、塗るかは表示だけが変わる。
    return sceneState({
      catalog: { ...CATALOG, routeStyleModes: [mode] as never },
      look: {
        layerVisibility: visibility,
        paintedAxisId: RAMP_AXES[0].axisId,
        lens: "difficulty",
        hiddenLegendKeys: {
          ...firstKeyHidden(roadLegendAxes()),
          ...firstKeyHidden(pointLegendAxes()),
          ...Object.fromEntries([...RAMP_AXES, ...DEDICATED_AXES].map((axis) => [axis.axisId, bandsHidden])),
        },
        dynamicWeather: everyWeatherGroupState() as never,
      },
      routes: [candidate] as never,
      selectedRouteId: "a",
      experimentSlots: [{ color: "#16a34a", topCandidate: candidate }] as never,
    });
  }

  // 「差し替え後に戻るか」はレイヤーごとの性質ではないので、家族ごとに繰り返さず
  // **全部を載せた状態で1回**見る。新しいレイヤーが増えればそのまま対象になる。
  it("スタイルを差し替えても、同じ状態を伝え直せば元へ戻る", () => {
    const { map, handle } = createRecordingMap();
    const state = everythingVisible();
    rebuild(map as never, state);
    const before = handle.layerOrder();
    // 空振りしていないこと（載っていなければ比較は常に通る）。
    expect(before.length).toBeGreaterThan(mapDisplay.weatherElements.length);

    handle.dropEverything();
    rebuild(map as never, state);

    expect(handle.layerOrder()).toEqual(before);
  });

  // 式の誤りは例外にならず、そのレイヤーだけが黙って描かれない（代役地図は式を検証しない）。
  // 出せるものを全部出した状態の宣言を、MapLibreと同じ版のstyle検証へ通す。
  it("地図へ渡すソースとレイヤーは、すべてMapLibreのstyle検証を通る", () => {
    const { map, handle } = createRecordingMap();
    rebuild(map, everythingVisible());
    const sources = Object.fromEntries(
      handle.trace.filter((entry) => entry.call === "addSource").map((entry) => [entry.args[0], entry.args[1]]),
    );
    const layers = handle.trace.filter((entry) => entry.call === "addLayer").map((entry) => entry.args[2]);
    // 空振りしていないこと（載っていなければ検証は常に通る）。
    expect(layers.length).toBeGreaterThan(mapDisplay.weatherElements.length);

    const errors = validateStyleMin({
      version: 8,
      glyphs: "https://example.test/{fontstack}/{range}.pbf",
      sources,
      layers,
    } as never);

    expect(errors.map((error) => error.message)).toEqual([]);
  });

  // 世代が届く前にソースを作ると、世代の違う中身がブラウザのキャッシュへ載って以後ずっと残る。
  it("世代を要るソースは、世代が届くまで1つも作られない", () => {
    const state = everythingVisible();

    setTileVersions(READY_VERSIONS);
    const ready = createRecordingMap();
    rebuild(ready.map as never, state);

    setTileVersions({});
    const pending = createRecordingMap();
    rebuild(pending.map as never, state);

    const gated = ready.handle.sources().filter((id) => !pending.handle.sources().includes(id));
    // 世代で守られているソースが実際にあること（0件なら、この検査は何も見ていない）。
    expect(gated.length).toBeGreaterThan(0);
    expect(gated).toContain(ROAD_LINE_SOURCE_ID);
  });

  it("世代が届いた後に同じ状態を伝えると、世代を要るソースが揃う", () => {
    setTileVersions({});
    const { map, handle } = createRecordingMap();
    const state = everythingVisible();
    rebuild(map as never, state);

    setTileVersions(READY_VERSIONS);
    rebuild(map as never, state);

    expect(handle.sources()).toContain(ROAD_LINE_SOURCE_ID);
  });
});
