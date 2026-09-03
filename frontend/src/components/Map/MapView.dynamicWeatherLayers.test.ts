// 改善計画T559: 風の矢印（gridMark）の縁取り層が1つも配置されない問題（別レイヤーの
// 衝突落ち）の回帰テスト。ensureDynamicWeatherLayerがgridMarkを1層（icon-halo-*で
// 縁取り表現）だけ作ることを確認する。mark.createIcon()（windArrowIcon.ts）がCanvas 2D
// （document.createElement("canvas")）に依存するため、既定のDOM環境のままにする
// （このファイルはvitest-environmentディレクティブを持たない）。
import { describe, expect, it } from "vitest";
import { DYNAMIC_WEATHER_RENDERERS, dynamicWeatherIds, ensureDynamicWeatherLayer } from "./MapView";

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
