import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { AxisCatalogResponse } from "@/types/route";
import type { MapLayerId, MapLayerVisibility } from "@/components/Map/mapLayers";
import RouteSettingsPanel, { DEFAULT_HARD_FILTERS } from "./RouteSettingsPanel";

// 改善計画T302: unpublishでカタログから軸が消えた場合、RouteSettingsPanelが
// routePreferenceから対応するキーを自動で取り除く（自己修復）ことの回帰テスト。
// これが無いと、unpublish直後に旧設定を保持したブラウザで次のルート生成が
// RoutePreferenceWeightsのキー完全一致検証（backend/app/api/routers/routes.py）で
// 422になる（docs/decisions/t221-axis-registry.md「Stage D拡張3」参照）。
vi.mock("@/services/axisCatalogApi", () => ({
  getAxisCatalog: vi.fn(),
}));

import { getAxisCatalog } from "@/services/axisCatalogApi";
import axisCatalogStatic from "@/types/generated/axis-catalog.json";

// 改善計画T418: 軸ごとの「地図で色分け」トグル（renderMapColorToggle）検証用に、
// display.kindを呼び出し側で選べるよう拡張した（従来は全軸kind="none"固定だった）。
function catalogResponse(
  axisIds: string[],
  kindByAxisId: Record<string, "none" | "ramp"> = {},
): AxisCatalogResponse {
  return {
    axes: axisIds.map((axisId) => {
      const kind = kindByAxisId[axisId] ?? "none";
      return {
        axis_id: axisId,
        label: `ラベル[${axisId}]`,
        description: "",
        category: "観測",
        default_weight: 0.1,
        // 改善計画T308: GET /api/axis-catalogのレスポンスへdisplay/primary_attribute_idsが
        // 必須フィールドとして追加された。改善計画T310でicon_id/chip_label/panel_hintも
        // 同様に必須（値はnull許容）となった。改善計画T318でshow_map_icon（真偽値、
        // null不可）も必須フィールドに加わった。このテストはどれも内容を検証しないため
        // kind="none"・空配列・null・trueで済ませる（kind="ramp"のtile_inputs/thresholdsは
        // renderMapColorToggleがlayerIdの有無しか見ないため空でよい）。
        display: {
          kind,
          label: `ラベル[${axisId}]`,
          category: "trafficSafety",
          tile_inputs: [],
          thresholds: [],
          unit: "",
          note: "",
        },
        primary_attribute_ids: [],
        icon_id: null,
        chip_label: null,
        panel_hint: null,
        show_map_icon: true,
        supports_route_coloring: false,
      };
    }),
    // 改善計画T404: material_runtime_scalesはAxisCatalogResponseの必須フィールド
    // （既定{}だがopenapi-typescriptはdefault付きフィールドをoptionalにしない）。
    material_runtime_scales: {},
  };
}

// 改善計画T418: layerVisibility/onLayerToggle/hasDetailが新規必須propsになったための
// 既定値。個々のテストは必要な値だけ上書きする。
function baseLayerVisibility(): MapLayerVisibility {
  return {
    elevation: false,
    roadType: false,
    roadSurface: false,
    designation: false,
    tunnel: false,
    oneway: false,
    stopPoi: false,
    supplyPoi: false,
    accidents: false,
    route: false,
    precipitationNowcast: false,
    windVector: false,
    windAxis: false,
    thunderNowcast: false,
    tornadoNowcast: false,
    landslideRisk: false,
    heavyRainRisk: false,
    inundationRisk: false,
    linearRainbandRisk: false,
  };
}

function baseNewProps() {
  return {
    layerVisibility: baseLayerVisibility(),
    onLayerToggle: vi.fn() as (id: MapLayerId, on: boolean) => void,
    hasDetail: false,
  };
}

