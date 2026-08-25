import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AxisCatalogResponse } from "@/types/route";

// デッドコード監査（2026-08-25）回帰テスト: layerVisibility永続化ホワイトリストの静的固定
// バグ修正。以前はuseStoredStateのdeserializeが常にDEFAULT_LAYER_VISIBILITY（ビルド時
// 静的7軸ぶんのキー）だけを走査していたため、軸スタジオで新規公開されたGUI作成軸
// （axis:xxx）のON/OFF保存値が復元時に黙って捨てられていた。ここでは、GUI作成軸を含む
// カタログをGET /api/axis-catalogのモックで返し、localStorageにその軸をONにした保存値を
// 仕込んだ状態でHomeをマウントし、カタログ取得完了後にON状態が復元されることを確認する。
//
// page.tsxは地図・位置情報・天候等の重いコンポーネント/フックを多数使うため、本テストの
// 関心事（layerVisibilityの永続化・復元）に無関係なものはすべて軽量スタブへ差し替える。
// MapOverlayControlsだけは、実際に組み立てられたlayers（id・on）をそのまま可視化する
// スタブにして、テストからlayerVisibilityの実効値を検証できるようにする。

vi.mock("@/components/Map/MapView", () => ({ default: () => null }));
vi.mock("@/components/LocationControl/LocationControl", () => ({ default: () => null }));
vi.mock("@/components/MapLayersPanel/MapLayersPanel", () => ({ default: () => null }));
vi.mock("@/components/RouteForm/RouteForm", () => ({ default: () => null }));
vi.mock("@/components/RouteList/RouteList", () => ({ default: () => null }));
vi.mock("@/components/WeatherPanel/WeatherPanel", () => ({ default: () => null }));
vi.mock("@/components/WarningBadge/WarningBadge", () => ({ default: () => null }));
vi.mock("@/components/DynamicLayerTimeSlider/DynamicLayerTimeSlider", () => ({ default: () => null }));
vi.mock("@/components/ComparisonPanel/ComparisonPanel", () => ({ default: () => null }));
vi.mock("@/components/DebugConsole/DebugConsole", () => ({ default: () => null }));

vi.mock("@/components/RouteSettingsPanel/RouteSettingsPanel", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/RouteSettingsPanel/RouteSettingsPanel")>();
  return { ...actual, default: () => null };
});

// 実際に組み立てられたoverlayLayers（id・on）をテストから読み取れるようにするスタブ。
vi.mock("@/components/MapOverlayControls/MapOverlayControls", () => ({
  default: (props: { layers: Array<{ id: string; on: boolean }> }) => (
    <div data-testid="overlay-layers">{JSON.stringify(props.layers.map((l) => [l.id, l.on]))}</div>
  ),
}));

vi.mock("@/hooks/useIsMobile", () => ({ useIsMobile: () => false }));
vi.mock("@/hooks/useResearchMode", () => ({ useResearchEnabled: () => false }));
vi.mock("@/hooks/useDebugLog", () => ({ useDebugEnabled: () => false }));

vi.mock("@/hooks/useLocation", () => ({
  useLocation: () => ({
    location: { latitude: 35.7597, longitude: 139.7387 },
    locationSource: "default",
    locationReady: true,
    locating: false,
    locateError: null,
    handleLocateMe: vi.fn(),
  }),
}));

vi.mock("@/services/weatherApi", () => ({
  getCurrentWeather: vi.fn().mockRejectedValue(new Error("mock: unused in this test")),
  getFloodForecasts: vi.fn().mockRejectedValue(new Error("mock: unused in this test")),
  getWbgtStatus: vi.fn().mockRejectedValue(new Error("mock: unused in this test")),
  getWeatherWarnings: vi.fn().mockRejectedValue(new Error("mock: unused in this test")),
}));

vi.mock("@/services/axisCatalogApi", () => ({
  getAxisCatalog: vi.fn(),
}));

import { getAxisCatalog } from "@/services/axisCatalogApi";
import Home from "./page";

const LAYER_VISIBILITY_STORAGE_KEY = "ridecompass:layer-visibility";

// 軸スタジオで新規公開されたGUI作成軸を1つだけ含むカタログ（kind="ramp"なので
// mapLayers.ts: buildMapLayersが二次軸rampレイヤーとして拾い、axis:gui_created_axisという
// レイヤーIDになる、axisLayers.ts: axisMapLayerId参照）。
function catalogWithGuiCreatedAxis(): AxisCatalogResponse {
  return {
    axes: [
      {
        axis_id: "gui_created_axis",
        label: "GUI作成軸",
        description: "",
        category: "動的",
        default_weight: 0.1,
        display: {
          kind: "ramp",
          label: "GUI作成軸",
          category: "trafficSafety",
          tile_inputs: [],
          thresholds: [1, 2, 3],
          unit: "",
          note: "",
        },
        primary_attribute_ids: [],
        icon_id: null,
        chip_label: null,
        panel_hint: null,
        proxy_hint: null,
      },
    ],
  };
}

describe("Home（app/page.tsx） layerVisibilityの永続化", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    window.localStorage.clear();
    vi.mocked(getAxisCatalog).mockReset();
  });

  it("GUI作成軸をONにした保存値は、カタログ取得完了後に復元される（実バグ修正の回帰テスト）", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogWithGuiCreatedAxis());
    // 「GUI作成軸をONにしてリロードした」状態を模した保存値。
    window.localStorage.setItem(
      LAYER_VISIBILITY_STORAGE_KEY,
      JSON.stringify({ route: true, "axis:gui_created_axis": true }),
    );

    render(<Home />);

    // カタログ取得（axisCatalog.loaded===true）完了後、layerVisibilityの復元effectが
    // 実行時カタログ由来のキー集合で再実行され、axis:gui_created_axisがONとして
    // 復元される（このJSONに現れる時点でmapLayersにも含まれていることが分かる）。
    await waitFor(() => {
      const text = screen.getByTestId("overlay-layers").textContent ?? "";
      expect(text).toContain('["axis:gui_created_axis",true]');
    });
  });

  it("保存値が無ければGUI作成軸は既定でOFFのまま", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogWithGuiCreatedAxis());

    render(<Home />);

    // 保存値が無い場合、layerVisibilityは初期値（DEFAULT_LAYER_VISIBILITY）のまま変わらない
    // ため、ビルド時静的集合に含まれないaxis:gui_created_axisはキー自体が無い
    // （JSON.stringifyでnullになる=truthyではない）。少なくとも「ONとして復元される」
    // という誤りは起きないことを確認する。
    await waitFor(() => {
      const text = screen.getByTestId("overlay-layers").textContent ?? "";
      expect(text).toContain('"axis:gui_created_axis"');
    });
    const text = screen.getByTestId("overlay-layers").textContent ?? "";
    const layers = JSON.parse(text) as Array<[string, boolean | null]>;
    const guiAxisEntry = layers.find(([id]) => id === "axis:gui_created_axis");
    expect(guiAxisEntry?.[1]).not.toBe(true);
  });
});
