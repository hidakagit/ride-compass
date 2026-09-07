// 改善計画T559: 風の矢印（gridMark）の縁取り層が1つも配置されない問題（別レイヤーの
// 衝突落ち）の回帰テスト。ensureDynamicWeatherLayerがgridMarkを1層（icon-halo-*で
// 縁取り表現）だけ作ることを確認する。mark.createIcon()（windArrowIcon.ts）がCanvas 2D
// （document.createElement("canvas")）に依存するため、既定のDOM環境のままにする
// （このファイルはvitest-environmentディレクティブを持たない）。
import { describe, expect, it } from "vitest";
import { applyDynamicWeatherState, DYNAMIC_WEATHER_RENDERERS, dynamicWeatherIds, ensureDynamicWeatherLayer } from "./MapView";

// MapView.layerOps.test.ts等と同じ「実際のMapLibre Mapが必要とするメソッドだけを
// 持つフェイク」パターン。ensureDynamicWeatherLayerが読むメソッドのみ実装する。
function fakeMap() {
  const addLayerCalls: { id: string; type: string; paint?: Record<string, unknown> }[] = [];
  const sources = new Set<string>();
  const images = new Set<string>();
  return {
    __rcStyleReady: true,
    addLayerCalls,
    getLayer: () => undefined,
    getSource: (id: string) => (sources.has(id) ? {} : undefined),
    addSource: (id: string) => sources.add(id),
    hasImage: (id: string) => images.has(id),
    addImage: (id: string) => images.add(id),
    addLayer: (spec: { id: string; type: string; paint?: Record<string, unknown> }) => addLayerCalls.push(spec),
  };
}

describe("ensureDynamicWeatherLayer（gridMark、改善計画T559）", () => {
  it("windVector.arrow（gridMark）はレイヤーを1つだけ作る（縁取り専用の別レイヤーを持たない）", () => {
    const map = fakeMap();

    ensureDynamicWeatherLayer(map as never, "windVector", DYNAMIC_WEATHER_RENDERERS.windVector);

    const { layerId } = dynamicWeatherIds("windVector", "arrow", "mark");
    const markLayers = map.addLayerCalls.filter((l) => l.id.startsWith("region-dynamic-weather-windVector-arrow-mark"));
    expect(markLayers.map((l) => l.id)).toEqual([layerId]);
  });

  it("gridMarkの唯一のレイヤーがicon-halo-color/icon-halo-widthを持つ（縁取りは主層のpaintで表現する）", () => {
    const map = fakeMap();

    ensureDynamicWeatherLayer(map as never, "windVector", DYNAMIC_WEATHER_RENDERERS.windVector);

    const { layerId } = dynamicWeatherIds("windVector", "arrow", "mark");
    const layer = map.addLayerCalls.find((l) => l.id === layerId);
    expect(layer?.paint?.["icon-halo-color"]).toBeTruthy();
    expect(layer?.paint?.["icon-halo-width"]).toBeGreaterThan(0);
  });
});

// ユーザー報告「zoom11ぐらい、画面が重すぎる」の調査で発覚した回帰テスト。
// applyDynamicWeatherStateを呼ぶeffectの依存はdynamicWeatherオブジェクト全体のため、
// 風・雷等いずれか1要素が更新されるだけでも全グループぶん再実行される。tileUrlTemplateが
// 変化していないソースまでsetTilesで巻き添えに再読み込みさせない（ラスタは特にPNGデコード・
// GPUテクスチャアップロードのコストが大きい）ことを確認する。
describe("applyDynamicWeatherState（setTilesの冗長呼び出し防止）", () => {
  function fakeMapWithRasterSource(sourceId: string) {
    const setTilesCalls: string[][] = [];
    const source = { setTiles: (tiles: string[]) => setTilesCalls.push(tiles) };
    const map = {
      __rcStyleReady: true,
      getLayer: () => ({}),
      setLayoutProperty: () => {},
      setPaintProperty: () => {},
      getSource: (id: string) => (id === sourceId ? source : undefined),
      addSource: () => {},
      addLayer: () => {},
      hasImage: () => true,
      addImage: () => {},
    };
    return { map, setTilesCalls };
  }

  it("tileUrlTemplateが変わらない限りsetTilesは1回しか呼ばれない", () => {
    const { sourceId } = dynamicWeatherIds("disaster", "heavyRain", "raster");
    const { map, setTilesCalls } = fakeMapWithRasterSource(sourceId);
    const groupState = {
      heavyRain: { visible: true, payload: { kind: "rasterTile" as const, tileUrlTemplate: "https://example.com/a.png" } },
    };

    applyDynamicWeatherState(map as never, "disaster", DYNAMIC_WEATHER_RENDERERS.disaster, groupState);
    applyDynamicWeatherState(map as never, "disaster", DYNAMIC_WEATHER_RENDERERS.disaster, groupState);
    applyDynamicWeatherState(map as never, "disaster", DYNAMIC_WEATHER_RENDERERS.disaster, { ...groupState });

    // jmatile://スキームが付く（jmaTileProtocol.tsが在否インデックスで要求を間引くため）。
    expect(setTilesCalls).toEqual([["jmatile://https://example.com/a.png"]]);
  });

  it("tileUrlTemplateが変わればsetTilesが再度呼ばれる", () => {
    const { sourceId } = dynamicWeatherIds("disaster", "heavyRain", "raster");
    const { map, setTilesCalls } = fakeMapWithRasterSource(sourceId);

    applyDynamicWeatherState(map as never, "disaster", DYNAMIC_WEATHER_RENDERERS.disaster, {
      heavyRain: { visible: true, payload: { kind: "rasterTile", tileUrlTemplate: "https://example.com/a.png" } },
    });
    applyDynamicWeatherState(map as never, "disaster", DYNAMIC_WEATHER_RENDERERS.disaster, {
      heavyRain: { visible: true, payload: { kind: "rasterTile", tileUrlTemplate: "https://example.com/b.png" } },
    });

    expect(setTilesCalls).toEqual([
      ["jmatile://https://example.com/a.png"],
      ["jmatile://https://example.com/b.png"],
    ]);
  });

  it("gridMark（GeoJSONSource）も内容が変わらない限りsetDataは1回しか呼ばれない", () => {
    const { sourceId } = dynamicWeatherIds("windVector", "arrow", "mark");
    const setDataCalls: unknown[] = [];
    const source = { setData: (data: unknown) => setDataCalls.push(data) };
    const map = {
      __rcStyleReady: true,
      getLayer: () => ({}),
      setLayoutProperty: () => {},
      setPaintProperty: () => {},
      getSource: (id: string) => (id === sourceId ? source : undefined),
      addSource: () => {},
      addLayer: () => {},
      hasImage: () => true,
      addImage: () => {},
    };
    const emptyFeatureCollection = (): GeoJSON.FeatureCollection => ({ type: "FeatureCollection", features: [] });

    applyDynamicWeatherState(map as never, "windVector", DYNAMIC_WEATHER_RENDERERS.windVector, {
      arrow: { visible: true, payload: { kind: "gridMark", geojson: emptyFeatureCollection() } },
    });
    // 内容が同じでも都度新しいオブジェクト参照になるケース（payload計算のuseMemoが
    // 再実行された想定）を再現する。
    applyDynamicWeatherState(map as never, "windVector", DYNAMIC_WEATHER_RENDERERS.windVector, {
      arrow: { visible: true, payload: { kind: "gridMark", geojson: emptyFeatureCollection() } },
    });

    expect(setDataCalls).toHaveLength(1);
  });
});