describe("RouteSettingsPanel", () => {
  it("カタログから消えた軸（unpublish後）のキーをroutePreferenceから取り除く", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse(["gradient", "surface_q"]));
    const onRoutePreferenceChange = vi.fn();

    render(
      <RouteSettingsPanel
        hardFilters={DEFAULT_HARD_FILTERS}
        onHardFiltersChange={vi.fn()}
        // "night"は下書きへ戻った(unpublishされた)想定の古いキー。
        routePreference={{ gradient: 0.5, surface_q: 0.3, night: 0.2 }}
        onRoutePreferenceChange={onRoutePreferenceChange}
        overrideEnabled={false}
        onOverrideEnabledChange={vi.fn()}
        {...baseNewProps()}
      />,
    );

    await waitFor(() => expect(onRoutePreferenceChange).toHaveBeenCalled());

    const synced = onRoutePreferenceChange.mock.calls.at(-1)?.[0];
    expect(synced).toEqual({ gradient: 0.5, surface_q: 0.3 });
  });

  it("カタログに新しく現れた軸の既定重みをroutePreferenceへ補う", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse(["gradient", "surface_q"]));
    const onRoutePreferenceChange = vi.fn();

    render(
      <RouteSettingsPanel
        hardFilters={DEFAULT_HARD_FILTERS}
        onHardFiltersChange={vi.fn()}
        routePreference={{ gradient: 0.5 }}
        onRoutePreferenceChange={onRoutePreferenceChange}
        overrideEnabled={false}
        onOverrideEnabledChange={vi.fn()}
        {...baseNewProps()}
      />,
    );

    await waitFor(() => expect(onRoutePreferenceChange).toHaveBeenCalled());

    const synced = onRoutePreferenceChange.mock.calls.at(-1)?.[0];
    expect(synced).toEqual({ gradient: 0.5, surface_q: 0.1 });
  });

  it("routePreferenceがカタログと既に一致している場合は呼び出さない", async () => {
    // マウント直後はフェッチ完了までの一瞬、静的フォールバックカタログ
    // （axis-catalog.json、useAxisCatalog.tsのFALLBACK_CATALOG）がそのまま使われる
    // ため、この初期状態とも一致させておかないと「フェッチ前の一瞬だけ差分が
    // あるから呼ばれる」という別の要因で誤検知する。フォールバックと同じ内容を
    // 返すモックにしておくことで、フェッチ前後どちらの時点でも一致した状態を保つ。
    const staticDefaults = axisCatalogStatic.preference_defaults as Record<string, number>;
    vi.mocked(getAxisCatalog).mockResolvedValue(
      catalogResponse(Object.keys(staticDefaults)),
    );
    const onRoutePreferenceChange = vi.fn();

    render(
      <RouteSettingsPanel
        hardFilters={DEFAULT_HARD_FILTERS}
        onHardFiltersChange={vi.fn()}
        routePreference={staticDefaults}
        onRoutePreferenceChange={onRoutePreferenceChange}
        overrideEnabled={false}
        onOverrideEnabledChange={vi.fn()}
        {...baseNewProps()}
      />,
    );

    // フェッチが解決してeffectが走り切るまで待つ（呼ばれないことの確認のため一呼吸置く）。
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(onRoutePreferenceChange).not.toHaveBeenCalled();
  });

  // 改善計画T418: 軸ごとの「この条件で地図を色分け」トグル（renderMapColorToggle）。
  // 評価軸チップを地図UIから撤去したのに伴い、軸選択・重み設定と同じ行から地図色分けを
  // 起動できるようにした（docs/tasks/T418.md「やること」2.）。
  describe("軸ごとの地図色分けトグル（改善計画T418）", () => {
    it("専用の表示レイヤーを持つ軸（kind=ramp）は色分けトグルが押せ、layerVisibilityに応じたON/OFFをonLayerToggleへ伝える", async () => {
      const user = userEvent.setup();
      vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse(["car_stress"], { car_stress: "ramp" }));
      const onLayerToggle = vi.fn();

      render(
        <RouteSettingsPanel
          hardFilters={DEFAULT_HARD_FILTERS}
          onHardFiltersChange={vi.fn()}
          routePreference={{ car_stress: 0.3 }}
          onRoutePreferenceChange={vi.fn()}
          overrideEnabled={false}
          onOverrideEnabledChange={vi.fn()}
          {...baseNewProps()}
          onLayerToggle={onLayerToggle}
        />,
      );

      const toggle = await screen.findByRole("button", { name: "ラベル[car_stress]で地図を色分け表示" });
      expect(toggle).toHaveAttribute("aria-pressed", "false");

      await user.click(toggle);
      expect(onLayerToggle).toHaveBeenCalledWith("axis:car_stress", true);
    });

    it("専用の表示レイヤーを持たない軸（kind=none、勾配等）は色分けトグルの代わりに非対応の案内が出る", async () => {
      vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse(["gradient"], { gradient: "none" }));

      render(
        <RouteSettingsPanel
          hardFilters={DEFAULT_HARD_FILTERS}
          onHardFiltersChange={vi.fn()}
          routePreference={{ gradient: 0.3 }}
          onRoutePreferenceChange={vi.fn()}
          overrideEnabled={false}
          onOverrideEnabledChange={vi.fn()}
          {...baseNewProps()}
        />,
      );

      await waitFor(() => expect(screen.getByText("地図表示なし")).toBeInTheDocument());
      expect(screen.queryByRole("button", { name: /で地図を色分け表示/ })).not.toBeInTheDocument();
    });

    it("風（wind）はsecondaryAxesに現れない特殊軸だが、windAxisレイヤーへの色分けトグルとして機能する", async () => {
      const user = userEvent.setup();
      // windはbackendのAXIS_DEFINITIONS上category="推定"・show_map_icon=falseで
      // 公開される（secondaryAxes.tsがcategoryではなくshow_map_iconで除外する、
      // axis_definitions_snapshot.json参照）。
      vi.mocked(getAxisCatalog).mockResolvedValue({
        axes: [
          {
            axis_id: "wind",
            label: "風",
            description: "向かい風が弱いほど易しい",
            category: "推定",
            default_weight: 0.26,
            display: { kind: "none", label: "風", category: "weather", tile_inputs: [], thresholds: [], unit: "", note: "" },
            primary_attribute_ids: [],
            icon_id: null,
            chip_label: null,
            panel_hint: null,
            show_map_icon: false,
            supports_route_coloring: true,
          },
        ],
        material_runtime_scales: {},
      });
      const onLayerToggle = vi.fn();

      render(
        <RouteSettingsPanel
          hardFilters={DEFAULT_HARD_FILTERS}
          onHardFiltersChange={vi.fn()}
          routePreference={{ wind: 0.26 }}
          onRoutePreferenceChange={vi.fn()}
          overrideEnabled={false}
          onOverrideEnabledChange={vi.fn()}
          {...baseNewProps()}
          onLayerToggle={onLayerToggle}
        />,
      );

      const toggle = await screen.findByRole("button", { name: "風で地図を色分け表示" });
      await user.click(toggle);
      expect(onLayerToggle).toHaveBeenCalledWith("windAxis", true);
    });

    it("ルート確定後（hasDetail=true）は風の色分けトグルが非対応の案内に切り替わる", async () => {
      vi.mocked(getAxisCatalog).mockResolvedValue({
        axes: [
          {
            axis_id: "wind",
            label: "風",
            description: "向かい風が弱いほど易しい",
            category: "推定",
            default_weight: 0.26,
            display: { kind: "none", label: "風", category: "weather", tile_inputs: [], thresholds: [], unit: "", note: "" },
            primary_attribute_ids: [],
            icon_id: null,
            chip_label: null,
            panel_hint: null,
            show_map_icon: false,
            supports_route_coloring: true,
          },
        ],
        material_runtime_scales: {},
      });

      render(
        <RouteSettingsPanel
          hardFilters={DEFAULT_HARD_FILTERS}
          onHardFiltersChange={vi.fn()}
          routePreference={{ wind: 0.26 }}
          onRoutePreferenceChange={vi.fn()}
          overrideEnabled={false}
          onOverrideEnabledChange={vi.fn()}
          {...baseNewProps()}
          hasDetail
        />,
      );

      await waitFor(() => expect(screen.getByText("地図表示なし")).toBeInTheDocument());
      expect(screen.queryByRole("button", { name: "風で地図を色分け表示" })).not.toBeInTheDocument();
    });
  });
});
